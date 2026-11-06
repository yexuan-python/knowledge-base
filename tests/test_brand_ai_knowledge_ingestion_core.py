from __future__ import annotations

from tests.fakes.brand_ai_ingestion import *


class BrandAiKnowledgeIngestionCoreTests(unittest.IsolatedAsyncioTestCase):
    def test_uploaded_markdown_normalization_preserves_unit_glyphs(self) -> None:
        markdown_text = "面积 20㎡\r\n浓度 0.025mg/m³ \r\n型号 ISO₉₀₀₁\r\n"

        normalized = BrandAiKnowledgeIngestionService._normalize_uploaded_markdown_text(markdown_text)

        self.assertEqual("面积 20㎡\n浓度 0.025mg/m³\n型号 ISO₉₀₀₁", normalized)

    def test_generic_markdown_normalization_keeps_nfkc_for_non_md_sources(self) -> None:
        markdown_text = "面积 20㎡\r\n浓度 0.025mg/m³ \r\n型号 ISO₉₀₀₁\r\n"

        normalized = BrandAiKnowledgeIngestionService._normalize_markdown_text(markdown_text)

        self.assertEqual("面积 20m2\n浓度 0.025mg/m3\n型号 ISO9001", normalized)

    async def test_ingest_facts_only_upload_upserts_new_facts_then_cleans_old_facts(self) -> None:
        facts_store = _FakeFactsStore()
        facts_store.rows = [
            {
                "brand_code": "BRAND-001",
                "fact_id": "fact-old",
                "source_document_id": "brandfacts:BRAND-001:legacy",
            }
        ]
        vector_store = _FakeVectorStore()
        service = BrandAiKnowledgeIngestionService(
            BrandAiKnowledgeIngestionDependencies(
                settings=types.SimpleNamespace(chunk_size=200, chunk_overlap=20),
                brands=_FakeBrands(),
                parser=_FakeParser("# 示例品牌"),
                embeddings=_FakeEmbeddings(),
                store=vector_store,
                oss_client=_FakeOssClient(),
                brand_full_knowledge=_FakeBrandFullKnowledgeStore(),
                brand_knowledge_facts=facts_store,
                brand_knowledge_ingestion_jobs=_FakeJobStore(),
            )
        )

        async def _fake_build_fact_rows(**kwargs):
            return [
                {
                    "brand_code": "BRAND-001",
                    "brand_name": "示例品牌",
                    "fact_scope": "official_kb",
                    "fact_id": "fact-new",
                    "fact_text": "示例品牌是一家测试品牌",
                    "normalized_fact_hash": "fact-new",
                    "source_document_id": kwargs["source_document_id"],
                    "source_task_id": None,
                    "source_asset_id": None,
                    "full_knowledge_file_id": None,
                    "version_no": None,
                    "knowledge_date": None,
                    "section_path": None,
                }
            ]

        service._build_fact_rows = _fake_build_fact_rows

        with tempfile.NamedTemporaryFile(delete=False, suffix=".md") as tmp:
            tmp.write("# 示例品牌".encode("utf-8"))
            staged_path = Path(tmp.name)

        try:
            result = await service.ingest_facts_only_upload(
                task_id="facts-only-task-1",
                filename="facts.md",
                brand_code="BRAND-001",
                brand_name="示例品牌",
                staged_path=staged_path,
                source_url=None,
                content_type="text/markdown",
            )
        finally:
            staged_path.unlink(missing_ok=True)

        self.assertEqual("success", result["status"])
        self.assertEqual(1, result["fact_count"])
        self.assertEqual(1, result["deleted_fact_count"])
        self.assertEqual(1, len(facts_store.upserted_rows))
        self.assertEqual("fact-new", facts_store.upserted_rows[0]["fact_id"])
        self.assertEqual(1, len(vector_store.upserted_facts))
        self.assertEqual("fact-new", vector_store.upserted_facts[0]["facts_data"][0]["fact_id"])
        self.assertEqual(["fact-old"], vector_store.deleted_fact_ids)
        self.assertEqual(
            [
                {
                    "brand_code": "BRAND-001",
                    "brand_name": "示例品牌",
                    "fact_scope": "official_kb",
                    "fact_id": "fact-new",
                    "fact_text": "示例品牌是一家测试品牌",
                    "normalized_fact_hash": "fact-new",
                    "source_document_id": result["document_id"],
                    "source_task_id": None,
                    "source_asset_id": None,
                    "full_knowledge_file_id": None,
                    "version_no": None,
                    "knowledge_date": None,
                    "section_path": None,
                }
            ],
            facts_store.rows,
        )

    async def test_ingest_rejects_filename_brand_mismatch(self) -> None:
        service = BrandAiKnowledgeIngestionService(
            BrandAiKnowledgeIngestionDependencies(
                settings=types.SimpleNamespace(chunk_size=200, chunk_overlap=20),
                brands=_FakeBrands(),
                parser=_FakeParser("# 示例品牌"),
                embeddings=_FakeEmbeddings(),
                store=_FakeVectorStore(),
                oss_client=_FakeOssClient(),
                brand_full_knowledge=_FakeBrandFullKnowledgeStore(),
                brand_knowledge_facts=_FakeFactsStore(),
                brand_knowledge_ingestion_jobs=_FakeJobStore(),
            )
        )

        with tempfile.NamedTemporaryFile(delete=False, suffix=".md") as tmp:
            tmp.write(b"# content")
            staged_path = Path(tmp.name)

        try:
            with self.assertRaisesRegex(ValueError, "文件名中的品牌名与请求中的 brand_name 不一致"):
                await service.ingest_upload_task_file(
                    task_id="task-1",
                    upload_task_file_id=1,
                    filename="【别的品牌】品牌AI知识库_V1_20260715.md",
                    brand_code="BRAND-001",
                    brand_name="示例品牌",
                    force_reingest=False,
                    staged_path=staged_path,
                    source_url=None,
                    content_type="text/markdown",
                )
        finally:
            staged_path.unlink(missing_ok=True)

    async def test_ingest_skips_same_content_without_force(self) -> None:
        full_knowledge_store = _FakeBrandFullKnowledgeStore()
        full_knowledge_store.same_content_row = {
            "id": 88,
            "document_id": "doc-existing",
        }
        job_store = _FakeJobStore()
        parser = _FakeParser("# 示例品牌")
        service = BrandAiKnowledgeIngestionService(
            BrandAiKnowledgeIngestionDependencies(
                settings=types.SimpleNamespace(chunk_size=200, chunk_overlap=20),
                brands=_FakeBrands(),
                parser=parser,
                embeddings=_FakeEmbeddings(),
                store=_FakeVectorStore(),
                oss_client=_FakeOssClient(),
                brand_full_knowledge=full_knowledge_store,
                brand_knowledge_facts=_FakeFactsStore(),
                brand_knowledge_ingestion_jobs=job_store,
            )
        )

        with tempfile.NamedTemporaryFile(delete=False, suffix=".md") as tmp:
            tmp.write("# 示例品牌".encode("utf-8"))
            staged_path = Path(tmp.name)

        try:
            result = await service.ingest_upload_task_file(
                task_id="task-2",
                upload_task_file_id=2,
                filename="【示例品牌】品牌AI知识库_V1_20260715.md",
                brand_code="BRAND-001",
                brand_name="示例品牌",
                force_reingest=False,
                staged_path=staged_path,
                source_url=None,
                content_type="text/markdown",
            )
        finally:
            staged_path.unlink(missing_ok=True)

        self.assertTrue(result["skipped"])
        self.assertEqual(88, result["full_knowledge_file_id"])
        self.assertEqual([], full_knowledge_store.created_rows)
        self.assertEqual("skipped", job_store.updated_jobs[-1]["status"])
        self.assertEqual([], parser.calls)

    async def test_ingest_skipped_same_content_can_backfill_basic_info(self) -> None:
        full_knowledge_store = _FakeBrandFullKnowledgeStore()
        full_knowledge_store.same_content_row = {
            "id": 88,
            "document_id": "doc-existing",
            "ingest_status": "success",
        }
        job_store = _FakeJobStore()
        brand_knowledge_store = _FakeBrandKnowledgeStore()
        brands_store = _FakeBrands(
            {
                "id": 1,
                "brand_code": "BRAND-001",
                "brand_name": "示例品牌",
                "vision": [],
            }
        )
        service = BrandAiKnowledgeIngestionService(
            BrandAiKnowledgeIngestionDependencies(
                settings=types.SimpleNamespace(chunk_size=200, chunk_overlap=20),
                brands=brands_store,
                parser=_FakeParser("# 示例品牌"),
                embeddings=_FakeEmbeddings(),
                store=_FakeVectorStore(),
                oss_client=_FakeOssClient(),
                brand_full_knowledge=full_knowledge_store,
                brand_knowledge_facts=_FakeFactsStore(),
                brand_knowledge_ingestion_jobs=job_store,
                brand_knowledge=brand_knowledge_store,
                brand_products=_FakeBrandProductsStore(),
            )
        )
        expected_vision = ["成为完整愿景，不因为相同内容跳过而丢失。"]

        async def _fake_extract_snapshot_from_markdown(**kwargs):
            return {
                "basic_info": {
                    "brand_name": "示例品牌",
                    "vision": expected_vision,
                },
                "company_profile": {},
            }

        original_extract_snapshot = _MODULE.extract_brand_knowledge_snapshot_from_markdown
        _MODULE.extract_brand_knowledge_snapshot_from_markdown = _fake_extract_snapshot_from_markdown

        with tempfile.NamedTemporaryFile(delete=False, suffix=".md") as tmp:
            tmp.write("# 示例品牌".encode("utf-8"))
            staged_path = Path(tmp.name)

        try:
            result = await service.ingest_upload_task_file(
                task_id="task-same-content-backfill",
                upload_task_file_id=22,
                filename="【示例品牌】品牌AI知识库_V1_20260715.md",
                brand_code="BRAND-001",
                brand_name="示例品牌",
                force_reingest=False,
                staged_path=staged_path,
                source_url=None,
                content_type="text/markdown",
                backfill_brand_knowledge_json_empty_only=True,
            )
        finally:
            _MODULE.extract_brand_knowledge_snapshot_from_markdown = original_extract_snapshot
            staged_path.unlink(missing_ok=True)

        self.assertTrue(result["skipped"])
        self.assertEqual("success", result["knowledge_json_backfill_status"])
        self.assertEqual([], full_knowledge_store.created_rows)
        self.assertEqual(expected_vision, brands_store.upserted_rows[0]["vision"])
        upserted_by_type = {
            row["knowledge_type"]: row
            for row in brand_knowledge_store.upserted_rows
        }
        self.assertNotIn("basic_info", upserted_by_type)

    async def test_ingest_skipped_same_content_merges_other_info_by_title(self) -> None:
        full_knowledge_store = _FakeBrandFullKnowledgeStore()
        full_knowledge_store.same_content_row = {
            "id": 88,
            "document_id": "doc-existing",
            "ingest_status": "success",
        }
        job_store = _FakeJobStore()
        brand_knowledge_store = _FakeBrandKnowledgeStore()
        brand_knowledge_store.rows_by_brand_id[1] = [
            {
                "knowledge_type": "other_info",
                "content_json": [
                    {"title": "停车信息", "content": "旧停车信息"},
                    {"title": "营业说明", "content": "保留营业说明"},
                ],
            }
        ]
        service = BrandAiKnowledgeIngestionService(
            BrandAiKnowledgeIngestionDependencies(
                settings=types.SimpleNamespace(chunk_size=200, chunk_overlap=20),
                brands=_FakeBrands(
                    {
                        "id": 1,
                        "brand_code": "BRAND-001",
                        "brand_name": "示例品牌",
                    }
                ),
                parser=_FakeParser("# 示例品牌"),
                embeddings=_FakeEmbeddings(),
                store=_FakeVectorStore(),
                oss_client=_FakeOssClient(),
                brand_full_knowledge=full_knowledge_store,
                brand_knowledge_facts=_FakeFactsStore(),
                brand_knowledge_ingestion_jobs=job_store,
                brand_knowledge=brand_knowledge_store,
                brand_products=_FakeBrandProductsStore(),
            )
        )

        async def _fake_extract_snapshot_from_markdown(**kwargs):
            return {
                "basic_info": {},
                "company_profile": {},
                "other_info": [
                    {"title": "停车信息", "content": "新停车信息"},
                    {"title": "夜游说明", "content": "新增夜游说明"},
                ],
            }

        original_extract_snapshot = _MODULE.extract_brand_knowledge_snapshot_from_markdown
        _MODULE.extract_brand_knowledge_snapshot_from_markdown = _fake_extract_snapshot_from_markdown

        with tempfile.NamedTemporaryFile(delete=False, suffix=".md") as tmp:
            tmp.write("# 示例品牌".encode("utf-8"))
            staged_path = Path(tmp.name)

        try:
            result = await service.ingest_upload_task_file(
                task_id="task-same-content-other-info-backfill",
                upload_task_file_id=23,
                filename="【示例品牌】品牌AI知识库_V1_20260715.md",
                brand_code="BRAND-001",
                brand_name="示例品牌",
                force_reingest=False,
                staged_path=staged_path,
                source_url=None,
                content_type="text/markdown",
                backfill_brand_knowledge_json_empty_only=True,
            )
        finally:
            _MODULE.extract_brand_knowledge_snapshot_from_markdown = original_extract_snapshot
            staged_path.unlink(missing_ok=True)

        self.assertTrue(result["skipped"])
        self.assertEqual("success", result["knowledge_json_backfill_status"])
        upserted_by_type = {
            row["knowledge_type"]: row["content_json"]
            for row in brand_knowledge_store.upserted_rows
        }
        self.assertEqual(
            [
                {"title": "停车信息", "content": "新停车信息"},
                {"title": "营业说明", "content": "保留营业说明"},
                {"title": "夜游说明", "content": "新增夜游说明"},
            ],
            upserted_by_type["other_info"],
        )

    async def test_ingest_does_not_skip_failed_same_content_placeholder(self) -> None:
        full_knowledge_store = _FakeBrandFullKnowledgeStore()
        full_knowledge_store.same_content_row = {
            "id": 88,
            "document_id": "doc-failed",
            "ingest_status": "failed",
            "oss_key": None,
            "oss_url": None,
        }
        job_store = _FakeJobStore()
        service = BrandAiKnowledgeIngestionService(
            BrandAiKnowledgeIngestionDependencies(
                settings=types.SimpleNamespace(chunk_size=200, chunk_overlap=20),
                brands=_FakeBrands(),
                parser=_FakeParser("# 示例品牌"),
                embeddings=_FakeEmbeddings(),
                store=_FakeVectorStore(),
                oss_client=_FakeOssClient(),
                brand_full_knowledge=full_knowledge_store,
                brand_knowledge_facts=_FakeFactsStore(),
                brand_knowledge_ingestion_jobs=job_store,
            )
        )

        async def _fake_render_pdf(*, markdown_text: str, title: str) -> bytes:
            return b"%PDF-1.4"

        async def _fake_build_fact_rows(**kwargs):
            return []

        async def _fake_write_document_chunks(**kwargs):
            return None

        service._render_pdf = _fake_render_pdf
        service._build_fact_rows = _fake_build_fact_rows
        service._write_document_chunks = _fake_write_document_chunks

        with tempfile.NamedTemporaryFile(delete=False, suffix=".md") as tmp:
            tmp.write("# 示例品牌".encode("utf-8"))
            staged_path = Path(tmp.name)

        try:
            result = await service.ingest_upload_task_file(
                task_id="task-failed-placeholder",
                upload_task_file_id=4,
                filename="【示例品牌】品牌AI知识库_V1_20260715.md",
                brand_code="BRAND-001",
                brand_name="示例品牌",
                force_reingest=False,
                staged_path=staged_path,
                source_url=None,
                content_type="text/markdown",
            )
        finally:
            staged_path.unlink(missing_ok=True)

        self.assertFalse(result["skipped"])
        self.assertEqual(101, result["full_knowledge_file_id"])
        self.assertEqual(1, len(full_knowledge_store.created_rows))
        self.assertEqual(1, len(full_knowledge_store.asset_updates))

    async def test_ingest_same_version_creates_new_revision_and_cleans_old_data(self) -> None:
        full_knowledge_store = _FakeBrandFullKnowledgeStore()
        full_knowledge_store.latest_row = {
            "id": 77,
            "version_no": 3,
            "document_id": "doc-latest-old",
        }
        full_knowledge_store.next_revision_no = 2
        full_knowledge_store.old_document_ids = ["doc-old-1", "doc-old-2"]

        facts_store = _FakeFactsStore()
        facts_store.rows = [
            {
                "brand_code": "BRAND-001",
                "fact_id": "fact-old",
                "source_document_id": "doc-old-1",
            }
        ]
        vector_store = _FakeVectorStore()
        job_store = _FakeJobStore()
        parser = _FakeParser("# 新知识库\n\n正文")
        service = BrandAiKnowledgeIngestionService(
            BrandAiKnowledgeIngestionDependencies(
                settings=types.SimpleNamespace(chunk_size=100, chunk_overlap=10),
                brands=_FakeBrands(),
                parser=parser,
                embeddings=_FakeEmbeddings(),
                store=vector_store,
                oss_client=_FakeOssClient(),
                brand_full_knowledge=full_knowledge_store,
                brand_knowledge_facts=facts_store,
                brand_knowledge_ingestion_jobs=job_store,
            )
        )

        async def _fake_render_pdf(*, markdown_text: str, title: str) -> bytes:
            return b"%PDF-1.4"

        async def _fake_build_fact_rows(**kwargs):
            return [
                {
                    "brand_code": "BRAND-001",
                    "brand_name": "示例品牌",
                    "fact_id": "fact-new",
                    "fact_text": "示例品牌是一家测试品牌",
                    "normalized_fact_hash": "fact-new",
                    "source_document_id": "brandkb:BRAND-001:V3:20260715:R2",
                    "full_knowledge_file_id": 101,
                    "version_no": 3,
                    "knowledge_date": "20260715",
                    "section_path": None,
                }
            ]

        async def _fake_write_document_chunks(**kwargs):
            vector_store.inserted_chunks.append(kwargs)

        service._render_pdf = _fake_render_pdf
        service._build_fact_rows = _fake_build_fact_rows
        service._write_document_chunks = _fake_write_document_chunks

        with tempfile.NamedTemporaryFile(delete=False, suffix=".md") as tmp:
            tmp.write("# 新知识库\n\n正文".encode("utf-8"))
            staged_path = Path(tmp.name)

        try:
            result = await service.ingest_upload_task_file(
                task_id="task-3",
                upload_task_file_id=3,
                filename="【示例品牌】品牌AI知识库_V3_20260715.md",
                brand_code="BRAND-001",
                brand_name="示例品牌",
                force_reingest=False,
                staged_path=staged_path,
                source_url=None,
                content_type="text/markdown",
            )
        finally:
            staged_path.unlink(missing_ok=True)

        self.assertFalse(result["skipped"])
        self.assertEqual(101, result["full_knowledge_file_id"])
        self.assertEqual(2, full_knowledge_store.created_rows[0]["revision_no"])
        self.assertEqual(3, full_knowledge_store.created_rows[0]["version_no"])
        self.assertEqual("20260715", full_knowledge_store.created_rows[0]["knowledge_date"])
        self.assertEqual("frontend", full_knowledge_store.created_rows[0]["change_origin"])
        self.assertIsNone(full_knowledge_store.created_rows[0]["oss_key"])
        self.assertIsNone(full_knowledge_store.created_rows[0]["oss_url"])
        self.assertIsNone(full_knowledge_store.created_rows[0]["pdf_oss_key"])
        self.assertIsNone(full_knowledge_store.created_rows[0]["pdf_oss_url"])
        self.assertEqual(1, len(full_knowledge_store.asset_updates))
        self.assertEqual(101, full_knowledge_store.asset_updates[0]["file_id"])
        self.assertTrue(str(full_knowledge_store.asset_updates[0]["oss_key"]).endswith("【示例品牌】品牌AI知识库_V3_20260715.md"))
        self.assertTrue(str(full_knowledge_store.asset_updates[0]["pdf_oss_key"]).endswith("【示例品牌】品牌AI知识库_V3_20260715.pdf"))
        self.assertEqual(1, len(full_knowledge_store.promoted_rows))
        self.assertEqual("BRAND-001", full_knowledge_store.promoted_rows[0]["brand_code"])
        self.assertEqual(101, full_knowledge_store.promoted_rows[0]["file_id"])
        self.assertRegex(
            str(full_knowledge_store.promoted_rows[0]["knowledge_revision"]),
            r"^LXKG-[A-Z0-9]+-V1\.0\.0-\d{14}$",
        )
        self.assertRegex(
            str(result["knowledge_revision"]),
            r"^LXKG-[A-Z0-9]+-V1\.0\.0-\d{14}$",
        )
        self.assertEqual(["doc-old-1", "doc-old-2"], vector_store.deleted_document_ids)
        self.assertEqual(["fact-old"], vector_store.deleted_fact_ids)
        self.assertEqual("success", job_store.updated_jobs[-1]["status"])
        self.assertEqual([], parser.calls)

    async def test_ingest_allows_lower_version_when_knowledge_date_is_newer_than_latest(self) -> None:
        full_knowledge_store = _FakeBrandFullKnowledgeStore()
        full_knowledge_store.latest_row = {
            "id": 77,
            "version_no": 3,
            "knowledge_date": "20260915",
            "document_id": "doc-latest-old",
        }
        vector_store = _FakeVectorStore()
        service = BrandAiKnowledgeIngestionService(
            BrandAiKnowledgeIngestionDependencies(
                settings=types.SimpleNamespace(chunk_size=100, chunk_overlap=10),
                brands=_FakeBrands(),
                parser=_FakeParser("# 新日期低版本知识库\n\n正文"),
                embeddings=_FakeEmbeddings(),
                store=vector_store,
                oss_client=_FakeOssClient(),
                brand_full_knowledge=full_knowledge_store,
                brand_knowledge_facts=_FakeFactsStore(),
                brand_knowledge_ingestion_jobs=_FakeJobStore(),
            )
        )

        async def _fake_render_pdf(*, markdown_text: str, title: str) -> bytes:
            return b"%PDF-1.4"

        async def _fake_build_fact_rows(**kwargs):
            return []

        async def _fake_write_document_chunks(**kwargs):
            vector_store.inserted_chunks.append(kwargs)

        service._render_pdf = _fake_render_pdf
        service._build_fact_rows = _fake_build_fact_rows
        service._write_document_chunks = _fake_write_document_chunks

        with tempfile.NamedTemporaryFile(delete=False, suffix=".md") as tmp:
            tmp.write("# 新日期低版本知识库\n\n正文".encode("utf-8"))
            staged_path = Path(tmp.name)

        try:
            result = await service.ingest_upload_task_file(
                task_id="task-newer-date-lower-version",
                upload_task_file_id=5,
                filename="【示例品牌】品牌AI知识库_V2_20260918.md",
                brand_code="BRAND-001",
                brand_name="示例品牌",
                force_reingest=False,
                staged_path=staged_path,
                source_url=None,
                content_type="text/markdown",
            )
        finally:
            staged_path.unlink(missing_ok=True)

        self.assertFalse(result["skipped"])
        self.assertEqual(101, result["full_knowledge_file_id"])
        self.assertEqual(2, full_knowledge_store.created_rows[0]["version_no"])
        self.assertEqual("20260918", full_knowledge_store.created_rows[0]["knowledge_date"])
        self.assertEqual(1, len(full_knowledge_store.promoted_rows))

    async def test_ingest_rejects_lower_version_when_knowledge_date_matches_latest(self) -> None:
        full_knowledge_store = _FakeBrandFullKnowledgeStore()
        full_knowledge_store.latest_row = {
            "id": 77,
            "version_no": 3,
            "knowledge_date": "20260918",
            "document_id": "doc-latest-old",
        }
        service = BrandAiKnowledgeIngestionService(
            BrandAiKnowledgeIngestionDependencies(
                settings=types.SimpleNamespace(chunk_size=100, chunk_overlap=10),
                brands=_FakeBrands(),
                parser=_FakeParser("# 同日期低版本知识库\n\n正文"),
                embeddings=_FakeEmbeddings(),
                store=_FakeVectorStore(),
                oss_client=_FakeOssClient(),
                brand_full_knowledge=full_knowledge_store,
                brand_knowledge_facts=_FakeFactsStore(),
                brand_knowledge_ingestion_jobs=_FakeJobStore(),
            )
        )

        with tempfile.NamedTemporaryFile(delete=False, suffix=".md") as tmp:
            tmp.write("# 同日期低版本知识库\n\n正文".encode("utf-8"))
            staged_path = Path(tmp.name)

        try:
            with self.assertRaisesRegex(ValueError, "知识库版本过旧"):
                await service.ingest_upload_task_file(
                    task_id="task-same-date-lower-version",
                    upload_task_file_id=6,
                    filename="【示例品牌】品牌AI知识库_V2_20260918.md",
                    brand_code="BRAND-001",
                    brand_name="示例品牌",
                    force_reingest=False,
                    staged_path=staged_path,
                    source_url=None,
                    content_type="text/markdown",
                )
        finally:
            staged_path.unlink(missing_ok=True)

    async def test_ingest_rejects_lower_version_when_latest_has_no_knowledge_date(self) -> None:
        full_knowledge_store = _FakeBrandFullKnowledgeStore()
        full_knowledge_store.latest_row = {
            "id": 77,
            "version_no": 3,
            "document_id": "doc-latest-old",
        }
        service = BrandAiKnowledgeIngestionService(
            BrandAiKnowledgeIngestionDependencies(
                settings=types.SimpleNamespace(chunk_size=100, chunk_overlap=10),
                brands=_FakeBrands(),
                parser=_FakeParser("# 旧数据低版本知识库\n\n正文"),
                embeddings=_FakeEmbeddings(),
                store=_FakeVectorStore(),
                oss_client=_FakeOssClient(),
                brand_full_knowledge=full_knowledge_store,
                brand_knowledge_facts=_FakeFactsStore(),
                brand_knowledge_ingestion_jobs=_FakeJobStore(),
            )
        )

        async def _fake_render_pdf(*, markdown_text: str, title: str) -> bytes:
            return b"%PDF-1.4"

        async def _fake_build_fact_rows(**kwargs):
            return []

        async def _fake_write_document_chunks(**kwargs):
            return None

        service._render_pdf = _fake_render_pdf
        service._build_fact_rows = _fake_build_fact_rows
        service._write_document_chunks = _fake_write_document_chunks

        with tempfile.NamedTemporaryFile(delete=False, suffix=".md") as tmp:
            tmp.write("# 旧数据低版本知识库\n\n正文".encode("utf-8"))
            staged_path = Path(tmp.name)

        try:
            with self.assertRaisesRegex(ValueError, "知识库版本过旧"):
                await service.ingest_upload_task_file(
                    task_id="task-missing-date-lower-version",
                    upload_task_file_id=7,
                    filename="【示例品牌】品牌AI知识库_V2_20260918.md",
                    brand_code="BRAND-001",
                    brand_name="示例品牌",
                    force_reingest=False,
                    staged_path=staged_path,
                    source_url=None,
                    content_type="text/markdown",
                )
        finally:
            staged_path.unlink(missing_ok=True)

    async def test_ingest_reuses_half_created_full_knowledge_file_on_retry(self) -> None:
        markdown_text = "# 重试知识库\n\n正文"
        content_hash = hashlib.sha256(markdown_text.encode("utf-8")).hexdigest()
        source_task_id = "bg:brand_full_knowledge_refresh:100052"
        existing_document_id = "brandkb:BRAND-001:V8:20260909:R1"
        full_knowledge_store = _FakeBrandFullKnowledgeStore()
        full_knowledge_store.latest_row = {
            "id": 88,
            "version_no": 8,
            "revision_no": 1,
            "document_id": existing_document_id,
        }
        full_knowledge_store.next_revision_no = 2
        full_knowledge_store.source_task_file_row = {
            "id": 88,
            "brand_code": "BRAND-001",
            "source_task_id": source_task_id,
            "file_name": "【示例品牌】品牌AI知识库_V8_20260909.md",
            "version_no": 8,
            "knowledge_date": "20260909",
            "revision_no": 1,
            "document_id": existing_document_id,
            "content_hash": content_hash,
            "ingest_status": "failed",
            "oss_key": None,
            "oss_url": None,
        }
        vector_store = _FakeVectorStore()
        job_store = _FakeJobStore()
        service = BrandAiKnowledgeIngestionService(
            BrandAiKnowledgeIngestionDependencies(
                settings=types.SimpleNamespace(chunk_size=100, chunk_overlap=10),
                brands=_FakeBrands(),
                parser=_FakeParser(markdown_text),
                embeddings=_FakeEmbeddings(),
                store=vector_store,
                oss_client=_FakeOssClient(),
                brand_full_knowledge=full_knowledge_store,
                brand_knowledge_facts=_FakeFactsStore(),
                brand_knowledge_ingestion_jobs=job_store,
            )
        )

        async def _fake_render_pdf(*, markdown_text: str, title: str) -> bytes:
            return b"%PDF-1.4"

        async def _fake_build_fact_rows(**kwargs):
            return []

        async def _fake_write_document_chunks(**kwargs):
            vector_store.inserted_chunks.append(kwargs)

        service._render_pdf = _fake_render_pdf
        service._build_fact_rows = _fake_build_fact_rows
        service._write_document_chunks = _fake_write_document_chunks

        result = await service.ingest_generated_markdown(
            task_id=source_task_id,
            filename="【示例品牌】品牌AI知识库_V8_20260909.md",
            brand_code="BRAND-001",
            brand_name="示例品牌",
            markdown_text=markdown_text,
            source_task_id=source_task_id,
            job_id=f"brand-ai-kb-generated:{source_task_id}",
        )

        self.assertFalse(result["skipped"])
        self.assertEqual(88, result["full_knowledge_file_id"])
        self.assertEqual(existing_document_id, result["document_id"])
        self.assertEqual([], full_knowledge_store.created_rows)
        self.assertEqual(88, full_knowledge_store.asset_updates[0]["file_id"])
        self.assertEqual(88, full_knowledge_store.promoted_rows[0]["file_id"])
        self.assertEqual(existing_document_id, vector_store.inserted_chunks[0]["document_id"])
        self.assertEqual("success", job_store.updated_jobs[-1]["status"])
