from __future__ import annotations

import types
import unittest
from unittest.mock import AsyncMock

from knowledge_base.brand_knowledge.application import AttachmentDraftDependencies, AttachmentDraftService

from tests.fakes.brand_flow import (
    FakeBrandKnowledgeStore,
    FakeBrandProductStore,
    FakeBrandStore,
    FakeSettings,
)


class AttachmentPreviewStructuredTests(unittest.TestCase):
    def test_attachment_preview_extracts_structured_candidate_from_xlsx_markdown(self) -> None:
        service = AttachmentDraftService(
            AttachmentDraftDependencies(
                settings=FakeSettings(),
                parser=None,
                oss_client=types.SimpleNamespace(enabled=False),
                brands=FakeBrandStore(),
                brand_products=FakeBrandProductStore(),
                brand_knowledge=FakeBrandKnowledgeStore(),
                update_knowledge=AsyncMock(),
            )
        )
        markdown_text = """# Sheet: 「品牌知识库」

| 核心维度 | 字段名称 | 填写具体内容（客户填写） |
| --- | --- | --- |
| 品牌/公司实体 | 品牌标准名 | 厦门示例品牌股份有限公司+示例品牌 |
| 官方阵地 | 官网地址 | https://www.example.com/ |
| 官方阵地 | 官方账号—搜狐号 | 示例品牌<br>https://mp.sohu.com/profile/demo |
| 基础身份 | 核心高管/创始人 | 创始人、董事长 张三<br>总裁 李四 |

# Sheet: 核心产品清单

| 序号 | 产品线 | 产品名 | 原料体系 | 营养成分 | 配料与安全 |
| --- | --- | --- | --- | --- | --- |
|  |  |  | 燕窝原产地 | 燕窝投料量 | 配料表 |
| 1 | 碗燕 | 碗燕尊享款 | 印度尼西亚 | ≥6.7g/碗 | 纯净水、燕窝、有机冰糖 |

# Sheet: 权威背书资料

| 类目 | 出处/证明 | 图片 |
| --- | --- | --- |
| 中国燕窝行业首家上市公司 | 2023年12月12日上市，详见 https://www.hkexnews.hk/index_c.htm |  |

# Sheet: 备注

这里是未结构化的补充说明。
"""

        snapshot, residual_markdown = service._extract_structured_candidate_from_xlsx_markdown(
            markdown_text=markdown_text,
            brand_name="示例品牌",
            brand_code="BRAND-001",
        )

        self.assertEqual(snapshot["basic_info"]["brand_name"], "示例品牌")
        self.assertEqual(snapshot["company_profile"]["brand_subject_name"], "厦门示例品牌股份有限公司")
        self.assertEqual(snapshot["basic_info"]["website"], ["https://www.example.com/"])
        self.assertEqual(snapshot["management_team"][0]["name"], "张三")
        self.assertEqual(snapshot["management_team"][1]["title"], "总裁")
        self.assertEqual(snapshot["official_media_matrix"][0]["media_platform"], "搜狐号")
        self.assertEqual(snapshot["official_media_matrix"][0]["account_name"], "示例品牌")
        self.assertEqual(snapshot["products"][0]["name"], "碗燕尊享款")
        self.assertIn("原料体系 燕窝原产地：印度尼西亚", snapshot["products"][0]["other_info"])
        self.assertEqual(snapshot["authority_honors"][0]["title"], "中国燕窝行业首家上市公司")
        self.assertIn("https://www.hkexnews.hk/index_c.htm", snapshot["authority_honors"][0]["report_link"])
        self.assertIn("# Sheet: 备注", residual_markdown)
        self.assertNotIn("# Sheet: 「品牌知识库」", residual_markdown)
        self.assertNotIn("# Sheet: 核心产品清单", residual_markdown)

    def test_attachment_preview_structured_enhancement_keeps_non_xlsx_markdown_in_residual(self) -> None:
        service = AttachmentDraftService(
            AttachmentDraftDependencies(
                settings=FakeSettings(),
                parser=None,
                oss_client=types.SimpleNamespace(enabled=False),
                brands=FakeBrandStore(),
                brand_products=FakeBrandProductStore(),
                brand_knowledge=FakeBrandKnowledgeStore(),
                update_knowledge=AsyncMock(),
            )
        )
        parsed_items = [
            {
                "status": "success",
                "source_type": "xlsx",
                "markdown_text": """# Sheet: 「品牌知识库」

| 核心维度 | 字段名称 | 填写具体内容（客户填写） |
| --- | --- | --- |
| 官方阵地 | 官网地址 | https://www.example.com/ |
""",
            },
            {
                "status": "success",
                "source_type": "pdf",
                "markdown_text": "# PDF\n\n这是 pdf 补充内容。",
            },
        ]

        snapshot, residual_markdown = service._extract_structured_candidate_from_parsed_items(
            parsed_items=parsed_items,
            brand_name="示例品牌",
            brand_code="BRAND-001",
        )

        self.assertEqual(snapshot["basic_info"]["website"], ["https://www.example.com/"])
        self.assertIn("# PDF", residual_markdown)
        self.assertNotIn("官网地址", residual_markdown)

    def test_attachment_preview_structured_enhancement_restores_competitors_sensitive_topics_and_media_split(self) -> None:
        service = AttachmentDraftService(
            AttachmentDraftDependencies(
                settings=FakeSettings(),
                parser=None,
                oss_client=types.SimpleNamespace(enabled=False),
                brands=FakeBrandStore(),
                brand_products=FakeBrandProductStore(),
                brand_knowledge=FakeBrandKnowledgeStore(),
                update_knowledge=AsyncMock(),
            )
        )
        markdown_text = """# Sheet: 「品牌知识库」

| 核心维度 | 字段名称 | 填写具体内容（客户填写） |
| --- | --- | --- |
| 竞品信息 | 主要竞争对手 1 | 小仙炖 |
| 竞品信息 | 主要竞争对手 2 | 同仁堂 |
| 竞品信息 | 允许对比的维度1 | 工艺/专利：115°C精炖锁鲜工艺\\n品牌历史：28年专注高品质燕窝 |
| 风险边界 | 禁忌元素/敏感内容 | 1、行业危机事件(血燕、血燕事件)\\n2、功效相关\\n3、不得诋毁、拉踩友商\\n4、极限词(我们有证书、出处的可以说) |
| 官方阵地 | 官方账号 | 燕之屋\\nhttps://mp.sohu.com/profile/demo\\nhttps://www.toutiao.com/c/user/token/demo\\nhttps://www.douyin.com/user/demo |
| 权威背书 | 权威背书资料(原件/链接/可核验出处) | 详见【权威背书资料】 |
| 权威背书 | 燕之屋 中国燕窝行业首家上市公司 | 2023年12月12日上市，详见 https://www.hkexnews.hk/index_c.htm |
| 品牌资料 | 公司近期新闻 | https://www.yanzhiwu.com/news.html |
| 品牌资料 | 品牌故事/发展里程碑 | 品牌简介:https://www.yanzhiwu.com/brand.html\\n品牌历程:https://www.yanzhiwu.com/history.html |

# Sheet: 核心产品清单

| 序号 | 产品线 | 产品名 | 价格 | 工艺专利 | 适用场景 |
| --- | --- | --- | --- | --- | --- |
| 1 | 碗燕 | 碗燕尊享款 | 2998元/盒(158g*6碗) | 121°C萃火工艺 | 孕妇 |
"""

        snapshot, _ = service._extract_structured_candidate_from_xlsx_markdown(
            markdown_text=markdown_text,
            brand_name="示例品牌",
            brand_code="BRAND-001",
        )

        self.assertEqual([item["name"] for item in snapshot["competitors"]], ["小仙炖", "同仁堂"])
        self.assertIn("工艺/专利：115°C精炖锁鲜工艺", snapshot["competitors"][0]["comparison_dimensions"])
        self.assertIn("品牌历史：28年专注高品质燕窝", snapshot["competitors"][0]["comparison_dimensions"])
        self.assertIn("行业危机事件(血燕、血燕事件)", snapshot["sensitive_topics"]["controversial_events"])
        self.assertIn("功效相关", snapshot["sensitive_topics"]["sensitive_contents"])
        self.assertIn("极限词(我们有证书、出处的可以说)", snapshot["sensitive_topics"]["forbidden_words"])
        self.assertEqual(
            [item["media_platform"] for item in snapshot["official_media_matrix"]],
            ["搜狐号", "头条号", "抖音"],
        )
        self.assertNotIn("权威背书资料(原件/链接/可核验出处)", [item["title"] for item in snapshot.get("authority_honors", [])])
        self.assertEqual(snapshot["company_profile"]["recent_news"], "https://www.yanzhiwu.com/news.html")
        self.assertIn("品牌历程:https://www.yanzhiwu.com/history.html", snapshot["company_profile"]["development_history"])

    def test_attachment_preview_refines_other_info_into_competitor_fields_and_keeps_media_accounts_split(self) -> None:
        service = AttachmentDraftService(
            AttachmentDraftDependencies(
                settings=FakeSettings(),
                parser=None,
                oss_client=types.SimpleNamespace(enabled=False),
                brands=FakeBrandStore(),
                brand_products=FakeBrandProductStore(),
                brand_knowledge=FakeBrandKnowledgeStore(),
                update_knowledge=AsyncMock(),
            )
        )
        snapshot = service._refine_preview_candidate_snapshot(
            {
                "basic_info": {
                    "brand_name": "示例品牌",
                    "advantages": "高端燕窝连续十年销售第一\n详见【权威背书资料】",
                },
                "competitors": [
                    {
                        "name": "小仙炖",
                        "comparison_dimensions": ["工艺对比"],
                    },
                    {
                        "name": "同仁堂",
                        "comparison_dimensions": ["滋养力对比"],
                    },
                ],
                "authority_honors": [
                    {
                        "title": "示例荣誉",
                        "description": "出处/证明：2023年12月12日获奖\n*备注: 来源机构A",
                    }
                ],
                "official_media_matrix": service._merge_snapshot(
                    current_snapshot={
                        "official_media_matrix": [
                            {"media_platform": "搜狐号", "account_name": "燕之屋", "homepage_urls": ["https://mp.sohu.com/profile/demo"]},
                        ]
                    },
                    candidate_snapshot={
                        "official_media_matrix": [
                            {"media_platform": "抖音", "account_name": "燕之屋", "homepage_urls": ["https://www.douyin.com/user/demo"]},
                        ]
                    },
                ).get("official_media_matrix"),
                "other_info": [
                    {"title": "主张与证据1", "content": "燕之屋高端燕窝 连续10年全国销售第一"},
                    {"title": "主张与证据2", "content": "燕之屋 燕窝行业标准牵头起草者和制定者"},
                    {"title": "主张与证据3", "content": "燕之屋 常温鲜炖燕窝开创者\n燕之屋 精炖燕窝开创者"},
                    {"title": "核心产品优势", "content": "中国燕窝行业首家上市企业"},
                    {"title": "差异化“护城河”", "content": "28年专注高品质燕窝"},
                    {"title": "选择品牌类", "content": "详见「权威背书资料」"},
                    {"title": "价格/套餐", "content": "详见「核心产品清单」"},
                    {"title": "售后/质保", "content": "破损赔偿\n质保时间详见「核心产品清单」"},
                    {"title": "品牌资料下载", "content": "20260702燕之屋品牌资料\n链接: https://pan.baidu.com/s/xxx 提取码: 9999"},
                    {"title": "内部资料包", "content": "品牌培训素材\n链接: https://pan.baidu.com/s/yyy?pwd=8888 提取码: 8888"},
                    {"title": "分支机构 / 办事处清单(可以是 excel)", "content": "https://www.example.com/network"},
                ],
            }
        )

        self.assertEqual(len(snapshot["official_media_matrix"]), 2)
        self.assertEqual(snapshot["basic_info"]["advantages"], ["高端燕窝连续十年销售第一"])
        self.assertEqual(len(snapshot["competitors"][0]["strengths"]), 1)
        self.assertEqual(len(snapshot["competitors"][1]["strengths"]), 1)
        strengths_summary = snapshot["competitors"][0]["strengths"][0]
        self.assertIn("燕之屋高端燕窝连续10年全国销售第一", strengths_summary)
        self.assertIn("中国燕窝行业首家上市企业", snapshot["competitors"][1]["strengths"][0])
        self.assertIn("燕之屋常温鲜炖燕窝开创者", strengths_summary)
        self.assertIn("燕之屋精炖燕窝开创者", strengths_summary)
        self.assertEqual(snapshot["competitors"][0]["differentiated_positioning"], ["28年专注高品质燕窝"])
        self.assertEqual(snapshot["authority_honors"][0]["description"], "2023年12月12日获奖\n来源机构A")
        self.assertNotIn("选择品牌类", [item["title"] for item in snapshot.get("other_info", [])])
        self.assertNotIn("价格/套餐", [item["title"] for item in snapshot.get("other_info", [])])
        self.assertNotIn("售后/质保", [item["title"] for item in snapshot.get("other_info", [])])
        self.assertNotIn("品牌资料下载", [item["title"] for item in snapshot.get("other_info", [])])
        self.assertNotIn("内部资料包", [item["title"] for item in snapshot.get("other_info", [])])
        self.assertIn("分支机构 / 办事处清单", [item["title"] for item in snapshot.get("other_info", [])])
        self.assertNotIn("分支机构 / 办事处清单(可以是 excel)", [item["title"] for item in snapshot.get("other_info", [])])
