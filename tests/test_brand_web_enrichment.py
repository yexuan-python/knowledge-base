from __future__ import annotations

import sys
import types
import unittest

from tests._stub_utils import ensure_stub_module


def _install_import_stubs() -> None:
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
        dashscope_stub.Generation = type("Generation", (), {"call": staticmethod(lambda *args, **kwargs: None)})
        sys.modules.setdefault("dashscope", dashscope_stub)


_install_import_stubs()

from knowledge_base.brand.ai import web_enrichment
from knowledge_base.infrastructure.settings import Settings


class BrandWebEnrichmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_web_enrichment_discovers_and_fetches_sources_before_llm_fill(self) -> None:
        get_calls: list[dict[str, object]] = []

        class FakeResponse:
            def __init__(self, text: str, *, content_type: str = "text/html; charset=utf-8") -> None:
                self.text = text
                self.headers = {"Content-Type": content_type}

            def raise_for_status(self) -> None:
                return None

        def fake_get(url, *args, **kwargs):
            params = kwargs.get("params") or {}
            get_calls.append({"url": url, "params": params})
            if url == "https://duckduckgo.com/html/":
                query = str(params.get("q") or "")
                if "国家企业信用信息公示系统" in query:
                    return FakeResponse(
                        '<html><body><a href="https://www.gsxt.gov.cn/company/demo">公示系统</a></body></html>'
                    )
                return FakeResponse(
                    '<html><body><a href="https://brand.example.com">官网</a></body></html>'
                )
            if url == "https://brand.example.com":
                return FakeResponse(
                    """
                    <html>
                      <head><title>品牌官网</title></head>
                      <body>
                        <h1>示例品牌管理团队</h1>
                        <a href="/team">团队介绍</a>
                        官网介绍文本
                      </body>
                    </html>
                    """
                )
            if url == "https://brand.example.com/team":
                return FakeResponse(
                    """
                    <html>
                      <body>
                        张三 联合创始人
                        https://brand.example.com/team/zhangsan
                      </body>
                    </html>
                    """
                )
            if url == "https://www.gsxt.gov.cn/company/demo":
                return FakeResponse(
                    """
                    <html>
                      <body>
                        国家企业信用信息公示系统 企业信息
                      </body>
                    </html>
                    """
                )
            raise AssertionError(f"unexpected url: {url}")

        def fake_call(prompt: str, *, settings):
            self.assertIn("https://brand.example.com", prompt)
            self.assertIn("https://brand.example.com/team", prompt)
            self.assertIn("https://www.gsxt.gov.cn/company/demo", prompt)
            return {
                "management_team": [
                    {
                        "member_name": "张三",
                        "position": "联合创始人",
                        "profile": "官网团队页人物介绍",
                        "introduction_website": "https://brand.example.com/team/zhangsan",
                        "other_info": "来源于官网团队页",
                    }
                ]
            }

        result = await web_enrichment.enrich_brand_fields_from_web(
            brand_name="示例品牌",
            company_name="示例企业主体",
            official_website="https://brand.example.com",
            missing_fields={
                "management_team": [
                    {
                        "member_name": "张三",
                        "position": "",
                        "profile": "",
                        "introduction_website": "",
                        "other_info": "",
                    }
                ]
            },
            settings=Settings(),
            requests_module=types.SimpleNamespace(get=fake_get),
            text_json_caller=fake_call,
        )

        self.assertEqual(result["management_team"][0]["position"], "联合创始人")
        self.assertTrue(any(call["url"] == "https://duckduckgo.com/html/" for call in get_calls))
        self.assertTrue(any(call["url"] == "https://brand.example.com" for call in get_calls))
        self.assertTrue(any(call["url"] == "https://brand.example.com/team" for call in get_calls))

    async def test_web_enrichment_returns_empty_when_no_sources_found(self) -> None:
        class FakeResponse:
            def __init__(self, text: str, *, content_type: str = "text/html; charset=utf-8") -> None:
                self.text = text
                self.headers = {"Content-Type": content_type}

            def raise_for_status(self) -> None:
                return None

        def fake_get(url, *args, **kwargs):
            if url == "https://duckduckgo.com/html/":
                return FakeResponse("<html><body>no results</body></html>")
            raise AssertionError(f"unexpected url: {url}")

        def fake_call(prompt: str, *, settings):
            raise AssertionError("LLM should not be called when no usable sources are found")

        result = await web_enrichment.enrich_brand_fields_from_web(
            brand_name="示例品牌",
            company_name="示例企业主体",
            official_website="",
            missing_fields={"management_team": [{"member_name": "张三", "position": ""}]},
            settings=Settings(),
            requests_module=types.SimpleNamespace(get=fake_get),
            text_json_caller=fake_call,
        )

        self.assertEqual(result, {})
