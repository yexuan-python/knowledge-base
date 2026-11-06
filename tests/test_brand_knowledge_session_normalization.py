from __future__ import annotations

import unittest

from knowledge_base.brand.application import BrandApplicationService


class BrandKnowledgeSessionNormalizationTests(unittest.TestCase):
    def test_conflicts_force_waiting_user_input_and_backend_markdown(self) -> None:
        payload = {
            "status": "completed",
            "working_summary": "模型误报已完成",
            "conflicts": [
                {
                    "conflict_id": "C1",
                    "topic": "协会职务冲突",
                    "description": "两个文件对协会职务描述不一致",
                    "options": [
                        {"option_id": "A", "content": "理事单位", "source_files": ["荣誉.md"]},
                        {"option_id": "B", "content": "副会长单位", "source_files": ["品牌介绍.md"]},
                    ],
                }
            ],
            "conflict_markdown": "模型自己写的 markdown",
            "final_markdown": "# 不应该保留",
        }

        normalized = BrandApplicationService._normalize_session_payload(
            payload,
            allow_completed=True,
        )

        self.assertEqual(normalized["status"], "waiting_user_input")
        self.assertIsNone(normalized["final_markdown"])
        self.assertIn("协会职务冲突", normalized["conflict_markdown"])
        self.assertIn("理事单位", normalized["conflict_markdown"])
        self.assertNotEqual(normalized["conflict_markdown"], "模型自己写的 markdown")

    def test_conflict_normalization_preserves_model_conflict_id_and_severity(self) -> None:
        payload = {
            "status": "waiting_user_input",
            "scan_summary": "发现 1 条硬冲突",
            "conflicts": [
                {
                    "conflict_id": "C-BRAND-001",
                    "topic": "主体名称冲突",
                    "severity": "hard",
                    "description": "两个来源主体名称不一致",
                    "options": [
                        {"option_id": "A", "content": "方案A", "source_files": ["文件A.md"]},
                        {"option_id": "B", "content": "方案B", "source_files": ["文件B.md"]},
                    ],
                }
            ],
        }

        normalized = BrandApplicationService._normalize_session_payload(
            payload,
            allow_completed=False,
        )

        self.assertEqual(normalized["conflicts"][0]["conflict_id"], "C-BRAND-001")
        self.assertEqual(normalized["conflicts"][0]["severity"], "hard")

    def test_completed_requires_no_conflicts_and_final_markdown(self) -> None:
        payload = {
            "status": "completed",
            "working_summary": "已完成整合",
            "conflicts": [],
            "final_markdown": "# Jollybaby 品牌知识库",
        }

        normalized = BrandApplicationService._normalize_session_payload(
            payload,
            allow_completed=True,
        )

        self.assertEqual(normalized["status"], "completed")
        self.assertEqual(normalized["final_markdown"], "# Jollybaby 品牌知识库")
        self.assertIsNone(normalized["conflict_markdown"])


if __name__ == "__main__":
    unittest.main()
