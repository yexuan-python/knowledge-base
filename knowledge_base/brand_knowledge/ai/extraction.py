from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import urlsplit

from dashscope import Generation

from knowledge_base.brand_knowledge.field_hints import build_hint_lines
from knowledge_base.infrastructure.llm import (
    extract_json_value,
    get_dashscope_api_key,
    require_settings,
)
from knowledge_base.infrastructure.settings import Settings


_HTML_BREAK_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]\n]{1,500})\]\(([^)\n]{1,1500})\)")
_MALFORMED_HTTP_SCHEME_RE = re.compile(r"\b(https?):/(?!/)")
_RAW_LOCAL_PATH_MARKERS = (
    "/Users/",
    "\\Users\\",
    "%5C",
    "%5c",
    "%22",
    "%27",
)


def _repair_url_text(value: str) -> str:
    candidate = str(value or "").strip().strip("<>\"'")
    candidate = _MALFORMED_HTTP_SCHEME_RE.sub(r"\1://", candidate)
    return candidate.strip().strip("<>\"'")


def _is_safe_http_url(value: str) -> bool:
    candidate = _repair_url_text(value)
    if not candidate:
        return False
    if any(marker in candidate for marker in _RAW_LOCAL_PATH_MARKERS):
        return False
    if any(char.isspace() for char in candidate):
        return False
    parsed = urlsplit(candidate)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _sanitize_markdown_urls_for_text_llm(markdown_text: str) -> str:
    """Keep URL facts readable without letting model services validate broken links."""

    def replace_markdown_link(match: re.Match[str]) -> str:
        label = match.group(1).strip()
        href = match.group(2).strip()

        repaired_label = _repair_url_text(label)
        if _is_safe_http_url(repaired_label):
            return repaired_label

        repaired_href = _repair_url_text(href)
        if _is_safe_http_url(repaired_href):
            return f"{label}（链接：{repaired_href}）" if label else repaired_href

        return label or href

    sanitized = _MARKDOWN_LINK_RE.sub(replace_markdown_link, str(markdown_text or ""))
    sanitized = _HTML_BREAK_RE.sub("\n", sanitized)
    sanitized = _MALFORMED_HTTP_SCHEME_RE.sub(r"\1://", sanitized)
    return sanitized.strip()


HINTS_LIST = build_hint_lines()


PROMPT_TEMPLATE = """
# 角色与目标
你是一名专业的品牌知识抽取助手。请只根据提供的 Markdown 文本，精准抽取品牌知识，并严格输出一个纯 JSON 对象。

# 任务上下文
- 品牌名称：{brand_name}
- 文件名称：{source_name}
- 子分类 / 产品线：{subcategory}

# 核心抽取规则（必须严格遵守）
1. 绝对忠于原文：
   - 只能提取原文中明确出现的信息。
   - 缺失字段留空、输出空数组或空对象。
   - 绝对不要编造或推断。

2. 附件内容覆盖要求：
   - 附件解析要尽量覆盖 Markdown 原文中的全部有效信息。
   - 不要因为找不到标准字段就丢弃原文信息。
   - 能归入标准字段的信息，必须优先归入对应字段。
   - 无法明确归入任何标准字段的信息，放入最合适层级的 `other_info`。

3. 数组格式强制要求：
   - 以下字段必须输出为数组；即使只有一个值，也要输出成单元素数组：
     - `basic_info.website`
     - `basic_info.target_regions`
     - `products[].product_images`
     - `products[].coverage_regions`
     - `customers_cases[].related_products`
     - `official_malls[].homepage_urls`
     - `official_malls[].store_ids`
     - `official_malls[].main_categories`
     - `official_malls[].advantages`
     - `official_malls[].related_products`
     - `official_malls[].other_info`
     - `official_media_matrix[].homepage_urls`
     - `official_media_matrix[].content_focus`
     - `official_media_matrix[].related_products`
     - `official_media_matrix[].other_info`

4. 空值处理：
   - 如果某个列表/数组没有内容，输出空数组 `[]`。
   - 数组字段没有可抽取内容时，必须输出 `[]`，不要输出空模板对象。
   - `basic_info`、`company_profile` 必须保留为对象；如果没有任何可抽取信息，输出空对象 `{{}}`。
   - JSON 输出结构用于说明字段全集；如果对象内完全没有可抽取信息，允许输出空对象 `{{}}`。
   - 内部缺失字段使用空字符串 `""`、空数组 `[]` 或空对象 `{{}}`，不要编造，严禁使用 `null`。
   - `products`、`management_team`、`competitors`、`authority_honors`、`customers_cases`、`sensitive_topics`、`official_malls`、`official_media_matrix` 没有内容时输出空数组 `[]`。
   - `official_malls` 和 `official_media_matrix` 只抽取原文中明确出现的信息，没有则输出空数组 `[]`。

5. 特定字段处理逻辑：
   - `products`：完整抽取与当前品牌相关、且在原文中明确提到的产品信息。
   - 产品分流由接口层处理：接口层会根据现有产品清单决定已有产品进入 `products`、新产品进入 `other_info`；你只需要完整抽取原文产品信息。也就是说，已有产品进入 `products`、新产品进入 `other_info` 的分流不是你的职责。
   - `related_products`：保持原文能确定的产品标识，不要自行编造或推断类型。
   - `authority_honors[].year`：如果原文对该荣誉给出具体年月日或年月，必须保留具体时间，例如 `2023年12月12日`，不要简化成 `2023`;如果不明确具体时间，可以不拿出来。
   -  `competitors[].competitive_advantages`：竞品信息中的竞争优势，预期为目标品牌相比于竞品的优势，非竞品自身优势；
   - `industry_id`：如果抽取到的是“行业名称”（如“电商行业”“文创玩具”），不要返回，请直接忽略；只有原文明确给出可用行业 ID 时才可填写。
   -  customer_service_hotline：如果出现多个内容分隔符只能是换行、逗号、顿号、空格。
   - `official_malls` 与 `official_media_matrix` 必须互斥：电商/交易/商城店铺进入 `official_malls`；媒体账号、内容平台账号（如微信公众号、视频号、抖音号、小红书、微博、搜狐号、头条号、百家号、网易号、B站）只能进入 `official_media_matrix`，不能进入 `official_malls`。

6. other_info（兜底字段）处理规则：
   - 互斥原则：凡是已经进入标准字段的信息，绝对不允许重复进入 `other_info`。
   - 局部 `other_info`：各 section（如 `basic_info`、`products[]`、`company_profile` 等）内的 `other_info` 只收该 section 下无法归入标准字段的信息；能归入标准字段的必须归入标准字段。
   - 全局 `other_info`：最外层的 `other_info` 只收“无明确归属字段”的全局信息，并总结成清晰的 `title/content` 数组。
   - `other_info[].title` 必须使用中文；原文中的信息标题放 `title`，信息内容放 `content`。
   - `other_info[].content` 如果是产品对象数组，必须使用后端约定的稳定英文字段 key。
   - `other_info[].content` 不要输出多层嵌套数组；普通表格、术语表、说明列表应整理成清晰文本或扁平的 title/content 信息。

7. 输出格式限制：
   - 不要输出 Markdown 标记。
   - 不要输出 ```json 代码块。
   - 不要输出解释文字、注释、前后缀。
   - 只能输出一个合法且闭合的 JSON 对象。

# 字段归属参考字典
下面是常见中文字段、同义词与 JSON 输出字段路径的对应关系。请优先根据这份映射把原文信息放入正确字段；如果映射没有覆盖，再根据 JSON 输出结构和核心抽取规则归类。

{formatted_hints}

# 必须遵循的 JSON 输出结构
{{
  "basic_info": {{
    "brand_name": "",
    "brand_alias": "",
    "brand_logo": "",
    "english_name": "",
    "industry_id": "",
    "website": [],
    "customer_service_hotline": "",
    "official_wechat_account": "",
    "intro": "",
    "email": "",
    "positioning": "",
    "advantages": "",
    "mission": "",
    "vision": "",
    "target_regions": [],
    "other_info": ""
  }},
  "products": [
    {{
      "name": "",
      "product_alias": "",
      "product_description": "",
      "product_website": "",
      "product_images": [],
      "price_info": "",
      "coverage_regions": [],
      "product_advantages": "",
      "target_scenarios": "",
      "service_standard": "",
      "service_process": "",
      "cases_and_reputation": "",
      "certification_info": "",
      "core_technology": "",
      "other_info": ""
    }}
  ],
  "company_profile": {{
    "brand_subject_name": "",
    "business_license_image_path": "",
    "stock_info": "",
    "company_address": "",
    "company_intro": "",
    "established_time": "",
    "store_distribution": "",
    "recent_news": "",
    "development_concept": "",
    "corporate_values": "",
    "company_mission": "",
    "development_history": "",
    "other_info": ""
  }},
  "management_team": [
    {{
      "member_name": "",
      "position": "",
      "profile": "",
      "introduction_website": "",
      "other_info": ""
    }}
  ],
  "competitors": [
    {{
      "name": "",
      "competitors_alias": "",
      "competitors_description": "",
      "website": "",
      "competitors_logo": "",
      "competitive_advantages": "",
      "differentiated_positioning": "",
      "comparison_dimensions": "",
      "other_info": ""
    }}
  ],
  "authority_honors": [
    {{
      "title": "",
      "year": "",
      "description": "",
      "report_link": "",
      "qualification_proof": "",
      "issuing_authority": "",
      "other_info": ""
    }}
  ],
  "customers_cases": [
    {{
      "case_name": "",
      "cooperation_time": "",
      "customer_name": "",
      "cooperation_product": "",
      "cooperation_highlight": "",
      "customer_feedback": "",
      "case_link": "",
      "related_products": [],
      "other_info": ""
    }}
  ],
  "sensitive_topics": [
    {{
      "topic": "",
      "description": "",
      "forbidden_terms": "",
      "history_negative_clarification": "",
      "other_info": ""
    }}
  ],
  "official_malls": [
    {{
      "store_name": "",
      "platform": "",
      "homepage_urls": [],
      "store_ids": [],
      "main_categories": [],
      "advantages": [],
      "related_products": [],
      "other_info": []
    }}
  ],
  "official_media_matrix": [
    {{
      "media_platform": "",
      "account_name": "",
      "account_id": "",
      "is_official": "",
      "homepage_urls": [],
      "fans_count": "",
      "content_focus": [],
      "related_products": [],
      "other_info": []
    }}
  ],
  "other_info": [
    {{
      "title": "信息标题",
      "content": "信息内容"
    }}
  ]
}}

# Markdown 原文
<Text>
{markdown_text}
</Text>
"""


async def extract_brand_knowledge_from_markdown(
    markdown_text: str,
    *,
    brand_name: str,
    source_name: str,
    subcategory: str | None = None,
    model: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    formatted_hints = "\n".join(f"- {hint}" for hint in HINTS_LIST)
    prompt = PROMPT_TEMPLATE.format(
        brand_name=brand_name,
        source_name=source_name,
        subcategory=subcategory or "未提供",
        formatted_hints=formatted_hints,
        markdown_text=markdown_text,
    )

    resolved_settings = require_settings(settings)
    api_key = get_dashscope_api_key(resolved_settings)
    model_name = model or resolved_settings.text_llm_model
    if not api_key:
        raise ValueError("未提供 API Key，请设置环境变量 DASHSCOPE_API_KEY")

    def _call_api() -> dict[str, Any]:
        response = Generation.call(
            api_key=api_key,
            model=model_name,
            prompt=prompt,
            result_format="message",
        )
        if response.status_code != 200:
            raise Exception(
                f"品牌知识提取 API 调用失败 (HTTP {response.status_code}) 错误码: {response.code} 错误信息: {response.message}"
            )

        content = response.output.choices[0].message.content
        parsed = extract_json_value(str(content).strip())
        if not isinstance(parsed, dict):
            raise ValueError("品牌知识提取结果不是合法 JSON 对象")
        return parsed

    return await asyncio.to_thread(_call_api)
