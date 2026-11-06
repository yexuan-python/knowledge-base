from __future__ import annotations

import unittest

from knowledge_base.service import KnowledgeBaseService
from knowledge_base.upload_task.schemas import UploadTaskCreateResponse


class _FakeUploadTaskApplication:
    def __init__(self) -> None:
        self.brand_ai_knowledge_url_calls: list[dict] = []

    async def enqueue_brand_ai_knowledge_url_task(self, **kwargs) -> UploadTaskCreateResponse:
        self.brand_ai_knowledge_url_calls.append(dict(kwargs))
        return UploadTaskCreateResponse(
            task_id="task-official-kb",
            status="queued",
            file_count=1,
            message="queued",
        )


class _FakeDraftApplication:
    def __init__(self) -> None:
        self.preview_parse_calls: list[dict] = []

    async def preview_parse(self, **kwargs) -> dict:
        self.preview_parse_calls.append(dict(kwargs))
        return {
            "draft_id": "bad_123",
            "brand_name": kwargs["brand_name"],
            "candidate_snapshot": {},
            "field_labels": {},
            "knowledge_revision": "rev-1",
        }


class _FakeBrandStore:
    def __init__(self, brand: dict | None = None) -> None:
        self.brand = brand

    def get_brand_by_name(self, brand_name: str):
        if self.brand and self.brand.get("brand_name") == brand_name:
            return dict(self.brand)
        return None


class AttachmentPreviewOfficialUploadTests(unittest.IsolatedAsyncioTestCase):
    async def test_preview_parse_routes_official_ai_knowledge_file_to_upload_task(self) -> None:
        service = KnowledgeBaseService.__new__(KnowledgeBaseService)
        upload_task_app = _FakeUploadTaskApplication()
        draft_app = _FakeDraftApplication()
        service._upload_task_app = upload_task_app
        service._brand_knowledge_attachment_draft_app = draft_app
        service._brands = _FakeBrandStore()

        result = await service.preview_parse_brand_attachments(
            brand_name="燕之屋",
            brand_code="100209",
            attachments=[
                {
                    "name": "【燕之屋】品牌AI知识库_V3_20260918.md",
                    "url": "https://example.com/kb.md",
                }
            ],
        )

        self.assertEqual(result, {"brand_name": "燕之屋", "status": "true"})
        self.assertEqual([], draft_app.preview_parse_calls)
        self.assertEqual(
            [
                {
                    "filename": "【燕之屋】品牌AI知识库_V3_20260918.md",
                    "source_url": "https://example.com/kb.md",
                    "brand_code": "100209",
                    "brand_name": "燕之屋",
                    "force_reingest": False,
                }
            ],
            upload_task_app.brand_ai_knowledge_url_calls,
        )

    async def test_preview_parse_resolves_brand_code_for_official_ai_knowledge_file(self) -> None:
        service = KnowledgeBaseService.__new__(KnowledgeBaseService)
        upload_task_app = _FakeUploadTaskApplication()
        service._upload_task_app = upload_task_app
        service._brand_knowledge_attachment_draft_app = _FakeDraftApplication()
        service._brands = _FakeBrandStore({"brand_code": "100888", "brand_name": "燕之屋"})

        result = await service.preview_parse_brand_attachments(
            brand_name="任意前端品牌名",
            brand_code=None,
            attachments=[
                {
                    "name": "【燕之屋】品牌AI知识库_V3_20260918.md",
                    "url": "https://example.com/kb.md",
                }
            ],
        )

        self.assertEqual(result, {"brand_name": "燕之屋", "status": "true"})
        self.assertEqual(upload_task_app.brand_ai_knowledge_url_calls[0]["brand_code"], "100888")

    async def test_preview_parse_keeps_normal_attachments_on_existing_flow(self) -> None:
        service = KnowledgeBaseService.__new__(KnowledgeBaseService)
        draft_app = _FakeDraftApplication()
        service._brand_knowledge_attachment_draft_app = draft_app

        result = await service.preview_parse_brand_attachments(
            brand_name="示例品牌",
            brand_code="BRAND-001",
            attachments=[
                {
                    "name": "品牌手册.pdf",
                    "url": "https://example.com/manual.pdf",
                }
            ],
        )

        self.assertEqual(result["draft_id"], "bad_123")
        self.assertEqual(
            [
                {
                    "brand_name": "示例品牌",
                    "brand_code": "BRAND-001",
                    "attachments": [
                        {
                            "name": "品牌手册.pdf",
                            "url": "https://example.com/manual.pdf",
                        }
                    ],
                }
            ],
            draft_app.preview_parse_calls,
        )

