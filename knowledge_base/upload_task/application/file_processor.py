from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

from .helpers import is_duplicate_upload_error


logger = logging.getLogger(__name__)


class UploadTaskFileProcessor:
    def __init__(
        self,
        *,
        dependencies: Any,
        lifecycle: Any,
        resolve_metadata_brand_name: Callable[[dict[str, Any]], str | None],
        process_attachment_asset_file: Callable[..., Awaitable[dict[str, Any]]],
    ) -> None:
        self._deps = dependencies
        self._lifecycle = lifecycle
        self._resolve_metadata_brand_name = resolve_metadata_brand_name
        self._process_attachment_asset_file = process_attachment_asset_file

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
        del chunk_size, chunk_overlap

        file_id = int(file_item["id"])
        file_index = int(file_item["file_index"])
        filename = file_item["original_filename"]
        file_hash = file_item.get("file_hash")
        converted_version = file_item.get("converted_version")
        file_role = str(file_item.get("file_role") or "").strip() or "legacy_document"
        stored_path = str(file_item.get("stored_path") or "")
        staged_path = Path(stored_path) if stored_path else None

        logger.info(
            "Upload task file started task_id=%s file_id=%s filename=%s role=%s file_size=%s file_hash=%s",
            task_id,
            file_id,
            filename,
            file_role,
            file_item.get("file_size"),
            file_hash,
        )
        self._lifecycle.start_file(
            task_id=task_id,
            file_id=file_id,
            current_status=str(file_item.get("status") or "").strip() or None,
        )
        use_attachment_asset_flow = self.should_use_attachment_asset_flow(
            file_role=file_role,
            metadata=metadata,
        )
        use_brand_ai_knowledge_flow = self.should_use_brand_ai_knowledge_flow(
            file_role=file_role,
            metadata=metadata,
        )
        if file_hash and not use_attachment_asset_flow and not use_brand_ai_knowledge_flow:
            self._deps.document_registry.update_document_registry_status(
                category=registry_category,
                file_hash=file_hash,
                status="processing",
            )
        try:
            file_metadata = dict(metadata)
            file_overrides = file_metadata_by_index.get(str(file_index), {})
            if not isinstance(file_overrides, dict) or (not file_overrides and file_hash):
                file_overrides = file_metadata_by_hash.get(file_hash or "", {})
            if isinstance(file_overrides, dict):
                file_metadata.update(file_overrides)
            if file_hash:
                file_metadata["file_hash"] = file_hash
            if converted_version is not None:
                file_metadata["converted_version"] = int(converted_version)

            content_type = file_metadata.pop("content_type", None)
            source_url = file_metadata.get("source_url")
            file_metadata.pop("title", None)

            if use_attachment_asset_flow:
                await self._process_attachment_flow(
                    task_id=task_id,
                    file_id=file_id,
                    filename=filename,
                    file_item=file_item,
                    staged_path=staged_path,
                    file_metadata=file_metadata,
                    source_url=source_url,
                    content_type=content_type,
                    file_hash=file_hash,
                )
                return

            if use_brand_ai_knowledge_flow:
                await self._process_brand_ai_knowledge_flow(
                    task_id=task_id,
                    file_id=file_id,
                    filename=filename,
                    staged_path=staged_path,
                    file_metadata=file_metadata,
                    source_url=source_url,
                    content_type=content_type,
                )
                return

            raise ValueError("/api/v1/documents/upload 已不再支持普通文档入库；当前仅支持品牌附件和正式品牌 AI 知识库文件")
        except Exception as exc:
            if is_duplicate_upload_error(exc):
                logger.warning(
                    "Upload task file skipped as duplicate task_id=%s file_id=%s filename=%s reason=%s",
                    task_id,
                    file_id,
                    filename,
                    exc,
                )
            else:
                logger.exception(
                    "Upload task file failed task_id=%s file_id=%s filename=%s",
                    task_id,
                    file_id,
                    filename,
                )
            self._lifecycle.mark_file_failed(task_id=task_id, file_id=file_id, error_message=str(exc))
            await self._deps.notify_upload_failure(
                task_id=task_id,
                file_index=file_index,
                original_filename=str(filename),
                error_message=str(exc),
                created_at=file_item.get("created_at"),
            )
            preserve_registry = bool(getattr(exc, "preserve_registry", False))
            if file_hash and not preserve_registry and not use_attachment_asset_flow and not use_brand_ai_knowledge_flow:
                self._deps.document_registry.release_document_upload(
                    category=registry_category,
                    file_hash=file_hash,
                )
        finally:
            if staged_path is not None:
                staged_path.unlink(missing_ok=True)

    def should_use_attachment_asset_flow(
        self,
        *,
        file_role: str,
        metadata: dict[str, Any],
    ) -> bool:
        normalized_brand_code = str(metadata.get("brand_code") or "").strip()
        return (
            file_role == "attachment"
            and bool(normalized_brand_code)
            and getattr(self._deps, "attachment_assets", None) is not None
            and getattr(self._deps, "oss_client", None) is not None
        )

    def should_use_brand_ai_knowledge_flow(
        self,
        *,
        file_role: str,
        metadata: dict[str, Any],
    ) -> bool:
        normalized_brand_code = str(metadata.get("brand_code") or "").strip()
        normalized_brand_name = self._resolve_metadata_brand_name(metadata) or ""
        return (
            file_role == "brand_ai_knowledge"
            and bool(normalized_brand_code)
            and bool(normalized_brand_name)
            and getattr(self._deps, "brand_ai_knowledge_ingestion", None) is not None
        )

    async def _process_attachment_flow(
        self,
        *,
        task_id: str,
        file_id: int,
        filename: str,
        file_item: dict[str, Any],
        staged_path: Path | None,
        file_metadata: dict[str, Any],
        source_url: Any,
        content_type: Any,
        file_hash: Any,
    ) -> None:
        logger.info(
            "Upload task file entering attachment flow task_id=%s file_id=%s filename=%s",
            task_id,
            file_id,
            filename,
        )
        result = await self._process_attachment_asset_file(
            task_id=task_id,
            file_id=file_id,
            filename=filename,
            staged_path=staged_path,
            metadata=file_metadata,
            source_url=source_url,
            content_type=content_type,
            fallback_file_hash=file_hash,
            fallback_file_size=file_item.get("file_size"),
        )
        self._lifecycle.mark_file_success(
            task_id=task_id,
            file_id=file_id,
            document_id=result.get("document_id"),
            source_type=result.get("source_type", "attachment"),
            oss_key=result["oss_key"],
            oss_url=result["oss_url"],
            asset_id=result["asset_id"],
            content_type=result["content_type"],
            file_size=result["file_size"],
            file_hash=result["file_hash"],
        )
        logger.info(
            "Upload task file completed task_id=%s file_id=%s filename=%s role=attachment asset_id=%s",
            task_id,
            file_id,
            filename,
            result.get("asset_id"),
        )

    async def _process_brand_ai_knowledge_flow(
        self,
        *,
        task_id: str,
        file_id: int,
        filename: str,
        staged_path: Path | None,
        file_metadata: dict[str, Any],
        source_url: Any,
        content_type: Any,
    ) -> None:
        logger.info(
            "Upload task file entering brand AI knowledge flow task_id=%s file_id=%s filename=%s brand_code=%s brand_name=%s",
            task_id,
            file_id,
            filename,
            file_metadata.get("brand_code"),
            file_metadata.get("brand_name") or file_metadata.get("category"),
        )
        result = await self._deps.brand_ai_knowledge_ingestion.ingest_upload_task_file(
            task_id=task_id,
            upload_task_file_id=file_id,
            filename=filename,
            brand_code=str(file_metadata.get("brand_code") or "").strip(),
            brand_name=str(file_metadata.get("brand_name") or file_metadata.get("category") or "").strip(),
            force_reingest=bool(file_metadata.get("force_reingest", False)),
            staged_path=staged_path,
            source_url=source_url,
            content_type=content_type,
            backfill_brand_knowledge_json_empty_only=bool(
                file_metadata.get("backfill_brand_knowledge_json_empty_only", True)
            ),
        )
        self._lifecycle.mark_file_success(
            task_id=task_id,
            file_id=file_id,
            document_id=result.get("document_id"),
            source_type="brand_ai_knowledge",
            oss_key=result.get("markdown_oss_key"),
            oss_url=result.get("markdown_oss_url"),
            full_knowledge_file_id=result.get("full_knowledge_file_id"),
            content_type=result.get("content_type"),
            file_size=result.get("file_size"),
            file_hash=result.get("file_hash"),
            error_message="相同内容已存在，默认跳过" if result.get("skipped") else None,
        )
        logger.info(
            "Upload task file completed task_id=%s file_id=%s filename=%s role=brand_ai_knowledge status=%s full_knowledge_file_id=%s document_id=%s skipped=%s",
            task_id,
            file_id,
            filename,
            result.get("status"),
            result.get("full_knowledge_file_id"),
            result.get("document_id"),
            result.get("skipped"),
        )
