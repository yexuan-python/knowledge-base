from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Callable
from uuid import uuid4

from knowledge_base.shared.callback_delivery import (
    deliver_upload_task_callback,
    load_callback_payload,
    seconds_until,
)
from knowledge_base.shared.http import post_json_text_response


logger = logging.getLogger(__name__)

ATTACHMENT_DELETE_CALLBACK_TYPE = "attachment_delete_completed"
ATTACHMENT_DELETE_CALLBACK_RETRY_DELAYS_SECONDS = (60, 120, 180)


@dataclass(frozen=True)
class AttachmentDeleteDependencies:
    settings: Any
    brands: Any
    brand_knowledge: Any
    brand_products: Any
    brand_full_knowledge: Any
    upload_tasks: Any
    runtime: Any
    spawn_background_task: Callable[[Any], Any]
    build_callback_payload: Callable[..., dict[str, Any]]
    post_callback: Callable[[str, dict[str, Any], float], tuple[int | None, str | None]] | None = None


class AttachmentDeleteWorkflow:
    def __init__(self, dependencies: AttachmentDeleteDependencies) -> None:
        self._deps = dependencies

    @staticmethod
    def parse_json_value(raw: Any, default: Any) -> Any:
        if raw is None:
            return default
        if isinstance(raw, (dict, list)):
            return raw
        if isinstance(raw, str) and raw.strip():
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return default
        return default

    @staticmethod
    def normalize_attachment_entries(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        normalized: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for item in value:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("attachment_name") or "").strip()
            url = str(item.get("url") or item.get("source_url") or "").strip()
            if not name:
                continue
            dedupe_key = (name.casefold(), url)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            entry: dict[str, Any] = {"name": name}
            if url:
                entry["url"] = url
            for key in ("type", "description"):
                text = str(item.get(key) or "").strip()
                if text:
                    entry[key] = text
            normalized.append(entry)
        return normalized

    @staticmethod
    def attachment_matches_deleted_entry(
        attachment: dict[str, Any],
        deleted_entry: dict[str, Any],
    ) -> bool:
        attachment_name = str(attachment.get("name") or "").strip()
        deleted_name = str(deleted_entry.get("name") or "").strip()
        if not attachment_name or attachment_name != deleted_name:
            return False
        deleted_url = str(deleted_entry.get("url") or "").strip()
        if not deleted_url:
            return True
        attachment_url = str(attachment.get("url") or attachment.get("source_url") or "").strip()
        return attachment_url == deleted_url

    def load_brand_knowledge_snapshot(self, *, brand: dict[str, Any]) -> dict[str, Any]:
        brand_id = brand.get("id")
        if brand_id is None or self._deps.brand_knowledge is None:
            return {"basic_info": {}, "attachments": []}
        knowledge_rows = self._deps.brand_knowledge.get_all_brand_knowledge_json(brand_id=int(brand_id))
        knowledge_map = {
            str(row.get("knowledge_type") or "").strip(): self.parse_json_value(row.get("content_json"), None)
            for row in knowledge_rows
            if str(row.get("knowledge_type") or "").strip()
        }
        products: list[dict[str, Any]] = []
        if self._deps.brand_products is not None:
            for product in self._deps.brand_products.get_brand_products(brand_id=int(brand_id)):
                if not isinstance(product, dict):
                    continue
                products.append(
                    {
                        "name": str(product.get("product_name") or product.get("name") or "").strip(),
                        "product_description": product.get("product_description"),
                        "product_website": product.get("product_website"),
                        "product_images": self.parse_json_value(
                            product.get("product_images_json"),
                            product.get("product_images") or [],
                        ),
                        "coverage_regions": self.parse_json_value(
                            product.get("coverage_regions_json"),
                            product.get("coverage_regions") or [],
                        ),
                        "price_info": product.get("price_info"),
                        "product_advantages": product.get("product_advantages"),
                        "target_scenarios": product.get("target_scenarios"),
                        "service_standard": product.get("service_standard"),
                        "service_process": product.get("service_process"),
                        "cases_and_reputation": product.get("cases_and_reputation"),
                        "certification_info": product.get("certification_info"),
                        "core_technology": product.get("core_technology"),
                        "other_info": product.get("other_info"),
                    }
                )
        return {
            "basic_info": {
                "brand_code": brand.get("brand_code"),
                "brand_name": brand.get("brand_name"),
                "brand_alias": brand.get("brand_alias"),
                "brand_logo": brand.get("brand_logo"),
                "website": brand.get("website"),
                "customer_service_hotline": brand.get("customer_service_hotline"),
                "intro": brand.get("intro"),
                "email": brand.get("email"),
                "brand_enterprise_entity": brand.get("brand_enterprise_entity"),
                "business_license_image_path": brand.get("business_license_image_path"),
                "english_name": brand.get("english_name"),
                "official_wechat_account": brand.get("official_wechat_account"),
                "positioning": brand.get("positioning"),
                "advantages": brand.get("advantages"),
                "mission": brand.get("mission"),
                "vision": brand.get("vision"),
                "target_regions": brand.get("target_regions_json"),
                "other_info": brand.get("other_info"),
            },
            "company_profile": knowledge_map.get("company_profile") or knowledge_map.get("company_info") or {},
            "management_team": knowledge_map.get("management_team") or [],
            "competitors": knowledge_map.get("competitors") or [],
            "authority_honors": knowledge_map.get("authority_honors") or knowledge_map.get("honors") or [],
            "customers_cases": knowledge_map.get("customers_cases") or knowledge_map.get("cases") or [],
            "products": products,
            "attachment_products": knowledge_map.get("attachment_products") or [],
            "sensitive_topics": knowledge_map.get("sensitive_topics") or {},
            "attachments": self.normalize_attachment_entries(knowledge_map.get("attachments")),
            "official_malls": knowledge_map.get("official_malls") or [],
            "official_media_matrix": knowledge_map.get("official_media_matrix") or [],
            "other_info": knowledge_map.get("other_info") or [],
        }

    def sync_remaining_attachments_after_delete(
        self,
        *,
        brand: dict[str, Any],
        deleted_entries: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        brand_id = brand.get("id")
        if brand_id is None or not deleted_entries or self._deps.brand_knowledge is None:
            return []
        row = self._deps.brand_knowledge.get_brand_knowledge_json(
            brand_id=int(brand_id),
            knowledge_type="attachments",
        )
        current_attachments = self.normalize_attachment_entries(
            self.parse_json_value((row or {}).get("content_json"), [])
        )
        remaining_attachments = [
            item
            for item in current_attachments
            if not any(self.attachment_matches_deleted_entry(item, deleted_entry) for deleted_entry in deleted_entries)
        ]
        if remaining_attachments != current_attachments:
            self._deps.brand_knowledge.upsert_brand_knowledge_json(
                brand_id=int(brand_id),
                knowledge_type="attachments",
                content_json=remaining_attachments,
                source_task_id=None,
            )
        return remaining_attachments

    def current_brand_knowledge_mete(self, *, brand: dict[str, Any]) -> tuple[str, dict[str, str]]:
        version = str(brand.get("knowledge_revision") or "").strip()
        latest = None
        brand_id = brand.get("id")
        brand_code = str(brand.get("brand_code") or "").strip()
        if self._deps.brand_full_knowledge is not None:
            if brand_code and hasattr(self._deps.brand_full_knowledge, "get_latest_by_brand_code"):
                latest = self._deps.brand_full_knowledge.get_latest_by_brand_code(brand_code=brand_code)
            elif brand_id is not None and hasattr(self._deps.brand_full_knowledge, "get_latest_by_brand_id"):
                latest = self._deps.brand_full_knowledge.get_latest_by_brand_id(brand_id=int(brand_id))
        return (
            "success" if latest else "skipped",
            {
                "version": version,
                "oss_url_md": str((latest or {}).get("oss_url") or "").strip(),
                "oss_url_pdf": str((latest or {}).get("pdf_oss_url") or "").strip(),
            },
        )

    def get_callback_store(self) -> Any | None:
        upload_tasks = self._deps.upload_tasks
        required_methods = (
            "upsert_upload_task_callback",
            "get_upload_task_callback",
            "update_upload_task_callback_result",
        )
        if upload_tasks is None or not all(hasattr(upload_tasks, method_name) for method_name in required_methods):
            return None
        return upload_tasks

    @staticmethod
    def post_attachment_delete_callback(
        callback_url: str,
        payload: dict[str, Any],
        timeout_seconds: float,
    ) -> tuple[int | None, str | None]:
        status_code, response_body = post_json_text_response(
            callback_url,
            payload,
            timeout_seconds=timeout_seconds,
        )
        return status_code, response_body

    async def send_callback(
        self,
        *,
        payload: dict[str, Any],
        callback_task_id: str,
    ) -> dict[str, Any]:
        return await deliver_upload_task_callback(
            callback_store=self.get_callback_store(),
            task_id=callback_task_id,
            callback_type=ATTACHMENT_DELETE_CALLBACK_TYPE,
            callback_url=str(getattr(self._deps.settings, "brand_completion_callback_url", "") or "").strip(),
            payload=payload,
            timeout_seconds=float(getattr(self._deps.settings, "brand_completion_callback_timeout_seconds", 5.0)),
            retry_delays_seconds=ATTACHMENT_DELETE_CALLBACK_RETRY_DELAYS_SECONDS,
            post_callback=self._deps.post_callback or self.post_attachment_delete_callback,
            missing_url_error="brand_completion_callback_url 未配置",
        )

    def load_callback_payload(self, callback: dict[str, Any]) -> dict[str, Any]:
        return load_callback_payload(callback, label="attachment delete")

    async def run_persisted_callback_retries(
        self,
        *,
        callback_task_id: str,
        initial_delay_seconds: float,
    ) -> None:
        try:
            delay_seconds = initial_delay_seconds
            while True:
                if delay_seconds > 0:
                    await asyncio.sleep(delay_seconds)
                upload_tasks = self.get_callback_store()
                if upload_tasks is None:
                    return
                callback = upload_tasks.get_upload_task_callback(
                    task_id=callback_task_id,
                    callback_type=ATTACHMENT_DELETE_CALLBACK_TYPE,
                )
                if not callback or str(callback.get("status") or "") != "retrying":
                    return
                try:
                    payload = self.load_callback_payload(callback)
                except Exception as exc:  # noqa: BLE001
                    upload_tasks.update_upload_task_callback_result(
                        task_id=callback_task_id,
                        callback_type=ATTACHMENT_DELETE_CALLBACK_TYPE,
                        request_payload_json=None,
                        status="failed",
                        retry_count=int(callback.get("retry_count") or 0),
                        next_retry_at=None,
                        last_response_code=None,
                        last_response_body=None,
                        last_error_message=str(exc),
                        sent_at=None,
                    )
                    return
                result = await self.send_callback(
                    payload=payload,
                    callback_task_id=callback_task_id,
                )
                if result.get("status") != "retrying":
                    return
                refreshed_callback = upload_tasks.get_upload_task_callback(
                    task_id=callback_task_id,
                    callback_type=ATTACHMENT_DELETE_CALLBACK_TYPE,
                )
                delay_seconds = seconds_until((refreshed_callback or {}).get("next_retry_at"))
        finally:
            scheduled = getattr(self._deps.runtime, "scheduled_attachment_delete_callback_retries", None)
            if isinstance(scheduled, set):
                scheduled.discard(callback_task_id)

    def schedule_callback_retry_if_needed(self, *, callback_task_id: str) -> bool:
        upload_tasks = self.get_callback_store()
        scheduled = getattr(self._deps.runtime, "scheduled_attachment_delete_callback_retries", None)
        if upload_tasks is None or not isinstance(scheduled, set):
            return False
        callback = upload_tasks.get_upload_task_callback(
            task_id=callback_task_id,
            callback_type=ATTACHMENT_DELETE_CALLBACK_TYPE,
        )
        if not callback or str(callback.get("status") or "") != "retrying":
            return False
        if callback_task_id in scheduled:
            return True
        scheduled.add(callback_task_id)
        self._deps.spawn_background_task(
            self.run_persisted_callback_retries(
                callback_task_id=callback_task_id,
                initial_delay_seconds=seconds_until(callback.get("next_retry_at")),
            )
        )
        return True

    def schedule_due_callback_retries(self) -> None:
        upload_tasks = self.get_callback_store()
        scheduled = getattr(self._deps.runtime, "scheduled_attachment_delete_callback_retries", None)
        if upload_tasks is None or not hasattr(upload_tasks, "list_retryable_upload_task_callbacks"):
            return
        if not isinstance(scheduled, set):
            return
        for callback in upload_tasks.list_retryable_upload_task_callbacks(
            callback_type=ATTACHMENT_DELETE_CALLBACK_TYPE,
        ):
            callback_task_id = str(callback.get("task_id") or "").strip()
            if not callback_task_id or callback_task_id in scheduled:
                continue
            scheduled.add(callback_task_id)
            self._deps.spawn_background_task(
                self.run_persisted_callback_retries(
                    callback_task_id=callback_task_id,
                    initial_delay_seconds=0,
                )
            )

    async def notify_attachment_delete_success(
        self,
        *,
        brand: dict[str, Any],
        delete_result: dict[str, Any],
    ) -> None:
        callback_entries = [
            item for item in delete_result.get("results", [])
            if isinstance(item, dict) and item.get("status") in {"deleted", "not_found"}
        ]
        if not callback_entries:
            return
        if brand.get("id") is None:
            logger.info("Skip attachment delete callback because brand id is missing brand_code=%s", brand.get("brand_code"))
            return

        self.sync_remaining_attachments_after_delete(
            brand=brand,
            deleted_entries=callback_entries,
        )
        refreshed_brand = self._deps.brands.get_brand_by_code(str(brand.get("brand_code") or "").strip()) or brand
        callback_task_id = (
            f"attachment-delete:{str(refreshed_brand.get('brand_code') or '').strip() or uuid4().hex}:"
            f"{uuid4().hex}"
        )
        callback_result = await self.send_callback(
            payload=self._deps.build_callback_payload(brand=refreshed_brand),
            callback_task_id=callback_task_id,
        )
        if callback_result.get("status") in {"failed", "retrying"}:
            self.schedule_callback_retry_if_needed(callback_task_id=callback_task_id)

    async def delete_documents_by_attachments(
        self,
        *,
        brand_code: str,
        attachments: list[dict[str, Any]],
        notify_success: Callable[..., Any] | None = None,
    ) -> dict[str, Any]:
        normalized_brand_code = str(brand_code or "").strip()
        if not normalized_brand_code:
            raise ValueError("brand_code 不能为空")
        if not attachments:
            raise ValueError("attachments 不能为空")

        brand = self._deps.brands.get_brand_by_code(normalized_brand_code)
        if not brand:
            raise ValueError("brand_code 对应的品牌不存在")

        brand_name = str(brand.get("brand_name") or "").strip()
        if not brand_name:
            raise ValueError("brand_code 对应的品牌名称不存在")

        current_attachments: list[dict[str, Any]] = []
        if brand.get("id") is not None and self._deps.brand_knowledge is not None:
            row = self._deps.brand_knowledge.get_brand_knowledge_json(
                brand_id=int(brand["id"]),
                knowledge_type="attachments",
            )
            current_attachments = self.normalize_attachment_entries(
                self.parse_json_value((row or {}).get("content_json"), [])
            )

        results: list[dict[str, Any]] = []
        deleted_count = 0
        not_found_count = 0
        failed_count = 0
        ambiguous_count = 0

        for index, attachment in enumerate(attachments):
            if not isinstance(attachment, dict):
                raise ValueError(f"attachments[{index}] 格式不正确")

            attachment_name = str(attachment.get("name") or "").strip()
            if not attachment_name:
                raise ValueError(f"attachments[{index}].name 不能为空")

            attachment_url = str(attachment.get("url") or "").strip() or None
            deleted_entry = {
                "name": attachment_name,
                "url": attachment_url,
            }
            matches = [
                item
                for item in current_attachments
                if self.attachment_matches_deleted_entry(item, deleted_entry)
            ]

            if not matches:
                not_found_count += 1
                results.append(
                    {
                        "name": attachment_name,
                        "url": attachment_url,
                        "status": "not_found",
                        "detail": "未找到品牌知识附件记录",
                    }
                )
                continue

            deleted_count += 1
            results.append(
                {
                    "name": attachment_name,
                    "url": attachment_url,
                    "status": "deleted",
                    "detail": "已从品牌知识附件列表移除",
                }
            )

        result = {
            "brand_code": normalized_brand_code,
            "brand_name": brand_name,
            "summary": {
                "requested_count": len(attachments),
                "deleted_count": deleted_count,
                "not_found_count": not_found_count,
                "failed_count": failed_count,
                "ambiguous_count": ambiguous_count,
            },
            "results": results,
        }
        if deleted_count > 0 or not_found_count > 0:
            try:
                if notify_success is None:
                    await self.notify_attachment_delete_success(
                        brand=brand,
                        delete_result=result,
                    )
                else:
                    await notify_success(brand=brand, delete_result=result)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Attachment delete callback side effect failed brand_code=%s",
                    normalized_brand_code,
                )
        return result
