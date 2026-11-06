from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import AsyncMock

from tests._stub_utils import ensure_stub_module


def _install_service_import_stubs() -> None:
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

        class _MultiModalEmbedding:
            @staticmethod
            def call(*args, **kwargs):
                raise RuntimeError("MultiModalEmbedding.call should be stubbed in tests")

        dashscope_stub.Generation = _Generation
        dashscope_stub.MultiModalEmbedding = _MultiModalEmbedding
        sys.modules.setdefault("dashscope", dashscope_stub)

    fastapi_stub = ensure_stub_module("fastapi")
    if fastapi_stub is not None:
        fastapi_stub.UploadFile = type("UploadFile", (), {})
        sys.modules.setdefault("fastapi", fastapi_stub)


def _format_brand_callback_knowledge_from_snapshot_for_test(*, brand, knowledge_snapshot):
    del brand
    raw_attachments = knowledge_snapshot.get("attachments") or []
    if isinstance(raw_attachments, dict):
        raw_attachments = raw_attachments.get("files") or []
    files = []
    for item in raw_attachments:
        if not isinstance(item, dict):
            continue
        files.append(
            {
                "name": str(item.get("name") or "").strip(),
                "url": str(item.get("url") or "").strip(),
                "type": str(item.get("type") or "").strip(),
                "description": str(item.get("description") or "").strip(),
            }
        )
    return {
        "attachments": {
            "files": files,
        }
    }


_install_service_import_stubs()

from knowledge_base.service import KnowledgeBaseService


def _build_attachment_delete_callback_payload_for_test(
    service: KnowledgeBaseService,
    *,
    brand: dict[str, object],
) -> dict[str, object]:
    knowledge_markdown_status, knowledge_mete = service._current_brand_knowledge_mete(brand=brand)
    return {
        "brand_code": str(brand.get("brand_code") or "").strip(),
        "overall_status": "completed",
        "completed_at": "2026-07-30 00:00:00",
        "knowledge_extraction_status": "success",
        "knowledge_markdown_status": knowledge_markdown_status,
        "knowledge_mete": knowledge_mete,
        "knowledge": _format_brand_callback_knowledge_from_snapshot_for_test(
            brand=brand,
            knowledge_snapshot=service._load_brand_knowledge_snapshot(brand=brand),
        ),
    }


def _attach_brand_callback_stub(service: KnowledgeBaseService) -> None:
    service._brand_callbacks = types.SimpleNamespace(
        build_attachment_delete_callback_payload=lambda *, brand: (
            _build_attachment_delete_callback_payload_for_test(service, brand=brand)
        )
    )


class _FakeDocumentRegistry:
    def __init__(self, matches: list[dict[str, str]]) -> None:
        self.matches = matches
        self.calls: list[dict[str, str | None]] = []

    def find_latest_success_documents_by_filename(
        self,
        original_filename: str,
        *,
        category: str | None = None,
        source_url: str | None = None,
    ) -> list[dict[str, str]]:
        self.calls.append(
            {
                "original_filename": original_filename,
                "category": category,
                "source_url": source_url,
            }
        )
        return list(self.matches)


class _FakeBrands:
    def __init__(self, brands_by_code: dict[str, dict[str, str]] | None = None) -> None:
        self.brands_by_code = brands_by_code or {}
        self.calls: list[str] = []

    def get_brand_by_code(self, brand_code: str) -> dict[str, str] | None:
        self.calls.append(brand_code)
        return self.brands_by_code.get(brand_code)


class _FakeBrandKnowledge:
    def __init__(self, attachments: list[dict[str, object]]) -> None:
        self.attachments = attachments
        self.upserts: list[dict[str, object]] = []

    def get_brand_knowledge_json(self, *, brand_id: int, knowledge_type: str):
        if knowledge_type != "attachments":
            return None
        return {
            "brand_id": brand_id,
            "knowledge_type": knowledge_type,
            "content_json": self.attachments,
        }

    def get_all_brand_knowledge_json(self, *, brand_id: int):
        return [
            {
                "brand_id": brand_id,
                "knowledge_type": "attachments",
                "content_json": self.attachments,
            }
        ]

    def upsert_brand_knowledge_json(self, **kwargs):
        self.upserts.append(kwargs)
        if kwargs.get("knowledge_type") == "attachments":
            self.attachments = list(kwargs.get("content_json") or [])


class _FakeBrandProducts:
    def get_brand_products(self, *, brand_id: int):
        return []


class _FakeBrandFullKnowledge:
    def __init__(self) -> None:
        self.calls: list[int] = []

    def get_latest_by_brand_id(self, *, brand_id: int):
        self.calls.append(brand_id)
        return {
            "oss_url": "https://oss.example.com/knowledge/current.md",
            "pdf_oss_url": "https://oss.example.com/knowledge/current.pdf",
        }


class _FakeUploadTasks:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], dict[str, object]] = {}

    def upsert_upload_task_callback(
        self,
        *,
        task_id: str,
        callback_type: str,
        callback_url: str,
        request_payload_json: dict | None,
        status: str,
    ):
        row = dict(self.rows.get((task_id, callback_type)) or {})
        row.update(
            {
                "task_id": task_id,
                "callback_type": callback_type,
                "callback_url": callback_url,
                "request_payload_json": request_payload_json,
                "status": status,
            }
        )
        row.setdefault("retry_count", 0)
        self.rows[(task_id, callback_type)] = row

    def get_upload_task_callback(self, *, task_id: str, callback_type: str):
        return self.rows.get((task_id, callback_type))

    def update_upload_task_callback_result(self, **kwargs):
        key = (kwargs["task_id"], kwargs["callback_type"])
        row = dict(self.rows.get(key) or {})
        row.update(kwargs)
        self.rows[key] = row


class _FakeSettings:
    brand_completion_callback_url = "https://callback.example.com"
    brand_completion_callback_timeout_seconds = 5.0


class AttachmentDeleteBehaviorTests(unittest.IsolatedAsyncioTestCase):
    async def test_delete_attachment_by_name_delegates_to_document_application(self) -> None:
        service = KnowledgeBaseService.__new__(KnowledgeBaseService)
        document_app = types.SimpleNamespace(
            delete_document_by_attachment_name=AsyncMock(return_value="doc-1")
        )
        service._document_app = document_app

        result = await service.delete_document_by_attachment_name(
            "品牌手册.pdf",
            url="https://example.com/a.pdf",
            category="demo",
        )

        self.assertEqual("doc-1", result)
        document_app.delete_document_by_attachment_name.assert_awaited_once_with(
            "品牌手册.pdf",
            url="https://example.com/a.pdf",
            category="demo",
        )

    async def test_batch_delete_uses_brand_code_to_resolve_brand_name(self) -> None:
        service = KnowledgeBaseService.__new__(KnowledgeBaseService)
        service._brands = _FakeBrands(
            {
                "100093": {
                    "id": 93,
                    "brand_code": "100093",
                    "brand_name": "理想汽车",
                }
            }
        )
        service._brand_knowledge = _FakeBrandKnowledge(
            [{"name": "理想汽车品牌概述.docx", "url": "https://example.com/a.pdf"}]
        )
        service._notify_attachment_delete_success = AsyncMock()

        result = await service.delete_documents_by_attachments(
            brand_code="100093",
            attachments=[
                {
                    "name": "理想汽车品牌概述.docx",
                    "url": "https://example.com/a.pdf",
                }
            ],
        )

        self.assertEqual(["100093"], service._brands.calls)
        self.assertEqual("100093", result["brand_code"])
        self.assertEqual("理想汽车", result["brand_name"])
        self.assertEqual(
            {
                "requested_count": 1,
                "deleted_count": 1,
                "not_found_count": 0,
                "failed_count": 0,
                "ambiguous_count": 0,
            },
            result["summary"],
        )
        self.assertEqual(
            [
                {
                    "name": "理想汽车品牌概述.docx",
                    "url": "https://example.com/a.pdf",
                    "status": "deleted",
                    "detail": "已从品牌知识附件列表移除",
                }
            ],
            result["results"],
        )

    async def test_batch_delete_updates_remaining_attachments_and_sends_current_callback_shape(self) -> None:
        service = KnowledgeBaseService.__new__(KnowledgeBaseService)
        service._settings = _FakeSettings()
        service._brands = _FakeBrands(
            {
                "BRAND-001": {
                    "id": 1,
                    "brand_code": "BRAND-001",
                    "brand_name": "Example Brand",
                    "knowledge_revision": "LXKG-EB-V1.0.0-20260710153000",
                }
            }
        )
        service._brand_knowledge = _FakeBrandKnowledge(
            [
                {
                    "name": "品牌手册.pdf",
                    "url": "https://example.com/brand-book.pdf",
                    "type": "pdf",
                    "description": "",
                },
                {
                    "name": "招商手册.pdf",
                    "url": "https://example.com/investment.pdf",
                    "type": "pdf",
                    "description": "",
                },
            ]
        )
        service._brand_products = _FakeBrandProducts()
        service._brand_full_knowledge = _FakeBrandFullKnowledge()
        service._upload_tasks = _FakeUploadTasks()
        _attach_brand_callback_stub(service)
        posted_payloads: list[dict[str, object]] = []

        def _fake_post_callback(callback_url: str, payload: dict[str, object], timeout_seconds: float):
            posted_payloads.append(payload)
            return 200, "ok"

        service._post_attachment_delete_callback = _fake_post_callback

        result = await service.delete_documents_by_attachments(
            brand_code="BRAND-001",
            attachments=[
                {
                    "name": "品牌手册.pdf",
                    "url": "https://example.com/brand-book.pdf",
                }
            ],
        )

        self.assertEqual(1, result["summary"]["deleted_count"])
        self.assertEqual(
            [
                {
                    "name": "招商手册.pdf",
                    "url": "https://example.com/investment.pdf",
                    "type": "pdf",
                }
            ],
            service._brand_knowledge.attachments,
        )
        self.assertEqual([1], service._brand_full_knowledge.calls)
        self.assertEqual(1, len(posted_payloads))
        callback_payload = posted_payloads[0]
        self.assertEqual("BRAND-001", callback_payload["brand_code"])
        self.assertEqual("completed", callback_payload["overall_status"])
        self.assertEqual("success", callback_payload["knowledge_extraction_status"])
        self.assertEqual("success", callback_payload["knowledge_markdown_status"])
        self.assertEqual(
            {
                "version": "LXKG-EB-V1.0.0-20260710153000",
                "oss_url_md": "https://oss.example.com/knowledge/current.md",
                "oss_url_pdf": "https://oss.example.com/knowledge/current.pdf",
            },
            callback_payload["knowledge_mete"],
        )
        self.assertEqual(
            {
                "files": [
                    {
                        "name": "招商手册.pdf",
                        "url": "https://example.com/investment.pdf",
                        "type": "pdf",
                        "description": "",
                    }
                ]
            },
            callback_payload["knowledge"]["attachments"],
        )

    async def test_batch_delete_keeps_same_name_attachment_with_different_url_in_state_and_callback(self) -> None:
        service = KnowledgeBaseService.__new__(KnowledgeBaseService)
        service._settings = _FakeSettings()
        service._brands = _FakeBrands(
            {
                "BRAND-001": {
                    "id": 1,
                    "brand_code": "BRAND-001",
                    "brand_name": "Example Brand",
                    "knowledge_revision": "LXKG-EB-V1.0.0-20260710153000",
                }
            }
        )
        service._brand_knowledge = _FakeBrandKnowledge(
            [
                {
                    "name": "品牌手册.pdf",
                    "url": "https://example.com/brand-book-2025.pdf",
                    "type": "pdf",
                    "description": "旧版",
                },
                {
                    "name": "品牌手册.pdf",
                    "url": "https://example.com/brand-book-2026.pdf",
                    "type": "pdf",
                    "description": "新版",
                },
            ]
        )
        service._brand_products = _FakeBrandProducts()
        service._brand_full_knowledge = _FakeBrandFullKnowledge()
        service._upload_tasks = _FakeUploadTasks()
        _attach_brand_callback_stub(service)
        posted_payloads: list[dict[str, object]] = []

        def _fake_post_callback(callback_url: str, payload: dict[str, object], timeout_seconds: float):
            posted_payloads.append(payload)
            return 200, "ok"

        service._post_attachment_delete_callback = _fake_post_callback

        result = await service.delete_documents_by_attachments(
            brand_code="BRAND-001",
            attachments=[
                {
                    "name": "品牌手册.pdf",
                    "url": "https://example.com/brand-book-2025.pdf",
                }
            ],
        )

        self.assertEqual(1, result["summary"]["deleted_count"])
        self.assertEqual(
            [
                {
                    "name": "品牌手册.pdf",
                    "url": "https://example.com/brand-book-2026.pdf",
                    "type": "pdf",
                    "description": "新版",
                }
            ],
            service._brand_knowledge.attachments,
        )
        self.assertEqual(1, len(posted_payloads))
        self.assertEqual(
            [
                {
                    "name": "品牌手册.pdf",
                    "url": "https://example.com/brand-book-2026.pdf",
                    "type": "pdf",
                    "description": "新版",
                }
            ],
            posted_payloads[0]["knowledge"]["attachments"]["files"],
        )

    async def test_batch_delete_marks_not_found_without_fallback_when_url_is_present(self) -> None:
        service = KnowledgeBaseService.__new__(KnowledgeBaseService)
        service._brands = _FakeBrands({"100093": {"brand_name": "理想汽车"}})
        service._brand_knowledge = _FakeBrandKnowledge([])

        result = await service.delete_documents_by_attachments(
            brand_code="100093",
            attachments=[
                {
                    "name": "理想汽车品牌概述.docx",
                    "url": "https://example.com/missing.docx",
                }
            ],
        )

        self.assertEqual(
            {
                "requested_count": 1,
                "deleted_count": 0,
                "not_found_count": 1,
                "failed_count": 0,
                "ambiguous_count": 0,
            },
            result["summary"],
        )
        self.assertEqual("not_found", result["results"][0]["status"])

    async def test_batch_delete_not_found_still_sends_attachment_delete_callback(self) -> None:
        service = KnowledgeBaseService.__new__(KnowledgeBaseService)
        service._settings = _FakeSettings()
        service._brands = _FakeBrands(
            {
                "BRAND-001": {
                    "id": 1,
                    "brand_code": "BRAND-001",
                    "brand_name": "Example Brand",
                    "knowledge_revision": "LXKG-EB-V1.0.0-20260710153000",
                }
            }
        )
        service._brand_knowledge = _FakeBrandKnowledge(
            [
                {
                    "name": "招商手册.pdf",
                    "url": "https://example.com/investment.pdf",
                    "type": "pdf",
                    "description": "",
                }
            ]
        )
        service._brand_products = _FakeBrandProducts()
        service._brand_full_knowledge = _FakeBrandFullKnowledge()
        service._upload_tasks = _FakeUploadTasks()
        _attach_brand_callback_stub(service)
        posted_payloads: list[dict[str, object]] = []

        def _fake_post_callback(callback_url: str, payload: dict[str, object], timeout_seconds: float):
            posted_payloads.append(payload)
            return 200, "ok"

        service._post_attachment_delete_callback = _fake_post_callback

        result = await service.delete_documents_by_attachments(
            brand_code="BRAND-001",
            attachments=[
                {
                    "name": "品牌手册.pdf",
                    "url": "https://example.com/brand-book.pdf",
                }
            ],
        )

        self.assertEqual(0, result["summary"]["deleted_count"])
        self.assertEqual(1, result["summary"]["not_found_count"])
        self.assertEqual("not_found", result["results"][0]["status"])
        self.assertEqual(
            [
                {
                    "name": "招商手册.pdf",
                    "url": "https://example.com/investment.pdf",
                    "type": "pdf",
                    "description": "",
                }
            ],
            service._brand_knowledge.attachments,
        )
        self.assertEqual([1], service._brand_full_knowledge.calls)
        self.assertEqual(1, len(posted_payloads))
        callback_payload = posted_payloads[0]
        self.assertEqual("BRAND-001", callback_payload["brand_code"])
        self.assertEqual(
            [
                {
                    "name": "招商手册.pdf",
                    "url": "https://example.com/investment.pdf",
                    "type": "pdf",
                    "description": "",
                }
            ],
            callback_payload["knowledge"]["attachments"]["files"],
        )

    async def test_batch_delete_rejects_unknown_brand_code(self) -> None:
        service = KnowledgeBaseService.__new__(KnowledgeBaseService)
        service._brands = _FakeBrands()

        with self.assertRaisesRegex(ValueError, "brand_code 对应的品牌不存在"):
            await service.delete_documents_by_attachments(
                brand_code="404",
                attachments=[{"name": "理想汽车品牌概述.docx"}],
            )


async def _unexpected_delete(_document_id: str) -> bool:
    raise AssertionError("delete_document should not be called when attachment match is ambiguous")


if __name__ == "__main__":
    unittest.main()
