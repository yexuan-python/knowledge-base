from __future__ import annotations

import types
import unittest

from knowledge_base.brand import knowledge_extraction as brand_knowledge_extraction

from tests.fakes.brand_flow import FakeBrandStore


class BrandBasicInfoBackfillTests(unittest.TestCase):
    def test_full_markdown_backfill_basic_info_updates_brand_table_with_incoming_long_text_fields(self) -> None:
        service = types.SimpleNamespace(_brands=FakeBrandStore())
        brand = {
            "brand_code": "BRAND-001",
            "brand_name": "示例品牌",
            "brand_alias": "旧别名",
            "brand_logo": "https://example.com/old-logo.png",
            "website": "[\"https://old.example.com\"]",
            "industry_id": 12,
            "customer_service_hotline": "[\"400-OLD\"]",
            "official_wechat_account": "old_wechat",
            "intro": "旧简介",
            "email": "old@example.com",
            "brand_enterprise_entity": "旧主体",
            "business_license_image_path": "https://example.com/old-license.png",
            "english_name": "Old Brand",
            "positioning": "[\"旧定位A\", \"旧定位B\"]",
            "advantages": "[\"旧优势A\", \"旧优势B\"]",
            "mission": "[\"旧使命A\", \"旧使命B\"]",
            "vision": "[\"旧愿景A\", \"旧愿景B\"]",
            "target_regions_json": "[\"旧区域\"]",
            "other_info": "旧补充信息",
        }
        extracted_basic_info = {
            "brand_alias": "新别名",
            "brand_logo": "https://example.com/new-logo.png",
            "website": ["https://new.example.com"],
            "industry_id": 34,
            "customer_service_hotline": ["400-NEW"],
            "official_wechat_account": "new_wechat",
            "intro": "新简介",
            "email": "new@example.com",
            "brand_enterprise_entity": "新主体",
            "business_license_image_path": "https://example.com/new-license.png",
            "english_name": "New Brand",
            "positioning": ["新定位A，新定位B"],
            "advantages": ["新优势A，新优势B"],
            "mission": ["新使命A，新使命B"],
            "vision": ["新愿景A，新愿景B"],
            "target_regions": ["新区域"],
            "other_info": "新补充信息",
        }

        brand_knowledge_extraction._apply_extracted_basic_info_to_brand(
            service,
            brand=brand,
            extracted_basic_info=extracted_basic_info,
        )

        payload = service._brands.last_upsert_brand_kwargs
        self.assertEqual(payload["brand_alias"], "旧别名")
        self.assertEqual(payload["brand_logo"], "https://example.com/old-logo.png")
        self.assertEqual(
            payload["website"],
            "[\"https://old.example.com\", \"https://new.example.com\"]",
        )
        self.assertEqual(payload["industry_id"], 12)
        self.assertEqual(payload["customer_service_hotline"], ["400-NEW"])
        self.assertEqual(payload["official_wechat_account"], "new_wechat")
        self.assertEqual(payload["intro"], "旧简介")
        self.assertEqual(payload["email"], "new@example.com")
        self.assertEqual(payload["brand_enterprise_entity"], "新主体")
        self.assertEqual(payload["business_license_image_path"], "https://example.com/new-license.png")
        self.assertEqual(payload["english_name"], "New Brand")
        self.assertEqual(payload["positioning"], ["新定位A，新定位B"])
        self.assertEqual(payload["advantages"], ["新优势A，新优势B"])
        self.assertEqual(payload["mission"], ["新使命A，新使命B"])
        self.assertEqual(payload["vision"], ["新愿景A，新愿景B"])
        self.assertEqual(payload["target_regions"], ["新区域"])
        self.assertEqual(payload["other_info"], "新补充信息")

    def test_full_markdown_backfill_basic_info_uses_incoming_intro_when_existing_intro_is_empty(self) -> None:
        service = types.SimpleNamespace(_brands=FakeBrandStore())
        brand = {
            "brand_code": "BRAND-001",
            "brand_name": "示例品牌",
            "intro": "",
        }
        extracted_basic_info = {
            "intro": "新简介",
        }

        brand_knowledge_extraction._apply_extracted_basic_info_to_brand(
            service,
            brand=brand,
            extracted_basic_info=extracted_basic_info,
        )

        payload = service._brands.last_upsert_brand_kwargs
        self.assertEqual(payload["intro"], "新简介")

    def test_full_markdown_backfill_basic_info_ignores_stringified_empty_list_other_info(self) -> None:
        service = types.SimpleNamespace(_brands=FakeBrandStore())
        brand = {
            "brand_code": "BRAND-001",
            "brand_name": "示例品牌",
            "other_info": "旧补充信息",
        }
        extracted_basic_info = {
            "other_info": '["[]"]',
        }

        brand_knowledge_extraction._apply_extracted_basic_info_to_brand(
            service,
            brand=brand,
            extracted_basic_info=extracted_basic_info,
        )

        payload = service._brands.last_upsert_brand_kwargs
        self.assertEqual(payload["other_info"], "旧补充信息")

    def test_full_markdown_backfill_basic_info_normalizes_and_dedupes_websites(self) -> None:
        service = types.SimpleNamespace(_brands=FakeBrandStore())
        brand = {
            "brand_code": "BRAND-001",
            "brand_name": "示例品牌",
            "website": "[\"HTTPS://WWW.DINOSAURODYSSEY.COM/?utm_source=wechat#top\"]",
        }
        extracted_basic_info = {
            "website": [
                "https://www.dinosaurodyssey.com/",
                "https://www.dinosaurodyssey.com/?utm_medium=social",
            ],
        }

        brand_knowledge_extraction._apply_extracted_basic_info_to_brand(
            service,
            brand=brand,
            extracted_basic_info=extracted_basic_info,
        )

        payload = service._brands.last_upsert_brand_kwargs
        self.assertEqual(payload["website"], "[\"https://www.dinosaurodyssey.com\"]")
