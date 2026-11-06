from __future__ import annotations

import json
import logging
from typing import Any
from uuid import uuid4

from knowledge_base.shared.settings import get_brand_full_knowledge_refresh_delay_seconds


logger = logging.getLogger(__name__)


class BrandKnowledgeUpdateFollowupMixin:
    def _persist_structured_change_audits(
        self,
        *,
        resolved_brand_id: int,
        brand_code: str | None,
        brand_name: str,
        knowledge_revision: str | None,
        structured_change_details: list[dict[str, Any]],
        source_type: str | None = None,
        source_task_id: str | None = None,
        source_job_id: str | None = None,
        source_name: str | None = None,
        source_oss_key: str | None = None,
    ) -> int:
        store = getattr(self._deps, "brand_knowledge_update_audits", None)
        if store is None or not hasattr(store, "create_audit_entries"):
            return 0
        if not structured_change_details:
            return 0
        normalized_source_type = str(source_type or "knowledge_update").strip() or "knowledge_update"
        grouped_entries: dict[str, list[dict[str, Any]]] = {}
        for detail in structured_change_details:
            if not isinstance(detail, dict):
                continue
            entry_source_type = str(detail.get("source_type") or normalized_source_type).strip() or normalized_source_type
            audit_entry = {
                key: value
                for key, value in detail.items()
                if key != "source_type"
            }
            grouped_entries.setdefault(entry_source_type, []).append(audit_entry)
        if not grouped_entries:
            return 0
        persisted_count = 0
        try:
            for entry_source_type, entries in grouped_entries.items():
                audit_id = f"{entry_source_type}:{uuid4().hex}"
                persisted_count += int(
                    store.create_audit_entries(
                        audit_id=audit_id,
                        brand_id=resolved_brand_id,
                        brand_code=brand_code,
                        brand_name=brand_name,
                        knowledge_revision=knowledge_revision,
                        entries=entries,
                        source_type=entry_source_type,
                        source_task_id=source_task_id,
                        source_job_id=source_job_id,
                        source_name=source_name,
                        source_oss_key=source_oss_key,
                    )
                    or 0
                )
            return persisted_count
        except Exception:
            logger.exception(
                "Failed to persist knowledge update audits brand_id=%s brand_code=%s brand_name=%s source_type=%s",
                resolved_brand_id,
                brand_code,
                brand_name,
                normalized_source_type,
            )
            return 0

    def _build_update_result(
        self,
        *,
        resolved_brand_id: int,
        brand_code: str | None,
        brand_name: str,
        updated_sections: list[str],
        deleted_sections: list[str],
        knowledge_revision: str | None,
    ) -> dict[str, Any]:
        return {
            "brand_id": resolved_brand_id,
            "brand_code": brand_code,
            "brand_name": brand_name,
            "status": "success",
            "updated_sections": updated_sections,
            "deleted_sections": deleted_sections,
            "knowledge_revision": knowledge_revision,
        }

    def _refresh_callback_knowledge_snapshot(
        self,
        *,
        brand_code: str | None,
        brand_name: str,
        existing_brand: dict[str, Any],
    ) -> dict[str, Any]:
        refreshed_brand_for_snapshot = self._deps.brands.get_brand_by_code(brand_code) if brand_code else None
        if refreshed_brand_for_snapshot is None:
            refreshed_brand_for_snapshot = self._deps.brands.get_brand_by_name(brand_name)
        _, refreshed_products_for_snapshot, _knowledge_rows, refreshed_knowledge_map = self._load_brand_snapshot(
            brand=refreshed_brand_for_snapshot or existing_brand
        )
        return self._build_attachment_product_callback_snapshot(
            brand_products=refreshed_products_for_snapshot,
            knowledge_map=refreshed_knowledge_map,
        )

    def _build_structured_update_summary(
        self,
        *,
        brand_name: str,
        structured_update_entries: list[dict[str, Any]],
        deleted_sections: list[str],
    ) -> tuple[str, str]:
        structured_update_markdown = self._render_structured_update_delta_markdown(
            brand_name=brand_name,
            entries=structured_update_entries,
            deleted_sections=deleted_sections,
        )
        structured_update_mode = self._classify_structured_update_mode(
            entries=structured_update_entries,
            deleted_sections=deleted_sections,
        )
        return structured_update_markdown, structured_update_mode

    def _log_structured_update(
        self,
        *,
        resolved_brand_id: int,
        brand_code: str | None,
        brand_name: str,
        revision_should_bump: bool,
        updated_sections: list[str],
        deleted_sections: list[str],
        structured_update_entries: list[dict[str, Any]],
        structured_change_details: list[dict[str, Any]],
        structured_update_markdown: str,
        structured_update_mode: str,
    ) -> None:
        logger.info(
            "knowledge/update structured delta brand_id=%s brand_code=%s brand_name=%s mode=%s revision_should_bump=%s updated_sections=%s deleted_sections=%s",
            resolved_brand_id,
            brand_code,
            brand_name,
            structured_update_mode,
            revision_should_bump,
            json.dumps(updated_sections, ensure_ascii=False),
            json.dumps(deleted_sections, ensure_ascii=False),
        )
        logger.debug(
            "knowledge/update structured delta details brand_id=%s brand_code=%s brand_name=%s structured_entries_count=%s structured_changes_count=%s structured_markdown_chars=%s",
            resolved_brand_id,
            brand_code,
            brand_name,
            len(structured_update_entries),
            len(structured_change_details),
            len(str(structured_update_markdown or "")),
        )

    async def _attach_update_followup_result(
        self,
        *,
        result: dict[str, Any],
        revision_should_bump: bool,
        skip_full_ai_knowledge_sync: bool,
        resolved_brand_id: int,
        brand_code: str | None,
        brand_name: str,
        knowledge_revision: str | None,
        deleted_sections: list[str],
        structured_update_markdown: str,
        callback_knowledge_snapshot: dict[str, Any],
        source_type: str | None = None,
        source_task_id: str | None = None,
        source_job_id: str | None = None,
        source_name: str | None = None,
        source_oss_key: str | None = None,
    ) -> None:
        if not revision_should_bump or skip_full_ai_knowledge_sync:
            return

        normalized_source_type = str(source_type or "knowledge_update").strip() or "knowledge_update"
        normalized_source_task_id = str(source_task_id or "").strip() or f"knowledge_update:{uuid4().hex}"
        update_reason = "knowledge_delete" if deleted_sections else "knowledge_update"
        if brand_code and callable(getattr(self._deps, "enqueue_brand_full_knowledge_refresh_job", None)):
            job = await self._deps.enqueue_brand_full_knowledge_refresh_job(
                brand_code=brand_code,
                brand_name=brand_name,
                trigger_source_type=normalized_source_type,
                trigger_source_task_id=normalized_source_task_id,
                knowledge_revision=knowledge_revision,
                delay_seconds=get_brand_full_knowledge_refresh_delay_seconds(self._deps.settings),
            )
            result["background_job_id"] = job.get("job_id")
            result["background_job_status"] = job.get("status") or "waiting"
            return

        if callable(self._deps.enqueue_brand_knowledge_update_job):
            job = await self._deps.enqueue_brand_knowledge_update_job(
                brand_id=resolved_brand_id,
                brand_code=brand_code,
                brand_name=brand_name,
                knowledge_revision=knowledge_revision,
                update_reason=update_reason,
                source_task_id=normalized_source_task_id,
                deleted_sections=deleted_sections,
                structured_knowledge_markdown=structured_update_markdown,
                knowledge_snapshot=callback_knowledge_snapshot,
            )
            result["background_job_id"] = job.get("job_id")
            result["background_job_status"] = job.get("status") or "waiting"
            return

        if callable(self._deps.build_next_brand_full_knowledge):
            ai_knowledge_payload = await self._deps.build_next_brand_full_knowledge(
                brand_name=brand_name,
                update_reason=update_reason,
                source_task_id=normalized_source_task_id,
                change_origin="api" if normalized_source_type == "attachment_confirm" else "frontend",
                knowledge_revision=knowledge_revision,
                deleted_sections=deleted_sections,
                structured_knowledge_markdown=structured_update_markdown,
            )
            result["knowledge_mete"] = {
                "version": str(knowledge_revision or ""),
                "oss_url_md": str((ai_knowledge_payload or {}).get("knowledge_oss_url_md") or ""),
                "oss_url_pdf": str((ai_knowledge_payload or {}).get("knowledge_oss_url_pdf") or ""),
            }
