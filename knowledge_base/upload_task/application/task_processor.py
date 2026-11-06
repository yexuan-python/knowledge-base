from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable

from knowledge_base.shared.utils import normalize_upload_metadata, resolve_registry_category


logger = logging.getLogger(__name__)


class UploadTaskProcessor:
    def __init__(
        self,
        *,
        dependencies: Any,
        lifecycle: Any,
        process_upload_task_file: Callable[..., Awaitable[None]],
        cleanup_task_directory: Callable[[str], None],
    ) -> None:
        self._deps = dependencies
        self._lifecycle = lifecycle
        self._process_upload_task_file = process_upload_task_file
        self._cleanup_task_directory = cleanup_task_directory

    async def process_upload_task(self, task_id: str) -> None:
        logger.info("Upload task processing started task_id=%s", task_id)
        task = self._deps.upload_tasks.get_upload_task(task_id)
        if not task:
            logger.warning("Upload task missing task_id=%s", task_id)
            return

        raw_metadata = task.get("metadata_json")
        if isinstance(raw_metadata, str):
            metadata = json.loads(raw_metadata) if raw_metadata else {}
        elif isinstance(raw_metadata, dict):
            metadata = raw_metadata
        else:
            metadata = {}

        metadata = normalize_upload_metadata(metadata)
        task_payload = metadata.pop("_task_payload", {})
        file_metadata_by_index: dict[str, dict[str, Any]] = {}
        file_metadata_by_hash: dict[str, dict[str, Any]] = {}
        if isinstance(task_payload, dict):
            raw_file_metadata_by_index = task_payload.get("file_metadata_by_index")
            if isinstance(raw_file_metadata_by_index, dict):
                file_metadata_by_index = raw_file_metadata_by_index
            raw_file_metadata_by_hash = task_payload.get("file_metadata_by_hash")
            if isinstance(raw_file_metadata_by_hash, dict):
                file_metadata_by_hash = raw_file_metadata_by_hash
        registry_category = resolve_registry_category(metadata.get("category"))

        chunk_size = task.get("chunk_size")
        chunk_overlap = task.get("chunk_overlap")
        files = self._deps.upload_tasks.get_upload_task_files(task_id)
        logger.info(
            "Upload task loaded task_id=%s file_count=%s brand_code=%s brand_name=%s",
            task_id,
            len(files),
            metadata.get("brand_code"),
            metadata.get("brand_name") or metadata.get("category"),
        )

        self._lifecycle.start_task(task_id)

        default_semaphore = asyncio.Semaphore(3)
        brand_ai_knowledge_semaphore = asyncio.Semaphore(1)

        async def process_one(file_item: dict[str, Any]) -> None:
            if file_item["status"] != "pending":
                return
            file_role = str(file_item.get("file_role") or "").strip()
            semaphore = brand_ai_knowledge_semaphore if file_role == "brand_ai_knowledge" else default_semaphore
            async with semaphore:
                await self._process_upload_task_file(
                    task_id=task_id,
                    registry_category=registry_category,
                    metadata=metadata,
                    file_metadata_by_index=file_metadata_by_index,
                    file_metadata_by_hash=file_metadata_by_hash,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    file_item=file_item,
                )

        await asyncio.gather(*(process_one(file_item) for file_item in files))

        self._cleanup_task_directory(task_id)
        completion = self._lifecycle.complete_task_from_file_counts(task_id)
        logger.info(
            "Upload task processing completed task_id=%s status=%s counts=%s",
            task_id,
            completion.status,
            completion.counts,
        )
        self._deps.schedule_delayed_completion_check(task_id, delay_seconds=0)
