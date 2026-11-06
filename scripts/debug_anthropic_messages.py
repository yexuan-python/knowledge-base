#!/usr/bin/env python3
"""Probe the configured Messages endpoint and retain raw HTTP/SSE errors.

Examples (run from the repository root):
    .venv/bin/python scripts/debug_anthropic_messages.py --dry-run
    .venv/bin/python scripts/debug_anthropic_messages.py
    .venv/bin/python scripts/debug_anthropic_messages.py --mode minimal
    .venv/bin/python scripts/debug_anthropic_messages.py --mode adaptive
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys
from time import perf_counter

import requests


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from knowledge_base.infrastructure.llm import _anthropic_request_payload
from knowledge_base.infrastructure.settings import Settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="单次测试 Claude 中转接口，打印 HTTP 状态、请求 ID 和原始响应（不自动重试）。",
    )
    parser.add_argument("--model", help="默认读取 ANTHROPIC_MODEL，未设置时为 claude-opus-4-8")
    parser.add_argument("--url", help="完整接口地址，默认读取 ANTHROPIC_BASE_URL")
    parser.add_argument(
        "--mode", choices=("current", "minimal", "adaptive"), default="current",
        help="current: 项目当前参数；minimal: 文档最简请求；adaptive: 改用自适应思考并移除 temperature",
    )
    prompt_group = parser.add_mutually_exclusive_group()
    prompt_group.add_argument("--prompt", default="请只回复：连接测试成功。")
    prompt_group.add_argument("--prompt-file", type=Path, help="从 UTF-8 文件读取完整 prompt")
    parser.add_argument("--max-tokens", type=int, help="覆盖最大输出 token 数")
    parser.add_argument("--thinking-budget-tokens", type=int, help="覆盖手动思考预算；0 表示不传 thinking")
    parser.add_argument("--stream", action=argparse.BooleanOptionalAction, default=None,
                        help="覆盖流式设置；--no-stream 使用普通 JSON 响应")
    parser.add_argument("--dry-run", action="store_true", help="只显示请求，不联网，也不要求配置 API Key")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.max_tokens is not None and args.max_tokens < 1:
        parser.error("--max-tokens 必须大于 0")
    if args.thinking_budget_tokens is not None and args.thinking_budget_tokens < 0:
        parser.error("--thinking-budget-tokens 不能小于 0")
    if args.mode != "current" and args.thinking_budget_tokens is not None:
        parser.error("--thinking-budget-tokens 仅用于 current 模式")

    settings = Settings()
    settings = replace(
        settings,
        anthropic_model=args.model or settings.anthropic_model,
        anthropic_base_url=args.url or settings.anthropic_base_url,
        anthropic_max_tokens=(args.max_tokens if args.max_tokens is not None else settings.anthropic_max_tokens),
        anthropic_thinking_budget_tokens=(
            args.thinking_budget_tokens if args.thinking_budget_tokens is not None
            else settings.anthropic_thinking_budget_tokens
        ),
    )
    try:
        prompt = args.prompt_file.read_text(encoding="utf-8-sig") if args.prompt_file else args.prompt
    except (OSError, UnicodeError) as exc:
        parser.error(f"无法读取 prompt 文件：{exc}")
    if not prompt.strip():
        parser.error("prompt 不能为空")

    stream_enabled = settings.anthropic_stream_enabled if args.stream is None else args.stream
    if args.mode == "minimal":
        payload = {
            "model": settings.anthropic_model,
            "max_tokens": args.max_tokens if args.max_tokens is not None else 1024,
            "messages": [{"role": "user", "content": prompt}],
        }
        # Match the relay documentation unless streaming was explicitly requested.
        stream_enabled = False if args.stream is None else args.stream
    else:
        payload = _anthropic_request_payload(prompt, settings=settings)
        if args.mode == "adaptive":
            payload.pop("temperature", None)
            payload["thinking"] = {"type": "adaptive"}
    if stream_enabled:
        payload["stream"] = True

    api_key = settings.anthropic_api_key

    def safe_print(value: str) -> None:
        print(value.replace(api_key, "<REDACTED>") if api_key else value, flush=True)

    timeout = (
        max(0.1, settings.anthropic_connect_timeout_seconds),
        max(0.1, settings.anthropic_read_timeout_seconds),
    )
    safe_print(f"模式: {args.mode}\nPOST {settings.anthropic_base_url}")
    safe_print("Authorization: <REDACTED>\nAccept: application/json\nContent-Type: application/json")
    safe_print(f"连接/读取超时（秒）: {timeout}")
    safe_print("请求 JSON:\n" + json.dumps(payload, ensure_ascii=False, indent=2))
    if args.dry_run:
        safe_print("dry-run：未发送请求。")
        return 0
    if not api_key:
        safe_print("未配置 ANTHROPIC_API_KEY；请在项目 .env 或环境变量中设置。")
        return 2

    started_at = perf_counter()
    try:
        with requests.post(
            settings.anthropic_base_url,
            headers={"Accept": "application/json", "Authorization": api_key,
                     "Content-Type": "application/json"},
            json=payload,
            stream=stream_enabled,
            timeout=timeout,
            allow_redirects=False,
        ) as response:
            safe_print(f"\nHTTP {response.status_code} {response.reason}")
            for name in ("Content-Type", "request-id", "x-request-id", "x-oneapi-request-id", "cf-ray"):
                if response.headers.get(name):
                    safe_print(f"{name}: {response.headers[name]}")
            safe_print("响应正文（保留错误详情和 SSE 事件）:")
            has_stream_error = False
            if stream_enabled and "text/event-stream" in response.headers.get("Content-Type", "").lower():
                for raw_line in response.iter_lines():
                    line = raw_line.decode("utf-8", errors="replace")
                    safe_print(line)
                    if line.strip() == "event: error":
                        has_stream_error = True
                    if line.startswith("data:"):
                        try:
                            event = json.loads(line.removeprefix("data:").strip())
                        except json.JSONDecodeError:
                            continue
                        if isinstance(event, dict) and (event.get("type") == "error" or event.get("error")):
                            has_stream_error = True
            else:
                response.encoding = "utf-8"
                safe_print(response.text)
            return 0 if 200 <= response.status_code < 300 and not has_stream_error else 1
    except requests.RequestException as exc:
        safe_print(f"请求失败: {type(exc).__name__}: {exc}")
        return 1
    finally:
        safe_print(f"总耗时: {perf_counter() - started_at:.3f} 秒")


if __name__ == "__main__":
    raise SystemExit(main())
