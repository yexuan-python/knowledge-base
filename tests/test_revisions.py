from __future__ import annotations

import importlib
import sys
import types
import unittest

from tests._stub_utils import module_available, ensure_stub_module


def _install_pypinyin_stub() -> None:
    if module_available("pypinyin"):
        return

    stub = ensure_stub_module("pypinyin")
    if stub is None:
        return

    class _Style:
        FIRST_LETTER = "FIRST_LETTER"

    char_map = {
        "金": "j",
        "牌": "p",
        "家": "j",
        "居": "j",
        "溪": "x",
        "谷": "g",
        "留": "l",
        "香": "x",
        "示": "s",
        "例": "l",
        "品": "p",
    }

    def lazy_pinyin(value, style=None, errors=None):
        tokens = []
        for ch in value:
            if ch in char_map:
                tokens.append(char_map[ch])
            elif ch.isascii() and ch.isalnum():
                tokens.append(ch)
            elif errors is not None:
                tokens.extend(errors(ch))
        return tokens

    stub.Style = _Style
    stub.lazy_pinyin = lazy_pinyin
    sys.modules["pypinyin"] = stub


_install_pypinyin_stub()
revisions = importlib.import_module("knowledge_base.shared.utils.revisions")
revisions = importlib.reload(revisions)


class KnowledgeRevisionTests(unittest.TestCase):
    def test_build_brand_abbr_uses_chinese_initials(self) -> None:
        self.assertEqual(
            revisions.build_brand_abbr(brand_name="金牌家居"),
            "JPJJ",
        )
        self.assertEqual(
            revisions.build_brand_abbr(brand_name="溪谷留香"),
            "XGLX",
        )

    def test_build_knowledge_revision_initializes_new_format_from_legacy_revision(self) -> None:
        revision = revisions.build_knowledge_revision(
            brand_name="金牌家居",
            current_revision="brand-001-20260623154510",
            change_type=revisions.KNOWLEDGE_REVISION_CHANGE_ATTACHMENT,
        )

        self.assertRegex(revision, r"^LXKG-JPJJ-V1\.0\.0-\d{14}$")

    def test_build_knowledge_revision_manual_rolls_patch_into_minor(self) -> None:
        revision = revisions.build_knowledge_revision(
            brand_name="示例品牌",
            current_revision="LXKG-SLPP-V1.0.9-20260630010101",
            change_type=revisions.KNOWLEDGE_REVISION_CHANGE_MANUAL,
        )

        self.assertRegex(revision, r"^LXKG-SLPP-V1\.1\.0-\d{14}$")

    def test_build_knowledge_revision_attachment_rolls_minor_into_major(self) -> None:
        revision = revisions.build_knowledge_revision(
            brand_name="示例品牌",
            current_revision="LXKG-SLPP-V1.9.4-20260630010101",
            change_type=revisions.KNOWLEDGE_REVISION_CHANGE_ATTACHMENT,
        )

        self.assertRegex(revision, r"^LXKG-SLPP-V2\.0\.0-\d{14}$")


if __name__ == "__main__":
    unittest.main()
