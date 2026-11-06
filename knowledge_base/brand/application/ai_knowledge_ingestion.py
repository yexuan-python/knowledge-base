from __future__ import annotations

import asyncio
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from knowledge_base.brand.application.brand_ai_knowledge_ingestion_backfill import (
    BrandAiKnowledgeIngestionBackfillMixin,
)
from knowledge_base.brand.application.brand_ai_knowledge_ingestion_facts_only import (
    BrandAiKnowledgeIngestionFactsOnlyMixin,
)
from knowledge_base.brand.application.brand_ai_knowledge_ingestion_pipeline import (
    BrandAiKnowledgeIngestionPipelineMixin,
)
from knowledge_base.brand.application.brand_ai_knowledge_ingestion_support import (
    BrandAiKnowledgeIngestionSupportMixin,
)
from knowledge_base.brand.knowledge_extraction import (
    extract_brand_knowledge_snapshot_from_markdown,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BrandAiKnowledgeIngestionDependencies:
    settings: Any
    brands: Any
    parser: Any
    embeddings: Any
    store: Any
    oss_client: Any
    brand_full_knowledge: Any
    brand_knowledge_facts: Any
    brand_knowledge_ingestion_jobs: Any
    brand_knowledge: Any = None
    brand_products: Any = None


class BrandAiKnowledgeIngestionService(
    BrandAiKnowledgeIngestionFactsOnlyMixin,
    BrandAiKnowledgeIngestionPipelineMixin,
    BrandAiKnowledgeIngestionBackfillMixin,
    BrandAiKnowledgeIngestionSupportMixin,
):
    def __init__(self, dependencies: BrandAiKnowledgeIngestionDependencies) -> None:
        self._deps = dependencies

    async def _extract_brand_knowledge_snapshot_from_markdown(
        self,
        *,
        brand_name: str,
        markdown_text: str,
        source_name: str,
    ) -> dict[str, Any]:
        return await extract_brand_knowledge_snapshot_from_markdown(
            brand_name=brand_name,
            markdown_text=markdown_text,
            source_name=source_name,
            settings=self._deps.settings,
        )

    async def ingest_generated_markdown(
        self,
        *,
        task_id: str,
        filename: str,
        brand_code: str,
        brand_name: str,
        markdown_text: str,
        force_reingest: bool = False,
        upload_task_file_id: int = 0,
        source_task_id: str | None = None,
        change_origin: str | None = None,
        job_id: str | None = None,
        backfill_brand_knowledge_json_empty_only: bool = False,
    ) -> dict[str, Any]:
        normalized_markdown_text = str(markdown_text or "").strip()
        if not normalized_markdown_text:
            raise ValueError("markdown_text 不能为空")

        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".md") as tmp:
                tmp.write(normalized_markdown_text.encode("utf-8"))
                temp_path = Path(tmp.name)
            return await self.ingest_upload_task_file(
                task_id=task_id,
                upload_task_file_id=upload_task_file_id,
                filename=filename,
                brand_code=brand_code,
                brand_name=brand_name,
                force_reingest=force_reingest,
                staged_path=temp_path,
                source_url=None,
                content_type="text/markdown; charset=utf-8",
                source_task_id=source_task_id,
                change_origin=change_origin or "frontend",
                job_id=job_id,
                backfill_brand_knowledge_json_empty_only=backfill_brand_knowledge_json_empty_only,
            )
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
