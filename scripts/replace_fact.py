from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Replace one fact in the project's Milvus facts collection and keep MySQL relations in sync."
    )
    parser.add_argument("old_fact_text", help="Existing fact text to replace")
    parser.add_argument("new_fact_text", help="New fact text")
    parser.add_argument(
        "--category",
        default="",
        help="Optional category check. If provided, the existing fact must belong to this category.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write the change. Without this flag the script only shows a preview.",
    )
    return parser


def _normalize_text(value: str) -> str:
    return str(value or "").strip()


def _replace_fact_relations(fact_relations, *, old_fact_id: str, new_fact_id: str) -> int:
    with fact_relations._get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT document_id FROM document_fact_relations WHERE fact_id = %s",
                (old_fact_id,),
            )
            document_ids = [str(row[0]) for row in cursor.fetchall() if row and row[0]]
            if document_ids:
                cursor.executemany(
                    "INSERT IGNORE INTO document_fact_relations (document_id, fact_id) VALUES (%s, %s)",
                    [(document_id, new_fact_id) for document_id in document_ids],
                )
                cursor.execute(
                    "DELETE FROM document_fact_relations WHERE fact_id = %s",
                    (old_fact_id,),
                )
    return len(document_ids)


def main() -> None:
    from knowledge_base.infrastructure import (
        EmbeddingService,
        MilvusVectorStore,
        get_settings,
        setup_logging,
    )
    from knowledge_base.stores import DocumentFactRelationStore

    parser = _build_parser()
    args = parser.parse_args()

    old_fact_text = _normalize_text(args.old_fact_text)
    new_fact_text = _normalize_text(args.new_fact_text)
    category_check = _normalize_text(args.category)

    if not old_fact_text:
        raise SystemExit("old_fact_text cannot be empty")
    if not new_fact_text:
        raise SystemExit("new_fact_text cannot be empty")
    if old_fact_text == new_fact_text:
        raise SystemExit("old_fact_text and new_fact_text are identical")

    old_fact_id = hashlib.sha256(old_fact_text.encode("utf-8")).hexdigest()
    new_fact_id = hashlib.sha256(new_fact_text.encode("utf-8")).hexdigest()

    settings = get_settings()
    setup_logging(level=settings.log_level, log_file=None)

    fact_relations = DocumentFactRelationStore(settings)
    embeddings = EmbeddingService(settings)
    store = MilvusVectorStore(settings, embeddings.dimension)

    old_fact = store.get_fact_by_id(old_fact_id)
    if not old_fact:
        raise SystemExit(
            "Existing fact not found in Milvus facts collection. "
            f"fact_id={old_fact_id}"
        )

    old_category = _normalize_text(old_fact.get("category"))
    if category_check and old_category != category_check:
        raise SystemExit(
            "Existing fact category does not match --category. "
            f"existing={old_category!r}, expected={category_check!r}"
        )

    document_ids = json.loads(old_fact.get("document_ids") or "[]")
    if not isinstance(document_ids, list):
        raise SystemExit("Existing fact document_ids is not a JSON list")
    document_ids = [str(document_id).strip() for document_id in document_ids if str(document_id).strip()]
    document_ids = list(dict.fromkeys(document_ids))

    new_fact = store.get_fact_by_id(new_fact_id)
    merged_document_ids = list(document_ids)
    if new_fact:
        new_category = _normalize_text(new_fact.get("category"))
        if old_category and new_category and new_category != old_category:
            raise SystemExit(
                "Target fact_id already exists under another category. "
                f"existing={new_category!r}, source={old_category!r}"
            )
        existing_new_document_ids = json.loads(new_fact.get("document_ids") or "[]")
        merged_document_ids = list(
            dict.fromkeys(
                [
                    str(document_id).strip()
                    for document_id in list(existing_new_document_ids) + merged_document_ids
                    if str(document_id).strip()
                ]
            )
        )

    preview = {
        "collection": f"{settings.collection_name}_facts",
        "old_fact_id": old_fact_id,
        "new_fact_id": new_fact_id,
        "category": old_category,
        "document_ids": merged_document_ids,
        "new_fact_already_exists": new_fact is not None,
        "apply": bool(args.apply),
    }

    if not args.apply:
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        return

    vector = embeddings.embed_documents([new_fact_text])[0]
    store.upsert_fact(
        {
            "fact_id": new_fact_id,
            "fact_text": new_fact_text,
            "category": old_category,
            "document_ids": json.dumps(merged_document_ids, ensure_ascii=False),
            "vector": vector,
        }
    )

    relation_count = _replace_fact_relations(
        fact_relations,
        old_fact_id=old_fact_id,
        new_fact_id=new_fact_id,
    )

    if old_fact_id != new_fact_id:
        store.delete_fact(old_fact_id)

    result = dict(preview)
    result["updated_relation_count"] = relation_count
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
