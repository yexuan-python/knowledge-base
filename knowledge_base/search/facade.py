from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from knowledge_base.document.schemas import ImageSearchRequest, SearchRequest
from knowledge_base.search.application import SearchApplicationService


@dataclass(frozen=True)
class KnowledgeSearchFacadeDependencies:
    search_application: Callable[[], Any]
    document_application: Callable[[], Any]


class KnowledgeSearchFacade:
    """Compatibility facade for knowledge search and fact lookup entrypoints."""

    def __init__(self, dependencies: KnowledgeSearchFacadeDependencies) -> None:
        self._deps = dependencies

    def _search_application(self) -> Any:
        return self._deps.search_application()

    def _document_application(self) -> Any:
        return self._deps.document_application()

    async def search(self, request: SearchRequest) -> list[dict[str, Any]]:
        return await self._search_application().search(request)

    async def search_semantic(self, request: SearchRequest) -> list[dict[str, Any]]:
        return await self._search_application().search_semantic(request)

    async def search_images(self, request: ImageSearchRequest) -> list[dict[str, Any]]:
        return await self._search_application().search_images(request)

    @staticmethod
    def classify_search_query(query: str) -> str:
        return SearchApplicationService._classify_search_query(query)

    async def supplement_structured_with_semantic(
        self,
        request: SearchRequest,
        structured_hits: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return await self._search_application()._supplement_structured_with_semantic(request, structured_hits)

    @staticmethod
    def count_hit_chunks(hits: list[dict[str, Any]]) -> int:
        return SearchApplicationService._count_hit_chunks(hits)

    def flatten_grouped_hits_to_results(
        self,
        grouped_hits: list[dict[str, Any]],
        *,
        top_k: int,
        request_category: str | None = None,
    ) -> list[dict[str, Any]]:
        return self._search_application()._flatten_grouped_hits_to_results(
            grouped_hits,
            top_k=top_k,
            request_brand_name=request_category,
        )

    @staticmethod
    def merge_search_hits(
        structured_hits: list[dict[str, Any]],
        semantic_hits: list[dict[str, Any]],
        *,
        top_k: int,
    ) -> list[dict[str, Any]]:
        return SearchApplicationService._merge_search_hits(
            structured_hits,
            semantic_hits,
            top_k=top_k,
        )

    async def search_with_document_filter_batches(
        self,
        *,
        query_vector: list[float],
        top_k: int,
        document_ids: list[str] | None,
        source_types: list[str] | None,
    ) -> list[dict[str, Any]]:
        return await self._search_application()._search_with_document_filter_batches(
            query_vector=query_vector,
            top_k=top_k,
            document_ids=document_ids,
            source_types=source_types,
        )

    async def search_facts_by_brand_name(
        self,
        brand_name: str,
        query: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        return await self._document_application().search_facts_by_brand_name(brand_name, query, top_k)

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
        return await self._document_application().search_facts(
            brand_code=brand_code,
            brand_name=brand_name,
            category=category,
            product_code=product_code,
            query=query,
            top_k=top_k,
        )

    async def search_facts_by_category(
        self,
        category: str,
        query: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        return await self._document_application().search_facts_by_category(category, query, top_k)

    async def search_facts_by_brand_name_matched(
        self,
        brand_name: str,
        query: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        return await self._document_application().search_facts_by_brand_name_matched(brand_name, query, top_k)

    async def search_facts_by_category_matched(
        self,
        category: str,
        query: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        return await self._document_application().search_facts_by_category_matched(category, query, top_k)
