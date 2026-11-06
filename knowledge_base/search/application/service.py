from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from typing import Any

from knowledge_base.brand.application.brand_scope import resolve_brand_scope_from_codes
from knowledge_base.document.schemas import ImageSearchRequest, SearchRequest


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SearchApplicationDependencies:
    settings: Any
    store: Any
    embeddings: Any
    brands: Any
    brand_app: Any
    document_app: Any
    document_categories: Any
    brand_products: Any = None
    brand_full_knowledge: Any = None
    attachment_assets: Any = None


class SearchApplicationService:
    def __init__(self, dependencies: SearchApplicationDependencies) -> None:
        self._deps = dependencies
        max_concurrency = max(
            1,
            int(
                getattr(
                    dependencies.settings,
                    "vector_search_max_concurrency",
                    getattr(dependencies.settings, "milvus_search_max_concurrency", 1),
                )
                or 1
            ),
        )
        self._milvus_search_semaphore = asyncio.Semaphore(max_concurrency)

    async def search(self, request: SearchRequest) -> list[dict[str, Any]]:
        search_mode = self._classify_search_query(request.query)
        if search_mode == "structured":
            structured_hits = await asyncio.to_thread(
                self._deps.brand_app.search_structured,
                request,
            )
            return await self._supplement_structured_with_semantic(request, structured_hits)

        if search_mode == "hybrid":
            structured_hits = await asyncio.to_thread(
                self._deps.brand_app.search_structured,
                request,
            )
            return await self._supplement_structured_with_semantic(request, structured_hits)

        return await self.search_semantic(request)

    async def search_semantic(
        self,
        request: SearchRequest,
        *,
        prefer_latest_brand_document: bool = True,
    ) -> list[dict[str, Any]]:
        brand_cache: dict[str, dict[str, Any] | None] = {}
        grouped_hits, request_brand_name = await self._search_semantic_grouped_hits(
            request,
            brand_cache=brand_cache,
            prefer_latest_brand_document=prefer_latest_brand_document,
        )
        return await asyncio.to_thread(
            self._flatten_grouped_hits_to_results,
            grouped_hits,
            top_k=request.top_k,
            request_brand_name=request_brand_name,
            brand_cache=brand_cache,
        )

    async def search_images(self, request: ImageSearchRequest) -> list[dict[str, Any]]:
        request_scope = self._resolve_request_brand_scope(request)
        request_brand_name = request_scope.get("brand_name") or self._resolve_request_brand_name(request)
        request_brand_code = request_scope.get("brand_code") or str(getattr(request, "brand_code", None) or "").strip() or None

        final_document_ids = request.document_ids
        if request_brand_name:
            if request.subcategory:
                category_document_ids = await asyncio.to_thread(
                    self._deps.document_categories.get_latest_document_ids_by_category_and_subcategory,
                    request_brand_name,
                    request.subcategory,
                )
            else:
                category_document_ids = await asyncio.to_thread(
                    self._deps.document_categories.get_latest_document_ids_by_category,
                    request_brand_name,
                )
            if final_document_ids is None:
                final_document_ids = category_document_ids
            else:
                final_document_ids = list(set(final_document_ids) & set(category_document_ids))
            if not final_document_ids:
                logger.info(
                    "Image search skipped after brand/category filtering query_length=%s brand_name=%s subcategory=%s",
                    len(request.query),
                    request_brand_name,
                    request.subcategory,
                )
                return []
        else:
            final_document_ids = await asyncio.to_thread(
                self._deps.document_categories.get_searchable_document_ids,
                final_document_ids,
            )
            if not final_document_ids:
                logger.info(
                    "Image search skipped after searchable-document filtering query_length=%s",
                    len(request.query),
                )
                return []

        query_vector = await asyncio.to_thread(self._deps.embeddings.embed_query, request.query)
        results = await self._search_with_document_filter_batches(
            query_vector=query_vector,
            top_k=request.top_k,
            document_ids=final_document_ids,
            source_types=["image"],
            brand_code=request_brand_code,
            product_code=None,
        )
        grouped_hits = self._deps.document_app.build_search_hits(results)

        results: list[dict[str, Any]] = []
        attachment_assets = getattr(self._deps, "attachment_assets", None)
        asset_ids_by_document_id: dict[str, int] = {}
        for hit in grouped_hits:
            document_id = str(hit.get("document_id") or "").strip()
            if not document_id.startswith("asset_"):
                continue
            try:
                asset_ids_by_document_id[document_id] = int(document_id.split("_", 1)[1])
            except (IndexError, ValueError):
                continue
        asset_rows_by_id: dict[int, dict[str, Any]] = {}
        if attachment_assets is not None:
            if hasattr(attachment_assets, "get_by_ids"):
                asset_rows_by_id = await asyncio.to_thread(
                    attachment_assets.get_by_ids,
                    asset_ids=list(asset_ids_by_document_id.values()),
                ) or {}
            elif hasattr(attachment_assets, "get_by_id"):
                asset_rows_by_id = await asyncio.to_thread(
                    self._load_attachment_asset_rows_by_id,
                    attachment_assets,
                    list(asset_ids_by_document_id.values()),
                )
        for hit in grouped_hits:
            document_id = str(hit.get("document_id") or "").strip()
            asset_id = asset_ids_by_document_id.get(document_id)
            if asset_id is None:
                continue

            asset_row = asset_rows_by_id.get(asset_id) or {}
            raw_metadata = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
            score: float | None = None
            if isinstance(hit.get("chunks"), list) and hit["chunks"]:
                score = max(
                    float(chunk.get("score", 0.0))
                    for chunk in hit["chunks"]
                    if chunk.get("score") is not None
                )
            item = {
                "asset_id": asset_id,
                "document_id": document_id,
                "score": score,
                "brand_code": str(asset_row.get("brand_code") or raw_metadata.get("brand_code") or "").strip() or None,
                "brand_name": str(
                    asset_row.get("brand_name")
                    or raw_metadata.get("brand_name")
                    or raw_metadata.get("category")
                    or request_brand_name
                    or ""
                ).strip()
                or None,
                "subcategory": str(raw_metadata.get("subcategory") or "").strip() or None,
                "original_filename": str(
                    asset_row.get("original_filename")
                    or raw_metadata.get("original_filename")
                    or hit.get("source_name")
                    or ""
                ).strip()
                or None,
                "oss_url": str(asset_row.get("oss_url") or hit.get("file_url") or "").strip() or None,
                "source_url": str(asset_row.get("source_url") or raw_metadata.get("source_url") or "").strip() or None,
                "content_type": str(asset_row.get("content_type") or "").strip() or None,
                "file_size": int(asset_row.get("file_size")) if asset_row.get("file_size") is not None else None,
                "image_summary": str(
                    asset_row.get("image_summary")
                    or raw_metadata.get("image_summary")
                    or ""
                ).strip()
                or None,
                "image_tags": list(asset_row.get("image_tags") or raw_metadata.get("image_tags") or []),
            }
            product_code = str(asset_row.get("product_code") or raw_metadata.get("product_code") or "").strip()
            product_name = str(asset_row.get("product_name") or raw_metadata.get("product_name") or "").strip()
            if product_code:
                item["product_code"] = product_code
            if product_name:
                item["product_name"] = product_name
            results.append(item)
        return results

    async def _search_semantic_grouped_hits(
        self,
        request: SearchRequest,
        *,
        brand_cache: dict[str, dict[str, Any] | None] | None = None,
        prefer_latest_brand_document: bool = True,
    ) -> tuple[list[dict[str, Any]], str | None]:
        final_doc_ids = request.document_ids
        request_scope = self._resolve_request_brand_scope(request)
        request_brand_name = request_scope.get("brand_name") or self._resolve_request_brand_name(request)
        request_brand_code = request_scope.get("brand_code") or str(getattr(request, "brand_code", None) or "").strip() or None

        if request_brand_name:
            if request.subcategory:
                cat_doc_ids = await asyncio.to_thread(
                    self._deps.document_categories.get_latest_document_ids_by_category_and_subcategory,
                    request_brand_name,
                    request.subcategory,
                )
            elif prefer_latest_brand_document:
                is_brand_category, latest_brand_document_ids = await asyncio.to_thread(
                    self._resolve_latest_brand_document_ids,
                    request_brand_name,
                    brand_cache=brand_cache,
                )
                if is_brand_category:
                    cat_doc_ids = latest_brand_document_ids
                else:
                    cat_doc_ids = await asyncio.to_thread(
                        self._deps.document_categories.get_latest_document_ids_by_category,
                        request_brand_name,
                    )
            else:
                cat_doc_ids = await asyncio.to_thread(
                    self._deps.document_categories.get_latest_document_ids_by_category,
                    request_brand_name,
                )
            if final_doc_ids is None:
                final_doc_ids = cat_doc_ids
            else:
                final_doc_ids = list(set(final_doc_ids) & set(cat_doc_ids))
            if not final_doc_ids:
                logger.info(
                    "Search skipped after brand/category filtering query_length=%s brand_name=%s subcategory=%s",
                    len(request.query),
                    request_brand_name,
                    request.subcategory,
                )
                return [], request_brand_name
        else:
            final_doc_ids = await asyncio.to_thread(
                self._deps.document_categories.get_searchable_document_ids,
                final_doc_ids,
            )
            if not final_doc_ids:
                logger.info(
                    "Search skipped after latest-version filtering query_length=%s",
                    len(request.query),
                )
                return [], request_brand_name

        query_vector = await asyncio.to_thread(self._deps.embeddings.embed_query, request.query)
        results = await self._search_with_document_filter_batches(
            query_vector=query_vector,
            top_k=request.top_k,
            document_ids=final_doc_ids,
            source_types=request.source_types,
            brand_code=request_brand_code,
            product_code=None,
        )

        grouped_hits = self._deps.document_app.build_search_hits(results)
        return grouped_hits, request_brand_name

    @staticmethod
    def _classify_search_query(query: str) -> str:
        normalized_query = (query or "").strip()
        if not normalized_query:
            return "semantic"

        structured_keywords = (
            "品牌名称",
            "品牌名",
            "企业主体",
            "营业执照",
            "主体名称",
            "所属行业",
            "英文名",
            "品牌定位",
            "品牌优势",
            "核心优势",
            "品牌力",
            "品牌使命",
            "品牌愿景",
            "公司档案",
            "管理团队",
            "价格",
            "覆盖区域",
            "覆盖地域",
            "覆盖城市",
            "服务标准",
            "服务流程",
            "产品信息",
            "产品介绍",
            "主要产品",
            "主要服务",
            "产品矩阵",
            "核心品类",
            "主营品类",
            "官网",
            "官网链接",
            "官网地址",
            "网址",
            "目标用户",
            "目标客户",
            "用户群体",
            "适用人群",
            "应用场景",
            "使用场景",
            "核心场景",
            "资质",
            "认证",
            "证书",
            "里程碑",
            "发展历程",
            "常见问题",
            "常见用户质疑",
            "用户质疑",
            "用户疑虑",
            "敏感话题",
            "相关附件",
            "官方商城",
            "商城",
            "旗舰店",
            "媒体矩阵",
            "官方媒体",
            "账号矩阵",
            "公众号",
        )
        hybrid_keywords = (
            "对比",
            "差异",
            "风险",
            "争议",
            "荣誉",
            "背书",
            "案例",
            "合作客户",
            "竞品",
            "口碑",
            "投诉",
            "质疑",
            "为什么选择",
            "为什么不用",
        )

        if any(keyword in normalized_query for keyword in hybrid_keywords):
            return "hybrid"
        if any(keyword in normalized_query for keyword in structured_keywords):
            return "structured"
        return "semantic"

    async def _supplement_structured_with_semantic(
        self,
        request: SearchRequest,
        structured_hits: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        semantic_request = request.model_copy(update={"top_k": request.top_k})
        semantic_hits = await self.search_semantic(semantic_request)
        request_brand_name = self._resolve_request_brand_name(request)
        if (
            len(semantic_hits) < request.top_k
            and request_brand_name
            and not request.subcategory
        ):
            fallback_semantic_hits = await self.search_semantic(
                semantic_request,
                prefer_latest_brand_document=False,
            )
            semantic_hits = self._merge_search_hits(
                semantic_hits,
                fallback_semantic_hits,
                top_k=request.top_k,
            )

        if not structured_hits:
            return semantic_hits[: request.top_k]
        if not semantic_hits:
            return structured_hits[: request.top_k]
        return self._merge_search_hits(structured_hits, semantic_hits, top_k=request.top_k)

    @staticmethod
    def _count_hit_chunks(hits: list[dict[str, Any]]) -> int:
        return len(hits)

    def _flatten_grouped_hits_to_results(
        self,
        grouped_hits: list[dict[str, Any]],
        *,
        top_k: int,
        request_brand_name: str | None,
        brand_cache: dict[str, dict[str, Any] | None] | None = None,
    ) -> list[dict[str, Any]]:
        flattened: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        for hit in grouped_hits:
            raw_metadata = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
            source_name = str(hit.get("source_name") or "").strip() or None
            file_url = str(hit.get("file_url") or "").strip() or None
            brand_name = str(raw_metadata.get("brand_name") or raw_metadata.get("category") or request_brand_name or "").strip() or None
            for chunk in hit.get("chunks", []):
                content = str(chunk.get("text") or "").strip()
                if not content:
                    continue
                chunk_id = str(chunk.get("chunk_id") or "").strip() or None
                dedupe_key = chunk_id or content
                if dedupe_key in seen_keys:
                    continue
                seen_keys.add(dedupe_key)
                score = float(chunk.get("score", 0.0)) if chunk.get("score") is not None else None
                flattened.append(
                    {
                        "chunk_id": chunk_id,
                        "content": content,
                        "score": score,
                        "brand_name": brand_name,
                        "category": brand_name,
                        "metadata": self._build_result_metadata(
                            brand_name=brand_name,
                            raw_metadata=raw_metadata,
                            content=content,
                            source_url=file_url,
                            section_title=str(raw_metadata.get("section_title") or source_name or "").strip() or None,
                            brand_cache=brand_cache,
                        ),
                    }
                )

        flattened.sort(
            key=lambda item: (
                float(item["score"]) if item.get("score") is not None else float("-inf"),
                len(str(item.get("content") or "")),
            ),
            reverse=True,
        )
        return flattened[:top_k]

    @staticmethod
    def _merge_search_hits(
        structured_hits: list[dict[str, Any]],
        semantic_hits: list[dict[str, Any]],
        *,
        top_k: int,
    ) -> list[dict[str, Any]]:
        if not structured_hits:
            return semantic_hits[:top_k]
        if not semantic_hits:
            return structured_hits[:top_k]

        merged: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        for hit in [*structured_hits, *semantic_hits]:
            dedupe_key = SearchApplicationService._build_hit_dedupe_key(hit)
            if dedupe_key and dedupe_key in seen_keys:
                continue
            if dedupe_key:
                seen_keys.add(dedupe_key)
            merged.append(hit)
            if len(merged) >= top_k:
                break
        return merged[:top_k]

    @staticmethod
    def _build_hit_dedupe_key(hit: dict[str, Any]) -> str:
        chunk_id = str(hit.get("chunk_id") or "").strip()
        if chunk_id:
            return chunk_id

        content = str(hit.get("content") or hit.get("text") or "").strip()
        if content:
            return content

        document_id = str(hit.get("document_id") or "").strip()
        if document_id:
            return document_id

        source_name = str(hit.get("source_name") or "").strip()
        if source_name:
            return source_name

        metadata = hit.get("metadata")
        if isinstance(metadata, dict):
            section_title = str(metadata.get("section_title") or "").strip()
            if section_title:
                return section_title
        return ""

    def _build_result_metadata(
        self,
        *,
        brand_name: str | None,
        raw_metadata: dict[str, Any],
        content: str,
        source_url: str | None,
        section_title: str | None,
        brand_cache: dict[str, dict[str, Any] | None] | None = None,
    ) -> dict[str, Any]:
        resolved_brand_name = str(raw_metadata.get("brand_name") or raw_metadata.get("category") or brand_name or "").strip() or None
        brand = self._resolve_brand(resolved_brand_name, brand_cache=brand_cache)

        brand_id = raw_metadata.get("brand_id")
        if brand_id in {"", None} and brand and brand.get("id") is not None:
            brand_id = brand.get("id")

        brand_code = str(raw_metadata.get("brand_code") or "").strip() or None
        if brand_code is None and brand and brand.get("brand_code") is not None:
            brand_code = str(brand.get("brand_code") or "").strip() or None

        kb_version = (
            str(raw_metadata.get("kb_version") or "").strip()
            or str(raw_metadata.get("knowledge_revision") or "").strip()
            or str(raw_metadata.get("knowledge_version") or "").strip()
            or str((brand or {}).get("knowledge_revision") or "").strip()
            or None
        )

        resolved_source_url = (
            source_url
            or str(raw_metadata.get("source_url") or "").strip()
            or None
        )

        content_hash = (
            str(raw_metadata.get("content_hash") or "").strip()
            or f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}"
        )

        metadata = {
            "brand_id": brand_id,
            "brand_code": brand_code,
            "brand_name": resolved_brand_name or str((brand or {}).get("brand_name") or "").strip() or None,
            "kb_version": kb_version,
            "section_title": section_title,
            "source_url": resolved_source_url,
            "content_hash": content_hash,
        }
        product_code = str(raw_metadata.get("product_code") or "").strip()
        product_name = str(raw_metadata.get("product_name") or "").strip()
        if product_code:
            metadata["product_code"] = product_code
        if product_name:
            metadata["product_name"] = product_name
        return metadata

    @staticmethod
    def _resolve_request_brand_name(request: SearchRequest) -> str | None:
        return str(getattr(request, "brand_name", None) or getattr(request, "category", None) or "").strip() or None

    def _resolve_request_brand_scope(self, request: SearchRequest | ImageSearchRequest) -> dict[str, Any]:
        scope = resolve_brand_scope_from_codes(
            self._deps,
            brand_code=getattr(request, "brand_code", None),
            brand_name=getattr(request, "brand_name", None),
            category=getattr(request, "category", None),
            product_code=getattr(request, "product_code", None),
        )
        return {
            "brand_code": scope.brand_code,
            "brand_name": scope.brand_name,
            "product_code": scope.product_code,
            "product_name": scope.product_name,
        }

    def _resolve_brand(
        self,
        brand_name: str | None,
        *,
        brand_cache: dict[str, dict[str, Any] | None] | None = None,
    ) -> dict[str, Any] | None:
        normalized_brand_name = (brand_name or "").strip()
        if not normalized_brand_name:
            return None
        if brand_cache is not None:
            cache_key = normalized_brand_name.casefold()
            if cache_key in brand_cache:
                return brand_cache[cache_key]
            brand = self._deps.brands.get_brand_by_name(normalized_brand_name)
            brand_cache[cache_key] = brand
            return brand
        return self._deps.brands.get_brand_by_name(normalized_brand_name)

    @staticmethod
    def _load_attachment_asset_rows_by_id(
        attachment_assets: Any,
        asset_ids: list[int],
    ) -> dict[int, dict[str, Any]]:
        return {
            asset_id: row
            for asset_id in asset_ids
            for row in [attachment_assets.get_by_id(asset_id=asset_id)]
            if row is not None
        }

    def _resolve_latest_brand_document_ids(
        self,
        category: str | None,
        *,
        brand_cache: dict[str, dict[str, Any] | None] | None = None,
    ) -> tuple[bool, list[str]]:
        brand = self._resolve_brand(category, brand_cache=brand_cache)
        if not brand:
            return False, []

        brand_code = str(brand.get("brand_code") or "").strip()
        if not brand_code:
            return True, []

        store = getattr(self._deps, "brand_full_knowledge", None)
        if store is None or not hasattr(store, "get_latest_by_brand_code"):
            return True, []

        latest_row = store.get_latest_by_brand_code(brand_code=brand_code)
        document_id = str((latest_row or {}).get("document_id") or "").strip()
        if not document_id:
            return True, []
        return True, [document_id]

    async def _search_with_document_filter_batches(
        self,
        *,
        query_vector: list[float],
        top_k: int,
        document_ids: list[str] | None,
        source_types: list[str] | None,
        brand_code: str | None = None,
        product_code: str | None = None,
    ) -> list[dict[str, Any]]:
        if not document_ids:
            return await self._search_store(
                query_vector=query_vector,
                top_k=top_k,
                document_ids=None,
                source_types=source_types,
                brand_code=brand_code,
                product_code=product_code,
            )

        batch_size = max(1, self._deps.settings.milvus_filter_batch_size)
        if len(document_ids) <= batch_size:
            return await self._search_store(
                query_vector=query_vector,
                top_k=top_k,
                document_ids=document_ids,
                source_types=source_types,
                brand_code=brand_code,
                product_code=product_code,
            )

        logger.info(
            "Search document filter split into batches document_count=%s batch_size=%s",
            len(document_ids),
            batch_size,
        )
        batched_results = await asyncio.gather(
            *[
                self._search_store(
                    query_vector=query_vector,
                    top_k=top_k,
                    document_ids=document_ids[index:index + batch_size],
                    source_types=source_types,
                    brand_code=brand_code,
                    product_code=product_code,
                )
                for index in range(0, len(document_ids), batch_size)
            ]
        )
        merged_results = [item for batch in batched_results for item in batch]
        merged_results.sort(key=lambda item: float(item.get("distance", 0.0)), reverse=True)
        return merged_results[:top_k]

    async def _search_store(
        self,
        *,
        query_vector: list[float],
        top_k: int,
        document_ids: list[str] | None,
        source_types: list[str] | None,
        brand_code: str | None = None,
        product_code: str | None = None,
    ) -> list[dict[str, Any]]:
        async with self._milvus_search_semaphore:
            return await asyncio.to_thread(
                self._deps.store.search,
                query_vector=query_vector,
                top_k=top_k,
                document_ids=document_ids,
                source_types=source_types,
                brand_code=brand_code,
                product_code=product_code,
            )
