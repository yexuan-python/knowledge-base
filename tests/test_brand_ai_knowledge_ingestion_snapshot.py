from __future__ import annotations

from tests.fakes.brand_ai_ingestion import *


class BrandAiKnowledgeIngestionSnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_extract_snapshot_resolves_product_description_reference_from_markdown_table(self) -> None:
        markdown_text = """
### **3.2 详细产品列表 (来自产品资料整理.xlsx)**

|序号|风格|产品名称|产品特点概要|使用场景|
|---|---|---|---|---|
|1|意式轻奢|云系565 Targa|极光银等花色，超跑曲线门型，艺术中岛。|全屋定制|
|2|法式中古风|峰系365·峰絮|“焦糖拿铁色”基调，法式复古，J/U创意拉手，亚光黑色烤漆。|全屋定制|
""".strip()

        async def _fake_extract_markdown(*args, **kwargs):
            return {
                "basic_info": {"brand_name": "示例品牌"},
                "products": [
                    {
                        "name": "云系565 (Targa/云缦)",
                        "product_description": "详情见3.2产品1",
                        "coverage_regions": ["全国"],
                    }
                ],
                "company_profile": {},
                "management_team": [],
                "competitors": [],
                "authority_honors": [],
                "customers_cases": [],
                "sensitive_topics": {},
                "attachments": [],
                "official_malls": [],
                "official_media_matrix": [],
                "other_info": [],
            }

        extraction_module = sys.modules[_MODULE.extract_brand_knowledge_snapshot_from_markdown.__module__]
        original_extract = extraction_module.extract_brand_knowledge_from_markdown
        extraction_module.extract_brand_knowledge_from_markdown = _fake_extract_markdown
        try:
            snapshot = await extraction_module.extract_brand_knowledge_snapshot_from_markdown(
                brand_name="示例品牌",
                markdown_text=markdown_text,
                source_name="【示例品牌】品牌AI知识库_V1_20260715.md",
                settings=types.SimpleNamespace(),
            )
        finally:
            extraction_module.extract_brand_knowledge_from_markdown = original_extract

        self.assertEqual(
            "极光银等花色，超跑曲线门型，艺术中岛。",
            snapshot["attachment_products"][0]["product_description"],
        )
        self.assertEqual(["全国"], snapshot["attachment_products"][0]["coverage_regions"])

    async def test_extract_snapshot_sets_unresolved_product_description_reference_to_none(self) -> None:
        markdown_text = """
### **3.2 详细产品列表 (来自产品资料整理.xlsx)**

|序号|风格|产品名称|产品特点概要|使用场景|
|---|---|---|---|---|
|1|意式轻奢|云系565 Targa|极光银等花色，超跑曲线门型，艺术中岛。|全屋定制|
""".strip()

        async def _fake_extract_markdown(*args, **kwargs):
            return {
                "basic_info": {"brand_name": "示例品牌"},
                "products": [
                    {
                        "name": "云系565 (Targa/云缦)",
                        "product_description": "详情见3.2产品9",
                        "coverage_regions": ["全国"],
                    }
                ],
                "company_profile": {},
                "management_team": [],
                "competitors": [],
                "authority_honors": [],
                "customers_cases": [],
                "sensitive_topics": {},
                "attachments": [],
                "official_malls": [],
                "official_media_matrix": [],
                "other_info": [],
            }

        extraction_module = sys.modules[_MODULE.extract_brand_knowledge_snapshot_from_markdown.__module__]
        original_extract = extraction_module.extract_brand_knowledge_from_markdown
        extraction_module.extract_brand_knowledge_from_markdown = _fake_extract_markdown
        try:
            snapshot = await extraction_module.extract_brand_knowledge_snapshot_from_markdown(
                brand_name="示例品牌",
                markdown_text=markdown_text,
                source_name="【示例品牌】品牌AI知识库_V1_20260715.md",
                settings=types.SimpleNamespace(),
            )
        finally:
            extraction_module.extract_brand_knowledge_from_markdown = original_extract

        self.assertIsNone(snapshot["attachment_products"][0]["product_description"])

    async def test_extract_snapshot_fills_missing_product_description_from_markdown_product_block(self) -> None:
        markdown_text = """
### **3.5 零售主推的产品价格和套餐**

- **金牌实木多层板新品 899元/㎡**

- **产品配置**:

- 基础配置：单㎡定制衣柜（门板、柜体、标配五金）

- 五金：T级拉手+B标阻尼铰链

- 柜体含9毫米颗粒板背板

- **板材优势**:

- 板材原料采用天然优质桉木

- **金牌爆品烤漆厨房套餐 9999元**

- **套餐配置**:

- 基础配置：3米地柜+3米台面（金牌石英石台面）+1米吊柜

- 门板配置：烤漆门板，4款花色可选

- 洗涤配置：金牌水槽+龙头

- **烤漆优势**:

- 金牌首创，22道极致烤漆工艺

- **全年套餐：29800元品质全屋套餐**

- **套餐配置**: 7m厨柜+20㎡定制衣柜＋2樘木门+6㎡时尚背景墙

- **厨柜配置**：3米地柜+3米台面（金牌石英石台面）+1米吊柜

- 厨柜材质：经典美耐板

- **衣柜配置**：20㎡定制衣柜含五金

- 衣柜材质：经典美耐板

- **套餐优势**:

- ENF级环保标准
""".strip()

        async def _fake_extract_markdown(*args, **kwargs):
            return {
                "basic_info": {"brand_name": "示例品牌"},
                "products": [
                    {
                        "name": "金牌实木多层板新品",
                        "product_description": None,
                    },
                    {
                        "name": "金牌爆品烤漆厨房套餐",
                        "product_description": None,
                    },
                    {
                        "name": "全年套餐:29800元品质全屋套餐",
                        "product_description": None,
                    },
                ],
                "company_profile": {},
                "management_team": [],
                "competitors": [],
                "authority_honors": [],
                "customers_cases": [],
                "sensitive_topics": {},
                "attachments": [],
                "official_malls": [],
                "official_media_matrix": [],
                "other_info": [],
            }

        extraction_module = sys.modules[_MODULE.extract_brand_knowledge_snapshot_from_markdown.__module__]
        original_extract = extraction_module.extract_brand_knowledge_from_markdown
        extraction_module.extract_brand_knowledge_from_markdown = _fake_extract_markdown
        try:
            snapshot = await extraction_module.extract_brand_knowledge_snapshot_from_markdown(
                brand_name="示例品牌",
                markdown_text=markdown_text,
                source_name="【示例品牌】品牌AI知识库_V1_20260715.md",
                settings=types.SimpleNamespace(),
            )
        finally:
            extraction_module.extract_brand_knowledge_from_markdown = original_extract

        self.assertEqual(
            "基础配置：单㎡定制衣柜（门板、柜体、标配五金）；五金：T级拉手+B标阻尼铰链；柜体含9毫米颗粒板背板",
            snapshot["attachment_products"][0]["product_description"],
        )
        self.assertEqual(
            "基础配置：3米地柜+3米台面（金牌石英石台面）+1米吊柜；门板配置：烤漆门板，4款花色可选；洗涤配置：金牌水槽+龙头",
            snapshot["attachment_products"][1]["product_description"],
        )
        self.assertEqual(
            "套餐配置：7m厨柜+20㎡定制衣柜＋2樘木门+6㎡时尚背景墙；厨柜配置：3米地柜+3米台面（金牌石英石台面）+1米吊柜；厨柜材质：经典美耐板；衣柜配置：20㎡定制衣柜含五金；衣柜材质：经典美耐板",
            snapshot["attachment_products"][2]["product_description"],
        )


if __name__ == "__main__":
    unittest.main()
