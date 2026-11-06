from __future__ import annotations

import asyncio

from dashscope import Generation

from knowledge_base.infrastructure.llm import get_dashscope_api_key, require_settings
from knowledge_base.infrastructure.settings import Settings


async def summarize_text(
    text: str,
    model: str | None = None,
    settings: Settings | None = None,
) -> str:
    prompt = f"""
    你是一个专业的文档分析助手。请用一句话总结以下文档的核心内容，长度不超过100字，用简洁、清晰的语言概括要点，保留关键信息，忽略次要细节。

    文档：
    {text}
    """
    resolved_settings = require_settings(settings)
    api_key = get_dashscope_api_key(resolved_settings)
    model_name = model or resolved_settings.text_llm_model
    if not api_key:
        raise ValueError("未提供 API Key，请设置环境变量 DASHSCOPE_API_KEY")

    def _call_api() -> str:
        response = Generation.call(
            api_key=api_key,
            model=model_name,
            prompt=prompt,
            result_format="message",
        )
        if response.status_code == 200:
            return response.output.choices[0].message.content
        raise Exception(
            f"API 调用失败 (HTTP {response.status_code}) 错误码: {response.code} 错误信息: {response.message}"
        )

    return await asyncio.to_thread(_call_api)
