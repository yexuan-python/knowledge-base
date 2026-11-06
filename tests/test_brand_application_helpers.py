from __future__ import annotations

import unittest

from knowledge_base.brand.application.service import BrandApplicationService


class BrandApplicationHelperTests(unittest.TestCase):
    def test_normalize_attachment_entries_dedupes_by_url_and_keeps_last_item(self) -> None:
        self.assertEqual(
            BrandApplicationService._normalize_attachment_entries(
                [
                    {"name": "旧展示名.pdf", "url": "https://example.com/brand.pdf"},
                    {"name": "另一个附件.pdf", "url": "https://example.com/other.pdf"},
                    {"name": "新展示名.pdf", "url": "https://example.com/brand.pdf"},
                ]
            ),
            [
                {"name": "另一个附件.pdf", "url": "https://example.com/other.pdf"},
                {"name": "新展示名.pdf", "url": "https://example.com/brand.pdf"},
            ],
        )

    def test_log_structured_update_does_not_log_delta_body(self) -> None:
        application = BrandApplicationService.__new__(BrandApplicationService)

        with self.assertLogs("knowledge_base.brand.application.brand_update_followup", level="DEBUG") as captured_logs:
            application._log_structured_update(
                resolved_brand_id=1,
                brand_code="BRAND-001",
                brand_name="示例品牌",
                revision_should_bump=True,
                updated_sections=["brands"],
                deleted_sections=[],
                structured_update_entries=[
                    {
                        "section": "brands",
                        "title": "品牌基础信息",
                        "action": "update",
                        "content": "SHOULD_NOT_APPEAR_IN_DEBUG_LOGS",
                    }
                ],
                structured_change_details=[
                    {
                        "section": "brands",
                        "title": "品牌基础信息",
                        "action": "update",
                        "before": {"intro": "旧简介"},
                        "after": {"intro": "新简介"},
                    }
                ],
                structured_update_markdown="# 品牌基础信息\nSHOULD_NOT_APPEAR_IN_DEBUG_LOGS",
                structured_update_mode="update",
            )

        log_text = "\n".join(captured_logs.output)
        self.assertIn("structured_entries_count=1", log_text)
        self.assertIn("structured_changes_count=1", log_text)
        self.assertIn("structured_markdown_chars=", log_text)
        self.assertNotIn("SHOULD_NOT_APPEAR_IN_DEBUG_LOGS", log_text)
        self.assertNotIn("旧简介", log_text)
        self.assertNotIn("新简介", log_text)
