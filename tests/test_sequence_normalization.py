from __future__ import annotations

import unittest

from knowledge_base.shared.utils import (
    is_effective_empty_sequence,
    normalize_text_sequence,
    parse_jsonish_literal,
)


class SequenceNormalizationTests(unittest.TestCase):
    def test_parse_jsonish_literal_supports_nested_stringified_empty_list(self) -> None:
        self.assertEqual(parse_jsonish_literal('"[]"'), "[]")
        self.assertEqual(parse_jsonish_literal('["[]"]'), ["[]"])
        self.assertEqual(parse_jsonish_literal("['[]']"), ["[]"])

    def test_is_effective_empty_sequence_recognizes_nested_empty_markers(self) -> None:
        self.assertTrue(is_effective_empty_sequence("[]"))
        self.assertTrue(is_effective_empty_sequence('"[]"'))
        self.assertTrue(is_effective_empty_sequence('["[]"]'))
        self.assertTrue(is_effective_empty_sequence(["[]"]))
        self.assertTrue(is_effective_empty_sequence(['"[]"']))
        self.assertFalse(is_effective_empty_sequence("400-800-9000"))

    def test_normalize_text_sequence_drops_nested_empty_markers(self) -> None:
        self.assertEqual(normalize_text_sequence('"[]"'), [])
        self.assertEqual(normalize_text_sequence('["[]"]'), [])
        self.assertEqual(normalize_text_sequence(['"[]"']), [])
        self.assertEqual(normalize_text_sequence(["400-800-9000"]), ["400-800-9000"])

    def test_normalize_text_sequence_respects_configured_split_separators(self) -> None:
        self.assertEqual(
            normalize_text_sequence(
                "华北、华东,华南\n华中；华西",
                split_separators=("\n",),
            ),
            ["华北、华东,华南", "华中；华西"],
        )


if __name__ == "__main__":
    unittest.main()
