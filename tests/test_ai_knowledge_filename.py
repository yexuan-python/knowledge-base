from __future__ import annotations

import unittest

from knowledge_base.brand.ai_knowledge_filename import (
    ParsedAiKnowledgeFilename,
    is_ai_knowledge_filename,
    parse_ai_knowledge_filename,
)


class AiKnowledgeFilenameTests(unittest.TestCase):
    def test_parse_accepts_supported_pattern(self) -> None:
        parsed = parse_ai_knowledge_filename("【示例品牌】品牌AI知识库_V12_20260715.docx")

        self.assertIsInstance(parsed, ParsedAiKnowledgeFilename)
        assert parsed is not None
        self.assertEqual("示例品牌", parsed.brand_name)
        self.assertEqual(12, parsed.version_no)
        self.assertEqual("20260715", parsed.knowledge_date)
        self.assertEqual("docx", parsed.extension)
        self.assertEqual(".docx", parsed.suffix)

    def test_parse_uses_basename_and_supports_corner_quotes(self) -> None:
        parsed = parse_ai_knowledge_filename("/tmp/uploads/「品牌A」品牌AI知识库_V1_20260101.PDF")

        assert parsed is not None
        self.assertEqual("品牌A", parsed.brand_name)
        self.assertEqual("PDF", parsed.extension)
        self.assertEqual("pdf", parsed.normalized_extension)

    def test_parse_rejects_invalid_pattern(self) -> None:
        self.assertIsNone(parse_ai_knowledge_filename("品牌知识库_V1_20260715.md"))
        self.assertFalse(is_ai_knowledge_filename("普通附件.pdf"))


if __name__ == "__main__":
    unittest.main()
