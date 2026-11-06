from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from typing import Any

import requests
from dashscope import Generation

from knowledge_base.infrastructure.llm import get_dashscope_api_key, require_settings
from knowledge_base.infrastructure.settings import Settings


logger = logging.getLogger(__name__)


class _RetryableFactExtractionError(Exception):
    """Raised for transient DashScope responses that are safe to retry."""


def _trim_for_log(value: str, *, limit: int = 500) -> str:
    normalized = str(value or "").strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit]}...(truncated,total_chars={len(normalized)})"


def _strip_markdown_code_fence(value: str) -> str:
    text = str(value or "").strip()
    fenced_match = re.match(r"^```(?:json|JSON)?\s*(.*?)\s*```$", text, flags=re.DOTALL)
    if fenced_match:
        return str(fenced_match.group(1) or "").strip()
    return text


def _extract_balanced_json_segment(value: str, opening_char: str) -> str | None:
    text = str(value or "")
    closing_char = "]" if opening_char == "[" else "}"
    start_index = text.find(opening_char)
    if start_index < 0:
        return None

    depth = 0
    in_string = False
    escape = False
    for index in range(start_index, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == opening_char:
            depth += 1
            continue
        if char == closing_char:
            depth -= 1
            if depth == 0:
                return text[start_index : index + 1].strip()
    return None


def _remove_trailing_commas(value: str) -> str:
    previous = str(value or "")
    while True:
        updated = re.sub(r",(\s*[\]}])", r"\1", previous)
        if updated == previous:
            return updated
        previous = updated


def _build_json_candidates(raw_output: str) -> list[str]:
    base_text = str(raw_output or "").strip()
    candidates: list[str] = []
    for candidate in (
        base_text,
        _strip_markdown_code_fence(base_text),
    ):
        normalized_candidate = str(candidate or "").strip()
        if normalized_candidate:
            candidates.append(normalized_candidate)
        for opening_char in ("[", "{"):
            extracted = _extract_balanced_json_segment(normalized_candidate, opening_char)
            if extracted:
                candidates.append(extracted)

    deduplicated: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized_candidate = str(candidate or "").strip()
        if not normalized_candidate or normalized_candidate in seen:
            continue
        seen.add(normalized_candidate)
        deduplicated.append(normalized_candidate)
        comma_fixed = _remove_trailing_commas(normalized_candidate).strip()
        if comma_fixed and comma_fixed not in seen:
            seen.add(comma_fixed)
            deduplicated.append(comma_fixed)
    return deduplicated


def _coerce_facts_payload(parsed: Any) -> list[dict[str, Any]]:
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    if isinstance(parsed, dict):
        return [parsed]
    raise ValueError(f"facts payload 顶层必须是 JSON 数组或对象，实际是 {type(parsed).__name__}")


async def _repair_facts_json_output(
    raw_output: str,
    *,
    model: str | None,
    settings: Settings | None,
) -> str:
    resolved_settings = require_settings(settings)
    api_key = get_dashscope_api_key(resolved_settings)
    model_name = model or resolved_settings.text_llm_model
    if not api_key:
        raise ValueError("未提供 API Key")

    prompt = f"""
你是一个 JSON 修复助手。下面文本本应是一个 JSON 数组，元素形如 {{"主题组名": ["事实1", "事实2"]}} 或 {{"主题组名": "单个事实"}}，但它可能混入了解释文字、markdown 代码块，或者存在少逗号、多逗号、括号不配对等语法问题。

要求：
1. 只输出修复后的合法 JSON。
2. 顶层必须是 JSON 数组；如果输入本质上只有一个对象，请把它包成数组。
3. 不要补充外部知识，不要改写事实语义，只做最小必要的格式修复。
4. 不要输出 markdown 代码块，不要输出任何解释说明。

待修复内容：
{raw_output}
"""

    def _call_api() -> str:
        response = Generation.call(
            api_key=api_key,
            model=model_name,
            prompt=prompt,
            result_format="message",
        )
        if response.status_code == 200:
            try:
                content = response.output.choices[0].message.content
            except Exception as exc:  # noqa: BLE001
                raise ValueError(f"DashScope JSON 修复返回结构异常: {response}") from exc
            content = str(content or "").strip()
            if not content:
                raise ValueError(f"DashScope JSON 修复返回内容为空: {response}")
            return content
        if response.status_code in {408, 429, 500, 502, 503, 504}:
            raise _RetryableFactExtractionError(
                f"JSON 修复调用失败 (HTTP {response.status_code}) 错误码: {response.code} 错误信息: {response.message}"
            )
        raise Exception(
            f"JSON 修复调用失败 (HTTP {response.status_code}) 错误码: {response.code} 错误信息: {response.message}"
        )

    return await asyncio.to_thread(_call_api)


async def parse_facts_json_response(
    raw_output: str,
    *,
    source_name: str | None = None,
    model: str | None = None,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    normalized_output = str(raw_output or "").strip()
    source_name_hint = str(source_name or "").strip() or "未提供"
    if not normalized_output:
        raise ValueError(f"facts 抽取结果为空 source_name={source_name_hint}")

    last_json_error: json.JSONDecodeError | None = None
    for candidate in _build_json_candidates(normalized_output):
        try:
            return _coerce_facts_payload(json.loads(candidate))
        except json.JSONDecodeError as exc:
            last_json_error = exc

    logger.warning(
        "Fact extraction returned invalid JSON, attempting repair source_name=%s raw_chars=%s raw_excerpt=%s",
        source_name_hint,
        len(normalized_output),
        _trim_for_log(normalized_output),
    )
    repaired_output = await _repair_facts_json_output(
        normalized_output,
        model=model,
        settings=settings,
    )
    for candidate in _build_json_candidates(repaired_output):
        try:
            parsed = _coerce_facts_payload(json.loads(candidate))
            logger.warning(
                "Fact extraction JSON repaired successfully source_name=%s repaired_chars=%s repaired_excerpt=%s",
                source_name_hint,
                len(repaired_output),
                _trim_for_log(repaired_output),
            )
            return parsed
        except json.JSONDecodeError as exc:
            last_json_error = exc

    error_detail = (
        f"{last_json_error.msg} line={last_json_error.lineno} column={last_json_error.colno} char={last_json_error.pos}"
        if last_json_error is not None
        else "unknown JSON parse error"
    )
    raise ValueError(
        f"facts 抽取结果不是合法 JSON source_name={source_name_hint} error={error_detail} raw_excerpt={_trim_for_log(normalized_output)}"
    )


async def extract_facts_from_text(
    text: str,
    category: str | None = None,
    subcategory: str | None = None,
    source_name: str | None = None,
    model: str | None = None,
    settings: Settings | None = None,
) -> str:
    category_hint = category.strip() if category else "未提供"
    subcategory_hint = subcategory.strip() if subcategory else "未提供"
    source_name_hint = source_name.strip() if source_name else "未提供"
    prompt = f"""
你是一个专业的品牌知识事实提取助手。请从下面的文本中，尽可能全面、准确地抽取所有独立、完整的事实陈述，不要遗漏。

背景信息（仅供你理解文本，本身不要作为事实输出）：
- 品牌：{category_hint}
- 来源文件：{source_name_hint}

抽取要求：
1. 追求较高召回：把文本中有信息量、可独立成立的事实尽量抽出来，但不要为了“多”而抽无关噪音。
2. 每条事实必须自包含：脱离原文上下文后也能被独立理解。
3. 优先保留事实原本最自然、最准确的主语，如果原文使用了代词、简称、省略主语（如“它”“该公司”“该产品”“其”“项目中”），请替换为明确实体。
4. 一条事实只表达一个完整的主谓宾信息，不要把多个信息点塞进同一句。
5. 忠于原文：只抽取文本中明确陈述或可直接推断的信息，或仅做最小必要的改写以补全主语、消除代词、提升可读性；不要臆造、不要补充外部知识。
6. 去重：语义重复的事实只保留一条。
7. 把主题相近的事实归到同一组，组名用简洁的中文主题词概括（如“基本属性”“营养成分”“健康功效”“使用场景”）。不要产生空组或无意义的组名。

输出格式：
- 只输出一个 JSON 数组，禁止输出任何解释、说明或前后缀文字。
- 禁止使用 markdown 代码块，不要出现 ``` 符号。
- 数组每个元素是一个对象：{{"主题组名": ["事实1", "事实2"]}}；若该组只有一条事实，值可写成字符串：{{"主题组名": "单个事实"}}。

示例：
文本：苹果是水果，富含膳食纤维和维生素C。皮中的槲皮素是强效抗氧化物。经常吃可以降低心脏病风险。
输出：
[
    {{"基本属性": "苹果是一种水果"}},
    {{"营养与功效": ["苹果富含膳食纤维和维生素C", "苹果皮中的槲皮素是强效抗氧化物", "经常吃苹果可以降低患心脏病的风险"]}}
]

请从下面的文本中抽取事实，并严格按上述格式输出 JSON：
{text}
"""
    resolved_settings = require_settings(settings)
    api_key = get_dashscope_api_key(resolved_settings)
    model_name = model or resolved_settings.text_llm_model
    if not api_key:
        raise ValueError("未提供 API Key")

    def _call_api() -> str:
        response = Generation.call(
            api_key=api_key,
            model=model_name,
            prompt=prompt,
            result_format="message",
        )
        if response.status_code == 200:
            try:
                raw_content = response.output.choices[0].message.content
            except Exception as exc:  # noqa: BLE001
                raise ValueError(f"DashScope 返回结构异常: {response}") from exc
            content = str(raw_content or "").strip()
            content = str(content or "").strip()
            if not content:
                raise ValueError(f"DashScope 返回内容为空: {response}")
            return content
        if response.status_code in {408, 429, 500, 502, 503, 504}:
            raise _RetryableFactExtractionError(
                f"API 调用失败 (HTTP {response.status_code}) 错误码: {response.code} 错误信息: {response.message}"
            )
        raise Exception(
            f"API 调用失败 (HTTP {response.status_code}) 错误码: {response.code} 错误信息: {response.message}"
        )

    max_attempts = 3
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await asyncio.to_thread(_call_api)
        except (requests.exceptions.RequestException, _RetryableFactExtractionError) as exc:
            last_exc = exc
            if attempt >= max_attempts:
                break
            wait_seconds = min(8.0, 2 ** (attempt - 1)) + random.uniform(0, 0.5)
            logger.warning(
                "DashScope fact extraction failed, retrying source_name=%s attempt=%s/%s wait_seconds=%.2f error_type=%s error=%s",
                source_name_hint,
                attempt,
                max_attempts,
                wait_seconds,
                exc.__class__.__name__,
                exc,
            )
            await asyncio.sleep(wait_seconds)

    assert last_exc is not None
    raise last_exc
