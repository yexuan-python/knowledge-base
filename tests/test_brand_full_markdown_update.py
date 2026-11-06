from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import AsyncMock, call, patch

from knowledge_base.brand.full_markdown import (
    build_full_brand_knowledge_markdown_from_update,
    generate_full_brand_knowledge_markdown_from_update,
)

from tests.fakes.brand_flow import (
    FakeBrandFullKnowledgeStore,
    FakeBrandKnowledgeStore,
    FakeBrandProductStore,
    FakeBrandStore,
    FakeSettings,
)


class BrandFullMarkdownUpdateTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_applies_structured_patch_and_preserves_unaffected_markdown(self) -> None:
        full_store = FakeBrandFullKnowledgeStore()
        full_store.rows.append({
            "id": 1, "brand_id": 1, "version_no": 1,
            "content_markdown": (
                "# 示例品牌\n\n## 品牌介绍\n\n旧介绍。\n\n"
                "## 竞品信息\n\n旧竞品。\n\n## 保留章节\n\n这段必须保留。"
            ),
        })
        service = types.SimpleNamespace(
            _brands=FakeBrandStore(),
            _brand_full_knowledge=full_store,
            _settings=FakeSettings(),
        )
        patch_payload = {"operations": [
            {"op": "replace_section", "target_heading": "## 品牌介绍", "content": "## 品牌介绍\n\n新介绍。"},
            {"op": "delete_section", "target_heading": "## 竞品信息", "content": ""},
            {"op": "append_document", "target_heading": "", "content": "## 门店信息\n\n新门店。"},
        ]}
        with (
            patch("knowledge_base.brand_knowledge.ai.rounds.call_anthropic_json", return_value=patch_payload) as llm,
            patch("knowledge_base.brand.full_markdown.generate_brand_ai_knowledge_from_merged_sources", new_callable=AsyncMock) as full_generator,
        ):
            result = await generate_full_brand_knowledge_markdown_from_update(
                service,
                brand_name="示例品牌",
                update_reason="brand_full_knowledge_refresh",
                structured_knowledge_markdown=(
                    "# 本次结构化知识变更\n\n- source_type: knowledge_update\n新介绍。删除竞品。\n\n"
                    "## 其他信息\n本次更新后的内容：[{\"门店信息\": \"新门店。\"}]"
                ),
                deleted_sections=["competitors"],
                change_origin="frontend",
            )
        llm.assert_called_once()
        full_generator.assert_not_awaited()
        prompt = llm.call_args.args[0]
        self.assertIn("/knowledge/update 结构化变更摘要", prompt)
        self.assertIn("新门店。", prompt)
        self.assertEqual(
            result["knowledge_markdown"],
            "# 示例品牌\n\n## 品牌介绍\n\n新介绍。\n\n"
            "## 保留章节\n\n这段必须保留。\n\n## 门店信息\n\n新门店。",
        )

    async def test_refresh_retries_patch_before_full_generation(self) -> None:
        cases = [
            ("first_patch_succeeds", [{"final_markdown": "# 补丁结果"}], [], ["patch"]),
            ("second_patch_succeeds", [ValueError("bad patch"), {"final_markdown": "# 补丁结果"}], [], ["patch"] * 2),
            ("third_patch_succeeds", [ValueError("bad patch")] * 2 + [{"final_markdown": "# 补丁结果"}], [], ["patch"] * 3),
            ("patch_exhausted", [ValueError("bad patch")] * 3, [{"final_markdown": "# 完整结果"}], ["patch"] * 3 + ["full"]),
            ("empty_patch_exhausted", [{"final_markdown": " "}] * 3, [{"final_markdown": "# 完整结果"}], ["patch"] * 3 + ["full"]),
            ("full_retries_after_patch_exhausted", [ValueError("bad patch")] * 3, [ValueError("bad full"), {"final_markdown": "# 完整结果"}], ["patch"] * 3 + ["full"] * 2),
            ("all_attempts_fail", [ValueError("bad patch")] * 3, [ValueError("bad full")] * 3, ["patch"] * 3 + ["full"] * 3),
        ]
        for name, patch_results, full_results, expected_order in cases:
            with self.subTest(name=name):
                full_store = FakeBrandFullKnowledgeStore()
                full_store.rows.append({
                    "id": 1, "brand_id": 1, "version_no": 1,
                    "content_markdown": "# 示例品牌\n\n## 品牌介绍\n旧介绍。",
                })
                service = types.SimpleNamespace(
                    _brands=FakeBrandStore(),
                    _brand_full_knowledge=full_store,
                    _settings=FakeSettings(),
                )
                order = []

                async def generate_patch(**kwargs):
                    order.append("patch")
                    self.assertIn("本次更新后的内容", kwargs["structured_knowledge_markdown"])
                    self.assertEqual(kwargs["deleted_sections"], ["competitors"])
                    result = patch_results[len([item for item in order if item == "patch"]) - 1]
                    if isinstance(result, Exception):
                        raise result
                    return result

                async def generate_full(**kwargs):
                    order.append("full")
                    self.assertEqual(order[:3], ["patch"] * 3)
                    result = full_results[len([item for item in order if item == "full"]) - 1]
                    if isinstance(result, Exception):
                        raise result
                    return result

                with (
                    patch("knowledge_base.brand.full_markdown.generate_brand_ai_knowledge_patch_from_structured_update", side_effect=generate_patch),
                    patch("knowledge_base.brand.full_markdown.generate_brand_ai_knowledge_from_merged_sources", side_effect=generate_full),
                    patch("knowledge_base.brand.full_markdown.asyncio.sleep", new_callable=AsyncMock) as sleep,
                ):
                    kwargs = dict(
                        brand_name="示例品牌",
                        structured_knowledge_markdown="# 结构化变更\n\n## 品牌介绍\n本次更新后的内容：新介绍。",
                        update_reason="brand_full_knowledge_refresh",
                        deleted_sections=["competitors"],
                        change_origin="frontend",
                    )
                    if name == "all_attempts_fail":
                        with self.assertRaisesRegex(ValueError, "bad full"):
                            await generate_full_brand_knowledge_markdown_from_update(service, **kwargs)
                    else:
                        result = await generate_full_brand_knowledge_markdown_from_update(service, **kwargs)
                        self.assertEqual(result["knowledge_markdown"], "# 完整结果" if full_results else "# 补丁结果")
                        self.assertEqual(result["change_origin"], "frontend")
                    self.assertEqual(order, expected_order)
                    expected_delays = [10, 20][:min(len(patch_results) - 1, 2)]
                    expected_delays += [1, 2][:max(len(full_results) - 1, 0)]
                    self.assertEqual(sleep.await_args_list, [call(delay) for delay in expected_delays])

    async def test_build_full_markdown_from_update_prefers_patch_when_base_exists(self) -> None:
        full_store = FakeBrandFullKnowledgeStore()
        full_store.rows.append(
            {
                "id": 1,
                "brand_id": 1,
                "version_no": 1,
                "content_markdown": (
                    "# 示例品牌\n\n"
                    "## 品牌介绍\n\n旧介绍。\n\n"
                    "## 保留章节\n\n这段必须保留。"
                ),
            }
        )
        service = types.SimpleNamespace(
            _brands=FakeBrandStore(),
            _brand_full_knowledge=full_store,
            _brand_products=FakeBrandProductStore(),
            _brand_knowledge=FakeBrandKnowledgeStore(),
            _settings=FakeSettings(),
            oss_client=types.SimpleNamespace(
                enabled=True,
                upload_bytes=lambda data, object_key, content_type=None: object_key,
                build_object_url=lambda object_key: f"https://oss.example.com/{object_key}",
            ),
        )
        module = sys.modules["knowledge_base.brand.full_markdown"]
        original_patch_generate = module.generate_brand_ai_knowledge_patch_from_structured_update
        original_update_generate = module.generate_brand_ai_knowledge_from_structured_update
        original_render_pdf = module.render_brand_full_knowledge_pdf_bytes
        calls = {"patch": 0, "update": 0}

        async def fake_patch_generate(**kwargs):
            calls["patch"] += 1
            self.assertEqual(kwargs["update_reason"], "knowledge_update")
            self.assertIn("## 品牌介绍", kwargs["previous_ai_knowledge_markdown"])
            self.assertIn("新介绍", kwargs["structured_knowledge_markdown"])
            return {
                "final_markdown": (
                    "# 示例品牌\n\n"
                    "## 品牌介绍\n\n新介绍。\n\n"
                    "## 保留章节\n\n这段必须保留。"
                ),
                "patch_operations": [
                    {
                        "op": "replace_section",
                        "target_heading": "## 品牌介绍",
                        "content": "## 品牌介绍\n\n新介绍。",
                    }
                ],
            }

        async def fake_update_generate(**_kwargs):
            calls["update"] += 1
            return {"final_markdown": "# 不应走整体更新"}

        async def fake_render_pdf(*_args, **_kwargs):
            return b"%PDF-1.4"

        module.generate_brand_ai_knowledge_patch_from_structured_update = fake_patch_generate
        module.generate_brand_ai_knowledge_from_structured_update = fake_update_generate
        module.render_brand_full_knowledge_pdf_bytes = fake_render_pdf
        try:
            result = await build_full_brand_knowledge_markdown_from_update(
                service,
                brand_name="示例品牌",
                structured_knowledge_markdown="# 结构化\n## 品牌介绍\n新介绍",
                update_reason="knowledge_update",
                deleted_sections=[],
                knowledge_revision="LXKG-SLPP-V1.0.2-20260710101010",
            )
        finally:
            module.generate_brand_ai_knowledge_patch_from_structured_update = original_patch_generate
            module.generate_brand_ai_knowledge_from_structured_update = original_update_generate
            module.render_brand_full_knowledge_pdf_bytes = original_render_pdf

        self.assertEqual(calls, {"patch": 1, "update": 0})
        self.assertEqual(
            result["knowledge_markdown"],
            "# 示例品牌\n\n## 品牌介绍\n\n新介绍。\n\n## 保留章节\n\n这段必须保留。",
        )

    @patch("knowledge_base.brand.full_markdown.asyncio.sleep", new_callable=AsyncMock)
    async def test_build_full_markdown_from_update_falls_back_to_full_generation_when_patch_fails(self, sleep: AsyncMock) -> None:
        full_store = FakeBrandFullKnowledgeStore()
        full_store.rows.append(
            {
                "id": 1,
                "brand_id": 1,
                "version_no": 1,
                "content_markdown": "# 示例品牌\n\n## 品牌介绍\n\n旧介绍。",
            }
        )
        service = types.SimpleNamespace(
            _brands=FakeBrandStore(),
            _brand_full_knowledge=full_store,
            _brand_products=FakeBrandProductStore(),
            _brand_knowledge=FakeBrandKnowledgeStore(),
            _settings=FakeSettings(),
            oss_client=types.SimpleNamespace(
                enabled=True,
                upload_bytes=lambda data, object_key, content_type=None: object_key,
                build_object_url=lambda object_key: f"https://oss.example.com/{object_key}",
            ),
        )
        module = sys.modules["knowledge_base.brand.full_markdown"]
        original_patch_generate = module.generate_brand_ai_knowledge_patch_from_structured_update
        original_update_generate = module.generate_brand_ai_knowledge_from_structured_update
        original_render_pdf = module.render_brand_full_knowledge_pdf_bytes
        calls = {"patch": 0, "update": 0}

        async def fake_patch_generate(**_kwargs):
            calls["patch"] += 1
            raise ValueError("bad patch")

        async def fake_update_generate(**kwargs):
            calls["update"] += 1
            self.assertEqual(kwargs["update_reason"], "knowledge_update")
            return {"final_markdown": "# 回退整体生成知识库"}

        async def fake_render_pdf(*_args, **_kwargs):
            return b"%PDF-1.4"

        module.generate_brand_ai_knowledge_patch_from_structured_update = fake_patch_generate
        module.generate_brand_ai_knowledge_from_structured_update = fake_update_generate
        module.render_brand_full_knowledge_pdf_bytes = fake_render_pdf
        try:
            result = await build_full_brand_knowledge_markdown_from_update(
                service,
                brand_name="示例品牌",
                structured_knowledge_markdown="# 结构化\n## 品牌介绍\n新介绍",
                update_reason="knowledge_update",
                deleted_sections=[],
                knowledge_revision="LXKG-SLPP-V1.0.2-20260710101010",
            )
        finally:
            module.generate_brand_ai_knowledge_patch_from_structured_update = original_patch_generate
            module.generate_brand_ai_knowledge_from_structured_update = original_update_generate
            module.render_brand_full_knowledge_pdf_bytes = original_render_pdf

        self.assertEqual(calls, {"patch": 3, "update": 1})
        self.assertEqual(sleep.await_args_list, [call(10), call(20)])
        self.assertEqual(result["knowledge_markdown"], "# 回退整体生成知识库")

    async def test_build_full_markdown_from_update_uses_delete_generator_when_deleted_sections_present(self) -> None:
        service = types.SimpleNamespace(
            _brands=FakeBrandStore(),
            _brand_full_knowledge=FakeBrandFullKnowledgeStore(),
            _brand_products=FakeBrandProductStore(),
            _brand_knowledge=FakeBrandKnowledgeStore(),
            _settings=FakeSettings(),
            oss_client=types.SimpleNamespace(
                enabled=True,
                upload_bytes=lambda data, object_key, content_type=None: object_key,
                build_object_url=lambda object_key: f"https://oss.example.com/{object_key}",
            ),
        )
        module = sys.modules["knowledge_base.brand.full_markdown"]
        original_change_generate = module.generate_brand_ai_knowledge_from_structured_change
        original_update_generate = module.generate_brand_ai_knowledge_from_structured_update
        original_delete_generate = module.generate_brand_ai_knowledge_from_structured_deletion
        original_render_pdf = module.render_brand_full_knowledge_pdf_bytes
        calls = {"change": 0, "update": 0, "delete": 0}

        async def fake_change_generate(**kwargs):
            calls["change"] += 1
            return {"final_markdown": "# 不应走到混合更新"}

        async def fake_update_generate(**kwargs):
            calls["update"] += 1
            return {"final_markdown": "# 不应走到普通更新"}

        async def fake_delete_generate(**kwargs):
            calls["delete"] += 1
            self.assertEqual(kwargs["deleted_sections"], ["competitors"])
            self.assertEqual(kwargs["update_reason"], "knowledge_delete")
            return {"final_markdown": "# 删除版知识库"}

        async def fake_render_pdf(*args, **kwargs):
            return b"%PDF-1.4"

        module.generate_brand_ai_knowledge_from_structured_change = fake_change_generate
        module.generate_brand_ai_knowledge_from_structured_update = fake_update_generate
        module.generate_brand_ai_knowledge_from_structured_deletion = fake_delete_generate
        module.render_brand_full_knowledge_pdf_bytes = fake_render_pdf
        try:
            result = await build_full_brand_knowledge_markdown_from_update(
                service,
                brand_name="示例品牌",
                structured_knowledge_markdown="# 结构化知识",
                update_reason="knowledge_delete",
                deleted_sections=["competitors"],
                knowledge_revision="LXKG-SLPP-V1.0.1-20260709121234",
            )
        finally:
            module.generate_brand_ai_knowledge_from_structured_change = original_change_generate
            module.generate_brand_ai_knowledge_from_structured_update = original_update_generate
            module.generate_brand_ai_knowledge_from_structured_deletion = original_delete_generate
            module.render_brand_full_knowledge_pdf_bytes = original_render_pdf

        self.assertEqual(calls, {"change": 0, "update": 0, "delete": 1})
        self.assertEqual(result["knowledge_markdown"], "# 删除版知识库")

    async def test_build_full_markdown_from_update_does_not_log_structured_markdown_body(self) -> None:
        service = types.SimpleNamespace(
            _brands=FakeBrandStore(),
            _brand_full_knowledge=FakeBrandFullKnowledgeStore(),
            _brand_products=FakeBrandProductStore(),
            _brand_knowledge=FakeBrandKnowledgeStore(),
            _settings=FakeSettings(),
            oss_client=types.SimpleNamespace(
                enabled=True,
                upload_bytes=lambda data, object_key, content_type=None: object_key,
                build_object_url=lambda object_key: f"https://oss.example.com/{object_key}",
            ),
        )
        module = sys.modules["knowledge_base.brand.full_markdown"]
        original_update_generate = module.generate_brand_ai_knowledge_from_structured_update
        original_render_pdf = module.render_brand_full_knowledge_pdf_bytes
        structured_markdown = "\n".join(
            [
                "### 品牌基础信息",
                "- source_type: `knowledge_update`",
                "- before_json:",
                "```json",
                "{\"intro\":\"旧简介\"}",
                "```",
                "- after_json:",
                "```json",
                "{\"intro\":\"新简介\"}",
                "```",
            ]
        )

        async def fake_update_generate(**_kwargs):
            return {"final_markdown": "# 修改后知识库"}

        async def fake_render_pdf(*_args, **_kwargs):
            return b"%PDF-1.4"

        module.generate_brand_ai_knowledge_from_structured_update = fake_update_generate
        module.render_brand_full_knowledge_pdf_bytes = fake_render_pdf
        try:
            with self.assertLogs("knowledge_base.brand.full_markdown", level="INFO") as captured_logs:
                result = await build_full_brand_knowledge_markdown_from_update(
                    service,
                    brand_name="示例品牌",
                    structured_knowledge_markdown=structured_markdown,
                    update_reason="knowledge_update",
                    deleted_sections=[],
                    knowledge_revision="LXKG-SLPP-V1.0.2-20260710101010",
                )
        finally:
            module.generate_brand_ai_knowledge_from_structured_update = original_update_generate
            module.render_brand_full_knowledge_pdf_bytes = original_render_pdf

        self.assertEqual(result["knowledge_markdown"], "# 修改后知识库")
        log_text = "\n".join(captured_logs.output)
        self.assertIn("structured_chars=", log_text)
        self.assertNotIn("before_json", log_text)
        self.assertNotIn("after_json", log_text)
        self.assertNotIn("旧简介", log_text)
        self.assertNotIn("新简介", log_text)

    async def test_build_full_markdown_from_refresh_uses_merged_sources_generator(self) -> None:
        service = types.SimpleNamespace(
            _brands=FakeBrandStore(),
            _brand_full_knowledge=FakeBrandFullKnowledgeStore(),
            _brand_products=FakeBrandProductStore(),
            _brand_knowledge=FakeBrandKnowledgeStore(),
            _settings=FakeSettings(),
            oss_client=types.SimpleNamespace(
                enabled=True,
                upload_bytes=lambda data, object_key, content_type=None: object_key,
                build_object_url=lambda object_key: f"https://oss.example.com/{object_key}",
            ),
        )
        module = sys.modules["knowledge_base.brand.full_markdown"]
        original_merged_generate = module.generate_brand_ai_knowledge_from_merged_sources
        original_update_generate = module.generate_brand_ai_knowledge_from_structured_update
        original_change_generate = module.generate_brand_ai_knowledge_from_structured_change
        original_delete_generate = module.generate_brand_ai_knowledge_from_structured_deletion
        original_render_pdf = module.render_brand_full_knowledge_pdf_bytes
        calls = {"merged": 0, "update": 0, "change": 0, "delete": 0}

        async def fake_merged_generate(**kwargs):
            calls["merged"] += 1
            self.assertEqual(kwargs["update_reason"], "brand_full_knowledge_refresh")
            self.assertEqual(kwargs["deleted_sections"], ["competitors"])
            self.assertIn("## 附件确认 Markdown", kwargs["structured_knowledge_markdown"])
            return {"final_markdown": "# 合并来源新版知识库"}

        async def fake_update_generate(**_kwargs):
            calls["update"] += 1
            return {"final_markdown": "# 不应走普通更新"}

        async def fake_change_generate(**_kwargs):
            calls["change"] += 1
            return {"final_markdown": "# 不应走混合更新"}

        async def fake_delete_generate(**_kwargs):
            calls["delete"] += 1
            return {"final_markdown": "# 不应走删除更新"}

        async def fake_render_pdf(*_args, **_kwargs):
            return b"%PDF-1.4"

        module.generate_brand_ai_knowledge_from_merged_sources = fake_merged_generate
        module.generate_brand_ai_knowledge_from_structured_update = fake_update_generate
        module.generate_brand_ai_knowledge_from_structured_change = fake_change_generate
        module.generate_brand_ai_knowledge_from_structured_deletion = fake_delete_generate
        module.render_brand_full_knowledge_pdf_bytes = fake_render_pdf
        try:
            result = await build_full_brand_knowledge_markdown_from_update(
                service,
                brand_name="示例品牌",
                structured_knowledge_markdown="\n".join(
                    [
                        "# 示例品牌 本轮品牌知识变更摘要",
                        "",
                        "## 结构化变更",
                        "",
                        "## 竞品信息",
                        "- section：`competitors`",
                        "- change_type：`delete`",
                        "",
                        "本次更新后的内容：",
                        "```json",
                        "[]",
                        "```",
                        "",
                        "## 附件确认 Markdown",
                        "# 附件资料",
                    ]
                ),
                update_reason="brand_full_knowledge_refresh",
                deleted_sections=["competitors"],
                knowledge_revision="LXKG-SLPP-V1.0.2-20260710101010",
            )
        finally:
            module.generate_brand_ai_knowledge_from_merged_sources = original_merged_generate
            module.generate_brand_ai_knowledge_from_structured_update = original_update_generate
            module.generate_brand_ai_knowledge_from_structured_change = original_change_generate
            module.generate_brand_ai_knowledge_from_structured_deletion = original_delete_generate
            module.render_brand_full_knowledge_pdf_bytes = original_render_pdf

        self.assertEqual(calls, {"merged": 1, "update": 0, "change": 0, "delete": 0})
        self.assertEqual(result["knowledge_markdown"], "# 合并来源新版知识库")

    async def test_build_full_markdown_from_update_uses_change_generator_when_updates_and_deletions_coexist(self) -> None:
        service = types.SimpleNamespace(
            _brands=FakeBrandStore(),
            _brand_full_knowledge=FakeBrandFullKnowledgeStore(),
            _brand_products=FakeBrandProductStore(),
            _brand_knowledge=FakeBrandKnowledgeStore(),
            _settings=FakeSettings(),
            oss_client=types.SimpleNamespace(
                enabled=True,
                upload_bytes=lambda data, object_key, content_type=None: object_key,
                build_object_url=lambda object_key: f"https://oss.example.com/{object_key}",
            ),
        )
        module = sys.modules["knowledge_base.brand.full_markdown"]
        original_change_generate = module.generate_brand_ai_knowledge_from_structured_change
        original_update_generate = module.generate_brand_ai_knowledge_from_structured_update
        original_delete_generate = module.generate_brand_ai_knowledge_from_structured_deletion
        original_render_pdf = module.render_brand_full_knowledge_pdf_bytes
        calls = {"change": 0, "update": 0, "delete": 0}
        structured_markdown = "\n".join(
            [
                "# 示例品牌 本次结构化知识变更",
                "",
                "本文件只包含本次更新涉及的结构化内容；未列出的 section 请沿用上一版品牌 AI 知识库。",
                "",
                "## 本次明确删除或收缩的 section",
                "",
                "- competitors",
                "",
                "## 竞品信息",
                "",
                "- section：`competitors`",
                "- change_type：`delete`",
                "",
                "本次更新后的内容：",
                "```json",
                "[]",
                "```",
                "",
                "## 产品信息",
                "",
                "- section：`products`",
                "- change_type：`update`",
                "",
                "本次更新后的内容：",
                "```json",
                "[{\"name\":\"新品A\"}]",
                "```",
            ]
        )

        async def fake_change_generate(**kwargs):
            calls["change"] += 1
            self.assertEqual(kwargs["deleted_sections"], ["competitors"])
            self.assertEqual(kwargs["update_reason"], "knowledge_delete")
            self.assertEqual(kwargs["structured_knowledge_markdown"], structured_markdown)
            self.assertIn("## 产品信息", kwargs["structured_knowledge_markdown"])
            return {"final_markdown": "# 混合版知识库"}

        async def fake_update_generate(**kwargs):
            calls["update"] += 1
            return {"final_markdown": "# 不应走到普通更新"}

        async def fake_delete_generate(**kwargs):
            calls["delete"] += 1
            return {"final_markdown": "# 不应走到纯删除"}

        async def fake_render_pdf(*args, **kwargs):
            return b"%PDF-1.4"

        module.generate_brand_ai_knowledge_from_structured_change = fake_change_generate
        module.generate_brand_ai_knowledge_from_structured_update = fake_update_generate
        module.generate_brand_ai_knowledge_from_structured_deletion = fake_delete_generate
        module.render_brand_full_knowledge_pdf_bytes = fake_render_pdf
        try:
            result = await build_full_brand_knowledge_markdown_from_update(
                service,
                brand_name="示例品牌",
                structured_knowledge_markdown=structured_markdown,
                update_reason="knowledge_delete",
                deleted_sections=["competitors"],
                knowledge_revision="LXKG-SLPP-V1.0.2-20260710121234",
            )
        finally:
            module.generate_brand_ai_knowledge_from_structured_change = original_change_generate
            module.generate_brand_ai_knowledge_from_structured_update = original_update_generate
            module.generate_brand_ai_knowledge_from_structured_deletion = original_delete_generate
            module.render_brand_full_knowledge_pdf_bytes = original_render_pdf

        self.assertEqual(calls, {"change": 1, "update": 0, "delete": 0})
        self.assertEqual(result["knowledge_markdown"], "# 混合版知识库")
