from __future__ import annotations

import types
import unittest
from unittest.mock import AsyncMock

from knowledge_base.brand.application import BrandApplicationDependencies, BrandApplicationService
from knowledge_base.brand.schemas import KnowledgeBasicInfo, KnowledgeUpdateRequest

from tests.fakes.brand_flow import (
    FakeBrandKnowledgeStore,
    FakeBrandProductStore,
    FakeBrandStore,
    FakeDocumentCategoryStore,
    FakeIndustryStore,
    FakeSettings,
)


def _build_application(*, brand_knowledge, build_next_brand_full_knowledge) -> BrandApplicationService:
    return BrandApplicationService(
        BrandApplicationDependencies(
            settings=FakeSettings(),
            brands=FakeBrandStore(knowledge_revision="LXKG-SLPP-V1.0.0-20260630010101"),
            brand_products=FakeBrandProductStore(),
            brand_knowledge=brand_knowledge,
            industries=FakeIndustryStore(),
            brand_knowledge_sessions=types.SimpleNamespace(),
            document_registry=None,
            document_categories=FakeDocumentCategoryStore(),
            fact_relations=None,
            store=None,
            document_app=None,
            delete_document=AsyncMock(),
            get_full_text=lambda _document_id: None,
            ingest_staged_file=AsyncMock(),
            ingest_from_url=AsyncMock(),
            delete_document_by_attachment_name=AsyncMock(),
            build_next_brand_full_knowledge=build_next_brand_full_knowledge,
        )
    )


class BrandKnowledgeUpdateDeletionTests(unittest.IsolatedAsyncioTestCase):
    async def test_knowledge_update_clears_structured_sections_and_uses_delete_reason(self) -> None:
        brand_knowledge = FakeBrandKnowledgeStore()
        brand_knowledge.knowledge_rows = [
            {
                "knowledge_type": "competitors",
                "content_json": [
                    {"name": "竞品A", "introduction": "老竞品A"},
                    {"name": "竞品B", "introduction": "老竞品B"},
                ],
            },
            {
                "knowledge_type": "authority_honors",
                "content_json": [
                    {"title": "奖项A", "year": "2024"},
                ],
            },
        ]
        captured_build_calls: list[dict[str, object]] = []

        async def fake_build_next_brand_full_knowledge(**kwargs):
            captured_build_calls.append(kwargs)
            return {
                "knowledge_oss_url_md": "https://oss.example.com/ai_knowledge/delete.md",
                "knowledge_oss_url_pdf": "https://oss.example.com/ai_knowledge/delete.pdf",
            }

        application = _build_application(
            brand_knowledge=brand_knowledge,
            build_next_brand_full_knowledge=fake_build_next_brand_full_knowledge,
        )

        request = KnowledgeUpdateRequest(
            basic_info=KnowledgeBasicInfo(
                brand_name="示例品牌",
                brand_code="BRAND-001",
            ),
            competitors=[],
            authority_honors=[],
        )

        result = await application.update_knowledge(request)

        self.assertEqual(result["status"], "success")
        self.assertEqual(sorted(result["deleted_sections"]), ["authority_honors", "competitors"])
        self.assertRegex(result["knowledge_revision"], r"^LXKG-SLPP-V1\.0\.1-\d{14}$")
        self.assertEqual(
            brand_knowledge.deleted_knowledge_types,
            [
                (1, "competitors"),
                (1, "authority_honors"),
            ],
        )
        self.assertEqual(len(captured_build_calls), 1)
        self.assertEqual(captured_build_calls[0]["update_reason"], "knowledge_delete")
        self.assertEqual(
            sorted(captured_build_calls[0]["deleted_sections"]),
            ["authority_honors", "competitors"],
        )
        structured_delta = str(captured_build_calls[0]["structured_knowledge_markdown"])
        self.assertIn("本次明确删除或收缩的 section", structured_delta)
        self.assertIn("competitors", structured_delta)
        self.assertIn("authority_honors", structured_delta)
        self.assertIn("change_type：`delete`", structured_delta)
        self.assertNotIn("明星产品", structured_delta)
        self.assertEqual(
            result["knowledge_mete"],
            {
                "version": result["knowledge_revision"],
                "oss_url_md": "https://oss.example.com/ai_knowledge/delete.md",
                "oss_url_pdf": "https://oss.example.com/ai_knowledge/delete.pdf",
            },
        )

    async def test_knowledge_update_detects_partial_structured_deletion_and_overwrites_section(self) -> None:
        brand_knowledge = FakeBrandKnowledgeStore()
        brand_knowledge.knowledge_rows = [
            {
                "knowledge_type": "competitors",
                "content_json": [
                    {"name": "竞品A", "introduction": "保留"},
                    {"name": "竞品B", "introduction": "删除"},
                ],
            }
        ]
        captured_build_calls: list[dict[str, object]] = []

        async def fake_build_next_brand_full_knowledge(**kwargs):
            captured_build_calls.append(kwargs)
            return {
                "knowledge_oss_url_md": "https://oss.example.com/ai_knowledge/partial-delete.md",
                "knowledge_oss_url_pdf": "https://oss.example.com/ai_knowledge/partial-delete.pdf",
            }

        application = _build_application(
            brand_knowledge=brand_knowledge,
            build_next_brand_full_knowledge=fake_build_next_brand_full_knowledge,
        )

        request = KnowledgeUpdateRequest(
            basic_info=KnowledgeBasicInfo(
                brand_name="示例品牌",
                brand_code="BRAND-001",
            ),
            competitors=[
                {"name": "竞品A", "introduction": "保留"},
            ],
        )

        result = await application.update_knowledge(request)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["deleted_sections"], ["competitors"])
        competitor_upserts = [
            item for item in brand_knowledge.last_knowledge_upserts
            if item[1] == "competitors"
        ]
        self.assertEqual(
            competitor_upserts[-1][3],
            [
                {
                    "name": "竞品A",
                    "aliases": [],
                    "introduction": "保留",
                    "official_websites": [],
                    "logo_urls": [],
                    "strengths": [],
                    "differentiated_positioning": [],
                    "comparison_dimensions": [],
                    "other_info": [],
                }
            ],
        )
        self.assertEqual(captured_build_calls[0]["update_reason"], "knowledge_delete")
        self.assertEqual(captured_build_calls[0]["deleted_sections"], ["competitors"])
        structured_delta = str(captured_build_calls[0]["structured_knowledge_markdown"])
        self.assertIn("competitors", structured_delta)
        self.assertIn("竞品A", structured_delta)
        self.assertNotIn("竞品B", structured_delta)
        self.assertIn("change_type：`delete`", structured_delta)
