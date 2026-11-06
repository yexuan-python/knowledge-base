from __future__ import annotations

import logging
from typing import Any


logger = logging.getLogger(__name__)


class BrandAiKnowledgeIngestionPublishMixin:
    def _create_full_knowledge_file_record(
        self,
        *,
        brand: dict[str, Any],
        normalized_brand_code: str,
        normalized_brand_name: str,
        parsed_filename: Any,
        revision_no: int,
        markdown_file_name: str,
        pdf_file_name: str,
        markdown_text: str,
        content_hash: str,
        document_id: str,
        resolved_source_task_id: str,
        change_origin: str,
    ) -> int:
        return self._deps.brand_full_knowledge.create_brand_full_knowledge_file(
            brand_id=int(brand["id"]),
            brand_code=normalized_brand_code,
            brand_name=normalized_brand_name,
            version_no=parsed_filename.version_no,
            knowledge_date=parsed_filename.knowledge_date,
            revision_no=revision_no,
            file_name=markdown_file_name,
            source_ext=parsed_filename.suffix.lower(),
            pdf_file_name=pdf_file_name,
            oss_key=None,
            oss_url=None,
            pdf_oss_key=None,
            pdf_oss_url=None,
            content_markdown=markdown_text,
            content_hash=content_hash,
            document_id=document_id,
            is_latest=False,
            ingest_status="processing",
            milvus_status="pending",
            facts_status="pending",
            conflict_count=0,
            conflicts_json=[],
            source_task_id=resolved_source_task_id,
            change_origin=change_origin,
        )

    async def _upload_knowledge_assets(
        self,
        *,
        task_id: str,
        job_id: str,
        full_knowledge_file_id: int,
        document_id: str,
        normalized_brand_name: str,
        markdown_file_name: str,
        pdf_file_name: str,
        markdown_text: str,
        content_hash: str,
    ) -> tuple[str, str, str, str]:
        self._deps.brand_knowledge_ingestion_jobs.update_job_status(
            job_id=job_id,
            status="processing",
            current_step="upload_assets",
            parse_status="success",
            content_hash=content_hash,
            full_knowledge_file_id=full_knowledge_file_id,
            document_id=document_id,
        )
        logger.info(
            "Brand AI knowledge markdown upload started task_id=%s job_id=%s full_knowledge_file_id=%s filename=%s",
            task_id,
            job_id,
            full_knowledge_file_id,
            markdown_file_name,
        )
        markdown_oss_key, markdown_oss_url = await self._upload_markdown_file(
            brand_name=normalized_brand_name,
            filename=markdown_file_name,
            markdown_text=markdown_text,
        )
        logger.info(
            "Brand AI knowledge markdown upload completed task_id=%s job_id=%s full_knowledge_file_id=%s oss_key=%s",
            task_id,
            job_id,
            full_knowledge_file_id,
            markdown_oss_key,
        )

        self._deps.brand_knowledge_ingestion_jobs.update_job_status(
            job_id=job_id,
            status="processing",
            current_step="render_pdf",
            pdf_status="processing",
            content_hash=content_hash,
            full_knowledge_file_id=full_knowledge_file_id,
            document_id=document_id,
        )
        logger.info(
            "Brand AI knowledge pdf render started task_id=%s job_id=%s full_knowledge_file_id=%s",
            task_id,
            job_id,
            full_knowledge_file_id,
        )
        pdf_bytes = await self._render_pdf(markdown_text=markdown_text, title=normalized_brand_name)
        logger.info(
            "Brand AI knowledge pdf upload started task_id=%s job_id=%s full_knowledge_file_id=%s pdf_size=%s filename=%s",
            task_id,
            job_id,
            full_knowledge_file_id,
            len(pdf_bytes),
            pdf_file_name,
        )
        pdf_oss_key, pdf_oss_url = await self._upload_pdf_file(
            brand_name=normalized_brand_name,
            filename=pdf_file_name,
            pdf_bytes=pdf_bytes,
        )
        logger.info(
            "Brand AI knowledge pdf upload completed task_id=%s job_id=%s full_knowledge_file_id=%s pdf_oss_key=%s",
            task_id,
            job_id,
            full_knowledge_file_id,
            pdf_oss_key,
        )

        self._deps.brand_full_knowledge.update_storage_assets(
            file_id=full_knowledge_file_id,
            oss_key=markdown_oss_key,
            oss_url=markdown_oss_url,
            pdf_oss_key=pdf_oss_key,
            pdf_oss_url=pdf_oss_url,
        )
        logger.info(
            "Brand AI knowledge storage assets updated task_id=%s job_id=%s full_knowledge_file_id=%s",
            task_id,
            job_id,
            full_knowledge_file_id,
        )
        self._deps.brand_knowledge_ingestion_jobs.update_job_status(
            job_id=job_id,
            status="processing",
            current_step="upload_assets",
            mysql_status="success",
            pdf_status="success",
            full_knowledge_file_id=full_knowledge_file_id,
            document_id=document_id,
            content_hash=content_hash,
        )
        return markdown_oss_key, markdown_oss_url, pdf_oss_key, pdf_oss_url

    async def _write_knowledge_vectors_and_facts(
        self,
        *,
        task_id: str,
        job_id: str,
        full_knowledge_file_id: int,
        document_id: str,
        normalized_brand_code: str,
        normalized_brand_name: str,
        markdown_file_name: str,
        markdown_oss_url: str,
        markdown_text: str,
        parsed_filename: Any,
        revision_no: int,
        content_hash: str,
    ) -> None:
        self._deps.brand_knowledge_ingestion_jobs.update_job_status(
            job_id=job_id,
            status="processing",
            current_step="write_milvus",
            milvus_status="processing",
            full_knowledge_file_id=full_knowledge_file_id,
            document_id=document_id,
            content_hash=content_hash,
        )
        logger.info(
            "Brand AI knowledge milvus write started task_id=%s job_id=%s full_knowledge_file_id=%s document_id=%s",
            task_id,
            job_id,
            full_knowledge_file_id,
            document_id,
        )
        await self._write_document_chunks(
            document_id=document_id,
            brand_code=normalized_brand_code,
            brand_name=normalized_brand_name,
            source_name=markdown_file_name,
            source_url=markdown_oss_url,
            markdown_text=markdown_text,
            version_no=parsed_filename.version_no,
            knowledge_date=parsed_filename.knowledge_date,
            revision_no=revision_no,
            full_knowledge_file_id=full_knowledge_file_id,
            content_hash=content_hash,
        )
        self._deps.brand_full_knowledge.update_ingestion_result(
            file_id=full_knowledge_file_id,
            ingest_status="processing",
            milvus_status="success",
        )
        logger.info(
            "Brand AI knowledge milvus write completed task_id=%s job_id=%s full_knowledge_file_id=%s document_id=%s",
            task_id,
            job_id,
            full_knowledge_file_id,
            document_id,
        )

        self._deps.brand_knowledge_ingestion_jobs.update_job_status(
            job_id=job_id,
            status="processing",
            current_step="extract_facts",
            facts_status="processing",
            full_knowledge_file_id=full_knowledge_file_id,
            document_id=document_id,
            content_hash=content_hash,
        )
        logger.info(
            "Brand AI knowledge facts extraction started task_id=%s job_id=%s full_knowledge_file_id=%s",
            task_id,
            job_id,
            full_knowledge_file_id,
        )
        fact_rows = await self._build_fact_rows(
            brand_code=normalized_brand_code,
            brand_name=normalized_brand_name,
            source_document_id=document_id,
            full_knowledge_file_id=full_knowledge_file_id,
            version_no=parsed_filename.version_no,
            knowledge_date=parsed_filename.knowledge_date,
            source_name=markdown_file_name,
            markdown_text=markdown_text,
        )
        logger.info(
            "Brand AI knowledge facts extraction completed task_id=%s job_id=%s full_knowledge_file_id=%s fact_count=%s",
            task_id,
            job_id,
            full_knowledge_file_id,
            len(fact_rows),
        )
        await self._upsert_facts(fact_rows)
        self._deps.brand_full_knowledge.update_ingestion_result(
            file_id=full_knowledge_file_id,
            ingest_status="processing",
            facts_status="success",
        )

    async def _promote_and_cleanup_knowledge(
        self,
        *,
        task_id: str,
        job_id: str,
        brand: dict[str, Any],
        normalized_brand_code: str,
        normalized_brand_name: str,
        full_knowledge_file_id: int,
        document_id: str,
        knowledge_revision: str,
        markdown_text: str,
        markdown_file_name: str,
        content_hash: str,
        resolved_source_task_id: str,
        backfill_brand_knowledge_json_empty_only: bool,
    ) -> tuple[dict[str, Any], str]:
        self._deps.brand_knowledge_ingestion_jobs.update_job_status(
            job_id=job_id,
            status="processing",
            current_step="promote_latest",
            cleanup_status="processing",
            full_knowledge_file_id=full_knowledge_file_id,
            document_id=document_id,
            content_hash=content_hash,
        )
        logger.info(
            "Brand AI knowledge promote latest started task_id=%s job_id=%s full_knowledge_file_id=%s knowledge_revision=%s",
            task_id,
            job_id,
            full_knowledge_file_id,
            knowledge_revision,
        )
        self._deps.brand_full_knowledge.promote_latest(
            brand_code=normalized_brand_code,
            file_id=full_knowledge_file_id,
            knowledge_revision=knowledge_revision,
        )
        knowledge_json_backfill_status = "skipped"
        if backfill_brand_knowledge_json_empty_only:
            logger.info(
                "Brand AI knowledge json backfill started task_id=%s job_id=%s full_knowledge_file_id=%s",
                task_id,
                job_id,
                full_knowledge_file_id,
            )
            self._deps.brand_knowledge_ingestion_jobs.update_job_status(
                job_id=job_id,
                status="processing",
                current_step="backfill_brand_knowledge_json",
                full_knowledge_file_id=full_knowledge_file_id,
                document_id=document_id,
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
                full_knowledge_file_id,
            )
        cleanup_result = self._cleanup_old_versions(
            brand_code=normalized_brand_code,
            keep_document_id=document_id,
        )
        logger.info(
            "Brand AI knowledge cleanup completed task_id=%s job_id=%s full_knowledge_file_id=%s cleanup=%s",
            task_id,
            job_id,
            full_knowledge_file_id,
            cleanup_result,
        )
        return cleanup_result, knowledge_json_backfill_status
