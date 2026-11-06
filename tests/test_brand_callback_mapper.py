from __future__ import annotations

import json
import unittest

from knowledge_base.brand.callback_mapper import format_brand_callback_knowledge_from_snapshot


class BrandCallbackMapperTests(unittest.TestCase):
    def test_callback_other_info_keeps_same_title_with_different_content(self) -> None:
        payload = format_brand_callback_knowledge_from_snapshot(
            brand={"brand_name": "示例品牌", "industry_id": 1},
            knowledge_snapshot={
                "other_info": [
                    {
                        "title": "功能性优势",
                        "content": "夏季版本",
                    },
                    {
                        "title": "功能性优势",
                        "content": "冬季版本",
                    },
                ],
            },
        )

        self.assertEqual(
            payload["other_info"],
            [
                {
                    "title": "功能性优势",
                    "content": "夏季版本",
                },
                {
                    "title": "功能性优势",
                    "content": "冬季版本",
                },
            ],
        )

    def test_callback_other_info_filters_empty_and_standard_covered_titles(self) -> None:
        payload = format_brand_callback_knowledge_from_snapshot(
            brand={
                "brand_name": "校园及第",
                "brand_alias": "校园及第、及第校服",
                "website": "fjdgtex.com",
                "official_wechat_account": "校园及第",
                "intro": "一句话品牌简介",
                "positioning": ["校服精工专家"],
                "advantages": ["安全舒适"],
                "target_regions_json": ["全国", "福建"],
            },
            knowledge_snapshot={
                "basic_info": {
                    "website": ["https://www.fjdgtex.com"],
                    "english_name": "Campus First",
                },
                "company_profile": {
                    "brand_subject_name": "福建及第校服有限公司",
                    "company_intro": "标准公司简介",
                    "company_address": ["福建省福州市仓山区"],
                    "established_time": "2018年",
                    "development_history": ["2018年成立品牌"],
                    "recent_news": ["https://example.com/news"],
                },
                "management_team": [
                    {
                        "member_name": "马海朝",
                        "position": "创始人",
                        "profile": "负责品牌战略与经营管理",
                    }
                ],
                "authority_honors": [{"title": "高新技术企业"}],
                "official_media_matrix": [
                    {
                        "media_platform": "抖音号",
                        "account_name": "校园及第",
                    }
                ],
                "competitors": [
                    {
                        "name": "竞品A",
                        "comparison_dimensions": ["原有对比维度"],
                        "differentiated_positioning": ["原有差异化定位"],
                    }
                ],
                "attachment_products": [
                    {
                        "name": "夏季系列",
                        "product_description": "短袖POLO衫、短裤",
                    }
                ],
                "other_info": [
                    {"title": "品牌英文名", "content": "(空)"},
                    {"title": "服务据点/展厅", "content": "(空)"},
                    {"title": "官方宣传物料", "content": "详情见附件"},
                    {"title": "附件解析新增产品", "content": [{"name": "夏季系列"}]},
                    {"title": "1.1 品牌基础身份", "content": "品牌标准名：校园及第"},
                    {"title": "1.2 官方阵地", "content": "官网地址：fjdgtex.com"},
                    {"title": "一、品牌 / 公司实体", "content": "品牌标准名：校园及第；公司主体：福建及第校服有限公司"},
                    {"title": "三、官方阵地", "content": "官网地址：www.fjdgtex.com；公众号：校园及第"},
                    {"title": "四、品牌档案", "content": "品牌定位：校服精工专家；品牌英文名：Campus First"},
                    {"title": "五、公司档案", "content": "公司简介：标准公司简介；总部：福建省福州市仓山区"},
                    {"title": "马海朝", "content": "创始人，负责品牌战略与经营管理"},
                    {"title": "品牌定位(positioning)", "content": "校服精工专家"},
                    {"title": "一句话简介(one_liner)", "content": "一句话品牌简介"},
                    {"title": "核心价值主张", "content": "安全舒适"},
                    {"title": "目标区域", "content": "全国,福建"},
                    {"title": "品牌故事/发展里程碑", "content": "2018年成立品牌"},
                    {"title": "公司简介", "content": "标准公司简介"},
                    {"title": "公司所获荣誉", "content": "高新技术企业"},
                    {"title": "公司近期新闻", "content": "https://example.com/news"},
                    {"title": "2.1 产品线(主推)", "content": "夏季系列"},
                    {"title": "4.3 竞品多维对比", "content": "| 对比维度 | 校园及第 |\n| --- | --- |\n| 面料体感 | 原纱冰感 |"},
                    {"title": "4.4 优劣势对比", "content": "* **差异化\"护城河\"**:本土快反\n* 对比规则(允许对比的维度1/2):(空)"},
                    {"title": "三、重点宣传方向", "content": "*销售希望多宣传的六大方向。*"},
                    {"title": "八、案例、口碑与深度知识", "content": "| 维度 | 内容 |\n| --- | --- |\n| 案例与素材 1/2/3 | (空) |\n| 好评素材包 | (空) |\n| 官方宣传物料 | 详情见附件 |"},
                    {"title": "十、视觉资产与安全边界", "content": "| 维度 | 字段 | 内容 |\n| --- | --- | --- |\n| 视觉资产 | 品牌视觉元素 | (空) |\n| 安全边界 | 禁忌元素/敏感内容 | (空) |"},
                    {"title": "五、高频问答 FAQ", "content": "Q:支持补购吗?\nA:支持。"},
                ],
            },
        )

        self.assertEqual(
            payload["other_info"],
            [
                {"title": "附件解析新增产品", "content": [{"name": "夏季系列"}]},
                {"title": "五、高频问答 FAQ", "content": "Q:支持补购吗?\nA:支持。"},
            ],
        )
        self.assertEqual(
            payload["competitors"]["competitors"][0]["comparison_dimensions"],
            ["原有对比维度"],
        )
        self.assertEqual(
            payload["competitors"]["competitors"][0]["differentiated_positioning"],
            ["原有差异化定位"],
        )

    def test_callback_basic_info_keeps_brand_long_text_fields_as_full_sentences(self) -> None:
        payload = format_brand_callback_knowledge_from_snapshot(
            brand={
                "brand_name": "灵犀智擎",
                "positioning": json.dumps(
                    [
                        "中国领先的原生AI营销技术公司",
                        "端到端，一站式的AI营销Agent服务体系",
                    ],
                    ensure_ascii=False,
                ),
                "advantages": json.dumps(
                    [
                        "AI数字资产沉淀（知识库，内容矩阵，AI官网，AI百科）",
                        "转化归因承接（推荐，留资，线索到成交闭环）",
                    ],
                    ensure_ascii=False,
                ),
                "mission": json.dumps(
                    [
                        "成为企业在 AI 世界中不可替代的增长基础设施。",
                    ],
                    ensure_ascii=False,
                ),
                "vision": json.dumps(
                    [
                        "让品牌赢在AI时代",
                    ],
                    ensure_ascii=False,
                ),
            },
            knowledge_snapshot={},
        )

        self.assertEqual(
            payload["basic_info"]["extra_info"]["brand_positioning"],
            [
                "中国领先的原生AI营销技术公司",
                "端到端，一站式的AI营销Agent服务体系",
            ],
        )
        self.assertEqual(
            payload["basic_info"]["extra_info"]["brand_advantage"],
            [
                "AI数字资产沉淀（知识库，内容矩阵，AI官网，AI百科）",
                "转化归因承接（推荐，留资，线索到成交闭环）",
            ],
        )
        self.assertEqual(
            payload["basic_info"]["extra_info"]["brand_mission"],
            ["成为企业在 AI 世界中不可替代的增长基础设施。"],
        )
        self.assertEqual(
            payload["basic_info"]["extra_info"]["brand_vision"],
            ["让品牌赢在AI时代"],
        )

    def test_callback_basic_info_display_dedupes_punctuation_only_variants(self) -> None:
        payload = format_brand_callback_knowledge_from_snapshot(
            brand={
                "brand_name": "灵犀智擎",
                "positioning": json.dumps(
                    [
                        '中国领先的原生AI营销技术公司,中国GEO服务先行者；面向AI生成式搜索与AI智能问答的品牌数字资产优化服务商；AIBE可信资产建设者、AIBV标准共建者；端到端、一站式的AI营销Agent服务体系；规模化、结果级的AI视频生产工厂,为企业提供"专属AI视频部"。',
                        '中国领先的原生AI营销技术公司，中国GEO服务先行者；面向AI生成式搜索与AI智能问答的品牌数字资产优化服务商；AIBE可信资产建设者、AIBV标准共建者；端到端、一站式的AI营销Agent服务体系；规模化、结果级的AI视频生产工厂，为企业提供“专属AI视频部”。',
                    ],
                    ensure_ascii=False,
                ),
                "advantages": json.dumps(
                    [
                        "量化式交付,10v1 专属服务",
                        "量化式交付，10v1 专属服务",
                    ],
                    ensure_ascii=False,
                ),
                "mission": json.dumps(
                    [
                        "让AI在回答用户时,主动推荐您的品牌",
                        "让AI在回答用户时，主动推荐您的品牌",
                    ],
                    ensure_ascii=False,
                ),
                "vision": json.dumps(
                    [
                        "成为企业在 AI 世界中不可替代的增长基础设施",
                        "成为企业在 AI 世界中不可替代的增长基础设施",
                    ],
                    ensure_ascii=False,
                ),
            },
            knowledge_snapshot={},
        )

        self.assertEqual(
            payload["basic_info"]["extra_info"]["brand_positioning"],
            [
                '中国领先的原生AI营销技术公司,中国GEO服务先行者；面向AI生成式搜索与AI智能问答的品牌数字资产优化服务商；AIBE可信资产建设者、AIBV标准共建者；端到端、一站式的AI营销Agent服务体系；规模化、结果级的AI视频生产工厂,为企业提供"专属AI视频部"。',
            ],
        )
        self.assertEqual(
            payload["basic_info"]["extra_info"]["brand_advantage"],
            ["量化式交付,10v1 专属服务"],
        )
        self.assertEqual(
            payload["basic_info"]["extra_info"]["brand_mission"],
            ["让AI在回答用户时,主动推荐您的品牌"],
        )
        self.assertEqual(
            payload["basic_info"]["extra_info"]["brand_vision"],
            ["成为企业在 AI 世界中不可替代的增长基础设施"],
        )

    def test_callback_company_profile_development_history_keeps_newline_only_split(self) -> None:
        payload = format_brand_callback_knowledge_from_snapshot(
            brand={"brand_name": "校园及第"},
            knowledge_snapshot={
                "company_profile": {
                    "development_history": "2018年成立品牌；开启业务\n2020年扩产，新增基地",
                }
            },
        )

        self.assertEqual(
            payload["company_profile"]["development_history"],
            ["2018年成立品牌；开启业务", "2020年扩产，新增基地"],
        )

    def test_callback_basic_info_normalizes_and_dedupes_websites(self) -> None:
        payload = format_brand_callback_knowledge_from_snapshot(
            brand={
                "brand_name": "示例品牌",
                "website": "[\"HTTPS://WWW.DINOSAURODYSSEY.COM/visit?scene=tickets#map\"]",
            },
            knowledge_snapshot={
                "basic_info": {
                    "website": [
                        "https://www.dinosaurodyssey.com/visit?scene=tickets&utm_source=wechat",
                    ],
                }
            },
        )

        self.assertEqual(
            payload["basic_info"]["website"],
            ["https://www.dinosaurodyssey.com/visit?scene=tickets"],
        )

    def test_callback_basic_info_merges_http_https_and_www_but_keeps_mobile_subdomain(self) -> None:
        payload = format_brand_callback_knowledge_from_snapshot(
            brand={
                "brand_name": "嘉和康养",
                "website": "[\"http://www.jiahecare.com/\"]",
            },
            knowledge_snapshot={
                "basic_info": {
                    "website": [
                        "https://jiahecare.com/",
                        "https://m.jiahecare.com",
                    ],
                }
            },
        )

        self.assertEqual(
            payload["basic_info"]["website"],
            ["https://www.jiahecare.com", "https://m.jiahecare.com"],
        )

    def test_callback_other_info_keeps_competitor_sections_when_not_structured(self) -> None:
        payload = format_brand_callback_knowledge_from_snapshot(
            brand={"brand_name": "校园及第"},
            knowledge_snapshot={
                "competitors": [
                    {
                        "name": "竞品A",
                    }
                ],
                "other_info": [
                    {"title": "4.3 竞品多维对比", "content": "| 对比维度 | 校园及第 |\n| --- | --- |\n| 面料体感 | 原纱冰感 |"},
                    {"title": "4.4 优劣势对比", "content": "* **差异化\"护城河\"**:本土快反"},
                ],
            },
        )

        self.assertEqual(
            payload["other_info"],
            [
                {"title": "4.3 竞品多维对比", "content": "| 对比维度 | 校园及第 |\n| --- | --- |\n| 面料体感 | 原纱冰感 |"},
                {"title": "4.4 优劣势对比", "content": "* **差异化\"护城河\"**:本土快反"},
            ],
        )
        self.assertEqual(payload["competitors"]["competitors"][0]["comparison_dimensions"], [])
        self.assertEqual(payload["competitors"]["competitors"][0]["differentiated_positioning"], [])


if __name__ == "__main__":
    unittest.main()
