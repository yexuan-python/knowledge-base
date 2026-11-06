from __future__ import annotations

import unittest
import types

from knowledge_base.ingest.application.document_pipeline import ParsedDocumentContext, _enforce_watermark_policy
from knowledge_base.ingest.infrastructure import (
    ParsedDocument,
    _is_single_page_repeated_watermark,
    analyze_pdf_watermark_phrases,
    detect_markdown_watermark_residue,
    remove_markdown_watermark_residue,
)


class PdfWatermarkTests(unittest.IsolatedAsyncioTestCase):
    def test_repeated_keyword_phrases_are_marked_as_suspected(self) -> None:
        report = analyze_pdf_watermark_phrases(
            [
                {"机密", "第一页正文"},
                {"机密", "第二页正文"},
                {"机密", "第三页正文"},
            ]
        )

        self.assertTrue(report.suspected)
        self.assertGreaterEqual(len(report.candidates), 1)
        self.assertEqual(report.candidates[0].phrase, "机密")

    def test_non_keyword_body_lines_are_not_marked_as_watermark(self) -> None:
        report = analyze_pdf_watermark_phrases(
            [
                {"第一章 产品介绍", "品牌故事"},
                {"第一章 产品介绍", "市场分析"},
                {"第一章 产品介绍", "总结"},
            ]
        )

        self.assertFalse(report.suspected)

    def test_markdown_residue_detects_repeated_candidate_lines(self) -> None:
        residue = detect_markdown_watermark_residue(
            "机密\n\n这里是正文\n\n机密\n\n更多正文",
            ["机密"],
        )

        self.assertTrue(residue.has_residue)
        self.assertIn("机密", residue.matched_phrases)

    def test_markdown_residue_passes_when_candidate_disappears(self) -> None:
        residue = detect_markdown_watermark_residue(
            "# 标题\n\n这里是正常正文内容，没有残留水印。",
            ["机密"],
        )

        self.assertFalse(residue.has_residue)

    def test_markdown_residue_accepts_metadata_string_candidates(self) -> None:
        residue = detect_markdown_watermark_residue(
            "CONFIDENTIAL\n\n这里是正文",
            [" confidential "],
        )

        self.assertTrue(residue.has_residue)
        self.assertEqual(residue.matched_phrases, (" confidential ",))

    def test_remove_markdown_watermark_residue_keeps_body_content(self) -> None:
        cleaned = remove_markdown_watermark_residue(
            "# 产品介绍\n\n内部资料,请勿外传\n\n这里是正文\n\n内部资料,请勿外传",
            ["内部资料,请勿外传"],
        )

        self.assertNotIn("内部资料,请勿外传", cleaned)
        self.assertIn("# 产品介绍", cleaned)
        self.assertIn("这里是正文", cleaned)

    def test_single_page_repeated_watermark_tokens_are_marked_as_suspected(self) -> None:
        page_words = (
            ["仅", "供", "g", "e", "o", "优", "化", "服", "务", "项", "目", "使", "用", "有", "效", "期", "至", "再", "次", "复", "印", "无", "效"]
            * 8
        )

        self.assertTrue(_is_single_page_repeated_watermark(page_words))

    def test_single_page_normal_words_are_not_marked_as_suspected(self) -> None:
        page_words = [
            "专利",
            "名称",
            "可调节多功能玩具固定夹",
            "申请日",
            "申请人",
            "发明人",
            "中华人民共和国国家知识产权局",
        ] * 3

        self.assertFalse(_is_single_page_repeated_watermark(page_words))

    async def test_watermark_policy_removes_residue_instead_of_failing(self) -> None:
        metadata = {"category": "示例品牌", "file_hash": "hash-1"}
        parsed_ctx = ParsedDocumentContext(
            parsed=ParsedDocument(
                text="内部资料,请勿外传\n\n这里是正文",
                markdown_text="# 标题\n\n内部资料,请勿外传\n\n这里是正文",
                source_name="demo.pdf",
                source_type="pdf",
                metadata={
                    "parser_backend": "docmind",
                    "pdf_watermark_suspected": True,
                    "pdf_watermark_candidates": ["内部资料,请勿外传"],
                },
            ),
            suffix=".pdf",
            converted_version=1,
            parsed_text="内部资料,请勿外传\n\n这里是正文",
            parsed_markdown_text="# 标题\n\n内部资料,请勿外传\n\n这里是正文",
            effective_source_type="pdf",
            metadata={},
            original_file_key="original/demo.pdf",
            fulltext_key="converted/demo.md",
        )

        cleaned_text, cleaned_markdown = await _enforce_watermark_policy(
            types.SimpleNamespace(_document_registry=types.SimpleNamespace()),
            filename="demo.pdf",
            parsed_ctx=parsed_ctx,
            effective_metadata=metadata,
            uploaded_original_file_key=None,
        )

        self.assertNotIn("内部资料,请勿外传", cleaned_text)
        self.assertNotIn("内部资料,请勿外传", cleaned_markdown)
        self.assertIn("这里是正文", cleaned_text)
        self.assertIn("# 标题", cleaned_markdown)
        self.assertTrue(metadata["pdf_watermark_removed"])
        self.assertEqual(metadata["pdf_watermark_removed_candidates"], ["内部资料,请勿外传"])


if __name__ == "__main__":
    unittest.main()
