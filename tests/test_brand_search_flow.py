from __future__ import annotations

import unittest

from knowledge_base.document.schemas import SearchRequest

from tests.fakes.brand_flow import _build_search_application


class BrandSearchFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_structured_search_returns_brand_text_only(self) -> None:
        application = _build_search_application()
        request = SearchRequest(query="企业主体", category="示例品牌", top_k=5)
        hits = await application.search(request)

        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["content"], "品牌企业主体：示例企业主体")
        self.assertEqual(hits[0]["category"], "示例品牌")
        self.assertEqual(hits[0]["metadata"]["brand_name"], "示例品牌")

    async def test_structured_search_matches_official_website_query(self) -> None:
        application = _build_search_application()
        request = SearchRequest(query="官网链接", category="示例品牌", top_k=5)
        hits = await application.search(request)

        self.assertGreaterEqual(len(hits), 1)
        self.assertEqual(hits[0]["content"], "品牌官网：https://example.com")
        self.assertGreater(float(hits[0]["score"]), 0.0)
        self.assertEqual(hits[0]["metadata"]["section_title"], "品牌官网")

    async def test_hybrid_search_merges_structured_and_semantic_hits(self) -> None:
        application = _build_search_application()

        async def fake_semantic(request: SearchRequest, *, prefer_latest_brand_document: bool = True):
            return [
                {
                    "document_id": "milvus-doc-1",
                    "source_name": "语义文档",
                    "source_type": "text",
                    "file_url": None,
                    "chunks": [{"chunk_id": "c1", "score": 0.8, "text": "语义结果"}],
                }
            ]

        application.search_semantic = fake_semantic  # type: ignore[method-assign]

        request = SearchRequest(query="示例品牌和竞品对比", category="示例品牌", top_k=5)
        hits = await application.search(request)

        self.assertEqual(len(hits), 2)
        self.assertEqual(hits[0]["content"], "竞品信息：竞品A")
        self.assertEqual(hits[0]["metadata"]["section_title"], "竞品信息")
        self.assertEqual(
            hits[1],
            {
                "document_id": "milvus-doc-1",
                "source_name": "语义文档",
                "source_type": "text",
                "file_url": None,
                "chunks": [{"chunk_id": "c1", "score": 0.8, "text": "语义结果"}],
            },
        )

    async def test_hybrid_search_prunes_empty_structured_fields(self) -> None:
        application = _build_search_application()
        application._deps.brand_app._deps.brand_knowledge.knowledge_rows = [
            {
                "knowledge_type": "competitors",
                "content_json": [
                    {
                        "name": "竞品A",
                        "aliases": ["竞品A别名"],
                        "logo_urls": [],
                        "strengths": [],
                        "other_info": [],
                        "introduction": "",
                        "official_websites": [],
                        "comparison_dimensions": [],
                        "differentiated_positioning": [],
                    }
                ],
            }
        ]

        request = SearchRequest(query="行业竞品", category="示例品牌", top_k=5)
        hits = await application.search(request)

        self.assertEqual(len(hits), 1)
        self.assertEqual(
            hits[0]["content"],
            "竞品信息：竞品A（别名：竞品A别名）",
        )

    async def test_structured_search_still_queries_semantic_when_structured_hits_reach_top_k(self) -> None:
        application = _build_search_application()
        semantic_calls: list[bool] = []

        async def fake_semantic(request: SearchRequest, *, prefer_latest_brand_document: bool = True):
            semantic_calls.append(prefer_latest_brand_document)
            return []

        application.search_semantic = fake_semantic  # type: ignore[method-assign]

        request = SearchRequest(query="官网链接", category="示例品牌", top_k=1)
        hits = await application.search(request)

        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["content"], "品牌官网：https://example.com")
        self.assertEqual(semantic_calls, [True, False])

    async def test_hybrid_search_falls_back_to_broader_semantic_scope_when_brand_doc_hits_are_insufficient(self) -> None:
        application = _build_search_application()
        semantic_calls: list[bool] = []

        async def fake_semantic(request: SearchRequest, *, prefer_latest_brand_document: bool = True):
            semantic_calls.append(prefer_latest_brand_document)
            if prefer_latest_brand_document:
                return []
            return [
                {
                    "chunk_id": "c1",
                    "content": "Milvus补充结果1",
                    "score": 0.81,
                    "brand_name": "示例品牌",
                    "category": "示例品牌",
                    "metadata": {"section_title": "补充结果1"},
                },
                {
                    "chunk_id": "c2",
                    "content": "Milvus补充结果2",
                    "score": 0.8,
                    "brand_name": "示例品牌",
                    "category": "示例品牌",
                    "metadata": {"section_title": "补充结果2"},
                },
                {
                    "chunk_id": "c3",
                    "content": "Milvus补充结果3",
                    "score": 0.79,
                    "brand_name": "示例品牌",
                    "category": "示例品牌",
                    "metadata": {"section_title": "补充结果3"},
                },
                {
                    "chunk_id": "c4",
                    "content": "Milvus补充结果4",
                    "score": 0.78,
                    "brand_name": "示例品牌",
                    "category": "示例品牌",
                    "metadata": {"section_title": "补充结果4"},
                },
            ]

        application.search_semantic = fake_semantic  # type: ignore[method-assign]

        request = SearchRequest(query="行业竞品", category="示例品牌", top_k=5)
        hits = await application.search(request)

        self.assertEqual(len(hits), 5)
        self.assertEqual(semantic_calls, [True, False])
        self.assertEqual(hits[0]["content"], "竞品信息：竞品A")
        self.assertEqual(hits[1]["content"], "Milvus补充结果1")

    async def test_structured_search_matches_official_malls_and_media_queries(self) -> None:
        application = _build_search_application()
        application._deps.brand_app._deps.brand_knowledge.knowledge_rows = [
            {
                "knowledge_type": "official_malls",
                "content_json": [
                    {
                        "store_name": "品牌旗舰店",
                        "platform": "天猫",
                        "homepage_urls": ["https://mall.example.com"],
                        "main_categories": ["智能汽车"],
                        "advantages": ["官方正品"],
                        "related_products": [1001],
                        "other_info": ["支持售后咨询"],
                    }
                ],
            },
            {
                "knowledge_type": "official_media_matrix",
                "content_json": [
                    {
                        "media_platform": "微信公众号",
                        "account_name": "品牌服务号",
                        "account_id": "brand-service",
                        "is_official": "是",
                        "related_products": ["200001"],
                        "other_info": ["新品发布"],
                    }
                ],
            },
        ]

        mall_hits = await application.search(SearchRequest(query="官方商城", category="示例品牌", top_k=5))
        media_hits = await application.search(SearchRequest(query="媒体矩阵", category="示例品牌", top_k=5))

        self.assertTrue(any("官方商城" in item["content"] for item in mall_hits))
        self.assertTrue(any(item["metadata"]["section_title"] == "官方商城" for item in mall_hits))
        self.assertTrue(any("官方媒体与矩阵" in item["content"] for item in media_hits))
        self.assertTrue(any(item["metadata"]["section_title"] == "官方媒体与矩阵" for item in media_hits))
