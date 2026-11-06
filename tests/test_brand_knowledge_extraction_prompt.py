from __future__ import annotations

import types
import unittest
from unittest.mock import patch

from knowledge_base.brand_knowledge.ai.extraction import extract_brand_knowledge_from_markdown


class BrandKnowledgeExtractionPromptTests(unittest.IsolatedAsyncioTestCase):
    async def test_attachment_extraction_prompt_preserves_unmapped_content_and_product_split_rule(self) -> None:
        captured: dict[str, str] = {}

        def fake_generation_call(**kwargs):
            captured["prompt"] = kwargs["prompt"]
            return types.SimpleNamespace(
                status_code=200,
                output=types.SimpleNamespace(
                    choices=[
                        types.SimpleNamespace(
                            message=types.SimpleNamespace(
                                content='{"basic_info":{},"products":[],"other_info":[]}'
                            )
                        )
                    ]
                ),
            )

        settings = types.SimpleNamespace(
            dashscope_api_key="test-key",
            text_llm_model="qwen-plus",
        )

        with patch("knowledge_base.brand_knowledge.ai.extraction.Generation.call", side_effect=fake_generation_call):
            await extract_brand_knowledge_from_markdown(
                "# 附件内容\n未归属信息：门店提供一对一服务",
                brand_name="示例品牌",
                source_name="附件.md",
                settings=settings,
            )

        prompt = captured["prompt"]
        self.assertIn("附件解析要尽量覆盖 Markdown 原文中的全部有效信息", prompt)
        self.assertIn("不要因为找不到标准字段就丢弃原文信息", prompt)
        self.assertIn("无法明确归入任何标准字段的信息，放入最合适层级的 `other_info`", prompt)
        self.assertIn("已有产品进入 `products`、新产品进入 `other_info`", prompt)
        self.assertIn("other_info（兜底字段）处理规则", prompt)
        self.assertIn("`other_info[].title` 必须使用中文", prompt)
        self.assertIn("`other_info[].content` 如果是产品对象数组，必须使用后端约定的稳定英文字段 key", prompt)
        self.assertIn("如果原文对该荣誉给出具体年月日或年月，必须保留具体时间", prompt)
        self.assertIn("例如 `2023年12月12日`，不要简化成 `2023`", prompt)
        self.assertNotIn("对应中文展示名由接口 field_labels 返回", prompt)
        self.assertIn("下面是常见中文字段、同义词与 JSON 输出字段路径的对应关系", prompt)
        self.assertIn("# 字段归属参考字典", prompt)
        self.assertIn("数组字段没有可抽取内容时，必须输出 `[]`，不要输出空模板对象", prompt)
        self.assertIn("严禁使用 `null`", prompt)
        self.assertIn("`official_malls` 与 `official_media_matrix` 必须互斥", prompt)
        self.assertIn("媒体账号、内容平台账号", prompt)
        self.assertIn("- 股票/上市信息、上市信息、股票代码、证券代码、上市地点、上市日期 -> company_profile.stock_info", prompt)
        self.assertIn("核心高管、创始人、董事长、副董事长、总裁、CEO、管理团队 -> management_team[].member_name / management_team[].position", prompt)
        self.assertIn("- 官网地址、官网、官方网站、品牌官网、官网链接 -> basic_info.website", prompt)
        self.assertIn("- 产品名称、产品标准名、商品名称、SKU 名称、服务名称 -> products[].name", prompt)
        self.assertIn("- 价格、规格、包装规格、售价、价格体系、套餐价、月套餐、年套餐 -> products[].price_info", prompt)
        self.assertIn("- 服务流程、服务 SOP、流程节点、使用流程、购买流程 -> products[].service_process", prompt)
        self.assertIn("- 微信公众号、微信视频号、视频号、抖音号、小红书、微博、搜狐号、头条号、百家号、网易号、B站、快手、官方账号、媒体矩阵、内容平台账号 -> official_media_matrix[].media_platform / official_media_matrix[].account_name", prompt)
        self.assertIn("术语表", prompt)
        self.assertIn("-> other_info", prompt)
        self.assertNotIn("EXTRACTION_FIELD_HINTS", prompt)
        self.assertNotIn("products[].base_info", prompt)
        self.assertNotIn("products[].knowledge", prompt)


if __name__ == "__main__":
    unittest.main()
