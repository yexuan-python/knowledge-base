from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from knowledge_base.document.domain import IngestedDocument
from knowledge_base.ingest.infrastructure import NoTextExtractedError, build_chunks
from knowledge_base.ingest.ai import describe_image
from knowledge_base.shared.utils import (
    build_image_object_key,
    build_registry_reservation,
    legacy_fulltext_object_key,
    normalize_upload_metadata,
    parse_metadata_json,
    resolve_registry_category,
)
from .document_pipeline import (
    finalize_document_ingest,
    parse_document_with_policy,
    persist_document_assets,
)
from .remote_download import download_remote_content_to_temp_file

if TYPE_CHECKING:
    from knowledge_base.service import KnowledgeBaseService


logger = logging.getLogger(__name__)


def _compute_sha256_for_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            if not chunk:
                continue
            digest.update(chunk)
    return digest.hexdigest()


def _build_image_search_text(
    filename: str,
    image_summary: str | None,
    image_tags: list[str] | None,
    category: str | None,
    subcategory: str | None,
) -> str:
    parts = [f"[Image] {filename}"]
    if category:
        parts.append(f"分类: {category}")
    if subcategory:
        parts.append(f"子分类: {subcategory}")
    if image_summary:
        parts.append(f"图片描述: {image_summary}")
    if image_tags:
        parts.append(f"图片标签: {'、'.join(image_tags)}")
    return "\n".join(parts)


def _should_route_image_as_document(
    service: KnowledgeBaseService,
    *,
    suffix: str,
    content_type: str | None = None,
) -> bool:
    normalized_content_type = (content_type or "").lower()
    is_image = (
        suffix in {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
        or normalized_content_type.startswith("image/")
    )
    return is_image and service._should_route_image_to_document_pipeline(suffix)


async def _describe_image_if_enabled(
    service: KnowledgeBaseService,
    *,
    image_path: Path,
    filename: str,
    category: str | None,
    subcategory: str | None,
) -> tuple[str, list[str]]:
    if not service._settings.image_tagging_enabled:
        return "", []

    prepared_path, cleanup_prepared_path = await asyncio.to_thread(
        service._prepare_image_tagging_path,
        image_path,
    )
    try:
        semantic_info = await describe_image(
            str(prepared_path),
            category=category,
            subcategory=subcategory,
            source_name=filename,
            model=service._settings.image_tagging_model,
            max_tags=service._settings.image_tagging_max_tags,
            settings=service._settings,
        )
    finally:
        if cleanup_prepared_path and prepared_path != image_path:
            prepared_path.unlink(missing_ok=True)

    image_summary = str(semantic_info.get("summary") or "").strip()
    image_tags = [
        str(tag).strip()
        for tag in semantic_info.get("tags", [])
        if str(tag).strip()
    ]
    return image_summary, image_tags


async def ingest_text_document(
    service: KnowledgeBaseService,
    *,
    text: str,
    title: str,
    metadata: dict[str, Any],
    chunk_size: int | None,
    chunk_overlap: int | None,
    document_id: str | None = None,
) -> IngestedDocument:
    effective_metadata = dict(metadata)
    document_id = document_id or str(uuid4())
    effective_chunk_size = chunk_size or service._settings.chunk_size
    effective_chunk_overlap = chunk_overlap or service._settings.chunk_overlap
    chunks = build_chunks(
        text,
        document_id=document_id,
        chunk_size=effective_chunk_size,
        chunk_overlap=effective_chunk_overlap,
    )
    if not chunks:
        logger.warning("Text ingest produced no chunks document_id=%s title=%s", document_id, title)
        raise ValueError("Text input is empty after normalization")

    vectors = await asyncio.to_thread(service._embeddings.embed_documents, [chunk.text for chunk in chunks])
    rows = [
        {
            "id": chunk.chunk_id,
            "document_id": document_id,
            "source_name": title,
            "source_type": "text",
            "brand_code": effective_metadata.get("brand_code"),
            "brand_name": effective_metadata.get("brand_name") or effective_metadata.get("category"),
            "product_code": effective_metadata.get("product_code"),
            "product_name": effective_metadata.get("product_name"),
            "chunk_index": chunk.chunk_index,
            "text": chunk.text,
            "metadata_json": json.dumps(effective_metadata, ensure_ascii=False),
            "vector": vector,
        }
        for chunk, vector in zip(chunks, vectors, strict=True)
    ]
    service._store.insert_chunks(
        document_id=document_id,
        source_name=title,
        source_type="text",
        chunk_payloads=rows,
    )

    if "category" in effective_metadata:
        category = effective_metadata["category"]
        file_hash = str(effective_metadata.get("file_hash") or "").strip() or None
        try:
            service._document_categories.add_document(
                document_id,
                category,
                effective_metadata.get("subcategory"),
            )
            if file_hash:
                service._document_registry.update_document_ai_status(
                    category=category,
                    file_hash=file_hash,
                    task_type="facts",
                    status="pending",
                )
            service._spawn_background_task(
                service.generate_and_save_facts(
                    document_id=document_id,
                    category=category,
                    file_hash=file_hash,
                    text=text,
                    subcategory=effective_metadata.get("subcategory"),
                    product_code=effective_metadata.get("product_code"),
                    product_name=effective_metadata.get("product_name"),
                )
            )
        except Exception as exc:
            logger.error("Category/Facts save failed for text document %s: %s", document_id, exc)
            service._store.delete_document(document_id)
            service._document_categories.remove_document(document_id)
            raise ValueError(f"Failed to save text document metadata: {title}") from exc

    return IngestedDocument(
        document_id=document_id,
        source_name=title,
        source_type="text",
        chunk_count=len(rows),
        metadata=effective_metadata,
    )


async def ingest_from_url(
    service: KnowledgeBaseService,
    url: str,
    name: str,
    category: str,
    metadata: dict[str, Any] | None = None,
    task_id: str | None = None,
) -> IngestedDocument:
    if metadata is None:
        metadata = {}
    else:
        metadata = dict(metadata)
    metadata["category"] = category
    metadata["source_url"] = url
    metadata = normalize_upload_metadata(metadata)
    registry_category = resolve_registry_category(metadata.get("category"))

    temp_path, content_type, file_size = await download_remote_content_to_temp_file(
        url=url,
        name=name,
        log_context=f"ingest_from_url:{registry_category}",
    )
    try:
        file_hash = await asyncio.to_thread(_compute_sha256_for_path, temp_path)
        reservation = {
            **build_registry_reservation(
                filename=name,
                file_size=file_size,
                file_hash=file_hash,
            ),
            "original_filename": name,
            "file_size": file_size,
            "file_hash": file_hash,
        }
        service._document_registry.reserve_document_uploads(
            category=registry_category,
            task_id=task_id,
            files=[reservation],
        )
        metadata["file_hash"] = file_hash
        metadata["file_size"] = file_size
        metadata["converted_version"] = int(reservation.get("converted_version", 1))

        suffix = Path(name).suffix.lower()
        is_image = suffix in {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"} or content_type.startswith("image/")
        route_image_as_document = _should_route_image_as_document(
            service,
            suffix=suffix,
            content_type=content_type,
        )
        document_id = str(uuid4())
        if is_image and not route_image_as_document:
            document = await ingest_image(
                service,
                temporary_path=temp_path,
                filename=name,
                document_id=document_id,
                metadata=metadata,
            )
        else:
            try:
                document = await ingest_document(
                    service,
                    temporary_path=temp_path,
                    filename=name,
                    document_id=document_id,
                    metadata=metadata,
                    chunk_size=None,
                    chunk_overlap=None,
                )
            except NoTextExtractedError:
                if not (is_image and route_image_as_document):
                    raise
                logger.warning(
                    "Falling back to image ingestion after document parsing failed name=%s",
                    name,
                )
                document = await ingest_image(
                    service,
                    temporary_path=temp_path,
                    filename=name,
                    document_id=document_id,
                    metadata=metadata,
                )
        service._document_registry.complete_document_upload(
            category=registry_category,
            file_hash=file_hash,
            document_id=document.document_id,
            source_type=document.source_type,
            source_url=document.metadata.get("source_url"),
            original_file_key=document.metadata.get("original_file_key"),
            fulltext_key=document.metadata.get("fulltext_key"),
            converted_version=document.metadata.get("converted_version"),
        )
        service._document_categories.invalidate_latest_document_ids_cache(registry_category)
    except Exception as exc:
        preserve_registry = bool(getattr(exc, "preserve_registry", False))
        if not preserve_registry:
            service._document_registry.release_document_upload(
                category=registry_category,
                file_hash=file_hash,
            )
        raise
    finally:
        temp_path.unlink(missing_ok=True)
    return document


def get_full_text(service: KnowledgeBaseService, document_id: str) -> str | None:
    if not service.oss_client.enabled:
        return None

    document_id = service._document_registry.resolve_latest_document_id(document_id) or document_id

    doc_info = service._get_document_info(document_id)
    metadata = parse_metadata_json(doc_info.get("metadata_json")) if doc_info else {}

    candidate_keys: list[str] = []
    fulltext_key = metadata.get("fulltext_key")
    if fulltext_key:
        candidate_keys.append(fulltext_key)

    legacy_key = legacy_fulltext_object_key(document_id)
    if legacy_key not in candidate_keys:
        candidate_keys.append(legacy_key)

    for object_key in candidate_keys:
        data = service.oss_client.get_object(object_key)
        if data:
            logger.debug("Fulltext loaded from OSS document_id=%s key=%s", document_id, object_key)
            return data.decode("utf-8")

    return None


async def ingest_image(
    service: KnowledgeBaseService,
    *,
    temporary_path: Path,
    filename: str,
    document_id: str,
    metadata: dict[str, Any],
) -> IngestedDocument:
    metadata = dict(metadata)
    converted_version = int(metadata.get("converted_version", 1))

    image_url = None
    oss_key = None
    object_key = build_image_object_key(
        category=metadata.get("category"),
        subcategory=metadata.get("subcategory"),
        filename=filename,
        document_id=document_id,
        converted_version=converted_version,
    )

    effective_metadata = {
        **metadata,
        "original_filename": filename,
        "image_url": image_url,
    }

    if service.oss_client.enabled:
        uploaded_key = await asyncio.to_thread(
            service.oss_client.upload_file,
            str(temporary_path),
            object_key,
        )
        if uploaded_key:
            image_url = f"https://{service.oss_client.bucket_name}.{service.oss_client.endpoint}/{object_key}"
            oss_key = object_key
            effective_metadata["image_url"] = image_url
            effective_metadata["oss_key"] = oss_key
            effective_metadata["original_file_key"] = oss_key
        else:
            raise ValueError(f"Failed to upload image to OSS: {filename}")

    image_summary = ""
    image_tags: list[str] = []
    try:
        image_summary, image_tags = await _describe_image_if_enabled(
            service,
            image_path=temporary_path,
            filename=filename,
            category=effective_metadata.get("category"),
            subcategory=effective_metadata.get("subcategory"),
        )
    except Exception as exc:
        logger.warning("Image semantic tagging failed filename=%s error=%s", filename, exc, exc_info=True)

    if image_summary:
        effective_metadata["image_summary"] = image_summary
    if image_tags:
        effective_metadata["image_tags"] = image_tags

    text_content = _build_image_search_text(
        filename=filename,
        image_summary=image_summary,
        image_tags=image_tags,
        category=effective_metadata.get("category"),
        subcategory=effective_metadata.get("subcategory"),
    )
    try:
        vector = await asyncio.to_thread(
            service._embeddings.embed_image_with_text,
            str(temporary_path),
            text_content,
        )
    except Exception:
        logger.warning("Falling back to image-only embedding filename=%s", filename, exc_info=True)
        vector = await asyncio.to_thread(service._embeddings.embed_image, str(temporary_path))
    source_type = "image"
    try:
        rows = [
            {
                "id": f"{document_id}:0",
                "document_id": document_id,
                "source_name": filename,
                "source_type": source_type,
                "brand_code": effective_metadata.get("brand_code"),
                "brand_name": effective_metadata.get("brand_name") or effective_metadata.get("category"),
                "product_code": effective_metadata.get("product_code"),
                "product_name": effective_metadata.get("product_name"),
                "chunk_index": 0,
                "text": text_content,
                "metadata_json": json.dumps(effective_metadata, ensure_ascii=False),
                "vector": vector,
            }
        ]
        service._store.insert_chunks(
            document_id=document_id,
            source_name=filename,
            source_type=source_type,
            chunk_payloads=rows,
        )
    except Exception as exc:
        if service.oss_client.enabled:
            await asyncio.to_thread(service.oss_client.delete_object, object_key)
        raise ValueError(f"Failed to upload image to milvus: {filename}") from exc

    if "category" in effective_metadata:
        try:
            service._document_categories.add_document(
                document_id,
                effective_metadata["category"],
                effective_metadata.get("subcategory"),
            )
        except Exception as exc:
            service._store.delete_document(document_id)
            if service.oss_client.enabled:
                await asyncio.to_thread(service.oss_client.delete_object, object_key)
            raise ValueError(f"Failed to upload image to sqlite: {filename}") from exc

    return IngestedDocument(
        document_id=document_id,
        source_name=filename,
        source_type=source_type,
        chunk_count=len(rows),
        metadata=effective_metadata,
    )


async def ingest_document(
    service: KnowledgeBaseService,
    *,
    temporary_path: Path,
    filename: str,
    document_id: str,
    metadata: dict[str, Any],
    chunk_size: int | None,
    chunk_overlap: int | None,
) -> IngestedDocument:
    metadata = dict(metadata)
    parsed_ctx = await parse_document_with_policy(
        service,
        temporary_path=temporary_path,
        filename=filename,
        document_id=document_id,
        metadata=metadata,
    )
    stored_ctx = await persist_document_assets(
        service,
        temporary_path=temporary_path,
        filename=filename,
        document_id=document_id,
        parsed_ctx=parsed_ctx,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    return await finalize_document_ingest(
        service,
        filename=filename,
        document_id=document_id,
        stored_ctx=stored_ctx,
    )


async def ingest_staged_file(
    service: KnowledgeBaseService,
    *,
    staged_path: Path,
    filename: str,
    metadata: dict[str, Any],
    chunk_size: int | None,
    chunk_overlap: int | None,
    content_type: str | None = None,
) -> IngestedDocument:
    document_id = str(uuid4())
    suffix = Path(filename).suffix.lower()
    normalized_content_type = (content_type or "").lower()
    is_image = (
        suffix in {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
        or normalized_content_type.startswith("image/")
    )
    route_image_as_document = _should_route_image_as_document(
        service,
        suffix=suffix,
        content_type=content_type,
    )

    if is_image and not route_image_as_document:
        return await ingest_image(
            service,
            temporary_path=staged_path,
            filename=filename,
            document_id=document_id,
            metadata=metadata,
        )
    try:
        return await ingest_document(
            service,
            temporary_path=staged_path,
            filename=filename,
            document_id=document_id,
            metadata=metadata,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
    except NoTextExtractedError:
        if not (is_image and route_image_as_document):
            raise
        logger.warning(
            "Falling back to image ingestion after document parsing failed filename=%s",
            filename,
        )
        return await ingest_image(
            service,
            temporary_path=staged_path,
            filename=filename,
            document_id=document_id,
            metadata=metadata,
        )
