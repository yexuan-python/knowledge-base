from __future__ import annotations

import logging
from typing import Any


logger = logging.getLogger(__name__)


class BrandAiKnowledgeIngestionSameContentMixin:
    async def _maybe_skip_existing_same_content(
        self,
        *,
        task_id: str,
        job_id: str,
        brand: dict[str, Any],
        normalized_brand_code: str,
        normalized_brand_name: str,
        markdown_text: str,
        markdown_file_name: str,
        content_hash: str,
        resolved_content_type: str | None,
        source_hash: str,
        source_file_size: int,
        existing_same_content: dict[str, Any] | None,
        force_reingest: bool,
        backfill_brand_knowledge_json_empty_only: bool,
        resolved_source_task_id: str,
    ) -> dict[str, Any] | None:
        if (
            existing_same_content is None
            or not self._is_reusable_same_content_row(existing_same_content)
            or force_reingest
        ):
            return None

        logger.info(
            "Brand AI knowledge skipped same content task_id=%s job_id=%s filename=%s existing_file_id=%s existing_document_id=%s",
            task_id,
            job_id,
            markdown_file_name,
            existing_same_content.get("id"),
            existing_same_content.get("document_id"),
        )
        knowledge_json_backfill_status = "skipped"
        if backfill_brand_knowledge_json_empty_only:
            logger.info(
                "Brand AI knowledge json backfill started task_id=%s job_id=%s full_knowledge_file_id=%s",
                task_id,
                job_id,
                existing_same_content.get("id"),
            )
            self._deps.brand_knowledge_ingestion_jobs.update_job_status(
                job_id=job_id,
                status="processing",
                current_step="backfill_brand_knowledge_json",
                full_knowledge_file_id=int(existing_same_content.get("id")),
                document_id=str(existing_same_content.get("document_id") or "") or None,
                content_hash=content_hash,
            )
            await self._backfill_brand_knowledge_json_from_full_markdown(
                brand=brand,
                brand_name=normalized_brand_name,
                markdown_text=markdown_text,
                source_name=markdown_file_name,
                source_task_id=resolved_source_task_id,
            )
            knowledge_json_backfill_status = "success"
            logger.info(
                "Brand AI knowledge json backfill completed task_id=%s job_id=%s full_knowledge_file_id=%s",
                task_id,
                job_id,
                existing_same_content.get("id"),
            )
        self._deps.brand_knowledge_ingestion_jobs.update_job_status(
            job_id=job_id,
            status="skipped",
            current_step="skipped",
            parse_status="success",
            mysql_status="skipped",
            milvus_status="skipped",
            facts_status="skipped",
            cleanup_status="skipped",
            full_knowledge_file_id=int(existing_same_content.get("id")),
            document_id=str(existing_same_content.get("document_id") or "") or None,
            content_hash=content_hash,
            error_message="相同内容已存在，默认跳过",
        )
        return {
            "status": "skipped",
            "skipped": True,
            "document_id": str(existing_same_content.get("document_id") or "") or None,
            "full_knowledge_file_id": int(existing_same_content.get("id")),
            "content_hash": content_hash,
            "markdown_oss_key": str(existing_same_content.get("oss_key") or "") or None,
            "markdown_oss_url": str(existing_same_content.get("oss_url") or "") or None,
            "change_origin": str(existing_same_content.get("change_origin") or "") or None,
            "content_type": resolved_content_type,
            "file_hash": source_hash,
            "file_size": source_file_size,
            "knowledge_json_backfill_status": knowledge_json_backfill_status,
        }
