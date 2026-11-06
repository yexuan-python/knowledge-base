from __future__ import annotations

import os
import types
import unittest
from unittest.mock import AsyncMock, patch

from knowledge_base.brand.application import BrandApplicationDependencies, BrandApplicationService

from tests.fakes.brand_flow import (
    FakeBrandFullKnowledgeStore,
    FakeBrandKnowledgeStore,
    FakeBrandProductStore,
    FakeBrandStore,
    FakeDocumentCategoryStore,
    FakeDocumentRegistryStore,
    FakeIndustryStore,
    FakeMilvusRenameStore,
    FakeSettings,
    FakeUploadTaskStore,
    OperationalError,
)
from tests.fakes.delete_flow import (
    FakeDeleteAttachmentAssets,
    FakeDeleteBackgroundJobs,
    FakeDeleteBrandFactsStore,
    FakeDeleteBrandKnowledgeIngestionJobs,
    FakeDeleteBrandKnowledgeSessions,
    FakeDeleteDocumentApp,
    FakeDeleteFactRelations,
    FakeDeleteOSSClient,
    FakeDeleteVectorStore,
)


class BrandDeleteRenameFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_delete_brand_dry_run_counts_full_knowledge_and_brand_artifacts(self) -> None:
        brand_full_knowledge = FakeBrandFullKnowledgeStore()
        brand_full_knowledge.rows = [
            {
                "id": 1,
                "brand_id": 1,
                "brand_code": "BRAND-001",
                "brand_name": "示例品牌",
                "version_no": 1,
                "oss_key": "test/示例品牌/ai_knowledge/demo.md",
                "pdf_oss_key": "test/示例品牌/ai_knowledge/demo.pdf",
                "document_id": "brandkb:BRAND-001:V1:20260716:R1",
            }
        ]
        oss_client = FakeDeleteOSSClient(
            [
                "test/示例品牌/ai_knowledge/demo.md",
                "test/示例品牌/ai_knowledge/demo.pdf",
                "test/示例品牌/ai_knowledge/extra.md",
                "示例品牌/ai_knowledge/live.md",
                "test/示例品牌/confirmed_knowledge/示例品牌-confirmed-knowledge.md",
                "示例品牌/confirmed_knowledge/live-confirmed.md",
                "test/BRAND-001/attachments/doc.pdf/abc123.pdf",
                "test/BRAND-001/attachments/doc.pdf/V1.md",
            ]
        )
        document_registry = FakeDocumentRegistryStore()
        document_registry.entries_by_category["示例品牌"] = [
            {"document_id": "doc-1", "original_file_key": "test/示例品牌/original/doc.pdf"}
        ]
        attachment_assets = FakeDeleteAttachmentAssets()
        session_store = FakeDeleteBrandKnowledgeSessions()
        upload_tasks = FakeUploadTaskStore()
        vector_store = FakeDeleteVectorStore()
        brand_facts_store = FakeDeleteBrandFactsStore()
        ingestion_jobs = FakeDeleteBrandKnowledgeIngestionJobs()
        background_jobs = FakeDeleteBackgroundJobs()
        application = BrandApplicationService(
            BrandApplicationDependencies(
                settings=FakeSettings(),
                brands=FakeBrandStore(),
                brand_products=FakeBrandProductStore(),
                brand_knowledge=FakeBrandKnowledgeStore(),
                brand_full_knowledge=brand_full_knowledge,
                industries=FakeIndustryStore(),
                brand_knowledge_sessions=session_store,
                document_registry=document_registry,
                document_categories=FakeDocumentCategoryStore(),
                fact_relations=FakeDeleteFactRelations(),
                store=vector_store,
                document_app=FakeDeleteDocumentApp(),
                upload_tasks=upload_tasks,
                brand_attachment_assets=attachment_assets,
                brand_knowledge_facts=brand_facts_store,
                brand_knowledge_ingestion_jobs=ingestion_jobs,
                delete_document=AsyncMock(),
                get_full_text=lambda _document_id: None,
                ingest_staged_file=AsyncMock(),
                oss_client=oss_client,
                background_jobs=background_jobs,
            )
        )

        with patch.dict(os.environ, {"OSS_OBJECT_KEY_PREFIX": ""}):
            result = await application.delete_brand(brand_name="示例品牌", dry_run=False)

        self.assertFalse(result["executed"])
        self.assertEqual(result["counts"]["brand_full_knowledge_files"], 1)
        self.assertEqual(result["counts"]["brand_attachment_assets"], 1)
        self.assertEqual(result["counts"]["brand_knowledge_sessions"], 2)
        self.assertEqual(result["counts"]["brand_knowledge_session_rounds"], 3)
        self.assertEqual(result["counts"]["brand_knowledge_facts"], 2)
        self.assertEqual(result["counts"]["brand_knowledge_ingestion_jobs"], 2)
        self.assertEqual(result["counts"]["background_jobs"], 3)
        self.assertEqual(result["counts"]["upload_tasks"], 1)
        self.assertEqual(result["counts"]["upload_task_files"], 2)
        self.assertEqual(result["counts"]["upload_task_callbacks"], 1)
        self.assertEqual(result["counts"]["ai_knowledge_oss_objects"], 1)
        self.assertEqual(result["counts"]["confirmed_knowledge_oss_objects"], 1)
        self.assertEqual(result["counts"]["oss_objects"], 3)
        self.assertEqual(oss_client.deleted_keys, [])
        self.assertEqual(brand_full_knowledge.deleted_brand_ids, [])
        self.assertEqual(vector_store.deleted_brand_fact_codes, [])

    async def test_delete_brand_deletes_artifacts_before_brand_records(self) -> None:
        brand_store = FakeBrandStore()
        brand_products = FakeBrandProductStore()
        brand_knowledge = FakeBrandKnowledgeStore()
        brand_full_knowledge = FakeBrandFullKnowledgeStore()
        brand_full_knowledge.rows = [
            {
                "id": 1,
                "brand_id": 1,
                "brand_code": "BRAND-001",
                "brand_name": "示例品牌",
                "version_no": 1,
                "oss_key": "test/示例品牌/ai_knowledge/demo.md",
                "pdf_oss_key": "test/示例品牌/ai_knowledge/demo.pdf",
                "document_id": "brandkb:BRAND-001:V1:20260716:R1",
            }
        ]
        oss_client = FakeDeleteOSSClient(
            [
                "test/示例品牌/ai_knowledge/demo.md",
                "test/示例品牌/ai_knowledge/demo.pdf",
                "test/示例品牌/ai_knowledge/extra.md",
                "test/示例品牌/confirmed_knowledge/示例品牌-confirmed-knowledge.md",
                "示例品牌/ai_knowledge/live.md",
                "示例品牌/confirmed_knowledge/live-confirmed.md",
                "test/BRAND-001/attachments/doc.pdf/abc123.pdf",
                "test/BRAND-001/attachments/doc.pdf/V1.md",
            ]
        )
        document_registry = FakeDocumentRegistryStore()
        document_registry.entries_by_category["示例品牌"] = [
            {"document_id": "doc-1", "original_file_key": "test/示例品牌/original/doc.pdf"}
        ]
        delete_document = AsyncMock()
        attachment_assets = FakeDeleteAttachmentAssets()
        session_store = FakeDeleteBrandKnowledgeSessions()
        upload_tasks = FakeUploadTaskStore()
        vector_store = FakeDeleteVectorStore()
        brand_facts_store = FakeDeleteBrandFactsStore()
        ingestion_jobs = FakeDeleteBrandKnowledgeIngestionJobs()
        background_jobs = FakeDeleteBackgroundJobs()
        application = BrandApplicationService(
            BrandApplicationDependencies(
                settings=FakeSettings(),
                brands=brand_store,
                brand_products=brand_products,
                brand_knowledge=brand_knowledge,
                brand_full_knowledge=brand_full_knowledge,
                industries=FakeIndustryStore(),
                brand_knowledge_sessions=session_store,
                document_registry=document_registry,
                document_categories=FakeDocumentCategoryStore(),
                fact_relations=FakeDeleteFactRelations(),
                store=vector_store,
                document_app=FakeDeleteDocumentApp(),
                upload_tasks=upload_tasks,
                brand_attachment_assets=attachment_assets,
                brand_knowledge_facts=brand_facts_store,
                brand_knowledge_ingestion_jobs=ingestion_jobs,
                delete_document=delete_document,
                get_full_text=lambda _document_id: None,
                ingest_staged_file=AsyncMock(),
                oss_client=oss_client,
                background_jobs=background_jobs,
            )
        )

        with patch.dict(os.environ, {"OSS_OBJECT_KEY_PREFIX": "test"}):
            result = await application.delete_brand(brand_name="示例品牌", dry_run=True)

        self.assertTrue(result["executed"])
        self.assertEqual(
            delete_document.await_args_list,
            [
                unittest.mock.call(
                    "brandkb:BRAND-001:V1:20260716:R1",
                    oss_object_key_filter=unittest.mock.ANY,
                ),
                unittest.mock.call(
                    "doc-1",
                    oss_object_key_filter=unittest.mock.ANY,
                ),
            ],
        )
        self.assertEqual(
            oss_client.deleted_keys,
            [
                "test/BRAND-001/attachments/doc.pdf/V1.md",
                "test/BRAND-001/attachments/doc.pdf/abc123.pdf",
                "test/示例品牌/ai_knowledge/demo.md",
                "test/示例品牌/ai_knowledge/demo.pdf",
                "test/示例品牌/ai_knowledge/extra.md",
                "test/示例品牌/confirmed_knowledge/示例品牌-confirmed-knowledge.md",
            ],
        )
        self.assertEqual(brand_full_knowledge.deleted_brand_ids, [1])
        self.assertEqual(brand_full_knowledge.rows, [])
        self.assertEqual(brand_knowledge.deleted_brand_ids, [1])
        self.assertEqual(brand_products.deleted_brand_ids, [1])
        self.assertEqual(brand_store.deleted_brand_ids, [1])
        self.assertEqual(session_store.deleted_calls, [{"brand_code": "BRAND-001", "brand_name": "示例品牌"}])
        self.assertEqual(attachment_assets.deleted_brand_codes, ["BRAND-001"])
        self.assertEqual(ingestion_jobs.deleted_brand_codes, ["BRAND-001"])
        self.assertEqual(
            upload_tasks.deleted_brand_identifier_calls,
            [{"brand_code": "BRAND-001", "brand_name": "示例品牌"}],
        )
        self.assertEqual(
            background_jobs.deleted_calls,
            [
                {
                    "brand_code": "BRAND-001",
                    "brand_name": "示例品牌",
                    "source_ids": ["task-brand-1"],
                }
            ],
        )
        self.assertEqual(brand_facts_store.deleted_brand_codes, ["BRAND-001"])
        self.assertEqual(vector_store.deleted_brand_fact_codes, ["BRAND-001"])

    async def test_rename_brand_invalidates_document_category_and_path_caches(self) -> None:
        brand_store = FakeBrandStore()
        brand_store.rename_result = {
            "brand_id": 1,
            "brand_code": "BRAND-001",
            "old_brand_name": "示例品牌",
            "brand_name": "珠海示例品牌",
            "counts": {
                "brands": 1,
                "brand_products": 2,
                "brand_full_knowledge_files": 1,
                "brand_knowledge_facts": 1,
                "brand_attachment_assets": 1,
                "brand_knowledge_ingestion_jobs": 1,
                "brand_knowledge_sessions": 1,
                "document_registry": 3,
                "document_categories": 3,
                "background_jobs": 1,
                "upload_tasks": 1,
            },
            "updated_tables": [
                "brands",
                "brand_products",
                "document_registry",
                "document_categories",
            ],
        }
        document_categories = FakeDocumentCategoryStore()
        application = BrandApplicationService(
            BrandApplicationDependencies(
                settings=FakeSettings(),
                brands=brand_store,
                brand_products=FakeBrandProductStore(),
                brand_knowledge=FakeBrandKnowledgeStore(),
                industries=FakeIndustryStore(),
                brand_knowledge_sessions=types.SimpleNamespace(),
                document_registry=FakeDocumentRegistryStore(),
                document_categories=document_categories,
                fact_relations=None,
                store=FakeMilvusRenameStore(),
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
        application._brand_paths_load_cache[("BRAND-001", "rev-1", "品牌基础信息/品牌介绍")] = (1e9, 1e9, {"title": "x"})
        application._path_index_summary_cache[("BRAND-001", "rev-1", "品牌基础信息/品牌介绍")] = (1e9, 1e9, "summary")

        result = application.rename_brand(
            brand_code="BRAND-001",
            new_brand_name="珠海示例品牌",
        )

        self.assertIsNotNone(result)
        self.assertEqual(
            brand_store.rename_calls,
            [
                {
                    "brand_code": "BRAND-001",
                    "new_brand_name": "珠海示例品牌",
                }
            ],
        )
        self.assertEqual(
            brand_store.rename_job_calls,
            [
                {
                    "brand_code": "BRAND-001",
                    "old_brand_name": "示例品牌",
                    "new_brand_name": "珠海示例品牌",
                    "background_job": {
                        "job_id": "bg:brand_rename_milvus_sync:BRAND-001:珠海示例品牌",
                        "job_type": "brand_rename_milvus_sync",
                        "source_type": "brand_rename",
                        "source_id": "BRAND-001:珠海示例品牌",
                        "status": "waiting",
                    },
                }
            ],
        )
        self.assertEqual(document_categories.invalidated_categories, [None])
        self.assertEqual(application._brand_paths_load_cache, {})
        self.assertEqual(application._path_index_summary_cache, {})

    async def test_rename_brand_retries_mysql_before_success(self) -> None:
        brand_store = FakeBrandStore()
        brand_store.rename_errors = [OperationalError(1213, "Deadlock found when trying to get lock")]
        document_categories = FakeDocumentCategoryStore()
        application = BrandApplicationService(
            BrandApplicationDependencies(
                settings=FakeSettings(),
                brands=brand_store,
                brand_products=FakeBrandProductStore(),
                brand_knowledge=FakeBrandKnowledgeStore(),
                industries=FakeIndustryStore(),
                brand_knowledge_sessions=types.SimpleNamespace(),
                document_registry=None,
                document_categories=document_categories,
                fact_relations=None,
                store=FakeMilvusRenameStore(),
                document_app=None,
                delete_document=AsyncMock(),
                get_full_text=lambda _document_id: None,
                ingest_staged_file=AsyncMock(),
            )
        )

        result = application.rename_brand(
            brand_code="BRAND-001",
            new_brand_name="珠海示例品牌",
        )

        self.assertEqual(
            result["background_job_id"],
            "bg:brand_rename_milvus_sync:BRAND-001:珠海示例品牌",
        )
        self.assertEqual(
            brand_store.rename_calls,
            [
                {
                    "brand_code": "BRAND-001",
                    "new_brand_name": "珠海示例品牌",
                },
                {
                    "brand_code": "BRAND-001",
                    "new_brand_name": "珠海示例品牌",
                }
            ],
        )
        self.assertEqual(
            brand_store.rename_job_calls,
            [
                {
                    "brand_code": "BRAND-001",
                    "old_brand_name": "示例品牌",
                    "new_brand_name": "珠海示例品牌",
                    "background_job": {
                        "job_id": "bg:brand_rename_milvus_sync:BRAND-001:珠海示例品牌",
                        "job_type": "brand_rename_milvus_sync",
                        "source_type": "brand_rename",
                        "source_id": "BRAND-001:珠海示例品牌",
                        "status": "waiting",
                    },
                },
            ],
        )
        self.assertEqual(brand_store._brand_row["brand_name"], "珠海示例品牌")
        self.assertEqual(document_categories.invalidated_categories, [None])

    async def test_rename_brand_returns_real_background_job_status(self) -> None:
        brand_store = FakeBrandStore()
        brand_store.rename_result = {
            "brand_id": 1,
            "brand_code": "BRAND-001",
            "old_brand_name": "示例品牌",
            "brand_name": "珠海示例品牌",
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
            "background_job": {
                "job_id": "bg:brand_rename_milvus_sync:BRAND-001:珠海示例品牌",
                "job_type": "brand_rename_milvus_sync",
                "source_type": "brand_rename",
                "source_id": "BRAND-001:珠海示例品牌",
                "status": "success",
            },
        }
        document_categories = FakeDocumentCategoryStore()
        application = BrandApplicationService(
            BrandApplicationDependencies(
                settings=FakeSettings(),
                brands=brand_store,
                brand_products=FakeBrandProductStore(),
                brand_knowledge=FakeBrandKnowledgeStore(),
                industries=FakeIndustryStore(),
                brand_knowledge_sessions=types.SimpleNamespace(),
                document_registry=None,
                document_categories=document_categories,
                fact_relations=None,
                store=FakeMilvusRenameStore(),
                document_app=None,
                delete_document=AsyncMock(),
                get_full_text=lambda _document_id: None,
                ingest_staged_file=AsyncMock(),
            )
        )

        result = application.rename_brand(
            brand_code="BRAND-001",
            new_brand_name="珠海示例品牌",
        )

        self.assertEqual(result["background_job_id"], "bg:brand_rename_milvus_sync:BRAND-001:珠海示例品牌")
        self.assertEqual(result["background_job_status"], "success")

    async def test_rename_brand_does_not_retry_on_non_mysql_runtime_error(self) -> None:
        brand_store = FakeBrandStore()
        brand_store.rename_errors = [RuntimeError("unexpected failure")]
        document_categories = FakeDocumentCategoryStore()
        application = BrandApplicationService(
            BrandApplicationDependencies(
                settings=FakeSettings(),
                brands=brand_store,
                brand_products=FakeBrandProductStore(),
                brand_knowledge=FakeBrandKnowledgeStore(),
                industries=FakeIndustryStore(),
                brand_knowledge_sessions=types.SimpleNamespace(),
                document_registry=None,
                document_categories=document_categories,
                fact_relations=None,
                store=FakeMilvusRenameStore(),
                document_app=None,
                delete_document=AsyncMock(),
                get_full_text=lambda _document_id: None,
                ingest_staged_file=AsyncMock(),
            )
        )

        with self.assertRaisesRegex(RuntimeError, "unexpected failure"):
            application.rename_brand(
                brand_code="BRAND-001",
                new_brand_name="珠海示例品牌",
            )

        self.assertEqual(
            brand_store.rename_calls,
            [
                {
                    "brand_code": "BRAND-001",
                    "new_brand_name": "珠海示例品牌",
                }
            ],
        )
        self.assertEqual(brand_store.rename_job_calls, [])
        self.assertEqual(document_categories.invalidated_categories, [])
