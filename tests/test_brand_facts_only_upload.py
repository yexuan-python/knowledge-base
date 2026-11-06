from __future__ import annotations

import io
import unittest
from pathlib import Path

from knowledge_base.brand.application.facts_only_upload import (
    BrandFactsOnlyUploadDependencies,
    BrandFactsOnlyUploadService,
)


class _FakeUpload:
    def __init__(self, content: bytes, *, filename: str = "facts.md", content_type: str = "text/markdown") -> None:
        self.filename = filename
        self.content_type = content_type
        self._buffer = io.BytesIO(content)

    async def seek(self, offset: int) -> None:
        self._buffer.seek(offset)

    async def read(self, size: int = -1) -> bytes:
        return self._buffer.read(size)


class _FakeUploadTaskApplication:
    def __init__(self) -> None:
        self.validated_metadata: list[dict] = []

    def _validate_documents_upload_metadata(self, metadata: dict) -> None:
        self.validated_metadata.append(dict(metadata))

    def _resolve_metadata_brand_name(self, metadata: dict) -> str | None:
        return str(metadata.get("brand_name") or metadata.get("category") or "").strip() or None


class _FakeBrandAiKnowledgeIngestion:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def ingest_facts_only_upload(self, **kwargs):
        staged_path = kwargs["staged_path"]
        self.calls.append(
            {
                **kwargs,
                "staged_text": Path(staged_path).read_text(encoding="utf-8"),
                "exists_during_call": Path(staged_path).exists(),
            }
        )
        return {
            "brand_code": kwargs["brand_code"],
            "brand_name": kwargs["brand_name"],
            "document_id": "brandfacts:BRAND-001:abc123",
            "fact_count": 2,
            "deleted_fact_count": 1,
        }


class BrandFactsOnlyUploadServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_ingests_single_file_and_cleans_temp_file(self) -> None:
        upload_tasks = _FakeUploadTaskApplication()
        ingestion = _FakeBrandAiKnowledgeIngestion()
        service = BrandFactsOnlyUploadService(
            BrandFactsOnlyUploadDependencies(
                upload_task_application=upload_tasks,
                brand_ai_knowledge_ingestion=ingestion,
            )
        )

        result = await service.ingest_brand_facts_only(
            files=[_FakeUpload(b"# facts\n")],
            metadata={
                "brand_code": "BRAND-001",
                "brand_name": "示例品牌",
                "category": "示例品牌",
            },
        )

        self.assertEqual(result["document_id"], "brandfacts:BRAND-001:abc123")
        self.assertEqual(upload_tasks.validated_metadata[0]["brand_code"], "BRAND-001")
        self.assertEqual(len(ingestion.calls), 1)
        call = ingestion.calls[0]
        self.assertRegex(call["task_id"], r"^brand-facts-only:BRAND-001:")
        self.assertEqual(call["filename"], "facts.md")
        self.assertEqual(call["brand_code"], "BRAND-001")
        self.assertEqual(call["brand_name"], "示例品牌")
        self.assertEqual(call["content_type"], "text/markdown")
        self.assertEqual(call["source_url"], None)
        self.assertEqual(call["staged_text"], "# facts\n")
        self.assertTrue(call["exists_during_call"])
        self.assertFalse(Path(call["staged_path"]).exists())

    async def test_rejects_multiple_files(self) -> None:
        service = BrandFactsOnlyUploadService(
            BrandFactsOnlyUploadDependencies(
                upload_task_application=_FakeUploadTaskApplication(),
                brand_ai_knowledge_ingestion=_FakeBrandAiKnowledgeIngestion(),
            )
        )

        with self.assertRaisesRegex(ValueError, "facts-only 上传当前仅支持单文件"):
            await service.ingest_brand_facts_only(
                files=[_FakeUpload(b"a"), _FakeUpload(b"b")],
                metadata={
                    "brand_code": "BRAND-001",
                    "brand_name": "示例品牌",
                    "category": "示例品牌",
                },
            )
