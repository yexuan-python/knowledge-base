from __future__ import annotations

import unittest

from knowledge_base.brand_knowledge.ai.rounds import _apply_brand_knowledge_patch_operations


class BrandKnowledgePatchApplyTests(unittest.TestCase):
    def test_empty_operations_return_base_markdown_unchanged(self) -> None:
        base_markdown = "# 品牌概述\n\n旧内容。"

        result = _apply_brand_knowledge_patch_operations(
            base_markdown=base_markdown,
            operations=[],
        )

        self.assertEqual(result, base_markdown)

    def test_insert_after_section_places_content_after_complete_target_section(self) -> None:
        base_markdown = (
            "# 一、品牌概述\n\n旧介绍。\n\n"
            "# 二、服务介绍\n\n旧服务。\n\n"
            "## 2.1 子服务\n\n子服务说明。\n\n"
            "# 三、后续重要内容\n\n这段尾部必须保留。"
        )

        result = _apply_brand_knowledge_patch_operations(
            base_markdown=base_markdown,
            operations=[
                {
                    "op": "insert_after_section",
                    "target_heading": "# 二、服务介绍",
                    "content": "# 二点五、插入章节\n\n新增插入内容。",
                }
            ],
        )

        self.assertEqual(
            result,
            (
                "# 一、品牌概述\n\n旧介绍。\n\n"
                "# 二、服务介绍\n\n旧服务。\n\n"
                "## 2.1 子服务\n\n子服务说明。\n\n"
                "# 二点五、插入章节\n\n新增插入内容。\n\n"
                "# 三、后续重要内容\n\n这段尾部必须保留。"
            ),
        )

    def test_target_heading_is_trimmed_before_matching(self) -> None:
        result = _apply_brand_knowledge_patch_operations(
            base_markdown="# 一、品牌概述\n\n旧介绍。\n\n# 二、服务介绍\n\n旧服务。",
            operations=[
                {
                    "op": "replace_section",
                    "target_heading": "  # 一、品牌概述  ",
                    "content": "新介绍。",
                }
            ],
        )

        self.assertEqual(result, "# 一、品牌概述\n\n新介绍。\n\n# 二、服务介绍\n\n旧服务。")

    def test_delete_section_does_not_require_content(self) -> None:
        result = _apply_brand_knowledge_patch_operations(
            base_markdown="# 品牌概述\n\n旧内容。\n\n# 待删除章节\n\n删除我。\n\n# 保留章节\n\n保留我。",
            operations=[
                {
                    "op": "delete_section",
                    "target_heading": "# 待删除章节",
                    "content": "",
                }
            ],
        )

        self.assertEqual(result, "# 品牌概述\n\n旧内容。\n\n# 保留章节\n\n保留我。")

    def test_non_object_operation_raises_clear_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "补丁操作必须是 JSON 对象"):
            _apply_brand_knowledge_patch_operations(
                base_markdown="# 品牌概述\n\n旧内容。",
                operations=["replace_section"],  # type: ignore[list-item]
            )

    def test_unknown_operation_raises_clear_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "不支持的知识库补丁操作"):
            _apply_brand_knowledge_patch_operations(
                base_markdown="# 品牌概述\n\n旧内容。",
                operations=[
                    {
                        "op": "rewrite_document",
                        "content": "新内容。",
                    }
                ],
            )

    def test_empty_content_raises_for_content_operations(self) -> None:
        with self.assertRaisesRegex(ValueError, "补丁操作 content 不能为空"):
            _apply_brand_knowledge_patch_operations(
                base_markdown="# 品牌概述\n\n旧内容。",
                operations=[
                    {
                        "op": "append_document",
                        "content": "  ",
                    }
                ],
            )

    def test_missing_target_heading_raises_clear_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "未在基线 Markdown 中找到标题"):
            _apply_brand_knowledge_patch_operations(
                base_markdown="# 品牌概述\n\n旧内容。",
                operations=[
                    {
                        "op": "append_to_section",
                        "target_heading": "# 不存在的章节",
                        "content": "新增内容。",
                    }
                ],
            )

    def test_replace_bold_section_preserves_following_bold_label_boundary(self) -> None:
        base_markdown = (
            "- **孙秀丽**:心理治疗师。\n\n"
            "**李瑛团队成员名单(核心团队)**\n\n"
            "李瑛、周璇梓、张渝、吴琼、崔雪梅、许曼、黄丽明、侯洪雁、孙秀丽\n\n"
            "**李瑛团队挂号建议**:目前北京儿童医院李瑛主任本部号源长期爆满、预约周期极长。"
            "先挂团队号尽早介入干预。\n\n"
            "**4.9 国际医疗专家团队**\n\n"
            "- **李军(新加坡)**:新加坡国立大学杨潞龄医学院妇产科行政副主任。"
        )

        result = _apply_brand_knowledge_patch_operations(
            base_markdown=base_markdown,
            operations=[
                {
                    "op": "replace_section",
                    "target_heading": "**李瑛团队成员名单(核心团队)**",
                    "content": (
                        "**李瑛团队成员名单(核心团队)**\n\n"
                        "李瑛、周璇梓、张渝、吴琼、崔雪梅、许曼、黄丽明、侯洪雁、孙秀丽、殷晶晶"
                    ),
                }
            ],
        )

        self.assertIn("孙秀丽、殷晶晶", result)
        self.assertIn("**李瑛团队挂号建议**:目前北京儿童医院李瑛主任本部号源长期爆满", result)
        self.assertIn("先挂团队号尽早介入干预", result)
        self.assertIn("**4.9 国际医疗专家团队**", result)

    def test_replace_bold_section_does_not_treat_bold_list_items_as_boundaries(self) -> None:
        base_markdown = (
            "**核心医生团队**\n\n"
            "- **李瑛**:主任医师,儿童心理方向。\n"
            "- **吴琼**:主任医师,儿童保健方向。\n\n"
            "**团队挂号建议**:建议优先预约团队门诊。"
        )

        result = _apply_brand_knowledge_patch_operations(
            base_markdown=base_markdown,
            operations=[
                {
                    "op": "replace_section",
                    "target_heading": "**核心医生团队**",
                    "content": (
                        "**核心医生团队**\n\n"
                        "- **李瑛**:主任医师,儿童心理方向。\n"
                        "- **吴琼**:主任医师,儿童保健方向。\n"
                        "- **殷晶晶**:心理咨询师。"
                    ),
                }
            ],
        )

        self.assertIn("- **李瑛**:主任医师", result)
        self.assertIn("- **吴琼**:主任医师", result)
        self.assertIn("- **殷晶晶**:心理咨询师", result)
        self.assertIn("**团队挂号建议**:建议优先预约团队门诊。", result)

    def test_replace_bold_section_keeps_immediate_bold_label_rows_as_section_body(self) -> None:
        base_markdown = (
            "**门诊服务信息**\n\n"
            "**学习困难门诊**:30分钟,199元。\n\n"
            "**拒学厌学门诊**:20分钟问诊,500元。\n\n"
            "**下一章节**\n\n"
            "后续内容。"
        )

        result = _apply_brand_knowledge_patch_operations(
            base_markdown=base_markdown,
            operations=[
                {
                    "op": "replace_section",
                    "target_heading": "**门诊服务信息**",
                    "content": (
                        "**门诊服务信息**\n\n"
                        "**学习困难门诊**:30分钟,199元。\n\n"
                        "**拒学厌学门诊**:20分钟问诊,500元。\n\n"
                        "**注意事项**:具体以最新排班为准。"
                    ),
                }
            ],
        )

        self.assertIn("**学习困难门诊**:30分钟,199元。", result)
        self.assertIn("**拒学厌学门诊**:20分钟问诊,500元。", result)
        self.assertIn("**注意事项**:具体以最新排班为准。", result)
        self.assertIn("**下一章节**", result)
        self.assertIn("后续内容。", result)

    def test_append_existing_child_heading_replaces_existing_span_instead_of_duplicating(self) -> None:
        base_markdown = (
            "### 水上运动 度假体验 — 海上项目篇\n\n"
            "**水上运动中心**\n"
            "景区现设有游玩体验类项目海洋浮/深潜、摩托艇等十余种。\n\n"
            "**远礁深潜/浮潜**\n"
            "旧潜水介绍。\n\n"
            "**水上运动中心**\n"
            "景区现设有游玩体验类项目野趣赶海、海洋浮/深潜、摩托艇等十余种。\n\n"
            "**野趣赶海**\n"
            "呆呆岛海上运动中心赶海包含拉网捕鱼和沙滩挖螃蟹等赶海玩法。\n\n"
            "**远礁深潜/浮潜**\n"
            "旧潜水介绍。\n\n"
            "### 出片海岛 呆式旅拍 — 网红打卡篇\n\n"
            "旅拍内容。"
        )

        result = _apply_brand_knowledge_patch_operations(
            base_markdown=base_markdown,
            operations=[
                {
                    "op": "append_to_section",
                    "target_heading": "### 水上运动 度假体验 — 海上项目篇",
                    "content": (
                        "**水上运动中心**\n"
                        "景区现设有游玩体验类项目海洋浮/深潜、摩托艇等十余种。\n\n"
                        "**远礁深潜/浮潜**\n"
                        "新版潜水介绍。"
                    ),
                }
            ],
        )

        self.assertIn("### 水上运动 度假体验 — 海上项目篇", result)
        self.assertIn("新版潜水介绍。", result)
        self.assertIn("### 出片海岛 呆式旅拍 — 网红打卡篇", result)
        self.assertNotIn("野趣赶海", result)
        self.assertNotIn("赶海", result)
        self.assertEqual(result.count("**水上运动中心**"), 1)
        self.assertEqual(result.count("**远礁深潜/浮潜**"), 1)
