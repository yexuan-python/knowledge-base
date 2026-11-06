from __future__ import annotations

import importlib.util
import hashlib
import sys
import tempfile
import types
import unittest
from pathlib import Path

from tests._stub_utils import ensure_stub_module, module_available


def _install_stubs() -> None:
    if not module_available("httpx"):
        httpx_stub = ensure_stub_module("httpx")
        if httpx_stub is not None:
            httpx_stub.ConnectError = type("ConnectError", (Exception,), {})
            httpx_stub.TimeoutException = type("TimeoutException", (Exception,), {})
            httpx_stub.RemoteProtocolError = type("RemoteProtocolError", (Exception,), {})
            httpx_stub.AsyncClient = type("AsyncClient", (), {})
            sys.modules.setdefault("httpx", httpx_stub)
    if not module_available("requests"):
        requests_stub = ensure_stub_module("requests")
        if requests_stub is not None:
            def _unavailable_get(*args, **kwargs):
                raise RuntimeError("requests stub should not be called in this test")

            requests_stub.get = _unavailable_get
            sys.modules.setdefault("requests", requests_stub)
    if not module_available("dashscope"):
        dashscope_stub = ensure_stub_module("dashscope")
        if dashscope_stub is not None:
            dashscope_stub.MultiModalEmbedding = type("MultiModalEmbedding", (), {})
            dashscope_stub.Generation = type("Generation", (), {})
            sys.modules.setdefault("dashscope", dashscope_stub)


_install_stubs()

_MODULE_PATH = Path(__file__).resolve().parents[2] / "knowledge_base" / "brand" / "application" / "ai_knowledge_ingestion.py"
_SPEC = importlib.util.spec_from_file_location("kb_brand_ai_ingestion_test_module", _MODULE_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("无法加载 ai_knowledge_ingestion.py")
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

BrandAiKnowledgeIngestionDependencies = _MODULE.BrandAiKnowledgeIngestionDependencies
BrandAiKnowledgeIngestionService = _MODULE.BrandAiKnowledgeIngestionService


class _FakeBrands:
    def __init__(self, brand: dict[str, object] | None = None) -> None:
        self.brand = brand or {"id": 1, "brand_code": "BRAND-001", "brand_name": "示例品牌"}
        self.upserted_rows: list[dict[str, object]] = []

    def get_brand_by_code(self, brand_code: str):
        if self.brand and self.brand.get("brand_code") == brand_code:
            return dict(self.brand)
        return None

    def upsert_brand(self, **kwargs):
        self.upserted_rows.append(dict(kwargs))
        if self.brand is None:
            self.brand = {}
        for key, value in kwargs.items():
            if value is None:
                continue
            if key == "target_regions":
                self.brand["target_regions_json"] = value
                continue
            self.brand[key] = value
        return int(self.brand.get("id") or 1)


class _FakeParser:
    def __init__(self, markdown_text: str) -> None:
        self.markdown_text = markdown_text
        self.calls: list[dict[str, object]] = []

    def parse_path(self, path: Path, source_name: str | None = None, *, source_url: str | None = None):
        self.calls.append(
            {
                "path": str(path),
                "source_name": source_name,
                "source_url": source_url,
            }
        )
        return types.SimpleNamespace(markdown_text=self.markdown_text, text=self.markdown_text)


class _FakeEmbeddings:
    def embed_documents(self, texts: list[str]):
        return [[float(index + 1)] * 3 for index, _text in enumerate(texts)]


class _FakeVectorStore:
    def __init__(self) -> None:
        self.inserted_chunks: list[dict[str, object]] = []
        self.upserted_facts: list[dict[str, object]] = []
        self.deleted_document_ids: list[str] = []
        self.deleted_fact_ids: list[str] = []

    def insert_chunks(self, *, document_id: str, source_name: str, source_type: str, chunk_payloads: list[dict[str, object]]):
        self.inserted_chunks.append(
            {
                "document_id": document_id,
                "source_name": source_name,
                "source_type": source_type,
                "chunk_payloads": chunk_payloads,
            }
        )

    def upsert_facts(self, facts_data: list[dict], *, partial_update: bool = False) -> None:
        self.upserted_facts.append(
            {
                "facts_data": facts_data,
                "partial_update": partial_update,
            }
        )

    def delete_documents_by_ids(self, document_ids: list[str]) -> None:
        self.deleted_document_ids.extend(document_ids)

    def delete_facts_by_ids(self, fact_ids: list[str]) -> None:
        self.deleted_fact_ids.extend(fact_ids)


class _FakeOssClient:
    def __init__(self) -> None:
        self.enabled = True
        self.uploads: list[tuple[str, bytes, str]] = []

    def upload_bytes(self, data: bytes, object_key: str, content_type: str):
        self.uploads.append((object_key, data, content_type))
        return object_key

    def build_object_url(self, object_key: str):
        return f"https://oss.example.com/{object_key}"


class _FakeBrandFullKnowledgeStore:
    def __init__(self) -> None:
        self.latest_row: dict[str, object] | None = None
        self.same_content_row: dict[str, object] | None = None
        self.source_task_file_row: dict[str, object] | None = None
        self.created_rows: list[dict[str, object]] = []
        self.asset_updates: list[dict[str, object]] = []
        self.promoted_rows: list[dict[str, object]] = []
        self.updated_rows: list[dict[str, object]] = []
        self.old_document_ids: list[str] = []
        self.next_revision_no = 1

    def get_latest_by_brand_code(self, *, brand_code: str):
        return self.latest_row

    def get_next_revision_no(self, *, brand_code: str, version_no: int, knowledge_date: str) -> int:
        return self.next_revision_no

    def get_by_brand_code_and_content_hash(self, *, brand_code: str, content_hash: str):
        return self.same_content_row

    def get_by_brand_code_source_task_file(self, *, brand_code: str, source_task_id: str, file_name: str):
        if self.source_task_file_row is None:
            return None
        if (
            self.source_task_file_row.get("brand_code") == brand_code
            and self.source_task_file_row.get("source_task_id") == source_task_id
            and self.source_task_file_row.get("file_name") == file_name
        ):
            return dict(self.source_task_file_row)
        return None

    def create_brand_full_knowledge_file(self, **kwargs) -> int:
        self.created_rows.append(kwargs)
        return 101

    def update_storage_assets(self, **kwargs) -> None:
        self.asset_updates.append(kwargs)

    def update_ingestion_result(self, **kwargs) -> None:
        self.updated_rows.append(kwargs)

    def promote_latest(self, **kwargs) -> None:
        self.promoted_rows.append(kwargs)

    def list_old_document_ids(self, *, brand_code: str, keep_document_id: str | None = None) -> list[str]:
        return list(self.old_document_ids)


class _FakeFactsStore:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []
        self.upserted_rows: list[dict[str, object]] = []

    def upsert_fact(self, **kwargs) -> None:
        row = dict(kwargs)
        self.upserted_rows.append(row)
        self.rows = [item for item in self.rows if item.get("fact_id") != row.get("fact_id")]
        self.rows.append(row)

    def list_by_brand_code(self, *, brand_code: str) -> list[dict[str, object]]:
        return [dict(item) for item in self.rows if item.get("brand_code") == brand_code]

    def delete_by_brand_code_excluding_document(self, *, brand_code: str, keep_document_id: str) -> int:
        before = len(self.rows)
        self.rows = [
            item
            for item in self.rows
            if not (item.get("brand_code") == brand_code and item.get("source_document_id") != keep_document_id)
        ]
        return before - len(self.rows)


class _FakeJobStore:
    def __init__(self) -> None:
        self.created_jobs: list[dict[str, object]] = []
        self.updated_jobs: list[dict[str, object]] = []

    def create_job(self, **kwargs) -> int:
        self.created_jobs.append(kwargs)
        return len(self.created_jobs)

    def update_job_status(self, **kwargs) -> None:
        self.updated_jobs.append(kwargs)


class _FakeBrandKnowledgeStore:
    def __init__(self) -> None:
        self.rows_by_brand_id: dict[int, list[dict[str, object]]] = {}
        self.upserted_rows: list[dict[str, object]] = []

    def get_all_brand_knowledge_json(self, *, brand_id: int) -> list[dict[str, object]]:
        return list(self.rows_by_brand_id.get(brand_id, []))

    def upsert_brand_knowledge_json(self, **kwargs) -> None:
        self.upserted_rows.append(dict(kwargs))


class _FakeBrandProductsStore:
    def __init__(self) -> None:
        self.rows_by_brand_id: dict[int, list[dict[str, object]]] = {}
        self.last_products_upsert: dict[str, object] | None = None

    def get_brand_products(self, *, brand_id: int) -> list[dict[str, object]]:
        return list(self.rows_by_brand_id.get(brand_id, []))

    def upsert_brand_products(self, *, brand_id: int, brand_name: str, products: list[dict[str, object]]) -> None:
        self.last_products_upsert = {
            "brand_id": brand_id,
            "brand_name": brand_name,
            "products": list(products),
        }



__all__ = [
    "hashlib",
    "sys",
    "tempfile",
    "types",
    "unittest",
    "Path",
    "_MODULE",
    "BrandAiKnowledgeIngestionDependencies",
    "BrandAiKnowledgeIngestionService",
    "_FakeBrands",
    "_FakeParser",
    "_FakeEmbeddings",
    "_FakeVectorStore",
    "_FakeOssClient",
    "_FakeBrandFullKnowledgeStore",
    "_FakeFactsStore",
    "_FakeJobStore",
    "_FakeBrandKnowledgeStore",
    "_FakeBrandProductsStore",
]
