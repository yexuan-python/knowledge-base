from __future__ import annotations

import types
import unittest
from unittest.mock import AsyncMock

from knowledge_base.brand.callback_mapper import format_brand_callback_knowledge_from_snapshot
from knowledge_base.brand_knowledge.application import AttachmentDraftDependencies, AttachmentDraftService

from tests.fakes.brand_flow import (
    FakeBrandKnowledgeStore,
    FakeBrandProductStore,
    FakeBrandStore,
    FakeSettings,
)


class AttachmentConfirmHelperTests(unittest.IsolatedAsyncioTestCase):
    async def test_confirm_callback_filters_stringified_empty_lists(self) -> None:
        payload = format_brand_callback_knowledge_from_snapshot(
            brand={"brand_name": "示例品牌", "industry_id": 1, "other_info": "历史补充信息"},
            knowledge_snapshot={
                "basic_info": {
                    "brand_name": "示例品牌",
                    "customer_service_hotline": "[\"[]\"]",
                    "advantages": "[\"[]\"]",
                    "vision": "['[]']",
                    "other_info": "[]",
                },
                "products": [
                    {
                        "name": "熟饭视频",
                        "target_scenarios": "[{\"title\":\"医疗、法律、教育等等\"}]",
                        "product_advantages": "[\"策略安全合规\", \"规模化高效生产\"]",
                        "service_process": "[{\"step\":\"1\",\"title\":\"需求沟通\"}]",
                        "other_info": "[]",
                    }
                ],
                "company_profile": {
                    "other_info": ["[]"],
                    "store_distribution": "['[]']",
                },
                "management_team": [
                    {
                        "name": "张三",
                        "other_info": "['[]']",
                    }
                ],
                "competitors": [
                    {
                        "name": "竞品A",
                        "competitive_advantages": "['[]']",
                        "comparison_dimensions": ["[]"],
                    },
                    {
                        "name": "竞品B",
                        "strengths": "['渠道广', '价格低']",
                        "aliases": "['竞品B别名', 'Competitor B']",
                        "official_websites": ["https://competitor-b.example.com"],
                        "logo_urls": "['https://img.example.com/competitor-b.png']",
                        "differentiated_positioning": "['[]']",
                    },
                ],
                "authority_honors": [
                    {
                        "title": "高新技术企业",
                        "qualification_proof": ["[]"],
                    }
                ],
            },
        )

        self.assertEqual(payload["basic_info"]["customer_service_hotline"], [])
        self.assertEqual(payload["basic_info"]["extra_info"]["brand_advantage"], [])
        self.assertEqual(payload["basic_info"]["extra_info"]["brand_vision"], [])
        self.assertNotIn("other_info", payload["basic_info"]["extra_info"])
        self.assertEqual(payload["products"][0]["knowledge"]["scenarios"], [{"title": "医疗、法律、教育等等"}])
        self.assertEqual(payload["products"][0]["knowledge"]["advantages"], ["策略安全合规", "规模化高效生产"])
        self.assertEqual(payload["products"][0]["knowledge"]["service_processes"], [{"step": "1", "title": "需求沟通"}])
        self.assertEqual(payload["products"][0]["knowledge"]["other_info"], [])
        self.assertEqual(payload["company_profile"]["other_info"], [])
        self.assertEqual(payload["company_profile"]["store_distribution"], [])
        self.assertEqual(payload["management_team"]["members"][0]["other_info"], [])
        self.assertEqual(payload["competitors"]["competitors"][0]["strengths"], [])
        self.assertEqual(payload["competitors"]["competitors"][0]["comparison_dimensions"], [])
        self.assertEqual(payload["competitors"]["competitors"][1]["strengths"], ["渠道广", "价格低"])
        self.assertEqual(payload["competitors"]["competitors"][1]["aliases"], ["竞品B别名", "Competitor B"])
        self.assertEqual(payload["competitors"]["competitors"][1]["official_websites"], ["https://competitor-b.example.com"])
        self.assertEqual(payload["competitors"]["competitors"][1]["logo_urls"], ["https://img.example.com/competitor-b.png"])
        self.assertEqual(payload["competitors"]["competitors"][1]["differentiated_positioning"], [])
        self.assertEqual(payload["authority_honors"]["honors"][0]["proof_files"], [])

    async def test_confirm_callback_omits_identifier_only_basic_info(self) -> None:
        service = AttachmentDraftService(
            AttachmentDraftDependencies(
                settings=FakeSettings(),
                parser=types.SimpleNamespace(),
                oss_client=types.SimpleNamespace(enabled=False),
                brands=FakeBrandStore(),
                brand_products=FakeBrandProductStore(),
                brand_knowledge=FakeBrandKnowledgeStore(),
                update_knowledge=AsyncMock(),
                ingest_text_document=AsyncMock(),
            )
        )

        payload = service._build_confirm_callback_payload(
            brand={
                "brand_code": "BRAND-001",
                "brand_name": "示例品牌",
                "knowledge_revision": "demo-2026-06-23",
            },
            merged_snapshot={
                "basic_info": {
                    "brand_code": "BRAND-001",
                    "brand_name": "示例品牌",
                    "intro": "历史简介",
                },
            },
            changed_snapshot={
                "basic_info": {
                    "brand_code": "BRAND-001",
                    "brand_name": "示例品牌",
                },
                "attachments": [
                    {
                        "name": "本次附件.pdf",
                        "url": "https://example.com/current.pdf",
                    }
                ],
            },
            knowledge_revision="demo-2026-06-23",
            ai_knowledge_payload=None,
        )

        self.assertNotIn("knowledge_mete", payload)
        self.assertEqual("success", payload["knowledge_markdown_status"])
        self.assertNotIn("basic_info", payload["knowledge"])
        self.assertEqual(
            payload["knowledge"],
            {
                "attachments": {
                    "files": [
                        {
                            "name": "本次附件.pdf",
                            "url": "https://example.com/current.pdf",
                            "type": "",
                            "description": "",
                        }
                    ],
                },
            },
        )

    async def test_confirm_merge_appends_list_fields_and_ignores_empty_array_markers(self) -> None:
        service = AttachmentDraftService(
            AttachmentDraftDependencies(
                settings=FakeSettings(),
                parser=types.SimpleNamespace(),
                oss_client=types.SimpleNamespace(enabled=False),
                brands=FakeBrandStore(),
                brand_products=FakeBrandProductStore(),
                brand_knowledge=FakeBrandKnowledgeStore(),
                update_knowledge=AsyncMock(),
                ingest_text_document=AsyncMock(),
            )
        )

        merged = service._merge_snapshot(
            current_snapshot={
                "competitors": [
                    {
                        "name": "万数科技",
                        "aliases": ["万数", "Wanshu Tech"],
                        "strengths": ["渠道广"],
                        "differentiated_positioning": ["老定位"],
                    }
                ],
                "sensitive_topics": {
                    "forbidden_words": ["禁词A"],
                },
            },
            candidate_snapshot={
                "competitors": [
                    {
                        "name": "万数科技",
                        "aliases": "['万数科技公司', 'Wanshu Tech']",
                        "strengths": "['价格低']",
                        "differentiated_positioning": "['[]']",
                    }
                ],
                "sensitive_topics": {
                    "forbidden_words": "['禁词A', '禁词B']",
                },
            },
        )

        self.assertEqual(
            merged["competitors"][0]["aliases"],
            ["万数", "Wanshu Tech", "万数科技公司"],
        )
        self.assertEqual(merged["competitors"][0]["strengths"], ["渠道广", "价格低"])
        self.assertEqual(merged["competitors"][0]["differentiated_positioning"], ["老定位"])
        self.assertEqual(merged["sensitive_topics"]["forbidden_words"], ["禁词A", "禁词B"])
