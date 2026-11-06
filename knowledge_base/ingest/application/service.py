from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from knowledge_base.document.domain import IngestedDocument
from . import workflows


@dataclass(frozen=True)
class IngestApplicationDependencies:
    kb_service: Any


class IngestApplicationService:
    def __init__(self, dependencies: IngestApplicationDependencies) -> None:
        self._deps = dependencies

    async def ingest_text_document(
        self,
        *,
        text: str,
        title: str,
        metadata: dict[str, Any],
        chunk_size: int | None,
        chunk_overlap: int | None,
        document_id: str | None = None,
    ) -> IngestedDocument:
        return await workflows.ingest_text_document(
            self._deps.kb_service,
            text=text,
            title=title,
            metadata=metadata,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            document_id=document_id,
        )

    async def ingest_from_url(
        self,
        *,
        url: str,
        name: str,
        category: str,
        metadata: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> IngestedDocument:
        return await workflows.ingest_from_url(
            self._deps.kb_service,
            url=url,
            name=name,
            category=category,
            metadata=metadata,
            task_id=task_id,
        )

    def get_full_text(self, document_id: str) -> str | None:
        return workflows.get_full_text(self._deps.kb_service, document_id)

    async def ingest_image(
        self,
        *,
        temporary_path: Path,
        filename: str,
        document_id: str,
        metadata: dict[str, Any],
    ) -> IngestedDocument:
        return await workflows.ingest_image(
            self._deps.kb_service,
            temporary_path=temporary_path,
            filename=filename,
            document_id=document_id,
            metadata=metadata,
        )

    async def ingest_document(
        self,
        *,
        temporary_path: Path,
        filename: str,
        document_id: str,
        metadata: dict[str, Any],
        chunk_size: int | None,
        chunk_overlap: int | None,
    ) -> IngestedDocument:
        return await workflows.ingest_document(
            self._deps.kb_service,
            temporary_path=temporary_path,
            filename=filename,
            document_id=document_id,
            metadata=metadata,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    async def ingest_staged_file(
        self,
        *,
        staged_path: Path,
        filename: str,
        metadata: dict[str, Any],
        chunk_size: int | None,
        chunk_overlap: int | None,
        content_type: str | None = None,
    ) -> IngestedDocument:
        return await workflows.ingest_staged_file(
            self._deps.kb_service,
            staged_path=staged_path,
            filename=filename,
            metadata=metadata,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            content_type=content_type,
        )
