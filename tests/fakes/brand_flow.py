from __future__ import annotations

import json
import sys
import types
from dataclasses import dataclass
from datetime import datetime
from unittest.mock import AsyncMock

from tests._stub_utils import ensure_stub_module, module_available

def _install_service_import_stubs() -> None:
    pydantic_stub = ensure_stub_module("pydantic")
    if pydantic_stub is not None:

        class BaseModel:
            def __init__(self, **kwargs):
                fields_set = set(kwargs.keys())
                for name, value in self.__class__.__dict__.items():
                    if name.startswith("_") or callable(value):
                        continue
                    setattr(self, name, value)
                for key, value in kwargs.items():
                    setattr(self, key, value)
                self.model_fields_set = fields_set
                self.__fields_set__ = fields_set

            def model_copy(self, *, update=None):
                data = {
                    key: value
                    for key, value in self.__dict__.items()
                    if key not in {"model_fields_set", "__fields_set__"}
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

        class _Generation:
            @staticmethod
            def call(*args, **kwargs):
                raise RuntimeError("Generation.call should be stubbed in tests")

        class _MultiModalConversation:
            @staticmethod
            def call(*args, **kwargs):
                raise RuntimeError("MultiModalConversation.call should be stubbed in tests")

        class _MultiModalEmbedding:
            @staticmethod
            def call(*args, **kwargs):
                raise RuntimeError("MultiModalEmbedding.call should be stubbed in tests")

        dashscope_stub.Generation = _Generation
        dashscope_stub.MultiModalConversation = _MultiModalConversation
        dashscope_stub.MultiModalEmbedding = _MultiModalEmbedding
        sys.modules.setdefault("dashscope", dashscope_stub)

    fastapi_stub = ensure_stub_module("fastapi")
    if fastapi_stub is not None:
        fastapi_stub.UploadFile = type("UploadFile", (), {})
        sys.modules.setdefault("fastapi", fastapi_stub)

    pypinyin_stub = None if "pypinyin" in sys.modules else ensure_stub_module("pypinyin")
    if pypinyin_stub is not None:

        class _Style:
            FIRST_LETTER = "FIRST_LETTER"

        char_map = {
            "示": "s",
            "例": "l",
            "品": "p",
            "牌": "p",
            "金": "j",
            "家": "j",
            "居": "j",
            "溪": "x",
            "谷": "g",
            "留": "l",
            "香": "x",
        }

        def lazy_pinyin(value, style=None, errors=None):
            tokens = []
            for ch in value:
                if ch in char_map:
                    tokens.append(char_map[ch])
                elif ch.isascii() and ch.isalnum():
                    tokens.append(ch)
                elif errors is not None:
                    tokens.extend(errors(ch))
            return tokens

        pypinyin_stub.Style = _Style
        pypinyin_stub.lazy_pinyin = lazy_pinyin
        sys.modules.setdefault("pypinyin", pypinyin_stub)

    module_stubs: dict[str, dict[str, object]] = {
        "knowledge_base.stores.brand_store": {"BrandStore": type("BrandStore", (), {})},
        "knowledge_base.stores.brand_product_store": {"BrandProductStore": type("BrandProductStore", (), {})},
        "knowledge_base.stores.brand_knowledge_store": {"BrandKnowledgeStore": type("BrandKnowledgeStore", (), {})},
        "knowledge_base.stores.industry_store": {"IndustryStore": type("IndustryStore", (), {})},
        "knowledge_base.stores.document_alert_store": {"DocumentAlertStore": type("DocumentAlertStore", (), {})},
        "knowledge_base.stores.document_fact_relation_store": {
            "DocumentFactRelationStore": type("DocumentFactRelationStore", (), {})
        },
        "knowledge_base.stores.document_registry_store": {
            "DocumentRegistryStore": type("DocumentRegistryStore", (), {})
        },
        "knowledge_base.stores.document_category_store": {
            "DocumentCategoryStore": type("DocumentCategoryStore", (), {})
        },
        "knowledge_base.infrastructure.embedding": {"EmbeddingService": type("EmbeddingService", (), {})},
        "knowledge_base.infrastructure.milvus_store": {"MilvusVectorStore": type("MilvusVectorStore", (), {})},
        "knowledge_base.infrastructure.oss_client": {"OSSClient": type("OSSClient", (), {})},
        "knowledge_base.stores.upload_task_store": {
            "UploadTaskStore": type("UploadTaskStore", (), {})
        },
    }

    if not module_available("httpx"):
        module_stubs["httpx"] = {
            "ConnectError": type("ConnectError", (Exception,), {}),
            "TimeoutException": type("TimeoutException", (Exception,), {}),
            "RemoteProtocolError": type("RemoteProtocolError", (Exception,), {}),
            "AsyncClient": type("AsyncClient", (), {}),
        }
    if not module_available("xlrd"):
        module_stubs["xlrd"] = {
            "open_workbook": lambda *args, **kwargs: None,
        }
    if not module_available("markitdown"):
        module_stubs["markitdown"] = {
            "MarkItDown": type("MarkItDown", (), {}),
        }
    if not module_available("openpyxl"):
        module_stubs["openpyxl"] = {
            "load_workbook": lambda *args, **kwargs: None,
        }
    if not module_available("pymysql"):
        module_stubs["pymysql"] = {}

    for module_name, attrs in module_stubs.items():
        if module_name in sys.modules:
            continue
        stub = types.ModuleType(module_name)
        for attr_name, value in attrs.items():
            setattr(stub, attr_name, value)
        sys.modules[module_name] = stub


_install_service_import_stubs()

from knowledge_base.brand.application import BrandApplicationDependencies, BrandApplicationService
from knowledge_base.search.application.service import SearchApplicationDependencies, SearchApplicationService


def _fake_runtime():
    return types.SimpleNamespace(
        inflight_brand_callbacks=set(),
        queued_brand_callback_task_ids=set(),
        scheduled_brand_callback_retries=set(),
        scheduled_brand_completion_checks=set(),
        scheduled_attachment_confirm_callback_retries=set(),
    )


def _fake_spawn_background_task(coro):
    try:
        coro.close()
    except Exception:
        pass
    return None


class FakeUploadFile:
    def __init__(self, filename: str, content: str) -> None:
        self.filename = filename
        self._data = content.encode("utf-8")
        self._pos = 0

    async def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = len(self._data) - self._pos
        start = self._pos
        end = min(len(self._data), self._pos + size)
        self._pos = end
        return self._data[start:end]

    async def seek(self, offset: int) -> None:
        self._pos = max(0, offset)


def _build_brand_application() -> BrandApplicationService:
    return BrandApplicationService(
        BrandApplicationDependencies(
            settings=FakeSettings(),
            brands=FakeBrandStore(),
            brand_products=FakeBrandProductStore(),
            brand_knowledge=FakeBrandKnowledgeStore(),
            industries=FakeIndustryStore(),
            brand_knowledge_sessions=types.SimpleNamespace(),
            document_registry=FakeDocumentRegistryStore(),
            document_categories=FakeDocumentCategoryStore(),
            fact_relations=None,
            store=None,
            document_app=None,
            delete_document=None,
            get_full_text=lambda _document_id: None,
            ingest_staged_file=AsyncMock(),
            parser=types.SimpleNamespace(
                parse_path=lambda *args, **kwargs: types.SimpleNamespace(
                    markdown_text="示例 Markdown",
                    text="示例 Markdown",
                    source_type="docx",
                )
            ),
        )
    )


def _build_search_application() -> SearchApplicationService:
    return SearchApplicationService(
        SearchApplicationDependencies(
            settings=types.SimpleNamespace(milvus_filter_batch_size=200),
            store=types.SimpleNamespace(search=lambda **kwargs: []),
            embeddings=types.SimpleNamespace(embed_query=lambda _query: [0.1]),
            brands=FakeBrandStore(),
            brand_app=_build_brand_application(),
            document_app=types.SimpleNamespace(build_search_hits=lambda results: results),
            document_categories=FakeDocumentCategoryStore(),
        )
    )


class FakeBrandStore:
    def __init__(self, *, knowledge_revision: str = "demo-2026-06-23") -> None:
        self.callback_row = None
        self.last_upsert_brand_kwargs = None
        self.rename_calls: list[dict[str, object]] = []
        self.rename_job_calls: list[dict[str, object]] = []
        self.rename_errors: list[Exception] = []
        self.rename_result: dict[str, object] | None = None
        self.knowledge_revision = knowledge_revision
        self.deleted_brand_ids: list[int] = []
        self._brand_row = {
            "id": 1,
            "brand_code": "BRAND-001",
            "brand_name": "示例品牌",
            "brand_alias": None,
            "brand_logo": None,
            "website": "[\"https://example.com\"]",
            "customer_service_hotline": "[\"400-000-0000\"]",
            "official_wechat_account": "example_wechat",
            "email": None,
            "brand_enterprise_entity": "示例企业主体",
            "business_license_image_path": "https://example.com/license.png",
            "english_name": "Demo Brand",
            "industry": "消费品",
            "industry_id": 1,
            "knowledge_revision": self.knowledge_revision,
            "positioning": "[\"高端定位\"]",
            "advantages": "[\"渠道优势\"]",
            "mission": "[\"服务用户\"]",
            "vision": "[\"成为第一\"]",
            "intro": "品牌简介",
            "target_regions_json": "[\"中国\", \"新加坡\"]",
            "other_info": None,
        }

    def get_brand_by_name(self, brand_name: str):
        if brand_name != self._brand_row["brand_name"]:
            return None
        row = dict(self._brand_row)
        row["knowledge_revision"] = self.knowledge_revision
        return row

    def get_brand_by_code(self, brand_code: str):
        if brand_code != "BRAND-001":
            return None
        row = dict(self._brand_row)
        row["knowledge_revision"] = self.knowledge_revision
        return row

    def get_brand_by_id(self, brand_id: int):
        if brand_id != 1:
            return None
        row = dict(self._brand_row)
        row["knowledge_revision"] = self.knowledge_revision
        return row

    def upsert_brand(self, **kwargs):
        self.last_upsert_brand_kwargs = kwargs
        knowledge_revision = kwargs.get("knowledge_revision")
        if isinstance(knowledge_revision, str) and knowledge_revision.strip():
            self.knowledge_revision = knowledge_revision.strip()
        for key, value in kwargs.items():
            if value is None:
                continue
            if key == "target_regions":
                self._brand_row["target_regions_json"] = value
                continue
            self._brand_row[key] = value
        self._brand_row["knowledge_revision"] = self.knowledge_revision
        return 1

    def list_brands(self, *, keyword: str | None = None):
        return []

    def delete_brand(self, *, brand_id: int) -> None:
        self.deleted_brand_ids.append(brand_id)

    def rename_brand(self, *, brand_code: str, new_brand_name: str):
        old_brand_name = str(self._brand_row.get("brand_name") or "")
        self.rename_calls.append(
            {
                "brand_code": brand_code,
                "new_brand_name": new_brand_name,
            }
        )
        if self.rename_errors:
            raise self.rename_errors.pop(0)
        rename_job = {
            "job_id": f"bg:brand_rename_milvus_sync:{brand_code}:{new_brand_name}",
            "job_type": "brand_rename_milvus_sync",
            "source_type": "brand_rename",
            "source_id": f"{brand_code}:{new_brand_name}",
            "status": "waiting",
        }
        self.rename_job_calls.append(
            {
                "brand_code": brand_code,
                "old_brand_name": old_brand_name,
                "new_brand_name": new_brand_name,
                "background_job": rename_job,
            }
        )
        if self.rename_result is not None:
            return self.rename_result
        self._brand_row["brand_name"] = new_brand_name
        return {
            "brand_id": self._brand_row["id"],
            "brand_code": brand_code,
            "old_brand_name": old_brand_name,
            "brand_name": new_brand_name,
            "counts": {
                "brands": 1,
                "brand_products": 0,
                "brand_full_knowledge_files": 0,
                "brand_knowledge_facts": 0,
                "brand_attachment_assets": 0,
                "brand_knowledge_ingestion_jobs": 0,
                "brand_knowledge_sessions": 0,
                "document_registry": 0,
                "document_categories": 0,
                "background_jobs": 1,
                "upload_tasks": 0,
            },
            "updated_tables": ["brands"],
            "background_job": rename_job,
        }


class OperationalError(RuntimeError):
    pass


class FakeMilvusRenameStore:
    def __init__(self, *, should_raise: bool = False) -> None:
        self.should_raise = should_raise
        self.rename_calls: list[dict[str, object]] = []

    def rename_brand(self, *, brand_code: str, old_brand_name: str, new_brand_name: str):
        self.rename_calls.append(
            {
                "brand_code": brand_code,
                "old_brand_name": old_brand_name,
                "new_brand_name": new_brand_name,
            }
        )
        if self.should_raise:
            raise RuntimeError("Milvus rename failed")
        return {
            "chunks": 2,
            "facts": 3,
        }


class EmptyWebsiteBrandStore(FakeBrandStore):
    def __init__(self, *, knowledge_revision: str = "demo-2026-06-23") -> None:
        super().__init__(knowledge_revision=knowledge_revision)
        self._brand_row["website"] = ""

    def get_brand_by_name(self, brand_name: str):
        row = super().get_brand_by_name(brand_name)
        if row is None:
            return None
        return row


class EmptyWebsiteAndEnglishBrandStore(FakeBrandStore):
    def __init__(self, *, knowledge_revision: str = "demo-2026-06-23") -> None:
        super().__init__(knowledge_revision=knowledge_revision)
        self._brand_row["website"] = ""
        self._brand_row["english_name"] = ""

    def get_brand_by_name(self, brand_name: str):
        row = super().get_brand_by_name(brand_name)
        if row is None:
            return None
        return row


class FakeIndustryStore:
    def get_industry_by_id(self, industry_id: int):
        if industry_id != 1:
            return None
        return {
            "id": 1,
            "code": "consumer",
            "name": "消费品",
            "level": 1,
        }


class FakeBrandProductStore:
    def __init__(self) -> None:
        self.last_products_upsert = None
        self.deleted_brand_ids: list[int] = []
        self.synced_products: list[dict] | None = None

    def get_brand_products(self, *, brand_id: int):
        if brand_id != 1:
            return []
        if self.synced_products is not None:
            return self.synced_products
        return [
            {
                "product_name": "明星产品",
                "product_alias": "爆款",
                "product_description": "核心产品介绍",
                "product_website": "https://example.com/product",
                "product_images_json": "[\"https://example.com/product-1.png\"]",
                "price_info": "199元",
                "coverage_regions_json": "[\"中国\"]",
                "product_advantages": "复购率高",
                "target_scenarios": "家庭使用",
                "service_standard": "7x24",
                "service_process": "咨询-开通",
                "cases_and_reputation": "头部客户在用",
                "certification_info": "ISO",
                "core_technology": "自研引擎",
            }
        ]

    def upsert_brand_products(self, *, brand_id: int, brand_name: str, products: list[dict]):
        self.last_products_upsert = {
            "brand_id": brand_id,
            "brand_name": brand_name,
            "products": products,
        }

    def count_brand_products_for_delete(self, *, brand_id: int, brand_name: str) -> int:
        return len(self.get_brand_products(brand_id=brand_id))

    def sync_brand_products(self, *, brand_id: int, brand_name: str, products: list[dict]) -> None:
        coded_products = [product for product in products if product.get("product_code")]
        uncoded_names = {product["product_name"].casefold() for product in products if not product.get("product_code")}
        retained = [
            product for product in self.get_brand_products(brand_id=brand_id)
            if product["product_name"].casefold() in uncoded_names
        ]
        if coded_products:
            self.upsert_brand_products(brand_id=brand_id, brand_name=brand_name, products=coded_products)
        self.synced_products = [*coded_products, *retained]

    def delete_brand_products(self, *, brand_id: int, brand_name: str) -> None:
        self.deleted_brand_ids.append(brand_id)


class EmptyBrandProductStore(FakeBrandProductStore):
    def get_brand_products(self, *, brand_id: int):
        return []


class FakeBrandKnowledgeStore:
    def __init__(self) -> None:
        self.last_knowledge_upserts: list[tuple[object, str, object]] = []
        self.knowledge_rows: list[dict[str, object]] = []
        self.deleted_brand_ids: list[int] = []
        self.deleted_knowledge_types: list[tuple[int, str]] = []

    def count_brand_knowledge_json(self, *, brand_id: int) -> int:
        return len(self.get_all_brand_knowledge_json(brand_id=brand_id))

    def delete_brand_knowledge_json(self, *, brand_id: int) -> None:
        self.deleted_brand_ids.append(brand_id)

    def delete_brand_knowledge_type(self, *, brand_id: int, knowledge_type: str) -> None:
        self.deleted_knowledge_types.append((brand_id, knowledge_type))
        self.knowledge_rows = [
            row
            for row in self.knowledge_rows
            if not (row.get("knowledge_type") == knowledge_type and brand_id == 1)
        ]

    def get_all_brand_knowledge_json(self, *, brand_id: int):
        if self.knowledge_rows:
            return self.knowledge_rows
        if brand_id != 1:
            return []
        return [
            {
                "knowledge_type": "company_info",
                "content_json": {"brand_subject_name": "示例品牌主体名称"},
            },
            {
                "knowledge_type": "competitors",
                "content_json": [{"name": "竞品A"}],
            },
        ]

    def upsert_brand_knowledge_json(
        self,
        *,
        brand_id: int,
        knowledge_type: str,
        knowledge_name=None,
        content_json=None,
        source_task_id=None,
    ):
        self.last_knowledge_upserts.append((brand_id, knowledge_type, knowledge_name, content_json))
        self.knowledge_rows = [
            row for row in self.knowledge_rows
            if row.get("knowledge_type") != knowledge_type
        ]
        self.knowledge_rows.append(
            {
                "knowledge_type": knowledge_type,
                "knowledge_name": knowledge_name,
                "content_json": content_json,
                "source_task_id": source_task_id,
            }
        )


class FakeBrandKnowledgeUpdateAuditStore:
    def __init__(self, *, should_raise: bool = False) -> None:
        self.created_calls: list[dict[str, object]] = []
        self.should_raise = should_raise

    def create_audit_entries(
        self,
        *,
        audit_id: str,
        brand_id: int,
        brand_code: str | None,
        brand_name: str,
        knowledge_revision: str | None,
        entries: list[dict[str, object]],
        source_type: str = "knowledge_update",
        source_task_id: str | None = None,
        source_job_id: str | None = None,
        source_name: str | None = None,
        source_oss_key: str | None = None,
    ) -> int:
        if self.should_raise:
            raise RuntimeError("audit insert failed")
        self.created_calls.append(
            {
                "audit_id": audit_id,
                "brand_id": brand_id,
                "brand_code": brand_code,
                "brand_name": brand_name,
                "knowledge_revision": knowledge_revision,
                "entries": json.loads(json.dumps(entries, ensure_ascii=False, default=str)),
                "source_type": source_type,
                "source_task_id": source_task_id,
                "source_job_id": source_job_id,
                "source_name": source_name,
                "source_oss_key": source_oss_key,
            }
        )
        return len(entries)


class FakeBrandFullKnowledgeStore:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []
        self.deleted_brand_ids: list[int] = []

    @staticmethod
    def _is_queryable_latest(row: dict[str, object]) -> bool:
        return str(row.get("ingest_status") or "").strip() != "skipped"

    @staticmethod
    def _latest_sort_key(row: dict[str, object]) -> tuple[int, int, int, int]:
        return (
            1 if row.get("is_latest") else 0,
            int(row.get("version_no") or 0),
            int(row.get("revision_no") or 0),
            int(row.get("id") or 0),
        )

    def get_latest_by_brand_id(self, *, brand_id: int):
        brand_rows = [
            row
            for row in self.rows
            if int(row.get("brand_id") or 0) == brand_id and self._is_queryable_latest(row)
        ]
        if not brand_rows:
            return None
        return sorted(brand_rows, key=self._latest_sort_key, reverse=True)[0]

    def get_by_brand_id_and_task_id(self, *, brand_id: int, source_task_id: str):
        for row in self.rows:
            if int(row.get("brand_id") or 0) == brand_id and str(row.get("source_task_id") or "") == source_task_id:
                return row
        return None

    def list_by_brand_id(self, *, brand_id: int):
        return [row for row in self.rows if int(row.get("brand_id") or 0) == brand_id]

    def delete_by_brand_id(self, *, brand_id: int) -> None:
        self.deleted_brand_ids.append(brand_id)
        self.rows = [row for row in self.rows if int(row.get("brand_id") or 0) != brand_id]

    def get_next_version_no(self, *, brand_id: int) -> int:
        latest = self.get_latest_by_brand_id(brand_id=brand_id)
        if latest is None:
            return 1
        return int(latest.get("version_no") or 0) + 1

    def create_brand_full_knowledge_file(
        self,
        *,
        brand_id: int,
        brand_name: str,
        version_no: int,
        file_name: str,
        pdf_file_name: str | None,
        oss_key: str | None,
        oss_url: str | None,
        pdf_oss_key: str | None,
        pdf_oss_url: str | None,
        content_markdown: str,
        conflict_count: int,
        conflicts_json,
        source_task_id: str | None,
    ) -> int:
        row_id = len(self.rows) + 1
        self.rows.append(
            {
                "id": row_id,
                "brand_id": brand_id,
                "brand_name": brand_name,
                "version_no": version_no,
                "file_name": file_name,
                "pdf_file_name": pdf_file_name,
                "oss_key": oss_key,
                "oss_url": oss_url,
                "pdf_oss_key": pdf_oss_key,
                "pdf_oss_url": pdf_oss_url,
                "content_markdown": content_markdown,
                "conflict_count": conflict_count,
                "conflicts_json": conflicts_json,
                "source_task_id": source_task_id,
            }
        )
        return row_id


class FakeDocumentRegistryStore:
    def __init__(self) -> None:
        self.latest_success_documents_by_filename: dict[tuple[str, str, str], list[dict[str, object]]] = {}
        self.entries_by_category: dict[str, list[dict[str, object]]] = {}

    def get_document_ai_statuses(self, document_ids: list[str]):
        return {
            "doc-1": {"facts_status": "success"},
            "doc-2": {"facts_status": "failed"},
        }

    def reserve_document_uploads(self, **kwargs):
        return {"reserved_files": list(kwargs.get("files", [])), "duplicate_files": []}

    def release_document_upload(self, **kwargs):
        return None

    def complete_document_upload(self, **kwargs):
        return None

    def get_document_registry_record(self, *, category: str, file_hash: str):
        return {
            "document_id": "doc-1",
            "upload_task_id": "task-1",
            "facts_status": "success",
        }

    def get_document_registry_entries_by_category(self, category: str):
        return list(self.entries_by_category.get(category, []))

    def find_latest_success_documents_by_filename(
        self,
        original_filename: str,
        *,
        category: str | None = None,
        source_url: str | None = None,
    ):
        key = (
            str(original_filename),
            str(category or ""),
            str(source_url or ""),
        )
        return list(self.latest_success_documents_by_filename.get(key, []))


class FakeDocumentCategoryStore:
    def __init__(self) -> None:
        self.invalidated_categories: list[str | None] = []

    def get_latest_document_ids_by_category(self, category: str):
        return []

    def get_latest_document_ids_by_category_and_subcategory(self, category: str, subcategory: str):
        return []

    def get_searchable_document_ids(self, document_ids):
        return document_ids or []

    def get_document_ids_by_category(self, category: str):
        return []

    def invalidate_latest_document_ids_cache(self, category=None):
        self.invalidated_categories.append(category)
        return None

    def document_exists(self, document_id: str) -> bool:
        return True

    def reserve_document_uploads(self, **kwargs):
        return None

    def release_document_upload(self, **kwargs):
        return None

    def complete_document_upload(self, **kwargs):
        return None


class FakeUploadTaskStore:
    def __init__(self) -> None:
        self.callback_row = None
        self.callback_rows: dict[tuple[str, str], dict[str, object]] = {}
        self.retryable_callbacks: list[dict[str, object]] = []
        self.deleted_brand_identifier_calls: list[dict[str, object]] = []

    def refresh_upload_task_counts(self, task_id: str):
        return {
            "file_count": 2,
            "success_count": 2,
            "failed_count": 0,
            "pending_count": 0,
            "processing_count": 0,
        }

    def get_upload_task(self, task_id: str):
        if task_id != "task-1":
            return None
        return {
            "task_id": task_id,
            "status": "completed",
            "file_count": 2,
            "success_count": 2,
            "failed_count": 0,
            "pending_count": 0,
            "processing_count": 0,
            "metadata_json": {
                "category": "示例品牌",
                "brand_callback_enabled": True,
                "brand_code": "BRAND-001",
                "_task_payload": {
                    "requested_competitors": [
                        {
                            "name": "竞品A",
                            "website": "https://competitor-a.example.com",
                        }
                    ],
                    "requested_products": [
                        {
                            "product_name": "明星产品",
                            "product_alias": "爆款",
                            "product_description": "核心产品介绍",
                            "product_website": "https://example.com/product",
                            "product_images": ["https://example.com/product-1.png"],
                        }
                    ],
                    "file_metadata_by_index": {
                        "0": {"source_url": "https://example.com/brand-book.pdf"},
                        "1": {"source_url": "https://example.com/certs.pdf", "subcategory": "产品A"},
                    }
                },
            },
            "updated_at": datetime(2026, 6, 8, 12, 0, 0),
        }

    def get_upload_task_files(self, task_id: str):
        return [
            {"status": "success", "document_id": "doc-1", "file_index": 0, "original_filename": "品牌手册.md", "source_type": "pdf", "file_size": 100},
            {"status": "success", "document_id": "doc-2", "file_index": 1, "original_filename": "资质证书.md", "source_type": "pdf", "file_size": 200},
        ]

    def get_upload_task_callback(self, *, task_id: str, callback_type: str):
        return self.callback_rows.get((task_id, callback_type)) or self.callback_row

    def upsert_upload_task_callback(
        self,
        *,
        task_id: str,
        callback_type: str,
        callback_url: str,
        request_payload_json: dict | None,
        status: str,
    ):
        key = (task_id, callback_type)
        row = dict(self.callback_rows.get(key) or {})
        row.update(
            {
                "task_id": task_id,
                "callback_type": callback_type,
                "callback_url": callback_url,
                "status": status,
            }
        )
        if request_payload_json is not None:
            row["request_payload_json"] = request_payload_json
        row.setdefault("request_payload_json", request_payload_json)
        row.setdefault("retry_count", 0)
        row.setdefault("next_retry_at", None)
        row.setdefault("last_response_code", None)
        row.setdefault("last_response_body", None)
        row.setdefault("last_error_message", None)
        row.setdefault("sent_at", None)
        self.callback_rows[key] = row
        self.callback_row = row

    def update_upload_task_callback_result(self, **kwargs):
        key = (kwargs["task_id"], kwargs["callback_type"])
        row = dict(self.callback_rows.get(key) or self.callback_row or {})
        row.update(kwargs)
        self.callback_rows[key] = row
        self.callback_row = row

    def list_retryable_upload_task_callbacks(self, *, callback_type: str):
        return [
            row for row in [*self.callback_rows.values(), *self.retryable_callbacks]
            if str(row.get("callback_type") or "") == callback_type
            and str(row.get("status") or "") == "retrying"
        ]

    def count_by_brand_identifier(self, *, brand_code: str | None, brand_name: str | None):
        if brand_code == "BRAND-001" or brand_name == "示例品牌":
            return {
                "upload_tasks": 1,
                "upload_task_files": 2,
                "upload_task_callbacks": 1,
            }
        return {
            "upload_tasks": 0,
            "upload_task_files": 0,
            "upload_task_callbacks": 0,
        }

    def list_task_ids_by_brand_identifier(self, *, brand_code: str | None, brand_name: str | None):
        if brand_code == "BRAND-001" or brand_name == "示例品牌":
            return ["task-brand-1"]
        return []

    def delete_by_brand_identifier(self, *, brand_code: str | None, brand_name: str | None):
        self.deleted_brand_identifier_calls.append(
            {
                "brand_code": brand_code,
                "brand_name": brand_name,
            }
        )
        return self.count_by_brand_identifier(brand_code=brand_code, brand_name=brand_name)


@dataclass
class FakeSettings:
    brand_completion_callback_url: str = "https://callback.example.com"
    brand_completion_callback_timeout_seconds: float = 5.0
    brand_full_knowledge_refresh_delay_seconds: int = 300
    brand_paths_load_cache_ttl_seconds: float = 600.0
    brand_paths_load_cache_max_entries: int = 100
    path_index_summary_cache_max_entries: int = 800
    upload_staging_dir: str = "/tmp"
    dashscope_api_key: str = "test-dashscope-key"
    text_llm_model: str = "qwen-plus"
    tianyancha_enabled: bool = False
    tianyancha_api_key: str = ""
    tianyancha_mcp_url: str = "https://mcp.tianyancha.com/v1"
    tianyancha_timeout_seconds: float = 15.0
    anthropic_base_url: str = "https://anthropic.example.com/v1/messages"
    anthropic_api_key: str = "test-anthropic-key"
    anthropic_model: str = "claude-opus-4-8"
    brand_patch_llm_provider: str = "anthropic"
    local_llm_base_url: str = "http://127.0.0.1:9111/v1/chat/completions"
    local_llm_model: str = "expert"
    local_llm_api_key: str = ""
