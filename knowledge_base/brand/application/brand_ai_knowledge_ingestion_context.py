from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from knowledge_base.brand.ai_knowledge_filename import parse_ai_knowledge_filename
from knowledge_base.shared.utils import (
    KNOWLEDGE_REVISION_CHANGE_ATTACHMENT,
    build_knowledge_revision,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BrandAiKnowledgeIngestionContext:
    task_id: str
    upload_task_file_id: int
    normalized_brand_code: str
    normalized_brand_name: str
    normalized_filename: str
    normalized_source_url: str | None
    force_reingest: bool
    change_origin: str
    job_id: str
    brand: dict[str, Any]
    parsed_filename: Any
    knowledge_revision: str


@dataclass(frozen=True)
class BrandAiKnowledgePreparedSource:
    source_path: Path
    resolved_content_type: str | None
    source_file_size: int
    cleanup_source_path: bool
    source_hash: str
    revision_no: int
    document_id: str
    resolved_source_task_id: str
    existing_full_knowledge_file: dict[str, Any] | None = None


class BrandAiKnowledgeIngestionContextMixin:
    def _build_ingestion_context(
        self,
        *,
        task_id: str,
        upload_task_file_id: int,
        filename: str,
        brand_code: str,
        brand_name: str,
        force_reingest: bool,
        source_url: str | None,
        change_origin: str | None,
        job_id: str | None,
    ) -> BrandAiKnowledgeIngestionContext:
        normalized_brand_code = str(brand_code or "").strip()
        normalized_brand_name = str(brand_name or "").strip()
        normalized_filename = Path(str(filename or "").strip()).name
        normalized_source_url = str(source_url or "").strip() or None
        normalized_change_origin = str(change_origin or "frontend").strip() or "frontend"
        if not normalized_brand_code:
            raise ValueError("brand_code 不能为空")
        if not normalized_brand_name:
            raise ValueError("brand_name 不能为空")
        if not normalized_filename:
            raise ValueError("正式知识库文件名不能为空")
        if self._deps.brand_knowledge_facts is None or self._deps.brand_knowledge_ingestion_jobs is None:
            raise RuntimeError("正式知识库入库依赖未初始化")
        resolved_job_id = str(
            job_id or self._build_job_id(task_id=task_id, upload_task_file_id=upload_task_file_id)
        ).strip()

        logger.info(
            "Brand AI knowledge ingest started task_id=%s file_id=%s job_id=%s filename=%s brand_code=%s brand_name=%s force_reingest=%s",
            task_id,
            upload_task_file_id,
            resolved_job_id,
            normalized_filename,
            normalized_brand_code,
            normalized_brand_name,
            force_reingest,
        )
        parsed_filename = parse_ai_knowledge_filename(normalized_filename)
        if parsed_filename is None:
            raise ValueError("正式知识库文件名不符合规范")
        if parsed_filename.brand_name != normalized_brand_name:
            raise ValueError("文件名中的品牌名与请求中的 brand_name 不一致")

        brand = self._deps.brands.get_brand_by_code(normalized_brand_code)
        if brand is None:
            raise ValueError("品牌不存在，请先建品牌")
        persisted_brand_name = str(brand.get("brand_name") or "").strip()
        if persisted_brand_name != normalized_brand_name:
            raise ValueError("请求中的 brand_code / brand_name 不匹配")
        knowledge_revision = build_knowledge_revision(
            brand_code=normalized_brand_code,
            brand_name=normalized_brand_name,
            current_revision=str(brand.get("knowledge_revision") or "").strip() or None,
            change_type=KNOWLEDGE_REVISION_CHANGE_ATTACHMENT,
        )

        latest = self._deps.brand_full_knowledge.get_latest_by_brand_code(brand_code=normalized_brand_code)
        latest_version_no = int(latest.get("version_no") or 0) if latest else None
        latest_knowledge_date = str(latest.get("knowledge_date") or "").strip() if latest else ""
        logger.info(
            "Brand AI knowledge version checked task_id=%s filename=%s upload_version=%s knowledge_date=%s latest_version=%s latest_knowledge_date=%s",
            task_id,
            normalized_filename,
            parsed_filename.version_no,
            parsed_filename.knowledge_date,
            latest_version_no,
            latest_knowledge_date or None,
        )
        upload_is_older_date = bool(latest_knowledge_date) and parsed_filename.knowledge_date < latest_knowledge_date
        upload_is_missing_latest_date_lower_version = (
            not latest_knowledge_date
            and latest_version_no is not None
            and parsed_filename.version_no < latest_version_no
        )
        upload_is_same_date_lower_version = (
            parsed_filename.knowledge_date == latest_knowledge_date
            and latest_version_no is not None
            and parsed_filename.version_no < latest_version_no
        )
        if (
            upload_is_older_date
            or upload_is_missing_latest_date_lower_version
            or upload_is_same_date_lower_version
        ) and not force_reingest:
            raise ValueError(
                "知识库版本过旧："
                f"当前最新版本为 V{latest_version_no}_{latest_knowledge_date or '未知日期'}，"
                f"上传版本为 V{parsed_filename.version_no}_{parsed_filename.knowledge_date}"
            )

        return BrandAiKnowledgeIngestionContext(
            task_id=task_id,
            upload_task_file_id=upload_task_file_id,
            normalized_brand_code=normalized_brand_code,
            normalized_brand_name=normalized_brand_name,
            normalized_filename=normalized_filename,
            normalized_source_url=normalized_source_url,
            force_reingest=force_reingest,
            change_origin=normalized_change_origin,
            job_id=resolved_job_id,
            brand=brand,
            parsed_filename=parsed_filename,
            knowledge_revision=knowledge_revision,
        )

    async def _prepare_ingestion_source(
        self,
        *,
        context: BrandAiKnowledgeIngestionContext,
        staged_path: Path | None,
        content_type: str | None,
        source_task_id: str | None,
    ) -> BrandAiKnowledgePreparedSource:
        logger.info(
            "Brand AI knowledge source prepare started task_id=%s filename=%s",
            context.task_id,
            context.normalized_filename,
        )
        source_path, resolved_content_type, source_file_size, cleanup_source_path = await self._prepare_source_file(
            filename=context.normalized_filename,
            staged_path=staged_path,
            source_url=context.normalized_source_url,
            content_type=content_type,
            brand_code=context.normalized_brand_code,
        )
        source_hash = await asyncio.to_thread(self._compute_sha256_for_path, source_path)
        logger.info(
            "Brand AI knowledge source prepared task_id=%s filename=%s content_type=%s file_size=%s file_hash=%s",
            context.task_id,
            context.normalized_filename,
            resolved_content_type,
            source_file_size,
            source_hash,
        )
        resolved_source_task_id = str(source_task_id or context.task_id or "").strip() or context.task_id
        markdown_file_name = self._build_markdown_file_name(
            brand_name=context.normalized_brand_name,
            version_no=context.parsed_filename.version_no,
            knowledge_date=context.parsed_filename.knowledge_date,
        )
        existing_full_knowledge_file = None
        get_by_source_task_file = getattr(
            self._deps.brand_full_knowledge,
            "get_by_brand_code_source_task_file",
            None,
        )
        if callable(get_by_source_task_file):
            existing_full_knowledge_file = get_by_source_task_file(
                brand_code=context.normalized_brand_code,
                source_task_id=resolved_source_task_id,
                file_name=markdown_file_name,
            )
        if existing_full_knowledge_file and existing_full_knowledge_file.get("revision_no"):
            revision_no = int(existing_full_knowledge_file["revision_no"])
        else:
            revision_no = self._deps.brand_full_knowledge.get_next_revision_no(
                brand_code=context.normalized_brand_code,
                version_no=context.parsed_filename.version_no,
                knowledge_date=context.parsed_filename.knowledge_date,
            )
        document_id = self._build_document_id(
            brand_code=context.normalized_brand_code,
            version_no=context.parsed_filename.version_no,
            knowledge_date=context.parsed_filename.knowledge_date,
            revision_no=revision_no,
        )
        if existing_full_knowledge_file:
            existing_document_id = str(existing_full_knowledge_file.get("document_id") or "").strip()
            if existing_document_id:
                document_id = existing_document_id
        return BrandAiKnowledgePreparedSource(
            source_path=source_path,
            resolved_content_type=resolved_content_type,
            source_file_size=source_file_size,
            cleanup_source_path=cleanup_source_path,
            source_hash=source_hash,
            revision_no=revision_no,
            document_id=document_id,
            resolved_source_task_id=resolved_source_task_id,
            existing_full_knowledge_file=existing_full_knowledge_file,
        )

    def _create_ingestion_job(
        self,
        *,
        context: BrandAiKnowledgeIngestionContext,
        prepared_source: BrandAiKnowledgePreparedSource,
    ) -> None:
        self._deps.brand_knowledge_ingestion_jobs.create_job(
            job_id=context.job_id,
            brand_code=context.normalized_brand_code,
            brand_name=context.normalized_brand_name,
            version_no=context.parsed_filename.version_no,
            knowledge_date=context.parsed_filename.knowledge_date,
            revision_no=prepared_source.revision_no,
            original_filename=context.normalized_filename,
            source_ext=context.parsed_filename.suffix.lower(),
            force_reingest=context.force_reingest,
            status="processing",
            current_step="parse",
            document_id=prepared_source.document_id,
        )

    def _mark_ingestion_success(
        self,
        *,
        context: BrandAiKnowledgeIngestionContext,
        prepared_source: BrandAiKnowledgePreparedSource,
        full_knowledge_file_id: int,
        content_hash: str,
    ) -> None:
        self._deps.brand_full_knowledge.update_ingestion_result(
            file_id=full_knowledge_file_id,
            ingest_status="success",
            milvus_status="success",
            facts_status="success",
        )
        self._deps.brand_knowledge_ingestion_jobs.update_job_status(
            job_id=context.job_id,
            status="success",
            current_step="completed",
            parse_status="success",
            pdf_status="success",
            mysql_status="success",
            milvus_status="success",
            facts_status="success",
            cleanup_status="success",
            full_knowledge_file_id=full_knowledge_file_id,
            document_id=prepared_source.document_id,
            content_hash=content_hash,
        )
        logger.info(
            "Brand AI knowledge ingest completed task_id=%s job_id=%s full_knowledge_file_id=%s document_id=%s knowledge_revision=%s",
            context.task_id,
            context.job_id,
            full_knowledge_file_id,
            prepared_source.document_id,
            context.knowledge_revision,
        )

    def _handle_ingestion_failure(
        self,
        *,
        context: BrandAiKnowledgeIngestionContext,
        prepared_source: BrandAiKnowledgePreparedSource,
        full_knowledge_file_id: int | None,
        inserted_chunk_document: bool,
        exc: Exception,
    ) -> None:
        logger.exception(
            "Brand AI knowledge ingest failed task_id=%s job_id=%s full_knowledge_file_id=%s document_id=%s filename=%s",
            context.task_id,
            context.job_id,
            full_knowledge_file_id,
            prepared_source.document_id,
            context.normalized_filename,
        )
        if inserted_chunk_document:
            try:
                self._deps.store.delete_documents_by_ids([prepared_source.document_id])
            except Exception as cleanup_exc:  # noqa: BLE001
                logger.warning(
                    "Failed to cleanup inserted brand AI knowledge chunks after ingest failure task_id=%s job_id=%s document_id=%s error=%s",
                    context.task_id,
                    context.job_id,
                    prepared_source.document_id,
                    cleanup_exc,
                    exc_info=True,
                )
        if full_knowledge_file_id is not None:
            self._deps.brand_full_knowledge.update_ingestion_result(
                file_id=full_knowledge_file_id,
                ingest_status="failed",
                milvus_status="failed",
                facts_status="failed",
                error_message=str(exc),
            )
        self._deps.brand_knowledge_ingestion_jobs.update_job_status(
            job_id=context.job_id,
            status="failed",
            current_step="failed",
            error_message=str(exc),
            full_knowledge_file_id=full_knowledge_file_id,
            document_id=prepared_source.document_id,
        )
