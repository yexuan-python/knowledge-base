from __future__ import annotations

from tests.fakes.brand_ai_ingestion import *


class BrandAiKnowledgeIngestionBackfillTests(unittest.IsolatedAsyncioTestCase):
    async def test_ingest_can_backfill_brand_knowledge_json_from_full_markdown(self) -> None:
        full_knowledge_store = _FakeBrandFullKnowledgeStore()
        job_store = _FakeJobStore()
        brand_knowledge_store = _FakeBrandKnowledgeStore()
        brand_products_store = _FakeBrandProductsStore()
        brand_knowledge_store.rows_by_brand_id[1] = [
            {
                "knowledge_type": "company_profile",
                "content_json": {
                    "brand_subject_name": "福建鼎冠纺织有限公司",
                    "company_intro": "旧简介",
                    "registered_capital": "3000万元",
                },
            },
            {
                "knowledge_type": "management_team",
                "content_json": [
                    {
                        "member_name": "旧高管",
                        "position": "旧职位",
                        "bio": "",
                    }
                ],
            },
            {
                "knowledge_type": "competitors",
                "content_json": [
                    {
                        "name": "已有竞品",
                        "aliases": ["旧别名"],
                        "introduction": "",
                    }
                ],
            },
            {
                "knowledge_type": "attachments",
                "content_json": [
                    {
                        "name": "已有附件.pdf",
                        "url": "https://example.com/existing.pdf",
                        "summary": "",
                    }
                ],
            },
            {
                "knowledge_type": "other_info",
                "content_json": [
                    {
                        "title": "已有说明",
                        "content": "保留已有内容",
                    }
                ],
            },
            {
                "knowledge_type": "sensitive_topics",
                "content_json": {
                    "controversial_events": ["旧争议A"],
                    "forbidden_words": ["禁用词A"],
                },
            },
            {
                "knowledge_type": "attachment_products",
                "content_json": [
                    {
                        "name": "已有附件产品C",
                        "product_description": "保留已有附件产品",
                    }
                ],
            },
        ]
        vector_store = _FakeVectorStore()
        brands_store = _FakeBrands(
            {
                "id": 1,
                "brand_code": "BRAND-001",
                "brand_name": "示例品牌",
                "brand_alias": "旧别名",
                "brand_logo": "https://example.com/old-logo.png",
                "website": ["https://old.example.com"],
                "industry_id": 12,
                "vision": [],
            }
        )
        service = BrandAiKnowledgeIngestionService(
            BrandAiKnowledgeIngestionDependencies(
                settings=types.SimpleNamespace(chunk_size=100, chunk_overlap=10),
                brands=brands_store,
                parser=_FakeParser("# 示例品牌\n\n正文"),
                embeddings=_FakeEmbeddings(),
                store=vector_store,
                oss_client=_FakeOssClient(),
                brand_full_knowledge=full_knowledge_store,
                brand_knowledge_facts=_FakeFactsStore(),
                brand_knowledge_ingestion_jobs=job_store,
                brand_knowledge=brand_knowledge_store,
                brand_products=brand_products_store,
            )
        )
        brand_products_store.rows_by_brand_id[1] = [
            {
                "product_name": "品牌产品A",
                "product_alias": "产品别名A",
                "product_description": "",
                "product_website": "https://example.com/product-a",
                "product_images_json": ["https://example.com/a.png"],
                "price_info": "1999",
                "coverage_regions_json": ["全国"],
                "product_advantages": "核心优势A",
                "target_scenarios": "使用场景A",
                "service_standard": "服务标准A",
                "service_process": "服务流程A",
                "cases_and_reputation": "案例口碑A",
                "certification_info": "资质A",
                "core_technology": "核心技术A",
                "other_info": "其他信息A",
            }
        ]

        async def _fake_render_pdf(*, markdown_text: str, title: str) -> bytes:
            return b"%PDF-1.4"

        async def _fake_build_fact_rows(**kwargs):
            return []

        async def _fake_write_document_chunks(**kwargs):
            vector_store.inserted_chunks.append(kwargs)

        expected_vision = [
            "成为高端厨柜的领导品牌和定制家居的领先品牌,引领定制家居行业的发展,打造国际一流的智慧家居集团,与员工、合作伙伴共同成长。"
        ]

        async def _fake_extract_snapshot_from_markdown(**kwargs):
            return {
                "basic_info": {
                    "brand_name": "示例品牌",
                    "brand_alias": "新别名不应覆盖",
                    "brand_logo": "https://example.com/new-logo.png",
                    "website": ["https://new.example.com"],
                    "industry_id": 34,
                    "customer_service_hotline": ["400-NEW,13366757920,13366757976"],
                    "vision": expected_vision,
                },
                "products": [
                    {
                        "name": "品牌产品A",
                        "product_description": "白名单产品只补 brand_products 空值",
                        "product_advantages": "新优势不应覆盖已有优势",
                    },
                    {
                        "name": "正文新增产品B",
                        "product_description": "应进入 attachment_products",
                        "product_website": "https://example.com/product-b",
                        "coverage_regions": "全国",
                    }
                ],
                "company_profile": {
                    "brand_subject_name": "福建鼎冠纺织有限公司",
                    "company_intro": "来自正式知识库的新简介",
                },
                "management_team": [
                    {
                        "member_name": "旧高管",
                        "position": "新职位不应覆盖",
                        "bio": "补充旧高管简介",
                    },
                    {
                        "member_name": "新高管",
                        "position": "新职位",
                    }
                ],
                "competitors": [
                    {
                        "name": "已有竞品",
                        "aliases": ["新别名"],
                        "introduction": "来自正式知识库的新介绍",
                    },
                    {
                        "name": "新增竞品",
                        "aliases": ["不应新增"],
                    }
                ],
                "authority_honors": [
                    {
                        "title": "新荣誉",
                        "year": "2026",
                    }
                ],
                "customers_cases": [],
                "sensitive_topics": {
                    "forbidden_words": ["禁用词A", "禁用词B"],
                },
                "attachments": [
                    {
                        "name": "已有附件.pdf",
                        "url": "https://example.com/existing.pdf",
                        "summary": "补充已有附件摘要",
                    },
                    {
                        "name": "新增附件.pdf",
                        "url": "https://example.com/new.pdf",
                    },
                ],
                "official_malls": [],
                "official_media_matrix": [],
                "other_info": [
                    {
                        "title": "新的说明",
                        "content": "来自正式知识库的新 other_info",
                    },
                ],
                "attachment_products": [
                    {
                        "name": "附件区新增产品D",
                        "product_description": "附件区产品也应进入 attachment_products",
                    }
                ],
            }

        original_extract_snapshot = _MODULE.extract_brand_knowledge_snapshot_from_markdown
        _MODULE.extract_brand_knowledge_snapshot_from_markdown = _fake_extract_snapshot_from_markdown
        service._render_pdf = _fake_render_pdf
        service._build_fact_rows = _fake_build_fact_rows
        service._write_document_chunks = _fake_write_document_chunks

        with tempfile.NamedTemporaryFile(delete=False, suffix=".md") as tmp:
            tmp.write("# 新知识库\n\n正文".encode("utf-8"))
            staged_path = Path(tmp.name)

        try:
            result = await service.ingest_upload_task_file(
                task_id="task-4",
                upload_task_file_id=4,
                filename="【示例品牌】品牌AI知识库_V1_20260715.md",
                brand_code="BRAND-001",
                brand_name="示例品牌",
                force_reingest=False,
                staged_path=staged_path,
                source_url=None,
                content_type="text/markdown",
                backfill_brand_knowledge_json_empty_only=True,
            )
        finally:
            _MODULE.extract_brand_knowledge_snapshot_from_markdown = original_extract_snapshot
            staged_path.unlink(missing_ok=True)

        self.assertEqual("success", result["knowledge_json_backfill_status"])
        self.assertEqual(1, len(brands_store.upserted_rows))
        brand_upsert_payload = brands_store.upserted_rows[0]
        self.assertEqual("旧别名", brand_upsert_payload["brand_alias"])
        self.assertEqual("https://example.com/old-logo.png", brand_upsert_payload["brand_logo"])
        self.assertEqual("[\"https://old.example.com\"]", brand_upsert_payload["website"])
        self.assertEqual(12, brand_upsert_payload["industry_id"])
        self.assertEqual(
            ["400-NEW", "13366757920", "13366757976"],
            brand_upsert_payload["customer_service_hotline"],
        )
        self.assertEqual(expected_vision, brand_upsert_payload["vision"])
        upserted_by_type = {
            row["knowledge_type"]: row
            for row in brand_knowledge_store.upserted_rows
        }
        self.assertNotIn("basic_info", upserted_by_type)
        self.assertEqual(
            "来自正式知识库的新简介",
            upserted_by_type["company_profile"]["content_json"]["company_intro"],
        )
        self.assertEqual(
            "福建鼎冠纺织有限公司",
            upserted_by_type["company_profile"]["content_json"]["brand_subject_name"],
        )
        self.assertEqual(
            "3000万元",
            upserted_by_type["company_profile"]["content_json"]["registered_capital"],
        )
        self.assertEqual(
            [
                {
                    "name": "已有竞品",
                    "aliases": ["旧别名"],
                    "introduction": "来自正式知识库的新介绍",
                    "official_websites": [],
                    "logo_urls": [],
                    "strengths": [],
                    "differentiated_positioning": [],
                    "comparison_dimensions": [],
                    "other_info": [],
                }
            ],
            upserted_by_type["competitors"]["content_json"],
        )
        self.assertEqual(
            [
                {
                    "member_name": "旧高管",
                    "position": "旧职位",
                    "bio": "补充旧高管简介",
                },
                {
                    "member_name": "新高管",
                    "position": "新职位",
                }
            ],
            upserted_by_type["management_team"]["content_json"],
        )
        self.assertEqual(
            [{"title": "新荣誉", "year": "2026"}],
            upserted_by_type["authority_honors"]["content_json"],
        )
        self.assertEqual(
            [
                {
                    "name": "已有附件.pdf",
                    "url": "https://example.com/existing.pdf",
                    "summary": "补充已有附件摘要",
                },
                {
                    "name": "新增附件.pdf",
                    "url": "https://example.com/new.pdf",
                }
            ],
            upserted_by_type["attachments"]["content_json"],
        )
        self.assertEqual(
            {
                "controversial_events": ["旧争议A"],
                "forbidden_words": ["禁用词A", "禁用词B"],
            },
            upserted_by_type["sensitive_topics"]["content_json"],
        )
        expected_attachment_products = [
            {
                "name": "已有附件产品C",
                "product_alias": None,
                "product_description": "保留已有附件产品",
                "product_website": None,
                "product_images": [],
                "price_info": None,
                "coverage_regions": [],
                "product_advantages": None,
                "target_scenarios": None,
                "service_standard": None,
                "service_process": None,
                "cases_and_reputation": None,
                "certification_info": None,
                "core_technology": None,
                "other_info": None,
            },
            {
                "name": "附件区新增产品D",
                "product_alias": None,
                "product_description": "附件区产品也应进入 attachment_products",
                "product_website": None,
                "product_images": [],
                "price_info": None,
                "coverage_regions": [],
                "product_advantages": None,
                "target_scenarios": None,
                "service_standard": None,
                "service_process": None,
                "cases_and_reputation": None,
                "certification_info": None,
                "core_technology": None,
                "other_info": None,
            },
            {
                "name": "正文新增产品B",
                "product_alias": None,
                "product_description": "应进入 attachment_products",
                "product_website": "https://example.com/product-b",
                "product_images": [],
                "price_info": None,
                "coverage_regions": ["全国"],
                "product_advantages": None,
                "target_scenarios": None,
                "service_standard": None,
                "service_process": None,
                "cases_and_reputation": None,
                "certification_info": None,
                "core_technology": None,
                "other_info": None,
            }
        ]
        self.assertEqual(
            expected_attachment_products,
            upserted_by_type["attachment_products"]["content_json"],
        )
        attachment_products_other_info = next(
            item
            for item in upserted_by_type["other_info"]["content_json"]
            if item["title"] == "附件解析新增产品"
        )
        self.assertIn(
            {
                "title": "新的说明",
                "content": "来自正式知识库的新 other_info",
            },
            upserted_by_type["other_info"]["content_json"],
        )
        self.assertNotIn(
            {
                "title": "已有说明",
                "content": "保留已有内容",
            },
            upserted_by_type["other_info"]["content_json"],
        )
        self.assertEqual(
            expected_attachment_products,
            attachment_products_other_info["content"],
        )
        self.assertIsNotNone(brand_products_store.last_products_upsert)
        upserted_products = brand_products_store.last_products_upsert["products"]
        self.assertEqual(1, len(upserted_products))
        self.assertEqual("品牌产品A", upserted_products[0]["product_name"])
        self.assertEqual("白名单产品只补 brand_products 空值", upserted_products[0]["product_description"])
        self.assertEqual("核心优势A", upserted_products[0]["product_advantages"])

    def test_full_markdown_backfill_other_info_replaces_existing_snapshot(self) -> None:
        service = BrandAiKnowledgeIngestionService(
            BrandAiKnowledgeIngestionDependencies(
                settings=types.SimpleNamespace(),
                brands=_FakeBrands(),
                parser=_FakeParser("# 示例品牌"),
                embeddings=_FakeEmbeddings(),
                store=_FakeVectorStore(),
                oss_client=_FakeOssClient(),
                brand_full_knowledge=_FakeBrandFullKnowledgeStore(),
                brand_knowledge_facts=_FakeFactsStore(),
                brand_knowledge_ingestion_jobs=_FakeJobStore(),
            )
        )

        merged = service._merge_full_markdown_backfill_snapshot(
            existing_snapshot={
                "other_info": [
                    {
                        "title": "服务政策",
                        "content": "旧服务政策",
                    },
                    {
                        "title": "历史保留",
                        "content": "本次 Markdown 未出现时应删除",
                    },
                ],
            },
            incoming_snapshot={
                "other_info": [
                    {
                        "title": "服务政策",
                        "content": "新服务政策",
                    },
                    {
                        "title": "新增说明",
                        "content": "新增内容",
                    },
                ],
            },
        )

        self.assertEqual(
            [
                {
                    "title": "服务政策",
                    "content": "新服务政策",
                },
                {
                    "title": "新增说明",
                    "content": "新增内容",
                },
            ],
            merged["other_info"],
        )

    def test_full_markdown_backfill_other_info_clears_existing_when_missing_from_markdown(self) -> None:
        service = BrandAiKnowledgeIngestionService(
            BrandAiKnowledgeIngestionDependencies(
                settings=types.SimpleNamespace(),
                brands=_FakeBrands(),
                parser=_FakeParser("# 示例品牌"),
                embeddings=_FakeEmbeddings(),
                store=_FakeVectorStore(),
                oss_client=_FakeOssClient(),
                brand_full_knowledge=_FakeBrandFullKnowledgeStore(),
                brand_knowledge_facts=_FakeFactsStore(),
                brand_knowledge_ingestion_jobs=_FakeJobStore(),
            )
        )

        merged = service._merge_full_markdown_backfill_snapshot(
            existing_snapshot={
                "other_info": [
                    {
                        "title": "历史保留",
                        "content": "本次 Markdown 未出现时应删除",
                    },
                ],
            },
            incoming_snapshot={"other_info": []},
        )

        self.assertEqual([], merged["other_info"])

    def test_merge_existing_competitors_only_matches_by_incoming_aliases(self) -> None:
        service = BrandAiKnowledgeIngestionService(
            BrandAiKnowledgeIngestionDependencies(
                settings=types.SimpleNamespace(),
                brands=_FakeBrands(),
                parser=_FakeParser("# 示例品牌"),
                embeddings=_FakeEmbeddings(),
                store=_FakeVectorStore(),
                oss_client=_FakeOssClient(),
                brand_full_knowledge=_FakeBrandFullKnowledgeStore(),
                brand_knowledge_facts=_FakeFactsStore(),
                brand_knowledge_ingestion_jobs=_FakeJobStore(),
            )
        )

        merged = service._merge_existing_competitors_only(
            [
                {
                    "name": "盛弘",
                    "aliases": [],
                    "introduction": "",
                    "official_websites": [],
                    "logo_urls": [],
                    "strengths": [],
                    "differentiated_positioning": [],
                    "comparison_dimensions": [],
                    "other_info": [],
                }
            ],
            [
                {
                    "name": "深圳市盛弘电气股份有限公司",
                    "aliases": ["盛弘", "Sinexcel"],
                    "introduction": "来自正式知识库的竞品介绍",
                    "official_websites": ["https://www.sinexcel.com"],
                    "strengths": ["大功率产品线"],
                }
            ],
        )

        self.assertEqual(
            [
                {
                    "name": "盛弘",
                    "aliases": ["盛弘", "Sinexcel"],
                    "introduction": "来自正式知识库的竞品介绍",
                    "official_websites": ["https://www.sinexcel.com"],
                    "logo_urls": [],
                    "strengths": ["大功率产品线"],
                    "differentiated_positioning": [],
                    "comparison_dimensions": [],
                    "other_info": [],
                }
            ],
            merged,
        )
    def test_merge_existing_competitors_only_does_not_match_unrelated_competitors(self) -> None:
        service = BrandAiKnowledgeIngestionService(
            BrandAiKnowledgeIngestionDependencies(
                settings=types.SimpleNamespace(),
                brands=_FakeBrands(),
                parser=_FakeParser("# 示例品牌"),
                embeddings=_FakeEmbeddings(),
                store=_FakeVectorStore(),
                oss_client=_FakeOssClient(),
                brand_full_knowledge=_FakeBrandFullKnowledgeStore(),
                brand_knowledge_facts=_FakeFactsStore(),
                brand_knowledge_ingestion_jobs=_FakeJobStore(),
            )
        )

        merged = service._merge_existing_competitors_only(
            [
                {
                    "name": "盛弘",
                    "aliases": [],
                    "introduction": "",
                    "official_websites": [],
                    "logo_urls": [],
                    "strengths": [],
                    "differentiated_positioning": [],
                    "comparison_dimensions": [],
                    "other_info": [],
                }
            ],
            [
                {
                    "name": "特来电新能源股份有限公司",
                    "aliases": ["特来电", "TELD"],
                    "introduction": "不应该误回补到盛弘",
                    "official_websites": ["https://www.teld.cn"],
                }
            ],
        )

        self.assertEqual(
            [
                {
                    "name": "盛弘",
                    "aliases": [],
                    "introduction": "",
                    "official_websites": [],
                    "logo_urls": [],
                    "strengths": [],
                    "differentiated_positioning": [],
                    "comparison_dimensions": [],
                    "other_info": [],
                }
            ],
            merged,
        )
