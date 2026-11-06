from __future__ import annotations

import threading
import types
import unittest

from knowledge_base.brand_knowledge.application.instruction_web_sources import (
    build_instruction_web_markdown_sources,
    extract_instruction_urls,
)


class InstructionWebSourcesTests(unittest.IsolatedAsyncioTestCase):
    def test_extract_instruction_urls_normalizes_and_deduplicates_http_urls(self) -> None:
        urls = extract_instruction_urls(
            "增加报道：http://city.ce.cn/xx/202608/t20260804_3128272.shtml。"
            "另见 https://example.com/a?x=1，再重复 http://city.ce.cn/xx/202608/t20260804_3128272.shtml",
        )

        self.assertEqual(
            urls,
            [
                "http://city.ce.cn/xx/202608/t20260804_3128272.shtml",
                "https://example.com/a?x=1",
            ],
        )

    def test_extract_instruction_urls_skips_localhost_and_private_ip_urls(self) -> None:
        urls = extract_instruction_urls(
            "http://127.0.0.1/admin https://192.168.1.2/page https://brand.example.com/news"
        )

        self.assertEqual(urls, ["https://brand.example.com/news"])

    def test_extract_instruction_urls_defaults_to_all_and_supports_explicit_limit(self) -> None:
        expected_urls = [f"https://example.com/article-{index}" for index in range(1, 21)]
        instruction = " ".join([*expected_urls, expected_urls[0]])

        self.assertEqual(extract_instruction_urls(instruction), expected_urls)
        self.assertEqual(extract_instruction_urls(instruction, max_urls=4), expected_urls[:4])

    async def test_build_sources_processes_all_urls_with_at_most_three_concurrent_requests(self) -> None:
        expected_urls = [f"https://example.com/article-{index}" for index in range(1, 21)]
        first_three = threading.Barrier(3, timeout=5)
        lock = threading.Lock()
        active = 0
        max_active = 0
        calls: list[str] = []

        class FakeResponse:
            headers = {"content-type": "text/html; charset=utf-8"}
            text = "<html><title>Article</title><body><p>Article body</p></body></html>"

            def raise_for_status(self) -> None:
                return None

        def fake_get(url, **_kwargs):
            nonlocal active, max_active
            with lock:
                calls.append(url)
                active += 1
                max_active = max(max_active, active)
                is_first_three = len(calls) <= 3
            try:
                if is_first_three:
                    first_three.wait()
                if url == expected_urls[6]:
                    raise TimeoutError("timed out")
                return FakeResponse()
            finally:
                with lock:
                    active -= 1

        source_documents, markdown_sources = await build_instruction_web_markdown_sources(
            " ".join(expected_urls),
            requests_module=types.SimpleNamespace(get=fake_get),
        )

        self.assertCountEqual(calls, expected_urls)
        self.assertEqual(max_active, 3)
        self.assertEqual([document["source_url"] for document in source_documents], expected_urls)
        self.assertEqual(source_documents[6]["source_type"], "web_article_error")
        self.assertEqual(source_documents[-1]["source_type"], "web_article")
        self.assertEqual(len(markdown_sources), 19)

    async def test_build_instruction_web_markdown_sources_fetches_article_body(self) -> None:
        get_calls: list[dict[str, object]] = []

        class FakeResponse:
            headers = {"content-type": "text/html; charset=utf-8"}

            text = """
            <html>
              <head>
                <title>页面标题兜底</title>
                <meta property="og:title" content="官方报道标题" />
                <meta property="og:site_name" content="中国经济网" />
                <meta name="publishdate" content="2026-08-04" />
              </head>
              <body>
                <nav>导航内容不应进入正文</nav>
                <article>
                  <h1>官方报道标题</h1>
                  <p>第一段报道正文。</p>
                  <p>第二段报道正文，包含品牌新增事实。</p>
                </article>
                <footer>页脚不应进入正文</footer>
              </body>
            </html>
            """

            def raise_for_status(self) -> None:
                return None

        def fake_get(url, **kwargs):
            get_calls.append({"url": url, "kwargs": kwargs})
            return FakeResponse()

        source_documents, markdown_sources = await build_instruction_web_markdown_sources(
            "增加官方报道文章：http://city.ce.cn/xx/202608/t20260804_3128272.shtml",
            requests_module=types.SimpleNamespace(get=fake_get),
        )

        self.assertEqual(len(source_documents), 1)
        self.assertEqual(len(markdown_sources), 1)
        self.assertEqual(get_calls[0]["url"], "http://city.ce.cn/xx/202608/t20260804_3128272.shtml")
        self.assertEqual(get_calls[0]["kwargs"]["timeout"], 30)
        self.assertEqual(source_documents[0]["source_type"], "web_article")
        self.assertEqual(markdown_sources[0]["source_role"], "iteration_web_article")
        markdown_text = markdown_sources[0]["markdown_text"]
        self.assertIn("# 网页正文：官方报道标题", markdown_text)
        self.assertIn("来源链接：http://city.ce.cn/xx/202608/t20260804_3128272.shtml", markdown_text)
        self.assertIn("来源名称：中国经济网", markdown_text)
        self.assertIn("发布时间：2026-08-04", markdown_text)
        self.assertIn("第一段报道正文", markdown_text)
        self.assertIn("第二段报道正文，包含品牌新增事实", markdown_text)
        self.assertNotIn("导航内容不应进入正文", markdown_text)
        self.assertNotIn("页脚不应进入正文", markdown_text)

    async def test_build_instruction_web_markdown_sources_skips_mojibake_title_for_display_name(self) -> None:
        class FakeResponse:
            headers = {"content-type": "text/html; charset=utf-8"}

            text = """
            <html>
              <head>
                <meta property="og:title" content="äº”å¤§çŒ´ç¾¤éƒ¨è½å…¨æ–°äº®ç›¸" />
              </head>
              <body>
                <article>
                  <h1>五大猴群部落全新亮相 南湾猴岛焕新IP场景</h1>
                  <p>官方报道正文内容。</p>
                </article>
              </body>
            </html>
            """

            def raise_for_status(self) -> None:
                return None

        def fake_get(_url, **_kwargs):
            return FakeResponse()

        source_documents, markdown_sources = await build_instruction_web_markdown_sources(
            "增加官方报道文章：http://city.ce.cn/xx/202608/t20260804_3128272.shtml",
            requests_module=types.SimpleNamespace(get=fake_get),
        )

        self.assertEqual(
            source_documents[0]["original_filename"],
            "五大猴群部落全新亮相 南湾猴岛焕新IP场景.md",
        )
        self.assertEqual(
            markdown_sources[0]["source_name"],
            "五大猴群部落全新亮相 南湾猴岛焕新IP场景.md",
        )
        self.assertNotIn("äº", source_documents[0]["original_filename"])
        self.assertIn("网页正文：五大猴群部落全新亮相 南湾猴岛焕新IP场景", markdown_sources[0]["markdown_text"])

    async def test_build_instruction_web_markdown_sources_returns_failure_document_without_markdown_source(
        self,
    ) -> None:
        class FakeResponse:
            headers = {"content-type": "text/html; charset=utf-8"}
            text = """
            <html>
              <body>
                <article>
                  <h1>成功链接标题</h1>
                  <p>成功链接正文。</p>
                </article>
              </body>
            </html>
            """

            def raise_for_status(self) -> None:
                return None

        def fake_get(url, **_kwargs):
            if "failed.example.com" in url:
                raise TimeoutError("timed out")
            return FakeResponse()

        source_documents, markdown_sources = await build_instruction_web_markdown_sources(
            "一个成功 https://ok.example.com/news 一个失败 https://failed.example.com/news",
            requests_module=types.SimpleNamespace(get=fake_get),
        )

        self.assertEqual(len(source_documents), 2)
        self.assertEqual(len(markdown_sources), 1)
        self.assertEqual(source_documents[0]["source_type"], "web_article")
        self.assertEqual(source_documents[1]["source_type"], "web_article_error")
        self.assertEqual(source_documents[1]["source_role"], "iteration_web_article_error")
        self.assertEqual(source_documents[1]["source_url"], "https://failed.example.com/news")
        self.assertEqual(source_documents[1]["error_message"], "链接内容提取失败，请复制链接内容到文字要求框")
        self.assertNotIn("markdown_text", source_documents[1])
        self.assertIn("成功链接正文", markdown_sources[0]["markdown_text"])
