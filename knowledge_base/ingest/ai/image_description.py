from __future__ import annotations

import asyncio
import re
from pathlib import Path

from dashscope import MultiModalConversation

from knowledge_base.infrastructure.llm import (
    extract_json_object,
    get_dashscope_api_key,
    require_settings,
)
from knowledge_base.infrastructure.settings import Settings


async def describe_image(
    image_path: str,
    *,
    category: str | None = None,
    subcategory: str | None = None,
    source_name: str | None = None,
    model: str | None = None,
    max_tags: int | None = None,
    settings: Settings | None = None,
) -> dict[str, object]:
    resolved_settings = require_settings(settings)
    api_key = get_dashscope_api_key(resolved_settings)
    if not api_key:
        raise ValueError("未提供 API Key，请设置环境变量 DASHSCOPE_API_KEY")

    model_name = model or resolved_settings.image_tagging_model
    tag_limit = max_tags or resolved_settings.image_tagging_max_tags
    category_hint = category.strip() if category else "未提供"
    subcategory_hint = subcategory.strip() if subcategory else "未提供"
    source_name_hint = source_name.strip() if source_name else Path(image_path).name
    file_uri = f"file://{Path(image_path).resolve()}"

    prompt = f"""
    你是一名图片理解助手。请识别这张图片的主要内容，并为知识库检索生成简洁、稳定、可复用的标签。

    当前分类：
    {category_hint}

    当前子分类：
    {subcategory_hint}

    当前文件名：
    {source_name_hint}

    请严格输出一个 JSON 对象，不要输出其他解释，不要使用 Markdown 代码块。
    输出格式：
    {{
    "summary": "一句话描述图片主要内容，20到60字",
    "tags": ["标签1", "标签2", "标签3"]
    }}

    要求：
    1. `summary` 只保留图片里肉眼可见、较确定的信息，不要编造。
    2. `tags` 输出 {tag_limit} 个以内的中文短标签，优先保留可检索关键词，例如主体、场景、物品、品牌物料类型、图表类型、海报、证书、菜单、课堂、人物、表格、截图等。
    3. 如果图片文字可辨认，可以把核心文字主题体现在 summary 或 tags 中，但不要逐字抄写整张图。
    4. 如果图片信息有限，也至少输出 2 个合理标签。
    """.strip()

    def _call_api() -> dict[str, object]:
        response = MultiModalConversation.call(
            api_key=api_key,
            model=model_name,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"image": file_uri},
                        {"text": prompt},
                    ],
                }
            ],
        )
        if response.status_code != 200:
            raise Exception(
                f"图片识别 API 调用失败 (HTTP {response.status_code}) 错误码: {response.code} 错误信息: {response.message}"
            )

        content = response.output.choices[0].message.content
        if isinstance(content, list):
            raw_text = "\n".join(
                str(item.get("text", "")).strip()
                for item in content
                if isinstance(item, dict) and item.get("text")
            ).strip()
        else:
            raw_text = str(content).strip()

        parsed = extract_json_object(raw_text)
        summary = str(parsed.get("summary") or "").strip()

        raw_tags = parsed.get("tags") or []
        if isinstance(raw_tags, str):
            raw_tags = [part.strip() for part in re.split(r"[，,、/\n]+", raw_tags) if part.strip()]
        elif not isinstance(raw_tags, list):
            raw_tags = []

        tags: list[str] = []
        for item in raw_tags:
            tag = str(item or "").strip()
            if tag and tag not in tags:
                tags.append(tag)

        return {
            "summary": summary,
            "tags": tags[:tag_limit],
        }

    return await asyncio.to_thread(_call_api)
