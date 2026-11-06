from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from knowledge_base.brand.schemas import BrandUploadRequest
from knowledge_base.ingest.ai import describe_image
from knowledge_base.ingest.application.remote_download import download_remote_content_to_temp_file
from knowledge_base.shared.image_preparation import prepare_image_tagging_path
from knowledge_base.upload_task.schemas import UploadTaskCreateResponse

from .attachment_assets import AttachmentAssetUploadProcessor
from .brand_upload_enqueuer import BrandUploadTaskEnqueuer
from .file_processor import UploadTaskFileProcessor
from .lifecycle import UploadTaskLifecycle
from .queue_coordinator import UploadTaskQueueCoordinator
from .status import UploadTaskStatusBuilder
from .task_processor import UploadTaskProcessor
from .upload_enqueuer import UploadTaskEnqueuer
from .helpers import (
    compute_sha256_for_path,
    detect_content_type,
    normalize_int,
    normalize_websites,
    resolve_brand_ai_knowledge_job_id,
    resolve_file_role,
    resolve_metadata_brand_name,
    serialize_brand_competitors,
    serialize_websites,
    stage_upload_file,
    validate_documents_upload_metadata,
)

@dataclass(frozen=True)
class UploadTaskApplicationDependencies:
    settings: Any
    brands: Any
    brand_products: Any
    industries: Any
    document_registry: Any
    document_categories: Any
    upload_tasks: Any
    queue: asyncio.Queue[str]
    queued_task_ids: set[str]
    queue_lock: asyncio.Lock
    ingest_text_document: Any
    ingest_from_url: Any
    ingest_staged_file: Any
    notify_failed_upload_files: Any
    notify_upload_failure: Any
    schedule_delayed_completion_check: Any
    parser: Any = None
    enqueue_upload_task_process_job: Any = None
    brand_ai_knowledge_ingestion: Any = None
    brand_full_knowledge: Any = None
    brand_knowledge_ingestion_jobs: Any = None
    attachment_assets: Any = None
    oss_client: Any = None
    brand_knowledge_sessions: Any = None
    embeddings: Any = None
    store: Any = None


class UploadTaskApplicationService:
    def __init__(self, dependencies: UploadTaskApplicationDependencies) -> None:
        self._deps = dependencies

    def _attachment_asset_processor(self) -> AttachmentAssetUploadProcessor:
        return AttachmentAssetUploadProcessor(
            dependencies=self._deps,
            resolve_metadata_brand_name=self._resolve_metadata_brand_name,
            compute_sha256_for_path=self._compute_sha256_for_path,
            detect_content_type=self._detect_content_type,
            prepare_image_tagging_path=lambda original_path: self._prepare_image_tagging_path(original_path),
            describe_image=lambda *args, **kwargs: describe_image(*args, **kwargs),
            download_remote_content=lambda **kwargs: download_remote_content_to_temp_file(**kwargs),
        )

    def _upload_task_file_processor(self) -> UploadTaskFileProcessor:
        return UploadTaskFileProcessor(
            dependencies=self._deps,
            lifecycle=self._upload_task_lifecycle(),
            resolve_metadata_brand_name=self._resolve_metadata_brand_name,
            process_attachment_asset_file=self._process_attachment_asset_file,
        )

    def _upload_task_lifecycle(self) -> UploadTaskLifecycle:
        return UploadTaskLifecycle(dependencies=self._deps)

    def _upload_task_queue_coordinator(self) -> UploadTaskQueueCoordinator:
        return UploadTaskQueueCoordinator(
            dependencies=self._deps,
            lifecycle=self._upload_task_lifecycle(),
            process_upload_task=self.process_upload_task,
        )

    def _brand_upload_enqueuer(self) -> BrandUploadTaskEnqueuer:
        return BrandUploadTaskEnqueuer(
            dependencies=self._deps,
            lifecycle=self._upload_task_lifecycle(),
            normalize_int=self._normalize_int,
            normalize_websites=self._normalize_websites,
            serialize_brand_competitors=self._serialize_brand_competitors,
            serialize_websites=self._serialize_websites,
            schedule_upload_task=self.schedule_upload_task,
        )

    def _upload_task_enqueuer(self) -> UploadTaskEnqueuer:
        return UploadTaskEnqueuer(
            dependencies=self._deps,
            validate_documents_upload_metadata=self._validate_documents_upload_metadata,
            resolve_file_role=self._resolve_file_role,
            schedule_upload_task=self.schedule_upload_task,
            stage_upload_file=lambda upload, staged_path: stage_upload_file(upload, staged_path),
        )

    def _upload_task_processor(self) -> UploadTaskProcessor:
        return UploadTaskProcessor(
            dependencies=self._deps,
            lifecycle=self._upload_task_lifecycle(),
            process_upload_task_file=self.process_upload_task_file,
            cleanup_task_directory=self.cleanup_task_directory,
        )

    def _upload_task_status_builder(self) -> UploadTaskStatusBuilder:
        return UploadTaskStatusBuilder(
            dependencies=self._deps,
            normalize_int=self._normalize_int,
            resolve_metadata_brand_name=self._resolve_metadata_brand_name,
            resolve_brand_ai_knowledge_job_id=self._resolve_brand_ai_knowledge_job_id,
        )

    @staticmethod
    def _normalize_int(value: Any) -> int | None:
        return normalize_int(value)

    @staticmethod
    def _normalize_websites(value: Any) -> list[str]:
        return normalize_websites(value)

    @staticmethod
    def _serialize_brand_competitors(value: Any) -> list[dict[str, str | None]]:
        return serialize_brand_competitors(value)

    @staticmethod
    def _resolve_metadata_brand_name(metadata: dict[str, Any]) -> str | None:
        return resolve_metadata_brand_name(metadata)

    @staticmethod
    def _compute_sha256_for_path(path: Path) -> str:
        return compute_sha256_for_path(path)

    @classmethod
    def _validate_documents_upload_metadata(cls, metadata: dict[str, Any]) -> None:
        del cls
        validate_documents_upload_metadata(metadata)

    @staticmethod
    def _resolve_brand_ai_knowledge_job_id(*, task_id: str, file_id: int) -> str:
        return resolve_brand_ai_knowledge_job_id(task_id=task_id, file_id=file_id)

    @classmethod
    def _serialize_websites(cls, value: Any) -> str | None:
        del cls
        return serialize_websites(value)

    async def enqueue_upload_task(
        self,
        *,
        files: list[UploadFile],
        metadata: dict[str, Any],
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
    ) -> UploadTaskCreateResponse:
        return await self._upload_task_enqueuer().enqueue_upload_task(
            files=files,
            metadata=metadata,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    async def enqueue_brand_ai_knowledge_url_task(
        self,
        *,
        filename: str,
        source_url: str,
        brand_code: str,
        brand_name: str,
        force_reingest: bool = False,
    ) -> UploadTaskCreateResponse:
        return await self._upload_task_enqueuer().enqueue_brand_ai_knowledge_url_task(
            filename=filename,
            source_url=source_url,
            brand_code=brand_code,
            brand_name=brand_name,
            force_reingest=force_reingest,
        )

    async def enqueue_brand_upload_task(self, request: BrandUploadRequest) -> UploadTaskCreateResponse:
        return await self._brand_upload_enqueuer().enqueue_brand_upload_task(request)

    async def schedule_upload_task(self, task_id: str) -> None:
        await self._upload_task_queue_coordinator().schedule_upload_task(task_id)

    async def upload_worker(self) -> None:
        await self._upload_task_queue_coordinator().upload_worker()

    async def process_upload_task(self, task_id: str) -> None:
        await self._upload_task_processor().process_upload_task(task_id)

    async def process_upload_task_file(
        self,
        *,
        task_id: str,
        registry_category: str,
        metadata: dict[str, Any],
        file_metadata_by_index: dict[str, dict[str, Any]],
        file_metadata_by_hash: dict[str, dict[str, Any]],
        chunk_size: int | None,
        chunk_overlap: int | None,
        file_item: dict[str, Any],
    ) -> None:
        await self._upload_task_file_processor().process_upload_task_file(
            task_id=task_id,
            registry_category=registry_category,
            metadata=metadata,
            file_metadata_by_index=file_metadata_by_index,
            file_metadata_by_hash=file_metadata_by_hash,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            file_item=file_item,
        )

    def get_upload_task_status(self, task_id: str) -> dict[str, Any] | None:
        return self._upload_task_status_builder().get_upload_task_status(task_id)

    def _build_upload_task_file_status(
        self,
        *,
        task_id: str,
        task_brand_code: str | None,
        task_brand_name: str | None,
        file_row: dict[str, Any],
        full_knowledge_map: dict[int, dict[str, Any]],
        ingestion_job_map: dict[int, dict[str, Any]],
    ) -> dict[str, Any]:
        del task_id
        return self._upload_task_status_builder().build_upload_task_file_status(
            task_brand_code=task_brand_code,
            task_brand_name=task_brand_name,
            file_row=file_row,
            full_knowledge_map=full_knowledge_map,
            ingestion_job_map=ingestion_job_map,
        )

    def _should_use_attachment_asset_flow(
        self,
        *,
        file_role: str,
        metadata: dict[str, Any],
    ) -> bool:
        return self._upload_task_file_processor().should_use_attachment_asset_flow(
            file_role=file_role,
            metadata=metadata,
        )

    def _should_use_brand_ai_knowledge_flow(
        self,
        *,
        file_role: str,
        metadata: dict[str, Any],
    ) -> bool:
        return self._upload_task_file_processor().should_use_brand_ai_knowledge_flow(
            file_role=file_role,
            metadata=metadata,
        )

    async def _process_attachment_asset_file(
        self,
        *,
        task_id: str,
        file_id: int,
        filename: str,
        staged_path: Path | None,
        metadata: dict[str, Any],
        source_url: str | None,
        content_type: str | None,
        fallback_file_hash: str | None,
        fallback_file_size: int | None,
    ) -> dict[str, Any]:
        return await self._attachment_asset_processor().process_attachment_asset_file(
            task_id=task_id,
            file_id=file_id,
            filename=filename,
            staged_path=staged_path,
            metadata=metadata,
            source_url=source_url,
            content_type=content_type,
            fallback_file_hash=fallback_file_hash,
            fallback_file_size=fallback_file_size,
        )

    async def _process_image_attachment_asset_file(
        self,
        *,
        task_id: str,
        file_id: int,
        filename: str,
        temporary_path: Path,
        metadata: dict[str, Any],
        source_url: str | None,
        brand_code: str,
        brand_name: str,
        resolved_content_type: str,
        resolved_file_hash: str,
        resolved_file_size: int,
        converted_version: int,
    ) -> dict[str, Any]:
        return await self._attachment_asset_processor().process_image_attachment_asset_file(
            task_id=task_id,
            file_id=file_id,
            filename=filename,
            temporary_path=temporary_path,
            metadata=metadata,
            source_url=source_url,
            brand_code=brand_code,
            brand_name=brand_name,
            resolved_content_type=resolved_content_type,
            resolved_file_hash=resolved_file_hash,
            resolved_file_size=resolved_file_size,
            converted_version=converted_version,
        )

    @staticmethod
    def _is_image_file(*, filename: str, content_type: str | None) -> bool:
        return AttachmentAssetUploadProcessor.is_image_file(filename=filename, content_type=content_type)

    def _prepare_image_tagging_path(self, original_path: Path) -> tuple[Path, bool]:
        return prepare_image_tagging_path(original_path)

    @staticmethod
    def _resolve_upload_filename_for_oss(
        *,
        original_filename: str,
        upload_image_path: Path,
        original_path: Path,
    ) -> str:
        return AttachmentAssetUploadProcessor.resolve_upload_filename_for_oss(
            original_filename=original_filename,
            upload_image_path=upload_image_path,
            original_path=original_path,
        )

    @staticmethod
    def _resolve_image_content_type_for_path(path: Path, fallback_content_type: str | None) -> str:
        return AttachmentAssetUploadProcessor.resolve_image_content_type_for_path(path, fallback_content_type)

    async def _describe_image_with_retries(
        self,
        *,
        image_path: Path,
        filename: str,
        brand_name: str,
        metadata: dict[str, Any],
        fallback_content_type: str | None,
    ) -> tuple[str | None, list[str], Path, str, int, bool]:
        return await self._attachment_asset_processor().describe_image_with_retries(
            image_path=image_path,
            filename=filename,
            brand_name=brand_name,
            metadata=metadata,
            fallback_content_type=fallback_content_type,
        )

    def _build_image_vector_payload(
        self,
        *,
        document_id: str,
        brand_code: str,
        brand_name: str,
        filename: str,
        source_url: str | None,
        subcategory: Any,
        summary: str | None,
        tags: list[str],
        oss_key: str,
        image_url: str | None,
    ) -> dict[str, Any]:
        return self._attachment_asset_processor().build_image_vector_payload(
            document_id=document_id,
            brand_code=brand_code,
            brand_name=brand_name,
            filename=filename,
            source_url=source_url,
            subcategory=subcategory,
            summary=summary,
            tags=tags,
            oss_key=oss_key,
            image_url=image_url,
        )

    async def _insert_image_vector(self, payload: dict[str, Any]) -> bool:
        return await self._attachment_asset_processor().insert_image_vector(payload)

    @staticmethod
    def _build_image_search_text(
        *,
        filename: str,
        brand_name: str,
        subcategory: str | None,
        image_summary: str | None,
        image_tags: list[str],
    ) -> str:
        return AttachmentAssetUploadProcessor.build_image_search_text(
            filename=filename,
            brand_name=brand_name,
            subcategory=subcategory,
            image_summary=image_summary,
            image_tags=image_tags,
        )

    def cleanup_task_directory(self, task_id: str) -> None:
        task_dir = Path(self._deps.settings.upload_staging_dir) / task_id
        if not task_dir.exists():
            return
        for child in task_dir.iterdir():
            if child.is_file():
                child.unlink(missing_ok=True)
        with suppress(OSError):
            task_dir.rmdir()
    @staticmethod
    def _resolve_file_role(filename: str, metadata: dict[str, Any]) -> str:
        return resolve_file_role(filename, metadata)

    @staticmethod
    def _detect_content_type(*, filename: str, content_type: str | None) -> str:
        return detect_content_type(filename=filename, content_type=content_type)
