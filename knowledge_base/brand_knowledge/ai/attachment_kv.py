from __future__ import annotations

import asyncio
from typing import Any

from dashscope import Generation

from knowledge_base.infrastructure.llm import (
    extract_json_value,
    get_dashscope_api_key,
    require_settings,
)
from knowledge_base.infrastructure.settings import Settings


def _normalize_kv_items(payload: Any) -> list[dict[str, str]]:
    items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return []

    normalized: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        value = str(item.get("value") or "").strip()
        if not key or not value:
            continue
        normalized.append({"key": key, "value": value})
    return normalized


async def extract_attachment_kv_from_markdown(
    markdown_text: str,
    *,
    brand_name: str,
    source_name: str,
    model: str | None = None,
    settings: Settings | None = None,
) -> list[dict[str, str]]:
    prompt = f"""
你是一名附件内容事实整理助手。你的唯一任务，是把给定 Markdown 文本整理为 K-V 列表，其中 K 是标题，V 是一段内容。

品牌名称：
{brand_name}

文件名称：
{source_name}

请严格遵守以下规则：
1. 只能依据本次提供的 Markdown 原文输出内容。
2. 严禁调用、补充、引用、套用模型内置静态知识、训练记忆、行业常识、品牌背景知识或任何外部信息。
3. 严禁杜撰、脑补、主观臆测、推断隐含结论；凡是原文没有明确写出的内容，一律不要输出。
4. 目标不是“筛选重点”，而是“尽量完整覆盖附件全部内容”。只要原文里出现的正文、标题、列表、表格、时间线、备注、补充说明、附录、零散片段有实际信息，都应整理进结果。
5. 不要因为你觉得内容真假不明、指代不清、上下文残缺、像备注、像草稿、像补充说明，就擅自省略；只要原文里出现，就应保留到最合适的 `key` 下。你不需要判断真假，只需要忠实整理原文内容。
6. 只有在“内容完全重复”时才允许去重；如果只是表述略有不同、角度不同、细节多寡不同，都应保留，不要误删。
7. `key` 必须是简洁明确的小标题，优先使用原文已有标题、章节名或可以直接从原文显式概括出的主题，不要写夸张营销词。若一段内容难以归入明确主题，可使用 `其他内容`、`补充说明`、`附录信息` 等中性标题承接，不要丢弃。
8. `value` 必须是一段完整表述，保留原文事实含义；允许对同一主题下相邻信息做轻度整理和顺序微调，但不得新增事实，不得改变数字、时间、主体、范围、结论。
9. 如果原文是列表、表格、要点，可整理成一段通顺文字；但不要省略关键事实项，尤其不要漏掉时间、主体、数量、奖项、型号、地区、名单、条目等信息。
10. 输出前请自检：你的 `items` 应尽量覆盖原文全部有效信息，而不是只挑一部分重点。
11. 输出必须是 JSON，对象格式固定为：
{{
  "items": [
    {{
      "key": "标题",
      "value": "一段内容"
    }}
  ]
}}
12. 不要输出 Markdown、解释文字、前后缀、代码块。
13. 只有当原文确实没有任何可整理的有效文本时，才返回 `{{"items":[]}}`。

Markdown 原文：
{markdown_text}
""".strip()

    resolved_settings = require_settings(settings)
    api_key = get_dashscope_api_key(resolved_settings)
    model_name = model or resolved_settings.text_llm_model
    if not api_key:
        raise ValueError("未提供 API Key，请设置环境变量 DASHSCOPE_API_KEY")

    def _call_api() -> list[dict[str, str]]:
        response = Generation.call(
            api_key=api_key,
            model=model_name,
            prompt=prompt,
            result_format="message",
        )
        if response.status_code != 200:
            raise Exception(
                f"附件 K-V 提取 API 调用失败 (HTTP {response.status_code}) 错误码: {response.code} 错误信息: {response.message}"
            )

        content = response.output.choices[0].message.content
        parsed = extract_json_value(str(content).strip())
        return _normalize_kv_items(parsed)

    return await asyncio.to_thread(_call_api)
