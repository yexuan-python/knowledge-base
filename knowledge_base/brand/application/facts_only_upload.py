from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BrandFactsOnlyUploadDependencies:
    upload_task_application: Any
    brand_ai_knowledge_ingestion: Any


class BrandFactsOnlyUploadService:
    def __init__(self, dependencies: BrandFactsOnlyUploadDependencies) -> None:
        self._deps = dependencies

    async def ingest_brand_facts_only(
        self,
        *,
        files: list[Any],
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        self._deps.upload_task_application._validate_documents_upload_metadata(metadata)
        if len(files) != 1:
            raise ValueError("facts-only 上传当前仅支持单文件")

        prepared_metadata = self._deps.upload_task_application._resolve_metadata_brand_name(metadata)
        brand_name = prepared_metadata or ""
        brand_code = str(metadata.get("brand_code") or "").strip()
        if not brand_code or not brand_name:
            raise ValueError("metadata 必须包含有效的 brand_code 和 brand_name")

        upload = files[0]
        filename = upload.filename or f"brand-facts-{uuid4().hex}.md"
        temp_path: Path | None = None
        task_id = f"brand-facts-only:{brand_code}:{uuid4().hex}"[:128]
        logger.info(
            "Brand facts upload service started task_id=%s brand_code=%s brand_name=%s filename=%s content_type=%s",
            task_id,
            brand_code,
            brand_name,
            filename,
            upload.content_type,
        )
        try:
            suffix = Path(filename).suffix or ".tmp"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                temp_path = Path(tmp.name)
            logger.info(
                "Brand facts upload staging started task_id=%s temp_path=%s filename=%s",
                task_id,
                temp_path,
                filename,
            )
            await upload.seek(0)
            with temp_path.open("wb") as staged_file:
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    staged_file.write(chunk)
            staged_file_size = temp_path.stat().st_size if temp_path.exists() else None
            logger.info(
                "Brand facts upload staging completed task_id=%s temp_path=%s filename=%s file_size=%s",
                task_id,
                temp_path,
                filename,
                staged_file_size,
            )
            await upload.seek(0)
            result = await self._deps.brand_ai_knowledge_ingestion.ingest_facts_only_upload(
                task_id=task_id,
                filename=filename,
                brand_code=brand_code,
                brand_name=brand_name,
                staged_path=temp_path,
                source_url=None,
                content_type=upload.content_type,
            )
            logger.info(
                "Brand facts upload service completed task_id=%s brand_code=%s brand_name=%s document_id=%s fact_count=%s deleted_fact_count=%s",
                task_id,
                result.get("brand_code"),
                result.get("brand_name"),
                result.get("document_id"),
                result.get("fact_count"),
                result.get("deleted_fact_count"),
            )
            return result
        finally:
            if temp_path is not None:
                logger.info(
                    "Brand facts upload temp cleanup task_id=%s temp_path=%s exists_before_cleanup=%s",
                    task_id,
                    temp_path,
                    temp_path.exists(),
                )
                temp_path.unlink(missing_ok=True)
