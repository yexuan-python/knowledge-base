from __future__ import annotations

import unittest

from knowledge_base.brand import knowledge_extraction as brand_knowledge_extraction

from tests.fakes.brand_flow import FakeSettings


class BrandCompetitorSummaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_summarize_competitor_sections_into_snapshot_merges_clean_summary(self) -> None:
        saved_call = brand_knowledge_extraction.call_text_llm_json

        def fake_call(prompt: str, *, settings):
            self.assertIn("4.3 竞品多维对比", prompt)
            self.assertIn("4.4 优劣势对比", prompt)
            return {
                "comparison_dimensions": ["面料体感", "安全功能", "价格定位"],
                "differentiated_positioning": ["原纱冰感面料体验更强", "本土快反补码更及时"],
            }

        brand_knowledge_extraction.call_text_llm_json = fake_call
        try:
            snapshot = await brand_knowledge_extraction._summarize_competitor_sections_into_snapshot(
                {
                    "competitors": [{"name": "竞品A"}],
                    "other_info": [
                        {"title": "4.3 竞品多维对比", "content": "| 对比维度 | 校园及第 |\n| --- | --- |\n| 面料体感 | 原纱冰感 |"},
                        {"title": "4.4 优劣势对比", "content": "* **差异化\"护城河\"**:本土快反"},
                        {"title": "五、高频问答 FAQ", "content": "Q:支持补购吗?\nA:支持。"},
                    ],
                },
                brand_name="校园及第",
                settings=FakeSettings(),
            )
        finally:
            brand_knowledge_extraction.call_text_llm_json = saved_call

        self.assertEqual(
            snapshot["competitors"][0]["comparison_dimensions"],
            "面料体感；安全功能；价格定位",
        )
        self.assertEqual(
            snapshot["competitors"][0]["differentiated_positioning"],
            "原纱冰感面料体验更强；本土快反补码更及时",
        )
        self.assertEqual(
            snapshot["other_info"],
            [{"title": "五、高频问答 FAQ", "content": "Q:支持补购吗?\nA:支持。"}],
        )

    async def test_summarize_competitor_sections_into_snapshot_keeps_raw_sections_on_failure(self) -> None:
        saved_call = brand_knowledge_extraction.call_text_llm_json

        def fake_call(prompt: str, *, settings):
            raise TimeoutError("llm timeout")

        brand_knowledge_extraction.call_text_llm_json = fake_call
        try:
            snapshot = await brand_knowledge_extraction._summarize_competitor_sections_into_snapshot(
                {
                    "competitors": [{"name": "竞品A"}],
                    "other_info": [
                        {"title": "4.3 竞品多维对比", "content": "| 对比维度 | 校园及第 |\n| --- | --- |\n| 面料体感 | 原纱冰感 |"},
                        {"title": "4.4 优劣势对比", "content": "* **差异化\"护城河\"**:本土快反"},
                    ],
                },
                brand_name="校园及第",
                settings=FakeSettings(),
            )
        finally:
            brand_knowledge_extraction.call_text_llm_json = saved_call

        self.assertEqual(snapshot["competitors"][0].get("comparison_dimensions"), None)
        self.assertEqual(snapshot["competitors"][0].get("differentiated_positioning"), None)
        self.assertEqual(
            [item["title"] for item in snapshot["other_info"]],
            ["4.3 竞品多维对比", "4.4 优劣势对比"],
        )

    async def test_summarize_competitor_sections_into_snapshot_skips_when_sections_absent(self) -> None:
        saved_call = brand_knowledge_extraction.call_text_llm_json

        def fake_call(prompt: str, *, settings):
            raise AssertionError("LLM should not be called when 4.3/4.4 are absent")

        brand_knowledge_extraction.call_text_llm_json = fake_call
        try:
            snapshot = await brand_knowledge_extraction._summarize_competitor_sections_into_snapshot(
                {
                    "competitors": [{"name": "竞品A"}],
                    "other_info": [{"title": "五、高频问答 FAQ", "content": "Q:支持补购吗?\nA:支持。"}],
                },
                brand_name="校园及第",
                settings=FakeSettings(),
            )
        finally:
            brand_knowledge_extraction.call_text_llm_json = saved_call

        self.assertEqual(
            snapshot["other_info"],
            [{"title": "五、高频问答 FAQ", "content": "Q:支持补购吗?\nA:支持。"}],
        )
        self.assertEqual(snapshot["competitors"][0].get("comparison_dimensions"), None)
        self.assertEqual(snapshot["competitors"][0].get("differentiated_positioning"), None)
