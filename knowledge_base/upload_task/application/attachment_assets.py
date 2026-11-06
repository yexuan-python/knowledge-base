from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Awaitable, Callable

from knowledge_base.ingest.application.remote_download import download_remote_content_to_temp_file
from .document_attachment_assets import DocumentAttachmentAssetProcessor
from .image_attachment_assets import ImageAttachmentAssetProcessor


class AttachmentAssetUploadProcessor:
    def __init__(
        self,
        *,
        dependencies: Any,
        resolve_metadata_brand_name: Callable[[dict[str, Any]], str | None],
        compute_sha256_for_path: Callable[[Path], str],
        detect_content_type: Callable[..., str],
        prepare_image_tagging_path: Callable[[Path], tuple[Path, bool]] | None = None,
        describe_image: Callable[..., Awaitable[dict[str, Any]]] | None = None,
        download_remote_content: Callable[..., Awaitable[tuple[Path, str | None, int | None]]] | None = None,
    ) -> None:
        self._deps = dependencies
        self._resolve_metadata_brand_name = resolve_metadata_brand_name
        self._compute_sha256_for_path = compute_sha256_for_path
        self._detect_content_type = detect_content_type
        self._prepare_image_tagging_path_override = prepare_image_tagging_path
        self._describe_image = describe_image
        self._download_remote_content = download_remote_content or download_remote_content_to_temp_file

    def _document_processor(self) -> DocumentAttachmentAssetProcessor:
        return DocumentAttachmentAssetProcessor(dependencies=self._deps)

    def _image_processor(self) -> ImageAttachmentAssetProcessor:
        return ImageAttachmentAssetProcessor(
            dependencies=self._deps,
            prepare_image_tagging_path=self._prepare_image_tagging_path_override,
            describe_image=self._describe_image,
        )

    async def process_attachment_asset_file(
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
        oss_client = self._deps.oss_client
        attachment_assets = self._deps.attachment_assets
        if oss_client is None or not getattr(oss_client, "enabled", False):
            raise ValueError("OSS 未启用，无法上传附件")
        if attachment_assets is None:
            raise ValueError("brand_attachment_assets 未初始化")

        brand_code = str(metadata.get("brand_code") or "").strip()
        brand_name = self._resolve_metadata_brand_name(metadata) or ""
        if not brand_code:
            raise ValueError("brand_code 不能为空")
        if not brand_name:
            raise ValueError("brand_name 不能为空")

        resolved_source_url = str(source_url or "").strip() or None
        temporary_path: Path | None = None
        if staged_path is not None and staged_path.exists():
            temporary_path = staged_path
            resolved_content_type = self._detect_content_type(filename=filename, content_type=content_type)
        else:
            if not resolved_source_url:
                raise ValueError("附件缺少 source_url")
            temporary_path, downloaded_content_type, _downloaded_size = await self._download_remote_content(
                url=resolved_source_url,
                name=filename,
                log_context=f"attachment_asset:{brand_code}",
            )
            resolved_content_type = self._detect_content_type(
                filename=filename,
                content_type=content_type or downloaded_content_type,
            )

        try:
            if temporary_path is None:
                raise ValueError("附件临时文件不存在")
            resolved_file_hash = fallback_file_hash or await asyncio.to_thread(
                self._compute_sha256_for_path,
                temporary_path,
            )
            existing = attachment_assets.get_by_brand_code_and_file_hash(
                brand_code=brand_code,
                file_hash=resolved_file_hash,
            )
            if existing is not None:
                raise ValueError("发现相同文件已存在，无法上传")

            resolved_file_size = fallback_file_size if fallback_file_size is not None else temporary_path.stat().st_size
            converted_version = attachment_assets.get_next_converted_version(
                brand_code=brand_code,
                original_filename=filename,
            )
            is_image = self.is_image_file(
                filename=filename,
                content_type=resolved_content_type,
            )
            if is_image:
                return await self.process_image_attachment_asset_file(
                    task_id=task_id,
                    file_id=file_id,
                    filename=filename,
                    temporary_path=temporary_path,
                    metadata=metadata,
                    source_url=resolved_source_url,
                    brand_code=brand_code,
                    brand_name=brand_name,
                    resolved_content_type=resolved_content_type,
                    resolved_file_hash=resolved_file_hash,
                    resolved_file_size=resolved_file_size,
                    converted_version=converted_version,
                )

            return await self._document_processor().process_document_attachment_asset_file(
                task_id=task_id,
                file_id=file_id,
                filename=filename,
                temporary_path=temporary_path,
                source_url=resolved_source_url,
                brand_code=brand_code,
                brand_name=brand_name,
                resolved_content_type=resolved_content_type,
                resolved_file_hash=resolved_file_hash,
                resolved_file_size=resolved_file_size,
                converted_version=converted_version,
            )
        finally:
            if temporary_path is not None and temporary_path != staged_path:
                temporary_path.unlink(missing_ok=True)

    async def process_image_attachment_asset_file(
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
        return await self._image_processor().process_image_attachment_asset_file(
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
    def is_image_file(*, filename: str, content_type: str | None) -> bool:
        return ImageAttachmentAssetProcessor.is_image_file(filename=filename, content_type=content_type)

    def prepare_image_tagging_path(self, original_path: Path) -> tuple[Path, bool]:
        return self._image_processor().prepare_image_tagging_path(original_path)

    @staticmethod
    def resolve_upload_filename_for_oss(
        *,
        original_filename: str,
        upload_image_path: Path,
        original_path: Path,
    ) -> str:
        return ImageAttachmentAssetProcessor.resolve_upload_filename_for_oss(
            original_filename=original_filename,
            upload_image_path=upload_image_path,
            original_path=original_path,
        )

    @staticmethod
    def resolve_image_content_type_for_path(path: Path, fallback_content_type: str | None) -> str:
        return ImageAttachmentAssetProcessor.resolve_image_content_type_for_path(path, fallback_content_type)

    async def describe_image_with_retries(
        self,
        *,
        image_path: Path,
        filename: str,
        brand_name: str,
        metadata: dict[str, Any],
        fallback_content_type: str | None,
    ) -> tuple[str | None, list[str], Path, str, int, bool]:
        return await self._image_processor().describe_image_with_retries(
            image_path=image_path,
            filename=filename,
            brand_name=brand_name,
            metadata=metadata,
            fallback_content_type=fallback_content_type,
        )

    def build_image_vector_payload(
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
        return self._image_processor().build_image_vector_payload(
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

    async def insert_image_vector(self, payload: dict[str, Any]) -> bool:
        return await self._image_processor().insert_image_vector(payload)

    @staticmethod
    def build_image_search_text(
        *,
        filename: str,
        brand_name: str,
        subcategory: str | None,
        image_summary: str | None,
        image_tags: list[str],
    ) -> str:
        return ImageAttachmentAssetProcessor.build_image_search_text(
            filename=filename,
            brand_name=brand_name,
            subcategory=subcategory,
            image_summary=image_summary,
            image_tags=image_tags,
        )
