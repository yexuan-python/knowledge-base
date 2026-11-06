from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import requests
from dashscope import Generation

from knowledge_base.infrastructure.dashscope_runtime import configure_dashscope
from knowledge_base.infrastructure.settings import Settings


logger = logging.getLogger(__name__)

_ANTHROPIC_RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}
_ANTHROPIC_RETRYABLE_EXCEPTIONS = (
    requests.exceptions.ChunkedEncodingError,
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
)


def require_settings(settings: Settings | None) -> Settings:
    if settings is None:
        raise ValueError("settings is required")
    return settings


def get_dashscope_api_key(settings: Settings) -> str:
    configure_dashscope(settings)
    return settings.dashscope_api_key


def call_text_llm_json(
    prompt: str,
    *,
    settings: Settings,
    model: str | None = None,
) -> dict[str, Any]:
    api_key = get_dashscope_api_key(settings)
    model_name = model or settings.text_llm_model
    if not api_key:
        raise ValueError("未提供 API Key，请设置环境变量 DASHSCOPE_API_KEY")

    response = Generation.call(
        api_key=api_key,
        model=model_name,
        prompt=prompt,
        result_format="message",
    )
    if response.status_code != 200:
        raise Exception(
            f"API 调用失败 (HTTP {response.status_code}) 错误码: {response.code} 错误信息: {response.message}"
        )

    content = response.output.choices[0].message.content
    parsed = extract_json_value(str(content).strip())
    if not isinstance(parsed, dict):
        raise ValueError("文本模型返回结果不是合法 JSON 对象")
    return parsed


def call_text_llm_text(
    prompt: str,
    *,
    settings: Settings,
    model: str | None = None,
) -> str:
    api_key = get_dashscope_api_key(settings)
    model_name = model or settings.text_llm_model
    if not api_key:
        raise ValueError("未提供 API Key，请设置环境变量 DASHSCOPE_API_KEY")

    response = Generation.call(
        api_key=api_key,
        model=model_name,
        prompt=prompt,
        result_format="message",
    )
    if response.status_code != 200:
        raise Exception(
            f"API 调用失败 (HTTP {response.status_code}) 错误码: {response.code} 错误信息: {response.message}"
        )

    return str(response.output.choices[0].message.content or "").strip()


def extract_json_object(text: str) -> dict[str, Any]:
    candidate = (text or "").strip()
    if not candidate:
        return {}

    fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, re.DOTALL)
    if fenced_match:
        candidate = fenced_match.group(1).strip()
    else:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = candidate[start : end + 1]

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        logger.warning("Failed to parse image semantic JSON response: %s", text)
        return {}

    return parsed if isinstance(parsed, dict) else {}


def extract_json_value(text: str) -> Any:
    candidate = (text or "").strip()
    if not candidate:
        return None

    fenced_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", candidate, re.DOTALL)
    if fenced_match:
        candidate = fenced_match.group(1).strip()
    else:
        start_positions = [index for index in (candidate.find("{"), candidate.find("[")) if index != -1]
        end_positions = [index for index in (candidate.rfind("}"), candidate.rfind("]")) if index != -1]
        if start_positions and end_positions:
            start = min(start_positions)
            end = max(end_positions)
            if end > start:
                candidate = candidate[start : end + 1]

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        logger.warning("Failed to parse JSON response: %s", text)
        return None


def build_source_blocks(
    markdown_sources: list[dict[str, Any]],
    *,
    include_full_markdown: bool,
    truncated_length: int = 6000,
) -> list[str]:
    source_blocks: list[str] = []
    for index, item in enumerate(markdown_sources, start=1):
        source_name = str(item.get("source_name") or f"source-{index}")
        subcategory = str(item.get("subcategory") or "").strip()
        source_role = str(item.get("source_role") or "").strip()
        markdown_text = str(item.get("markdown_text") or "").strip()
        if not markdown_text:
            continue
        effective_text = markdown_text if include_full_markdown else markdown_text[:truncated_length]
        header_lines = [
            f"# 文件 {index}",
            f"文件名：{source_name}",
            f"子分类：{subcategory or '未提供'}",
        ]
        if source_role:
            header_lines.append(f"来源角色：{source_role}")
        source_blocks.append(
            "\n".join(
                [
                    *header_lines,
                    "```markdown",
                    effective_text,
                    "```",
                ]
            )
        )
    return source_blocks


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _anthropic_request_payload(prompt: str, *, settings: Settings) -> dict[str, Any]:
    max_tokens = max(1, int(getattr(settings, "anthropic_max_tokens", 65536) or 65536))
    thinking_budget_tokens = max(
        0,
        int(getattr(settings, "anthropic_thinking_budget_tokens", 10000) or 0),
    )
    payload: dict[str, Any] = {
        "model": settings.anthropic_model,
        "max_tokens": max_tokens,
        "temperature": 1,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            }
        ],
    }
    if thinking_budget_tokens > 0:
        payload["thinking"] = {
            "type": "enabled",
            "budget_tokens": thinking_budget_tokens,
        }
    return payload


def _anthropic_messages_url(settings: Settings) -> str:
    url = str(getattr(settings, "anthropic_base_url", "") or "").strip()
    if not url:
        raise ValueError("未配置 Anthropic 地址，请设置 ANTHROPIC_BASE_URL")
    return url


def _local_chat_completions_url(settings: Settings) -> str:
    url = str(getattr(settings, "local_llm_base_url", "") or "").strip()
    if not url:
        raise ValueError("未配置本地 LLM 地址，请设置 KB_LOCAL_LLM_BASE_URL")
    return url


def _local_chat_completions_payload(prompt: str, *, settings: Settings) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是一个严格输出 JSON 的品牌 AI 知识库补丁生成助手。"
                    "只输出合法 JSON 对象，不要输出解释文字、Markdown 代码块或额外说明。"
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
    }
    model_name = str(getattr(settings, "local_llm_model", "") or "").strip()
    if model_name:
        payload["model"] = model_name
    return payload


def _extract_openai_chat_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        return ""

    message = first_choice.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    parts.append(str(item.get("text") or item.get("content") or ""))
                else:
                    parts.append(str(item))
            return "".join(parts).strip()
        return str(content or "").strip()

    return str(first_choice.get("text") or "").strip()


def _extract_anthropic_text(payload: dict[str, Any]) -> str:
    parts = payload.get("content") or []
    return "\n".join(
        str(part.get("text") or "").strip()
        for part in parts
        if isinstance(part, dict) and part.get("type") == "text"
    ).strip()


def _extract_text_from_stream_event(event: dict[str, Any]) -> str:
    event_type = event.get("type")
    if event_type == "content_block_start":
        content_block = event.get("content_block")
        if isinstance(content_block, dict) and content_block.get("type") == "text":
            return str(content_block.get("text") or "")
        return ""

    if event_type == "content_block_delta":
        delta = event.get("delta")
        if isinstance(delta, dict) and delta.get("type") == "text_delta":
            return str(delta.get("text") or "")
        return ""

    # Some OpenAI-compatible relays keep the Anthropic endpoint but stream
    # OpenAI-style chunks. Accept them so provider adapters do not lose text.
    choices = event.get("choices")
    if isinstance(choices, list):
        fragments: list[str] = []
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta")
            if isinstance(delta, dict):
                fragments.append(str(delta.get("content") or ""))
                continue
            message = choice.get("message")
            if isinstance(message, dict):
                fragments.append(str(message.get("content") or ""))
        return "".join(fragments)

    return ""


def _iter_anthropic_stream_events(response: requests.Response):
    data_lines: list[str] = []

    def decode_line(raw_line: str | bytes) -> str:
        if isinstance(raw_line, bytes):
            return raw_line.decode("utf-8", errors="replace")
        return raw_line

    def flush_data_lines():
        nonlocal data_lines
        if not data_lines:
            return None
        data = "\n".join(data_lines).strip()
        data_lines = []
        return data

    def buffered_data_is_complete_json() -> bool:
        if not data_lines:
            return False
        try:
            json.loads("\n".join(data_lines).strip())
        except json.JSONDecodeError:
            return False
        return True

    for raw_line in response.iter_lines(decode_unicode=False):
        if raw_line is None:
            continue
        line = decode_line(raw_line).strip()
        if not line:
            data = flush_data_lines()
            if data:
                yield data
            continue
        if line.startswith(":") or line.startswith("event:") or line.startswith("id:") or line.startswith("retry:"):
            continue
        if line.startswith("data:"):
            data_value = line.removeprefix("data:").strip()
            if data_value == "[DONE]":
                data = flush_data_lines()
                if data:
                    yield data
                yield data_value
                continue
            if buffered_data_is_complete_json():
                data = flush_data_lines()
                if data:
                    yield data
            data_lines.append(data_value)

    data = flush_data_lines()
    if data:
        yield data


def _read_anthropic_stream_text(response: requests.Response) -> str:
    text_parts: list[str] = []
    invalid_event_count = 0
    for data in _iter_anthropic_stream_events(response):
        if not data or data == "[DONE]":
            continue
        try:
            event = json.loads(data)
        except json.JSONDecodeError:
            invalid_event_count += 1
            continue
        if not isinstance(event, dict):
            continue

        event_type = event.get("type")
        if event_type == "error":
            error = event.get("error") if isinstance(event.get("error"), dict) else {}
            message = str(error.get("message") or "Anthropic stream error")
            raise RuntimeError(message)

        text_parts.append(_extract_text_from_stream_event(event))
    if invalid_event_count:
        logger.warning(
            "Skipped %s invalid Anthropic stream event(s)",
            invalid_event_count,
        )
    return "".join(text_parts).strip()


def _call_anthropic_text_once(
    prompt: str,
    *,
    settings: Settings,
    stream_enabled: bool,
    timeout: tuple[float, float],
) -> str:
    payload = _anthropic_request_payload(prompt, settings=settings)
    if stream_enabled:
        payload["stream"] = True
    response = requests.post(
        _anthropic_messages_url(settings),
        headers={
            "Accept": "application/json",
            "Authorization": settings.anthropic_api_key,
            "Content-Type": "application/json",
        },
        json=payload,
        stream=stream_enabled,
        timeout=timeout,
    )
    try:
        response.raise_for_status()
        if stream_enabled:
            return _read_anthropic_stream_text(response)
        return _extract_anthropic_text(response.json())
    finally:
        response.close()


def _call_local_llm_text_once(
    prompt: str,
    *,
    settings: Settings,
    timeout: tuple[float, float],
) -> str:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    api_key = str(getattr(settings, "local_llm_api_key", "") or "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    response = requests.post(
        _local_chat_completions_url(settings),
        headers=headers,
        json=_local_chat_completions_payload(prompt, settings=settings),
        stream=False,
        timeout=timeout,
    )
    try:
        response.raise_for_status()
        return _extract_openai_chat_text(response.json())
    finally:
        response.close()


def _brand_patch_llm_provider(settings: Settings) -> str:
    provider = str(getattr(settings, "brand_patch_llm_provider", "anthropic") or "anthropic").strip().lower()
    if provider in {"local", "local_llm", "openai", "openai_compatible", "openai-compatible"}:
        return "local"
    return "anthropic"


def _call_anthropic_text(prompt: str, *, settings: Settings) -> str:
    max_attempts = max(1, int(getattr(settings, "anthropic_max_attempts", 3) or 1))
    backoff_seconds = max(0.0, float(getattr(settings, "anthropic_retry_backoff_seconds", 2) or 0))
    stream_enabled = _coerce_bool(getattr(settings, "anthropic_stream_enabled", True), True)
    timeout = (
        max(0.1, float(getattr(settings, "anthropic_connect_timeout_seconds", 10) or 10)),
        max(0.1, float(getattr(settings, "anthropic_read_timeout_seconds", 600) or 600)),
    )
    max_tokens = max(1, int(getattr(settings, "anthropic_max_tokens", 65536) or 65536))
    thinking_budget_tokens = max(
        0,
        int(getattr(settings, "anthropic_thinking_budget_tokens", 10000) or 0),
    )
    provider = _brand_patch_llm_provider(settings)

    for attempt in range(1, max_attempts + 1):
        try:
            if provider == "local":
                return _call_local_llm_text_once(
                    prompt,
                    settings=settings,
                    timeout=timeout,
                )
            return _call_anthropic_text_once(
                prompt,
                settings=settings,
                stream_enabled=stream_enabled,
                timeout=timeout,
            )
        except requests.exceptions.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code not in _ANTHROPIC_RETRYABLE_STATUS_CODES or attempt >= max_attempts:
                raise
            logger.warning(
                (
                    "LLM text call attempt %s/%s returned HTTP %s; retrying "
                    "provider=%s stream=%s prompt_chars=%s max_tokens=%s "
                    "thinking_budget_tokens=%s timeout=%s"
                ),
                attempt,
                max_attempts,
                status_code,
                provider,
                stream_enabled,
                len(prompt),
                max_tokens,
                thinking_budget_tokens,
                timeout,
            )
        except _ANTHROPIC_RETRYABLE_EXCEPTIONS as exc:
            if attempt >= max_attempts:
                logger.warning(
                    (
                        "LLM text call failed after %s attempt(s): %s "
                        "provider=%s stream=%s prompt_chars=%s max_tokens=%s "
                        "thinking_budget_tokens=%s timeout=%s"
                    ),
                    attempt,
                    exc.__class__.__name__,
                    provider,
                    stream_enabled,
                    len(prompt),
                    max_tokens,
                    thinking_budget_tokens,
                    timeout,
                )
                raise
            logger.warning(
                (
                    "LLM text call attempt %s/%s failed with %s; retrying "
                    "provider=%s stream=%s prompt_chars=%s max_tokens=%s "
                    "thinking_budget_tokens=%s timeout=%s"
                ),
                attempt,
                max_attempts,
                exc.__class__.__name__,
                provider,
                stream_enabled,
                len(prompt),
                max_tokens,
                thinking_budget_tokens,
                timeout,
            )
        if backoff_seconds:
            time.sleep(backoff_seconds * attempt)

    raise RuntimeError("LLM text call did not produce a response")


def call_anthropic_text(prompt: str, *, settings: Settings) -> str:
    return _call_anthropic_text(prompt, settings=settings)


def call_anthropic_json(prompt: str, *, settings: Settings) -> dict[str, Any]:
    text = _call_anthropic_text(prompt, settings=settings)
    parsed = extract_json_value(text)
    if not isinstance(parsed, dict):
        raise ValueError("LLM 返回结果不是合法 JSON 对象")
    return parsed
