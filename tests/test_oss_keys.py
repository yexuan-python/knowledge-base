import os
import unittest
from unittest.mock import patch

from knowledge_base.shared.utils.oss_keys import (
    apply_oss_test_prefix,
    build_fulltext_object_key,
    build_original_object_key,
    object_key_matches_current_oss_prefix,
    sanitize_oss_segment,
)


class OssKeysTest(unittest.TestCase):
    def test_apply_oss_test_prefix_returns_object_key(self):
        with patch.dict(os.environ, {"OSS_OBJECT_KEY_PREFIX": ""}):
            self.assertEqual(
                apply_oss_test_prefix("瑞华智能/ai_knowledge/file.md"),
                "瑞华智能/ai_knowledge/file.md",
            )

    def test_apply_oss_test_prefix_uses_env_prefix(self):
        with patch.dict(os.environ, {"OSS_OBJECT_KEY_PREFIX": "/test/"}):
            self.assertEqual(
                apply_oss_test_prefix("瑞华智能/ai_knowledge/file.md"),
                "test/瑞华智能/ai_knowledge/file.md",
            )

    def test_build_object_keys_do_not_raise(self):
        with patch.dict(os.environ, {"OSS_OBJECT_KEY_PREFIX": ""}):
            self.assertEqual(
                build_original_object_key(
                    category="瑞华智能",
                    subcategory=None,
                    filename="品牌AI知识库.md",
                    document_id="doc-1",
                    converted_version=2,
                ),
                "瑞华智能/original/品牌AI知识库.md/V2.md",
            )
            self.assertEqual(
                build_fulltext_object_key(
                    category="瑞华智能",
                    subcategory="产品线",
                    filename="品牌AI知识库.md",
                    document_id="doc-1",
                    converted_version=2,
                ),
                "瑞华智能/converted/产品线/品牌AI知识库.md/V2.md",
            )

    def test_sanitize_oss_segment_replaces_slashes(self):
        self.assertEqual(sanitize_oss_segment(" A/B\\C ", default="x"), "A_B_C")
        self.assertEqual(sanitize_oss_segment(" / ", default="x"), "x")

    def test_object_key_matches_current_oss_prefix_uses_env_prefix(self):
        with patch.dict(os.environ, {"OSS_OBJECT_KEY_PREFIX": "test"}):
            self.assertTrue(object_key_matches_current_oss_prefix("test/瑞华智能/ai_knowledge/file.md"))
            self.assertFalse(object_key_matches_current_oss_prefix("瑞华智能/ai_knowledge/file.md"))
            self.assertFalse(object_key_matches_current_oss_prefix("prod/瑞华智能/ai_knowledge/file.md"))

    def test_object_key_matches_current_oss_prefix_without_env_rejects_known_env_prefixes(self):
        with patch.dict(os.environ, {"OSS_OBJECT_KEY_PREFIX": ""}):
            self.assertTrue(object_key_matches_current_oss_prefix("瑞华智能/ai_knowledge/file.md"))
            self.assertFalse(object_key_matches_current_oss_prefix("test/瑞华智能/ai_knowledge/file.md"))
            self.assertFalse(object_key_matches_current_oss_prefix("prod/瑞华智能/ai_knowledge/file.md"))


if __name__ == "__main__":
    unittest.main()
