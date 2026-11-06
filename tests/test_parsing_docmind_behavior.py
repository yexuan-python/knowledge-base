from __future__ import annotations

import builtins
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock

from tests._stub_utils import ensure_stub_module


def _install_test_stubs() -> None:
    dotenv_stub = ensure_stub_module("dotenv")
    if dotenv_stub is not None:
        dotenv_stub.load_dotenv = lambda *args, **kwargs: None
        sys.modules.setdefault("dotenv", dotenv_stub)

    requests_stub = ensure_stub_module("requests")
    if requests_stub is not None:
        requests_stub.get = lambda *args, **kwargs: None
        sys.modules.setdefault("requests", requests_stub)

    xlrd_stub = ensure_stub_module("xlrd")
    if xlrd_stub is not None:
        xlrd_stub.open_workbook = lambda *args, **kwargs: None
        sys.modules.setdefault("xlrd", xlrd_stub)

    openpyxl_stub = ensure_stub_module("openpyxl")
    if openpyxl_stub is not None:
        openpyxl_stub.load_workbook = lambda *args, **kwargs: None
        sys.modules.setdefault("openpyxl", openpyxl_stub)

    markitdown_stub = ensure_stub_module("markitdown")
    if markitdown_stub is not None:

        class _FakeMarkItDown:
            def convert(self, *_args, **_kwargs):
                return types.SimpleNamespace(text_content="")

        markitdown_stub.MarkItDown = _FakeMarkItDown
        sys.modules.setdefault("markitdown", markitdown_stub)

    dashscope_stub = ensure_stub_module("dashscope")
    if dashscope_stub is not None:
        dashscope_stub.MultiModalEmbedding = type("MultiModalEmbedding", (), {"call": staticmethod(lambda **kwargs: None)})
        sys.modules.setdefault("dashscope", dashscope_stub)

    pil_stub = ensure_stub_module("PIL")
    if pil_stub is not None:
        pil_stub.Image = type("Image", (), {})
        sys.modules.setdefault("PIL", pil_stub)

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


_install_test_stubs()

from knowledge_base.infrastructure.settings import Settings
from knowledge_base.ingest.infrastructure import DocMindClient, DocMindParseResult, DocumentParser
from knowledge_base.ingest.infrastructure.document_parser import _extract_geo_sheet1_rows
import knowledge_base.ingest.infrastructure.docmind_client as docmind_client_module


class ParsingDocMindBehaviorTests(unittest.TestCase):
    def _build_parser(self) -> DocumentParser:
        settings = Settings(
            docmind_enabled=True,
            docmind_access_key_id="test-ak",
            docmind_access_key_secret="test-sk",
        )
        return DocumentParser(settings)

    def test_docmind_text_only_result_falls_back_to_text_markdown(self) -> None:
        parser = self._build_parser()
        parser._docmind.parse_file = Mock(
            return_value=DocMindParseResult(
                text="这是 DocMind 提取出来的正文内容。",
                markdown_text="",
                task_id="task-123",
            )
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "sample.txt"
            path.write_text("placeholder", encoding="utf-8")

            parsed = parser.parse_path(path, force_docmind=True)

        self.assertEqual(parsed.text, "这是 DocMind 提取出来的正文内容。")
        self.assertEqual(parsed.markdown_text, parsed.text)
        self.assertEqual(parsed.metadata["parser_backend"], "docmind")
        self.assertEqual(parsed.metadata["docmind_task_id"], "task-123")

    def test_force_docmind_parse_passes_source_url_through_to_docmind_client(self) -> None:
        parser = self._build_parser()
        parser._docmind.parse_file = Mock(
            return_value=DocMindParseResult(
                text="DocMind URL submit content",
                markdown_text="# DocMind URL submit content",
                task_id="task-url-123",
            )
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "sample.pptx"
            path.write_bytes(b"fake pptx payload")

            parsed = parser.parse_path(
                path,
                source_name="品牌手册.pptx",
                force_docmind=True,
                source_url="https://static.example.com/brand-handbook.pptx",
            )

        parser._docmind.parse_file.assert_called_once_with(
            path,
            source_url="https://static.example.com/brand-handbook.pptx",
        )
        self.assertEqual(parsed.metadata["parser_backend"], "docmind")
        self.assertEqual(parsed.metadata["docmind_task_id"], "task-url-123")

    def test_non_pdf_parse_does_not_require_pdfplumber_import(self) -> None:
        parser = self._build_parser()
        original_import = builtins.__import__

        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "pdfplumber":
                raise ModuleNotFoundError("pdfplumber intentionally unavailable for test")
            return original_import(name, globals, locals, fromlist, level)

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "notes.txt"
            path.write_text("纯文本内容", encoding="utf-8")

            try:
                builtins.__import__ = guarded_import
                parsed = parser.parse_path(path)
            finally:
                builtins.__import__ = original_import

        self.assertEqual(parsed.text, "纯文本内容")
        self.assertEqual(parsed.markdown_text, "纯文本内容")
        self.assertEqual(parsed.metadata["parser_backend"], "local")

    def test_geo_sheet1_rows_keep_only_dimension_field_and_content_columns(self) -> None:
        class FakeSheet:
            def iter_rows(self, *, values_only: bool):
                assert values_only
                return iter(
                    [
                        ["说明文字", None, None, None, None, None],
                        ["核心维度", "字段名称", "填写说明（示例/说明）", "填写具体内容（客户填写）", "附件/链接", "GEO 作用"],
                        ["品牌/公司实体", "品牌标准名", "说明", "示例品牌", "-", "作用"],
                        [None, "品牌英文名", "说明", "DEMO", None, None],
                        ["第二部分：产品视角", None, None, None, None, None],
                        ["核心维度", "字段名称", "填写说明", "具体内容", "附件/链接", "GEO 作用"],
                        ["产品矩阵", "产品线1", "说明", "主推产品", "https://example.com", None],
                    ]
                )

        rows = _extract_geo_sheet1_rows(FakeSheet())

        self.assertEqual(
            [
                ["核心维度", "字段名称", "填写具体内容（客户填写）"],
                ["品牌/公司实体", "品牌标准名", "示例品牌"],
                ["", "品牌英文名", "DEMO"],
                ["核心维度", "字段名称", "具体内容"],
                ["产品矩阵", "产品线1", "主推产品"],
            ],
            rows,
        )


class DocMindClientBehaviorTests(unittest.TestCase):
    def _build_client(self) -> DocMindClient:
        settings = Settings(
            docmind_enabled=True,
            docmind_access_key_id="test-ak",
            docmind_access_key_secret="test-sk",
        )
        return DocMindClient(settings)

    def test_markdown_download_prefers_https_variant_for_http_output_url(self) -> None:
        client = self._build_client()
        called_urls: list[str] = []
        original_get = docmind_client_module.requests.get

        class FakeResponse:
            def __init__(self, text: str) -> None:
                self._content = text.encode("utf-8")
                self.encoding = None

            def raise_for_status(self) -> None:
                return None

            def iter_content(self, chunk_size: int = 0):
                _ = chunk_size
                yield self._content

            def close(self) -> None:
                return None

        def fake_get(url: str, timeout: int, stream: bool = False):
            called_urls.append(url)
            self.assertEqual(timeout, client._settings.docmind_download_timeout_seconds)
            self.assertTrue(stream)
            if url.startswith("https://"):
                return FakeResponse("# Markdown Content")
            raise AssertionError("http fallback should not be used when https succeeds")

        try:
            docmind_client_module.requests.get = fake_get
            markdown = client._download_markdown_from_status(
                {
                    "output_format_result": [
                        {
                            "output_type": "markdown",
                            "output_file_url": "http://example.com/result.md",
                        }
                    ]
                }
            )
        finally:
            docmind_client_module.requests.get = original_get

        self.assertEqual(markdown, "# Markdown Content")
        self.assertEqual(called_urls, ["https://example.com/result.md"])

    def test_markdown_download_failure_falls_back_to_result_api(self) -> None:
        client = self._build_client()
        client._download_markdown_from_status = Mock(side_effect=RuntimeError("download timeout"))
        client._load_markdown_from_result = Mock(return_value="# Result API Markdown")

        markdown = client._load_markdown_with_fallback(
            "task-123",
            {"output_format_result": []},
            object(),
            object(),
        )

        self.assertEqual(markdown, "# Result API Markdown")
        client._load_markdown_from_result.assert_called_once()

    def test_submit_prefers_source_url_when_available(self) -> None:
        client = self._build_client()
        calls: list[tuple[str, object]] = []

        class FakeRequest:
            def __init__(self, **kwargs) -> None:
                self.__dict__.update(kwargs)

        class FakeModels:
            SubmitDocParserJobRequest = FakeRequest
            SubmitDocParserJobAdvanceRequest = FakeRequest

        class FakeRuntimeOptions:
            def __init__(self, **kwargs) -> None:
                self.__dict__.update(kwargs)

        class FakeRuntimeModels:
            RuntimeOptions = FakeRuntimeOptions

        class FakeClient:
            def submit_doc_parser_job_with_options(self, request, runtime):
                calls.append(("url", request))
                return types.SimpleNamespace(body={"data": {"id": "task-url-submit"}})

            def submit_doc_parser_job_advance(self, request, runtime):
                calls.append(("file", request))
                return types.SimpleNamespace(body={"data": {"id": "task-file-submit"}})

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "sample.pptx"
            path.write_bytes(b"fake-pptx")
            task_id = client._submit_job(
                path,
                FakeClient(),
                FakeModels,
                FakeRuntimeModels,
                source_url="https://static.example.com/sample.pptx",
            )

        self.assertEqual(task_id, "task-url-submit")
        self.assertEqual([mode for mode, _request in calls], ["url"])
        self.assertEqual(calls[0][1].file_url, "https://static.example.com/sample.pptx")

    def test_submit_falls_back_to_file_upload_when_url_submit_fails(self) -> None:
        client = self._build_client()
        calls: list[tuple[str, object]] = []

        class FakeRequest:
            def __init__(self, **kwargs) -> None:
                self.__dict__.update(kwargs)

        class FakeModels:
            SubmitDocParserJobRequest = FakeRequest
            SubmitDocParserJobAdvanceRequest = FakeRequest

        class FakeRuntimeOptions:
            def __init__(self, **kwargs) -> None:
                self.__dict__.update(kwargs)

        class FakeRuntimeModels:
            RuntimeOptions = FakeRuntimeOptions

        class FakeClient:
            def submit_doc_parser_job_with_options(self, request, runtime):
                calls.append(("url", request))
                raise RuntimeError("url submit failed")

            def submit_doc_parser_job_advance(self, request, runtime):
                calls.append(("file", request))
                return types.SimpleNamespace(body={"data": {"id": "task-file-submit"}})

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "sample.pptx"
            path.write_bytes(b"fake-pptx")
            task_id = client._submit_job(
                path,
                FakeClient(),
                FakeModels,
                FakeRuntimeModels,
                source_url="https://static.example.com/sample.pptx",
            )

        self.assertEqual(task_id, "task-file-submit")
        self.assertEqual([mode for mode, _request in calls], ["url", "file"])
        self.assertEqual(calls[0][1].file_url, "https://static.example.com/sample.pptx")
        self.assertEqual(calls[1][1].file_name_extension, "pptx")


if __name__ == "__main__":
    unittest.main()
