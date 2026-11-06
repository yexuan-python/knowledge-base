from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import sys
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Sync uploaded brand attachment markdown into Milvus document chunks and attachment_temp facts only. "
            "This script does not run conflict scan, Tianyancha enrichment, callbacks, or full knowledge generation."
        )
    )
    parser.add_argument("--task-id", required=True, help="upload_tasks.task_id to sync")
    parser.add_argument("--chunk-size", type=int, default=None, help="Override KB_CHUNK_SIZE")
    parser.add_argument("--chunk-overlap", type=int, default=None, help="Override KB_CHUNK_OVERLAP")
    parser.add_argument(
        "--skip-chunks",
        action="store_true",
        help="Skip writing attachment markdown chunks to the main Milvus documents collection.",
    )
    parser.add_argument(
        "--skip-facts",
        action="store_true",
        help="Skip AI fact extraction and facts upsert.",
    )
    parser.add_argument(
        "--keep-existing-chunks",
        action="store_true",
        help="Do not delete existing Milvus chunks for asset_<asset_id> before inserting new chunks.",
    )
    parser.add_argument(
        "--keep-existing-task-facts",
        action="store_true",
        help="Do not delete existing attachment_temp facts for this task before extracting facts.",
    )
    return parser


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _fact_hash(*, brand_code: str, fact_text: str) -> str:
    return hashlib.sha256(f"{brand_code}{fact_text}".encode("utf-8")).hexdigest()


def _normalize_fact_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _asset_source_document(asset: dict[str, Any]) -> dict[str, Any]:
    asset_id = int(asset.get("id") or 0)
    filename = _normalize_text(asset.get("original_filename")) or f"asset-{asset_id}"
    return {
        "asset_id": asset_id,
        "document_id": f"asset_{asset_id}",
        "brand_code": _normalize_text(asset.get("brand_code")),
        "brand_name": _normalize_text(asset.get("brand_name")),
        "original_filename": filename,
        "source_url": _normalize_text(asset.get("source_url")) or None,
        "source_role": "attachment_asset",
        "source_type": _normalize_text(asset.get("parsed_source_type")) or "attachment",
        "markdown_text": _normalize_text(asset.get("parsed_markdown")),
    }


def _extract_fact_texts(facts_json_str: str) -> list[str]:
    try:
        facts_payload = json.loads(facts_json_str)
    except json.JSONDecodeError as exc:
        raise ValueError("AI facts response is not valid JSON") from exc

    fact_texts: list[str] = []
    for item in facts_payload if isinstance(facts_payload, list) else []:
        if not isinstance(item, dict):
            continue
        for value in item.values():
            if isinstance(value, list):
                fact_texts.extend(_normalize_text(entry) for entry in value if _normalize_text(entry))
            else:
                normalized = _normalize_text(value)
                if normalized:
                    fact_texts.append(normalized)
    return fact_texts


async def _sync_document_chunks(
    *,
    store: Any,
    embeddings: Any,
    settings: Any,
    source_documents: list[dict[str, Any]],
    chunk_size: int | None,
    chunk_overlap: int | None,
    replace_existing: bool,
) -> dict[str, int]:
    from knowledge_base.ingest.infrastructure.chunking import build_chunks

    effective_chunk_size = chunk_size or int(getattr(settings, "chunk_size", 1200) or 1200)
    effective_chunk_overlap = chunk_overlap or int(getattr(settings, "chunk_overlap", 150) or 150)
    total_chunks = 0
    success_documents = 0
    failed_documents = 0

    for source_document in source_documents:
        markdown_text = _normalize_text(source_document.get("markdown_text"))
        document_id = _normalize_text(source_document.get("document_id"))
        source_name = _normalize_text(source_document.get("original_filename")) or document_id
        if not markdown_text or not document_id:
            failed_documents += 1
            logger.warning("Attachment chunk sync skipped empty source document_id=%s source_name=%s", document_id, source_name)
            continue

        chunks = build_chunks(
            markdown_text,
            document_id=document_id,
            chunk_size=effective_chunk_size,
            chunk_overlap=effective_chunk_overlap,
        )
        if not chunks:
            failed_documents += 1
            logger.warning("Attachment chunk sync produced no chunks document_id=%s source_name=%s", document_id, source_name)
            continue

        try:
            if replace_existing:
                store.delete_document(document_id)
            vectors = await asyncio.to_thread(embeddings.embed_documents, [chunk.text for chunk in chunks])
            metadata = {
                "brand_code": source_document.get("brand_code"),
                "brand_name": source_document.get("brand_name"),
                "category": source_document.get("brand_name"),
                "asset_id": source_document.get("asset_id"),
                "source_url": source_document.get("source_url"),
                "source_type": "attachment_asset",
            }
            rows = [
                {
                    "id": chunk.chunk_id,
                    "document_id": document_id,
                    "source_name": source_name,
                    "source_type": "attachment_asset",
                    "brand_code": _normalize_text(source_document.get("brand_code")),
                    "brand_name": _normalize_text(source_document.get("brand_name")),
                    "chunk_index": chunk.chunk_index,
                    "text": chunk.text,
                    "metadata_json": json.dumps(metadata, ensure_ascii=False),
                    "vector": vector,
                }
                for chunk, vector in zip(chunks, vectors, strict=True)
            ]
            store.insert_chunks(
                document_id=document_id,
                source_name=source_name,
                source_type="attachment_asset",
                chunk_payloads=rows,
            )
        except Exception as exc:  # noqa: BLE001
            failed_documents += 1
            logger.warning(
                "Attachment chunk sync failed document_id=%s source_name=%s error_type=%s error=%s",
                document_id,
                source_name,
                exc.__class__.__name__,
                exc,
                exc_info=True,
            )
            continue

        success_documents += 1
        total_chunks += len(chunks)

    return {
        "chunk_success_documents": success_documents,
        "chunk_failed_documents": failed_documents,
        "chunk_count": total_chunks,
    }


async def _sync_attachment_temp_facts(
    *,
    facts_store: Any,
    store: Any,
    embeddings: Any,
    settings: Any,
    source_task_id: str,
    source_documents: list[dict[str, Any]],
    replace_existing_task_facts: bool,
) -> dict[str, int]:
    from knowledge_base.document.ai.facts import extract_facts_from_text

    if replace_existing_task_facts:
        stale_rows = facts_store.list_by_source_task_id_and_scope(
            source_task_id=source_task_id,
            fact_scope="attachment_temp",
        )
        stale_fact_ids = [
            _normalize_text(row.get("fact_id"))
            for row in stale_rows
            if _normalize_text(row.get("fact_id"))
        ]
        deleted_count = facts_store.delete_by_source_task_id_and_scope(
            source_task_id=source_task_id,
            fact_scope="attachment_temp",
        )
        if stale_fact_ids:
            store.delete_facts_by_ids(stale_fact_ids)
        logger.info(
            "Existing attachment_temp facts cleared source_task_id=%s mysql_deleted=%s milvus_deleted=%s",
            source_task_id,
            deleted_count,
            len(stale_fact_ids),
        )

    fact_rows: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    success_documents = 0
    failed_documents = 0
    for source_document in source_documents:
        markdown_text = _normalize_text(source_document.get("markdown_text"))
        source_name = _normalize_text(source_document.get("original_filename")) or _normalize_text(source_document.get("document_id"))
        brand_code = _normalize_text(source_document.get("brand_code"))
        brand_name = _normalize_text(source_document.get("brand_name"))
        if not markdown_text or not brand_code or not brand_name:
            failed_documents += 1
            logger.warning("Attachment facts sync skipped invalid source source_name=%s", source_name)
            continue

        try:
            facts_json_str = await extract_facts_from_text(
                markdown_text,
                category=brand_name,
                subcategory=None,
                source_name=source_name,
                settings=settings,
            )
            raw_fact_texts = _extract_fact_texts(facts_json_str)
        except Exception as exc:  # noqa: BLE001
            failed_documents += 1
            logger.warning(
                "Attachment facts sync failed source_name=%s error_type=%s error=%s",
                source_name,
                exc.__class__.__name__,
                exc,
                exc_info=True,
            )
            continue

        success_documents += 1
        for fact_text in raw_fact_texts:
            normalized_fact_text = _normalize_fact_text(fact_text)
            if not normalized_fact_text:
                continue
            fact_id = _fact_hash(brand_code=brand_code, fact_text=normalized_fact_text)
            if fact_id in seen_hashes:
                continue
            seen_hashes.add(fact_id)
            fact_rows.append(
                {
                    "brand_code": brand_code,
                    "brand_name": brand_name,
                    "fact_scope": "attachment_temp",
                    "fact_id": fact_id,
                    "fact_text": fact_text,
                    "normalized_fact_hash": fact_id,
                    "source_document_id": _normalize_text(source_document.get("document_id")),
                    "source_task_id": source_task_id,
                    "source_asset_id": int(source_document.get("asset_id") or 0) or None,
                    "full_knowledge_file_id": None,
                    "version_no": None,
                    "knowledge_date": None,
                    "section_path": None,
                }
            )

    if not fact_rows:
        return {
            "fact_success_documents": success_documents,
            "fact_failed_documents": failed_documents,
            "fact_count": 0,
        }

    vectors = await asyncio.to_thread(embeddings.embed_documents, [row["fact_text"] for row in fact_rows])
    milvus_rows: list[dict[str, Any]] = []
    for row, vector in zip(fact_rows, vectors, strict=True):
        facts_store.upsert_fact(**row)
        milvus_rows.append(
            {
                "fact_id": row["fact_id"],
                "fact_text": row["fact_text"],
                "brand_code": row["brand_code"],
                "brand_name": row["brand_name"],
                "category": row["brand_name"],
                "source_document_id": row["source_document_id"],
                "document_ids": json.dumps([row["source_document_id"]], ensure_ascii=False),
                "vector": vector,
            }
        )
    store.upsert_facts(milvus_rows)
    return {
        "fact_success_documents": success_documents,
        "fact_failed_documents": failed_documents,
        "fact_count": len(fact_rows),
    }


async def _main() -> None:
    from knowledge_base.infrastructure import EmbeddingService, MilvusVectorStore, get_settings, setup_logging
    from knowledge_base.stores import BrandAttachmentAssetStore, BrandKnowledgeFactStore

    parser = _build_parser()
    args = parser.parse_args()

    if args.skip_chunks and args.skip_facts:
        raise SystemExit("Nothing to do: --skip-chunks and --skip-facts cannot both be set")

    source_task_id = _normalize_text(args.task_id)
    if not source_task_id:
        raise SystemExit("--task-id cannot be empty")

    settings = get_settings()
    setup_logging(level=settings.log_level, log_file=None)

    embeddings = EmbeddingService(settings)
    store = MilvusVectorStore(settings, embeddings.dimension)
    attachment_assets = BrandAttachmentAssetStore(settings)
    facts_store = BrandKnowledgeFactStore(settings)

    assets = attachment_assets.list_by_upload_task_id(upload_task_id=source_task_id)
    source_documents = [
        source_document
        for source_document in (_asset_source_document(asset) for asset in assets)
        if _normalize_text(source_document.get("markdown_text"))
    ]
    if not source_documents:
        raise SystemExit(f"No parsed attachment markdown found for task_id={source_task_id}")

    logger.info(
        "Attachment assets ingest started source_task_id=%s asset_count=%s skip_chunks=%s skip_facts=%s",
        source_task_id,
        len(source_documents),
        args.skip_chunks,
        args.skip_facts,
    )

    result: dict[str, Any] = {
        "source_task_id": source_task_id,
        "asset_count": len(source_documents),
        "document_ids": [source_document["document_id"] for source_document in source_documents],
    }
    if not args.skip_chunks:
        result.update(
            await _sync_document_chunks(
                store=store,
                embeddings=embeddings,
                settings=settings,
                source_documents=source_documents,
                chunk_size=args.chunk_size,
                chunk_overlap=args.chunk_overlap,
                replace_existing=not args.keep_existing_chunks,
            )
        )
    if not args.skip_facts:
        result.update(
            await _sync_attachment_temp_facts(
                facts_store=facts_store,
                store=store,
                embeddings=embeddings,
                settings=settings,
                source_task_id=source_task_id,
                source_documents=source_documents,
                replace_existing_task_facts=not args.keep_existing_task_facts,
            )
        )

    logger.info("Attachment assets ingest completed result=%s", json.dumps(result, ensure_ascii=False))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
