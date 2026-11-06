from __future__ import annotations

import asyncio
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from tests._stub_utils import ensure_stub_module, module_available

def _install_model_stubs() -> None:
    pydantic_stub = ensure_stub_module("pydantic")
    if pydantic_stub is not None:

        class BaseModel:
            def __init__(self, **kwargs):
                for name, value in self.__class__.__dict__.items():
                    if name.startswith("_") or callable(value):
                        continue
                    setattr(self, name, value)
                for key, value in kwargs.items():
                    setattr(self, key, value)

            def model_copy(self, *, update=None):
                data = {
                    key: value
                    for key, value in self.__dict__.items()
                }
                if update:
                    data.update(update)
                return self.__class__(**data)

        def Field(default=None, **kwargs):
            if "default_factory" in kwargs:
                return kwargs["default_factory"]()
            return default

        pydantic_stub.BaseModel = BaseModel
        pydantic_stub.Field = Field
        sys.modules.setdefault("pydantic", pydantic_stub)

    dotenv_stub = ensure_stub_module("dotenv")
    if dotenv_stub is not None:
        dotenv_stub.load_dotenv = lambda *args, **kwargs: None
        sys.modules.setdefault("dotenv", dotenv_stub)

    requests_stub = ensure_stub_module("requests")
    if requests_stub is not None:
        requests_stub.post = lambda *args, **kwargs: None
        sys.modules.setdefault("requests", requests_stub)

    dashscope_stub = ensure_stub_module("dashscope")
    if dashscope_stub is not None:
        dashscope_stub.MultiModalConversation = type("MultiModalConversation", (), {})
        dashscope_stub.Generation = type("Generation", (), {})
        dashscope_stub.MultiModalEmbedding = type("MultiModalEmbedding", (), {})
        sys.modules.setdefault("dashscope", dashscope_stub)

    fastapi_stub = ensure_stub_module("fastapi")
    if fastapi_stub is not None:
        fastapi_stub.UploadFile = type("UploadFile", (), {})
        sys.modules.setdefault("fastapi", fastapi_stub)

    if not module_available("httpx"):
        httpx_stub = ensure_stub_module("httpx")
        if httpx_stub is not None:
            httpx_stub.ConnectError = type("ConnectError", (Exception,), {})
            httpx_stub.TimeoutException = type("TimeoutException", (Exception,), {})
            httpx_stub.RemoteProtocolError = type("RemoteProtocolError", (Exception,), {})
            httpx_stub.AsyncClient = type("AsyncClient", (), {})
            sys.modules.setdefault("httpx", httpx_stub)

    if not module_available("xlrd"):
        xlrd_stub = ensure_stub_module("xlrd")
        if xlrd_stub is not None:
            xlrd_stub.open_workbook = lambda *args, **kwargs: None
            sys.modules.setdefault("xlrd", xlrd_stub)

    if not module_available("markitdown"):
        markitdown_stub = ensure_stub_module("markitdown")
        if markitdown_stub is not None:
            markitdown_stub.MarkItDown = type("MarkItDown", (), {})
            sys.modules.setdefault("markitdown", markitdown_stub)

    if not module_available("openpyxl"):
        openpyxl_stub = ensure_stub_module("openpyxl")
        if openpyxl_stub is not None:
            openpyxl_stub.load_workbook = lambda *args, **kwargs: None
            sys.modules.setdefault("openpyxl", openpyxl_stub)

    module_stubs: dict[str, dict[str, object]] = {
        "knowledge_base.stores.brand_store": {"BrandStore": type("BrandStore", (), {})},
        "knowledge_base.stores.brand_product_store": {"BrandProductStore": type("BrandProductStore", (), {})},
        "knowledge_base.stores.brand_knowledge_store": {"BrandKnowledgeStore": type("BrandKnowledgeStore", (), {})},
        "knowledge_base.stores.industry_store": {"IndustryStore": type("IndustryStore", (), {})},
        "knowledge_base.stores.document_fact_relation_store": {
            "DocumentFactRelationStore": type("DocumentFactRelationStore", (), {})
        },
        "knowledge_base.stores.document_registry_store": {
            "DocumentRegistryStore": type("DocumentRegistryStore", (), {})
        },
        "knowledge_base.infrastructure.embedding": {"EmbeddingService": type("EmbeddingService", (), {})},
        "knowledge_base.infrastructure.milvus_store": {"MilvusVectorStore": type("MilvusVectorStore", (), {})},
        "knowledge_base.infrastructure.oss_client": {"OSSClient": type("OSSClient", (), {})},
        "knowledge_base.stores.upload_task_store": {
            "UploadTaskStore": type("UploadTaskStore", (), {})
        },
    }

    for module_name, attrs in module_stubs.items():
        if module_available(module_name):
            continue
        stub = ensure_stub_module(module_name)
        if stub is None:
            continue
        for attr_name, value in attrs.items():
            setattr(stub, attr_name, value)
        sys.modules[module_name] = stub


_install_model_stubs()

from knowledge_base.brand.schemas import BrandAttachment, BrandCompetitor, BrandProduct, BrandUploadRequest
from knowledge_base.upload_task.application import (
    UploadTaskApplicationDependencies,
    UploadTaskApplicationService,
)


class FakeBrandStore:
    def __init__(self) -> None:
        self.last_upsert_brand_kwargs = None

    def upsert_brand(self, **kwargs):
        self.last_upsert_brand_kwargs = kwargs
        return 1


class FakeBrandProductStore:
    def __init__(self) -> None:
        self.last_products_upsert = None

    def upsert_brand_products(self, *, brand_id: int, brand_name: str, products: list[dict]):
        self.last_products_upsert = {
            "brand_id": brand_id,
            "brand_name": brand_name,
            "products": products,
        }


class FakeIndustryStore:
    def __init__(self) -> None:
        self.last_upsert_industry_kwargs = None

    def upsert_industry(self, **kwargs):
        self.last_upsert_industry_kwargs = kwargs
        return kwargs.get("industry_id", 0)


class FakeDocumentRegistryStore:
    def __init__(self) -> None:
        self.last_reserved_files: list[dict] = []

    def reserve_document_uploads(self, *, category: str, task_id: str, files: list[dict], allow_partial: bool):
        self.last_reserved_files = list(files)
        return {
            "reserved_files": list(files),
            "duplicate_files": [],
        }

    def release_document_upload(self, **kwargs):
        return None

    def get_document_ai_statuses(self, document_ids: list[str]):
        return {
            document_id: {
                "facts_status": "success",
            }
            for document_id in document_ids
        }

class FakeUploadTaskStore:
    def __init__(self) -> None:
        self.created_task = None
        self.updated_statuses: list[tuple[str, str]] = []

    def create_upload_task(self, *, task_id: str, task_type: str | None = None, metadata: dict, chunk_size, chunk_overlap, files: list[dict]):
        normalized_files: list[dict] = []
        for index, file in enumerate(files):
            normalized_file = dict(file)
            normalized_file.setdefault("file_index", index)
            normalized_file.setdefault("id", normalized_file["file_index"])
            normalized_file.setdefault("status", "pending")
            normalized_files.append(normalized_file)
        self.created_task = {
            "task_id": task_id,
            "task_type": task_type,
            "metadata": metadata,
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
            "files": normalized_files,
            "status": "queued",
        }

    def get_upload_task_files(self, task_id: str):
        if self.created_task and self.created_task["task_id"] == task_id:
            return self.created_task["files"]
        return []

    def refresh_upload_task_counts(self, task_id: str):
        files = self.get_upload_task_files(task_id)
        return {
            "file_count": len(files),
            "success_count": sum(1 for file in files if file.get("status") == "success"),
            "failed_count": sum(1 for file in files if file.get("status") == "failed"),
            "pending_count": sum(1 for file in files if file.get("status", "pending") == "pending"),
            "processing_count": sum(1 for file in files if file.get("status") == "processing"),
        }

    def get_upload_task(self, task_id: str):
        if self.created_task and self.created_task["task_id"] == task_id:
            return {
                "task_id": task_id,
                "task_type": self.created_task.get("task_type"),
                "metadata_json": self.created_task["metadata"],
                "status": self.created_task.get("status", "queued"),
                "chunk_size": self.created_task.get("chunk_size"),
                "chunk_overlap": self.created_task.get("chunk_overlap"),
            }
        return None

    def update_upload_task_status(self, task_id: str, status: str, error_message=None):
        self.updated_statuses.append((task_id, status))
        if self.created_task and self.created_task["task_id"] == task_id:
            self.created_task["status"] = status

    def update_upload_task_file_status(self, file_id: int, status: str, **kwargs):
        if not self.created_task:
            return
        for file in self.created_task["files"]:
            if int(file.get("id", file.get("file_index", -1))) == file_id:
                file["status"] = status
                file.update(kwargs)
                break


class FakeAttachmentAssetStore:
    def __init__(self) -> None:
        self.assets_by_hash: dict[tuple[str, str], dict] = {}
        self.created_assets: list[dict] = []
        self.deleted_asset_ids: list[int] = []

    def get_by_brand_code_and_file_hash(self, *, brand_code: str, file_hash: str):
        return self.assets_by_hash.get((brand_code, file_hash))

    def create_asset(self, **kwargs):
        asset_id = len(self.created_assets) + 1
        record = {"id": asset_id, **kwargs}
        self.created_assets.append(record)
        self.assets_by_hash[(kwargs["brand_code"], kwargs["file_hash"])] = record
        return asset_id

    def get_next_converted_version(self, *, brand_code: str, original_filename: str) -> int:
        matching_rows = [
            item
            for item in self.created_assets
            if item.get("brand_code") == brand_code and item.get("original_filename") == original_filename
        ]
        return len(matching_rows) + 1

    def delete_by_id(self, *, asset_id: int) -> int:
        self.deleted_asset_ids.append(asset_id)
        before = len(self.created_assets)
        self.created_assets = [item for item in self.created_assets if int(item.get("id") or 0) != asset_id]
        self.assets_by_hash = {
            key: value
            for key, value in self.assets_by_hash.items()
            if int(value.get("id") or 0) != asset_id
        }
        return 1 if len(self.created_assets) != before else 0


class FakeDocumentCategoryStore:
    def __init__(self) -> None:
        self.added: list[tuple[str, str, str | None]] = []
        self.removed: list[str] = []

    def add_document(self, document_id: str, category: str, subcategory: str | None = None):
        self.added.append((document_id, category, subcategory))

    def remove_document(self, document_id: str):
        self.removed.append(document_id)

    def invalidate_latest_document_ids_cache(self, *_args, **_kwargs):
        return None


class FakeEmbeddings:
    def __init__(self) -> None:
        self.inputs: list[list[str]] = []

    def embed_documents(self, texts: list[str]):
        self.inputs.append(list(texts))
        return [[0.1, 0.2, 0.3] for _ in texts]


class FakeVectorStore:
    def __init__(self) -> None:
        self.inserted_rows: list[dict] = []
        self.deleted_document_ids: list[str] = []
        self.fail_on_insert = False

    def insert_chunks(self, *, document_id: str, source_name: str, source_type: str, chunk_payloads: list[dict]):
        if self.fail_on_insert:
            raise RuntimeError("milvus write failed")
        self.inserted_rows.append(
            {
                "document_id": document_id,
                "source_name": source_name,
                "source_type": source_type,
                "chunk_payloads": chunk_payloads,
            }
        )

    def delete_document(self, document_id: str):
        self.deleted_document_ids.append(document_id)


class FakeOSSClient:
    def __init__(self) -> None:
        self.enabled = True
        self.uploaded: list[tuple[object, str, str]] = []
        self.deleted: list[str] = []

    def upload_bytes(self, data: bytes, object_key: str, content_type: str):
        self.uploaded.append((data, object_key, content_type))
        return object_key

    def upload_file(self, file_path: str, object_key: str, content_type: str):
        self.uploaded.append((file_path, object_key, content_type))
        return object_key

    def build_object_url(self, object_key: str):
        return f"https://oss.example.com/{object_key}"

    def delete_object(self, object_key: str):
        self.deleted.append(object_key)
        return True


class FakeBrandAiKnowledgeIngestionService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def ingest_upload_task_file(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "status": "success",
            "skipped": False,
            "document_id": "brandkb-doc-1",
            "full_knowledge_file_id": 101,
            "markdown_oss_key": "BRAND-001/ai_knowledge/【示例品牌】品牌AI知识库_V3_20260715.md",
            "markdown_oss_url": "https://oss.example.com/BRAND-001/ai_knowledge/【示例品牌】品牌AI知识库_V3_20260715.md",
            "content_type": "text/markdown",
            "file_hash": "hash-1",
            "file_size": 128,
        }


class FakeParser:
    def parse_path(self, *_args, **_kwargs):
        return types.SimpleNamespace(markdown_text="# 品牌手册\n解析后的内容", source_type="pdf")


class FakeBrandFullKnowledgeStatusStore:
    def __init__(self) -> None:
        self.rows_by_id: dict[int, dict] = {}

    def get_by_ids(self, *, file_ids: list[int]) -> dict[int, dict]:
        return {
            int(file_id): self.rows_by_id[int(file_id)]
            for file_id in file_ids
            if int(file_id) in self.rows_by_id
        }


class FakeBrandKnowledgeIngestionJobStore:
    def __init__(self) -> None:
        self.jobs_by_id: dict[str, dict] = {}

    def get_job(self, *, job_id: str) -> dict | None:
        return self.jobs_by_id.get(job_id)


class FakeBrandKnowledgeSessionStore:
    def __init__(self) -> None:
        self.sessions_by_task: dict[tuple[str, str | None], dict] = {}

    def get_latest_by_source_task_id(self, *, source_task_id: str, session_kind: str | None = None):
        return self.sessions_by_task.get((source_task_id, session_kind))


class BrandUploadTaskBehaviorTests(unittest.IsolatedAsyncioTestCase):
    async def test_enqueue_brand_ai_knowledge_url_task_creates_formal_upload_task(self) -> None:
        upload_tasks = FakeUploadTaskStore()
        queue: asyncio.Queue = asyncio.Queue()
        queued_task_ids: set[str] = set()
        application = UploadTaskApplicationService(
            UploadTaskApplicationDependencies(
                settings=types.SimpleNamespace(
                    upload_staging_dir="/tmp/unused",
                    brand_completion_callback_url="",
                ),
                brands=FakeBrandStore(),
                brand_products=FakeBrandProductStore(),
                industries=FakeIndustryStore(),
                document_registry=FakeDocumentRegistryStore(),
                document_categories=types.SimpleNamespace(),
                upload_tasks=upload_tasks,
                queue=queue,
                queued_task_ids=queued_task_ids,
                queue_lock=asyncio.Lock(),
                ingest_text_document=None,
                ingest_from_url=None,
                ingest_staged_file=None,
                notify_failed_upload_files=_noop_async,
                notify_upload_failure=_noop_async,
                schedule_delayed_completion_check=lambda *_args, **_kwargs: None,
            )
        )

        response = await application.enqueue_brand_ai_knowledge_url_task(
            filename="【燕之屋】品牌AI知识库_V3_20260918.md",
            source_url="https://example.com/kb.md",
            brand_code="100209",
            brand_name="燕之屋",
        )

        self.assertEqual("queued", response.status)
        self.assertEqual(1, response.file_count)
        self.assertEqual("document_upload", upload_tasks.created_task["task_type"])
        self.assertEqual(["brand_ai_knowledge"], [item["file_role"] for item in upload_tasks.created_task["files"]])
        self.assertEqual("", upload_tasks.created_task["files"][0]["stored_path"])
        self.assertEqual("100209", upload_tasks.created_task["metadata"]["brand_code"])
        self.assertEqual("燕之屋", upload_tasks.created_task["metadata"]["brand_name"])
        self.assertEqual("燕之屋", upload_tasks.created_task["metadata"]["category"])
        self.assertTrue(upload_tasks.created_task["metadata"]["backfill_brand_knowledge_json_empty_only"])
        self.assertEqual(
            {
                "source_url": "https://example.com/kb.md",
                "content_type": "text/markdown",
            },
            upload_tasks.created_task["metadata"]["_task_payload"]["file_metadata_by_index"]["0"],
        )
        self.assertEqual(response.task_id, await queue.get())

    async def test_brand_upload_does_not_stage_intro_or_competitors_for_milvus(self) -> None:
        scheduled_checks: list[tuple[str, int]] = []

        application = UploadTaskApplicationService(
            UploadTaskApplicationDependencies(
                settings=types.SimpleNamespace(
                    upload_staging_dir="/tmp/unused",
                    brand_completion_callback_url="",
                ),
                brands=FakeBrandStore(),
                brand_products=FakeBrandProductStore(),
                industries=FakeIndustryStore(),
                document_registry=FakeDocumentRegistryStore(),
                document_categories=types.SimpleNamespace(),
                upload_tasks=FakeUploadTaskStore(),
                queue=asyncio.Queue(),
                queued_task_ids=set(),
                queue_lock=asyncio.Lock(),
                ingest_text_document=None,
                ingest_from_url=None,
                ingest_staged_file=None,
                notify_failed_upload_files=_noop_async,
                notify_upload_failure=_noop_async,
                schedule_delayed_completion_check=lambda task_id, delay_seconds=600: scheduled_checks.append((task_id, delay_seconds)),
            )
        )

        request = BrandUploadRequest(
            brand_name="示例品牌",
            industry_id=12,
            industry_code="STONE",
            industry_name="石材",
            enterprise_subject="示例企业主体",
            business_license_url="https://example.com/license.png",
            intro="品牌介绍",
            competitors=[BrandCompetitor(name="竞品A", website="https://example.com/a")],
            attachments=[BrandAttachment(name="品牌手册.pdf", url="https://example.com/brand-book.pdf")],
            products=[
                BrandProduct(
                    name="产品A",
                    product_description="产品介绍",
                    competitors=[
                        BrandCompetitor(name="竞品1"),
                        BrandCompetitor(name="竞品2", website="https://example.com/product-competitor-2"),
                    ],
                    attachments=[BrandAttachment(name="产品资料.pdf", url="https://example.com/product-a.pdf")],
                )
            ],
        )

        response = await application.enqueue_brand_upload_task(request)

        self.assertEqual(response.status, "queued")
        self.assertEqual(response.file_count, 2)
        self.assertEqual(scheduled_checks, [])
        self.assertEqual(
            application._deps.industries.last_upsert_industry_kwargs,
            {
                "industry_id": 12,
                "code": "STONE",
                "name": "石材",
            },
        )
        self.assertEqual(application._deps.brands.last_upsert_brand_kwargs["industry_id"], 12)
        self.assertEqual(application._deps.brands.last_upsert_brand_kwargs["brand_enterprise_entity"], "示例企业主体")
        self.assertEqual(
            application._deps.brands.last_upsert_brand_kwargs["business_license_image_path"],
            "https://example.com/license.png",
        )
        self.assertEqual(application._deps.brands.last_upsert_brand_kwargs["intro"], "品牌介绍")
        self.assertEqual(application._deps.brands.last_upsert_brand_kwargs["competitors"], ["竞品A"])
        self.assertEqual(
            application._deps.brand_products.last_products_upsert["products"],
            [
                {
                    "product_name": "产品A",
                    "product_alias": None,
                    "product_description": "产品介绍",
                    "product_website": None,
                    "product_images": [],
                    "competitors": [
                        {"name": "竞品1", "website": None},
                        {"name": "竞品2", "website": "https://example.com/product-competitor-2"},
                    ],
                }
            ],
        )

        created_files = application._deps.upload_tasks.created_task["files"]
        self.assertEqual(
            [item["original_filename"] for item in created_files],
            ["品牌手册.pdf", "产品资料.pdf"],
        )
        created_metadata = application._deps.upload_tasks.created_task["metadata"]
        self.assertEqual(created_metadata["industry_id"], 12)
        self.assertEqual(created_metadata["industry_code"], "STONE")
        self.assertEqual(created_metadata["industry_name"], "石材")
        self.assertEqual(created_metadata["brand_enterprise_entity"], "示例企业主体")
        self.assertEqual(created_metadata["business_license_image_path"], "https://example.com/license.png")
        self.assertEqual(created_metadata["intro"], "品牌介绍")
        self.assertEqual(created_metadata["competitors"], ["竞品A"])
        self.assertEqual(
            created_metadata["_task_payload"]["requested_products"],
            [
                {
                    "product_name": "产品A",
                    "product_alias": None,
                    "product_description": "产品介绍",
                    "product_website": None,
                    "product_images": [],
                    "competitors": [
                        {"name": "竞品1", "website": None},
                        {"name": "竞品2", "website": "https://example.com/product-competitor-2"},
                    ],
                }
            ],
        )
        self.assertEqual(
            created_metadata["_task_payload"]["requested_competitors"],
            [
                {
                    "name": "竞品A",
                    "website": "https://example.com/a",
                }
            ],
        )
        self.assertEqual(
            created_metadata["_task_payload"]["file_metadata_by_index"],
            {
                "0": {"source_url": "https://example.com/brand-book.pdf"},
                "1": {
                    "source_url": "https://example.com/product-a.pdf",
                    "subcategory": "产品A",
                    "product_name": "产品A",
                    "product_alias": None,
                    "product_images": [],
                    "product_link": None,
                    "product_description": "产品介绍",
                    "product_competitors": [
                        {"name": "竞品1", "website": None},
                        {"name": "竞品2", "website": "https://example.com/product-competitor-2"},
                    ],
                },
            },
        )

    async def test_brand_upload_keeps_ai_knowledge_named_file_on_attachment_flow(self) -> None:
        application = UploadTaskApplicationService(
            UploadTaskApplicationDependencies(
                settings=types.SimpleNamespace(
                    upload_staging_dir="/tmp/unused",
                    brand_completion_callback_url="",
                ),
                brands=FakeBrandStore(),
                brand_products=FakeBrandProductStore(),
                industries=FakeIndustryStore(),
                document_registry=FakeDocumentRegistryStore(),
                document_categories=types.SimpleNamespace(),
                upload_tasks=FakeUploadTaskStore(),
                queue=asyncio.Queue(),
                queued_task_ids=set(),
                queue_lock=asyncio.Lock(),
                ingest_text_document=None,
                ingest_from_url=None,
                ingest_staged_file=None,
                notify_failed_upload_files=_noop_async,
                notify_upload_failure=_noop_async,
                schedule_delayed_completion_check=lambda *_args, **_kwargs: None,
            )
        )

        request = BrandUploadRequest(
            brand_code="BRAND-001",
            brand_name="示例品牌",
            attachments=[
                BrandAttachment(
                    name="【示例品牌】品牌AI知识库_V3_20260715.md",
                    url="https://example.com/knowledge-v3.md",
                )
            ],
        )

        response = await application.enqueue_brand_upload_task(request)

        self.assertEqual("queued", response.status)
        self.assertEqual("brand_upload", application._deps.upload_tasks.created_task["task_type"])
        created_file = application._deps.upload_tasks.created_task["files"][0]
        self.assertEqual("attachment", created_file["file_role"])
        self.assertEqual("【示例品牌】品牌AI知识库_V3_20260715.md", created_file["original_filename"])

    async def test_documents_upload_routes_ai_knowledge_named_md_to_brand_ai_knowledge(self) -> None:
        class _FakeUploadFile:
            def __init__(self, *, filename: str, content: bytes) -> None:
                self.filename = filename
                self._content = content
                self._offset = 0

            async def seek(self, offset: int) -> None:
                self._offset = offset

            async def read(self, size: int = -1) -> bytes:
                if size < 0:
                    size = len(self._content) - self._offset
                start = self._offset
                end = min(len(self._content), start + size)
                self._offset = end
                return self._content[start:end]

        document_registry = FakeDocumentRegistryStore()
        application = UploadTaskApplicationService(
            UploadTaskApplicationDependencies(
                settings=types.SimpleNamespace(
                    upload_staging_dir="/tmp/unused",
                    brand_completion_callback_url="",
                ),
                brands=FakeBrandStore(),
                brand_products=FakeBrandProductStore(),
                industries=FakeIndustryStore(),
                document_registry=document_registry,
                document_categories=types.SimpleNamespace(),
                upload_tasks=FakeUploadTaskStore(),
                queue=asyncio.Queue(),
                queued_task_ids=set(),
                queue_lock=asyncio.Lock(),
                ingest_text_document=None,
                ingest_from_url=None,
                ingest_staged_file=None,
                notify_failed_upload_files=_noop_async,
                notify_upload_failure=_noop_async,
                schedule_delayed_completion_check=lambda *_args, **_kwargs: None,
            )
        )

        with patch("knowledge_base.upload_task.application.service.stage_upload_file", autospec=True) as mock_stage:
            mock_stage.side_effect = [
                (128, "hash-formal-kb"),
                (96, "hash-attachment"),
            ]
            response = await application.enqueue_upload_task(
                files=[
                    _FakeUploadFile(
                        filename="【示例品牌】品牌AI知识库_V3_20260715.md",
                        content="# 示例品牌\n\n正式知识库内容".encode("utf-8"),
                    ),
                    _FakeUploadFile(
                        filename="品牌手册.pdf",
                        content=b"pdf-bytes",
                    ),
                ],
                metadata={
                    "brand_code": "BRAND-001",
                    "brand_name": "示例品牌",
                    "category": "示例品牌",
                },
                chunk_size=None,
                chunk_overlap=None,
            )

        self.assertEqual("queued", response.status)
        self.assertEqual("document_upload", application._deps.upload_tasks.created_task["task_type"])
        self.assertEqual(
            ["brand_ai_knowledge", "attachment"],
            [item["file_role"] for item in application._deps.upload_tasks.created_task["files"]],
        )
        self.assertTrue(application._deps.upload_tasks.created_task["metadata"]["brand_callback_enabled"])
        self.assertTrue(application._deps.upload_tasks.created_task["metadata"]["backfill_brand_knowledge_json_empty_only"])
        self.assertEqual([], document_registry.last_reserved_files)

    async def test_documents_upload_force_attachment_overrides_ai_knowledge_filename(self) -> None:
        class _FakeUploadFile:
            def __init__(self, *, filename: str, content: bytes) -> None:
                self.filename = filename
                self._content = content
                self._offset = 0

            async def seek(self, offset: int) -> None:
                self._offset = offset

            async def read(self, size: int = -1) -> bytes:
                if size < 0:
                    size = len(self._content) - self._offset
                start = self._offset
                end = min(len(self._content), start + size)
                self._offset = end
                return self._content[start:end]

        application = UploadTaskApplicationService(
            UploadTaskApplicationDependencies(
                settings=types.SimpleNamespace(
                    upload_staging_dir="/tmp/unused",
                    brand_completion_callback_url="",
                ),
                brands=FakeBrandStore(),
                brand_products=FakeBrandProductStore(),
                industries=FakeIndustryStore(),
                document_registry=FakeDocumentRegistryStore(),
                document_categories=types.SimpleNamespace(),
                upload_tasks=FakeUploadTaskStore(),
                queue=asyncio.Queue(),
                queued_task_ids=set(),
                queue_lock=asyncio.Lock(),
                ingest_text_document=None,
                ingest_from_url=None,
                ingest_staged_file=None,
                notify_failed_upload_files=_noop_async,
                notify_upload_failure=_noop_async,
                schedule_delayed_completion_check=lambda *_args, **_kwargs: None,
            )
        )

        with patch("knowledge_base.upload_task.application.service.stage_upload_file", autospec=True) as mock_stage:
            mock_stage.return_value = (128, "hash-formal-kb-as-attachment")
            response = await application.enqueue_upload_task(
                files=[
                    _FakeUploadFile(
                        filename="【示例品牌】品牌AI知识库_V3_20260715.md",
                        content="# 示例品牌\n\n作为首次生成附件上传".encode("utf-8"),
                    ),
                ],
                metadata={
                    "brand_code": "BRAND-001",
                    "brand_name": "示例品牌",
                    "category": "示例品牌",
                    "force_attachment": True,
                },
                chunk_size=None,
                chunk_overlap=None,
            )

        self.assertEqual("queued", response.status)
        self.assertEqual(
            ["attachment"],
            [item["file_role"] for item in application._deps.upload_tasks.created_task["files"]],
        )
        self.assertNotIn("brand_callback_enabled", application._deps.upload_tasks.created_task["metadata"])

    async def test_documents_upload_rejects_missing_brand_metadata(self) -> None:
        class _FakeUploadFile:
            def __init__(self, *, filename: str, content: bytes) -> None:
                self.filename = filename
                self._content = content
                self._offset = 0

            async def seek(self, offset: int) -> None:
                self._offset = offset

            async def read(self, size: int = -1) -> bytes:
                if size < 0:
                    size = len(self._content) - self._offset
                start = self._offset
                end = min(len(self._content), start + size)
                self._offset = end
                return self._content[start:end]

        application = UploadTaskApplicationService(
            UploadTaskApplicationDependencies(
                settings=types.SimpleNamespace(
                    upload_staging_dir="/tmp/unused",
                    brand_completion_callback_url="",
                ),
                brands=FakeBrandStore(),
                brand_products=FakeBrandProductStore(),
                industries=FakeIndustryStore(),
                document_registry=FakeDocumentRegistryStore(),
                document_categories=types.SimpleNamespace(),
                upload_tasks=FakeUploadTaskStore(),
                queue=asyncio.Queue(),
                queued_task_ids=set(),
                queue_lock=asyncio.Lock(),
                ingest_text_document=None,
                ingest_from_url=None,
                ingest_staged_file=None,
                notify_failed_upload_files=_noop_async,
                notify_upload_failure=_noop_async,
                schedule_delayed_completion_check=lambda *_args, **_kwargs: None,
            )
        )

        with self.assertRaisesRegex(ValueError, "metadata 必须包含 category、brand_code、brand_name"):
            await application.enqueue_upload_task(
                files=[
                    _FakeUploadFile(
                        filename="品牌手册.pdf",
                        content=b"pdf-bytes",
                    )
                ],
                metadata={
                    "category": "示例品牌",
                },
                chunk_size=None,
                chunk_overlap=None,
            )

    async def test_brand_upload_without_attachments_completes_and_checks_immediately(self) -> None:
        scheduled_checks: list[tuple[str, int]] = []
        upload_tasks = FakeUploadTaskStore()
        queue: asyncio.Queue[str] = asyncio.Queue()

        application = UploadTaskApplicationService(
            UploadTaskApplicationDependencies(
                settings=types.SimpleNamespace(
                    upload_staging_dir="/tmp/unused",
                    brand_completion_callback_url="https://callback.example.com",
                ),
                brands=FakeBrandStore(),
                brand_products=FakeBrandProductStore(),
                industries=FakeIndustryStore(),
                document_registry=FakeDocumentRegistryStore(),
                document_categories=types.SimpleNamespace(),
                upload_tasks=upload_tasks,
                queue=queue,
                queued_task_ids=set(),
                queue_lock=asyncio.Lock(),
                ingest_text_document=None,
                ingest_from_url=None,
                ingest_staged_file=None,
                notify_failed_upload_files=_noop_async,
                notify_upload_failure=_noop_async,
                schedule_delayed_completion_check=lambda task_id, delay_seconds=600: scheduled_checks.append((task_id, delay_seconds)),
            )
        )

        request = BrandUploadRequest(
            brand_code="100113",
            brand_name="聚味瞿记",
            enterprise_subject="湖南聚味瞿记餐饮管理有限公司",
            intro="聚味瞿记是源自长沙的本土小龙虾餐饮连锁品牌。",
            attachments=[],
        )

        response = await application.enqueue_brand_upload_task(request)

        self.assertEqual(response.status, "completed")
        self.assertEqual(response.file_count, 0)
        self.assertEqual(queue.qsize(), 0)
        self.assertEqual(upload_tasks.updated_statuses, [(response.task_id, "completed")])
        self.assertEqual(scheduled_checks, [(response.task_id, 0)])

    async def test_brand_upload_with_attachment_enqueues_then_processes_successfully(self) -> None:
        scheduled_checks: list[tuple[str, int]] = []
        upload_tasks = FakeUploadTaskStore()
        queue: asyncio.Queue[str] = asyncio.Queue()
        attachment_assets = FakeAttachmentAssetStore()
        oss_client = FakeOSSClient()
        application = UploadTaskApplicationService(
            UploadTaskApplicationDependencies(
                settings=types.SimpleNamespace(
                    upload_staging_dir="/tmp/unused",
                    brand_completion_callback_url="https://callback.example.com",
                ),
                brands=FakeBrandStore(),
                brand_products=FakeBrandProductStore(),
                industries=FakeIndustryStore(),
                document_registry=FakeDocumentRegistryStore(),
                document_categories=types.SimpleNamespace(invalidate_latest_document_ids_cache=lambda *_args, **_kwargs: None),
                upload_tasks=upload_tasks,
                queue=queue,
                queued_task_ids=set(),
                queue_lock=asyncio.Lock(),
                ingest_text_document=None,
                ingest_from_url=None,
                ingest_staged_file=None,
                notify_failed_upload_files=_noop_async,
                notify_upload_failure=_noop_async,
                schedule_delayed_completion_check=lambda task_id, delay_seconds=600: scheduled_checks.append((task_id, delay_seconds)),
                attachment_assets=attachment_assets,
                oss_client=oss_client,
                parser=FakeParser(),
            )
        )

        request = BrandUploadRequest(
            brand_code="BRAND-001",
            brand_name="示例品牌",
            intro="示例品牌介绍",
            attachments=[
                BrandAttachment(
                    name="品牌手册.pdf",
                    url="https://example.com/brand-book.pdf",
                )
            ],
        )

        response = await application.enqueue_brand_upload_task(request)

        self.assertEqual("queued", response.status)
        self.assertEqual(1, response.file_count)
        self.assertEqual(1, queue.qsize())
        self.assertEqual(response.task_id, await queue.get())
        queue.task_done()

        async def _fake_download_remote_content_to_temp_file(*, url: str, name: str, log_context: str):
            self.assertEqual("https://example.com/brand-book.pdf", url)
            self.assertEqual("品牌手册.pdf", name)
            self.assertEqual("attachment_asset:BRAND-001", log_context)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(b"pdf-bytes")
                return (Path(tmp.name), "application/pdf", len(b"pdf-bytes"))

        with patch(
            "knowledge_base.upload_task.application.service.download_remote_content_to_temp_file",
            new=_fake_download_remote_content_to_temp_file,
        ):
            await application.process_upload_task(response.task_id)

        self.assertEqual(upload_tasks.created_task["status"], "completed")
        self.assertEqual(scheduled_checks, [(response.task_id, 0)])
        self.assertEqual(1, len(attachment_assets.created_assets))
        self.assertEqual(2, len(oss_client.uploaded))
        processed_file = upload_tasks.created_task["files"][0]
        self.assertEqual("success", processed_file["status"])
        self.assertEqual("attachment", processed_file["source_type"])
        self.assertEqual(1, processed_file["asset_id"])
        self.assertTrue(str(processed_file["oss_key"]).endswith("示例品牌/original/品牌手册.pdf/V1.pdf"))
        self.assertTrue(str(attachment_assets.created_assets[0]["fulltext_key"]).endswith("示例品牌/converted/品牌手册.pdf/V1.md"))
        self.assertEqual("https://example.com/brand-book.pdf", attachment_assets.created_assets[0]["source_url"])

    async def test_brand_upload_with_attachments_checks_after_files_complete(self) -> None:
        scheduled_checks: list[tuple[str, int]] = []
        upload_tasks = FakeUploadTaskStore()

        application = UploadTaskApplicationService(
            UploadTaskApplicationDependencies(
                settings=types.SimpleNamespace(
                    upload_staging_dir="/tmp/unused",
                    brand_completion_callback_url="https://callback.example.com",
                ),
                brands=FakeBrandStore(),
                brand_products=FakeBrandProductStore(),
                industries=FakeIndustryStore(),
                document_registry=FakeDocumentRegistryStore(),
                document_categories=types.SimpleNamespace(),
                upload_tasks=upload_tasks,
                queue=asyncio.Queue(),
                queued_task_ids=set(),
                queue_lock=asyncio.Lock(),
                ingest_text_document=None,
                ingest_from_url=None,
                ingest_staged_file=None,
                notify_failed_upload_files=_noop_async,
                notify_upload_failure=_noop_async,
                schedule_delayed_completion_check=lambda task_id, delay_seconds=600: scheduled_checks.append((task_id, delay_seconds)),
            )
        )
        upload_tasks.create_upload_task(
            task_id="task-with-files",
            task_type="brand_upload",
            metadata={"category": "示例品牌", "brand_callback_enabled": True},
            chunk_size=None,
            chunk_overlap=None,
            files=[
                {"file_index": 0, "original_filename": "品牌手册.pdf", "stored_path": "", "status": "success"},
                {"file_index": 1, "original_filename": "产品资料.pdf", "stored_path": "", "status": "success"},
            ],
        )

        await application.process_upload_task("task-with-files")

        self.assertEqual(upload_tasks.updated_statuses[-2:], [
            ("task-with-files", "processing"),
            ("task-with-files", "completed"),
        ])
        self.assertEqual(scheduled_checks, [("task-with-files", 0)])

    async def test_brand_upload_attachment_uses_asset_flow_when_brand_code_exists(self) -> None:
        scheduled_checks: list[tuple[str, int]] = []
        upload_tasks = FakeUploadTaskStore()
        upload_tasks.create_upload_task(
            task_id="task-attachment-assets",
            task_type="brand_upload",
            metadata={
                "category": "示例品牌",
                "brand_code": "BRAND-001",
                "_task_payload": {
                    "file_metadata_by_index": {
                        "0": {"source_url": "https://example.com/brand-book.pdf"},
                    }
                },
            },
            chunk_size=None,
            chunk_overlap=None,
            files=[
                {
                    "id": 0,
                    "file_index": 0,
                    "original_filename": "品牌手册.pdf",
                    "file_role": "attachment",
                    "stored_path": "",
                    "status": "pending",
                }
            ],
        )
        attachment_assets = FakeAttachmentAssetStore()
        oss_client = FakeOSSClient()
        application = UploadTaskApplicationService(
            UploadTaskApplicationDependencies(
                settings=types.SimpleNamespace(
                    upload_staging_dir="/tmp/unused",
                    brand_completion_callback_url="https://callback.example.com",
                ),
                brands=FakeBrandStore(),
                brand_products=FakeBrandProductStore(),
                industries=FakeIndustryStore(),
                document_registry=FakeDocumentRegistryStore(),
                document_categories=types.SimpleNamespace(invalidate_latest_document_ids_cache=lambda *_args, **_kwargs: None),
                upload_tasks=upload_tasks,
                queue=asyncio.Queue(),
                queued_task_ids=set(),
                queue_lock=asyncio.Lock(),
                ingest_text_document=None,
                ingest_from_url=None,
                ingest_staged_file=None,
                notify_failed_upload_files=_noop_async,
                notify_upload_failure=_noop_async,
                schedule_delayed_completion_check=lambda task_id, delay_seconds=600: scheduled_checks.append((task_id, delay_seconds)),
                attachment_assets=attachment_assets,
                oss_client=oss_client,
                parser=FakeParser(),
            )
        )

        async def _fake_download_remote_content_to_temp_file(*, url: str, name: str, log_context: str):
            self.assertEqual("https://example.com/brand-book.pdf", url)
            self.assertEqual("品牌手册.pdf", name)
            self.assertEqual("attachment_asset:BRAND-001", log_context)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(b"pdf-bytes")
                return (Path(tmp.name), "application/pdf", len(b"pdf-bytes"))

        with patch(
            "knowledge_base.upload_task.application.service.download_remote_content_to_temp_file",
            new=_fake_download_remote_content_to_temp_file,
        ):
            await application.process_upload_task("task-attachment-assets")

        self.assertEqual(upload_tasks.updated_statuses[-2:], [
            ("task-attachment-assets", "processing"),
            ("task-attachment-assets", "completed"),
        ])
        self.assertEqual(scheduled_checks, [("task-attachment-assets", 0)])
        self.assertEqual(1, len(attachment_assets.created_assets))
        self.assertEqual(2, len(oss_client.uploaded))
        self.assertTrue(str(oss_client.uploaded[0][1]).endswith("示例品牌/original/品牌手册.pdf/V1.pdf"))
        self.assertTrue(str(oss_client.uploaded[1][1]).endswith("示例品牌/converted/品牌手册.pdf/V1.md"))
        processed_file = upload_tasks.created_task["files"][0]
        self.assertEqual("success", processed_file["status"])
        self.assertEqual("attachment", processed_file["source_type"])
        self.assertEqual(1, processed_file["asset_id"])
        self.assertTrue(str(processed_file["oss_key"]).endswith("示例品牌/original/品牌手册.pdf/V1.pdf"))
        self.assertTrue(str(processed_file["oss_url"]).endswith("/示例品牌/original/品牌手册.pdf/V1.pdf"))
        self.assertEqual(1, attachment_assets.created_assets[0]["converted_version"])
        self.assertTrue(str(attachment_assets.created_assets[0]["fulltext_key"]).endswith("示例品牌/converted/品牌手册.pdf/V1.md"))

    async def test_brand_upload_image_attachment_writes_asset_and_vector(self) -> None:
        upload_tasks = FakeUploadTaskStore()
        upload_tasks.create_upload_task(
            task_id="task-image-attachment",
            task_type="brand_upload",
            metadata={
                "category": "示例品牌",
                "brand_code": "BRAND-001",
                "_task_payload": {
                    "file_metadata_by_index": {
                        "0": {"source_url": "https://example.com/kitchen.png"},
                    }
                },
            },
            chunk_size=None,
            chunk_overlap=None,
            files=[
                {
                    "id": 0,
                    "file_index": 0,
                    "original_filename": "厨房场景图.png",
                    "file_role": "attachment",
                    "stored_path": "",
                    "status": "pending",
                }
            ],
        )
        attachment_assets = FakeAttachmentAssetStore()
        document_categories = FakeDocumentCategoryStore()
        embeddings = FakeEmbeddings()
        vector_store = FakeVectorStore()
        oss_client = FakeOSSClient()
        application = UploadTaskApplicationService(
            UploadTaskApplicationDependencies(
                settings=types.SimpleNamespace(
                    upload_staging_dir="/tmp/unused",
                    brand_completion_callback_url="",
                    image_tagging_model="qwen-vl-max-latest",
                    image_tagging_max_tags=8,
                ),
                brands=FakeBrandStore(),
                brand_products=FakeBrandProductStore(),
                industries=FakeIndustryStore(),
                document_registry=FakeDocumentRegistryStore(),
                document_categories=document_categories,
                upload_tasks=upload_tasks,
                queue=asyncio.Queue(),
                queued_task_ids=set(),
                queue_lock=asyncio.Lock(),
                ingest_text_document=None,
                ingest_from_url=None,
                ingest_staged_file=None,
                notify_failed_upload_files=_noop_async,
                notify_upload_failure=_noop_async,
                schedule_delayed_completion_check=lambda *_args, **_kwargs: None,
                attachment_assets=attachment_assets,
                oss_client=oss_client,
                parser=FakeParser(),
                embeddings=embeddings,
                store=vector_store,
            )
        )

        async def _fake_download_remote_content_to_temp_file(*, url: str, name: str, log_context: str):
            self.assertEqual("https://example.com/kitchen.png", url)
            self.assertEqual("厨房场景图.png", name)
            self.assertEqual("attachment_asset:BRAND-001", log_context)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                tmp.write(b"png-bytes")
                return (Path(tmp.name), "image/png", len(b"png-bytes"))

        with (
            patch(
                "knowledge_base.upload_task.application.service.download_remote_content_to_temp_file",
                new=_fake_download_remote_content_to_temp_file,
            ),
            patch.object(
                UploadTaskApplicationService,
                "_prepare_image_tagging_path",
                new=lambda _self, original_path: (original_path, False),
            ),
            patch(
                "knowledge_base.upload_task.application.service.describe_image",
                new=_async_return({"summary": "现代厨房橱柜场景图", "tags": ["厨房", "橱柜", "家居场景"]}),
            ),
        ):
            await application.process_upload_task("task-image-attachment")

        processed_file = upload_tasks.created_task["files"][0]
        self.assertEqual("success", processed_file["status"])
        self.assertEqual("image", processed_file["source_type"])
        self.assertEqual("image/png", processed_file["content_type"])
        self.assertEqual(1, processed_file["asset_id"])
        self.assertEqual("asset_1", processed_file["document_id"])
        self.assertEqual(1, len(attachment_assets.created_assets))
        self.assertEqual("image", attachment_assets.created_assets[0]["asset_kind"])
        self.assertEqual("现代厨房橱柜场景图", attachment_assets.created_assets[0]["image_summary"])
        self.assertEqual('["厨房", "橱柜", "家居场景"]', attachment_assets.created_assets[0]["image_tags_json"])
        self.assertEqual(1, len(vector_store.inserted_rows))
        self.assertEqual("asset_1", vector_store.inserted_rows[0]["document_id"])
        self.assertIn("图片标签: 厨房、橱柜、家居场景", vector_store.inserted_rows[0]["chunk_payloads"][0]["text"])
        self.assertEqual([("asset_1", "示例品牌", None)], document_categories.added)
        self.assertEqual(1, len(embeddings.inputs))
        self.assertIn("现代厨房橱柜场景图", embeddings.inputs[0][0])
        self.assertEqual(1, len(oss_client.uploaded))
        self.assertEqual("image/png", oss_client.uploaded[0][2])

    async def test_brand_upload_image_attachment_uploads_compressed_image_to_oss_when_prepared(self) -> None:
        upload_tasks = FakeUploadTaskStore()
        upload_tasks.create_upload_task(
            task_id="task-image-attachment-compressed",
            task_type="brand_upload",
            metadata={
                "category": "示例品牌",
                "brand_code": "BRAND-001",
                "_task_payload": {
                    "file_metadata_by_index": {
                        "0": {"source_url": "https://example.com/kitchen.png"},
                    }
                },
            },
            chunk_size=None,
            chunk_overlap=None,
            files=[
                {
                    "id": 0,
                    "file_index": 0,
                    "original_filename": "厨房场景图.png",
                    "file_role": "attachment",
                    "stored_path": "",
                    "status": "pending",
                }
            ],
        )
        attachment_assets = FakeAttachmentAssetStore()
        document_categories = FakeDocumentCategoryStore()
        embeddings = FakeEmbeddings()
        vector_store = FakeVectorStore()
        oss_client = FakeOSSClient()
        application = UploadTaskApplicationService(
            UploadTaskApplicationDependencies(
                settings=types.SimpleNamespace(
                    upload_staging_dir="/tmp/unused",
                    brand_completion_callback_url="",
                    image_tagging_model="qwen-vl-max-latest",
                    image_tagging_max_tags=8,
                ),
                brands=FakeBrandStore(),
                brand_products=FakeBrandProductStore(),
                industries=FakeIndustryStore(),
                document_registry=FakeDocumentRegistryStore(),
                document_categories=document_categories,
                upload_tasks=upload_tasks,
                queue=asyncio.Queue(),
                queued_task_ids=set(),
                queue_lock=asyncio.Lock(),
                ingest_text_document=None,
                ingest_from_url=None,
                ingest_staged_file=None,
                notify_failed_upload_files=_noop_async,
                notify_upload_failure=_noop_async,
                schedule_delayed_completion_check=lambda *_args, **_kwargs: None,
                attachment_assets=attachment_assets,
                oss_client=oss_client,
                parser=FakeParser(),
                embeddings=embeddings,
                store=vector_store,
            )
        )

        compressed_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        compressed_path = Path(compressed_file.name)
        compressed_bytes = b"compressed-jpeg-bytes"
        compressed_file.write(compressed_bytes)
        compressed_file.close()

        async def _fake_download_remote_content_to_temp_file(*, url: str, name: str, log_context: str):
            self.assertEqual("https://example.com/kitchen.png", url)
            self.assertEqual("厨房场景图.png", name)
            self.assertEqual("attachment_asset:BRAND-001", log_context)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                tmp.write(b"png-bytes")
                return (Path(tmp.name), "image/png", len(b"png-bytes"))

        with (
            patch(
                "knowledge_base.upload_task.application.service.download_remote_content_to_temp_file",
                new=_fake_download_remote_content_to_temp_file,
            ),
            patch.object(
                UploadTaskApplicationService,
                "_prepare_image_tagging_path",
                new=lambda _self, _original_path: (compressed_path, True),
            ),
            patch(
                "knowledge_base.upload_task.application.service.describe_image",
                new=_async_return({"summary": "现代厨房橱柜场景图", "tags": ["厨房", "橱柜", "家居场景"]}),
            ),
        ):
            await application.process_upload_task("task-image-attachment-compressed")

        processed_file = upload_tasks.created_task["files"][0]
        self.assertEqual("success", processed_file["status"])
        self.assertEqual("image/jpeg", processed_file["content_type"])
        self.assertEqual(len(compressed_bytes), processed_file["file_size"])
        self.assertEqual(1, len(attachment_assets.created_assets))
        self.assertEqual("image/jpeg", attachment_assets.created_assets[0]["content_type"])
        self.assertEqual(len(compressed_bytes), attachment_assets.created_assets[0]["file_size"])
        self.assertEqual(1, len(oss_client.uploaded))
        self.assertEqual(str(compressed_path), oss_client.uploaded[0][0])
        self.assertEqual("image/jpeg", oss_client.uploaded[0][2])
        self.assertTrue(str(oss_client.uploaded[0][1]).endswith("示例品牌/original/厨房场景图.jpg/V1.jpg"))
        self.assertFalse(compressed_path.exists())

    async def test_brand_upload_image_attachment_fails_when_tags_empty(self) -> None:
        upload_tasks = FakeUploadTaskStore()
        upload_tasks.create_upload_task(
            task_id="task-image-empty-tags",
            task_type="brand_upload",
            metadata={
                "category": "示例品牌",
                "brand_code": "BRAND-001",
                "_task_payload": {
                    "file_metadata_by_index": {
                        "0": {"source_url": "https://example.com/kitchen.png"},
                    }
                },
            },
            chunk_size=None,
            chunk_overlap=None,
            files=[
                {
                    "id": 0,
                    "file_index": 0,
                    "original_filename": "厨房场景图.png",
                    "file_role": "attachment",
                    "stored_path": "",
                    "status": "pending",
                }
            ],
        )
        attachment_assets = FakeAttachmentAssetStore()
        application = UploadTaskApplicationService(
            UploadTaskApplicationDependencies(
                settings=types.SimpleNamespace(
                    upload_staging_dir="/tmp/unused",
                    brand_completion_callback_url="",
                    image_tagging_model="qwen-vl-max-latest",
                    image_tagging_max_tags=8,
                ),
                brands=FakeBrandStore(),
                brand_products=FakeBrandProductStore(),
                industries=FakeIndustryStore(),
                document_registry=FakeDocumentRegistryStore(),
                document_categories=FakeDocumentCategoryStore(),
                upload_tasks=upload_tasks,
                queue=asyncio.Queue(),
                queued_task_ids=set(),
                queue_lock=asyncio.Lock(),
                ingest_text_document=None,
                ingest_from_url=None,
                ingest_staged_file=None,
                notify_failed_upload_files=_noop_async,
                notify_upload_failure=_noop_async,
                schedule_delayed_completion_check=lambda *_args, **_kwargs: None,
                attachment_assets=attachment_assets,
                oss_client=FakeOSSClient(),
                embeddings=FakeEmbeddings(),
                store=FakeVectorStore(),
            )
        )

        async def _fake_download_remote_content_to_temp_file(*, url: str, name: str, log_context: str):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                tmp.write(b"png-bytes")
                return (Path(tmp.name), "image/png", len(b"png-bytes"))

        with (
            patch(
                "knowledge_base.upload_task.application.service.download_remote_content_to_temp_file",
                new=_fake_download_remote_content_to_temp_file,
            ),
            patch.object(
                UploadTaskApplicationService,
                "_prepare_image_tagging_path",
                new=lambda _self, original_path: (original_path, False),
            ),
            patch(
                "knowledge_base.upload_task.application.service.describe_image",
                new=_async_return({"summary": "现代厨房橱柜场景图", "tags": []}),
            ),
        ):
            await application.process_upload_task("task-image-empty-tags")

        processed_file = upload_tasks.created_task["files"][0]
        self.assertEqual("failed", processed_file["status"])
        self.assertIn("图片标签为空", processed_file["error_message"])
        self.assertEqual([], attachment_assets.created_assets)
        self.assertEqual("completed_with_errors", upload_tasks.created_task["status"])

    async def test_brand_upload_image_attachment_rolls_back_asset_when_milvus_write_fails(self) -> None:
        upload_tasks = FakeUploadTaskStore()
        upload_tasks.create_upload_task(
            task_id="task-image-milvus-fail",
            task_type="brand_upload",
            metadata={
                "category": "示例品牌",
                "brand_code": "BRAND-001",
                "_task_payload": {
                    "file_metadata_by_index": {
                        "0": {"source_url": "https://example.com/kitchen.png"},
                    }
                },
            },
            chunk_size=None,
            chunk_overlap=None,
            files=[
                {
                    "id": 0,
                    "file_index": 0,
                    "original_filename": "厨房场景图.png",
                    "file_role": "attachment",
                    "stored_path": "",
                    "status": "pending",
                }
            ],
        )
        attachment_assets = FakeAttachmentAssetStore()
        document_categories = FakeDocumentCategoryStore()
        vector_store = FakeVectorStore()
        vector_store.fail_on_insert = True
        oss_client = FakeOSSClient()
        application = UploadTaskApplicationService(
            UploadTaskApplicationDependencies(
                settings=types.SimpleNamespace(
                    upload_staging_dir="/tmp/unused",
                    brand_completion_callback_url="",
                    image_tagging_model="qwen-vl-max-latest",
                    image_tagging_max_tags=8,
                ),
                brands=FakeBrandStore(),
                brand_products=FakeBrandProductStore(),
                industries=FakeIndustryStore(),
                document_registry=FakeDocumentRegistryStore(),
                document_categories=document_categories,
                upload_tasks=upload_tasks,
                queue=asyncio.Queue(),
                queued_task_ids=set(),
                queue_lock=asyncio.Lock(),
                ingest_text_document=None,
                ingest_from_url=None,
                ingest_staged_file=None,
                notify_failed_upload_files=_noop_async,
                notify_upload_failure=_noop_async,
                schedule_delayed_completion_check=lambda *_args, **_kwargs: None,
                attachment_assets=attachment_assets,
                oss_client=oss_client,
                embeddings=FakeEmbeddings(),
                store=vector_store,
            )
        )

        async def _fake_download_remote_content_to_temp_file(*, url: str, name: str, log_context: str):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                tmp.write(b"png-bytes")
                return (Path(tmp.name), "image/png", len(b"png-bytes"))

        with (
            patch(
                "knowledge_base.upload_task.application.service.download_remote_content_to_temp_file",
                new=_fake_download_remote_content_to_temp_file,
            ),
            patch.object(
                UploadTaskApplicationService,
                "_prepare_image_tagging_path",
                new=lambda _self, original_path: (original_path, False),
            ),
            patch(
                "knowledge_base.upload_task.application.service.describe_image",
                new=_async_return({"summary": "现代厨房橱柜场景图", "tags": ["厨房", "橱柜"]}),
            ),
        ):
            await application.process_upload_task("task-image-milvus-fail")

        processed_file = upload_tasks.created_task["files"][0]
        self.assertEqual("failed", processed_file["status"])
        self.assertIn("milvus write failed", processed_file["error_message"])
        self.assertEqual([1], attachment_assets.deleted_asset_ids)
        self.assertEqual(1, len(oss_client.deleted))
        self.assertEqual([], document_categories.added)
        self.assertEqual("completed_with_errors", upload_tasks.created_task["status"])

    async def test_brand_ai_knowledge_file_routes_to_ingestion_service(self) -> None:
        upload_tasks = FakeUploadTaskStore()
        upload_tasks.create_upload_task(
            task_id="task-ai-knowledge",
            task_type="brand_ai_knowledge_upload",
            metadata={
                "category": "示例品牌",
                "brand_code": "BRAND-001",
                "force_reingest": True,
                "_task_payload": {
                    "file_metadata_by_index": {
                        "0": {"source_url": "https://example.com/kb.md"},
                    }
                },
            },
            chunk_size=None,
            chunk_overlap=None,
            files=[
                {
                    "id": 0,
                    "file_index": 0,
                    "original_filename": "【示例品牌】品牌AI知识库_V3_20260715.md",
                    "file_role": "brand_ai_knowledge",
                    "stored_path": "",
                    "status": "pending",
                }
            ],
        )
        ingestion_service = FakeBrandAiKnowledgeIngestionService()
        application = UploadTaskApplicationService(
            UploadTaskApplicationDependencies(
                settings=types.SimpleNamespace(
                    upload_staging_dir="/tmp/unused",
                    brand_completion_callback_url="https://callback.example.com",
                ),
                brands=FakeBrandStore(),
                brand_products=FakeBrandProductStore(),
                industries=FakeIndustryStore(),
                document_registry=FakeDocumentRegistryStore(),
                document_categories=types.SimpleNamespace(invalidate_latest_document_ids_cache=lambda *_args, **_kwargs: None),
                upload_tasks=upload_tasks,
                queue=asyncio.Queue(),
                queued_task_ids=set(),
                queue_lock=asyncio.Lock(),
                ingest_text_document=None,
                ingest_from_url=None,
                ingest_staged_file=None,
                notify_failed_upload_files=_noop_async,
                notify_upload_failure=_noop_async,
                schedule_delayed_completion_check=lambda *_args, **_kwargs: None,
                brand_ai_knowledge_ingestion=ingestion_service,
            )
        )

        await application.process_upload_task("task-ai-knowledge")

        self.assertEqual(1, len(ingestion_service.calls))
        self.assertTrue(ingestion_service.calls[0]["force_reingest"])
        self.assertTrue(ingestion_service.calls[0]["backfill_brand_knowledge_json_empty_only"])
        processed_file = upload_tasks.created_task["files"][0]
        self.assertEqual("success", processed_file["status"])
        self.assertEqual("brand_ai_knowledge", processed_file["source_type"])
        self.assertEqual(101, processed_file["full_knowledge_file_id"])
        self.assertEqual("https://oss.example.com/BRAND-001/ai_knowledge/【示例品牌】品牌AI知识库_V3_20260715.md", processed_file["oss_url"])

    def test_get_upload_task_status_exposes_attachment_asset_fields(self) -> None:
        upload_tasks = FakeUploadTaskStore()
        session_store = FakeBrandKnowledgeSessionStore()
        session_store.sessions_by_task[("task-attachment-status", "attachment_conflict")] = {
            "session_id": "bks_task_attachment_status",
            "status": "waiting_user_input",
        }
        upload_tasks.create_upload_task(
            task_id="task-attachment-status",
            task_type="brand_upload",
            metadata={"brand_name": "示例品牌", "brand_code": "BRAND-001"},
            chunk_size=None,
            chunk_overlap=None,
            files=[
                {
                    "id": 1,
                    "file_index": 0,
                    "original_filename": "品牌手册.pdf",
                    "file_role": "attachment",
                    "stored_path": "",
                    "status": "success",
                    "source_type": "attachment",
                    "file_size": 128,
                    "file_hash": "hash-attachment",
                    "content_type": "application/pdf",
                    "oss_key": "BRAND-001/attachments/hash-attachment/品牌手册.pdf",
                    "oss_url": "https://oss.example.com/BRAND-001/attachments/hash-attachment/品牌手册.pdf",
                    "asset_id": 11,
                }
            ],
        )
        application = UploadTaskApplicationService(
            UploadTaskApplicationDependencies(
                settings=types.SimpleNamespace(upload_staging_dir="/tmp/unused", brand_completion_callback_url=""),
                brands=FakeBrandStore(),
                brand_products=FakeBrandProductStore(),
                industries=FakeIndustryStore(),
                document_registry=FakeDocumentRegistryStore(),
                document_categories=types.SimpleNamespace(),
                upload_tasks=upload_tasks,
                queue=asyncio.Queue(),
                queued_task_ids=set(),
                queue_lock=asyncio.Lock(),
                ingest_text_document=None,
                ingest_from_url=None,
                ingest_staged_file=None,
                notify_failed_upload_files=_noop_async,
                notify_upload_failure=_noop_async,
                schedule_delayed_completion_check=lambda *_args, **_kwargs: None,
                brand_knowledge_sessions=session_store,
            )
        )

        result = application.get_upload_task_status("task-attachment-status")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual("BRAND-001", result["brand_code"])
        self.assertEqual("示例品牌", result["brand_name"])
        self.assertEqual("brand_upload", result["task_type"])
        self.assertEqual("bks_task_attachment_status", result["knowledge_session_id"])
        self.assertEqual("waiting_user_input", result["knowledge_session_status"])
        self.assertEqual("attachment", result["files"][0]["file_role"])
        self.assertEqual(11, result["files"][0]["asset_id"])
        self.assertEqual("https://oss.example.com/BRAND-001/attachments/hash-attachment/品牌手册.pdf", result["files"][0]["oss_url"])

    def test_get_upload_task_status_exposes_brand_ai_knowledge_progress_fields(self) -> None:
        upload_tasks = FakeUploadTaskStore()
        upload_tasks.create_upload_task(
            task_id="task-ai-kb-status",
            task_type="brand_ai_knowledge_upload",
            metadata={"brand_name": "示例品牌", "brand_code": "BRAND-001"},
            chunk_size=None,
            chunk_overlap=None,
            files=[
                {
                    "id": 7,
                    "file_index": 0,
                    "original_filename": "【示例品牌】品牌AI知识库_V3_20260715.md",
                    "file_role": "brand_ai_knowledge",
                    "stored_path": "",
                    "status": "processing",
                    "source_type": "brand_ai_knowledge",
                    "document_id": "brandkb:BRAND-001:V3:20260715:R1",
                    "full_knowledge_file_id": 101,
                    "oss_url": "https://oss.example.com/BRAND-001/ai_knowledge/【示例品牌】品牌AI知识库_V3_20260715.md",
                }
            ],
        )
        full_knowledge_store = FakeBrandFullKnowledgeStatusStore()
        full_knowledge_store.rows_by_id[101] = {
            "id": 101,
            "brand_code": "BRAND-001",
            "brand_name": "示例品牌",
            "oss_url": "https://oss.example.com/BRAND-001/ai_knowledge/full/latest.md",
            "pdf_oss_url": "https://oss.example.com/BRAND-001/ai_knowledge/full/latest.pdf",
            "ingest_status": "processing",
            "milvus_status": "processing",
            "facts_status": "pending",
            "is_latest": 0,
            "error_message": None,
        }
        ingestion_jobs = FakeBrandKnowledgeIngestionJobStore()
        ingestion_jobs.jobs_by_id["brand-ai-kb:task-ai-kb-status:7"] = {
            "job_id": "brand-ai-kb:task-ai-kb-status:7",
            "brand_code": "BRAND-001",
            "brand_name": "示例品牌",
            "status": "processing",
            "current_step": "write_milvus",
            "parse_status": "success",
            "pdf_status": "success",
            "mysql_status": "success",
            "milvus_status": "processing",
            "facts_status": "pending",
            "cleanup_status": "pending",
        }
        application = UploadTaskApplicationService(
            UploadTaskApplicationDependencies(
                settings=types.SimpleNamespace(upload_staging_dir="/tmp/unused", brand_completion_callback_url=""),
                brands=FakeBrandStore(),
                brand_products=FakeBrandProductStore(),
                industries=FakeIndustryStore(),
                document_registry=FakeDocumentRegistryStore(),
                document_categories=types.SimpleNamespace(),
                upload_tasks=upload_tasks,
                queue=asyncio.Queue(),
                queued_task_ids=set(),
                queue_lock=asyncio.Lock(),
                ingest_text_document=None,
                ingest_from_url=None,
                ingest_staged_file=None,
                notify_failed_upload_files=_noop_async,
                notify_upload_failure=_noop_async,
                schedule_delayed_completion_check=lambda *_args, **_kwargs: None,
                brand_full_knowledge=full_knowledge_store,
                brand_knowledge_ingestion_jobs=ingestion_jobs,
            )
        )

        result = application.get_upload_task_status("task-ai-kb-status")

        self.assertIsNotNone(result)
        assert result is not None
        file_result = result["files"][0]
        self.assertEqual("brand_ai_knowledge", file_result["file_role"])
        self.assertEqual(101, file_result["full_knowledge_file_id"])
        self.assertEqual("write_milvus", file_result["current_step"])
        self.assertEqual("processing", file_result["ingest_status"])
        self.assertEqual("processing", file_result["milvus_status"])
        self.assertEqual("pending", file_result["facts_status"])
        self.assertEqual("https://oss.example.com/BRAND-001/ai_knowledge/full/latest.md", file_result["knowledge_markdown_oss_url"])
        self.assertEqual("https://oss.example.com/BRAND-001/ai_knowledge/full/latest.pdf", file_result["knowledge_pdf_oss_url"])


async def _noop_async(*args, **kwargs):
    return None


def _async_return(value):
    async def _runner(*args, **kwargs):
        return value

    return _runner


if __name__ == "__main__":
    unittest.main()
