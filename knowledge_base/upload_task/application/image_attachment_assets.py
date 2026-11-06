from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
from contextlib import suppress
from pathlib import Path
from typing import Any, Awaitable, Callable
from uuid import uuid4

from knowledge_base.shared.image_preparation import IMAGE_TAGGING_MAX_BYTES, prepare_image_tagging_path
from knowledge_base.shared.utils import build_original_object_key


logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
IMAGE_TAGGING_MAX_ATTEMPTS = 4


class ImageAttachmentAssetProcessor:
    def __init__(
        self,
        *,
        dependencies: Any,
        prepare_image_tagging_path: Callable[[Path], tuple[Path, bool]] | None = None,
        describe_image: Callable[..., Awaitable[dict[str, Any]]] | None = None,
    ) -> None:
        self._deps = dependencies
        self._prepare_image_tagging_path_override = prepare_image_tagging_path
        self._describe_image = describe_image

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
        attachment_assets = self._deps.attachment_assets
        oss_client = self._deps.oss_client
        if attachment_assets is None:
            raise ValueError("brand_attachment_assets 未初始化")
        if oss_client is None or not getattr(oss_client, "enabled", False):
            raise ValueError("OSS 未启用，无法上传图片附件")
        if self._deps.embeddings is None or self._deps.store is None:
            raise ValueError("图片向量检索依赖未初始化")
        if self._deps.document_categories is None:
            raise ValueError("document_categories 未初始化，无法登记图片检索文档")

        logger.info(
            "Attachment image asset detected task_id=%s file_id=%s filename=%s content_type=%s file_size=%s",
            task_id,
            file_id,
            filename,
            resolved_content_type,
            resolved_file_size,
        )

        (
            summary,
            tags,
            upload_image_path,
            upload_content_type,
            upload_file_size,
            cleanup_upload_image_path,
        ) = await self.describe_image_with_retries(
            image_path=temporary_path,
            filename=filename,
            brand_name=brand_name,
            metadata=metadata,
            fallback_content_type=resolved_content_type,
        )

        uploaded_original_key: str | None = None
        original_oss_url: str | None = None
        asset_id: int | None = None
        image_document_id: str | None = None
        categories_added = False
        vector_inserted = False

        try:
            upload_document_id = f"attachment_{uuid4().hex}"
            upload_filename = self.resolve_upload_filename_for_oss(
                original_filename=filename,
                upload_image_path=upload_image_path,
                original_path=temporary_path,
            )
            original_object_key = build_original_object_key(
                category=brand_name,
                subcategory=None,
                filename=upload_filename,
                document_id=upload_document_id,
                converted_version=converted_version,
            )
            uploaded_original_key = await asyncio.to_thread(
                oss_client.upload_file,
                str(upload_image_path),
                original_object_key,
                upload_content_type,
            )
            if not uploaded_original_key:
                raise ValueError(f"图片上传 OSS 失败: {filename}")
            original_oss_url = oss_client.build_object_url(uploaded_original_key)
            logger.info(
                "Attachment image upload completed task_id=%s file_id=%s asset_key=%s compressed=%s upload_content_type=%s upload_size=%s",
                task_id,
                file_id,
                uploaded_original_key,
                upload_image_path != temporary_path,
                upload_content_type,
                upload_file_size,
            )

            asset_id = attachment_assets.create_asset(
                brand_code=brand_code,
                brand_name=brand_name,
                upload_task_id=task_id,
                upload_task_file_id=file_id,
                original_filename=filename,
                content_type=upload_content_type,
                parsed_source_type="image",
                parsed_markdown=None,
                converted_version=converted_version,
                fulltext_key=None,
                fulltext_url=None,
                file_size=upload_file_size,
                file_hash=resolved_file_hash,
                oss_key=uploaded_original_key,
                oss_url=original_oss_url,
                source_url=source_url,
                asset_kind="image",
                image_summary=summary or None,
                image_tags_json=json.dumps(tags, ensure_ascii=False),
            )

            image_document_id = f"asset_{asset_id}"
            vector_payload = self.build_image_vector_payload(
                document_id=image_document_id,
                brand_code=brand_code,
                brand_name=brand_name,
                filename=filename,
                source_url=source_url,
                subcategory=metadata.get("subcategory"),
                summary=summary,
                tags=tags,
                oss_key=uploaded_original_key,
                image_url=original_oss_url,
            )
            vector_inserted = await self.insert_image_vector(vector_payload)
            self._deps.document_categories.add_document(
                image_document_id,
                brand_name,
                str(metadata.get("subcategory") or "").strip() or None,
            )
            categories_added = True
            logger.info(
                "Attachment image asset created task_id=%s file_id=%s asset_id=%s document_id=%s",
                task_id,
                file_id,
                asset_id,
                image_document_id,
            )
            return {
                "asset_id": asset_id,
                "document_id": image_document_id,
                "oss_key": uploaded_original_key,
                "oss_url": original_oss_url,
                "file_hash": resolved_file_hash,
                "file_size": upload_file_size,
                "content_type": upload_content_type,
                "converted_version": converted_version,
                "parsed_source_type": "image",
                "source_type": "image",
            }
        except Exception:
            if categories_added and image_document_id is not None:
                with suppress(Exception):
                    self._deps.document_categories.remove_document(image_document_id)
            if vector_inserted and image_document_id is not None:
                with suppress(Exception):
                    self._deps.store.delete_document(image_document_id)
            if asset_id is not None:
                with suppress(Exception):
                    attachment_assets.delete_by_id(asset_id=asset_id)
            if uploaded_original_key:
                with suppress(Exception):
                    await asyncio.to_thread(oss_client.delete_object, uploaded_original_key)
            raise
        finally:
            if cleanup_upload_image_path and upload_image_path != temporary_path:
                upload_image_path.unlink(missing_ok=True)

    @staticmethod
    def is_image_file(*, filename: str, content_type: str | None) -> bool:
        suffix = Path(filename).suffix.lower()
        normalized_content_type = str(content_type or "").strip().lower()
        return suffix in IMAGE_EXTENSIONS or normalized_content_type.startswith("image/")

    def prepare_image_tagging_path(self, original_path: Path) -> tuple[Path, bool]:
        if self._prepare_image_tagging_path_override is not None:
            return self._prepare_image_tagging_path_override(original_path)
        return prepare_image_tagging_path(original_path)

    @staticmethod
    def resolve_upload_filename_for_oss(
        *,
        original_filename: str,
        upload_image_path: Path,
        original_path: Path,
    ) -> str:
        if upload_image_path == original_path:
            return original_filename
        suffix = upload_image_path.suffix.lower() or ".jpg"
        return f"{Path(original_filename).stem}{suffix}"

    @staticmethod
    def resolve_image_content_type_for_path(path: Path, fallback_content_type: str | None) -> str:
        guessed_content_type, _ = mimetypes.guess_type(path.name)
        normalized_guessed = str(guessed_content_type or "").strip().lower()
        if normalized_guessed.startswith("image/"):
            return normalized_guessed
        normalized_fallback = str(fallback_content_type or "").strip().lower()
        if normalized_fallback.startswith("image/"):
            return normalized_fallback
        return "image/jpeg"

    async def describe_image_with_retries(
        self,
        *,
        image_path: Path,
        filename: str,
        brand_name: str,
        metadata: dict[str, Any],
        fallback_content_type: str | None,
    ) -> tuple[str | None, list[str], Path, str, int, bool]:
        if self._describe_image is None:
            raise ValueError("图片标签生成依赖未初始化")
        logger.info(
            "Attachment image tagging started filename=%s max_bytes=%s",
            filename,
            IMAGE_TAGGING_MAX_BYTES,
        )
        prepared_path, cleanup_prepared_path = await asyncio.to_thread(
            self.prepare_image_tagging_path,
            image_path,
        )
        completed = False
        try:
            last_error: Exception | None = None
            for attempt in range(1, IMAGE_TAGGING_MAX_ATTEMPTS + 1):
                try:
                    semantic_info = await self._describe_image(
                        str(prepared_path),
                        category=brand_name,
                        subcategory=str(metadata.get("subcategory") or "").strip() or None,
                        source_name=filename,
                        model=self._deps.settings.image_tagging_model,
                        max_tags=self._deps.settings.image_tagging_max_tags,
                        settings=self._deps.settings,
                    )
                    summary = str(semantic_info.get("summary") or "").strip() or None
                    raw_tags = semantic_info.get("tags", [])
                    tags: list[str] = []
                    if isinstance(raw_tags, list):
                        for item in raw_tags:
                            tag = str(item or "").strip()
                            if tag and tag not in tags:
                                tags.append(tag)
                    tags = tags[: int(self._deps.settings.image_tagging_max_tags)]
                    if not tags:
                        raise ValueError("图片标签为空，无法建立检索索引")
                    logger.info(
                        "Attachment image tagging completed filename=%s tag_count=%s has_summary=%s",
                        filename,
                        len(tags),
                        bool(summary),
                    )
                    completed = True
                    upload_content_type = self.resolve_image_content_type_for_path(
                        prepared_path,
                        fallback_content_type,
                    )
                    upload_file_size = prepared_path.stat().st_size
                    return summary, tags, prepared_path, upload_content_type, upload_file_size, cleanup_prepared_path
                except Exception as exc:
                    last_error = exc
                    logger.warning(
                        "Attachment image tagging failed attempt=%s/%s filename=%s error=%s",
                        attempt,
                        IMAGE_TAGGING_MAX_ATTEMPTS,
                        filename,
                        exc,
                    )
                    if attempt >= IMAGE_TAGGING_MAX_ATTEMPTS:
                        break
            assert last_error is not None
            raise ValueError(f"图片标签生成失败: {last_error}") from last_error
        finally:
            if not completed and cleanup_prepared_path and prepared_path != image_path:
                prepared_path.unlink(missing_ok=True)

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
        resolved_subcategory = str(subcategory or "").strip() or None
        text_content = self.build_image_search_text(
            filename=filename,
            brand_name=brand_name,
            subcategory=resolved_subcategory,
            image_summary=summary,
            image_tags=tags,
        )
        metadata = {
            "brand_code": brand_code,
            "brand_name": brand_name,
            "category": brand_name,
            "subcategory": resolved_subcategory,
            "source_url": source_url,
            "original_filename": filename,
            "image_summary": summary,
            "image_tags": tags,
            "image_url": image_url,
            "oss_key": oss_key,
            "original_file_key": oss_key,
        }
        return {
            "document_id": document_id,
            "source_name": filename,
            "source_type": "image",
            "text": text_content,
            "metadata": metadata,
        }

    async def insert_image_vector(self, payload: dict[str, Any]) -> bool:
        text_content = str(payload["text"])
        vectors = await asyncio.to_thread(self._deps.embeddings.embed_documents, [text_content])
        row = {
            "id": f'{payload["document_id"]}:0',
            "document_id": payload["document_id"],
            "source_name": payload["source_name"],
            "source_type": payload["source_type"],
            "brand_code": str(payload["metadata"].get("brand_code") or ""),
            "brand_name": str(payload["metadata"].get("brand_name") or ""),
            "chunk_index": 0,
            "text": text_content,
            "metadata_json": json.dumps(payload["metadata"], ensure_ascii=False),
            "vector": vectors[0],
        }
        await asyncio.to_thread(
            self._deps.store.insert_chunks,
            document_id=payload["document_id"],
            source_name=payload["source_name"],
            source_type=payload["source_type"],
            chunk_payloads=[row],
        )
        return True

    @staticmethod
    def build_image_search_text(
        *,
        filename: str,
        brand_name: str,
        subcategory: str | None,
        image_summary: str | None,
        image_tags: list[str],
    ) -> str:
        parts = [f"[Image] {filename}", f"分类: {brand_name}"]
        if subcategory:
            parts.append(f"子分类: {subcategory}")
        if image_summary:
            parts.append(f"图片描述: {image_summary}")
        parts.append(f"图片标签: {'、'.join(image_tags)}")
        return "\n".join(parts)
