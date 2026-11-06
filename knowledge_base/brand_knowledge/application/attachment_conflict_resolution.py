from __future__ import annotations

import json
from typing import Any

from knowledge_base.brand_knowledge.application.attachment_conflict_callbacks import (
    BRAND_KNOWLEDGE_COMPLETED_CALLBACK_TYPE,
)


class AttachmentConflictResolutionMixin:
    async def process_attachment_conflict_resolution_job(
        self,
        *,
        payload: dict[str, Any],
        job: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session_id = str(payload.get("session_id") or "").strip()
        if not session_id:
            raise ValueError("attachment conflict resolution 缺少 session_id")
        session = self._deps.brand_knowledge_sessions.get_session(session_id)
        if not session:
            raise ValueError("session_id 不存在")
        if not self._is_attachment_conflict_session_kind(session.get("session_kind")):
            raise ValueError("当前会话不是附件冲突会话")

        source_documents = self._parse_json_value(session.get("source_documents_json"), [])
        if not isinstance(source_documents, list) or not source_documents:
            raise ValueError("会话源文档缺失")
        markdown_sources, _ = self._load_session_markdown_sources(source_documents)
        if not markdown_sources:
            raise ValueError("无法读取会话源 Markdown")

        submitted_round_no = int(payload.get("submitted_round_no") or session.get("current_round") or 1)
        generation_round_no = int(payload.get("generation_round_no") or submitted_round_no + 1)
        current_resolutions = payload.get("current_resolutions")
        if not isinstance(current_resolutions, list):
            current_resolutions = []
        history_resolutions = payload.get("history_resolutions")
        if not isinstance(history_resolutions, list):
            history_resolutions = []
        auto_merged = self._normalize_auto_merged(payload.get("auto_merged"))
        force_reingest = bool(payload.get("force_reingest"))
        publish_mode = self._normalize_publish_mode(
            payload.get("publish_mode")
            or self._publish_mode_from_attachment_conflict_session_kind(session.get("session_kind"))
        )

        request_payload = {
            "brand_code": str(session.get("brand_code") or "").strip(),
            "brand_name": str(session.get("brand_name") or "").strip(),
            "source_task_id": str(session.get("source_task_id") or "").strip() or None,
            "round_no": generation_round_no,
            "stage": "attachment_generate_full_markdown_and_publish",
            "history_resolutions": history_resolutions,
            "current_resolutions": current_resolutions,
            "auto_merged": auto_merged,
            "source_count": len(markdown_sources),
            "force_reingest": force_reingest,
            "publish_mode": publish_mode,
        }
        try:
            brand = self._deps.brands.get_brand_by_code(str(session.get("brand_code") or "").strip())
            if not brand:
                raise ValueError("品牌不存在，请先建品牌")
            base_markdown = ""
            if self._is_draft_only_publish_mode(publish_mode):
                try:
                    _, base_markdown = self._load_latest_base_knowledge_markdown(brand=brand)
                except ValueError:
                    base_markdown = ""
            if self._is_draft_only_publish_mode(publish_mode) and base_markdown:
                response_payload = await self._generate_brand_knowledge_patch_markdown(
                    brand_name=str(session.get("brand_name") or ""),
                    markdown_sources=markdown_sources,
                    base_knowledge_markdown=base_markdown,
                    history_resolutions=history_resolutions,
                    current_resolutions=current_resolutions,
                    auto_merged=auto_merged,
                )
            else:
                response_payload = await self._generate_brand_knowledge_full_markdown(
                    brand_name=str(session.get("brand_name") or ""),
                    markdown_sources=markdown_sources,
                    history_resolutions=history_resolutions,
                    current_resolutions=current_resolutions,
                    auto_merged=auto_merged,
                )
            normalized_payload = self._normalize_session_payload(
                response_payload,
                allow_completed=True,
                fallback_summary=str(session.get("latest_draft_markdown") or "") or None,
            )
            final_markdown = normalized_payload["final_markdown"]
            if not final_markdown:
                raise ValueError("未生成有效的最终品牌知识库 Markdown")

            normalized_brand_code = str(session.get("brand_code") or "").strip()
            resolved_brand_name = str(session.get("brand_name") or "").strip()
            resolved_source_task_id = str(session.get("source_task_id") or "").strip() or session_id
            final_filename = ""
            if self._should_ingest_full_knowledge(publish_mode):
                snapshot_result = await self._build_brand_knowledge_snapshot_from_markdown(
                    brand_name=resolved_brand_name,
                    markdown_text=final_markdown,
                    source_name=f"{resolved_brand_name}-attachment-conflict-final.md",
                    attachments=self._build_snapshot_attachments(source_documents),
                )
                supplemental_markdown_sources = list(snapshot_result.get("supplemental_markdown_sources") or [])

                generated_ai_knowledge_payload: dict[str, Any] | None = None
                if callable(self._deps.generate_next_brand_full_knowledge):
                    generated_ai_knowledge_payload = await self._deps.generate_next_brand_full_knowledge(
                        brand_name=resolved_brand_name,
                        confirmed_markdown=final_markdown,
                        supplemental_markdown_sources=supplemental_markdown_sources,
                        source_task_id=resolved_source_task_id,
                    )
                    final_markdown = (
                        str(generated_ai_knowledge_payload.get("knowledge_markdown") or "").strip()
                        or final_markdown
                    )
                    final_filename = str(generated_ai_knowledge_payload.get("file_name") or "").strip()
            if not final_filename:
                if hasattr(self._deps.brand_full_knowledge, "get_next_version_no_by_brand_code") and normalized_brand_code:
                    version_no = self._deps.brand_full_knowledge.get_next_version_no_by_brand_code(
                        brand_code=normalized_brand_code,
                    )
                else:
                    version_no = self._deps.brand_full_knowledge.get_next_version_no(brand_id=int(brand["id"]))
                final_filename = self._build_final_knowledge_filename(
                    resolved_brand_name,
                    version_no=version_no,
                )
            if self._is_draft_only_publish_mode(publish_mode):
                ingest_result = await self._store_generated_markdown_draft(
                    session_id=session_id,
                    filename=final_filename,
                    brand=brand,
                    brand_code=normalized_brand_code,
                    brand_name=resolved_brand_name,
                    markdown_text=final_markdown,
                    source_task_id=resolved_source_task_id,
                    change_origin="frontend",
                )
                completed_knowledge_payload = None
                persisted_snapshot_result = None
            else:
                final_snapshot_result = await self._build_brand_knowledge_snapshot_from_markdown(
                    brand_name=resolved_brand_name,
                    markdown_text=final_markdown,
                    source_name=final_filename or f"{resolved_brand_name}-final-ai-knowledge.md",
                    attachments=self._build_snapshot_attachments(source_documents),
                    enable_tianyancha=False,
                )
                ingest_result = await self._ingest_attachment_conflict_final_markdown(
                    session_id=session_id,
                    filename=final_filename,
                    brand_code=normalized_brand_code,
                    brand_name=resolved_brand_name,
                    markdown_text=final_markdown,
                    force_reingest=force_reingest,
                    source_task_id=resolved_source_task_id,
                    change_origin="api",
                )

                persisted_snapshot_result = self._persist_brand_knowledge_snapshot(
                    brand_name=resolved_brand_name,
                    snapshot=final_snapshot_result["snapshot"],
                    source_task_id=resolved_source_task_id,
                )
                completed_knowledge_payload = self._format_brand_callback_knowledge_from_snapshot(
                    brand=persisted_snapshot_result["brand"],
                    knowledge_snapshot=persisted_snapshot_result["snapshot"],
                )

            source_task_id = str(session.get("source_task_id") or "").strip() or None
            if source_task_id:
                try:
                    self._cleanup_attachment_temp_facts(source_task_id=source_task_id)
                except Exception as cleanup_exc:  # noqa: BLE001
                    logger.warning(
                        "Failed to cleanup attachment conflict temporary facts session_id=%s source_task_id=%s error=%s",
                        session_id,
                        source_task_id,
                        cleanup_exc,
                        exc_info=True,
                    )

            assistant_message = (
                "最终品牌 AI 知识库草稿已生成并上传 OSS。"
                if self._is_draft_only_publish_mode(publish_mode)
                else "最终正式知识库已生成并完成入库。"
            )
            updated_resolution_history = [
                *history_resolutions,
                {"round_no": submitted_round_no, "resolutions": current_resolutions},
            ]
            self._deps.brand_knowledge_sessions.create_round(
                session_id=session_id,
                round_no=generation_round_no,
                stage="attachment_finalize",
                request_payload=request_payload,
                response_payload={**response_payload, "ingest_result": ingest_result},
                user_message_text=json.dumps(current_resolutions, ensure_ascii=False),
                assistant_message_text=assistant_message,
                draft_markdown=final_markdown,
                conflicts=[],
                conflict_markdown=None,
                user_resolution=current_resolutions,
            )
            self._deps.brand_knowledge_sessions.update_session_progress(
                session_id=session_id,
                status="completed",
                current_round=generation_round_no,
                latest_draft_markdown=str(session.get("latest_scan_summary") or "") or None,
                latest_conflicts=[],
                latest_conflict_markdown=None,
                latest_scan_summary=str(session.get("latest_scan_summary") or "") or None,
                latest_user_message=json.dumps(current_resolutions, ensure_ascii=False),
                latest_assistant_message=assistant_message,
                resolution_history=updated_resolution_history,
                final_markdown=final_markdown,
                final_oss_key=ingest_result.get("markdown_oss_key"),
                final_full_knowledge_file_id=ingest_result.get("full_knowledge_file_id"),
                final_document_id=ingest_result.get("document_id"),
            )
            callback_url = str(getattr(self._deps.settings, "brand_completion_callback_url", "") or "").strip()
            callback_result = {
                "status": "skipped",
                "response_code": None,
                "error": "draft_only 模式不回调上游" if self._is_draft_only_publish_mode(publish_mode) else "brand_completion_callback_url 未配置",
            }
            if callback_url and self._should_ingest_full_knowledge(publish_mode):
                callback_payload = self._build_attachment_conflict_completed_callback_payload(
                    session_id=session_id,
                    brand_code=normalized_brand_code,
                    knowledge_oss_url_md=ingest_result.get("markdown_oss_url"),
                    knowledge_oss_url_pdf=ingest_result.get("pdf_oss_url"),
                    knowledge_payload=completed_knowledge_payload,
                    knowledge_revision=str(persisted_snapshot_result.get("knowledge_revision") or "").strip() or None,
                    knowledge_extraction_status="success",
                )
                callback_task_id = self._attachment_conflict_callback_task_id(
                    session_id=session_id,
                    stage="completed",
                )
                callback_result = await self._send_attachment_conflict_callback(
                    payload=callback_payload,
                    callback_type=BRAND_KNOWLEDGE_COMPLETED_CALLBACK_TYPE,
                    callback_task_id=callback_task_id,
                )
                if callback_result.get("status") in {"failed", "retrying"}:
                    self._schedule_attachment_conflict_callback_retries_if_needed(
                        callback_task_id=callback_task_id,
                        callback_type=BRAND_KNOWLEDGE_COMPLETED_CALLBACK_TYPE,
                    )
            return {
                "session_id": session_id,
                "status": "completed",
                "round_no": generation_round_no,
                "final_filename": final_filename,
                "knowledge_oss_url_md": ingest_result.get("markdown_oss_url"),
                "knowledge_oss_url_pdf": ingest_result.get("pdf_oss_url"),
                "callback_result": callback_result,
            }
        except Exception as exc:
            self._deps.brand_knowledge_sessions.update_session_progress(
                session_id=session_id,
                status="failed",
                current_round=generation_round_no,
                latest_draft_markdown=str(session.get("latest_draft_markdown") or "") or None,
                latest_conflicts=[],
                latest_conflict_markdown=None,
                latest_scan_summary=str(session.get("latest_scan_summary") or "") or None,
                latest_user_message=json.dumps(current_resolutions, ensure_ascii=False),
                latest_assistant_message=f"正式知识库生成失败：{exc}",
                resolution_history=[
                    *history_resolutions,
                    {"round_no": submitted_round_no, "resolutions": current_resolutions},
                ],
            )
            raise
