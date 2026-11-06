from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from knowledge_base.brand.schemas.requests import KnowledgeUpdateRequest
from knowledge_base.brand_knowledge.schemas import AttachmentConfirmSaveRequest
from knowledge_base.shared.settings import get_brand_full_knowledge_refresh_delay_seconds


logger = logging.getLogger(__name__)


@dataclass
class AttachmentConfirmPipelineContext:
    request: AttachmentConfirmSaveRequest
    draft_id: str
    manifest: dict[str, Any]
    draft_attachments: list[dict[str, Any]]
    manifest_brand_name: str | None
    final_markdown_source: str
    update_result: dict[str, Any] = field(
        default_factory=lambda: {
            "brand_id": None,
            "updated_sections": [],
            "knowledge_revision": None,
        }
    )
    brand: dict[str, Any] | None = None
    merged_snapshot: dict[str, Any] | None = None
    changed_snapshot: dict[str, Any] | None = None
    brand_name: str | None = None
    review_payload: dict[str, Any] | None = None
    review_brand_code: str | None = None
    confirm_source_id: str = ""
    confirm_job_id: str | None = None
    confirmed_filename: str = ""
    final_fulltext_key: str = ""
    final_fulltext_url: str | None = None


class AttachmentDraftConfirmPipelineMixin:
    @staticmethod
    def _request_to_payload(request: AttachmentConfirmSaveRequest) -> dict[str, Any]:
        if hasattr(request, "model_dump"):
            return request.model_dump()
        return dict(getattr(request, "__dict__", {}) or {})

    async def confirm_save(
        self,
        *,
        request: AttachmentConfirmSaveRequest,
        draft_id: str,
    ) -> dict[str, Any]:
        if not self._normalize_optional_str(request.review_id):
            raise ValueError("review_id 不能为空，旧链路已禁用")
        if not callable(self._deps.enqueue_attachment_confirm_pipeline_job):
            raise RuntimeError("attachment confirm background job dependency is not initialized")

        manifest = self._load_draft_manifest(draft_id)
        draft_attachments = manifest.get("attachments") if isinstance(manifest, dict) else None
        if not isinstance(draft_attachments, list):
            raise ValueError("draft 附件信息缺失")

        manifest_brand_name = self._normalize_optional_str(manifest.get("brand_name")) if isinstance(manifest, dict) else None
        review_payload = self._load_review_result(
            draft_id=draft_id,
            review_id=str(request.review_id),
        )
        review_brand_name = self._normalize_optional_str(review_payload.get("brand_name"))
        review_brand_code = self._normalize_optional_str(review_payload.get("brand_code"))
        brand_name = review_brand_name or self._normalize_optional_str(request.brand_name) or manifest_brand_name
        if not brand_name:
            raise ValueError("brand_name 不能为空")

        brand = self._resolve_brand_record(
            brand_code=review_brand_code,
            brand_name=brand_name,
        )
        current_revision = self._normalize_optional_str(brand.get("knowledge_revision"))
        expected_revision = (
            self._normalize_optional_str(request.knowledge_revision)
            or self._normalize_optional_str(review_payload.get("knowledge_revision"))
        )
        if expected_revision and current_revision and expected_revision != current_revision:
            raise RuntimeError(f"knowledge_revision 不匹配，当前 revision={current_revision}")

        candidate_snapshot = review_payload.get("update_request_payload")
        if not isinstance(candidate_snapshot, dict):
            raise ValueError("review 结果缺少结构化内容")

        background_job = await self._deps.enqueue_attachment_confirm_pipeline_job(
            draft_id=draft_id,
            review_id=str(request.review_id),
            brand_name=brand_name,
            brand_code=review_brand_code,
            knowledge_revision=expected_revision or current_revision,
            request_payload=self._request_to_payload(request),
        )
        background_status = str((background_job or {}).get("status") or "waiting").strip() or "waiting"
        self._update_draft_manifest(
            draft_id=draft_id,
            updates={
                "draft_status": "confirming",
                "last_review_id": str(request.review_id),
                "background_job_id": (background_job or {}).get("job_id"),
            },
        )
        return {
            "draft_id": draft_id,
            "brand_code": review_brand_code,
            "brand_id": brand.get("id"),
            "brand_name": brand_name,
            "status": "success" if background_status == "success" else "waiting",
            "updated_sections": [],
            "knowledge_revision": expected_revision or current_revision,
            "final_markdown_oss_key": None,
            "final_markdown_oss_url": None,
            "final_document_id": None,
            "original_attachments": [],
            "attachment_documents": [],
            "background_job_id": (background_job or {}).get("job_id"),
            "background_job_status": background_status,
            "confirm_callback_status": "success" if background_status == "success" else "waiting",
        }

    async def process_confirm_pipeline_job(
        self,
        *,
        payload: dict[str, Any],
        job: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request_payload = payload.get("request_payload") if isinstance(payload.get("request_payload"), dict) else {}
        draft_id = str(payload.get("draft_id") or request_payload.get("draft_id") or "").strip()
        if not draft_id:
            raise ValueError("attachment confirm pipeline 缺少 draft_id")
        request = AttachmentConfirmSaveRequest(**{**request_payload, "draft_id": draft_id})
        if not self._normalize_optional_str(request.review_id):
            review_id = self._normalize_optional_str(payload.get("review_id"))
            if review_id:
                request = AttachmentConfirmSaveRequest(
                    **{
                        **self._request_to_payload(request),
                        "review_id": review_id,
                    }
                )
        return await self._process_confirm_pipeline(
            request=request,
            draft_id=draft_id,
            skip_revision_conflict_check=True,
            job=job,
        )

    async def _process_confirm_pipeline(
        self,
        *,
        request: AttachmentConfirmSaveRequest,
        draft_id: str,
        skip_revision_conflict_check: bool = False,
        job: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            context = await self._prepare_confirm_context(
                request=request,
                draft_id=draft_id,
                skip_revision_conflict_check=skip_revision_conflict_check,
                job=job,
            )
            final_markdown = self._build_confirm_final_markdown(context)
            return await self._publish_confirmed_markdown(
                context=context,
                final_markdown=final_markdown,
            )
        except Exception as exc:
            cleanup_draft = self._should_cleanup_draft_after_confirm_failure(job)
            logger.warning(
                "Attachment confirm pipeline failed draft_id=%s review_id=%s cleanup_draft=%s error=%s",
                draft_id,
                request.review_id,
                cleanup_draft,
                exc,
                exc_info=True,
            )
            if cleanup_draft:
                self._delete_draft_dir(draft_id, reason="confirm_failed_terminally")
            raise

    def _resolve_confirmed_markdown_location(
        self,
        *,
        brand_name: str,
        draft_id: str,
        review_id: str,
    ) -> tuple[str, str, str | None]:
        confirmed_filename = f"{brand_name}-{draft_id}-{review_id}-confirmed-knowledge.md"
        final_fulltext_key = self._build_confirmed_knowledge_object_key(
            brand_name=brand_name,
            filename=confirmed_filename,
        )
        final_fulltext_url = (
            self._deps.oss_client.build_object_url(final_fulltext_key)
            if self._deps.oss_client.enabled and hasattr(self._deps.oss_client, "build_object_url")
            else None
        )
        return confirmed_filename, final_fulltext_key, final_fulltext_url

    async def _prepare_confirm_context(
        self,
        *,
        request: AttachmentConfirmSaveRequest,
        draft_id: str,
        skip_revision_conflict_check: bool,
        job: dict[str, Any] | None,
    ) -> AttachmentConfirmPipelineContext:
        if not self._normalize_optional_str(request.review_id):
            raise ValueError("review_id 不能为空，旧链路已禁用")
        manifest = self._load_draft_manifest(draft_id)
        draft_attachments = manifest.get("attachments") if isinstance(manifest, dict) else None
        if not isinstance(draft_attachments, list):
            raise ValueError("draft 附件信息缺失")

        manifest_brand_name = self._normalize_optional_str(manifest.get("brand_name")) if isinstance(manifest, dict) else None
        brand_name = self._normalize_optional_str(request.brand_name) or manifest_brand_name
        confirmed_filename, final_fulltext_key, final_fulltext_url = self._resolve_confirmed_markdown_location(
            brand_name=brand_name or manifest_brand_name or "brand",
            draft_id=draft_id,
            review_id=str(request.review_id),
        )
        context = AttachmentConfirmPipelineContext(
            request=request,
            draft_id=draft_id,
            manifest=manifest,
            draft_attachments=draft_attachments,
            manifest_brand_name=manifest_brand_name,
            final_markdown_source=self._normalize_markdown_text(request.confirmed_text),
            brand_name=brand_name,
            confirm_source_id=f"confirm:{draft_id}:{request.review_id}",
            confirm_job_id=str((job or {}).get("job_id") or "").strip() or None,
            confirmed_filename=confirmed_filename,
            final_fulltext_key=final_fulltext_key,
            final_fulltext_url=final_fulltext_url,
        )

        if request.review_id:
            await self._apply_review_confirm_context(
                context=context,
                skip_revision_conflict_check=skip_revision_conflict_check,
            )
        if not context.brand_name:
            raise ValueError("brand_name 不能为空")
        return context

    async def _apply_review_confirm_context(
        self,
        *,
        context: AttachmentConfirmPipelineContext,
        skip_revision_conflict_check: bool,
    ) -> None:
        request = context.request
        review_payload = self._load_review_result(
            draft_id=context.draft_id,
            review_id=request.review_id,
        )
        review_brand_name = self._normalize_optional_str(review_payload.get("brand_name"))
        review_brand_code = self._normalize_optional_str(review_payload.get("brand_code"))
        brand_name = review_brand_name or context.brand_name
        if not brand_name:
            raise ValueError("brand_name 不能为空")
        confirmed_filename, final_fulltext_key, final_fulltext_url = self._resolve_confirmed_markdown_location(
            brand_name=brand_name,
            draft_id=context.draft_id,
            review_id=str(request.review_id),
        )

        brand = self._resolve_brand_record(
            brand_code=review_brand_code,
            brand_name=brand_name,
        )
        current_revision = self._normalize_optional_str(brand.get("knowledge_revision"))
        expected_revision = (
            self._normalize_optional_str(request.knowledge_revision)
            or self._normalize_optional_str(review_payload.get("knowledge_revision"))
        )
        if (
            not skip_revision_conflict_check
            and expected_revision
            and current_revision
            and expected_revision != current_revision
        ):
            raise RuntimeError(f"knowledge_revision 不匹配，当前 revision={current_revision}")

        candidate_snapshot = review_payload.get("update_request_payload")
        if not isinstance(candidate_snapshot, dict):
            raise ValueError("review 结果缺少结构化内容")
        current_snapshot, _ = self._build_current_snapshot(brand=brand)
        resolved_brand_id = brand.get("id")
        existing_attachment_products = (
            self._load_attachment_products(brand_id=int(resolved_brand_id))
            if resolved_brand_id is not None
            else []
        )
        merged_snapshot = self._merge_snapshot(
            current_snapshot=current_snapshot,
            candidate_snapshot=candidate_snapshot,
        )
        new_attachment_products = self._build_new_attachment_products(
            current_snapshot=current_snapshot,
            candidate_snapshot=candidate_snapshot,
            existing_attachment_products=existing_attachment_products,
        )
        update_request_payload = self._build_update_payload_for_confirm_merge(
            merged_snapshot=merged_snapshot,
            candidate_snapshot=candidate_snapshot,
            current_snapshot=current_snapshot,
        )
        update_request_payload["source_type"] = "attachment_confirm"
        update_request_payload["source_task_id"] = context.confirm_source_id
        update_request_payload["source_job_id"] = context.confirm_job_id
        update_request_payload["source_name"] = confirmed_filename
        update_request_payload["source_oss_key"] = final_fulltext_key if self._deps.oss_client.enabled else None
        update_request_payload["skip_full_ai_knowledge_sync"] = True
        update_result = await self._deps.update_knowledge(KnowledgeUpdateRequest(**update_request_payload))
        if new_attachment_products:
            resolved_brand_id = update_result.get("brand_id") or brand.get("id")
            if resolved_brand_id is not None:
                attachment_products = self._merge_attachment_products(
                    existing_attachment_products=existing_attachment_products,
                    new_attachment_products=new_attachment_products,
                )
                self._upsert_attachment_products(
                    brand_id=int(resolved_brand_id),
                    products=attachment_products,
                )
                updated_sections = update_result.setdefault("updated_sections", [])
                if (
                    isinstance(updated_sections, list)
                    and self.ATTACHMENT_PRODUCTS_KNOWLEDGE_TYPE not in updated_sections
                ):
                    updated_sections.append(self.ATTACHMENT_PRODUCTS_KNOWLEDGE_TYPE)
        final_markdown_source = context.final_markdown_source
        if not final_markdown_source:
            final_markdown_source = self._render_snapshot_markdown(
                brand_name=brand_name,
                snapshot=candidate_snapshot,
            )

        context.review_payload = review_payload
        context.review_brand_code = review_brand_code
        context.brand_name = brand_name
        context.confirmed_filename = confirmed_filename
        context.final_fulltext_key = final_fulltext_key
        context.final_fulltext_url = final_fulltext_url
        context.brand = brand
        context.merged_snapshot = merged_snapshot
        context.changed_snapshot = candidate_snapshot
        context.update_result = update_result
        context.final_markdown_source = final_markdown_source

    def _build_confirm_final_markdown(
        self,
        context: AttachmentConfirmPipelineContext,
    ) -> str:
        brand_name = context.brand_name
        if not brand_name:
            raise ValueError("brand_name 不能为空")
        final_markdown_source = context.final_markdown_source
        if not final_markdown_source:
            raise ValueError("最终确认内容为空，无法生成 Markdown")

        if final_markdown_source.startswith("#"):
            final_markdown = final_markdown_source
        else:
            final_markdown = self._render_final_markdown(
                brand_name=brand_name,
                confirmed_text=final_markdown_source,
                attachments=context.draft_attachments,
            )
        if not final_markdown:
            raise ValueError("最终确认内容为空，无法生成 Markdown")

        if context.request.review_id:
            confirmed_filename, final_fulltext_key, final_fulltext_url = self._resolve_confirmed_markdown_location(
                brand_name=brand_name,
                draft_id=context.draft_id,
                review_id=str(context.request.review_id),
            )
            context.confirmed_filename = confirmed_filename
            context.final_fulltext_key = final_fulltext_key
            context.final_fulltext_url = final_fulltext_url
        return final_markdown

    async def _publish_confirmed_markdown(
        self,
        *,
        context: AttachmentConfirmPipelineContext,
        final_markdown: str,
    ) -> dict[str, Any]:
        uploaded_keys: list[str] = []
        ai_knowledge_payload: dict[str, Any] | None = None
        refresh_job: dict[str, Any] | None = None
        confirm_callback_payload: dict[str, Any] | None = None
        confirm_callback_result: dict[str, Any] = {
            "status": "skipped",
            "response_code": None,
            "error": None,
        }

        try:
            if self._deps.oss_client.enabled:
                uploaded_markdown_key = await self._upload_bytes_with_retry(
                    data=final_markdown.encode("utf-8"),
                    object_key=context.final_fulltext_key,
                    content_type="text/markdown; charset=utf-8",
                )
                if not uploaded_markdown_key:
                    raise ValueError("最终 Markdown 上传 OSS 失败")
                uploaded_keys.append(uploaded_markdown_key)
            if callable(getattr(self._deps, "enqueue_brand_full_knowledge_refresh_job", None)):
                refresh_job = await self._deps.enqueue_brand_full_knowledge_refresh_job(
                    brand_code=str(
                        (context.update_result or {}).get("brand_code") or context.review_brand_code or ""
                    ).strip(),
                    brand_name=context.brand_name,
                    trigger_source_type="attachment_confirm",
                    trigger_source_task_id=context.confirm_source_id,
                    knowledge_revision=self._normalize_optional_str(context.update_result.get("knowledge_revision")),
                    delay_seconds=get_brand_full_knowledge_refresh_delay_seconds(self._deps.settings),
                )
            elif callable(self._deps.build_next_brand_full_knowledge):
                supplemental_markdown_sources = await self._build_confirm_supplemental_markdown_sources(
                    context=context,
                    final_markdown=final_markdown,
                )
                ai_knowledge_payload = await self._deps.build_next_brand_full_knowledge(
                    brand_name=context.brand_name,
                    confirmed_markdown=final_markdown,
                    supplemental_markdown_sources=supplemental_markdown_sources,
                    source_task_id=context.confirm_source_id,
                    change_origin="api",
                )

            if context.request.review_id and context.brand is not None and context.merged_snapshot is not None:
                confirm_callback_payload = self._build_confirm_callback_payload(
                    brand=context.brand,
                    merged_snapshot=context.merged_snapshot,
                    changed_snapshot=context.changed_snapshot,
                    knowledge_revision=self._normalize_optional_str(context.update_result.get("knowledge_revision")),
                    ai_knowledge_payload=ai_knowledge_payload,
                )
                confirm_callback_task_id = self._confirm_callback_task_id(
                    draft_id=context.draft_id,
                    review_id=context.request.review_id,
                )
                confirm_callback_result = await self._send_confirm_callback(
                    payload=confirm_callback_payload,
                    callback_task_id=confirm_callback_task_id,
                )
                if confirm_callback_result.get("status") in {"failed", "retrying"}:
                    scheduled = self._schedule_confirm_callback_retries_if_needed(
                        draft_id=context.draft_id,
                        review_id=context.request.review_id,
                        brand_name=context.brand_name,
                        payload=confirm_callback_payload,
                    )
                    if scheduled:
                        confirm_callback_result = {
                            **confirm_callback_result,
                            "status": "retrying",
                        }

            self._delete_draft_dir(context.draft_id, reason="confirm_completed")

            return {
                "draft_id": context.draft_id,
                "brand_code": str(
                    (context.update_result or {}).get("brand_code") or context.review_brand_code or ""
                ).strip()
                or None,
                "brand_id": context.update_result.get("brand_id"),
                "brand_name": context.brand_name,
                "status": "success",
                "updated_sections": list(context.update_result.get("updated_sections") or []),
                "knowledge_revision": context.update_result.get("knowledge_revision"),
                "final_markdown_oss_key": context.final_fulltext_key if self._deps.oss_client.enabled else None,
                "final_markdown_oss_url": context.final_fulltext_url if self._deps.oss_client.enabled else None,
                "final_document_id": None,
                "original_attachments": [],
                "attachment_documents": [],
                "background_job_id": None,
                "background_job_status": None,
                "full_knowledge_refresh_job_id": (refresh_job or {}).get("job_id"),
                "full_knowledge_refresh_status": (refresh_job or {}).get("status"),
                "confirm_callback_status": confirm_callback_result.get("status"),
                "ai_knowledge_payload": ai_knowledge_payload,
                "callback_payload": confirm_callback_payload,
                "callback_result": confirm_callback_result,
            }
        except Exception as publish_exc:
            logger.warning(
                "Attachment confirm publish failed; rolling back uploaded OSS objects draft_id=%s review_id=%s uploaded_count=%s error=%s",
                context.draft_id,
                context.request.review_id,
                len(uploaded_keys),
                publish_exc,
                exc_info=True,
            )
            if self._deps.oss_client.enabled:
                for object_key in reversed(uploaded_keys):
                    try:
                        self._deps.oss_client.delete_object(object_key)
                    except Exception:  # noqa: BLE001
                        logger.warning("Failed to rollback OSS object object_key=%s", object_key, exc_info=True)
            raise

    async def _build_confirm_supplemental_markdown_sources(
        self,
        *,
        context: AttachmentConfirmPipelineContext,
        final_markdown: str,
    ) -> list[dict[str, Any]]:
        supplemental_markdown_sources: list[dict[str, Any]] = []
        if not context.request.review_id or not context.brand_name:
            return supplemental_markdown_sources
        try:
            from knowledge_base.brand_knowledge.application import attachment_flow as attachment_flow_module

            snapshot_result = await attachment_flow_module.build_brand_knowledge_snapshot_from_markdown(
                self._knowledge_snapshot_service_proxy(),
                brand_name=context.brand_name,
                markdown_text=final_markdown,
                source_name=context.confirmed_filename,
                attachments=[
                    {
                        "name": str(item.get("name") or "").strip(),
                        "source_url": str(item.get("url") or "").strip() or None,
                        "subcategory": None,
                    }
                    for item in context.draft_attachments
                    if str(item.get("name") or "").strip()
                ],
            )
            supplemental_markdown_sources = list(snapshot_result.get("supplemental_markdown_sources") or [])
        except Exception:  # noqa: BLE001
            logger.exception(
                "Failed to build supplemental markdown sources for confirmed attachment flow brand_name=%s",
                context.brand_name,
            )
        return supplemental_markdown_sources
