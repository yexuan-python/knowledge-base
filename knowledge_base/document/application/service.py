from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
from dataclasses import dataclass
from collections.abc import Callable
from typing import Any

from knowledge_base.brand.application.brand_scope import resolve_brand_scope_from_codes
from knowledge_base.document.ai import extract_facts_from_text
from knowledge_base.document.ai.facts import parse_facts_json_response
from knowledge_base.shared.utils import legacy_fulltext_object_key, parse_metadata_json


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DocumentApplicationDependencies:
    settings: Any
    store: Any
    embeddings: Any
    document_categories: Any
    document_registry: Any
    fact_relations: Any
    oss_client: Any
    get_document_info: Any
    get_full_text: Any
    notify_ai_failure_if_ready: Any
    finalize_task_callback_from_document: Any
    brands: Any = None
    brand_products: Any = None
    brand_full_knowledge: Any = None


class DocumentApplicationService:
    def __init__(self, dependencies: DocumentApplicationDependencies) -> None:
        self._deps = dependencies

    async def delete_document(
        self,
        document_id: str,
        *,
        oss_object_key_filter: Callable[[str], bool] | None = None,
    ) -> bool:
        doc_info = self._deps.get_document_info(document_id)
        registry_entry = self._deps.document_registry.get_document_registry_entry(document_id)
        if (
            not doc_info
            and not registry_entry
            and not self._deps.document_categories.document_exists(document_id)
        ):
            return False

        await self.remove_document_from_facts(document_id)
        self._deps.document_registry.delete_document_registration(document_id)
        if registry_entry and registry_entry.get("category"):
            self._deps.document_categories.invalidate_latest_document_ids_cache(str(registry_entry["category"]))

        if self._deps.oss_client.enabled:
            for object_key in self.collect_document_object_keys(
                document_id=document_id,
                doc_info=doc_info,
                registry_entry=registry_entry,
            ):
                if oss_object_key_filter is not None and not oss_object_key_filter(object_key):
                    logger.info(
                        "Skipping OSS object delete outside allowed prefix document_id=%s object_key=%s",
                        document_id,
                        object_key,
                    )
                    continue
                self._deps.oss_client.delete_object(object_key)

        self._deps.store.delete_document(document_id)
        self._deps.document_categories.remove_document(document_id)
        return True

    async def delete_document_by_attachment_name(
        self,
        attachment_name: str,
        *,
        url: str | None = None,
        category: str | None = None,
    ) -> str | None:
        matches = self._deps.document_registry.find_latest_success_documents_by_filename(
            attachment_name,
            category=category,
            source_url=url,
        )
        if not matches:
            return None
        if len(matches) > 1:
            categories = "、".join(sorted({str(item["category"]) for item in matches if item.get("category")}))
            if url:
                raise ValueError(
                    "找到多个同名同 URL 附件，请传入 category 消歧: "
                    f"attachment_name={attachment_name}, url={url}, categories={categories}"
                )
            raise ValueError(
                f"找到多个同名附件，请传入 category 消歧: attachment_name={attachment_name}, categories={categories}"
            )

        document_id = str(matches[0]["document_id"])
        deleted = await self.delete_document(document_id)
        return document_id if deleted else None

    async def remove_document_from_facts(self, document_id: str) -> None:
        relations = self._deps.fact_relations.get_fact_ids_by_document(document_id)
        for fact_id in relations:
            fact = self._deps.store.get_fact_by_id(fact_id)
            if fact:
                doc_ids = json.loads(fact["document_ids"])
                doc_ids = [did for did in doc_ids if did != document_id]
                if doc_ids:
                    vector = fact.get("vector")
                    if vector is None:
                        vector_batch = await asyncio.to_thread(
                            self._deps.embeddings.embed_documents,
                            [fact["fact_text"]],
                        )
                        vector = vector_batch[0]
                    self._deps.store.upsert_fact(
                        {
                            "fact_id": fact_id,
                            "fact_text": fact["fact_text"],
                            "category": fact["category"],
                            "document_ids": json.dumps(doc_ids),
                            "vector": vector,
                        }
                    )
                else:
                    self._deps.store.delete_fact(fact_id)
        self._deps.fact_relations.delete_document_fact_relations(document_id)

    async def generate_and_save_facts(
        self,
        *,
        document_id: str,
        category: str,
        file_hash: str | None,
        text: str,
        subcategory: str | None = None,
        product_code: str | None = None,
        product_name: str | None = None,
    ) -> None:
        max_retries = 3
        empty_retry_limit = 2
        retry_delay = 3

        if not self._deps.document_categories.document_exists(document_id):
            logger.info("Document %s no longer exists, skipping facts generation.", document_id)
            return

        if file_hash:
            self._deps.document_registry.update_document_ai_status(
                category=category,
                file_hash=file_hash,
                task_type="facts",
                status="processing",
            )

        empty_result_retries = 0

        for attempt in range(1, max_retries + 1):
            try:
                if not self._deps.document_categories.document_exists(document_id):
                    return

                doc_info = self._deps.get_document_info(document_id)
                source_name = doc_info.get("source_name") if doc_info else None
                doc_metadata = parse_metadata_json((doc_info or {}).get("metadata_json"))
                resolved_product_code = str(product_code or doc_metadata.get("product_code") or "").strip() or None
                resolved_product_name = (
                    str(product_name or doc_metadata.get("product_name") or subcategory or "").strip() or None
                )

                facts_json_str = await extract_facts_from_text(
                    text,
                    category=category,
                    subcategory=subcategory,
                    source_name=source_name,
                    settings=self._deps.settings,
                )
                facts_list = await parse_facts_json_response(
                    facts_json_str,
                    source_name=source_name,
                    settings=self._deps.settings,
                )
                all_facts = []
                for item in facts_list:
                    for _, value in item.items():
                        if isinstance(value, list):
                            all_facts.extend(value)
                        else:
                            all_facts.append(value)
                unique_facts = list(dict.fromkeys(all_facts))
                extracted_fact_count = len(all_facts)
                deduplicated_fact_count = len(unique_facts)

                if not unique_facts:
                    if empty_result_retries < empty_retry_limit:
                        empty_result_retries += 1
                        logger.warning(
                            "No facts extracted for document %s attempt=%s empty_retry=%s/%s",
                            document_id,
                            attempt,
                            empty_result_retries,
                            empty_retry_limit,
                        )
                        await asyncio.sleep(retry_delay * empty_result_retries)
                        continue
                    if file_hash:
                        self._deps.document_registry.update_document_ai_status(
                            category=category,
                            file_hash=file_hash,
                            task_type="facts",
                            status="success",
                            error_message="提取为空",
                        )
                        await self._after_ai_status_terminal(category=category, file_hash=file_hash)
                    logger.warning("No facts extracted for document %s after retries", document_id)
                    return

                fact_records = [
                    {
                        "fact_id": hashlib.sha256(fact_text.encode("utf-8")).hexdigest(),
                        "fact_text": fact_text,
                    }
                    for fact_text in unique_facts
                ]
                fact_ids = [item["fact_id"] for item in fact_records]
                existing_map = self._deps.store.get_facts_by_ids(fact_ids)

                update_records: list[dict[str, Any]] = []
                new_records: list[dict[str, Any]] = []
                new_fact_texts: list[str] = []
                for item in fact_records:
                    fact_id = item["fact_id"]
                    fact_text = item["fact_text"]
                    existing = existing_map.get(fact_id)
                    if existing:
                        doc_ids = json.loads(existing["document_ids"])
                        if document_id not in doc_ids:
                            doc_ids.append(document_id)
                            vector = existing.get("vector")
                            if vector is None:
                                raise ValueError(f"Existing fact missing vector fact_id={fact_id}")
                            update_records.append(
                                {
                                    "fact_id": fact_id,
                                    "fact_text": existing["fact_text"],
                                    "category": existing["category"],
                                    "document_ids": json.dumps(doc_ids),
                                    "vector": vector,
                                }
                            )
                        continue

                    new_records.append(
                        {
                            "fact_id": fact_id,
                            "fact_text": fact_text,
                            "category": category,
                            "brand_code": str(doc_metadata.get("brand_code") or "").strip() or None,
                            "brand_name": str(doc_metadata.get("brand_name") or category or "").strip() or None,
                            "product_code": resolved_product_code,
                            "product_name": resolved_product_name,
                            "document_ids": json.dumps([document_id]),
                        }
                    )
                    new_fact_texts.append(fact_text)

                reused_fact_count = len(existing_map)
                updated_fact_count = len(update_records)
                new_fact_count = len(new_records)
                embedding_batch_size = 20
                embedding_batch_count = math.ceil(new_fact_count / embedding_batch_size) if new_fact_count else 0
                logger.info(
                    "Facts extracted document_id=%s category=%s extracted=%s deduplicated=%s existing=%s reused=%s new=%s embedding_batches=%s",
                    document_id,
                    category,
                    extracted_fact_count,
                    deduplicated_fact_count,
                    reused_fact_count,
                    updated_fact_count,
                    new_fact_count,
                    embedding_batch_count,
                )

                if new_records:
                    new_vectors = await asyncio.to_thread(self._deps.embeddings.embed_documents, new_fact_texts)
                    for record, vector in zip(new_records, new_vectors, strict=True):
                        record["vector"] = vector

                if update_records:
                    self._deps.store.upsert_facts(update_records, partial_update=True)
                if new_records:
                    self._deps.store.upsert_facts(new_records)

                self._deps.fact_relations.replace_document_fact_relations(document_id, fact_ids)
                if file_hash:
                    self._deps.document_registry.update_document_ai_status(
                        category=category,
                        file_hash=file_hash,
                        task_type="facts",
                        status="success",
                    )
                    await self._after_ai_status_terminal(category=category, file_hash=file_hash)
                logger.info("Facts (global deduped) saved for document %s, category=%s", document_id, category)
                return
            except Exception as exc:
                logger.error(
                    "Failed to generate facts for %s (attempt %s/%s): %s",
                    document_id,
                    attempt,
                    max_retries,
                    exc,
                )
                if attempt < max_retries:
                    await asyncio.sleep(retry_delay * (2 ** (attempt - 1)))
                else:
                    if file_hash:
                        self._deps.document_registry.update_document_ai_status(
                            category=category,
                            file_hash=file_hash,
                            task_type="facts",
                            status="failed",
                            error_message=str(exc),
                        )
                        await self._after_ai_status_terminal(category=category, file_hash=file_hash)
                    raise Exception(f"{document_id} 事实提取失败: {exc}") from exc

    def build_search_hits(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        groups: dict[str, dict[str, Any]] = {}
        for item in results:
            entity = item.get("entity", {})
            doc_id = entity.get("document_id", "")
            if not doc_id:
                continue
            if doc_id not in groups:
                groups[doc_id] = {
                    "source_name": entity.get("source_name", ""),
                    "source_type": entity.get("source_type", ""),
                    "metadata": json.loads(entity.get("metadata_json") or "{}"),
                    "chunks": [],
                }
            groups[doc_id]["chunks"].append(
                {
                    "chunk_id": str(item.get("id")),
                    "chunk_index": int(entity.get("chunk_index", 0)),
                    "score": float(item.get("distance", 0.0)),
                    "text": entity.get("text", ""),
                }
            )

        hits = []
        for doc_id, info in groups.items():
            source_type = info["source_type"]
            metadata = info["metadata"].copy()
            fulltext_key = metadata.get("fulltext_key")
            oss_key = metadata.get("oss_key")

            hit = {
                "document_id": doc_id,
                "source_name": info["source_name"],
                "source_type": source_type,
                "metadata": metadata,
                "chunks": info["chunks"],
            }

            if source_type != "image":
                candidate_key = fulltext_key
                if source_type != "text" and not candidate_key:
                    candidate_key = legacy_fulltext_object_key(doc_id)
                if candidate_key:
                    oss_url = self._deps.oss_client.build_object_url(candidate_key)
                    if oss_url:
                        hit["file_url"] = oss_url
            else:
                image_url = metadata.pop("image_url", None)
                if not image_url and oss_key:
                    image_url = self._deps.oss_client.build_object_url(oss_key)
                if image_url:
                    hit["file_url"] = image_url

            hits.append(hit)

        return hits

    async def search_facts_by_brand_name(
        self,
        brand_name: str,
        query: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        return await self.search_facts(
            brand_name=brand_name,
            query=query,
            top_k=top_k,
        )

    async def search_facts(
        self,
        *,
        brand_code: str | None = None,
        brand_name: str | None = None,
        category: str | None = None,
        product_code: str | None = None,
        query: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        query_vector = await asyncio.to_thread(self._deps.embeddings.embed_query, query)
        brand_context = self._resolve_fact_search_context(
            brand_code=brand_code,
            brand_name=brand_name,
            category=category,
            product_code=product_code,
        )
        normalized_brand_name = str(brand_context.get("brand_name") or brand_name or category or "").strip()
        if str(product_code or "").strip() and not brand_context.get("product_code"):
            return []
        if not normalized_brand_name:
            return []
        brand_code = brand_context["brand_code"]
        results = self._deps.store.search_facts(
            query_vector,
            normalized_brand_name,
            top_k,
            brand_code=brand_code,
        )
        filtered_results: list[dict[str, Any]] = []
        for hit in results:
            entity = hit["entity"]
            doc_ids = json.loads(entity["document_ids"])
            if brand_context["is_brand_category"]:
                matched_doc_ids = list(doc_ids)
            else:
                latest_doc_ids = set(self._deps.document_categories.get_latest_document_ids_by_category(normalized_brand_name))
                matched_doc_ids = [doc_id for doc_id in doc_ids if doc_id in latest_doc_ids]
                if not matched_doc_ids:
                    continue
            filtered_results.append(
                {
                    "fact": entity["fact_text"],
                    "score": hit["distance"],
                    "document_count": len(matched_doc_ids),
                    "metadata": self._fact_metadata(entity=entity, context=brand_context),
                }
            )
        return filtered_results

    async def search_facts_by_category(
        self,
        category: str,
        query: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        return await self.search_facts_by_brand_name(category, query, top_k)

    async def search_facts_by_brand_name_matched(
        self,
        brand_name: str,
        query: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        query_vector = await asyncio.to_thread(self._deps.embeddings.embed_query, query)
        normalized_brand_name = str(brand_name or "").strip()
        brand_context = self._resolve_brand_fact_search_context(normalized_brand_name)
        brand_code = brand_context["brand_code"]

        results = self._deps.store.search_facts(
            query_vector,
            normalized_brand_name,
            top_k,
            brand_code=brand_code,
        )
        filtered_results: list[dict[str, Any]] = []
        for hit in results:
            doc_ids = json.loads(hit["entity"]["document_ids"])
            if brand_context["is_brand_category"]:
                matched_doc_ids = list(doc_ids)
            else:
                latest_doc_ids = set(self._deps.document_categories.get_latest_document_ids_by_category(normalized_brand_name))
                matched_doc_ids = [doc_id for doc_id in doc_ids if doc_id in latest_doc_ids]
                if not matched_doc_ids:
                    continue
            filtered_results.append(
                {
                    "fact": hit["entity"]["fact_text"],
                    "score": hit["distance"],
                    "document_ids": matched_doc_ids,
                }
            )
        return filtered_results

    async def search_facts_by_category_matched(
        self,
        category: str,
        query: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        return await self.search_facts_by_brand_name_matched(category, query, top_k)

    def _resolve_brand_fact_search_context(self, brand_name: str | None) -> dict[str, Any]:
        return self._resolve_fact_search_context(brand_name=brand_name)

    def _resolve_fact_search_context(
        self,
        *,
        brand_code: str | None = None,
        brand_name: str | None = None,
        category: str | None = None,
        product_code: str | None = None,
    ) -> dict[str, Any]:
        scope = resolve_brand_scope_from_codes(
            self._deps,
            brand_code=brand_code,
            brand_name=brand_name,
            category=category,
            product_code=product_code,
        )
        normalized_brand_code = str(scope.brand_code or brand_code or "").strip()
        normalized_product_code = str(scope.product_code or product_code or "").strip()
        normalized_brand_name = str(scope.brand_name or brand_name or category or "").strip()
        brands = getattr(self._deps, "brands", None)

        if normalized_product_code:
            return {
                "is_brand_category": True,
                "brand_code": normalized_brand_code or None,
                "brand_name": normalized_brand_name or None,
                "product_code": normalized_product_code,
                "product_name": scope.product_name,
                "latest_document_id": None,
            }

        if normalized_brand_code and scope.brand:
            return {
                "is_brand_category": True,
                "brand_code": normalized_brand_code or None,
                "brand_name": normalized_brand_name or None,
                "product_code": None,
                "product_name": None,
                "latest_document_id": None,
            }

        normalized_brand_name = str(brand_name or "").strip()
        if not normalized_brand_name:
            return {
                "is_brand_category": False,
                "brand_code": None,
                "brand_name": None,
                "product_code": None,
                "product_name": None,
                "latest_document_id": None,
            }

        if brands is None or not hasattr(brands, "get_brand_by_name"):
            return {
                "is_brand_category": False,
                "brand_code": None,
                "brand_name": normalized_brand_name,
                "product_code": None,
                "product_name": None,
                "latest_document_id": None,
            }

        brand = brands.get_brand_by_name(normalized_brand_name)
        if not brand:
            return {
                "is_brand_category": False,
                "brand_code": None,
                "brand_name": normalized_brand_name,
                "product_code": None,
                "product_name": None,
                "latest_document_id": None,
            }

        brand_code = str(brand.get("brand_code") or "").strip()
        if not brand_code:
            return {
                "is_brand_category": True,
                "brand_code": None,
                "brand_name": normalized_brand_name,
                "product_code": None,
                "product_name": None,
                "latest_document_id": None,
            }

        store = getattr(self._deps, "brand_full_knowledge", None)
        if store is None or not hasattr(store, "get_latest_by_brand_code"):
            return {
                "is_brand_category": True,
                "brand_code": brand_code,
                "brand_name": normalized_brand_name,
                "product_code": None,
                "product_name": None,
                "latest_document_id": None,
            }

        latest_row = store.get_latest_by_brand_code(brand_code=brand_code)
        document_id = str((latest_row or {}).get("document_id") or "").strip() or None
        return {
            "is_brand_category": True,
            "brand_code": brand_code,
            "brand_name": normalized_brand_name,
            "product_code": None,
            "product_name": None,
            "latest_document_id": document_id,
        }

    @staticmethod
    def _fact_metadata(*, entity: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        return {
            "brand_code": str(entity.get("brand_code") or context.get("brand_code") or "").strip() or None,
            "brand_name": str(entity.get("brand_name") or context.get("brand_name") or "").strip() or None,
            "product_code": None,
            "product_name": None,
        }

    def collect_document_object_keys(
        self,
        *,
        document_id: str,
        doc_info: dict[str, Any] | None,
        registry_entry: dict[str, Any] | None,
    ) -> list[str]:
        metadata = parse_metadata_json(doc_info.get("metadata_json")) if doc_info else {}
        candidate_keys: list[str] = []

        original_file_key = metadata.get("original_file_key")
        if not original_file_key and registry_entry:
            original_file_key = registry_entry.get("original_file_key")
        if original_file_key:
            candidate_keys.append(str(original_file_key))

        fulltext_key = metadata.get("fulltext_key")
        if not fulltext_key and registry_entry:
            fulltext_key = registry_entry.get("fulltext_key")
        if fulltext_key:
            candidate_keys.append(str(fulltext_key))

        oss_key = metadata.get("oss_key")
        if oss_key:
            candidate_keys.append(str(oss_key))

        legacy_fulltext_key = legacy_fulltext_object_key(document_id)
        if legacy_fulltext_key not in candidate_keys:
            candidate_keys.append(legacy_fulltext_key)

        return list(dict.fromkeys(candidate_keys))

    async def _after_ai_status_terminal(
        self,
        *,
        category: str,
        file_hash: str,
    ) -> None:
        await self._deps.notify_ai_failure_if_ready(
            category=category,
            file_hash=file_hash,
        )
        await self._deps.finalize_task_callback_from_document(
            category=category,
            file_hash=file_hash,
        )
