from __future__ import annotations

import argparse
import hashlib
import json
from typing import Optional


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manually add a fact into the project's Milvus facts collection."
    )
    parser.add_argument("fact_text", help="Fact text to insert or merge")
    parser.add_argument(
        "--document-id",
        dest="document_ids",
        action="append",
        required=True,
        help="Attach the fact to an existing document_id. Repeat this flag to attach multiple documents.",
    )
    parser.add_argument(
        "--category",
        default="",
        help="Optional category override. By default the category is inferred from the given document_id.",
    )
    return parser


def _unique_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        candidate = value.strip()
        if candidate and candidate not in seen:
            seen.add(candidate)
            result.append(candidate)
    return result


def _get_document_category(category_mgr, document_id: str) -> Optional[str]:
    with category_mgr._get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT category FROM document_categories WHERE document_id = %s",
                (document_id,),
            )
            row = cursor.fetchone()
    if not row:
        return None
    category = row[0]
    if category is None:
        return None
    return str(category).strip() or None


def _save_document_fact_ids(fact_relations, document_id: str, fact_ids: list[str]) -> None:
    existing_fact_ids = fact_relations.get_fact_ids_by_document(document_id)
    merged_fact_ids = list(dict.fromkeys([*existing_fact_ids, *fact_ids]))
    fact_relations.replace_document_fact_relations(document_id, merged_fact_ids)


def main() -> None:
    from knowledge_base.infrastructure import (
        EmbeddingService,
        MilvusVectorStore,
        get_settings,
        setup_logging,
    )
    from knowledge_base.stores import DocumentCategoryStore, DocumentFactRelationStore

    parser = _build_parser()
    args = parser.parse_args()

    fact_text = str(args.fact_text or "").strip()
    if not fact_text:
        raise SystemExit("fact_text cannot be empty")

    document_ids = _unique_keep_order(list(args.document_ids or []))
    if not document_ids:
        raise SystemExit("At least one --document-id is required")

    settings = get_settings()
    setup_logging(level=settings.log_level, log_file=None)

    category_store = DocumentCategoryStore(settings)
    fact_relations = DocumentFactRelationStore(settings)
    document_categories: dict[str, str] = {}
    missing_document_ids: list[str] = []
    for document_id in document_ids:
        category = _get_document_category(category_store, document_id)
        if not category:
            missing_document_ids.append(document_id)
            continue
        document_categories[document_id] = category

    if missing_document_ids:
        raise SystemExit(
            "These document_ids do not exist in document_categories: "
            + ", ".join(missing_document_ids)
        )

    inferred_categories = list(dict.fromkeys(document_categories.values()))
    category_override = str(args.category or "").strip()
    if category_override:
        if any(category != category_override for category in inferred_categories):
            raise SystemExit(
                "The provided --category does not match all document_ids. "
                f"document categories: {inferred_categories}, override: {category_override}"
            )
        category = category_override
    else:
        if len(inferred_categories) != 1:
            raise SystemExit(
                "All document_ids must belong to the same category when --category is omitted. "
                f"Found categories: {inferred_categories}"
            )
        category = inferred_categories[0]

    embeddings = EmbeddingService(settings)
    store = MilvusVectorStore(settings, embeddings.dimension)

    fact_id = hashlib.sha256(fact_text.encode("utf-8")).hexdigest()
    existing = store.get_fact_by_id(fact_id)

    if existing:
        existing_category = str(existing["category"] or "").strip()
        if existing_category and existing_category != category:
            raise SystemExit(
                "An existing fact with the same fact_id already belongs to another category. "
                f"existing={existing_category}, requested={category}"
            )
        existing_doc_ids = json.loads(existing["document_ids"])
        merged_document_ids = _unique_keep_order(existing_doc_ids + document_ids)
        vector_text = str(existing["fact_text"])
        final_category = existing_category or category
    else:
        merged_document_ids = document_ids
        vector_text = fact_text
        final_category = category

    vector = embeddings.embed_documents([vector_text])[0]
    store.upsert_fact(
        {
            "fact_id": fact_id,
            "fact_text": vector_text,
            "category": final_category,
            "document_ids": json.dumps(merged_document_ids, ensure_ascii=False),
            "vector": vector,
        }
    )

    for document_id in document_ids:
        _save_document_fact_ids(fact_relations, document_id, [fact_id])

    print(
        json.dumps(
            {
                "status": "ok",
                "collection": f"{settings.collection_name}_facts",
                "fact_id": fact_id,
                "category": final_category,
                "document_ids": merged_document_ids,
                "created": existing is None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
