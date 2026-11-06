from __future__ import annotations

import hashlib
import types
import unittest
from unittest.mock import AsyncMock, patch

from knowledge_base.brand.application import BrandApplicationDependencies, BrandApplicationService
from knowledge_base.brand.schemas import KnowledgeBasicInfo, KnowledgeUpdateRequest

from tests.fakes.brand_flow import (
    FakeBrandKnowledgeStore,
    FakeBrandProductStore,
    FakeBrandStore,
    FakeDocumentCategoryStore,
    FakeDocumentRegistryStore,
    FakeIndustryStore,
    FakeSettings,
)
from tests.fakes.attachment_assets import (
    FakeAttachmentOSSClient,
    FakeAttachmentParser,
    FakeBrandAttachmentAssetStore,
    fake_temp_file_download,
)


def _build_application(
    *,
    brand_knowledge: FakeBrandKnowledgeStore,
    attachment_assets: FakeBrandAttachmentAssetStore,
    oss_client: FakeAttachmentOSSClient,
    ingest_from_url=None,
    delete_attachment=None,
    document_registry=None,
) -> BrandApplicationService:
    return BrandApplicationService(
        BrandApplicationDependencies(
            settings=FakeSettings(),
            brands=FakeBrandStore(),
            brand_products=FakeBrandProductStore(),
            brand_knowledge=brand_knowledge,
            industries=FakeIndustryStore(),
            brand_knowledge_sessions=types.SimpleNamespace(),
            document_registry=document_registry,
            document_categories=FakeDocumentCategoryStore(),
            fact_relations=None,
            store=None,
            document_app=None,
            delete_document=AsyncMock(),
            get_full_text=lambda _document_id: None,
            ingest_staged_file=AsyncMock(),
            ingest_from_url=ingest_from_url or AsyncMock(),
            delete_document_by_attachment_name=delete_attachment or AsyncMock(),
            brand_attachment_assets=attachment_assets,
            oss_client=oss_client,
            parser=FakeAttachmentParser(),
        )
    )


class BrandKnowledgeUpdateAttachmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_knowledge_update_syncs_added_attachments_without_removing_existing_assets(self) -> None:
        ingest_from_url = AsyncMock()
        delete_attachment = AsyncMock(return_value="doc-old-2")
        attachment_assets = FakeBrandAttachmentAssetStore()
        oss_client = FakeAttachmentOSSClient()
        brand_knowledge = FakeBrandKnowledgeStore()
        brand_knowledge.knowledge_rows = [
            {
                "knowledge_type": "attachments",
                "content_json": [
                    {"name": "保留附件.docx", "url": "https://example.com/keep.docx"},
                    {"name": "删除附件.docx", "url": "https://example.com/remove.docx"},
                ],
            }
        ]
        application = _build_application(
            brand_knowledge=brand_knowledge,
            attachment_assets=attachment_assets,
            oss_client=oss_client,
            ingest_from_url=ingest_from_url,
            delete_attachment=delete_attachment,
        )

        request = KnowledgeUpdateRequest(
            basic_info=KnowledgeBasicInfo(
                brand_name="示例品牌",
                brand_code="BRAND-001",
            ),
            attachments=[
                {"name": "保留附件.docx", "url": "https://example.com/keep.docx"},
                {"name": "新增附件A.docx", "url": "https://example.com/new-a.docx"},
                {"name": "新增附件B.docx", "url": "https://example.com/new-b.docx"},
            ],
        )

        download_stub, created_paths = await fake_temp_file_download(
            payloads=[
                (b"new-a-content", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                (b"new-b-content", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            ],
        )
        with patch(
            "knowledge_base.brand.application.service.download_remote_content_to_temp_file",
            new=AsyncMock(side_effect=download_stub),
        ):
            result = await application.update_knowledge(request)

        self.assertEqual(result["status"], "success")
        ingest_from_url.assert_not_awaited()
        delete_attachment.assert_not_awaited()
        self.assertEqual(len(attachment_assets.created_assets), 2)
        self.assertEqual(
            [item["original_filename"] for item in attachment_assets.created_assets],
            ["新增附件A.docx", "新增附件B.docx"],
        )
        self.assertEqual(attachment_assets.deleted_ids, [])
        self.assertEqual(oss_client.deleted_keys, [])
        self.assertEqual(len(oss_client.uploaded_objects), 2)
        self.assertTrue(all(not path.exists() for path in created_paths))
        attachments_upserts = [
            item for item in application._deps.brand_knowledge.last_knowledge_upserts
            if item[1] == "attachments"
        ]
        self.assertEqual(
            attachments_upserts[-1][3],
            [
                {"name": "保留附件.docx", "url": "https://example.com/keep.docx"},
                {"name": "新增附件A.docx", "url": "https://example.com/new-a.docx"},
                {"name": "新增附件B.docx", "url": "https://example.com/new-b.docx"},
            ],
        )

    async def test_knowledge_update_uses_url_identity_for_attachment_rename(self) -> None:
        attachment_assets = FakeBrandAttachmentAssetStore()
        oss_client = FakeAttachmentOSSClient()
        brand_knowledge = FakeBrandKnowledgeStore()
        brand_knowledge.knowledge_rows = [
            {
                "knowledge_type": "attachments",
                "content_json": [
                    {"name": "旧展示名.pdf", "url": "https://example.com/brand.pdf"},
                ],
            }
        ]
        application = _build_application(
            brand_knowledge=brand_knowledge,
            attachment_assets=attachment_assets,
            oss_client=oss_client,
        )

        request = KnowledgeUpdateRequest(
            basic_info=KnowledgeBasicInfo(
                brand_name="示例品牌",
                brand_code="BRAND-001",
            ),
            attachments=[
                {"name": "新展示名.pdf", "url": "https://example.com/brand.pdf"},
            ],
        )

        result = await application.update_knowledge(request)

        self.assertEqual(result["status"], "success")
        self.assertEqual(attachment_assets.created_assets, [])
        self.assertEqual(oss_client.uploaded_objects, [])
        attachments_upserts = [
            item for item in application._deps.brand_knowledge.last_knowledge_upserts
            if item[1] == "attachments"
        ]
        self.assertEqual(
            attachments_upserts[-1][3],
            [{"name": "新展示名.pdf", "url": "https://example.com/brand.pdf"}],
        )

    async def test_knowledge_update_clears_attachments_when_empty_list_is_provided(self) -> None:
        delete_attachment = AsyncMock(return_value="doc-old-1")
        attachment_assets = FakeBrandAttachmentAssetStore()
        attachment_assets.rows = [
            {
                "id": 1,
                "brand_code": "BRAND-001",
                "brand_name": "示例品牌",
                "original_filename": "旧附件A.docx",
                "source_url": "https://example.com/old-a.docx",
                "oss_key": "示例品牌/original/旧附件A.docx/V1.docx",
                "fulltext_key": "示例品牌/converted/旧附件A.docx/V1.md",
                "file_hash": "old-a-hash",
                "converted_version": 1,
            },
            {
                "id": 2,
                "brand_code": "BRAND-001",
                "brand_name": "示例品牌",
                "original_filename": "旧附件B.docx",
                "source_url": "https://example.com/old-b.docx",
                "oss_key": "示例品牌/original/旧附件B.docx/V1.docx",
                "fulltext_key": "示例品牌/converted/旧附件B.docx/V1.md",
                "file_hash": "old-b-hash",
                "converted_version": 1,
            },
        ]
        brand_knowledge = FakeBrandKnowledgeStore()
        brand_knowledge.knowledge_rows = [
            {
                "knowledge_type": "attachments",
                "content_json": [
                    {"name": "旧附件A.docx", "url": "https://example.com/old-a.docx"},
                    {"name": "旧附件B.docx", "url": "https://example.com/old-b.docx"},
                ],
            }
        ]
        application = _build_application(
            brand_knowledge=brand_knowledge,
            attachment_assets=attachment_assets,
            oss_client=FakeAttachmentOSSClient(),
            delete_attachment=delete_attachment,
        )

        request = KnowledgeUpdateRequest(
            basic_info=KnowledgeBasicInfo(
                brand_name="示例品牌",
                brand_code="BRAND-001",
            ),
            attachments=[],
        )

        result = await application.update_knowledge(request)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["knowledge_revision"], "demo-2026-06-23")
        delete_attachment.assert_not_awaited()
        self.assertEqual(len(application._deps.brand_attachment_assets.deleted_ids), 0)
        attachments_upserts = [
            item for item in application._deps.brand_knowledge.last_knowledge_upserts
            if item[1] == "attachments"
        ]
        self.assertEqual(attachments_upserts[-1][3], [])

    async def test_knowledge_update_reuses_existing_attachment_document_when_registry_already_has_it(self) -> None:
        ingest_from_url = AsyncMock()
        attachment_assets = FakeBrandAttachmentAssetStore()
        attachment_assets.rows = [
            {
                "id": 1,
                "brand_code": "BRAND-001",
                "brand_name": "示例品牌",
                "original_filename": "理想汽车品牌概述.docx",
                "source_url": "https://example.com/brand-overview.docx",
                "oss_key": "示例品牌/original/理想汽车品牌概述.docx/V1.docx",
                "fulltext_key": "示例品牌/converted/理想汽车品牌概述.docx/V1.md",
                "file_hash": hashlib.sha256(b"existing-content").hexdigest(),
                "converted_version": 1,
            }
        ]
        document_registry = FakeDocumentRegistryStore()
        document_registry.latest_success_documents_by_filename[
            ("理想汽车品牌概述.docx", "示例品牌", "https://example.com/brand-overview.docx")
        ] = [
            {
                "document_id": "doc-existing-1",
                "category": "示例品牌",
                "original_filename": "理想汽车品牌概述.docx",
                "source_url": "https://example.com/brand-overview.docx",
                "status": "success",
                "is_latest": 1,
            }
        ]
        brand_knowledge = FakeBrandKnowledgeStore()
        application = _build_application(
            brand_knowledge=brand_knowledge,
            attachment_assets=attachment_assets,
            oss_client=FakeAttachmentOSSClient(),
            ingest_from_url=ingest_from_url,
            document_registry=document_registry,
        )

        request = KnowledgeUpdateRequest(
            basic_info=KnowledgeBasicInfo(
                brand_name="示例品牌",
                brand_code="BRAND-001",
            ),
            attachments=[
                {"name": "理想汽车品牌概述.docx", "url": "https://example.com/brand-overview.docx"},
            ],
        )

        download_stub, created_paths = await fake_temp_file_download(
            payloads=[
                (b"existing-content", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            ],
        )
        with patch(
            "knowledge_base.brand.application.service.download_remote_content_to_temp_file",
            new=AsyncMock(side_effect=download_stub),
        ):
            result = await application.update_knowledge(request)

        self.assertEqual(result["status"], "success")
        ingest_from_url.assert_not_awaited()
        self.assertEqual(len(attachment_assets.created_assets), 0)
        self.assertTrue(all(not path.exists() for path in created_paths))
        attachments_upserts = [
            item for item in application._deps.brand_knowledge.last_knowledge_upserts
            if item[1] == "attachments"
        ]
        self.assertEqual(
            attachments_upserts[-1][3],
            [
                {"name": "理想汽车品牌概述.docx", "url": "https://example.com/brand-overview.docx"},
            ],
        )

    async def test_knowledge_update_skips_duplicate_attachment_ingest_and_still_updates_attachments(self) -> None:
        ingest_from_url = AsyncMock()
        attachment_assets = FakeBrandAttachmentAssetStore()
        attachment_assets.rows = [
            {
                "id": 1,
                "brand_code": "BRAND-001",
                "brand_name": "示例品牌",
                "original_filename": "金牌家居品牌知识库（v1版本）.pdf",
                "source_url": "https://example.com/goldenhome-v1.pdf",
                "oss_key": "示例品牌/original/金牌家居品牌知识库（v1版本）.pdf/V1.pdf",
                "fulltext_key": "示例品牌/converted/金牌家居品牌知识库（v1版本）.pdf/V1.md",
                "file_hash": hashlib.sha256(b"duplicate-content").hexdigest(),
                "converted_version": 1,
            }
        ]
        brand_knowledge = FakeBrandKnowledgeStore()
        application = _build_application(
            brand_knowledge=brand_knowledge,
            attachment_assets=attachment_assets,
            oss_client=FakeAttachmentOSSClient(),
            ingest_from_url=ingest_from_url,
            document_registry=FakeDocumentRegistryStore(),
        )

        request = KnowledgeUpdateRequest(
            basic_info=KnowledgeBasicInfo(
                brand_name="示例品牌",
                brand_code="BRAND-001",
            ),
            attachments=[
                {
                    "name": "金牌家居品牌知识库（v1版本）.pdf",
                    "url": "https://example.com/goldenhome-v1.pdf",
                },
            ],
        )

        download_stub, created_paths = await fake_temp_file_download(
            payloads=[
                (b"duplicate-content", "application/pdf"),
            ],
        )
        with patch(
            "knowledge_base.brand.application.service.download_remote_content_to_temp_file",
            new=AsyncMock(side_effect=download_stub),
        ):
            result = await application.update_knowledge(request)

        self.assertEqual(result["status"], "success")
        ingest_from_url.assert_not_awaited()
        self.assertEqual(len(attachment_assets.created_assets), 0)
        self.assertTrue(all(not path.exists() for path in created_paths))
        attachments_upserts = [
            item for item in application._deps.brand_knowledge.last_knowledge_upserts
            if item[1] == "attachments"
        ]
        self.assertEqual(
            attachments_upserts[-1][3],
            [
                {
                    "name": "金牌家居品牌知识库（v1版本）.pdf",
                    "url": "https://example.com/goldenhome-v1.pdf",
                },
            ],
        )
