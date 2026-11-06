from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from knowledge_base.brand.schemas import KnowledgeUpdateRequest
from knowledge_base.shared.utils import (
    KNOWLEDGE_REVISION_CHANGE_ATTACHMENT,
    KNOWLEDGE_REVISION_CHANGE_MANUAL,
    build_original_object_key,
    build_knowledge_revision,
)


logger = logging.getLogger(__name__)


class BrandKnowledgeUpdateWorkflowMixin:
    async def _sync_attachment_documents(
        self,
        *,
        brand_name: str,
        current_attachments: Any,
        next_attachments: Any,
    ) -> None:
        normalized_current = self._normalize_attachment_entries(current_attachments)
        normalized_next = self._normalize_attachment_entries(next_attachments)
        current_keys = {item["url"] for item in normalized_current}
        additions = [item for item in normalized_next if item["url"] not in current_keys]
        if not additions:
            return

        attachment_assets = self._deps.brand_attachment_assets
        oss_client = self._deps.oss_client
        if attachment_assets is None or not hasattr(attachment_assets, "create_asset"):
            raise RuntimeError("brand_attachment_assets dependency is not initialized")
        if oss_client is None or not getattr(oss_client, "enabled", False):
            raise RuntimeError("oss_client dependency is not initialized")

        processed_assets: list[dict[str, Any]] = []
        try:
            for item in additions:
                try:
                    asset_payload = await self._sync_attachment_asset(
                        brand_name=brand_name,
                        attachment_name=item["name"],
                        attachment_url=item["url"],
                    )
                except Exception as exc:
                    if self._is_duplicate_attachment_upload_error(exc):
                        logger.warning(
                            "Knowledge update attachment skipped as duplicate "
                            "brand_name=%s attachment_name=%s attachment_url=%s reason=%s",
                            brand_name,
                            item["name"],
                            item["url"],
                            exc,
                        )
                        continue
                    raise
                if asset_payload is not None:
                    processed_assets.append(asset_payload)

        except Exception:
            if attachment_assets is not None and hasattr(attachment_assets, "delete_by_id"):
                for asset_payload in reversed(processed_assets):
                    try:
                        object_key = str(asset_payload.get("oss_key") or "").strip()
                        if object_key:
                            try:
                                await asyncio.to_thread(oss_client.delete_object, object_key)
                            except Exception as cleanup_exc:  # noqa: BLE001
                                logger.warning(
                                    "Failed to rollback knowledge update attachment OSS object brand_name=%s attachment_asset_id=%s object_key=%s error=%s",
                                    brand_name,
                                    asset_payload.get("asset_id"),
                                    object_key,
                                    cleanup_exc,
                                    exc_info=True,
                                )
                        attachment_assets.delete_by_id(asset_id=int(asset_payload["asset_id"]))
                    except Exception as cleanup_exc:  # noqa: BLE001
                        logger.warning(
                            "Failed to rollback knowledge update attachment asset brand_name=%s attachment_asset_id=%s error=%s",
                            brand_name,
                            asset_payload.get("asset_id"),
                            cleanup_exc,
                            exc_info=True,
                        )
            raise

    async def _sync_attachment_asset(
        self,
        *,
        brand_name: str,
        attachment_name: str,
        attachment_url: str,
    ) -> dict[str, Any] | None:
        attachment_assets = self._deps.brand_attachment_assets
        oss_client = self._deps.oss_client
        if attachment_assets is None or not hasattr(attachment_assets, "create_asset"):
            raise RuntimeError("brand_attachment_assets dependency is not initialized")
        if oss_client is None or not getattr(oss_client, "enabled", False):
            raise RuntimeError("oss_client dependency is not initialized")

        brand = self._deps.brands.get_brand_by_name(brand_name)
        if brand is None:
            raise ValueError("brand_name 对应的品牌不存在")
        brand_code = str(brand.get("brand_code") or "").strip()
        if not brand_code:
            raise ValueError("brand_name 对应的品牌编码不存在")

        temp_path: Path | None = None
        try:
            from knowledge_base.brand.application import service as brand_application_service_module

            temp_path, content_type, file_size = await brand_application_service_module.download_remote_content_to_temp_file(
                url=attachment_url,
                name=attachment_name,
                log_context=f"knowledge_update_attachment:{brand_name}",
            )
            file_hash = await asyncio.to_thread(self._compute_sha256_for_path, temp_path)
            existing_asset = attachment_assets.get_by_brand_code_and_file_hash(
                brand_code=brand_code,
                file_hash=file_hash,
            )
            if existing_asset is not None:
                return None

            converted_version = attachment_assets.get_next_converted_version(
                brand_code=brand_code,
                original_filename=attachment_name,
            )
            upload_document_id = f"attachment_{uuid4().hex}"
            original_object_key = build_original_object_key(
                category=brand_name,
                subcategory=None,
                filename=attachment_name,
                document_id=upload_document_id,
                converted_version=converted_version,
            )
            uploaded_original_key = await asyncio.to_thread(
                oss_client.upload_file,
                str(temp_path),
                original_object_key,
                content_type or "application/octet-stream",
            )
            if not uploaded_original_key:
                raise ValueError(f"附件原文上传 OSS 失败: {attachment_name}")
            original_oss_url = oss_client.build_object_url(uploaded_original_key)

            asset_id = attachment_assets.create_asset(
                brand_code=brand_code,
                brand_name=brand_name,
                upload_task_id=None,
                upload_task_file_id=None,
                original_filename=attachment_name,
                content_type=content_type,
                parsed_source_type=None,
                parsed_markdown=None,
                converted_version=converted_version,
                fulltext_key=None,
                fulltext_url=None,
                file_size=file_size,
                file_hash=file_hash,
                oss_key=uploaded_original_key,
                oss_url=original_oss_url,
                source_url=attachment_url,
            )
        except Exception:
            if "uploaded_original_key" in locals():
                try:
                    await asyncio.to_thread(oss_client.delete_object, uploaded_original_key)
                except Exception as cleanup_exc:  # noqa: BLE001
                    logger.warning(
                        "Failed to rollback uploaded knowledge update attachment original brand_name=%s attachment_name=%s object_key=%s error=%s",
                        brand_name,
                        attachment_name,
                        uploaded_original_key,
                        cleanup_exc,
                        exc_info=True,
                    )
            raise
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
        return {
            "asset_id": asset_id,
            "oss_key": uploaded_original_key,
        }

    @staticmethod
    def _compute_sha256_for_path(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as file_obj:
            for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
                if not chunk:
                    continue
                digest.update(chunk)
        return digest.hexdigest()

    async def update_knowledge(self, request: KnowledgeUpdateRequest) -> dict[str, Any]:
        basic_info = request.basic_info
        brand_name = self._normalize_str(basic_info.brand_name)
        brand_code = self._normalize_str(basic_info.brand_code)
        attachments_was_provided = self._field_was_provided(request, "attachments")
        skip_attachment_document_sync = bool(getattr(request, "skip_attachment_document_sync", False))
        skip_full_ai_knowledge_sync = bool(getattr(request, "skip_full_ai_knowledge_sync", False))
        sensitive_topics_was_provided = self._field_was_provided(request, "sensitive_topics")

        if not brand_name:
            raise ValueError("无法确定品牌名称")

        existing_brand = self._align_brand_name_with_brand_code_for_update(
            brand_code=brand_code,
            brand_name=brand_name,
        )
        if existing_brand is None:
            existing_brand = self._resolve_existing_brand_for_update(
                brand_code=brand_code,
                brand_name=brand_name,
            )
        if existing_brand is None:
            return {
                "brand_id": None,
                "brand_code": brand_code,
                "brand_name": brand_name,
                "status": "没有这个品牌，无法修改",
                "updated_sections": [],
            }

        existing_products, knowledge_map, existing_attachments, existing_attachment_products = (
            self._load_update_snapshot(
                existing_brand=existing_brand,
            )
        )
        normalized_company_profile = self._normalize_company_profile_update_payload(request.company_profile)
        brand_upsert_payload = self._build_brand_upsert_payload(
            basic_info=basic_info,
            brand_code=brand_code,
            brand_name=brand_name,
            normalized_company_profile=normalized_company_profile,
        )

        revision_change_type = KNOWLEDGE_REVISION_CHANGE_MANUAL
        structured_update_entries: list[dict[str, Any]] = []
        structured_change_details: list[dict[str, Any]] = []
        brand_has_change = self._track_brand_update(
            existing_brand=existing_brand,
            brand_upsert_payload=brand_upsert_payload,
            structured_update_entries=structured_update_entries,
            structured_change_details=structured_change_details,
        )
        revision_should_bump = brand_has_change
        resolved_brand_id = self._deps.brands.upsert_brand(**brand_upsert_payload)

        updated_sections: list[str] = []
        if brand_has_change:
            updated_sections.append("brands")
        deleted_sections: list[str] = []
        if self._field_was_provided(request, "products") and self._apply_product_updates(
            request_products=request.products,
            existing_products=existing_products,
            resolved_brand_id=resolved_brand_id,
            brand_name=brand_name,
            updated_sections=updated_sections,
            deleted_sections=deleted_sections,
            structured_update_entries=structured_update_entries,
            structured_change_details=structured_change_details,
        ):
            revision_should_bump = True

        if attachments_was_provided and not skip_attachment_document_sync:
            await self._sync_attachment_documents(
                brand_name=brand_name,
                current_attachments=existing_attachments,
                next_attachments=request.attachments,
            )

        other_info_content, attachment_products_override_provided, attachment_products_content = (
            self._prepare_other_info_update(
                request=request,
                knowledge_map=knowledge_map,
                existing_attachment_products=existing_attachment_products,
            )
        )
        if self._apply_structured_knowledge_updates(
            request=request,
            resolved_brand_id=resolved_brand_id,
            knowledge_map=knowledge_map,
            normalized_company_profile=normalized_company_profile,
            other_info_content=other_info_content,
            updated_sections=updated_sections,
            deleted_sections=deleted_sections,
            structured_update_entries=structured_update_entries,
            structured_change_details=structured_change_details,
        ):
            revision_should_bump = True

        if self._apply_attachment_products_update(
            resolved_brand_id=resolved_brand_id,
            existing_attachment_products=existing_attachment_products,
            attachment_products_override_provided=attachment_products_override_provided,
            attachment_products_content=attachment_products_content,
            updated_sections=updated_sections,
            deleted_sections=deleted_sections,
            structured_update_entries=structured_update_entries,
            structured_change_details=structured_change_details,
        ):
            revision_should_bump = True

        if self._apply_sensitive_topics_update(
            request=request,
            sensitive_topics_was_provided=sensitive_topics_was_provided,
            knowledge_map=knowledge_map,
            resolved_brand_id=resolved_brand_id,
            updated_sections=updated_sections,
            structured_update_entries=structured_update_entries,
            structured_change_details=structured_change_details,
        ):
            revision_should_bump = True

        if attachments_was_provided:
            if self._apply_attachments_update(
                resolved_brand_id=resolved_brand_id,
                existing_attachments=existing_attachments,
                next_attachments=request.attachments,
                updated_sections=updated_sections,
                structured_update_entries=structured_update_entries,
                structured_change_details=structured_change_details,
            ):
                revision_should_bump = True
                revision_change_type = KNOWLEDGE_REVISION_CHANGE_ATTACHMENT

        structured_update_markdown, structured_update_mode = self._build_structured_update_summary(
            brand_name=brand_name,
            structured_update_entries=structured_update_entries,
            deleted_sections=deleted_sections,
        )
        should_refresh_full_knowledge = revision_should_bump and bool(str(structured_update_markdown or "").strip())

        current_revision = self._normalize_str(existing_brand.get("knowledge_revision"))
        knowledge_revision = current_revision
        if should_refresh_full_knowledge:
            knowledge_revision = build_knowledge_revision(
                brand_code=brand_code,
                brand_name=brand_name,
                current_revision=current_revision,
                change_type=revision_change_type,
            )
            self._deps.brands.upsert_brand(
                **brand_upsert_payload,
                knowledge_revision=knowledge_revision,
            )

        result = self._build_update_result(
            resolved_brand_id=resolved_brand_id,
            brand_code=brand_code,
            brand_name=brand_name,
            updated_sections=updated_sections,
            deleted_sections=deleted_sections,
            knowledge_revision=knowledge_revision,
        )
        callback_knowledge_snapshot = self._refresh_callback_knowledge_snapshot(
            brand_code=brand_code,
            brand_name=brand_name,
            existing_brand=existing_brand,
        )
        self._log_structured_update(
            resolved_brand_id=resolved_brand_id,
            brand_code=brand_code,
            brand_name=brand_name,
            revision_should_bump=should_refresh_full_knowledge,
            updated_sections=updated_sections,
            deleted_sections=deleted_sections,
            structured_update_entries=structured_update_entries,
            structured_change_details=structured_change_details,
            structured_update_markdown=structured_update_markdown,
            structured_update_mode=structured_update_mode,
        )
        request_source_type = str(getattr(request, "source_type", None) or "knowledge_update").strip() or "knowledge_update"
        request_source_task_id = str(getattr(request, "source_task_id", None) or "").strip()
        if not request_source_task_id:
            request_source_task_id = f"knowledge_update:{uuid4().hex}"
        request_source_job_id = str(getattr(request, "source_job_id", None) or "").strip() or None
        request_source_name = str(getattr(request, "source_name", None) or "").strip() or None
        request_source_oss_key = str(getattr(request, "source_oss_key", None) or "").strip() or None
        self._persist_structured_change_audits(
            resolved_brand_id=resolved_brand_id,
            brand_code=brand_code,
            brand_name=brand_name,
            knowledge_revision=knowledge_revision,
            structured_change_details=structured_change_details,
            source_type=request_source_type,
            source_task_id=request_source_task_id,
            source_job_id=request_source_job_id,
            source_name=request_source_name,
            source_oss_key=request_source_oss_key,
        )
        await self._attach_update_followup_result(
            result=result,
            revision_should_bump=should_refresh_full_knowledge,
            skip_full_ai_knowledge_sync=skip_full_ai_knowledge_sync,
            resolved_brand_id=resolved_brand_id,
            brand_code=brand_code,
            brand_name=brand_name,
            knowledge_revision=knowledge_revision,
            deleted_sections=deleted_sections,
            structured_update_markdown=structured_update_markdown,
            callback_knowledge_snapshot=callback_knowledge_snapshot,
            source_type=request_source_type,
            source_task_id=request_source_task_id,
            source_job_id=request_source_job_id,
            source_name=request_source_name,
            source_oss_key=request_source_oss_key,
        )

        return result
