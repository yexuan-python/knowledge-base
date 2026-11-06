from __future__ import annotations

import sys
import unittest

from knowledge_base.brand_knowledge.ai.rounds import (
    generate_brand_ai_knowledge_patch_from_structured_update,
    generate_brand_ai_knowledge_from_structured_deletion,
    generate_brand_ai_knowledge_from_structured_update,
    generate_brand_knowledge_patch_markdown,
)

from tests.fakes.brand_flow import FakeSettings


class BrandAiRoundPromptTests(unittest.IsolatedAsyncioTestCase):
    async def test_patch_markdown_replaces_section_and_preserves_unaffected_tail(self) -> None:
        module = sys.modules["knowledge_base.brand_knowledge.ai.rounds"]
        original_call = module.call_anthropic_json
        captured_prompts: list[str] = []

        def fake_call_anthropic_json(prompt: str, settings=None):
            captured_prompts.append(prompt)
            return {
                "status": "completed",
                "summary": "更新服务章节",
                "operations": [
                    {
                        "op": "replace_section",
                        "target_heading": "**二、服务介绍**",
                        "content": "**二、服务介绍**\n\n新增产康服务。",
                    }
                ],
            }

        module.call_anthropic_json = fake_call_anthropic_json
        try:
            result = await generate_brand_knowledge_patch_markdown(
                brand_name="示例品牌",
                base_knowledge_markdown=(
                    "**一、品牌概述**\n\n旧介绍。\n\n"
                    "**二、服务介绍**\n\n旧服务。\n\n"
                    "**三、后续重要内容**\n\n这段尾部必须保留。"
                ),
                markdown_sources=[
                    {
                        "source_name": "本轮迭代要求.md",
                        "source_role": "iteration_instruction",
                        "markdown_text": "# 本轮迭代要求\n\n新增产康服务。",
                    }
                ],
                settings=FakeSettings(),
            )
        finally:
            module.call_anthropic_json = original_call

        self.assertEqual(len(captured_prompts), 1)
        self.assertIn("只生成局部补丁操作 JSON；不要输出新版完整 Markdown", captured_prompts[0])
        self.assertIn("delete_section", captured_prompts[0])
        self.assertIn("严禁用 append_to_section 追加一个删减版片段来表达删除", captured_prompts[0])
        self.assertIn("来源角色：iteration_web_article", captured_prompts[0])
        self.assertIn("不要压缩成一句话摘要", captured_prompts[0])
        self.assertIn("**二、服务介绍**", captured_prompts[0])
        self.assertIn("新增产康服务", result["final_markdown"])
        self.assertIn("**三、后续重要内容**", result["final_markdown"])
        self.assertIn("这段尾部必须保留。", result["final_markdown"])
        self.assertNotIn("旧服务。", result["final_markdown"])

    async def test_patch_markdown_appends_inside_target_section_before_next_peer(self) -> None:
        module = sys.modules["knowledge_base.brand_knowledge.ai.rounds"]
        original_call = module.call_anthropic_json

        def fake_call_anthropic_json(prompt: str, settings=None):
            return {
                "status": "completed",
                "summary": "追加服务亮点",
                "operations": [
                    {
                        "op": "append_to_section",
                        "target_heading": "# 二、服务介绍",
                        "content": "- 新增夜游服务。",
                    }
                ],
            }

        module.call_anthropic_json = fake_call_anthropic_json
        try:
            result = await generate_brand_knowledge_patch_markdown(
                brand_name="示例品牌",
                base_knowledge_markdown=(
                    "# 一、品牌概述\n\n旧介绍。\n\n"
                    "# 二、服务介绍\n\n旧服务。\n\n"
                    "## 2.1 子服务\n\n子服务说明。\n\n"
                    "# 三、后续重要内容\n\n这段尾部必须保留。"
                ),
                markdown_sources=[
                    {
                        "source_name": "本轮迭代要求.md",
                        "source_role": "iteration_instruction",
                        "markdown_text": "# 本轮迭代要求\n\n新增夜游服务。",
                    }
                ],
                settings=FakeSettings(),
            )
        finally:
            module.call_anthropic_json = original_call

        self.assertEqual(
            result["final_markdown"],
            (
                "# 一、品牌概述\n\n旧介绍。\n\n"
                "# 二、服务介绍\n\n旧服务。\n\n"
                "## 2.1 子服务\n\n子服务说明。\n\n"
                "- 新增夜游服务。\n\n"
                "# 三、后续重要内容\n\n这段尾部必须保留。"
            ),
        )

    async def test_patch_markdown_appends_document_when_no_matching_base_heading(self) -> None:
        module = sys.modules["knowledge_base.brand_knowledge.ai.rounds"]
        original_call = module.call_anthropic_json

        def fake_call_anthropic_json(prompt: str, settings=None):
            return {
                "status": "completed",
                "summary": "新增主题",
                "operations": [
                    {
                        "op": "append_document",
                        "target_heading": "",
                        "content": "# 四、新增主题\n\n新增完整主题内容。",
                    }
                ],
            }

        module.call_anthropic_json = fake_call_anthropic_json
        try:
            result = await generate_brand_knowledge_patch_markdown(
                brand_name="示例品牌",
                base_knowledge_markdown="# 一、品牌概述\n\n旧介绍。",
                markdown_sources=[
                    {
                        "source_name": "新增主题.md",
                        "source_role": "attachment_asset",
                        "markdown_text": "# 新增主题\n\n新增完整主题内容。",
                    }
                ],
                settings=FakeSettings(),
            )
        finally:
            module.call_anthropic_json = original_call

        self.assertEqual(
            result["final_markdown"],
            "# 一、品牌概述\n\n旧介绍。\n\n# 四、新增主题\n\n新增完整主题内容。",
        )

    async def test_patch_markdown_replaces_first_matching_duplicate_heading_only(self) -> None:
        module = sys.modules["knowledge_base.brand_knowledge.ai.rounds"]
        original_call = module.call_anthropic_json

        def fake_call_anthropic_json(prompt: str, settings=None):
            return {
                "status": "completed",
                "summary": "更新第一个重复标题",
                "operations": [
                    {
                        "op": "replace_section",
                        "target_heading": "## 门店信息",
                        "content": "更新后的第一个门店信息。",
                    }
                ],
            }

        module.call_anthropic_json = fake_call_anthropic_json
        try:
            result = await generate_brand_knowledge_patch_markdown(
                brand_name="示例品牌",
                base_knowledge_markdown=(
                    "# 一、渠道\n\n"
                    "## 门店信息\n\n旧门店 A。\n\n"
                    "## 门店信息\n\n旧门店 B。"
                ),
                markdown_sources=[
                    {
                        "source_name": "门店更新.md",
                        "source_role": "attachment_asset",
                        "markdown_text": "# 门店更新\n\n更新门店 A。",
                    }
                ],
                settings=FakeSettings(),
            )
        finally:
            module.call_anthropic_json = original_call

        self.assertEqual(
            result["final_markdown"],
            "# 一、渠道\n\n## 门店信息\n\n更新后的第一个门店信息。\n\n## 门店信息\n\n旧门店 B。",
        )

    async def test_structured_update_patch_supports_delete_section_and_preserves_unrelated_content(self) -> None:
        module = sys.modules["knowledge_base.brand_knowledge.ai.rounds"]
        original_call = module.call_anthropic_json
        captured_prompts: list[str] = []

        def fake_call_anthropic_json(prompt: str, settings=None):
            captured_prompts.append(prompt)
            return {
                "status": "completed",
                "summary": "更新品牌介绍并删除竞品章节",
                "operations": [
                    {
                        "op": "replace_section",
                        "target_heading": "## 品牌介绍",
                        "content": "## 品牌介绍\n\n新介绍。",
                    },
                    {
                        "op": "delete_section",
                        "target_heading": "## 竞品信息",
                        "content": "",
                    },
                ],
            }

        module.call_anthropic_json = fake_call_anthropic_json
        try:
            result = await generate_brand_ai_knowledge_patch_from_structured_update(
                brand_name="示例品牌",
                previous_ai_knowledge_markdown=(
                    "# 示例品牌\n\n"
                    "## 品牌介绍\n\n旧介绍。\n\n"
                    "## 竞品信息\n\n旧竞品。\n\n"
                    "## 保留章节\n\n这段必须保留。"
                ),
                structured_knowledge_markdown=(
                    "# 示例品牌 本次结构化知识变更\n\n"
                    "## 本次明确删除或收缩的 section\n\n"
                    "- competitors\n\n"
                    "## 品牌介绍\n\n"
                    "- section：`intro`\n"
                    "- change_type：`update`\n\n"
                    "本次更新后的内容：新介绍。"
                ),
                deleted_sections=["competitors"],
                knowledge_revision="LXKG-SLPP-V1.0.2-20260710101010",
                settings=FakeSettings(),
            )
        finally:
            module.call_anthropic_json = original_call

        self.assertEqual(len(captured_prompts), 1)
        prompt = captured_prompts[0]
        self.assertIn("/knowledge/update 结构化变更摘要", prompt)
        self.assertIn("delete_section", prompt)
        self.assertIn("competitors", prompt)
        self.assertEqual(
            result["final_markdown"],
            "# 示例品牌\n\n## 品牌介绍\n\n新介绍。\n\n## 保留章节\n\n这段必须保留。",
        )

    async def test_structured_deletion_prompt_has_separate_rules(self) -> None:
        module = sys.modules["knowledge_base.brand_knowledge.ai.rounds"]
        original_call = module.call_anthropic_text
        captured_prompts: list[str] = []

        def fake_call_anthropic_text(prompt: str, settings=None):
            captured_prompts.append(prompt)
            return "# 删除后知识库"

        module.call_anthropic_text = fake_call_anthropic_text
        try:
            result = await generate_brand_ai_knowledge_from_structured_deletion(
                brand_name="示例品牌",
                previous_ai_knowledge_markdown="# 旧版\n## 竞品信息\n- 竞品A",
                structured_knowledge_markdown="# 结构化\n## 品牌介绍\n- 仅保留现有信息",
                deleted_sections=["competitors"],
                knowledge_revision="LXKG-SLPP-V1.0.1-20260709121234",
                settings=FakeSettings(),
            )
        finally:
            module.call_anthropic_text = original_call

        self.assertEqual(result["final_markdown"], "# 删除后知识库")
        self.assertEqual(len(captured_prompts), 1)
        prompt = captured_prompts[0]
        self.assertIn("品牌 AI 知识库删除更新助手", prompt)
        self.assertIn("删除更新规则", prompt)
        self.assertIn("本次明确存在删除/收缩的结构化 section", prompt)
        self.assertIn("competitors", prompt)
        self.assertIn("不得把已删除内容从上一版中带回", prompt)

    async def test_structured_update_uses_anthropic_entry(self) -> None:
        module = sys.modules["knowledge_base.brand_knowledge.ai.rounds"]
        original_call = module.call_anthropic_text
        captured_prompts: list[str] = []

        def fake_call_anthropic_text(prompt: str, settings=None):
            captured_prompts.append(prompt)
            return "# 修改后知识库"

        module.call_anthropic_text = fake_call_anthropic_text
        try:
            result = await generate_brand_ai_knowledge_from_structured_update(
                brand_name="示例品牌",
                previous_ai_knowledge_markdown="# 旧版\n## 品牌介绍\n- 旧介绍",
                structured_knowledge_markdown="# 结构化\n## 品牌介绍\n- 新介绍",
                knowledge_revision="LXKG-SLPP-V1.0.2-20260710101010",
                settings=FakeSettings(),
            )
        finally:
            module.call_anthropic_text = original_call

        self.assertEqual(result["final_markdown"], "# 修改后知识库")
        self.assertEqual(len(captured_prompts), 1)
        prompt = captured_prompts[0]
        self.assertIn("结构化字段更新", prompt)
        self.assertIn("这是一次非删除结构化更新", prompt)
        self.assertIn("未覆盖的内容一律保留，不得主动删除任何旧内容", prompt)
