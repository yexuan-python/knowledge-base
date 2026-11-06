from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

from tests._stub_utils import ensure_stub_module


def _install_import_stubs() -> None:
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

            def model_dump(self):
                return dict(self.__dict__)

        def Field(default=None, **kwargs):
            if "default_factory" in kwargs:
                return kwargs["default_factory"]()
            return default

        pydantic_stub.BaseModel = BaseModel
        pydantic_stub.Field = Field
        sys.modules.setdefault("pydantic", pydantic_stub)

    dashscope_stub = ensure_stub_module("dashscope")
    if dashscope_stub is not None:
        dashscope_stub.Generation = type("Generation", (), {"call": staticmethod(lambda *args, **kwargs: None)})
        dashscope_stub.MultiModalConversation = type(
            "MultiModalConversation",
            (),
            {"call": staticmethod(lambda *args, **kwargs: None)},
        )
        dashscope_stub.MultiModalEmbedding = type(
            "MultiModalEmbedding",
            (),
            {"call": staticmethod(lambda *args, **kwargs: None)},
        )
        sys.modules.setdefault("dashscope", dashscope_stub)

    requests_stub = ensure_stub_module("requests")
    if requests_stub is not None:
        requests_stub.post = lambda *args, **kwargs: None
        sys.modules.setdefault("requests", requests_stub)

    infrastructure_package_stub = ensure_stub_module("knowledge_base.infrastructure", is_package=True)
    if infrastructure_package_stub is not None:
        sys.modules.setdefault("knowledge_base.infrastructure", infrastructure_package_stub)

    settings_stub = ensure_stub_module("knowledge_base.infrastructure.settings")
    if settings_stub is not None:
        settings_stub.Settings = type("Settings", (), {})
        sys.modules.setdefault("knowledge_base.infrastructure.settings", settings_stub)

    llm_stub = ensure_stub_module("knowledge_base.infrastructure.llm")
    if llm_stub is not None:
        llm_stub.extract_json_value = lambda text: text
        llm_stub.get_dashscope_api_key = lambda settings: getattr(settings, "dashscope_api_key", "")
        llm_stub.require_settings = lambda settings: settings
        llm_stub.build_source_blocks = lambda markdown_sources, **kwargs: list(markdown_sources)
        llm_stub.call_text_llm_json = lambda *args, **kwargs: {}
        llm_stub.call_text_llm = lambda *args, **kwargs: ""
        llm_stub.call_text_llm_text = lambda *args, **kwargs: ""
        llm_stub.call_anthropic_json = lambda prompt, **kwargs: {}
        llm_stub.call_anthropic_text = lambda prompt, **kwargs: ""
        sys.modules.setdefault("knowledge_base.infrastructure.llm", llm_stub)

    brand_requests_stub = ensure_stub_module("knowledge_base.brand.schemas.requests")
    if brand_requests_stub is not None:
        class KnowledgeUpdateRequest:
            def __init__(self, **kwargs):
                for key, value in kwargs.items():
                    if key == "basic_info" and isinstance(value, dict):
                        value = types.SimpleNamespace(**value)
                    elif key == "products" and isinstance(value, list):
                        value = [
                            types.SimpleNamespace(**item) if isinstance(item, dict) else item
                            for item in value
                        ]
                    setattr(self, key, value)

        brand_requests_stub.KnowledgeUpdateRequest = KnowledgeUpdateRequest
        sys.modules.setdefault("knowledge_base.brand.schemas.requests", brand_requests_stub)

    ingest_package_stub = ensure_stub_module("knowledge_base.ingest", is_package=True)
    if ingest_package_stub is not None:
        sys.modules.setdefault("knowledge_base.ingest", ingest_package_stub)

    ingest_application_stub = ensure_stub_module("knowledge_base.ingest.application", is_package=True)
    if ingest_application_stub is not None:
        sys.modules.setdefault("knowledge_base.ingest.application", ingest_application_stub)

    remote_download_stub = ensure_stub_module("knowledge_base.ingest.application.remote_download")
    if remote_download_stub is not None:

        async def _fake_download_remote_content_to_temp_file(*, name: str, **kwargs):
            del kwargs
            suffix = Path(name).suffix or ".tmp"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                temp_path = Path(tmp.name)
            return temp_path, "application/octet-stream", 0

        async def _fake_download_remote_content_to_path(*, destination: Path, **kwargs):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"")
            return "application/octet-stream", 0

        remote_download_stub.download_remote_content_to_temp_file = _fake_download_remote_content_to_temp_file
        remote_download_stub.download_remote_content_to_path = _fake_download_remote_content_to_path
        sys.modules.setdefault("knowledge_base.ingest.application.remote_download", remote_download_stub)

    shared_package_stub = ensure_stub_module("knowledge_base.shared", is_package=True)
    if shared_package_stub is not None:
        sys.modules.setdefault("knowledge_base.shared", shared_package_stub)

    shared_utils_stub = ensure_stub_module("knowledge_base.shared.utils")
    if shared_utils_stub is not None:
        shared_utils_stub.build_fulltext_object_key = lambda **kwargs: "fulltext-key"
        shared_utils_stub.build_original_object_key = lambda **kwargs: "original-key"
        shared_utils_stub.compute_sha256 = lambda content: "sha256"
        shared_utils_stub.normalize_upload_metadata = lambda metadata: metadata
        shared_utils_stub.parse_metadata_json = lambda raw: json.loads(raw) if isinstance(raw, str) and raw.strip() else {}
        sys.modules.setdefault("knowledge_base.shared.utils", shared_utils_stub)


_install_import_stubs()

from knowledge_base.brand_knowledge.application.attachment_flow import (
    AttachmentDraftDependencies,
    AttachmentDraftService,
)
from knowledge_base.service import KnowledgeBaseService


def _value_from_object_or_dict(value, key: str):
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key)


class _FakeParser:
    def parse_path(self, _path: Path, *, source_name: str):
        return types.SimpleNamespace(
            markdown_text=f"# {source_name}\n这里是品牌附件正文",
            text="这里是品牌附件正文",
            source_type="pdf",
            metadata={"parser_backend": "fake-parser"},
        )


class _FakeOSSClient:
    enabled = True

    def __init__(self) -> None:
        self.uploaded: list[dict[str, object]] = []

    def upload_bytes(self, data: bytes, object_key: str, content_type: str = "application/octet-stream"):
        self.uploaded.append(
            {
                "data": data,
                "object_key": object_key,
                "content_type": content_type,
            }
        )
        return object_key

    def build_object_url(self, object_key: str):
        return f"https://oss.example.com/{object_key}"


class _FakeBrandStore:
    def __init__(self, *, knowledge_revision: str = "LXKG-SLPP-V1.0.0-20260630010101") -> None:
        self._brand = {
            "id": 1,
            "brand_code": "BRAND-001",
            "brand_name": "示例品牌",
            "website": json.dumps(["https://old.example.com"], ensure_ascii=False),
            "customer_service_hotline": "400-000-0000",
            "official_wechat_account": "demo_wechat",
            "intro": "旧品牌介绍",
            "email": "brand@example.com",
            "brand_enterprise_entity": "示例企业主体",
            "business_license_image_path": "https://example.com/license.png",
            "industry_id": "12",
            "english_name": None,
            "positioning": "旧定位",
            "advantages": "旧优势",
            "mission": "旧使命",
            "vision": "旧愿景",
            "target_regions_json": json.dumps(["中国"], ensure_ascii=False),
            "other_info": None,
            "knowledge_revision": knowledge_revision,
        }

    def get_brand_by_code(self, brand_code: str):
        if brand_code == self._brand["brand_code"]:
            return dict(self._brand)
        return None

    def get_brand_by_name(self, brand_name: str):
        if brand_name == self._brand["brand_name"]:
            return dict(self._brand)
        return None


class _FakeBrandProductStore:
    def __init__(self, products: list[dict[str, object]] | None = None) -> None:
        self._products = products or [
            {
                "product_name": "经典产品",
                "product_alias": "经典款",
                "product_description": "旧产品介绍",
                "product_website": "https://old.example.com/product",
                "product_images_json": json.dumps([], ensure_ascii=False),
                "price_info": None,
                "coverage_regions_json": json.dumps(["中国"], ensure_ascii=False),
                "product_advantages": None,
                "target_scenarios": None,
                "service_standard": None,
                "service_process": None,
                "cases_and_reputation": None,
                "certification_info": None,
                "core_technology": None,
                "other_info": None,
            }
        ]

    def get_brand_products(self, *, brand_id: int):
        return list(self._products)


class _FakeBrandKnowledgeStore:
    def __init__(self, rows: list[dict[str, object]] | None = None) -> None:
        self.last_knowledge_upserts: list[dict[str, object]] = []
        self._rows = rows or [
            {
                "knowledge_type": "company_profile",
                "content_json": json.dumps(
                    {
                        "brand_subject_name": "示例企业主体",
                        "company_intro": "旧公司简介",
                    },
                    ensure_ascii=False,
                ),
            },
            {
                "knowledge_type": "management_team",
                "content_json": json.dumps([], ensure_ascii=False),
            },
            {
                "knowledge_type": "competitors",
                "content_json": json.dumps(
                    [
                        {
                            "name": "竞品A",
                            "competitors_alias": "竞品甲",
                            "competitors_description": "老竞品介绍",
                            "website": "https://competitor-a.example.com",
                        }
                    ],
                    ensure_ascii=False,
                ),
            },
            {
                "knowledge_type": "authority_honors",
                "content_json": json.dumps([], ensure_ascii=False),
            },
            {
                "knowledge_type": "customers_cases",
                "content_json": json.dumps([], ensure_ascii=False),
            },
            {
                "knowledge_type": "sensitive_topics",
                "content_json": json.dumps({}, ensure_ascii=False),
            },
            {
                "knowledge_type": "attachments",
                "content_json": json.dumps(
                    [
                        {
                            "name": "历史附件.pdf",
                            "url": "https://example.com/history.pdf",
                        }
                    ],
                    ensure_ascii=False,
                ),
            },
            {
                "knowledge_type": "other_info",
                "content_json": json.dumps(
                    {
                        "夜游说明": "每晚开放",
                        "停车场信息": "旧停车场信息",
                    },
                    ensure_ascii=False,
                ),
            },
        ]

    def get_all_brand_knowledge_json(self, *, brand_id: int):
        return list(self._rows)

    def upsert_brand_knowledge_json(
        self,
        *,
        brand_id: int,
        knowledge_type: str,
        knowledge_name=None,
        content_json=None,
        source_task_id=None,
    ):
        self.last_knowledge_upserts.append(
            {
                "brand_id": brand_id,
                "knowledge_type": knowledge_type,
                "knowledge_name": knowledge_name,
                "content_json": content_json,
                "source_task_id": source_task_id,
            }
        )
        self._rows = [
            row for row in self._rows
            if row.get("knowledge_type") != knowledge_type
        ]
        self._rows.append(
            {
                "knowledge_type": knowledge_type,
                "knowledge_name": knowledge_name,
                "content_json": content_json,
                "source_task_id": source_task_id,
            }
        )



__all__ = [
    "asyncio",
    "json",
    "tempfile",
    "types",
    "unittest",
    "datetime",
    "timedelta",
    "Path",
    "AsyncMock",
    "patch",
    "AttachmentDraftDependencies",
    "AttachmentDraftService",
    "KnowledgeBaseService",
    "_value_from_object_or_dict",
    "_FakeParser",
    "_FakeOSSClient",
    "_FakeBrandStore",
    "_FakeBrandProductStore",
    "_FakeBrandKnowledgeStore",
]
