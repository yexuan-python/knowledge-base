from __future__ import annotations

import asyncio
import threading
import time
import types
import unittest
from typing import Any

from knowledge_base.search.application.service import (
    SearchApplicationDependencies,
    SearchApplicationService,
)


class _FakeBrandStore:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_brand_by_name(self, brand_name: str) -> dict | None:
        self.calls.append(brand_name)
        if brand_name != "炜衡密云分所":
            return None
        return {
            "id": 100003,
            "brand_code": "WHMY",
            "brand_name": "炜衡密云分所",
            "knowledge_revision": "LXKG-WHMY-V1.0.0-20260629000000",
        }

    def get_brand_by_code(self, brand_code: str) -> dict | None:
        if brand_code != "WHMY":
            return None
        return {
            "id": 100003,
            "brand_code": "WHMY",
            "brand_name": "炜衡密云分所",
            "knowledge_revision": "LXKG-WHMY-V1.0.0-20260629000000",
        }

    def get_brand_by_id(self, brand_id: int) -> dict | None:
        if brand_id != 100003:
            return None
        return {
            "id": 100003,
            "brand_code": "WHMY",
            "brand_name": "炜衡密云分所",
            "knowledge_revision": "LXKG-WHMY-V1.0.0-20260629000000",
        }


class _FakeBrandFullKnowledgeStore:
    def __init__(self, latest_document_id: str | None = "kb-latest") -> None:
        self.latest_document_id = latest_document_id
        self.calls: list[str] = []

    def get_latest_by_brand_code(self, *, brand_code: str) -> dict | None:
        self.calls.append(brand_code)
        if not self.latest_document_id:
            return None
        return {"document_id": self.latest_document_id}


class _FakeDocumentCategories:
    def __init__(self) -> None:
        self.category_calls: list[str] = []
        self.subcategory_calls: list[tuple[str, str]] = []
        self.searchable_calls: list[list[str] | None] = []

    def get_latest_document_ids_by_category(self, category: str) -> list[str]:
        self.category_calls.append(category)
        return ["legacy-doc"]

    def get_latest_document_ids_by_category_and_subcategory(self, category: str, subcategory: str) -> list[str]:
        self.subcategory_calls.append((category, subcategory))
        return ["legacy-doc-sub"]

    def get_searchable_document_ids(self, document_ids: list[str] | None) -> list[str]:
        self.searchable_calls.append(document_ids)
        return document_ids or ["legacy-searchable"]


class _FakeEmbeddings:
    def embed_query(self, _query: str) -> list[float]:
        return [0.1, 0.2]


class _FakeStore:
    def __init__(self, grouped_hits: list[dict] | None = None) -> None:
        self.grouped_hits = grouped_hits or []
        self.calls: list[dict[str, object]] = []

    def search(
        self,
        *,
        query_vector: list[float],
        top_k: int,
        document_ids: list[str] | None = None,
        source_types: list[str] | None = None,
        brand_code: str | None = None,
        product_code: str | None = None,
    ) -> list[dict]:
        self.calls.append(
            {
                "query_vector": query_vector,
                "top_k": top_k,
                "document_ids": list(document_ids) if document_ids is not None else None,
                "source_types": source_types,
                "brand_code": brand_code,
                "product_code": product_code,
            }
        )
        return self.grouped_hits


class _ConcurrencyTrackingStore:
    def __init__(self, delay_seconds: float = 0.02) -> None:
        self.delay_seconds = delay_seconds
        self.calls: list[list[str] | None] = []
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def search(
        self,
        *,
        query_vector: list[float],
        top_k: int,
        document_ids: list[str] | None = None,
        source_types: list[str] | None = None,
        brand_code: str | None = None,
        product_code: str | None = None,
    ) -> list[dict]:
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.calls.append(list(document_ids) if document_ids is not None else None)
        try:
            time.sleep(self.delay_seconds)
            return [
                {
                    "id": f"hit-{document_ids[0] if document_ids else 'all'}",
                    "distance": 0.5,
                }
            ]
        finally:
            with self._lock:
                self.active -= 1


class _FakeDocumentApp:
    def build_search_hits(self, results: list[dict]) -> list[dict]:
        return results


class _FakeAttachmentAssetStore:
    def __init__(self, rows_by_id: dict[int, dict] | None = None) -> None:
        self.rows_by_id = rows_by_id or {}
        self.get_by_id_calls: list[int] = []
        self.get_by_ids_calls: list[list[int]] = []

    def get_by_id(self, *, asset_id: int) -> dict | None:
        self.get_by_id_calls.append(asset_id)
        return self.rows_by_id.get(asset_id)

    def get_by_ids(self, *, asset_ids: list[int]) -> dict[int, dict]:
        self.get_by_ids_calls.append(list(asset_ids))
        return {
            asset_id: row
            for asset_id, row in self.rows_by_id.items()
            if asset_id in asset_ids
        }


class _FakeBrandApp:
    def __init__(self, structured_hits: list[dict] | None = None) -> None:
        self.structured_hits = structured_hits or []
        self.calls: list[dict[str, Any]] = []

    def search_structured(self, request) -> list[dict]:
        self.calls.append(
            {
                "query": getattr(request, "query", None),
                "top_k": getattr(request, "top_k", None),
                "brand_name": getattr(request, "brand_name", None),
                "category": getattr(request, "category", None),
                "subcategory": getattr(request, "subcategory", None),
            }
        )
        return list(self.structured_hits)


class _FakeBrandProductStore:
    def get_by_product_code(self, *, product_code: str) -> dict | None:
        if product_code != "PROD-WHMY":
            return None
        return {
            "brand_id": 100003,
            "brand_code": "WHMY",
            "brand_name": "炜衡密云分所",
            "product_code": "PROD-WHMY",
            "product_name": "法律顾问产品",
        }


class SearchApplicationServiceTests(unittest.TestCase):
    def _build_service(
        self,
        *,
        store: _FakeStore | None = None,
        brands: _FakeBrandStore | None = None,
        document_categories: _FakeDocumentCategories | None = None,
        brand_full_knowledge: _FakeBrandFullKnowledgeStore | None = None,
        attachment_assets: _FakeAttachmentAssetStore | None = None,
        brand_app: _FakeBrandApp | None = None,
        brand_products: _FakeBrandProductStore | None = None,
        settings: types.SimpleNamespace | None = None,
    ) -> SearchApplicationService:
        return SearchApplicationService(
            SearchApplicationDependencies(
                settings=settings or types.SimpleNamespace(milvus_filter_batch_size=200),
                store=store or _FakeStore(),
                embeddings=_FakeEmbeddings(),
                brands=brands or _FakeBrandStore(),
                brand_app=brand_app or _FakeBrandApp(),
                document_app=_FakeDocumentApp(),
                document_categories=document_categories or _FakeDocumentCategories(),
                brand_products=brand_products or _FakeBrandProductStore(),
                brand_full_knowledge=brand_full_knowledge,
                attachment_assets=attachment_assets,
            )
        )

    def test_flatten_grouped_hits_preserves_chunk_metadata(self) -> None:
        brands = _FakeBrandStore()
        service = self._build_service(brands=brands)

        grouped_hits = [
            {
                "document_id": "doc-1",
                "source_name": "4.1 企业法律顾问服务",
                "source_type": "text",
                "metadata": {
                    "category": "炜衡密云分所",
                    "source_url": "https://example.com/original.md",
                },
                "file_url": "https://example.com/brand-kb/100003/20260629.md",
                "chunks": [
                    {
                        "chunk_id": "100003_20260629_041_001",
                        "score": 0.88,
                        "text": "炜衡密云分所提供企业常年法律顾问、合同审查服务。",
                    }
                ],
            }
        ]

        result = service._flatten_grouped_hits_to_results(
            grouped_hits,
            top_k=5,
            request_brand_name="炜衡密云分所",
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(
            result[0],
            {
                "chunk_id": "100003_20260629_041_001",
                "content": "炜衡密云分所提供企业常年法律顾问、合同审查服务。",
                "score": 0.88,
                "brand_name": "炜衡密云分所",
                "category": "炜衡密云分所",
                "metadata": {
                    "brand_id": 100003,
                    "brand_code": "WHMY",
                    "brand_name": "炜衡密云分所",
                    "kb_version": "LXKG-WHMY-V1.0.0-20260629000000",
                    "section_title": "4.1 企业法律顾问服务",
                    "source_url": "https://example.com/brand-kb/100003/20260629.md",
                    "content_hash": result[0]["metadata"]["content_hash"],
                },
            },
        )
        self.assertTrue(str(result[0]["metadata"]["content_hash"]).startswith("sha256:"))
        self.assertEqual(brands.calls, ["炜衡密云分所"])

    def test_flatten_grouped_hits_reuses_brand_lookup_with_request_scope_cache(self) -> None:
        brands = _FakeBrandStore()
        service = self._build_service(brands=brands)

        grouped_hits = [
            {
                "document_id": "doc-1",
                "source_name": "章节A",
                "source_type": "text",
                "metadata": {"category": "炜衡密云分所"},
                "file_url": "https://example.com/a.md",
                "chunks": [
                    {"chunk_id": "chunk-1", "score": 0.91, "text": "第一段"},
                    {"chunk_id": "chunk-2", "score": 0.89, "text": "第二段"},
                ],
            },
            {
                "document_id": "doc-2",
                "source_name": "章节B",
                "source_type": "text",
                "metadata": {"category": "炜衡密云分所"},
                "file_url": "https://example.com/b.md",
                "chunks": [
                    {"chunk_id": "chunk-3", "score": 0.87, "text": "第三段"},
                ],
            },
        ]

        result = service._flatten_grouped_hits_to_results(
            grouped_hits,
            top_k=10,
            request_brand_name="炜衡密云分所",
            brand_cache={},
        )

        self.assertEqual(len(result), 3)
        self.assertEqual(brands.calls, ["炜衡密云分所"])

    def test_search_semantic_brand_category_uses_latest_official_document(self) -> None:
        grouped_hits = [
            {
                "document_id": "kb-latest",
                "source_name": "品牌知识库",
                "metadata": {"category": "炜衡密云分所"},
                "file_url": "https://example.com/latest.md",
                "chunks": [{"chunk_id": "chunk-1", "score": 0.91, "text": "最新正式知识库内容"}],
            }
        ]
        store = _FakeStore(grouped_hits=grouped_hits)
        categories = _FakeDocumentCategories()
        brand_full_knowledge = _FakeBrandFullKnowledgeStore(latest_document_id="kb-latest")
        service = self._build_service(
            store=store,
            document_categories=categories,
            brand_full_knowledge=brand_full_knowledge,
        )

        result = asyncio.run(
            service.search_semantic(
                types.SimpleNamespace(
                    query="企业法律顾问",
                    top_k=5,
                    document_ids=None,
                    source_types=None,
                    category="炜衡密云分所",
                    subcategory=None,
                )
            )
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(store.calls[0]["document_ids"], ["kb-latest"])
        self.assertEqual(categories.category_calls, [])
        self.assertEqual(brand_full_knowledge.calls, ["WHMY"])

    def test_search_semantic_brand_category_without_latest_official_document_returns_empty(self) -> None:
        store = _FakeStore()
        categories = _FakeDocumentCategories()
        service = self._build_service(
            store=store,
            document_categories=categories,
            brand_full_knowledge=_FakeBrandFullKnowledgeStore(latest_document_id=None),
        )

        result = asyncio.run(
            service.search_semantic(
                types.SimpleNamespace(
                    query="企业法律顾问",
                    top_k=5,
                    document_ids=None,
                    source_types=None,
                    category="炜衡密云分所",
                    subcategory=None,
                )
            )
        )

        self.assertEqual(result, [])
        self.assertEqual(store.calls, [])
        self.assertEqual(categories.category_calls, [])

    def test_search_semantic_product_code_resolves_brand_without_product_filter(self) -> None:
        grouped_hits = [
            {
                "document_id": "kb-latest",
                "source_name": "品牌知识库",
                "metadata": {"category": "炜衡密云分所"},
                "chunks": [{"chunk_id": "chunk-1", "score": 0.91, "text": "品牌级知识"}],
            }
        ]
        store = _FakeStore(grouped_hits=grouped_hits)
        service = self._build_service(
            store=store,
            brand_full_knowledge=_FakeBrandFullKnowledgeStore(latest_document_id="kb-latest"),
        )

        result = asyncio.run(
            service.search_semantic(
                types.SimpleNamespace(
                    query="企业法律顾问",
                    top_k=5,
                    document_ids=None,
                    source_types=None,
                    brand_code=None,
                    brand_name=None,
                    category=None,
                    product_code="PROD-WHMY",
                    subcategory=None,
                )
            )
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(store.calls[0]["document_ids"], ["kb-latest"])
        self.assertEqual(store.calls[0]["brand_code"], "WHMY")
        self.assertIsNone(store.calls[0]["product_code"])

    def test_search_images_returns_asset_friendly_results(self) -> None:
        grouped_hits = [
            {
                "document_id": "asset_21",
                "source_name": "厨房场景图.png",
                "source_type": "image",
                "metadata": {
                    "category": "示例品牌",
                    "brand_code": "BRAND-001",
                    "brand_name": "示例品牌",
                    "subcategory": "橱柜",
                    "image_summary": "现代厨房橱柜场景图",
                    "image_tags": ["厨房", "橱柜"],
                    "source_url": "https://example.com/kitchen.png",
                },
                "file_url": "https://oss.example.com/brand/image.png",
                "chunks": [
                    {
                        "chunk_id": "asset_21:0",
                        "score": 0.93,
                        "text": "[Image] 厨房场景图.png",
                    }
                ],
            }
        ]
        store = _FakeStore(grouped_hits=grouped_hits)
        attachment_assets = _FakeAttachmentAssetStore(
            rows_by_id={
                21: {
                    "id": 21,
                    "brand_code": "BRAND-001",
                    "brand_name": "示例品牌",
                    "original_filename": "厨房场景图.png",
                    "oss_url": "https://oss.example.com/brand/image.png",
                    "source_url": "https://example.com/kitchen.png",
                    "content_type": "image/png",
                    "file_size": 12345,
                    "image_summary": "现代厨房橱柜场景图",
                    "image_tags": ["厨房", "橱柜"],
                }
            }
        )
        categories = _FakeDocumentCategories()
        subcategory_calls: list[tuple[str, str]] = []

        def _latest_document_ids_by_category_and_subcategory(category: str, subcategory: str) -> list[str]:
            subcategory_calls.append((category, subcategory))
            return ["asset_21"]

        categories.get_latest_document_ids_by_category_and_subcategory = _latest_document_ids_by_category_and_subcategory
        service = self._build_service(
            store=store,
            document_categories=categories,
            attachment_assets=attachment_assets,
            brand_full_knowledge=_FakeBrandFullKnowledgeStore(latest_document_id="kb-latest"),
        )

        result = asyncio.run(
            service.search_images(
                types.SimpleNamespace(
                    query="厨房橱柜",
                    top_k=10,
                    document_ids=None,
                    brand_name="示例品牌",
                    category=None,
                    subcategory="橱柜",
                )
            )
        )

        self.assertEqual(store.calls[0]["source_types"], ["image"])
        self.assertEqual(subcategory_calls, [("示例品牌", "橱柜")])
        self.assertEqual(categories.category_calls, [])
        self.assertEqual(service._deps.brand_full_knowledge.calls, [])
        self.assertEqual(attachment_assets.get_by_ids_calls, [[21]])
        self.assertEqual(attachment_assets.get_by_id_calls, [])
        self.assertEqual(len(result), 1)
        self.assertEqual(
            result[0],
            {
                "asset_id": 21,
                "document_id": "asset_21",
                "score": 0.93,
                "brand_code": "BRAND-001",
                "brand_name": "示例品牌",
                "subcategory": "橱柜",
                "original_filename": "厨房场景图.png",
                "oss_url": "https://oss.example.com/brand/image.png",
                "source_url": "https://example.com/kitchen.png",
                "content_type": "image/png",
                "file_size": 12345,
                "image_summary": "现代厨房橱柜场景图",
                "image_tags": ["厨房", "橱柜"],
            },
        )

    def test_search_images_product_code_resolves_brand_without_product_filter(self) -> None:
        store = _FakeStore(grouped_hits=[])
        categories = _FakeDocumentCategories()
        service = self._build_service(
            store=store,
            document_categories=categories,
        )

        result = asyncio.run(
            service.search_images(
                types.SimpleNamespace(
                    query="厨房橱柜",
                    top_k=10,
                    document_ids=None,
                    brand_code=None,
                    brand_name=None,
                    category=None,
                    product_code="PROD-WHMY",
                    subcategory=None,
                )
            )
        )

        self.assertEqual(result, [])
        self.assertEqual(categories.category_calls, ["炜衡密云分所"])
        self.assertEqual(store.calls[0]["brand_code"], "WHMY")
        self.assertIsNone(store.calls[0]["product_code"])

    def test_search_semantic_non_brand_category_keeps_legacy_category_lookup(self) -> None:
        grouped_hits = [
            {
                "document_id": "legacy-doc",
                "source_name": "普通分类文档",
                "metadata": {"category": "非品牌分类"},
                "file_url": "https://example.com/legacy.md",
                "chunks": [{"chunk_id": "chunk-legacy", "score": 0.82, "text": "普通分类内容"}],
            }
        ]
        store = _FakeStore(grouped_hits=grouped_hits)
        categories = _FakeDocumentCategories()
        service = self._build_service(store=store, document_categories=categories)

        result = asyncio.run(
            service.search_semantic(
                types.SimpleNamespace(
                    query="普通分类内容",
                    top_k=5,
                    document_ids=None,
                    source_types=None,
                    category="非品牌分类",
                    subcategory=None,
                )
            )
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(categories.category_calls, ["非品牌分类"])
        self.assertEqual(store.calls[0]["document_ids"], ["legacy-doc"])

    def test_search_structured_uses_structured_hits_before_semantic_merge(self) -> None:
        structured_hits = [
            {
                "chunk_id": "structured-1",
                "content": "结构化命中",
                "score": 0.99,
                "brand_name": "示例品牌",
                "category": "示例品牌",
                "metadata": {"section_title": "品牌基础信息"},
            }
        ]
        grouped_hits = [
            {
                "document_id": "legacy-doc",
                "source_name": "普通分类文档",
                "metadata": {"category": "示例品牌"},
                "file_url": "https://example.com/legacy.md",
                "chunks": [{"chunk_id": "chunk-legacy", "score": 0.82, "text": "普通分类内容"}],
            }
        ]
        store = _FakeStore(grouped_hits=grouped_hits)
        categories = _FakeDocumentCategories()
        brand_app = _FakeBrandApp(structured_hits=structured_hits)
        service = self._build_service(
            store=store,
            document_categories=categories,
            brand_app=brand_app,
        )

        result = asyncio.run(
            service.search(
                types.SimpleNamespace(
                    query="品牌名称",
                    top_k=5,
                    document_ids=None,
                    source_types=None,
                    brand_name="示例品牌",
                    category=None,
                    subcategory=None,
                    model_copy=lambda update: types.SimpleNamespace(
                        query="品牌名称",
                        top_k=update["top_k"],
                        document_ids=None,
                        source_types=None,
                        brand_name="示例品牌",
                        category=None,
                        subcategory=None,
                    ),
                )
            )
        )

        self.assertEqual(brand_app.calls, [{"query": "品牌名称", "top_k": 5, "brand_name": "示例品牌", "category": None, "subcategory": None}])
        self.assertEqual(result[0]["chunk_id"], "structured-1")

    def test_search_with_document_filter_batches_limits_milvus_search_concurrency(self) -> None:
        store = _ConcurrencyTrackingStore()
        service = self._build_service(
            store=store,
            settings=types.SimpleNamespace(
                milvus_filter_batch_size=1,
                vector_search_max_concurrency=2,
            ),
        )

        result = asyncio.run(
            service._search_with_document_filter_batches(
                query_vector=[0.1, 0.2],
                top_k=10,
                document_ids=["doc-1", "doc-2", "doc-3", "doc-4", "doc-5"],
                source_types=None,
            )
        )

        self.assertLessEqual(store.max_active, 2)
        self.assertEqual(len(store.calls), 5)
        self.assertEqual(len(result), 5)


if __name__ == "__main__":
    unittest.main()
