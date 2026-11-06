from __future__ import annotations

from tests.fakes.attachment_preview_flow import *


class AttachmentPreviewReviewScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_review_changes_ignores_new_products_outside_existing_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = AttachmentDraftService(
                AttachmentDraftDependencies(
                    settings=types.SimpleNamespace(upload_staging_dir=temp_dir, dashscope_api_key="test-key", text_llm_model="qwen-plus"),
                    parser=_FakeParser(),
                    oss_client=types.SimpleNamespace(enabled=False),
                    brands=_FakeBrandStore(),
                    brand_products=_FakeBrandProductStore(),
                    brand_knowledge=_FakeBrandKnowledgeStore(),
                    update_knowledge=AsyncMock(),
                    ingest_text_document=AsyncMock(),
                )
            )

            draft_id = "bad_ignore_new_product"
            draft_dir = Path(temp_dir) / "attachment_parse_drafts" / draft_id
            draft_dir.mkdir(parents=True, exist_ok=True)
            (draft_dir / "draft.json").write_text(
                json.dumps(
                    {
                        "draft_id": draft_id,
                        "brand_name": "示例品牌",
                        "brand_code": "BRAND-001",
                        "attachments": [],
                        "combined_markdown_text": "# 示例品牌 附件预解析草稿",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            candidate_snapshot = {
                "basic_info": {},
                "products": [
                    {
                        "name": "新品A",
                        "product_description": "新品介绍",
                    }
                ],
                "company_profile": {},
                "management_team": [],
                "competitors": [],
                "authority_honors": [],
                "customers_cases": [],
                "sensitive_topics": {},
            }

            result = await service.review_changes(
                request=types.SimpleNamespace(
                    brand_name=None,
                    brand_code=None,
                    candidate_snapshot=candidate_snapshot,
                    knowledge_revision="LXKG-SLPP-V1.0.0-20260630010101",
                ),
                draft_id=draft_id,
            )

        self.assertTrue(any(str(item["field_path"]).startswith("products[新品A]") for item in result["changes"]))

    async def test_review_changes_ignores_products_when_brand_has_no_existing_products(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = AttachmentDraftService(
                AttachmentDraftDependencies(
                    settings=types.SimpleNamespace(upload_staging_dir=temp_dir, dashscope_api_key="test-key", text_llm_model="qwen-plus"),
                    parser=_FakeParser(),
                    oss_client=types.SimpleNamespace(enabled=False),
                    brands=_FakeBrandStore(),
                    brand_products=_FakeBrandProductStore(products=[]),
                    brand_knowledge=_FakeBrandKnowledgeStore(),
                    update_knowledge=AsyncMock(),
                    ingest_text_document=AsyncMock(),
                )
            )

            draft_id = "bad_no_existing_products"
            draft_dir = Path(temp_dir) / "attachment_parse_drafts" / draft_id
            draft_dir.mkdir(parents=True, exist_ok=True)
            (draft_dir / "draft.json").write_text(
                json.dumps(
                    {
                        "draft_id": draft_id,
                        "brand_name": "示例品牌",
                        "brand_code": "BRAND-001",
                        "attachments": [],
                        "combined_markdown_text": "# 示例品牌 附件预解析草稿",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            candidate_snapshot = {
                "basic_info": {},
                "products": [
                    {
                        "name": "新品A",
                        "product_description": "新品介绍",
                    }
                ],
                "company_profile": {},
                "management_team": [],
                "competitors": [],
                "authority_honors": [],
                "customers_cases": [],
                "sensitive_topics": {},
            }

            result = await service.review_changes(
                request=types.SimpleNamespace(
                    brand_name=None,
                    brand_code=None,
                    candidate_snapshot=candidate_snapshot,
                    knowledge_revision="LXKG-SLPP-V1.0.0-20260630010101",
                ),
                draft_id=draft_id,
            )

        self.assertTrue(any(str(item["field_path"]).startswith("products[新品A]") for item in result["changes"]))

    async def test_review_changes_ignores_new_competitors_outside_existing_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = AttachmentDraftService(
                AttachmentDraftDependencies(
                    settings=types.SimpleNamespace(upload_staging_dir=temp_dir, dashscope_api_key="test-key", text_llm_model="qwen-plus"),
                    parser=_FakeParser(),
                    oss_client=types.SimpleNamespace(enabled=False),
                    brands=_FakeBrandStore(),
                    brand_products=_FakeBrandProductStore(),
                    brand_knowledge=_FakeBrandKnowledgeStore(),
                    update_knowledge=AsyncMock(),
                    ingest_text_document=AsyncMock(),
                )
            )

            draft_id = "bad_ignore_new_competitor"
            draft_dir = Path(temp_dir) / "attachment_parse_drafts" / draft_id
            draft_dir.mkdir(parents=True, exist_ok=True)
            (draft_dir / "draft.json").write_text(
                json.dumps(
                    {
                        "draft_id": draft_id,
                        "brand_name": "示例品牌",
                        "brand_code": "BRAND-001",
                        "attachments": [],
                        "combined_markdown_text": "# 示例品牌 附件预解析草稿",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            candidate_snapshot = {
                "basic_info": {},
                "products": [],
                "company_profile": {},
                "management_team": [],
                "competitors": [
                    {
                        "name": "竞品B",
                        "competitors_description": "新竞品介绍",
                    }
                ],
                "authority_honors": [],
                "customers_cases": [],
                "sensitive_topics": {},
            }

            result = await service.review_changes(
                request=types.SimpleNamespace(
                    brand_name=None,
                    brand_code=None,
                    candidate_snapshot=candidate_snapshot,
                    knowledge_revision="LXKG-SLPP-V1.0.0-20260630010101",
                ),
                draft_id=draft_id,
            )

        self.assertTrue(any(str(item["field_path"]).startswith("competitors.competitors[竞品B]") for item in result["changes"]))

    async def test_review_changes_ignores_competitors_when_brand_has_no_existing_competitors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = AttachmentDraftService(
                AttachmentDraftDependencies(
                    settings=types.SimpleNamespace(upload_staging_dir=temp_dir, dashscope_api_key="test-key", text_llm_model="qwen-plus"),
                    parser=_FakeParser(),
                    oss_client=types.SimpleNamespace(enabled=False),
                    brands=_FakeBrandStore(),
                    brand_products=_FakeBrandProductStore(),
                    brand_knowledge=_FakeBrandKnowledgeStore(
                        rows=[
                            {
                                "knowledge_type": "company_profile",
                                "content_json": json.dumps(
                                    {
                                        "brand_subject_name": "示例企业主体",
                                        "company_intro": "旧公司简介",
                                    },
                                    ensure_ascii=False,
                                ),
                            },
                            {
                                "knowledge_type": "management_team",
                                "content_json": json.dumps([], ensure_ascii=False),
                            },
                            {
                                "knowledge_type": "competitors",
                                "content_json": json.dumps([], ensure_ascii=False),
                            },
                            {
                                "knowledge_type": "authority_honors",
                                "content_json": json.dumps([], ensure_ascii=False),
                            },
                            {
                                "knowledge_type": "customers_cases",
                                "content_json": json.dumps([], ensure_ascii=False),
                            },
                            {
                                "knowledge_type": "sensitive_topics",
                                "content_json": json.dumps({}, ensure_ascii=False),
                            },
                            {
                                "knowledge_type": "attachments",
                                "content_json": json.dumps([], ensure_ascii=False),
                            },
                        ]
                    ),
                    update_knowledge=AsyncMock(),
                    ingest_text_document=AsyncMock(),
                )
            )

            draft_id = "bad_no_existing_competitors"
            draft_dir = Path(temp_dir) / "attachment_parse_drafts" / draft_id
            draft_dir.mkdir(parents=True, exist_ok=True)
            (draft_dir / "draft.json").write_text(
                json.dumps(
                    {
                        "draft_id": draft_id,
                        "brand_name": "示例品牌",
                        "brand_code": "BRAND-001",
                        "attachments": [],
                        "combined_markdown_text": "# 示例品牌 附件预解析草稿",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            candidate_snapshot = {
                "basic_info": {},
                "products": [],
                "company_profile": {},
                "management_team": [],
                "competitors": [
                    {
                        "name": "竞品B",
                        "competitors_description": "新竞品介绍",
                    }
                ],
                "authority_honors": [],
                "customers_cases": [],
                "sensitive_topics": {},
            }

            result = await service.review_changes(
                request=types.SimpleNamespace(
                    brand_name=None,
                    brand_code=None,
                    candidate_snapshot=candidate_snapshot,
                    knowledge_revision="LXKG-SLPP-V1.0.0-20260630010101",
                ),
                draft_id=draft_id,
            )

        self.assertTrue(any(str(item["field_path"]).startswith("competitors.competitors[竞品B]") for item in result["changes"]))

    async def test_review_changes_rejects_stale_knowledge_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = AttachmentDraftService(
                AttachmentDraftDependencies(
                    settings=types.SimpleNamespace(upload_staging_dir=temp_dir, dashscope_api_key="test-key", text_llm_model="qwen-plus"),
                    parser=_FakeParser(),
                    oss_client=types.SimpleNamespace(enabled=False),
                    brands=_FakeBrandStore(),
                    brand_products=_FakeBrandProductStore(),
                    brand_knowledge=_FakeBrandKnowledgeStore(),
                    update_knowledge=AsyncMock(),
                    ingest_text_document=AsyncMock(),
                )
            )

            draft_id = "bad_stale_review"
            draft_dir = Path(temp_dir) / "attachment_parse_drafts" / draft_id
            draft_dir.mkdir(parents=True, exist_ok=True)
            (draft_dir / "draft.json").write_text(
                json.dumps(
                    {
                        "draft_id": draft_id,
                        "brand_name": "示例品牌",
                        "brand_code": "BRAND-001",
                        "attachments": [],
                        "combined_markdown_text": "# 示例品牌 附件预解析草稿",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            request = types.SimpleNamespace(
                brand_name=None,
                brand_code=None,
                candidate_snapshot={"basic_info": {"advantages": "新优势"}},
                knowledge_revision="stale-revision",
            )

            with self.assertRaises(RuntimeError) as ctx:
                await service.review_changes(
                    request=request,
                    draft_id=draft_id,
                )

        self.assertIn("knowledge_revision 不匹配", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
