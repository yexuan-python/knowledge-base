from __future__ import annotations

import concurrent.futures
import sys
import threading
import time
import types
import unittest
from unittest.mock import patch

from tests._stub_utils import ensure_stub_module


def _install_test_stubs() -> None:
    dotenv_stub = ensure_stub_module("dotenv")
    if dotenv_stub is not None:
        dotenv_stub.load_dotenv = lambda *args, **kwargs: None
        sys.modules.setdefault("dotenv", dotenv_stub)

    requests_stub = ensure_stub_module("requests")
    if requests_stub is not None:
        requests_stub.get = lambda *args, **kwargs: None
        requests_stub.post = lambda *args, **kwargs: None
        sys.modules.setdefault("requests", requests_stub)

    dashscope_stub = ensure_stub_module("dashscope")
    if dashscope_stub is not None:
        dashscope_stub.MultiModalEmbedding = type(
            "MultiModalEmbedding",
            (),
            {"call": staticmethod(lambda *args, **kwargs: None)},
        )
        sys.modules.setdefault("dashscope", dashscope_stub)

    pymilvus_stub = ensure_stub_module("pymilvus")
    if pymilvus_stub is not None:
        pymilvus_stub.DataType = type("DataType", (), {})
        pymilvus_stub.MilvusClient = type("MilvusClient", (), {})
        sys.modules.setdefault("pymilvus", pymilvus_stub)

    oss2_stub = ensure_stub_module("oss2")
    if oss2_stub is not None:
        oss2_stub.Auth = type("Auth", (), {})
        oss2_stub.Bucket = type("Bucket", (), {})
        sys.modules.setdefault("oss2", oss2_stub)

    pil_stub = ensure_stub_module("PIL", is_package=True)
    if pil_stub is not None:
        pil_stub.Image = types.SimpleNamespace(
            Resampling=types.SimpleNamespace(LANCZOS="LANCZOS"),
            open=lambda *args, **kwargs: None,
        )
        sys.modules.setdefault("PIL", pil_stub)


_install_test_stubs()

from knowledge_base.infrastructure.embedding import EmbeddingRateLimitedError, EmbeddingService
from knowledge_base.infrastructure.settings import Settings


class _FakeEmbeddingResponse:
    def __init__(self, embedding_count: int, *, status_code: int = 200, message: str = "ok") -> None:
        self.status_code = status_code
        self.message = message
        self.output = {
            "embeddings": [{"embedding": [float(index)]} for index in range(embedding_count)],
        }


class EmbeddingServiceTests(unittest.TestCase):
    def test_embedding_calls_respect_max_concurrency(self) -> None:
        settings = Settings(dashscope_api_key="test-key", embedding_max_concurrency=2)
        service = EmbeddingService(settings)
        active_calls = 0
        max_active_calls = 0
        lock = threading.Lock()

        def fake_call(*args, **kwargs):
            nonlocal active_calls, max_active_calls
            with lock:
                active_calls += 1
                max_active_calls = max(max_active_calls, active_calls)
            time.sleep(0.05)
            with lock:
                active_calls -= 1
            return _FakeEmbeddingResponse(1)

        with patch("knowledge_base.infrastructure.embedding.MultiModalEmbedding.call", side_effect=fake_call):
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
                futures = [executor.submit(service.embed_query, f"query-{index}") for index in range(6)]
                results = [future.result(timeout=2) for future in futures]

        self.assertEqual(results, [[0.0]] * 6)
        self.assertLessEqual(max_active_calls, 2)

    def test_rate_limited_requests_fail_fast_during_cooldown(self) -> None:
        settings = Settings(
            dashscope_api_key="test-key",
            embedding_max_concurrency=1,
            embedding_rate_limit_cooldown_seconds=0.05,
        )
        service = EmbeddingService(settings)
        call_count = 0
        lock = threading.Lock()

        def fake_call(*args, **kwargs):
            nonlocal call_count
            with lock:
                call_count += 1
                if call_count == 1:
                    return _FakeEmbeddingResponse(
                        1,
                        status_code=429,
                        message="Requests rate limit exceeded, please try again later.",
                    )
                return _FakeEmbeddingResponse(1)

        with patch("knowledge_base.infrastructure.embedding.MultiModalEmbedding.call", side_effect=fake_call):
            with self.assertRaises(EmbeddingRateLimitedError):
                service.embed_query("query-1")
            self.assertEqual(call_count, 1)

            with self.assertRaises(EmbeddingRateLimitedError):
                service.embed_query("query-2")
            self.assertEqual(call_count, 1)

            time.sleep(0.06)
            self.assertEqual([0.0], service.embed_query("query-3"))
            self.assertEqual(call_count, 2)


if __name__ == "__main__":
    unittest.main()
