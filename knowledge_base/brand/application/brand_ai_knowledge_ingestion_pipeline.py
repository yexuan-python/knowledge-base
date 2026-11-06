from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path
from typing import Any

from knowledge_base.brand.application.brand_ai_knowledge_ingestion_context import (
    BrandAiKnowledgeIngestionContextMixin,
)
from knowledge_base.brand.application.brand_ai_knowledge_ingestion_publish import (
    BrandAiKnowledgeIngestionPublishMixin,
)
from knowledge_base.brand.application.brand_ai_knowledge_ingestion_same_content import (
    BrandAiKnowledgeIngestionSameContentMixin,
)


logger = logging.getLogger(__name__)


class BrandAiKnowledgeIngestionPipelineMixin(
    BrandAiKnowledgeIngestionContextMixin,
    BrandAiKnowledgeIngestionPublishMixin,
    BrandAiKnowledgeIngestionSameContentMixin,
):
    async def _read_ingest_markdown_text(
        self,
        *,
        source_path: Path,
        normalized_filename: str,
        normalized_source_url: str | None,
        normalized_extension: str,
    ) -> str:
        if normalized_extension == "md":
            return self._normalize_uploaded_markdown_text(
                await asyncio.to_thread(source_path.read_text, encoding="utf-8-sig")
            )

        parsed_document = await asyncio.to_thread(
            lambda: self._deps.parser.parse_path(
                source_path,
                normalized_filename,
                source_url=normalized_source_url,
            )
        )
        return self._normalize_markdown_text(
            getattr(parsed_document, "markdown_text", "") or getattr(parsed_document, "text", "")
        )

    async def ingest_upload_task_file(
        self,
        *,
        task_id: str,
        upload_task_file_id: int,
        filename: str,
        brand_code: str,
        brand_name: str,
        force_reingest: bool,
        staged_path: Path | None,
        source_url: str | None,
        content_type: str | None,
        source_task_id: str | None = None,
        change_origin: str | None = None,
        job_id: str | None = None,
        backfill_brand_knowledge_json_empty_only: bool = False,
    ) -> dict[str, Any]:
        context = self._build_ingestion_context(
            task_id=task_id,
            upload_task_file_id=upload_task_file_id,
            filename=filename,
            brand_code=brand_code,
            brand_name=brand_name,
            force_reingest=force_reingest,
            source_url=source_url,
            change_origin=change_origin,
            job_id=job_id,
        )
        prepared_source = await self._prepare_ingestion_source(
            context=context,
            staged_path=staged_path,
            content_type=content_type,
            source_task_id=source_task_id,
        )
        self._create_ingestion_job(context=context, prepared_source=prepared_source)

        full_knowledge_file_id: int | None = None
        inserted_chunk_document = False
        try:
            self._deps.brand_knowledge_ingestion_jobs.update_job_status(
                job_id=context.job_id,
                status="processing",
                current_step="parse",
                parse_status="processing",
                document_id=prepared_source.document_id,
            )
            logger.info(
                "Brand AI knowledge parse started task_id=%s job_id=%s document_id=%s filename=%s revision_no=%s",
                context.task_id,
                context.job_id,
                prepared_source.document_id,
                context.normalized_filename,
                prepared_source.revision_no,
            )
            markdown_text = await self._read_ingest_markdown_text(
                source_path=prepared_source.source_path,
                normalized_filename=context.normalized_filename,
                normalized_source_url=context.normalized_source_url,
                normalized_extension=context.parsed_filename.normalized_extension,
            )
            if not markdown_text:
                raise ValueError(f"无法解析出有效 Markdown：{context.normalized_filename}")
            content_hash = hashlib.sha256(markdown_text.encode("utf-8")).hexdigest()
            logger.info(
                "Brand AI knowledge parse completed task_id=%s job_id=%s filename=%s markdown_chars=%s content_hash=%s",
                context.task_id,
                context.job_id,
                context.normalized_filename,
                len(markdown_text),
                content_hash,
            )

            markdown_file_name = self._build_markdown_file_name(
                brand_name=context.normalized_brand_name,
                version_no=context.parsed_filename.version_no,
                knowledge_date=context.parsed_filename.knowledge_date,
            )
            pdf_file_name = self._build_pdf_file_name(markdown_file_name)

            existing_same_content = self._deps.brand_full_knowledge.get_by_brand_code_and_content_hash(
                brand_code=context.normalized_brand_code,
                content_hash=content_hash,
            )
            skipped_result = await self._maybe_skip_existing_same_content(
                task_id=context.task_id,
                job_id=context.job_id,
                brand=context.brand,
                normalized_brand_code=context.normalized_brand_code,
                normalized_brand_name=context.normalized_brand_name,
                markdown_text=markdown_text,
                markdown_file_name=markdown_file_name,
                content_hash=content_hash,
                resolved_content_type=prepared_source.resolved_content_type,
                source_hash=prepared_source.source_hash,
                source_file_size=prepared_source.source_file_size,
                existing_same_content=existing_same_content,
                force_reingest=context.force_reingest,
                backfill_brand_knowledge_json_empty_only=backfill_brand_knowledge_json_empty_only,
                resolved_source_task_id=prepared_source.resolved_source_task_id,
            )
            if skipped_result is not None:
                return skipped_result

            existing_full_knowledge_file = prepared_source.existing_full_knowledge_file
            if existing_full_knowledge_file is not None:
                existing_content_hash = str(existing_full_knowledge_file.get("content_hash") or "").strip()
                if existing_content_hash and existing_content_hash != content_hash:
                    raise ValueError("同一来源任务已存在不同内容的品牌AI知识库记录，不能复用")
                full_knowledge_file_id = int(existing_full_knowledge_file["id"])
                logger.info(
                    "Brand AI knowledge mysql record reused task_id=%s job_id=%s full_knowledge_file_id=%s document_id=%s",
                    context.task_id,
                    context.job_id,
                    full_knowledge_file_id,
                    prepared_source.document_id,
                )
            else:
                logger.info(
                    "Brand AI knowledge mysql create started task_id=%s job_id=%s document_id=%s filename=%s version=%s knowledge_date=%s revision=%s",
                    context.task_id,
                    context.job_id,
                    prepared_source.document_id,
                    markdown_file_name,
                    context.parsed_filename.version_no,
                    context.parsed_filename.knowledge_date,
                    prepared_source.revision_no,
                )
                full_knowledge_file_id = self._create_full_knowledge_file_record(
                    brand=context.brand,
                    normalized_brand_code=context.normalized_brand_code,
                    normalized_brand_name=context.normalized_brand_name,
                    parsed_filename=context.parsed_filename,
                    revision_no=prepared_source.revision_no,
                    markdown_file_name=markdown_file_name,
                    pdf_file_name=pdf_file_name,
                    markdown_text=markdown_text,
                    content_hash=content_hash,
                    document_id=prepared_source.document_id,
                    resolved_source_task_id=prepared_source.resolved_source_task_id,
                    change_origin=context.change_origin,
                )
                logger.info(
                    "Brand AI knowledge mysql create completed task_id=%s job_id=%s full_knowledge_file_id=%s document_id=%s",
                    context.task_id,
                    context.job_id,
                    full_knowledge_file_id,
                    prepared_source.document_id,
                )
            self._deps.brand_knowledge_ingestion_jobs.update_job_status(
                job_id=context.job_id,
                status="processing",
                current_step="write_mysql",
                mysql_status="success",
                full_knowledge_file_id=full_knowledge_file_id,
                document_id=prepared_source.document_id,
                content_hash=content_hash,
            )

            markdown_oss_key, markdown_oss_url, pdf_oss_key, pdf_oss_url = await self._upload_knowledge_assets(
                task_id=context.task_id,
                job_id=context.job_id,
                full_knowledge_file_id=full_knowledge_file_id,
                document_id=prepared_source.document_id,
                normalized_brand_name=context.normalized_brand_name,
                markdown_file_name=markdown_file_name,
                pdf_file_name=pdf_file_name,
                markdown_text=markdown_text,
                content_hash=content_hash,
            )

            await self._write_knowledge_vectors_and_facts(
                task_id=context.task_id,
                job_id=context.job_id,
                full_knowledge_file_id=full_knowledge_file_id,
                document_id=prepared_source.document_id,
                normalized_brand_code=context.normalized_brand_code,
                normalized_brand_name=context.normalized_brand_name,
                markdown_file_name=markdown_file_name,
                markdown_oss_url=markdown_oss_url,
                markdown_text=markdown_text,
                parsed_filename=context.parsed_filename,
                revision_no=prepared_source.revision_no,
                content_hash=content_hash,
            )
            inserted_chunk_document = True

            cleanup_result, knowledge_json_backfill_status = await self._promote_and_cleanup_knowledge(
                task_id=context.task_id,
                job_id=context.job_id,
                brand=context.brand,
                normalized_brand_code=context.normalized_brand_code,
                normalized_brand_name=context.normalized_brand_name,
                full_knowledge_file_id=full_knowledge_file_id,
                document_id=prepared_source.document_id,
                knowledge_revision=context.knowledge_revision,
                markdown_text=markdown_text,
                markdown_file_name=markdown_file_name,
                content_hash=content_hash,
                resolved_source_task_id=prepared_source.resolved_source_task_id,
                backfill_brand_knowledge_json_empty_only=backfill_brand_knowledge_json_empty_only,
            )
            self._mark_ingestion_success(
                context=context,
                prepared_source=prepared_source,
                full_knowledge_file_id=full_knowledge_file_id,
                content_hash=content_hash,
            )
            return {
                "status": "success",
                "skipped": False,
                "document_id": prepared_source.document_id,
                "full_knowledge_file_id": full_knowledge_file_id,
                "content_hash": content_hash,
                "markdown_oss_key": markdown_oss_key,
                "markdown_oss_url": markdown_oss_url,
                "pdf_oss_key": pdf_oss_key,
                "pdf_oss_url": pdf_oss_url,
                "knowledge_revision": context.knowledge_revision,
                "change_origin": context.change_origin,
                "content_type": prepared_source.resolved_content_type,
                "file_hash": prepared_source.source_hash,
                "file_size": prepared_source.source_file_size,
                "cleanup": cleanup_result,
                "knowledge_json_backfill_status": knowledge_json_backfill_status,
            }
        except Exception as exc:
            self._handle_ingestion_failure(
                context=context,
                prepared_source=prepared_source,
                full_knowledge_file_id=full_knowledge_file_id,
                inserted_chunk_document=inserted_chunk_document,
                exc=exc,
            )
            raise
        finally:
            if prepared_source.cleanup_source_path:
                prepared_source.source_path.unlink(missing_ok=True)
