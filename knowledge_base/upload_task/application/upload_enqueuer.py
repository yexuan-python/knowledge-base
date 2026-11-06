from __future__ import annotations

import logging
from contextlib import suppress
from pathlib import Path
from typing import Any, Awaitable, Callable
from uuid import uuid4

from knowledge_base.shared.utils import build_registry_reservation, normalize_upload_metadata
from knowledge_base.upload_task.schemas import UploadTaskCreateResponse


logger = logging.getLogger(__name__)


class UploadTaskEnqueuer:
    def __init__(
        self,
        *,
        dependencies: Any,
        validate_documents_upload_metadata: Callable[[dict[str, Any]], None],
        resolve_file_role: Callable[..., str],
        schedule_upload_task: Callable[[str], Awaitable[None]],
        stage_upload_file: Callable[[Any, Path], Awaitable[tuple[int, str]]],
    ) -> None:
        self._deps = dependencies
        self._validate_documents_upload_metadata = validate_documents_upload_metadata
        self._resolve_file_role = resolve_file_role
        self._schedule_upload_task = schedule_upload_task
        self._stage_upload_file = stage_upload_file

    async def enqueue_upload_task(
        self,
        *,
        files: list[Any],
        metadata: dict[str, Any],
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
    ) -> UploadTaskCreateResponse:
        task_id = str(uuid4())
        self._validate_documents_upload_metadata(metadata)
        prepared_metadata = normalize_upload_metadata(metadata)
        task_dir = Path(self._deps.settings.upload_staging_dir) / task_id
        task_dir.mkdir(parents=True, exist_ok=True)

        staged_files: list[dict[str, Any]] = []
        has_brand_ai_knowledge_file = False
        try:
            seen_hashes: dict[str, str] = {}
            for index, upload in enumerate(files):
                filename = upload.filename or f"upload-{uuid4()}"
                staged_path = task_dir / f"{index:04d}_{Path(filename).name}"
                file_size, file_hash = await self._stage_upload_file(upload, staged_path)
                file_role = self._resolve_file_role(filename=filename, metadata=prepared_metadata)
                if file_role == "brand_ai_knowledge":
                    has_brand_ai_knowledge_file = True
                file_item = {
                    "file_index": index,
                    "original_filename": filename,
                    "file_role": file_role,
                    "stored_path": str(staged_path),
                    "file_size": file_size,
                    "file_hash": file_hash,
                    **build_registry_reservation(
                        filename=filename,
                        file_size=file_size,
                        file_hash=file_hash,
                    ),
                }
                previous_name = seen_hashes.get(file_hash)
                if previous_name is not None:
                    file_item["status"] = "failed"
                    file_item["error_message"] = f"当前批次存在重复文件，无法上传；与 {previous_name} 内容相同"
                    staged_files.append(file_item)
                    staged_path.unlink(missing_ok=True)
                    continue
                seen_hashes[file_hash] = filename

                staged_files.append(file_item)

            if has_brand_ai_knowledge_file:
                prepared_metadata["brand_callback_enabled"] = True
                prepared_metadata["backfill_brand_knowledge_json_empty_only"] = True

            self._deps.upload_tasks.create_upload_task(
                task_id=task_id,
                task_type="document_upload",
                metadata=prepared_metadata,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                files=staged_files,
            )
            logger.info(
                "Documents upload task created task_id=%s file_count=%s brand_code=%s brand_name=%s roles=%s",
                task_id,
                len(staged_files),
                prepared_metadata.get("brand_code"),
                prepared_metadata.get("brand_name") or prepared_metadata.get("category"),
                [item.get("file_role") for item in staged_files],
            )
            await self._deps.notify_failed_upload_files(task_id)
        except Exception:
            for item in staged_files:
                Path(item["stored_path"]).unlink(missing_ok=True)
            with suppress(OSError):
                task_dir.rmdir()
            raise

        await self._schedule_upload_task(task_id)
        logger.info("Documents upload task scheduled task_id=%s file_count=%s", task_id, len(staged_files))
        return UploadTaskCreateResponse(
            task_id=task_id,
            status="queued",
            file_count=len(staged_files),
            message="文件已上传成功，后台任务正在排队处理",
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
        normalized_filename = Path(str(filename or "").strip()).name
        normalized_source_url = str(source_url or "").strip()
        normalized_brand_code = str(brand_code or "").strip()
        normalized_brand_name = str(brand_name or "").strip()
        if not normalized_filename:
            raise ValueError("正式品牌AI知识库文件名不能为空")
        if not normalized_source_url:
            raise ValueError("正式品牌AI知识库文件 url 不能为空")
        if not normalized_brand_code:
            raise ValueError("brand_code 不能为空")
        if not normalized_brand_name:
            raise ValueError("brand_name 不能为空")

        metadata = normalize_upload_metadata(
            {
                "brand_code": normalized_brand_code,
                "brand_name": normalized_brand_name,
                "category": normalized_brand_name,
                "brand_callback_enabled": True,
                "backfill_brand_knowledge_json_empty_only": True,
                "_task_payload": {
                    "file_metadata_by_index": {
                        "0": {
                            "source_url": normalized_source_url,
                            "content_type": "text/markdown",
                        }
                    }
                },
            }
        )
        if force_reingest:
            metadata["force_reingest"] = True

        task_id = str(uuid4())
        self._deps.upload_tasks.create_upload_task(
            task_id=task_id,
            task_type="document_upload",
            metadata=metadata,
            chunk_size=None,
            chunk_overlap=None,
            files=[
                {
                    "file_index": 0,
                    "original_filename": normalized_filename,
                    "file_role": "brand_ai_knowledge",
                    "stored_path": "",
                    "file_size": None,
                    "file_hash": None,
                }
            ],
        )
        await self._schedule_upload_task(task_id)
        logger.info(
            "Brand AI knowledge URL upload task created task_id=%s filename=%s brand_code=%s brand_name=%s",
            task_id,
            normalized_filename,
            normalized_brand_code,
            normalized_brand_name,
        )
        return UploadTaskCreateResponse(
            task_id=task_id,
            status="queued",
            file_count=1,
            message="正式品牌AI知识库已提交成功，后台任务正在排队处理",
        )
