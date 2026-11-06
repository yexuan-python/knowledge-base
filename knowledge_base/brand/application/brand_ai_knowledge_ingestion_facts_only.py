from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path


logger = logging.getLogger(__name__)


class BrandAiKnowledgeIngestionFactsOnlyMixin:
    async def ingest_facts_only_upload(
        self,
        *,
        task_id: str,
        filename: str,
        brand_code: str,
        brand_name: str,
        staged_path: Path | None,
        source_url: str | None,
        content_type: str | None,
    ) -> dict:
        normalized_brand_code = str(brand_code or "").strip()
        normalized_brand_name = str(brand_name or "").strip()
        normalized_filename = Path(str(filename or "").strip()).name
        normalized_source_url = str(source_url or "").strip() or None
        if not normalized_brand_code:
            raise ValueError("brand_code 不能为空")
        if not normalized_brand_name:
            raise ValueError("brand_name 不能为空")
        if not normalized_filename:
            raise ValueError("facts 文件名不能为空")
        if Path(normalized_filename).suffix.lower() != ".md":
            raise ValueError("facts-only 上传仅支持 Markdown 文件")
        if self._deps.brand_knowledge_facts is None or self._deps.store is None or self._deps.embeddings is None:
            raise RuntimeError("facts 入库依赖未初始化")
        logger.info(
            "Brand facts-only ingest started task_id=%s brand_code=%s brand_name=%s filename=%s source_url=%s",
            task_id,
            normalized_brand_code,
            normalized_brand_name,
            normalized_filename,
            normalized_source_url,
        )

        brand = self._deps.brands.get_brand_by_code(normalized_brand_code)
        if brand is None:
            raise ValueError("品牌不存在，请先建品牌")
        persisted_brand_name = str(brand.get("brand_name") or "").strip()
        if persisted_brand_name != normalized_brand_name:
            raise ValueError("请求中的 brand_code / brand_name 不匹配")

        source_path, resolved_content_type, source_file_size, cleanup_source_path = await self._prepare_source_file(
            filename=normalized_filename,
            staged_path=staged_path,
            source_url=normalized_source_url,
            content_type=content_type,
            brand_code=normalized_brand_code,
        )
        logger.info(
            "Brand facts-only source prepared task_id=%s brand_code=%s filename=%s source_path=%s content_type=%s file_size=%s cleanup_source_path=%s",
            task_id,
            normalized_brand_code,
            normalized_filename,
            source_path,
            resolved_content_type,
            source_file_size,
            cleanup_source_path,
        )
        try:
            logger.info(
                "Brand facts-only hash compute started task_id=%s brand_code=%s filename=%s",
                task_id,
                normalized_brand_code,
                normalized_filename,
            )
            source_hash = await asyncio.to_thread(self._compute_sha256_for_path, source_path)
            logger.info(
                "Brand facts-only hash compute completed task_id=%s brand_code=%s filename=%s file_hash=%s",
                task_id,
                normalized_brand_code,
                normalized_filename,
                source_hash,
            )
            logger.info(
                "Brand facts-only markdown read started task_id=%s brand_code=%s filename=%s",
                task_id,
                normalized_brand_code,
                normalized_filename,
            )
            markdown_text = self._normalize_uploaded_markdown_text(
                await asyncio.to_thread(source_path.read_text, encoding="utf-8-sig")
            )
            if not markdown_text:
                raise ValueError(f"无法解析出有效 Markdown：{normalized_filename}")
            logger.info(
                "Brand facts-only markdown read completed task_id=%s brand_code=%s filename=%s markdown_chars=%s",
                task_id,
                normalized_brand_code,
                normalized_filename,
                len(markdown_text),
            )

            content_hash = hashlib.sha256(markdown_text.encode("utf-8")).hexdigest()
            document_id = self._build_facts_only_document_id(
                brand_code=normalized_brand_code,
                content_hash=content_hash,
            )
            logger.info(
                "Brand facts-only facts extraction started task_id=%s brand_code=%s filename=%s document_id=%s content_hash=%s",
                task_id,
                normalized_brand_code,
                normalized_filename,
                document_id,
                content_hash,
            )
            fact_rows = await self._build_fact_rows(
                brand_code=normalized_brand_code,
                brand_name=normalized_brand_name,
                source_document_id=document_id,
                full_knowledge_file_id=None,
                version_no=None,
                knowledge_date=None,
                source_name=normalized_filename,
                markdown_text=markdown_text,
            )
            logger.info(
                "Brand facts-only facts extraction completed task_id=%s brand_code=%s filename=%s document_id=%s fact_count=%s",
                task_id,
                normalized_brand_code,
                normalized_filename,
                document_id,
                len(fact_rows),
            )
            logger.info(
                "Brand facts-only fact upsert started task_id=%s brand_code=%s document_id=%s fact_count=%s",
                task_id,
                normalized_brand_code,
                document_id,
                len(fact_rows),
            )
            await self._upsert_facts(fact_rows)
            logger.info(
                "Brand facts-only fact upsert completed task_id=%s brand_code=%s document_id=%s fact_count=%s",
                task_id,
                normalized_brand_code,
                document_id,
                len(fact_rows),
            )
            logger.info(
                "Brand facts-only old fact cleanup started task_id=%s brand_code=%s keep_document_id=%s",
                task_id,
                normalized_brand_code,
                document_id,
            )
            cleanup_result = self._cleanup_old_facts(
                brand_code=normalized_brand_code,
                keep_document_id=document_id,
            )
            logger.info(
                "Brand facts-only old fact cleanup completed task_id=%s brand_code=%s keep_document_id=%s deleted_fact_count=%s",
                task_id,
                normalized_brand_code,
                document_id,
                cleanup_result.get("deleted_fact_count"),
            )
            logger.info(
                "Brand facts-only ingest completed task_id=%s brand_code=%s brand_name=%s document_id=%s fact_count=%s deleted_fact_count=%s",
                task_id,
                normalized_brand_code,
                normalized_brand_name,
                document_id,
                len(fact_rows),
                cleanup_result.get("deleted_fact_count"),
            )
            return {
                "status": "success",
                "brand_code": normalized_brand_code,
                "brand_name": normalized_brand_name,
                "document_id": document_id,
                "fact_count": len(fact_rows),
                "deleted_fact_count": int(cleanup_result.get("deleted_fact_count") or 0),
                "content_hash": content_hash,
                "content_type": resolved_content_type,
                "file_hash": source_hash,
                "file_size": source_file_size,
                "file_name": normalized_filename,
            }
        finally:
            if cleanup_source_path:
                logger.info(
                    "Brand facts-only source cleanup task_id=%s source_path=%s exists_before_cleanup=%s",
                    task_id,
                    source_path,
                    source_path.exists(),
                )
                source_path.unlink(missing_ok=True)
