from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

import requests

from knowledge_base.infrastructure import llm


class FakeAnthropicResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        payload: dict | None = None,
        lines: list[str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.payload = payload or {"content": [{"type": "text", "text": "ok"}]}
        self.lines = lines or []
        self.closed = False

    def json(self):
        return self.payload

    def iter_lines(self, decode_unicode: bool = False):
        for line in self.lines:
            if isinstance(line, bytes) and decode_unicode:
                yield line.decode("latin-1")
            else:
                yield line

    def raise_for_status(self) -> None:
        if self.status_code < 400:
            return
        error = requests.exceptions.HTTPError(f"{self.status_code} error")
        error.response = self
        raise error

    def close(self) -> None:
        self.closed = True


def fake_settings(**overrides):
    values = {
        "anthropic_base_url": "https://anthropic.example.com/v1/messages",
        "anthropic_api_key": "test-key",
        "anthropic_model": "claude-test",
        "anthropic_stream_enabled": True,
        "anthropic_connect_timeout_seconds": 1,
        "anthropic_read_timeout_seconds": 2,
        "anthropic_max_attempts": 3,
        "anthropic_retry_backoff_seconds": 0,
        "anthropic_max_tokens": 4096,
        "anthropic_thinking_budget_tokens": 0,
        "brand_patch_llm_provider": "anthropic",
        "local_llm_base_url": "http://127.0.0.1:9111/v1/chat/completions",
        "local_llm_model": "expert",
        "local_llm_api_key": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def stream_line(event: dict) -> str:
    return "data: " + json.dumps(event)


class AnthropicStreamTests(unittest.TestCase):
    def test_streaming_text_deltas_are_joined(self) -> None:
        original_post = llm.requests.post
        calls: list[dict] = []
        lines = [
            stream_line(
                {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "# 标题"},
                }
            ),
            stream_line(
                {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "\n正文"},
                }
            ),
            "data: [DONE]",
        ]

        def fake_post(url: str, **kwargs):
            calls.append({"url": url, **kwargs})
            return FakeAnthropicResponse(lines=lines)

        llm.requests.post = fake_post
        try:
            result = llm.call_anthropic_text("prompt", settings=fake_settings())
        finally:
            llm.requests.post = original_post

        self.assertEqual(result, "# 标题\n正文")
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0]["stream"])
        self.assertTrue(calls[0]["json"]["stream"])
        self.assertEqual(calls[0]["timeout"], (1, 2))
        self.assertEqual(calls[0]["json"]["max_tokens"], 4096)
        self.assertNotIn("thinking", calls[0]["json"])

    def test_anthropic_base_url_can_be_full_messages_endpoint(self) -> None:
        original_post = llm.requests.post
        calls: list[dict] = []

        def fake_post(url: str, **kwargs):
            calls.append({"url": url, **kwargs})
            return FakeAnthropicResponse(payload={"content": [{"type": "text", "text": "ok"}]})

        llm.requests.post = fake_post
        try:
            result = llm.call_anthropic_text(
                "prompt",
                settings=fake_settings(
                    anthropic_base_url="https://4sapi.org/custom/messages",
                    anthropic_stream_enabled=False,
                ),
            )
        finally:
            llm.requests.post = original_post

        self.assertEqual(result, "ok")
        self.assertEqual(calls[0]["url"], "https://4sapi.org/custom/messages")

    def test_anthropic_base_url_is_not_completed_when_path_is_missing(self) -> None:
        original_post = llm.requests.post
        calls: list[dict] = []

        def fake_post(url: str, **kwargs):
            calls.append({"url": url, **kwargs})
            return FakeAnthropicResponse(payload={"content": [{"type": "text", "text": "ok"}]})

        llm.requests.post = fake_post
        try:
            result = llm.call_anthropic_text(
                "prompt",
                settings=fake_settings(
                    anthropic_base_url="https://4sapi.org",
                    anthropic_stream_enabled=False,
                ),
            )
        finally:
            llm.requests.post = original_post

        self.assertEqual(result, "ok")
        self.assertEqual(calls[0]["url"], "https://4sapi.org")

    def test_streaming_utf8_bytes_are_not_decoded_as_latin1(self) -> None:
        original_post = llm.requests.post
        expected_text = "**一、品牌概述**"
        event = {
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": expected_text},
        }
        line = ("data: " + json.dumps(event, ensure_ascii=False)).encode("utf-8")

        def fake_post(url: str, **kwargs):
            return FakeAnthropicResponse(lines=[line, b"data: [DONE]"])

        llm.requests.post = fake_post
        try:
            result = llm.call_anthropic_text("prompt", settings=fake_settings())
        finally:
            llm.requests.post = original_post

        self.assertEqual(result, expected_text)

    def test_streaming_multiline_sse_data_is_joined_before_json_parse(self) -> None:
        original_post = llm.requests.post
        payload = json.dumps(
            {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "多行事件"},
            }
        )
        midpoint = len(payload) // 2

        def fake_post(url: str, **kwargs):
            return FakeAnthropicResponse(
                lines=[
                    "event: content_block_delta",
                    "data: " + payload[:midpoint],
                    "data: " + payload[midpoint:],
                    "",
                ]
            )

        llm.requests.post = fake_post
        try:
            result = llm.call_anthropic_text("prompt", settings=fake_settings())
        finally:
            llm.requests.post = original_post

        self.assertEqual(result, "多行事件")

    def test_streaming_accepts_openai_style_relay_chunks(self) -> None:
        original_post = llm.requests.post

        def fake_post(url: str, **kwargs):
            return FakeAnthropicResponse(
                lines=[
                    stream_line({"choices": [{"delta": {"content": "relay "}}]}),
                    stream_line({"choices": [{"delta": {"content": "ok"}}]}),
                    "data: [DONE]",
                ]
            )

        llm.requests.post = fake_post
        try:
            result = llm.call_anthropic_text("prompt", settings=fake_settings())
        finally:
            llm.requests.post = original_post

        self.assertEqual(result, "relay ok")

    def test_retries_remote_disconnect_before_stream_response(self) -> None:
        original_post = llm.requests.post
        calls = 0

        def fake_post(url: str, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise requests.exceptions.ConnectionError("RemoteDisconnected")
            return FakeAnthropicResponse(
                lines=[
                    stream_line(
                        {
                            "type": "content_block_delta",
                            "delta": {"type": "text_delta", "text": "ok"},
                        }
                    )
                ]
            )

        llm.requests.post = fake_post
        try:
            result = llm.call_anthropic_text("prompt", settings=fake_settings())
        finally:
            llm.requests.post = original_post

        self.assertEqual(result, "ok")
        self.assertEqual(calls, 2)

    def test_streaming_can_be_disabled_for_non_streaming_provider(self) -> None:
        original_post = llm.requests.post
        calls: list[dict] = []

        def fake_post(url: str, **kwargs):
            calls.append({"url": url, **kwargs})
            return FakeAnthropicResponse(payload={"content": [{"type": "text", "text": "json ok"}]})

        llm.requests.post = fake_post
        try:
            result = llm.call_anthropic_text(
                "prompt",
                settings=fake_settings(anthropic_stream_enabled=False),
            )
        finally:
            llm.requests.post = original_post

        self.assertEqual(result, "json ok")
        self.assertFalse(calls[0]["stream"])
        self.assertNotIn("stream", calls[0]["json"])

    def test_does_not_retry_non_retryable_http_status(self) -> None:
        original_post = llm.requests.post
        calls = 0

        def fake_post(url: str, **kwargs):
            nonlocal calls
            calls += 1
            return FakeAnthropicResponse(status_code=433)

        llm.requests.post = fake_post
        try:
            with self.assertRaises(requests.exceptions.HTTPError):
                llm.call_anthropic_text("prompt", settings=fake_settings())
        finally:
            llm.requests.post = original_post

        self.assertEqual(calls, 1)

    def test_local_llm_provider_uses_openai_chat_completions(self) -> None:
        original_post = llm.requests.post
        calls: list[dict] = []

        def fake_post(url: str, **kwargs):
            calls.append({"url": url, **kwargs})
            return FakeAnthropicResponse(
                payload={
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": '{"status":"completed","operations":[]}',
                            }
                        }
                    ]
                }
            )

        llm.requests.post = fake_post
        try:
            result = llm.call_anthropic_json(
                "请输出 JSON",
                settings=fake_settings(
                    brand_patch_llm_provider="local",
                    local_llm_base_url="http://192.168.1.68:9111/v1/chat/completions",
                    local_llm_model="expert",
                    local_llm_api_key="",
                ),
            )
        finally:
            llm.requests.post = original_post

        self.assertEqual(result, {"status": "completed", "operations": []})
        self.assertEqual(calls[0]["url"], "http://192.168.1.68:9111/v1/chat/completions")
        self.assertFalse(calls[0]["stream"])
        self.assertEqual(calls[0]["json"]["model"], "expert")
        self.assertEqual(calls[0]["json"]["temperature"], 0)
        self.assertEqual(calls[0]["json"]["messages"][0]["role"], "system")
        self.assertEqual(calls[0]["json"]["messages"][1], {"role": "user", "content": "请输出 JSON"})
        self.assertNotIn("Authorization", calls[0]["headers"])

    def test_local_llm_provider_preserves_custom_full_endpoint_path(self) -> None:
        original_post = llm.requests.post
        calls: list[dict] = []

        def fake_post(url: str, **kwargs):
            calls.append({"url": url, **kwargs})
            return FakeAnthropicResponse(
                payload={"choices": [{"message": {"content": '{"status":"completed"}'}}]}
            )

        llm.requests.post = fake_post
        try:
            result = llm.call_anthropic_json(
                "请输出 JSON",
                settings=fake_settings(
                    brand_patch_llm_provider="local",
                    local_llm_base_url="http://127.0.0.1:9111/custom/chat",
                ),
            )
        finally:
            llm.requests.post = original_post

        self.assertEqual(result, {"status": "completed"})
        self.assertEqual(calls[0]["url"], "http://127.0.0.1:9111/custom/chat")

    def test_local_llm_url_is_not_completed_when_path_is_missing(self) -> None:
        original_post = llm.requests.post
        calls: list[dict] = []

        def fake_post(url: str, **kwargs):
            calls.append({"url": url, **kwargs})
            return FakeAnthropicResponse(
                payload={"choices": [{"message": {"content": '{"status":"completed"}'}}]}
            )

        llm.requests.post = fake_post
        try:
            result = llm.call_anthropic_json(
                "请输出 JSON",
                settings=fake_settings(
                    brand_patch_llm_provider="local",
                    local_llm_base_url="http://127.0.0.1:9111",
                ),
            )
        finally:
            llm.requests.post = original_post

        self.assertEqual(result, {"status": "completed"})
        self.assertEqual(calls[0]["url"], "http://127.0.0.1:9111")
