from __future__ import annotations

import sys
import types
import unittest
import importlib.util
from pathlib import Path

from tests._stub_utils import ensure_stub_module


def _install_stubs() -> None:
    dotenv_stub = ensure_stub_module("dotenv")
    if dotenv_stub is not None:
        dotenv_stub.load_dotenv = lambda *args, **kwargs: None
        sys.modules.setdefault("dotenv", dotenv_stub)

    requests_stub = ensure_stub_module("requests")
    if requests_stub is not None:
        requests_stub.post = lambda *args, **kwargs: None
        sys.modules.setdefault("requests", requests_stub)

    settings_stub = ensure_stub_module("knowledge_base.infrastructure.settings")
    previous_settings_module = sys.modules.get("knowledge_base.infrastructure.settings")
    if settings_stub is not None:
        settings_stub.Settings = type("Settings", (), {})
        sys.modules["knowledge_base.infrastructure.settings"] = settings_stub

    oss2_stub = ensure_stub_module("oss2")
    if oss2_stub is not None:

        class _Auth:
            def __init__(self, *args, **kwargs):
                pass

        class _Bucket:
            def __init__(self, *args, **kwargs):
                pass

        oss2_stub.Auth = _Auth
        oss2_stub.Bucket = _Bucket
        oss2_stub.exceptions = types.SimpleNamespace(NoSuchKey=type("NoSuchKey", (Exception,), {}))
        sys.modules.setdefault("oss2", oss2_stub)

    return previous_settings_module


_PREVIOUS_SETTINGS_MODULE = _install_stubs()

_MODULE_PATH = Path("/Users/a0000/knowledge_base/knowledge_base/infrastructure/oss_client.py")
_SPEC = importlib.util.spec_from_file_location("testable_oss_client", _MODULE_PATH)
assert _SPEC is not None
assert _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
if _PREVIOUS_SETTINGS_MODULE is not None:
    sys.modules["knowledge_base.infrastructure.settings"] = _PREVIOUS_SETTINGS_MODULE
else:
    sys.modules.pop("knowledge_base.infrastructure.settings", None)
OSSClient = _MODULE.OSSClient


class OSSClientRetryTests(unittest.TestCase):
    def test_build_object_url_returns_signed_get_url(self) -> None:
        client = OSSClient.__new__(OSSClient)
        client.enabled = True
        client.bucket_name = "heartbit-kg"
        client.endpoint = "oss-cn-beijing.aliyuncs.com"
        client._settings = types.SimpleNamespace(oss_download_url_expires_seconds=3600)

        class Bucket:
            def sign_url(self, method, key, expires, headers=None, params=None, slash_safe=False, additional_headers=None):
                return f"https://signed.example.com/{method}/{key}?expires={expires}&slash_safe={str(slash_safe).lower()}"

        client.bucket = Bucket()

        result = client.build_object_url("test/Jollybaby/ai_knowledge/full/【Jollybaby】品牌AI知识库_V1_20260630.md")

        self.assertEqual(
            result,
            "https://signed.example.com/GET/test/Jollybaby/ai_knowledge/full/【Jollybaby】品牌AI知识库_V1_20260630.md?expires=3600&slash_safe=true",
        )

    def test_build_object_url_falls_back_to_encoded_public_url_when_signing_fails(self) -> None:
        client = OSSClient.__new__(OSSClient)
        client.enabled = True
        client.bucket_name = "heartbit-kg"
        client.endpoint = "oss-cn-beijing.aliyuncs.com"
        client._settings = types.SimpleNamespace(oss_download_url_expires_seconds=3600)

        class Bucket:
            def sign_url(self, method, key, expires, headers=None, params=None, slash_safe=False, additional_headers=None):
                raise RuntimeError("sign failed")

        client.bucket = Bucket()

        result = client.build_object_url("test/Jollybaby/ai_knowledge/full/【Jollybaby】品牌AI知识库_V1_20260630.md")

        self.assertEqual(
            result,
            "https://heartbit-kg.oss-cn-beijing.aliyuncs.com/test/Jollybaby/ai_knowledge/full/%E3%80%90Jollybaby%E3%80%91%E5%93%81%E7%89%8CAI%E7%9F%A5%E8%AF%86%E5%BA%93_V1_20260630.md",
        )

    def test_upload_file_retries_until_success(self) -> None:
        sleep_calls: list[int] = []
        original_sleep = _MODULE.time.sleep
        _MODULE.time.sleep = lambda seconds: sleep_calls.append(seconds)
        try:
            client = OSSClient.__new__(OSSClient)
            client.enabled = True
            attempts: list[str] = []

            class Bucket:
                def put_object_from_file(self, object_key, file_path, headers=None):
                    self.last_headers = headers
                    attempts.append(object_key)
                    if len(attempts) < 3:
                        raise ConnectionResetError(54, "Connection reset by peer")

            client.bucket = Bucket()
            result = client.upload_file("/tmp/demo.pdf", "demo/original/demo.pdf/V1.pdf")
        finally:
            _MODULE.time.sleep = original_sleep

        self.assertEqual(result, "demo/original/demo.pdf/V1.pdf")
        self.assertEqual(len(attempts), 3)
        self.assertEqual(sleep_calls, [1, 2])

    def test_upload_bytes_returns_none_after_three_failures(self) -> None:
        sleep_calls: list[int] = []
        original_sleep = _MODULE.time.sleep
        _MODULE.time.sleep = lambda seconds: sleep_calls.append(seconds)
        try:
            client = OSSClient.__new__(OSSClient)
            client.enabled = True
            attempts: list[str] = []

            class Bucket:
                def put_object(self, object_key, data, headers=None):
                    attempts.append(object_key)
                    raise ConnectionResetError(54, "Connection reset by peer")

            client.bucket = Bucket()
            result = client.upload_bytes(b"hello", "demo/converted/demo.pdf/V1.md", content_type="text/markdown")
        finally:
            _MODULE.time.sleep = original_sleep

        self.assertIsNone(result)
        self.assertEqual(len(attempts), 3)
        self.assertEqual(sleep_calls, [1, 2])


if __name__ == "__main__":
    unittest.main()
