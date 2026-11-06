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
        class _HTTPError(Exception):
            def __init__(self, *args, response=None, **kwargs):
                super().__init__(*args)
                self.response = response

        requests_stub.post = lambda *args, **kwargs: None
        requests_stub.Response = type("Response", (), {})
        requests_stub.exceptions = types.SimpleNamespace(HTTPError=_HTTPError)
        sys.modules.setdefault("requests", requests_stub)

    dashscope_stub = ensure_stub_module("dashscope")
    if dashscope_stub is not None:

        class _Generation:
            @staticmethod
            def call(*args, **kwargs):
                raise RuntimeError("Generation.call should not run in this test")

        class _MultiModalConversation:
            @staticmethod
            def call(*args, **kwargs):
                raise RuntimeError("MultiModalConversation.call should not run in this test")

        class _MultiModalEmbedding:
            @staticmethod
            def call(*args, **kwargs):
                raise RuntimeError("MultiModalEmbedding.call should not run in this test")

        dashscope_stub.Generation = _Generation
        dashscope_stub.MultiModalConversation = _MultiModalConversation
        dashscope_stub.MultiModalEmbedding = _MultiModalEmbedding
        sys.modules.setdefault("dashscope", dashscope_stub)


_install_stubs()

_MODULE_PATH = Path("/Users/a0000/knowledge_base/knowledge_base/infrastructure/tianyancha_client.py")
_SPEC = importlib.util.spec_from_file_location("testable_tianyancha_client", _MODULE_PATH)
assert _SPEC is not None
assert _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
TianyanchaClient = _MODULE.TianyanchaClient


class _FakeResponse:
    def __init__(self, *, headers=None, payload=None, text="", status_code=200):
        self.headers = headers or {}
        self._payload = payload
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise _MODULE.requests.exceptions.HTTPError(
                f"{self.status_code} Client Error",
                response=self,
            )

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class TianyanchaClientTests(unittest.TestCase):
    def test_lookup_company_profile_uses_https_mcp_flow(self) -> None:
        calls: list[dict[str, object]] = []

        def fake_post(url, json=None, headers=None, timeout=None):
            calls.append(
                {
                    "url": url,
                    "json": json,
                    "headers": headers,
                    "timeout": timeout,
                }
            )
            method = (json or {}).get("method")
            if method == "initialize":
                return _FakeResponse(
                    headers={"Mcp-Session-Id": "session-1", "Content-Type": "application/json"},
                    payload={"jsonrpc": "2.0", "id": "init-1", "result": {"protocolVersion": "2025-03-26"}},
                )
            if method == "notifications/initialized":
                return _FakeResponse(headers={"Content-Type": "application/json"}, payload={})
            if method == "tools/list":
                return _FakeResponse(
                    headers={"Content-Type": "application/json"},
                    payload={
                        "jsonrpc": "2.0",
                        "id": "tools-list-1",
                        "result": {
                            "tools": [
                                {
                                    "name": "company.registration-info",
                                    "description": "查询企业工商登记信息",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {
                                            "searchKey": {"type": "string"},
                                        },
                                    },
                                }
                            ]
                        },
                    },
                )
            if method == "tools/call":
                return _FakeResponse(
                    headers={"Content-Type": "application/json"},
                    payload={
                        "jsonrpc": "2.0",
                        "id": "tools-call-1",
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": "\n".join(
                                        [
                                            "# 公司基础画像：北京金堤科技有限公司",
                                            "| 字段 | 值 |",
                                            "|---|---|",
                                            "| 企业名称 | 北京金堤科技有限公司 |",
                                            "| 注册资本 | 1000万人民币 |",
                                            "| 成立日期 | 2011-01-01 |",
                                            "| 联系电话 | 400-000-0000 |",
                                            "| 注册地址 | 北京市海淀区 |",
                                            "| 官网 | https://www.example.com |",
                                            "| logo_url | https://img.example.com/logo.png |",
                                            "| profile | 企业简介示例 |",
                                            "| 统一社会信用代码 | 9111010831813798XE |",
                                            "| 法定代表人 | 张三 |",
                                            "| 登记状态 | 存续 |",
                                            "| 登记机关 | 北京市海淀区市场监督管理局 |",
                                            "| 企业类型 | 有限责任公司 |",
                                            "| 行业 | 科技推广和应用服务业 |",
                                            "| 行业分类 | 其他科技推广服务业 |",
                                            "| 参保人数 | 84 |",
                                            "| 人员规模 | 50-99人 |",
                                            "| 标签 | 高新技术企业;科技型中小企业 |",
                                            "| 核准日期 | 2023-07-12 |",
                                            "| 营业期限起 | 2014-10-30 |",
                                            "| 营业期限止 | 2034-10-29 |",
                                            "| 邮箱 | kf@tianyancha.com |",
                                        ]
                                    ),
                                }
                            ]
                        },
                    },
                )
            raise AssertionError(f"unexpected method: {method}")

        original_post = _MODULE.requests.post
        _MODULE.requests.post = fake_post
        try:
            client = TianyanchaClient(
                types.SimpleNamespace(
                    tianyancha_enabled=True,
                    tianyancha_api_key="api-key-1",
                    tianyancha_mcp_url="https://mcp.tianyancha.com/v1",
                    tianyancha_timeout_seconds=15.0,
                )
            )
            profile = client.lookup_company_profile(
                brand_name="天眼查",
                company_name="北京金堤科技有限公司",
            )
        finally:
            _MODULE.requests.post = original_post

        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertEqual(profile.company_name, "北京金堤科技有限公司")
        self.assertEqual(profile.registered_capital, "1000万人民币")
        self.assertEqual(profile.established_time, "2011-01-01")
        self.assertEqual(profile.company_address, "北京市海淀区")
        self.assertEqual(profile.website, "https://www.example.com")
        self.assertEqual(profile.brand_logo, "https://img.example.com/logo.png")
        self.assertEqual(profile.company_intro, "企业简介示例")
        self.assertEqual(profile.unified_social_credit_code, "9111010831813798XE")
        self.assertEqual(profile.legal_representative, "张三")
        self.assertEqual(profile.registration_status, "存续")
        self.assertEqual(profile.customer_service_hotline, "400-000-0000")
        self.assertEqual(calls[0]["headers"]["Authorization"], "api-key-1")
        self.assertEqual(calls[2]["headers"]["Mcp-Session-Id"], "session-1")
        self.assertEqual(calls[3]["json"]["params"]["arguments"], {"searchKey": "北京金堤科技有限公司"})

    def test_lookup_company_profile_uses_company_name_when_schema_requires_it(self) -> None:
        calls: list[dict[str, object]] = []

        def fake_post(url, json=None, headers=None, timeout=None):
            calls.append(
                {
                    "url": url,
                    "json": json,
                    "headers": headers,
                    "timeout": timeout,
                }
            )
            method = (json or {}).get("method")
            if method == "initialize":
                return _FakeResponse(
                    headers={"Mcp-Session-Id": "session-2", "Content-Type": "application/json"},
                    payload={"jsonrpc": "2.0", "id": "init-2", "result": {"protocolVersion": "2025-03-26"}},
                )
            if method == "notifications/initialized":
                return _FakeResponse(headers={"Content-Type": "application/json"}, payload={})
            if method == "tools/list":
                return _FakeResponse(
                    headers={"Content-Type": "application/json"},
                    payload={
                        "jsonrpc": "2.0",
                        "id": "tools-list-2",
                        "result": {
                            "tools": [
                                {
                                    "name": "company.registration-info",
                                    "description": "查询企业工商登记信息",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {
                                            "company_name": {"type": "string"},
                                        },
                                    },
                                }
                            ]
                        },
                    },
                )
            if method == "tools/call":
                return _FakeResponse(
                    headers={"Content-Type": "application/json"},
                    payload={
                        "jsonrpc": "2.0",
                        "id": "tools-call-2",
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": "\n".join(
                                        [
                                            "# 公司基础画像：北京金堤科技有限公司",
                                            "| 字段 | 值 |",
                                            "|---|---|",
                                            "| 企业名称 | 北京金堤科技有限公司 |",
                                            "| 注册资本 | 1000万人民币 |",
                                            "| 官网 | https://www.example.com |",
                                        ]
                                    ),
                                }
                            ]
                        },
                    },
                )
            raise AssertionError(f"unexpected method: {method}")

        original_post = _MODULE.requests.post
        _MODULE.requests.post = fake_post
        try:
            client = TianyanchaClient(
                types.SimpleNamespace(
                    tianyancha_enabled=True,
                    tianyancha_api_key="api-key-2",
                    tianyancha_mcp_url="https://mcp.tianyancha.com/v1",
                    tianyancha_timeout_seconds=15.0,
                )
            )
            profile = client.lookup_company_profile(
                brand_name="天眼查",
                company_name="北京金堤科技有限公司",
            )
        finally:
            _MODULE.requests.post = original_post

        self.assertIsNotNone(profile)
        self.assertEqual(calls[3]["json"]["params"]["arguments"], {"company_name": "北京金堤科技有限公司"})

    def test_lookup_company_management_filters_noise_and_limits_to_three(self) -> None:
        def fake_post(url, json=None, headers=None, timeout=None):
            method = (json or {}).get("method")
            if method == "initialize":
                return _FakeResponse(
                    headers={"Mcp-Session-Id": "session-3", "Content-Type": "application/json"},
                    payload={"jsonrpc": "2.0", "id": "init-3", "result": {"protocolVersion": "2025-03-26"}},
                )
            if method == "notifications/initialized":
                return _FakeResponse(headers={"Content-Type": "application/json"}, payload={})
            if method == "tools/list":
                return _FakeResponse(
                    headers={"Content-Type": "application/json"},
                    payload={
                        "jsonrpc": "2.0",
                        "id": "tools-list-3",
                        "result": {
                            "tools": [
                                {
                                    "name": "company.management-info",
                                    "description": "查询企业主要人员与管理层信息",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {
                                            "company_name": {"type": "string"},
                                        },
                                    },
                                }
                            ]
                        },
                    },
                )
            if method == "tools/call":
                return _FakeResponse(
                    headers={"Content-Type": "application/json"},
                    payload={
                        "jsonrpc": "2.0",
                        "id": "tools-call-3",
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": "\n".join(
                                        [
                                            "## 主要人员",
                                            "| 姓名 | 职位 |",
                                            "|---|---|",
                                            "| 李想 | 创始人 |",
                                            "| 冯伟丽 | 经理 |",
                                            "| 徐点 | 监事 |",
                                            "| 贾晓彦 | 财务负责人 |",
                                            "",
                                            "## 其他信息",
                                            "| 名称 | 值 |",
                                            "|---|---|",
                                            "| 成立日期 | 2015-04-10 |",
                                            "| 企业名称 | 北京车和家信息技术有限公司 |",
                                            "| 地址 | 北京市顺义区高丽营镇恒兴路4号院1幢101室(科技创新功能区) |",
                                            "| ok | 0 |",
                                        ]
                                    ),
                                }
                            ]
                        },
                    },
                )
            raise AssertionError(f"unexpected method: {method}")

        original_post = _MODULE.requests.post
        _MODULE.requests.post = fake_post
        try:
            client = TianyanchaClient(
                types.SimpleNamespace(
                    tianyancha_enabled=True,
                    tianyancha_api_key="api-key-3",
                    tianyancha_mcp_url="https://mcp.tianyancha.com/v1",
                    tianyancha_timeout_seconds=15.0,
                )
            )
            members = client.lookup_company_management(
                brand_name="理想",
                company_name="北京车和家信息技术有限公司",
            )
        finally:
            _MODULE.requests.post = original_post

        self.assertEqual(len(members), 3)
        self.assertEqual(members[0].name, "李想")
        self.assertEqual(members[0].title, "创始人")
        self.assertEqual(members[1].name, "冯伟丽")
        self.assertEqual(members[2].name, "徐点")

    def test_lookup_company_management_skips_insufficient_entitlement(self) -> None:
        calls: list[dict[str, object]] = []

        def fake_post(url, json=None, headers=None, timeout=None):
            calls.append(
                {
                    "url": url,
                    "json": json,
                    "headers": headers,
                    "timeout": timeout,
                }
            )
            method = (json or {}).get("method")
            if method == "initialize":
                return _FakeResponse(
                    headers={"Mcp-Session-Id": "session-4", "Content-Type": "application/json"},
                    payload={"jsonrpc": "2.0", "id": "init-4", "result": {"protocolVersion": "2025-03-26"}},
                )
            if method == "notifications/initialized":
                return _FakeResponse(headers={"Content-Type": "application/json"}, payload={})
            if method == "tools/list":
                return _FakeResponse(
                    headers={"Content-Type": "application/json"},
                    payload={
                        "jsonrpc": "2.0",
                        "id": "tools-list-4",
                        "result": {
                            "tools": [
                                {
                                    "name": "get_company_people",
                                    "description": "查询企业主要人员与管理层信息",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {
                                            "company_name": {"type": "string"},
                                        },
                                    },
                                }
                            ]
                        },
                    },
                )
            if method == "tools/call":
                return _FakeResponse(
                    headers={"Content-Type": "application/json"},
                    payload={
                        "currentPlan": "free",
                        "error": "insufficient_entitlement",
                        "error_description": "工具 get_company_people 需要 VIP 权益，请升级后重试",
                        "message": "工具 get_company_people 需要 VIP 权益，请升级后重试",
                        "requiredPlan": "vip",
                        "tools": ["get_company_people"],
                    },
                    status_code=403,
                )
            raise AssertionError(f"unexpected method: {method}")

        original_post = _MODULE.requests.post
        _MODULE.requests.post = fake_post
        try:
            client = TianyanchaClient(
                types.SimpleNamespace(
                    tianyancha_enabled=True,
                    tianyancha_api_key="api-key-4",
                    tianyancha_mcp_url="https://mcp.tianyancha.com/v1",
                    tianyancha_timeout_seconds=15.0,
                )
            )
            members = client.lookup_company_management(
                brand_name="西安圣心安诺",
                company_name="西安圣心安诺心理咨询有限公司",
            )
        finally:
            _MODULE.requests.post = original_post

        self.assertEqual(members, [])
        self.assertEqual(calls[3]["json"]["method"], "tools/call")

    def test_lookup_company_profile_skips_quota_exceeded(self) -> None:
        calls: list[dict[str, object]] = []

        def fake_post(url, json=None, headers=None, timeout=None):
            calls.append(
                {
                    "url": url,
                    "json": json,
                    "headers": headers,
                    "timeout": timeout,
                }
            )
            method = (json or {}).get("method")
            if method == "initialize":
                return _FakeResponse(
                    headers={"Mcp-Session-Id": "session-5", "Content-Type": "application/json"},
                    payload={"jsonrpc": "2.0", "id": "init-5", "result": {"protocolVersion": "2025-03-26"}},
                )
            if method == "notifications/initialized":
                return _FakeResponse(headers={"Content-Type": "application/json"}, payload={})
            if method == "tools/list":
                return _FakeResponse(
                    headers={"Content-Type": "application/json"},
                    payload={
                        "jsonrpc": "2.0",
                        "id": "tools-list-5",
                        "result": {
                            "tools": [
                                {
                                    "name": "company.registration-info",
                                    "description": "查询企业工商登记信息",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {
                                            "company_name": {"type": "string"},
                                        },
                                    },
                                }
                            ]
                        },
                    },
                )
            if method == "tools/call":
                return _FakeResponse(
                    headers={"Content-Type": "application/json"},
                    payload={
                        "error": "quota_exceeded",
                        "message": "日额度已用完",
                        "quota_type": "day",
                        "limit": 100,
                        "reset_at": "2026-09-08T00:00:00+08:00",
                    },
                    status_code=402,
                )
            raise AssertionError(f"unexpected method: {method}")

        original_post = _MODULE.requests.post
        _MODULE.requests.post = fake_post
        try:
            client = TianyanchaClient(
                types.SimpleNamespace(
                    tianyancha_enabled=True,
                    tianyancha_api_key="api-key-5",
                    tianyancha_mcp_url="https://mcp.tianyancha.com/v1",
                    tianyancha_timeout_seconds=15.0,
                )
            )
            profile = client.lookup_company_profile(
                brand_name="西安圣心安诺",
                company_name="西安圣心安诺心理咨询有限公司",
            )
        finally:
            _MODULE.requests.post = original_post

        self.assertIsNone(profile)
        self.assertEqual(calls[3]["json"]["method"], "tools/call")

    def test_lookup_company_management_skips_rate_limited(self) -> None:
        calls: list[dict[str, object]] = []

        def fake_post(url, json=None, headers=None, timeout=None):
            calls.append(
                {
                    "url": url,
                    "json": json,
                    "headers": headers,
                    "timeout": timeout,
                }
            )
            method = (json or {}).get("method")
            if method == "initialize":
                return _FakeResponse(
                    headers={"Mcp-Session-Id": "session-6", "Content-Type": "application/json"},
                    payload={"jsonrpc": "2.0", "id": "init-6", "result": {"protocolVersion": "2025-03-26"}},
                )
            if method == "notifications/initialized":
                return _FakeResponse(headers={"Content-Type": "application/json"}, payload={})
            if method == "tools/list":
                return _FakeResponse(
                    headers={"Content-Type": "application/json"},
                    payload={
                        "jsonrpc": "2.0",
                        "id": "tools-list-6",
                        "result": {
                            "tools": [
                                {
                                    "name": "get_company_people",
                                    "description": "查询企业主要人员与管理层信息",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {
                                            "company_name": {"type": "string"},
                                        },
                                    },
                                }
                            ]
                        },
                    },
                )
            if method == "tools/call":
                return _FakeResponse(
                    headers={"Content-Type": "application/json"},
                    payload={
                        "error": "rate_limited",
                        "message": "访问频率过快 / 限流",
                    },
                    status_code=429,
                )
            raise AssertionError(f"unexpected method: {method}")

        original_post = _MODULE.requests.post
        _MODULE.requests.post = fake_post
        try:
            client = TianyanchaClient(
                types.SimpleNamespace(
                    tianyancha_enabled=True,
                    tianyancha_api_key="api-key-6",
                    tianyancha_mcp_url="https://mcp.tianyancha.com/v1",
                    tianyancha_timeout_seconds=15.0,
                )
            )
            members = client.lookup_company_management(
                brand_name="西安圣心安诺",
                company_name="西安圣心安诺心理咨询有限公司",
            )
        finally:
            _MODULE.requests.post = original_post

        self.assertEqual(members, [])
        self.assertEqual(calls[3]["json"]["method"], "tools/call")


if __name__ == "__main__":
    unittest.main()
