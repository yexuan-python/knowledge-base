from __future__ import annotations

import asyncio
import types
import unittest
from typing import Any

from knowledge_base.search.facade import KnowledgeSearchFacade, KnowledgeSearchFacadeDependencies
from knowledge_base.service import KnowledgeBaseService


class _FakeSearchApplication:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.flatten_request_brand_name: str | None = None

    async def search(self, request: Any) -> list[dict[str, Any]]:
        self.calls.append(("search", request))
        return [{"source": "search"}]

    async def search_semantic(self, request: Any) -> list[dict[str, Any]]:
        self.calls.append(("search_semantic", request))
        return [{"source": "semantic"}]

    async def search_images(self, request: Any) -> list[dict[str, Any]]:
        self.calls.append(("search_images", request))
        return [{"source": "images"}]

    async def _supplement_structured_with_semantic(
        self,
        request: Any,
        structured_hits: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        self.calls.append(("supplement", (request, structured_hits)))
        return [*structured_hits, {"source": "semantic"}]

    def _flatten_grouped_hits_to_results(
        self,
        grouped_hits: list[dict[str, Any]],
        *,
        top_k: int,
        request_brand_name: str | None,
    ) -> list[dict[str, Any]]:
        self.calls.append(("flatten", (grouped_hits, top_k)))
        self.flatten_request_brand_name = request_brand_name
        return [{"brand": request_brand_name, "top_k": top_k}]

    async def _search_with_document_filter_batches(
        self,
        *,
        query_vector: list[float],
        top_k: int,
        document_ids: list[str] | None,
        source_types: list[str] | None,
    ) -> list[dict[str, Any]]:
        self.calls.append(("batched", (query_vector, top_k, document_ids, source_types)))
        return [{"source": "batched"}]


class _FakeDocumentApplication:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    async def search_facts_by_brand_name(
        self,
        brand_name: str,
        query: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        self.calls.append(("brand", (brand_name, query, top_k)))
        return [{"scope": brand_name}]

    async def search_facts(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("facts", kwargs))
        return [{"query": kwargs["query"]}]

    async def search_facts_by_category(
        self,
        category: str,
        query: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        self.calls.append(("category", (category, query, top_k)))
        return [{"scope": category}]

    async def search_facts_by_brand_name_matched(
        self,
        brand_name: str,
        query: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        self.calls.append(("brand_matched", (brand_name, query, top_k)))
        return [{"matched": brand_name}]

    async def search_facts_by_category_matched(
        self,
        category: str,
        query: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        self.calls.append(("category_matched", (category, query, top_k)))
        return [{"matched": category}]


class KnowledgeSearchFacadeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.search_app = _FakeSearchApplication()
        self.document_app = _FakeDocumentApplication()
        self.facade = KnowledgeSearchFacade(
            KnowledgeSearchFacadeDependencies(
                search_application=lambda: self.search_app,
                document_application=lambda: self.document_app,
            )
        )

    def test_delegates_search_entrypoints(self) -> None:
        request = types.SimpleNamespace(query="官网", top_k=3)

        self.assertEqual(asyncio.run(self.facade.search(request)), [{"source": "search"}])
        self.assertEqual(asyncio.run(self.facade.search_semantic(request)), [{"source": "semantic"}])
        self.assertEqual(asyncio.run(self.facade.search_images(request)), [{"source": "images"}])

        self.assertEqual(
            self.search_app.calls[:3],
            [
                ("search", request),
                ("search_semantic", request),
                ("search_images", request),
            ],
        )

    def test_maps_legacy_request_category_to_request_brand_name(self) -> None:
        result = self.facade.flatten_grouped_hits_to_results(
            [{"document_id": "doc-1"}],
            top_k=2,
            request_category="示例品牌",
        )

        self.assertEqual(result, [{"brand": "示例品牌", "top_k": 2}])
        self.assertEqual(self.search_app.flatten_request_brand_name, "示例品牌")

    def test_delegates_fact_search_entrypoints(self) -> None:
        self.assertEqual(
            asyncio.run(self.facade.search_facts_by_category("品牌资料", "官网", 5)),
            [{"scope": "品牌资料"}],
        )
        self.assertEqual(
            asyncio.run(self.facade.search_facts_by_category_matched("品牌资料", "官网", 5)),
            [{"matched": "品牌资料"}],
        )

        self.assertEqual(
            self.document_app.calls,
            [
                ("category", ("品牌资料", "官网", 5)),
                ("category_matched", ("品牌资料", "官网", 5)),
            ],
        )

    def test_service_keeps_legacy_search_proxy_methods(self) -> None:
        service = KnowledgeBaseService.__new__(KnowledgeBaseService)
        service._search_app = self.search_app
        service._document_app = self.document_app

        self.assertEqual(
            service._flatten_grouped_hits_to_results(
                [{"document_id": "doc-1"}],
                top_k=1,
                request_category="示例品牌",
            ),
            [{"brand": "示例品牌", "top_k": 1}],
        )
        self.assertEqual(
            asyncio.run(service.search_facts_by_category("品牌资料", "官网", 5)),
            [{"scope": "品牌资料"}],
        )

        self.assertEqual(self.search_app.flatten_request_brand_name, "示例品牌")
