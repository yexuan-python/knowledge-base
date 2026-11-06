from __future__ import annotations

import types
import unittest
from unittest.mock import AsyncMock, patch

from knowledge_base.brand.application import BrandApplicationDependencies, BrandApplicationService

from tests.fakes.brand_flow import (
    EmptyBrandProductStore,
    FakeBrandFullKnowledgeStore,
    FakeBrandKnowledgeStore,
    FakeBrandStore,
    FakeDocumentCategoryStore,
    FakeDocumentRegistryStore,
    FakeIndustryStore,
    FakeSettings,
    _build_brand_application,
)


class BrandPathCachingTests(unittest.TestCase):
    def test_load_brand_paths_caches_assets_by_revision_and_path(self) -> None:
        brand_store = FakeBrandStore()
        brand_full_knowledge = FakeBrandFullKnowledgeStore()
        brand_full_knowledge.rows = [
            {
                "id": 13,
                "brand_id": 1,
                "brand_code": "BRAND-001",
                "brand_name": "示例品牌",
                "version_no": 10,
                "file_name": "【示例品牌】品牌AI知识库_V10_20260808.md",
                "content_markdown": "\n".join(
                    [
                        "# 示例品牌 当前结构化知识基线",
                        "",
                        "## 产品信息",
                        "",
                        "### 花悦系列",
                        "",
                        "- **产品介绍**：缓存前的产品介绍。",
                    ]
                ),
            }
        ]
        application = BrandApplicationService(
            BrandApplicationDependencies(
                settings=FakeSettings(),
                brands=brand_store,
                brand_products=EmptyBrandProductStore(),
                brand_knowledge=FakeBrandKnowledgeStore(),
                brand_full_knowledge=brand_full_knowledge,
                industries=FakeIndustryStore(),
                brand_knowledge_sessions=types.SimpleNamespace(),
                document_registry=FakeDocumentRegistryStore(),
                document_categories=FakeDocumentCategoryStore(),
                fact_relations=None,
                store=None,
                document_app=None,
                delete_document=AsyncMock(),
                get_full_text=lambda _document_id: None,
                ingest_staged_file=AsyncMock(),
                ingest_from_url=AsyncMock(),
                delete_document_by_attachment_name=AsyncMock(),
            )
        )

        first_result = application.load_brand_paths(
            brand_code="BRAND-001",
            paths=["产品信息/花悦系列"],
            knowledge_revision="demo-2026-06-23",
        )
        self.assertIsNotNone(first_result)
        assert first_result is not None
        self.assertIn("缓存前的产品介绍", first_result["assets"][0]["content"])

        brand_full_knowledge.rows[0]["content_markdown"] = "\n".join(
            [
                "# 示例品牌 当前结构化知识基线",
                "",
                "## 产品信息",
                "",
                "### 花悦系列",
                "",
                "- **产品介绍**：同 revision 下不应直接读到的新介绍。",
            ]
        )
        second_result = application.load_brand_paths(
            brand_code="BRAND-001",
            paths=["产品信息/花悦系列"],
            knowledge_revision="demo-2026-06-23",
        )
        self.assertIsNotNone(second_result)
        assert second_result is not None
        self.assertIn("缓存前的产品介绍", second_result["assets"][0]["content"])
        self.assertNotIn("同 revision 下不应直接读到的新介绍", second_result["assets"][0]["content"])

        brand_store.knowledge_revision = "demo-2026-07-01"
        third_result = application.load_brand_paths(
            brand_code="BRAND-001",
            paths=["产品信息/花悦系列"],
            knowledge_revision="demo-2026-07-01",
        )
        self.assertIsNotNone(third_result)
        assert third_result is not None
        self.assertEqual(third_result["assets"][0]["knowledge_revision"], "demo-2026-07-01")
        self.assertIn("同 revision 下不应直接读到的新介绍", third_result["assets"][0]["content"])

    def test_load_brand_paths_returns_full_cache_hits_without_reloading_snapshot_or_markdown(self) -> None:
        brand_full_knowledge = FakeBrandFullKnowledgeStore()
        brand_full_knowledge.rows = [
            {
                "id": 14,
                "brand_id": 1,
                "brand_code": "BRAND-001",
                "brand_name": "示例品牌",
                "version_no": 11,
                "file_name": "【示例品牌】品牌AI知识库_V11_20260808.md",
                "content_markdown": "\n".join(
                    [
                        "# 示例品牌 当前结构化知识基线",
                        "",
                        "## 产品信息",
                        "",
                        "### 花悦系列",
                        "",
                        "- **产品介绍**：全命中缓存时不应重新读取的介绍。",
                    ]
                ),
            }
        ]
        application = BrandApplicationService(
            BrandApplicationDependencies(
                settings=FakeSettings(),
                brands=FakeBrandStore(),
                brand_products=EmptyBrandProductStore(),
                brand_knowledge=FakeBrandKnowledgeStore(),
                brand_full_knowledge=brand_full_knowledge,
                industries=FakeIndustryStore(),
                brand_knowledge_sessions=types.SimpleNamespace(),
                document_registry=FakeDocumentRegistryStore(),
                document_categories=FakeDocumentCategoryStore(),
                fact_relations=None,
                store=None,
                document_app=None,
                delete_document=AsyncMock(),
                get_full_text=lambda _document_id: None,
                ingest_staged_file=AsyncMock(),
                ingest_from_url=AsyncMock(),
                delete_document_by_attachment_name=AsyncMock(),
            )
        )

        first_result = application.load_brand_paths(
            brand_code="BRAND-001",
            paths=["产品信息/花悦系列"],
            knowledge_revision="demo-2026-06-23",
        )
        self.assertIsNotNone(first_result)

        with patch.object(application, "_load_brand_snapshot", side_effect=AssertionError("should not load snapshot")):
            with patch.object(
                application,
                "_get_latest_brand_full_knowledge_markdown",
                side_effect=AssertionError("should not load markdown"),
            ):
                second_result = application.load_brand_paths(
                    brand_code="BRAND-001",
                    paths=["产品信息/花悦系列"],
                    knowledge_revision="demo-2026-06-23",
                )

        self.assertIsNotNone(second_result)
        assert second_result is not None
        self.assertEqual(second_result["missing_paths"], [])
        self.assertIn("全命中缓存时不应重新读取的介绍", second_result["assets"][0]["content"])

    def test_load_brand_paths_access_cleans_expired_unused_cache_entries(self) -> None:
        application = _build_brand_application()
        application._brand_paths_load_cache_ttl_seconds = 1.0
        application._brand_paths_load_cache_cleanup_interval_seconds = 0.0
        stale_key = ("BRAND-001", "demo-old", "产品信息/旧产品")
        application._brand_paths_load_cache[stale_key] = (
            0.0,
            0.0,
            {
                "title": "旧产品",
                "path": "产品信息/旧产品",
                "content": "过期缓存",
                "knowledge_revision": "demo-old",
                "updated_at": None,
            },
        )

        application._brand_paths_load_cache_cleanup_interval_seconds = 0.0001
        application._brand_paths_load_cache_last_cleanup_at = 0.0

        result = application.load_brand_paths(
            brand_code="BRAND-001",
            paths=["品牌基础信息/品牌介绍"],
            knowledge_revision="demo-2026-06-23",
        )

        self.assertIsNotNone(result)
        self.assertNotIn(stale_key, application._brand_paths_load_cache)

    def test_load_brand_paths_cache_evicts_oldest_entries_when_over_limit(self) -> None:
        application = _build_brand_application()
        application._brand_paths_load_cache_max_entries = 1
        application._brand_paths_load_cache_ttl_seconds = 600.0

        application._cache_brand_path_asset(
            brand_code="BRAND-001",
            knowledge_revision="demo-2026-06-23",
            path="品牌基础信息/品牌介绍",
            asset={
                "title": "品牌介绍",
                "path": "品牌基础信息/品牌介绍",
                "content": "第一份缓存",
                "knowledge_revision": "demo-2026-06-23",
                "updated_at": None,
            },
        )
        application._cache_brand_path_asset(
            brand_code="BRAND-001",
            knowledge_revision="demo-2026-06-23",
            path="产品信息/明星产品",
            asset={
                "title": "明星产品",
                "path": "产品信息/明星产品",
                "content": "第二份缓存",
                "knowledge_revision": "demo-2026-06-23",
                "updated_at": None,
            },
        )

        self.assertEqual(len(application._brand_paths_load_cache), 1)
        self.assertIsNone(
            application._get_cached_brand_path_asset(
                brand_code="BRAND-001",
                knowledge_revision="demo-2026-06-23",
                path="品牌基础信息/品牌介绍",
            )
        )
        cached_asset = application._get_cached_brand_path_asset(
            brand_code="BRAND-001",
            knowledge_revision="demo-2026-06-23",
            path="产品信息/明星产品",
        )
        self.assertIsNotNone(cached_asset)
        assert cached_asset is not None
        self.assertEqual(cached_asset["content"], "第二份缓存")

    def test_path_index_summary_cache_evicts_oldest_entries_when_over_limit(self) -> None:
        application = _build_brand_application()
        application._path_index_summary_cache_max_entries = 1
        application._path_index_summary_cache_ttl_seconds = 600.0

        application._cache_path_index_summary(
            brand_code="BRAND-001",
            knowledge_revision="demo-2026-06-23",
            path="品牌基础信息/品牌介绍",
            summary="第一条摘要",
        )
        application._cache_path_index_summary(
            brand_code="BRAND-001",
            knowledge_revision="demo-2026-06-23",
            path="产品信息/明星产品",
            summary="第二条摘要",
        )

        self.assertEqual(len(application._path_index_summary_cache), 1)
        self.assertIsNone(
            application._get_cached_path_index_summary(
                brand_code="BRAND-001",
                knowledge_revision="demo-2026-06-23",
                path="品牌基础信息/品牌介绍",
            )
        )
        self.assertEqual(
            application._get_cached_path_index_summary(
                brand_code="BRAND-001",
                knowledge_revision="demo-2026-06-23",
                path="产品信息/明星产品",
            ),
            "第二条摘要",
        )
