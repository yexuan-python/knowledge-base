from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from knowledge_base.document.domain import IngestedDocument
from knowledge_base.ingest.infrastructure import (
    ParsedDocument,
    WatermarkedDocumentError,
    build_chunks,
    detect_markdown_watermark_residue,
    remove_markdown_watermark_residue,
)
from knowledge_base.ingest.ai import describe_image
from knowledge_base.shared.utils import build_fulltext_object_key, build_original_object_key

if TYPE_CHECKING:
    from knowledge_base.service import KnowledgeBaseService


logger = logging.getLogger(__name__)


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


@dataclass(frozen=True)
class ParsedDocumentContext:
    parsed: ParsedDocument
    suffix: str
    converted_version: int
    parsed_text: str
    parsed_markdown_text: str
    effective_source_type: str
    metadata: dict[str, Any]
    original_file_key: str
    fulltext_key: str


@dataclass(frozen=True)
class StoredDocumentContext:
    effective_metadata: dict[str, Any]
    parsed_text: str
    parsed_markdown_text: str
    effective_source_type: str
    original_file_key: str
    fulltext_key: str
    rows: list[dict[str, Any]]


async def parse_document_with_policy(
    service: KnowledgeBaseService,
    *,
    temporary_path: Path,
    filename: str,
    document_id: str,
    metadata: dict[str, Any],
) -> ParsedDocumentContext:
    suffix = Path(filename).suffix.lower()
    parsing_path = temporary_path
    cleanup_parsing_path = False

    try:
        if service._should_route_image_to_document_pipeline(suffix):
            parsing_path, cleanup_parsing_path = await asyncio.to_thread(
                service._prepare_docmind_image_parsing_path,
                temporary_path,
                suffix,
            )

        parsed = await asyncio.to_thread(
            service._parser.parse_path,
            parsing_path,
            source_name=filename,
            source_url=str(metadata.get("source_url") or "").strip() or None,
        )
    finally:
        if cleanup_parsing_path and parsing_path != temporary_path:
            parsing_path.unlink(missing_ok=True)

    converted_version = int(metadata.get("converted_version", 1))
    original_file_key = build_original_object_key(
        category=metadata.get("category"),
        subcategory=metadata.get("subcategory"),
        filename=filename,
        document_id=document_id,
        converted_version=converted_version,
    )
    fulltext_key = build_fulltext_object_key(
        category=metadata.get("category"),
        subcategory=metadata.get("subcategory"),
        filename=filename,
        document_id=document_id,
        converted_version=converted_version,
    )
    effective_source_type = suffix.lstrip(".") or parsed.source_type
    parsed_text = parsed.text
    parsed_markdown_text = parsed.markdown_text
    effective_metadata = {
        **parsed.metadata,
        **metadata,
    }

    if service._should_route_image_to_document_pipeline(suffix):
        try:
            image_summary, image_tags = await _describe_image_if_enabled(
                service,
                image_path=temporary_path,
                filename=filename,
                category=effective_metadata.get("category"),
                subcategory=effective_metadata.get("subcategory"),
            )
            if image_summary:
                effective_metadata["image_summary"] = image_summary
            if image_tags:
                effective_metadata["image_tags"] = image_tags
                parsed_text = "\n".join(
                    [part for part in [parsed_text, f"图片标签: {'、'.join(image_tags)}"] if part]
                )
                parsed_markdown_text = "\n".join(
                    [part for part in [parsed_markdown_text, f"\n图片标签：{'、'.join(image_tags)}"] if part]
                )
            if image_summary:
                parsed_text = "\n".join(
                    [part for part in [parsed_text, f"图片描述: {image_summary}"] if part]
                )
                parsed_markdown_text = "\n".join(
                    [part for part in [parsed_markdown_text, f"\n图片描述：{image_summary}"] if part]
                )
        except Exception as exc:
            logger.warning(
                "Image semantic tagging failed for DocMind pipeline filename=%s error=%s",
                filename,
                exc,
                exc_info=True,
            )

    return ParsedDocumentContext(
        parsed=parsed,
        suffix=suffix,
        converted_version=converted_version,
        parsed_text=parsed_text,
        parsed_markdown_text=parsed_markdown_text,
        effective_source_type=effective_source_type,
        metadata=effective_metadata,
        original_file_key=original_file_key,
        fulltext_key=fulltext_key,
    )


async def persist_document_assets(
    service: KnowledgeBaseService,
    *,
    temporary_path: Path,
    filename: str,
    document_id: str,
    parsed_ctx: ParsedDocumentContext,
    chunk_size: int | None,
    chunk_overlap: int | None,
) -> StoredDocumentContext:
    effective_metadata = dict(parsed_ctx.metadata)
    uploaded_original_file_key: str | None = None

    if service.oss_client.enabled:
        uploaded_original_key = await asyncio.to_thread(
            service.oss_client.upload_file,
            str(temporary_path),
            parsed_ctx.original_file_key,
        )
        if not uploaded_original_key:
            raise ValueError(f"Failed to upload original file to OSS: {filename}")
        uploaded_original_file_key = parsed_ctx.original_file_key
        effective_metadata["original_file_key"] = parsed_ctx.original_file_key
        effective_metadata["converted_version"] = parsed_ctx.converted_version

    parsed_text, parsed_markdown_text = await _enforce_watermark_policy(
        service,
        filename=filename,
        parsed_ctx=parsed_ctx,
        effective_metadata=effective_metadata,
        uploaded_original_file_key=uploaded_original_file_key,
    )

    if service.oss_client.enabled:
        try:
            uploaded_fulltext_key = await asyncio.to_thread(
                service.oss_client.upload_bytes,
                parsed_markdown_text.encode("utf-8"),
                parsed_ctx.fulltext_key,
                content_type="text/markdown; charset=utf-8",
            )
            if not uploaded_fulltext_key:
                raise ValueError(f"Failed to upload converted markdown to OSS: {filename}")
            effective_metadata["fulltext_key"] = parsed_ctx.fulltext_key
            effective_metadata["converted_version"] = parsed_ctx.converted_version
        except Exception as exc:
            logger.error("OSS upload failed for %s: %s", document_id, exc)
            await asyncio.to_thread(service.oss_client.delete_object, parsed_ctx.fulltext_key)
            await asyncio.to_thread(service.oss_client.delete_object, parsed_ctx.original_file_key)
            raise ValueError(f"Failed to upload fulltext to OSS: {exc}") from exc

    effective_chunk_size = chunk_size or service._settings.chunk_size
    effective_chunk_overlap = chunk_overlap or service._settings.chunk_overlap
    chunks = build_chunks(
        parsed_text,
        document_id=document_id,
        chunk_size=effective_chunk_size,
        chunk_overlap=effective_chunk_overlap,
    )
    if not chunks:
        logger.warning("Document ingest produced no chunks document_id=%s filename=%s", document_id, filename)
        raise ValueError(f"No chunks generated for {filename}")

    vectors = await asyncio.to_thread(service._embeddings.embed_documents, [chunk.text for chunk in chunks])
    rows = [
        {
            "id": chunk.chunk_id,
            "document_id": document_id,
            "source_name": filename,
            "source_type": parsed_ctx.effective_source_type,
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
    try:
        service._store.insert_chunks(
            document_id=document_id,
            source_name=filename,
            source_type=parsed_ctx.effective_source_type,
            chunk_payloads=rows,
        )
    except Exception as exc:
        logger.error("Milvus insert failed for %s: %s", document_id, exc)
        if service.oss_client.enabled:
            await asyncio.to_thread(service.oss_client.delete_object, parsed_ctx.fulltext_key)
            await asyncio.to_thread(service.oss_client.delete_object, parsed_ctx.original_file_key)
        raise ValueError(f"Failed to upload file to milvus: {filename}") from exc

    return StoredDocumentContext(
        effective_metadata=effective_metadata,
        parsed_text=parsed_text,
        parsed_markdown_text=parsed_markdown_text,
        effective_source_type=parsed_ctx.effective_source_type,
        original_file_key=parsed_ctx.original_file_key,
        fulltext_key=parsed_ctx.fulltext_key,
        rows=rows,
    )


async def finalize_document_ingest(
    service: KnowledgeBaseService,
    *,
    filename: str,
    document_id: str,
    stored_ctx: StoredDocumentContext,
) -> IngestedDocument:
    if "category" in stored_ctx.effective_metadata:
        category = stored_ctx.effective_metadata["category"]
        file_hash = str(stored_ctx.effective_metadata.get("file_hash") or "").strip() or None
        try:
            service._document_categories.add_document(
                document_id,
                stored_ctx.effective_metadata["category"],
                stored_ctx.effective_metadata.get("subcategory"),
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
                    text=stored_ctx.parsed_markdown_text,
                    subcategory=stored_ctx.effective_metadata.get("subcategory"),
                    product_code=stored_ctx.effective_metadata.get("product_code"),
                    product_name=stored_ctx.effective_metadata.get("product_name"),
                )
            )
        except Exception as exc:
            logger.error("Category/Facts save failed for %s: %s", document_id, exc)
            service._store.delete_document(document_id)
            if service.oss_client.enabled:
                await asyncio.to_thread(service.oss_client.delete_object, stored_ctx.fulltext_key)
                await asyncio.to_thread(service.oss_client.delete_object, stored_ctx.original_file_key)
            service._document_categories.remove_document(document_id)
            raise ValueError(f"Failed to upload file to sqlite: {filename}") from exc

    return IngestedDocument(
        document_id=document_id,
        source_name=filename,
        source_type=stored_ctx.effective_source_type,
        chunk_count=len(stored_ctx.rows),
        metadata=stored_ctx.effective_metadata,
    )


async def _enforce_watermark_policy(
    service: KnowledgeBaseService,
    *,
    filename: str,
    parsed_ctx: ParsedDocumentContext,
    effective_metadata: dict[str, Any],
    uploaded_original_file_key: str | None,
) -> tuple[str, str]:
    watermark_suspected = bool(parsed_ctx.parsed.metadata.get("pdf_watermark_suspected"))
    parser_backend = str(parsed_ctx.parsed.metadata.get("parser_backend") or "")
    if parsed_ctx.suffix != ".pdf" or not watermark_suspected or parser_backend != "docmind":
        return parsed_ctx.parsed_text, parsed_ctx.parsed_markdown_text

    residue_report = detect_markdown_watermark_residue(
        parsed_ctx.parsed_markdown_text,
        parsed_ctx.parsed.metadata.get("pdf_watermark_candidates", []),
    )
    if not residue_report.has_residue:
        return parsed_ctx.parsed_text, parsed_ctx.parsed_markdown_text

    cleaned_text = remove_markdown_watermark_residue(
        parsed_ctx.parsed_text,
        residue_report.matched_phrases,
    )
    cleaned_markdown_text = remove_markdown_watermark_residue(
        parsed_ctx.parsed_markdown_text,
        residue_report.matched_phrases,
    )
    if cleaned_text and cleaned_markdown_text:
        removed_candidates = list(residue_report.matched_phrases)
        effective_metadata["pdf_watermark_removed"] = True
        effective_metadata["pdf_watermark_removed_candidates"] = removed_candidates
        logger.warning(
            "Removed PDF watermark residue filename=%s candidates=%s",
            filename,
            removed_candidates,
        )
        return cleaned_text, cleaned_markdown_text

    if effective_metadata.get("category") and effective_metadata.get("file_hash"):
        service._document_registry.update_document_registry_upload_result(
            category=str(effective_metadata["category"]),
            file_hash=str(effective_metadata["file_hash"]),
            original_file_key=uploaded_original_file_key,
            source_type=parsed_ctx.suffix.lstrip("."),
            converted_version=parsed_ctx.converted_version,
            status="failed",
        )
    matched = "、".join(residue_report.matched_phrases[:3])
    detail = f" 检测到疑似水印内容：{matched}" if matched else ""
    raise WatermarkedDocumentError(
        f"文件存在水印，需要人工去水印后再上传。{detail}".strip(),
        preserve_registry=True,
    )
