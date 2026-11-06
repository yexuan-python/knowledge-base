from __future__ import annotations

import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


def _module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _install_import_stubs() -> None:
    module_stubs: dict[str, dict[str, object]] = {
        "knowledge_base.infrastructure.embedding": {
            "EmbeddingRateLimitedError": type("EmbeddingRateLimitedError", (Exception,), {}),
            "EmbeddingService": type("EmbeddingService", (), {}),
        },
        "knowledge_base.infrastructure.milvus_store": {"MilvusVectorStore": type("MilvusVectorStore", (), {})},
        "knowledge_base.infrastructure.oss_client": {"OSSClient": type("OSSClient", (), {})},
        "knowledge_base.infrastructure.integrations": {
            "TianyanchaClient": type("TianyanchaClient", (), {}),
            "TianyanchaCompanyProfile": type("TianyanchaCompanyProfile", (), {}),
            "TianyanchaManagementMember": type("TianyanchaManagementMember", (), {}),
        },
    }

    if not _module_available("requests"):
        module_stubs["requests"] = {"post": lambda *args, **kwargs: None}
    if not _module_available("pymysql"):
        module_stubs["pymysql"] = {}
    if not _module_available("dotenv"):
        module_stubs["dotenv"] = {"load_dotenv": lambda *args, **kwargs: None}
    if not _module_available("dashscope"):
        module_stubs["dashscope"] = {
            "Generation": type("Generation", (), {"call": staticmethod(lambda *args, **kwargs: None)}),
            "MultiModalEmbedding": type(
                "MultiModalEmbedding",
                (),
                {"call": staticmethod(lambda *args, **kwargs: None)},
            ),
        }

    for module_name, attrs in module_stubs.items():
        if module_name in sys.modules:
            continue
        stub = types.ModuleType(module_name)
        for attr_name, value in attrs.items():
            setattr(stub, attr_name, value)
        sys.modules[module_name] = stub


_install_import_stubs()

from knowledge_base.brand_knowledge.application import service as brand_knowledge_service_module
from knowledge_base.document.ai import facts as facts_module
from knowledge_base.brand_knowledge.application.service import (
    BrandKnowledgeApplicationDependencies,
    BrandKnowledgeApplicationService,
)


class _FakeBrands:
    def get_brand_by_code(self, brand_code: str) -> dict | None:
        if brand_code != "BR001":
            return None
        return {
            "id": 7,
            "brand_code": "BR001",
            "brand_name": "测试品牌",
            "knowledge_revision": "LXKG-CPPP-V1.0.0-20260716154306",
        }

    def get_brand_by_name(self, brand_name: str) -> dict | None:
        if brand_name != "测试品牌":
            return None
        return {
            "id": 7,
            "brand_code": "BR001",
            "brand_name": "测试品牌",
        }


class _FakeSessionStore:
    def __init__(self) -> None:
        self.sessions: dict[str, dict] = {}
        self.rounds: list[dict] = []

    def create_session(self, **kwargs) -> None:
        self.sessions[kwargs["session_id"]] = {
            "session_id": kwargs["session_id"],
            "brand_id": kwargs.get("brand_id"),
            "brand_code": kwargs.get("brand_code"),
            "brand_name": kwargs.get("brand_name"),
            "source_task_id": kwargs.get("source_task_id"),
            "session_kind": kwargs.get("session_kind"),
            "status": kwargs.get("status"),
            "current_round": kwargs.get("current_round"),
            "initial_user_message": kwargs.get("initial_user_message"),
            "latest_user_message": kwargs.get("latest_user_message"),
            "latest_assistant_message": kwargs.get("latest_assistant_message"),
            "source_documents_json": kwargs.get("source_documents"),
            "resolution_history_json": [],
            "latest_conflicts_json": [],
            "latest_auto_merged_json": [],
            "latest_conflict_markdown": None,
            "latest_scan_summary": None,
            "latest_draft_markdown": None,
            "final_markdown": None,
            "final_oss_key": None,
            "final_full_knowledge_file_id": None,
            "final_document_id": None,
        }

    def create_round(self, **kwargs) -> None:
        self.rounds.append(kwargs)

    def update_session_progress(self, *, session_id: str, **kwargs) -> None:
        session = self.sessions[session_id]
        session.update(
            {
                "status": kwargs.get("status", session.get("status")),
                "current_round": kwargs.get("current_round", session.get("current_round")),
                "latest_draft_markdown": kwargs.get("latest_draft_markdown", session.get("latest_draft_markdown")),
                "latest_conflicts_json": kwargs.get("latest_conflicts", session.get("latest_conflicts_json")),
                "latest_conflict_markdown": kwargs.get(
                    "latest_conflict_markdown",
                    session.get("latest_conflict_markdown"),
                ),
                "latest_scan_summary": kwargs.get("latest_scan_summary", session.get("latest_scan_summary")),
                "latest_auto_merged_json": kwargs.get("latest_auto_merged", session.get("latest_auto_merged_json")),
                "latest_user_message": kwargs.get("latest_user_message", session.get("latest_user_message")),
                "latest_assistant_message": kwargs.get(
                    "latest_assistant_message",
                    session.get("latest_assistant_message"),
                ),
                "resolution_history_json": kwargs.get(
                    "resolution_history",
                    session.get("resolution_history_json"),
                ),
                "final_markdown": kwargs.get("final_markdown", session.get("final_markdown")),
                "final_oss_key": kwargs.get("final_oss_key", session.get("final_oss_key")),
                "final_full_knowledge_file_id": kwargs.get(
                    "final_full_knowledge_file_id",
                    session.get("final_full_knowledge_file_id"),
                ),
                "final_document_id": kwargs.get("final_document_id", session.get("final_document_id")),
            }
        )

    def get_session(self, session_id: str) -> dict | None:
        return self.sessions.get(session_id)

    def get_rounds(self, session_id: str) -> list[dict]:
        return [item for item in self.rounds if item.get("session_id") == session_id]

    def get_latest_by_source_task_id(self, *, source_task_id: str, session_kind: str | None = None) -> dict | None:
        for session in reversed(list(self.sessions.values())):
            if session.get("source_task_id") != source_task_id:
                continue
            if session_kind is not None and session.get("session_kind") != session_kind:
                continue
            return session
        return None

    def get_latest_by_brand_code(
        self,
        *,
        brand_code: str,
        session_kind: str = "attachment_conflict",
        preferred_statuses: list[str] | None = None,
    ) -> dict | None:
        candidates = [
            session
            for session in self.sessions.values()
            if session.get("brand_code") == brand_code and session.get("session_kind") == session_kind
        ]
        if preferred_statuses:
            preferred = [session for session in candidates if session.get("status") in preferred_statuses]
            if preferred:
                candidates = preferred
        if not candidates:
            return None
        return candidates[-1]


class _FakeUploadTasks:
    def __init__(self) -> None:
        self.task = {
            "task_id": "task-1",
            "task_type": "brand_upload",
            "metadata_json": {
                "brand_code": "BR001",
                "brand_name": "测试品牌",
                "_task_payload": {
                    "file_metadata_by_index": {
                        "0": {
                            "subcategory": "产品A",
                        }
                    }
                },
            },
        }
        self.files = [
            {
                "id": 11,
                "file_index": 0,
                "status": "success",
                "file_role": "attachment",
            }
        ]
        self.callback_rows: dict[tuple[str, str], dict[str, object]] = {}

    def get_upload_task(self, task_id: str) -> dict | None:
        if task_id == "task-1":
            return self.task
        return None

    def get_upload_task_files(self, task_id: str) -> list[dict]:
        if task_id == "task-1":
            return list(self.files)
        return []

    def upsert_upload_task_callback(
        self,
        *,
        task_id: str,
        callback_type: str,
        callback_url: str,
        request_payload_json: dict | None,
        status: str,
    ) -> None:
        key = (task_id, callback_type)
        row = dict(self.callback_rows.get(key) or {})
        row.update(
            {
                "task_id": task_id,
                "callback_type": callback_type,
                "callback_url": callback_url,
                "status": status,
                "retry_count": 0,
                "next_retry_at": None,
                "last_response_code": None,
                "last_response_body": None,
                "last_error_message": None,
                "sent_at": None,
            }
        )
        if request_payload_json is not None:
            row["request_payload_json"] = request_payload_json
        self.callback_rows[key] = row

    def get_upload_task_callback(self, *, task_id: str, callback_type: str):
        return self.callback_rows.get((task_id, callback_type))

    def update_upload_task_callback_result(self, **kwargs) -> None:
        key = (kwargs["task_id"], kwargs["callback_type"])
        row = dict(self.callback_rows.get(key) or {})
        row.update(kwargs)
        self.callback_rows[key] = row

    def list_retryable_upload_task_callbacks(self, *, callback_type: str):
        return [
            dict(row)
            for (task_id, row_callback_type), row in self.callback_rows.items()
            if row_callback_type == callback_type and row.get("status") == "retrying"
        ]


class _FakeAttachmentAssets:
    def __init__(self) -> None:
        self.rows = [
            {
                "id": 21,
                "upload_task_file_id": 11,
                "original_filename": "资料一.md",
                "oss_key": "oss/asset-1.md",
                "oss_url": "https://oss.example.com/asset-1.md",
                "fulltext_key": None,
                "fulltext_url": None,
                "converted_version": None,
                "source_url": "https://example.com/asset-1.md",
            }
        ]

    def list_by_upload_task_id(self, *, upload_task_id: str) -> list[dict]:
        if upload_task_id != "task-1":
            return []
        return [dict(item) for item in self.rows]

    def update_parsed_content(
        self,
        *,
        asset_id: int,
        parsed_source_type: str | None,
        parsed_markdown: str | None,
        converted_version: int | None = None,
        fulltext_key: str | None = None,
        fulltext_url: str | None = None,
    ) -> None:
        for row in self.rows:
            if int(row.get("id") or 0) != asset_id:
                continue
            row["parsed_source_type"] = parsed_source_type
            row["parsed_markdown"] = parsed_markdown
            if converted_version is not None:
                row["converted_version"] = converted_version
            if fulltext_key is not None:
                row["fulltext_key"] = fulltext_key
            if fulltext_url is not None:
                row["fulltext_url"] = fulltext_url
            break


class _FakeOSSClient:
    enabled = True

    def __init__(self) -> None:
        self.uploaded_bytes: list[dict] = []

    def get_object(self, object_key: str) -> bytes | None:
        if object_key == "oss/asset-1.md":
            return "# 资料一\n冲突内容A".encode("utf-8")
        return None

    def download_object_to_temp_file(self, object_key: str, *, suffix: str = ".tmp") -> Path | None:
        data = self.get_object(object_key)
        if data is None:
            return None
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(data)
            return Path(tmp.name)

    def upload_bytes(self, data: bytes, object_key: str, content_type: str) -> str:
        self.uploaded_bytes.append(
            {
                "data": data,
                "object_key": object_key,
                "content_type": content_type,
            }
        )
        return object_key

    def build_object_url(self, object_key: str) -> str:
        return f"https://oss.example.com/{object_key}"


class _FakeFullKnowledgeStore:
    def __init__(self) -> None:
        self.created_rows: list[dict] = []
        self.frontend_row = {
            "id": 88,
            "brand_id": 7,
            "brand_code": "BR001",
            "brand_name": "测试品牌",
            "version_no": 1,
            "revision_no": 1,
            "file_name": "【测试品牌】品牌AI知识库_V1_20260715.md",
            "content_markdown": "# 旧版知识库\n旧内容",
            "document_id": "brandkb:BR001:V1:20260715:R1",
            "is_latest": True,
            "ingest_status": "success",
            "change_origin": "frontend",
        }
        self.latest_row = dict(self.frontend_row)

    @staticmethod
    def _is_queryable_latest(row: dict) -> bool:
        return str(row.get("ingest_status") or "").strip() != "skipped"

    @staticmethod
    def _latest_sort_key(row: dict) -> tuple[int, int, int, int]:
        return (
            1 if row.get("is_latest") else 0,
            int(row.get("version_no") or 0),
            int(row.get("revision_no") or 0),
            int(row.get("id") or 0),
        )

    @staticmethod
    def _version_sort_key(row: dict) -> tuple[int, str, int, int]:
        return (
            int(row.get("version_no") or 0),
            str(row.get("knowledge_date") or ""),
            int(row.get("revision_no") or 0),
            int(row.get("id") or 0),
        )

    def _rows(self) -> list[dict]:
        return [dict(self.frontend_row), *[dict(row) for row in self.created_rows]]

    def get_latest_by_brand_code(self, *, brand_code: str) -> dict | None:
        candidates = [
            row
            for row in self._rows()
            if str(row.get("brand_code") or "") == brand_code and self._is_queryable_latest(row)
        ]
        if not candidates:
            return None
        return sorted(candidates, key=self._latest_sort_key, reverse=True)[0]

    def get_latest_by_brand_code_and_origin(self, *, brand_code: str, change_origin: str) -> dict | None:
        candidates = [
            row
            for row in self._rows()
            if str(row.get("brand_code") or "") == brand_code
            and str(row.get("change_origin") or "") == change_origin
            and self._is_queryable_latest(row)
        ]
        if not candidates:
            return None
        return sorted(candidates, key=self._latest_sort_key, reverse=True)[0]

    def get_latest_by_brand_code_and_origin_including_skipped(
        self,
        *,
        brand_code: str,
        change_origin: str,
    ) -> dict | None:
        candidates = [
            row
            for row in self._rows()
            if str(row.get("brand_code") or "") == brand_code
            and str(row.get("change_origin") or "") == change_origin
        ]
        if not candidates:
            return None
        return sorted(candidates, key=self._version_sort_key, reverse=True)[0]

    def get_latest_by_brand_id(self, *, brand_id: int) -> dict | None:
        candidates = [
            row
            for row in self._rows()
            if int(row.get("brand_id") or 0) == brand_id and self._is_queryable_latest(row)
        ]
        if not candidates:
            return None
        return sorted(candidates, key=self._version_sort_key, reverse=True)[0]

    def get_latest_by_brand_id_and_origin_including_skipped(
        self,
        *,
        brand_id: int,
        change_origin: str,
    ) -> dict | None:
        candidates = [
            row
            for row in self._rows()
            if int(row.get("brand_id") or 0) == brand_id
            and str(row.get("change_origin") or "") == change_origin
        ]
        if not candidates:
            return None
        return sorted(candidates, key=self._latest_sort_key, reverse=True)[0]

    def get_latest_by_brand_id_and_origin(self, *, brand_id: int, change_origin: str) -> dict | None:
        candidates = [
            row
            for row in self._rows()
            if int(row.get("brand_id") or 0) == brand_id
            and str(row.get("change_origin") or "") == change_origin
            and self._is_queryable_latest(row)
        ]
        if not candidates:
            return None
        return sorted(candidates, key=self._latest_sort_key, reverse=True)[0]

    def get_next_version_no_by_brand_code(self, *, brand_code: str) -> int:
        if brand_code == "BR001":
            return 2
        return 1

    def get_next_version_no(self, *, brand_id: int) -> int:
        return 2

    def get_next_revision_no(self, *, brand_code: str, version_no: int, knowledge_date: str) -> int:
        revisions = [
            int(row.get("revision_no") or 0)
            for row in self._rows()
            if str(row.get("brand_code") or "") == brand_code
            and int(row.get("version_no") or 0) == int(version_no)
            and str(row.get("knowledge_date") or "") == knowledge_date
        ]
        return (max(revisions) if revisions else 0) + 1

    def get_by_ids(self, *, file_ids: list[int]) -> dict[int, dict]:
        result: dict[int, dict] = {}
        for file_id in file_ids:
            if file_id == 99:
                result[file_id] = {
                    "id": 99,
                    "file_name": "【测试品牌】品牌AI知识库_V2_20260715.md",
                    "oss_key": "knowledge/md",
                    "oss_url": "https://oss.example.com/knowledge.md",
                    "pdf_oss_url": "https://oss.example.com/knowledge.pdf",
                    "document_id": "brandkb:BR001:V2:20260715:R1",
                }
            for row in self.created_rows:
                if row.get("id") == file_id:
                    result[file_id] = dict(row)
        return result

    def create_brand_full_knowledge_file(self, **kwargs) -> int:
        file_id = 100 + len(self.created_rows)
        row = {"id": file_id, **kwargs}
        self.created_rows.append(row)
        return file_id


class _FakeIngestionService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def ingest_upload_task_file(self, **kwargs) -> dict:
        call = dict(kwargs)
        staged_path = call.get("staged_path")
        if isinstance(staged_path, Path) and staged_path.exists():
            call["staged_markdown"] = staged_path.read_text(encoding="utf-8")
        self.calls.append(call)
        return {
            "status": "success",
            "skipped": False,
            "document_id": "brandkb:BR001:V2:20260715:R1",
            "full_knowledge_file_id": 99,
            "markdown_oss_key": "knowledge/md",
            "markdown_oss_url": "https://oss.example.com/knowledge.md",
            "pdf_oss_url": "https://oss.example.com/knowledge.pdf",
        }


class _FakeParser:
    def parse_path(self, *_args, **_kwargs):
        return types.SimpleNamespace(markdown_text="# 解析结果", source_type="pdf")


class _FakeEmbeddings:
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[float(index + 1)] * 3 for index, _ in enumerate(texts)]


class _FakeVectorStore:
    def __init__(self) -> None:
        self.upserted_facts: list[dict] = []
        self.deleted_fact_ids: list[str] = []

    def upsert_facts(self, facts_data: list[dict], *, partial_update: bool = False) -> None:
        self.upserted_facts.append(
            {
                "facts_data": list(facts_data),
                "partial_update": partial_update,
            }
        )

    def delete_facts_by_ids(self, fact_ids: list[str]) -> None:
        self.deleted_fact_ids.extend(fact_ids)


class _FakeBrandFactsStore:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def upsert_fact(self, **kwargs) -> None:
        row = dict(kwargs)
        self.rows = [
            item
            for item in self.rows
            if str(item.get("normalized_fact_hash") or "") != str(row.get("normalized_fact_hash") or "")
        ]
        self.rows.append(row)

    def list_by_source_task_id_and_scope(self, *, source_task_id: str, fact_scope: str) -> list[dict]:
        return [
            dict(item)
            for item in self.rows
            if item.get("source_task_id") == source_task_id and item.get("fact_scope") == fact_scope
        ]

    def delete_by_source_task_id_and_scope(self, *, source_task_id: str, fact_scope: str) -> int:
        before = len(self.rows)
        self.rows = [
            item
            for item in self.rows
            if not (item.get("source_task_id") == source_task_id and item.get("fact_scope") == fact_scope)
        ]
        return before - len(self.rows)


class _FakeConflictResolutionEnqueuer:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def __call__(self, **kwargs) -> dict:
        self.calls.append(dict(kwargs))
        session_id = str(kwargs.get("session_id") or "").strip()
        return {
            "job_id": f"bg:attachment_conflict_resolution:{session_id}",
            "status": "waiting",
        }


class _FailingConflictResolutionEnqueuer:
    async def __call__(self, **_kwargs) -> dict:
        raise TypeError("enqueue failed")


class BrandAttachmentConflictSessionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.session_store = _FakeSessionStore()
        self.ingestion_service = _FakeIngestionService()
        self.vector_store = _FakeVectorStore()
        self.brand_facts_store = _FakeBrandFactsStore()
        self.conflict_resolution_enqueuer = _FakeConflictResolutionEnqueuer()
        self.service = BrandKnowledgeApplicationService(
            BrandKnowledgeApplicationDependencies(
                settings=types.SimpleNamespace(max_upload_size_mb=50),
                brands=_FakeBrands(),
                brand_knowledge_sessions=self.session_store,
                document_registry=types.SimpleNamespace(),
                store=self.vector_store,
                get_full_text=lambda _document_id: "",
                upload_tasks=_FakeUploadTasks(),
                attachment_assets=_FakeAttachmentAssets(),
                brand_full_knowledge=_FakeFullKnowledgeStore(),
                brand_ai_knowledge_ingestion=self.ingestion_service,
                oss_client=_FakeOSSClient(),
                parser=_FakeParser(),
                embeddings=_FakeEmbeddings(),
                brand_knowledge_facts=self.brand_facts_store,
                enqueue_attachment_conflict_resolution_job=self.conflict_resolution_enqueuer,
            )
        )

    async def test_start_attachment_conflict_session_returns_conflicts_and_auto_merged(self) -> None:
        original_scan = brand_knowledge_service_module.scan_brand_knowledge_conflicts
        original_extract_facts = facts_module.extract_facts_from_text

        async def fake_scan_brand_knowledge_conflicts(**_kwargs):
            return {
                "status": "waiting_user_input",
                "scan_summary": "扫描完成",
                "conflicts": [
                    {
                        "conflict_id": "C-BRAND-001",
                        "topic": "主体名称冲突",
                        "severity": "hard",
                        "description": "需要人工确认",
                        "options": [
                            {"option_id": "A", "content": "口径A", "source_files": ["资料一.md"]},
                            {"option_id": "B", "content": "口径B", "source_files": ["资料一.md"]},
                        ],
                    }
                ],
                "auto_merged": [
                    {
                        "topic": "网址归一化",
                        "category": "format",
                        "resolution": "统一保留官网主域名",
                        "source_files": ["资料一.md"],
                    }
                ],
            }

        async def fake_extract_facts_from_text(*_args, **_kwargs):
            return '[{"基础信息":["测试品牌官网为 https://example.com"]}]'

        brand_knowledge_service_module.scan_brand_knowledge_conflicts = fake_scan_brand_knowledge_conflicts
        facts_module.extract_facts_from_text = fake_extract_facts_from_text
        try:
            result = await self.service.start_attachment_conflict_session(task_id="task-1")
        finally:
            brand_knowledge_service_module.scan_brand_knowledge_conflicts = original_scan
            facts_module.extract_facts_from_text = original_extract_facts

        self.assertEqual(result["status"], "waiting_user_input")
        self.assertEqual(result["brand_code"], "BR001")
        self.assertEqual(result["source_task_id"], "task-1")
        self.assertEqual(len(result["conflicts"]), 1)
        self.assertEqual(result["conflicts"][0]["conflict_id"], "C-BRAND-001")
        self.assertEqual(result["conflicts"][0]["severity"], "hard")
        self.assertEqual(result["conflicts"][0]["topic"], "主体名称冲突")
        self.assertEqual(result["scan_summary"], "扫描完成")
        self.assertEqual(len(result["auto_merged"]), 1)
        self.assertEqual(result["source_documents"][0]["asset_id"], 21)
        self.assertEqual(self.brand_facts_store.rows, [])
        self.assertEqual(self.vector_store.upserted_facts, [])

    async def test_start_knowledge_iteration_instruction_only_generates_draft_file(self) -> None:
        captured_kwargs: dict = {}
        original_generate_patch = brand_knowledge_service_module.generate_brand_knowledge_patch_markdown
        full_knowledge_store = self.service._deps.brand_full_knowledge
        full_knowledge_store.latest_row = {
            **full_knowledge_store.latest_row,
            "id": 89,
            "version_no": 2,
            "file_name": "【测试品牌】品牌AI知识库_V2_20260716.md",
            "content_markdown": "# API生成知识库\n接口自动更新内容\n\n# 后续章节\n必须保留",
        }

        async def fake_generate_brand_knowledge_patch_markdown(**kwargs):
            captured_kwargs.update(kwargs)
            return {
                "status": "completed",
                "final_markdown": "# API生成知识库\n接口自动更新内容\n加入露营服务\n\n# 后续章节\n必须保留",
                "conflicts": [],
                "conflict_markdown": "",
                "patch_operations": [
                    {
                        "op": "append_to_section",
                        "target_heading": "# API生成知识库",
                        "content": "加入露营服务",
                    }
                ],
            }

        brand_knowledge_service_module.generate_brand_knowledge_patch_markdown = fake_generate_brand_knowledge_patch_markdown
        try:
            result = await self.service.start_knowledge_iteration_session(
                brand_code="BR001",
                iteration_mode="instruction_only",
                update_instruction="新增露营服务信息",
            )
        finally:
            brand_knowledge_service_module.generate_brand_knowledge_patch_markdown = original_generate_patch

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["session_type"], "knowledge_iteration")
        self.assertEqual(result["iteration_mode"], "instruction_only")
        self.assertEqual(
            result["final_markdown"],
            "# API生成知识库\n接口自动更新内容\n加入露营服务\n\n# 后续章节\n必须保留",
        )
        self.assertEqual(captured_kwargs["base_knowledge_markdown"], "# 旧版知识库\n旧内容")
        self.assertEqual(captured_kwargs["markdown_sources"][0]["source_role"], "iteration_instruction")
        self.assertIn("新增露营服务信息", captured_kwargs["markdown_sources"][0]["markdown_text"])
        self.assertEqual(self.ingestion_service.calls, [])
        self.assertEqual(len(full_knowledge_store.created_rows), 1)
        created_row = full_knowledge_store.created_rows[0]
        self.assertIn("【测试品牌】品牌AI知识库_V2_", created_row["file_name"])
        self.assertIn("加入露营服务", created_row["content_markdown"])
        self.assertIn("# 后续章节\n必须保留", created_row["content_markdown"])
        self.assertEqual(created_row["change_origin"], "frontend")
        self.assertEqual(created_row["ingest_status"], "skipped")
        self.assertEqual(created_row["milvus_status"], "skipped")
        self.assertEqual(created_row["facts_status"], "skipped")
        self.assertIsNone(created_row["document_id"])
        self.assertEqual(result["final_full_knowledge_file_id"], created_row["id"])
        self.assertIsNone(result["final_document_id"])
        self.assertTrue(result["knowledge_oss_url_md"].startswith("https://oss.example.com/"))
        draft_by_id = full_knowledge_store.get_by_ids(file_ids=[created_row["id"]])[created_row["id"]]
        self.assertEqual(draft_by_id["content_markdown"], created_row["content_markdown"])
        self.assertEqual(draft_by_id["ingest_status"], "skipped")
        latest_official = full_knowledge_store.get_latest_by_brand_code(brand_code="BR001")
        assert latest_official is not None
        self.assertEqual(latest_official["id"], 88)
        self.assertEqual(latest_official["content_markdown"], "# 旧版知识库\n旧内容")
        latest_frontend = full_knowledge_store.get_latest_by_brand_code_and_origin(
            brand_code="BR001",
            change_origin="frontend",
        )
        assert latest_frontend is not None
        self.assertEqual(latest_frontend["id"], 88)
        self.assertEqual(full_knowledge_store.get_next_version_no_by_brand_code(brand_code="BR001"), 2)

    async def test_start_knowledge_iteration_with_attachments_processes_all_instruction_urls(self) -> None:
        expected_urls = [f"https://example.com/article-{index}" for index in range(1, 7)]
        captured_kwargs: dict = {}

        class FakeResponse:
            headers = {"content-type": "text/html; charset=utf-8"}
            text = "<html><title>Article</title><body><p>Article body</p></body></html>"

            def raise_for_status(self) -> None:
                return None

        async def fake_generate_patch(**kwargs):
            captured_kwargs.update(kwargs)
            return {
                "status": "completed",
                "final_markdown": "# 旧版知识库\n旧内容\nArticle body",
                "conflicts": [],
                "conflict_markdown": "",
                "patch_operations": [
                    {"op": "append_to_section", "target_heading": "# 旧版知识库", "content": "Article body"}
                ],
            }

        with (
            patch(
                "knowledge_base.brand_knowledge.application.instruction_web_sources.requests.get",
                side_effect=lambda *_args, **_kwargs: FakeResponse(),
            ),
            patch.object(brand_knowledge_service_module, "generate_brand_knowledge_patch_markdown", fake_generate_patch),
        ):
            result = await self.service.start_knowledge_iteration_session(
                brand_code="BR001",
                task_id="task-1",
                iteration_mode="attachments_with_instruction",
                update_instruction=" ".join(expected_urls),
            )

        self.assertEqual(result["status"], "completed")
        session = self.session_store.sessions[result["session_id"]]
        web_documents = [
            source for source in session["source_documents_json"] if source.get("source_type") == "web_article"
        ]
        web_markdown_sources = [
            source
            for source in captured_kwargs["markdown_sources"]
            if source.get("source_role") == "iteration_web_article"
        ]
        self.assertEqual([source["source_url"] for source in web_documents], expected_urls)
        self.assertEqual([source["source_url"] for source in web_markdown_sources], expected_urls)
        self.assertTrue(
            any(source.get("source_role") == "iteration_instruction" for source in captured_kwargs["markdown_sources"])
        )

    async def test_start_knowledge_iteration_instruction_only_adds_fetched_url_sources(self) -> None:
        captured_kwargs: dict = {}
        original_generate_patch = brand_knowledge_service_module.generate_brand_knowledge_patch_markdown
        original_build_web_sources = brand_knowledge_service_module.build_instruction_web_markdown_sources

        async def fake_build_instruction_web_markdown_sources(instruction: str):
            self.assertIn("http://city.ce.cn/xx/202608/t20260804_3128272.shtml", instruction)
            markdown_text = (
                "# 网页正文：官方报道标题\n\n"
                "- 来源链接：http://city.ce.cn/xx/202608/t20260804_3128272.shtml\n\n"
                "## 正文\n\n"
                "官方报道正文内容"
            )
            return [
                {
                    "document_id": "iteration_url:abc123",
                    "original_filename": "官方报道标题.md",
                    "source_type": "web_article",
                    "source_role": "iteration_web_article",
                    "source_url": "http://city.ce.cn/xx/202608/t20260804_3128272.shtml",
                    "markdown_text": markdown_text,
                }
            ], [
                {
                    "source_name": "官方报道标题.md",
                    "subcategory": "网页正文",
                    "source_role": "iteration_web_article",
                    "source_url": "http://city.ce.cn/xx/202608/t20260804_3128272.shtml",
                    "markdown_text": markdown_text,
                }
            ]

        async def fake_generate_brand_knowledge_patch_markdown(**kwargs):
            captured_kwargs.update(kwargs)
            return {
                "status": "completed",
                "final_markdown": "# 旧版知识库\n官方报道正文内容",
                "conflicts": [],
                "conflict_markdown": "",
                "patch_operations": [
                    {
                        "op": "append_to_section",
                        "target_heading": "# 旧版知识库",
                        "content": "官方报道正文内容",
                    }
                ],
            }

        brand_knowledge_service_module.build_instruction_web_markdown_sources = (
            fake_build_instruction_web_markdown_sources
        )
        brand_knowledge_service_module.generate_brand_knowledge_patch_markdown = fake_generate_brand_knowledge_patch_markdown
        try:
            result = await self.service.start_knowledge_iteration_session(
                brand_code="BR001",
                iteration_mode="instruction_only",
                update_instruction=(
                    "删除涉及赶海的内容；增加官方报道文章："
                    "http://city.ce.cn/xx/202608/t20260804_3128272.shtml"
                ),
            )
        finally:
            brand_knowledge_service_module.generate_brand_knowledge_patch_markdown = original_generate_patch
            brand_knowledge_service_module.build_instruction_web_markdown_sources = original_build_web_sources

        self.assertEqual(result["status"], "completed")
        self.assertEqual(captured_kwargs["markdown_sources"][0]["source_role"], "iteration_instruction")
        self.assertEqual(captured_kwargs["markdown_sources"][1]["source_role"], "iteration_web_article")
        self.assertIn("官方报道正文内容", captured_kwargs["markdown_sources"][1]["markdown_text"])
        session = self.session_store.sessions[result["session_id"]]
        source_documents = session["source_documents_json"]
        self.assertEqual(source_documents[1]["source_role"], "iteration_instruction")
        self.assertEqual(source_documents[2]["source_role"], "iteration_web_article")
        self.assertIn("官方报道正文内容", source_documents[2]["markdown_text"])

    async def test_start_knowledge_iteration_waits_for_user_when_any_url_fetch_fails(self) -> None:
        original_generate_patch = brand_knowledge_service_module.generate_brand_knowledge_patch_markdown
        original_build_web_sources = brand_knowledge_service_module.build_instruction_web_markdown_sources

        async def fake_build_instruction_web_markdown_sources(_instruction: str):
            success_markdown = (
                "# 网页正文：成功报道\n\n"
                "- 来源链接：https://ok.example.com/news\n\n"
                "## 正文\n\n"
                "成功链接正文"
            )
            return [
                {
                    "document_id": "iteration_url:ok123",
                    "original_filename": "成功报道.md",
                    "source_type": "web_article",
                    "source_role": "iteration_web_article",
                    "source_url": "https://ok.example.com/news",
                    "markdown_text": success_markdown,
                },
                {
                    "document_id": "iteration_url_failed:fail123",
                    "original_filename": "链接内容提取失败-failed.example.com-2",
                    "source_type": "web_article_error",
                    "source_role": "iteration_web_article_error",
                    "source_url": "https://failed.example.com/news",
                    "error_message": "链接内容提取失败，请复制链接内容到文字要求框",
                    "error_type": "TimeoutError",
                },
            ], [
                {
                    "source_name": "成功报道.md",
                    "subcategory": "网页正文",
                    "source_role": "iteration_web_article",
                    "source_url": "https://ok.example.com/news",
                    "markdown_text": success_markdown,
                }
            ]

        async def fake_generate_brand_knowledge_patch_markdown(**_kwargs):
            raise AssertionError("存在失败链接时不应生成新版知识库")

        brand_knowledge_service_module.build_instruction_web_markdown_sources = (
            fake_build_instruction_web_markdown_sources
        )
        brand_knowledge_service_module.generate_brand_knowledge_patch_markdown = fake_generate_brand_knowledge_patch_markdown
        try:
            result = await self.service.start_knowledge_iteration_session(
                brand_code="BR001",
                iteration_mode="instruction_only",
                update_instruction=(
                    "增加两个报道链接：https://ok.example.com/news https://failed.example.com/news"
                ),
            )
        finally:
            brand_knowledge_service_module.generate_brand_knowledge_patch_markdown = original_generate_patch
            brand_knowledge_service_module.build_instruction_web_markdown_sources = original_build_web_sources

        self.assertEqual(result["status"], "waiting_user_input")
        self.assertIsNone(result["final_markdown"])
        self.assertIn("以下链接内容提取失败", result["assistant_message"])
        self.assertIn("https://failed.example.com/news", result["assistant_message"])
        self.assertEqual(self.service._deps.brand_full_knowledge.created_rows, [])
        session = self.session_store.sessions[result["session_id"]]
        source_documents = session["source_documents_json"]
        self.assertEqual(source_documents[1]["source_role"], "iteration_instruction")
        self.assertEqual(source_documents[2]["source_role"], "iteration_web_article")
        self.assertEqual(source_documents[3]["source_role"], "iteration_web_article_error")
        self.assertEqual(source_documents[3]["error_message"], "链接内容提取失败，请复制链接内容到文字要求框")
        self.assertEqual(self.session_store.rounds[-1]["stage"], "web_source_extract")
        self.assertLessEqual(len(self.session_store.rounds[-1]["stage"]), 32)
        self.assertEqual(self.session_store.rounds[-1]["response_payload"]["status"], "waiting_user_input")

    async def test_start_knowledge_iteration_draft_uses_latest_frontend_draft_as_base_and_next_version(self) -> None:
        original_generate_patch = brand_knowledge_service_module.generate_brand_knowledge_patch_markdown
        full_knowledge_store = self.service._deps.brand_full_knowledge
        captured_base_markdowns: list[str] = []
        full_knowledge_store.frontend_row = {
            **full_knowledge_store.frontend_row,
            "id": 333,
            "version_no": 6,
            "knowledge_date": "20260907",
            "revision_no": 1,
            "file_name": "【测试品牌】品牌AI知识库_V6_20260907.md",
            "content_markdown": "# 正式V6\n正式旧内容",
        }
        full_knowledge_store.created_rows.append(
            {
                "id": 344,
                "brand_id": 7,
                "brand_code": "BR001",
                "brand_name": "测试品牌",
                "version_no": 7,
                "knowledge_date": "20261008",
                "revision_no": 1,
                "file_name": "【测试品牌】品牌AI知识库_V7_20261008.md",
                "content_markdown": "# 草稿V7\n上一版草稿内容",
                "document_id": None,
                "is_latest": False,
                "ingest_status": "skipped",
                "change_origin": "frontend",
            }
        )

        async def fake_generate_brand_knowledge_patch_markdown(**kwargs):
            captured_base_markdowns.append(kwargs["base_knowledge_markdown"])
            return {
                "status": "completed",
                "final_markdown": "# 草稿V8\n基于上一版草稿继续更新",
                "conflicts": [],
                "conflict_markdown": "",
                "patch_operations": [],
            }

        brand_knowledge_service_module.generate_brand_knowledge_patch_markdown = fake_generate_brand_knowledge_patch_markdown
        try:
            await self.service.start_knowledge_iteration_session(
                brand_code="BR001",
                iteration_mode="instruction_only",
                update_instruction="继续基于草稿迭代",
            )
        finally:
            brand_knowledge_service_module.generate_brand_knowledge_patch_markdown = original_generate_patch

        self.assertEqual(captured_base_markdowns, ["# 草稿V7\n上一版草稿内容"])
        created_row = full_knowledge_store.created_rows[-1]
        self.assertEqual(created_row["version_no"], 8)
        self.assertEqual(created_row["revision_no"], 1)
        self.assertIn("【测试品牌】品牌AI知识库_V8_", created_row["file_name"])
        oss_client = self.service._deps.oss_client
        self.assertIn("【测试品牌】品牌AI知识库_V8_", oss_client.uploaded_bytes[-1]["object_key"])
        self.assertNotIn("_R2.md", oss_client.uploaded_bytes[-1]["object_key"])

    async def test_attachment_conflict_resolution_draft_only_uploads_without_ingestion_or_callback(self) -> None:
        original_generate = brand_knowledge_service_module.generate_brand_knowledge_patch_markdown
        full_knowledge_store = self.service._deps.brand_full_knowledge

        async def fake_generate_brand_knowledge_patch_markdown(**_kwargs):
            return {
                "status": "completed",
                "final_markdown": "# 旧版知识库\n旧内容\n\n# 最终知识库\n草稿内容",
            }

        self.session_store.create_session(
            session_id="bks_draft",
            brand_id=7,
            brand_code="BR001",
            brand_name="测试品牌",
            source_task_id="task-1",
            session_kind="attachment_conflict:draft_only",
            status="no_conflicts",
            current_round=1,
            initial_user_message="生成草稿",
            latest_user_message="生成草稿",
            latest_assistant_message="扫描完成",
            source_documents=[
                {
                    "document_id": "doc-1",
                    "original_filename": "资料一.md",
                    "source_type": "attachment",
                    "source_role": "attachment",
                    "markdown_text": "# 资料一\n草稿来源",
                }
            ],
        )
        brand_knowledge_service_module.generate_brand_knowledge_patch_markdown = fake_generate_brand_knowledge_patch_markdown
        try:
            result = await self.service.process_attachment_conflict_resolution_job(
                payload={
                    "session_id": "bks_draft",
                    "brand_code": "BR001",
                    "brand_name": "测试品牌",
                    "source_task_id": "task-1",
                    "submitted_round_no": 1,
                    "generation_round_no": 2,
                    "history_resolutions": [],
                    "current_resolutions": [],
                    "auto_merged": [],
                    "force_reingest": False,
                    "publish_mode": "draft_only",
                }
            )
        finally:
            brand_knowledge_service_module.generate_brand_knowledge_patch_markdown = original_generate

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["knowledge_oss_url_pdf"], None)
        self.assertEqual(self.ingestion_service.calls, [])
        self.assertEqual(self.service._deps.upload_tasks.callback_rows, {})
        self.assertEqual(len(full_knowledge_store.created_rows), 1)
        created_row = full_knowledge_store.created_rows[0]
        self.assertEqual(created_row["ingest_status"], "skipped")
        self.assertEqual(created_row["milvus_status"], "skipped")
        self.assertEqual(created_row["facts_status"], "skipped")
        self.assertIsNone(created_row["document_id"])
        self.assertEqual(created_row["content_markdown"], "# 旧版知识库\n旧内容\n\n# 最终知识库\n草稿内容")

    async def test_start_attachment_conflict_session_scans_with_external_enrichment_as_supplement(self) -> None:
        captured_source_roles: list[list[str]] = []
        original_scan = brand_knowledge_service_module.scan_brand_knowledge_conflicts
        original_extract_facts = facts_module.extract_facts_from_text
        original_build_snapshot = brand_knowledge_service_module.build_brand_knowledge_snapshot_from_markdown
        service = BrandKnowledgeApplicationService(
            BrandKnowledgeApplicationDependencies(
                settings=types.SimpleNamespace(max_upload_size_mb=50),
                brands=_FakeBrands(),
                brand_knowledge_sessions=self.session_store,
                document_registry=types.SimpleNamespace(),
                brand_products=object(),
                store=self.vector_store,
                get_full_text=lambda _document_id: "",
                upload_tasks=_FakeUploadTasks(),
                attachment_assets=_FakeAttachmentAssets(),
                brand_full_knowledge=_FakeFullKnowledgeStore(),
                brand_ai_knowledge_ingestion=self.ingestion_service,
                oss_client=_FakeOSSClient(),
                parser=_FakeParser(),
                embeddings=_FakeEmbeddings(),
                brand_knowledge_facts=self.brand_facts_store,
                enqueue_attachment_conflict_resolution_job=self.conflict_resolution_enqueuer,
            )
        )

        async def fake_scan_brand_knowledge_conflicts(**kwargs):
            captured_source_roles.append(
                [str(item.get("source_role") or "") for item in kwargs.get("markdown_sources", [])]
            )
            return {
                "status": "waiting_user_input",
                "scan_summary": "扫描完成",
                "conflicts": [
                    {
                        "conflict_id": "C-BRAND-001",
                        "topic": "主体名称冲突",
                        "severity": "hard",
                        "description": "需要人工确认",
                        "options": [
                            {"option_id": "A", "content": "口径A", "source_files": ["资料一.md"]},
                        ],
                    }
                ],
                "auto_merged": [
                    {
                        "topic": "外部官网口径与附件不同",
                        "category": "authority",
                        "resolution": "附件优先，补充来源仅作参考",
                        "source_files": ["资料一.md", "测试品牌-天眼查与联网回补.md"],
                    }
                ],
            }

        async def fake_extract_facts_from_text(*_args, **_kwargs):
            return '[{"基础信息":["测试品牌官网为 https://example.com"]}]'

        brand_knowledge_service_module.scan_brand_knowledge_conflicts = fake_scan_brand_knowledge_conflicts
        facts_module.extract_facts_from_text = fake_extract_facts_from_text
        brand_knowledge_service_module.build_brand_knowledge_snapshot_from_markdown = AsyncMock(
            return_value={
                "snapshot": {
                    "basic_info": {"brand_name": "测试品牌"},
                    "products": [],
                    "company_profile": {},
                    "management_team": [],
                    "competitors": [],
                    "authority_honors": [],
                    "customers_cases": [],
                    "sensitive_topics": [],
                    "attachments": [],
                    "official_malls": [],
                    "official_media_matrix": [],
                    "other_info": [],
                },
                "supplemental_markdown_sources": [
                    {
                        "source_name": "测试品牌-天眼查与联网回补.md",
                        "subcategory": "external_enrichment",
                        "source_role": "external_enrichment",
                        "markdown_text": "# 测试品牌 天眼查与联网回补补充信息\n- 官网: https://fallback.example.com",
                    }
                ],
            }
        )
        try:
            result = await service.start_attachment_conflict_session(task_id="task-1")
        finally:
            brand_knowledge_service_module.scan_brand_knowledge_conflicts = original_scan
            facts_module.extract_facts_from_text = original_extract_facts
            brand_knowledge_service_module.build_brand_knowledge_snapshot_from_markdown = original_build_snapshot

        self.assertEqual(result["status"], "waiting_user_input")
        self.assertEqual(
            captured_source_roles,
            [["attachment_asset", "external_enrichment"]],
        )

    async def test_start_attachment_conflict_session_sends_waiting_callback(self) -> None:
        original_scan = brand_knowledge_service_module.scan_brand_knowledge_conflicts

        async def fake_scan_brand_knowledge_conflicts(**_kwargs):
            return {
                "status": "waiting_user_input",
                "scan_summary": "扫描完成",
                "conflicts": [
                    {
                        "conflict_id": "C-BRAND-001",
                        "topic": "主体名称冲突",
                        "severity": "hard",
                        "description": "需要人工确认",
                        "options": [
                            {"option_id": "A", "content": "口径A", "source_files": ["资料一.md"]},
                        ],
                    }
                ],
                "auto_merged": [],
            }

        async def fake_extract_facts_from_text(*_args, **_kwargs):
            return '[{"基础信息":["测试品牌官网为 https://example.com"]}]'

        session_store = _FakeSessionStore()
        upload_tasks = _FakeUploadTasks()
        service = BrandKnowledgeApplicationService(
            BrandKnowledgeApplicationDependencies(
                settings=types.SimpleNamespace(
                    max_upload_size_mb=50,
                    brand_completion_callback_url="https://callback.example.com/hook",
                    brand_completion_callback_timeout_seconds=5.0,
                ),
                brands=_FakeBrands(),
                brand_knowledge_sessions=session_store,
                document_registry=types.SimpleNamespace(),
                store=_FakeVectorStore(),
                get_full_text=lambda _document_id: "",
                upload_tasks=upload_tasks,
                attachment_assets=_FakeAttachmentAssets(),
                brand_full_knowledge=_FakeFullKnowledgeStore(),
                brand_ai_knowledge_ingestion=_FakeIngestionService(),
                oss_client=_FakeOSSClient(),
                parser=_FakeParser(),
                embeddings=_FakeEmbeddings(),
                brand_knowledge_facts=_FakeBrandFactsStore(),
                runtime=types.SimpleNamespace(scheduled_attachment_conflict_callback_retries=set()),
                spawn_background_task=lambda coro: coro.close(),
                build_current_brand_callback_knowledge=lambda *, brand_code: None,
            )
        )

        brand_knowledge_service_module.scan_brand_knowledge_conflicts = fake_scan_brand_knowledge_conflicts
        original_extract_facts = facts_module.extract_facts_from_text
        facts_module.extract_facts_from_text = fake_extract_facts_from_text
        try:
            with patch.object(
                brand_knowledge_service_module.requests,
                "post",
                return_value=types.SimpleNamespace(status_code=200, text="ok"),
            ):
                result = await service.start_attachment_conflict_session(task_id="task-1")
        finally:
            brand_knowledge_service_module.scan_brand_knowledge_conflicts = original_scan
            facts_module.extract_facts_from_text = original_extract_facts

        self.assertEqual(result["status"], "waiting_user_input")
        self.assertEqual(len(upload_tasks.callback_rows), 1)
        callback = next(iter(upload_tasks.callback_rows.values()))
        self.assertEqual(callback["callback_type"], brand_knowledge_service_module.ATTACHMENT_CONFLICT_WAITING_CALLBACK_TYPE)
        self.assertEqual(callback["status"], "success")
        self.assertEqual(callback["request_payload_json"]["brand_code"], "BR001")
        self.assertEqual(callback["request_payload_json"]["overall_status"], "waiting_user_input")
        self.assertNotIn("knowledge", callback["request_payload_json"])

    async def test_start_attachment_conflict_session_draft_only_skips_waiting_callback(self) -> None:
        original_scan = brand_knowledge_service_module.scan_brand_knowledge_conflicts
        original_extract_facts = facts_module.extract_facts_from_text

        async def fake_scan_brand_knowledge_conflicts(**_kwargs):
            return {
                "status": "waiting_user_input",
                "scan_summary": "扫描完成",
                "conflicts": [
                    {
                        "conflict_id": "C-BRAND-001",
                        "topic": "主体名称冲突",
                        "severity": "hard",
                        "description": "需要人工确认",
                        "options": [
                            {"option_id": "A", "content": "口径A", "source_files": ["资料一.md"]},
                        ],
                    }
                ],
                "auto_merged": [],
            }

        async def fake_extract_facts_from_text(*_args, **_kwargs):
            return '[{"基础信息":["测试品牌官网为 https://example.com"]}]'

        upload_tasks = _FakeUploadTasks()
        service = BrandKnowledgeApplicationService(
            BrandKnowledgeApplicationDependencies(
                settings=types.SimpleNamespace(
                    max_upload_size_mb=50,
                    brand_completion_callback_url="https://callback.example.com/hook",
                    brand_completion_callback_timeout_seconds=5.0,
                ),
                brands=_FakeBrands(),
                brand_knowledge_sessions=_FakeSessionStore(),
                document_registry=types.SimpleNamespace(),
                store=_FakeVectorStore(),
                get_full_text=lambda _document_id: "",
                upload_tasks=upload_tasks,
                attachment_assets=_FakeAttachmentAssets(),
                brand_full_knowledge=_FakeFullKnowledgeStore(),
                brand_ai_knowledge_ingestion=_FakeIngestionService(),
                oss_client=_FakeOSSClient(),
                parser=_FakeParser(),
                embeddings=_FakeEmbeddings(),
                brand_knowledge_facts=_FakeBrandFactsStore(),
                runtime=types.SimpleNamespace(scheduled_attachment_conflict_callback_retries=set()),
                spawn_background_task=lambda coro: coro.close(),
                build_current_brand_callback_knowledge=lambda *, brand_code: None,
            )
        )

        brand_knowledge_service_module.scan_brand_knowledge_conflicts = fake_scan_brand_knowledge_conflicts
        facts_module.extract_facts_from_text = fake_extract_facts_from_text
        try:
            with patch.object(brand_knowledge_service_module.requests, "post") as post_mock:
                result = await service.start_attachment_conflict_session(
                    task_id="task-1",
                    publish_mode="draft_only",
                )
        finally:
            brand_knowledge_service_module.scan_brand_knowledge_conflicts = original_scan
            facts_module.extract_facts_from_text = original_extract_facts

        self.assertEqual(result["status"], "waiting_user_input")
        self.assertEqual(result["session_kind"], "attachment_conflict:draft_only")
        self.assertEqual(upload_tasks.callback_rows, {})
        post_mock.assert_not_called()

    async def test_start_attachment_conflict_session_auto_enqueues_when_no_conflicts(self) -> None:
        original_scan = brand_knowledge_service_module.scan_brand_knowledge_conflicts
        original_extract_facts = facts_module.extract_facts_from_text

        async def fake_scan_brand_knowledge_conflicts(**_kwargs):
            return {
                "status": "no_conflicts",
                "scan_summary": "扫描完成，无需人工确认",
                "conflicts": [],
                "auto_merged": [
                    {
                        "topic": "网址归一化",
                        "category": "format",
                        "resolution": "统一保留官网主域名",
                        "source_files": ["资料一.md"],
                    }
                ],
            }

        async def fake_extract_facts_from_text(*_args, **_kwargs):
            return '[{"基础信息":["测试品牌官网为 https://example.com"]}]'

        brand_knowledge_service_module.scan_brand_knowledge_conflicts = fake_scan_brand_knowledge_conflicts
        facts_module.extract_facts_from_text = fake_extract_facts_from_text
        try:
            result = await self.service.start_attachment_conflict_session(task_id="task-1")
        finally:
            brand_knowledge_service_module.scan_brand_knowledge_conflicts = original_scan
            facts_module.extract_facts_from_text = original_extract_facts

        self.assertEqual(result["status"], "running")
        self.assertEqual(result["knowledge_markdown_status"], "running")
        self.assertEqual(result["round_no"], 2)
        self.assertEqual(result["conflicts"], [])
        self.assertEqual(result["scan_summary"], "扫描完成，无需人工确认")
        self.assertIsNone(result["final_full_knowledge_file_id"])
        self.assertIsNone(result["final_document_id"])
        self.assertIsNone(result["knowledge_oss_url_md"])
        self.assertIsNone(result["knowledge_oss_url_pdf"])
        self.assertEqual(len(self.ingestion_service.calls), 0)
        self.assertEqual(self.brand_facts_store.rows, [])
        self.assertEqual(len(self.session_store.get_rounds(result["session_id"])), 1)
        self.assertEqual(len(self.conflict_resolution_enqueuer.calls), 1)
        self.assertEqual(self.conflict_resolution_enqueuer.calls[0]["source_task_id"], "task-1")
        self.assertEqual(self.conflict_resolution_enqueuer.calls[0]["generation_round_no"], 2)
        self.assertEqual(self.conflict_resolution_enqueuer.calls[0]["publish_mode"], "full_ingest")

    async def test_start_attachment_conflict_session_draft_only_auto_enqueue_preserves_publish_mode(self) -> None:
        original_scan = brand_knowledge_service_module.scan_brand_knowledge_conflicts
        original_extract_facts = facts_module.extract_facts_from_text

        async def fake_scan_brand_knowledge_conflicts(**_kwargs):
            return {
                "status": "no_conflicts",
                "scan_summary": "扫描完成，无需人工确认",
                "conflicts": [],
                "auto_merged": [],
            }

        async def fake_extract_facts_from_text(*_args, **_kwargs):
            return '[{"基础信息":["测试品牌官网为 https://example.com"]}]'

        brand_knowledge_service_module.scan_brand_knowledge_conflicts = fake_scan_brand_knowledge_conflicts
        facts_module.extract_facts_from_text = fake_extract_facts_from_text
        try:
            result = await self.service.start_attachment_conflict_session(
                task_id="task-1",
                publish_mode="draft_only",
            )
        finally:
            brand_knowledge_service_module.scan_brand_knowledge_conflicts = original_scan
            facts_module.extract_facts_from_text = original_extract_facts

        self.assertEqual(result["status"], "running")
        self.assertEqual(result["session_kind"], "attachment_conflict:draft_only")
        self.assertEqual(len(self.conflict_resolution_enqueuer.calls), 1)
        self.assertEqual(self.conflict_resolution_enqueuer.calls[0]["publish_mode"], "draft_only")

    async def test_submit_attachment_conflict_resolutions_sends_completed_callback(self) -> None:
        session_id = "bks_test_completed"
        snapshot_payload = {
            "basic_info": {
                "brand_name": "测试品牌",
                "website": ["https://example.com"],
            },
            "products": [],
            "company_profile": {},
            "management_team": [],
            "competitors": [],
            "authority_honors": [],
            "customers_cases": [],
            "sensitive_topics": [],
            "attachments": [
                {
                    "name": "资料一.md",
                    "source_url": "https://example.com/asset-1.md",
                    "type": "attachment_asset",
                }
            ],
            "official_malls": [],
            "official_media_matrix": [],
            "other_info": [],
        }
        self.session_store.sessions[session_id] = {
            "session_id": session_id,
            "brand_id": 7,
            "brand_code": "BR001",
            "brand_name": "测试品牌",
            "source_task_id": "task-1",
            "session_kind": "attachment_conflict",
            "status": "waiting_user_input",
            "current_round": 1,
            "latest_scan_summary": "扫描完成",
            "latest_auto_merged_json": [],
            "latest_conflicts_json": [],
            "latest_conflict_markdown": None,
            "latest_draft_markdown": None,
            "resolution_history_json": [],
            "source_documents_json": [
                {
                    "document_id": "asset_21",
                    "asset_id": 21,
                    "original_filename": "资料一.md",
                    "source_role": "attachment_asset",
                    "subcategory": "产品A",
                    "markdown_text": "# 资料一\n冲突内容A",
                }
            ],
            "final_markdown": None,
            "final_oss_key": None,
            "final_full_knowledge_file_id": None,
            "final_document_id": None,
            "latest_assistant_message": None,
            "latest_user_message": None,
        }

        service = BrandKnowledgeApplicationService(
            BrandKnowledgeApplicationDependencies(
                settings=types.SimpleNamespace(
                    max_upload_size_mb=50,
                    brand_completion_callback_url="https://callback.example.com/hook",
                    brand_completion_callback_timeout_seconds=5.0,
                ),
                brands=_FakeBrands(),
                brand_knowledge_sessions=self.session_store,
                document_registry=types.SimpleNamespace(),
                store=self.vector_store,
                get_full_text=lambda _document_id: "",
                upload_tasks=_FakeUploadTasks(),
                attachment_assets=_FakeAttachmentAssets(),
                brand_full_knowledge=_FakeFullKnowledgeStore(),
                brand_ai_knowledge_ingestion=self.ingestion_service,
                oss_client=_FakeOSSClient(),
                parser=_FakeParser(),
                embeddings=_FakeEmbeddings(),
                brand_knowledge_facts=self.brand_facts_store,
                runtime=types.SimpleNamespace(scheduled_attachment_conflict_callback_retries=set()),
                spawn_background_task=lambda coro: coro.close(),
                build_current_brand_callback_knowledge=lambda *, brand_code: {
                    "basic_info": {"brand_name": "测试品牌", "website": ["https://example.com"]},
                    "attachments": {"files": [{"name": "资料一.md", "url": "https://example.com/asset-1.md"}]},
                },
                enqueue_attachment_conflict_resolution_job=_FakeConflictResolutionEnqueuer(),
            )
        )

        original_generate = brand_knowledge_service_module.generate_brand_knowledge_full_markdown
        original_build_snapshot = brand_knowledge_service_module.build_brand_knowledge_snapshot_from_markdown
        original_persist_snapshot = brand_knowledge_service_module.persist_brand_knowledge_snapshot

        async def fake_generate_brand_knowledge_full_markdown(**_kwargs):
            return {
                "status": "completed",
                "final_markdown": "# 最终知识库\n已确认内容",
            }

        brand_knowledge_service_module.generate_brand_knowledge_full_markdown = fake_generate_brand_knowledge_full_markdown
        brand_knowledge_service_module.build_brand_knowledge_snapshot_from_markdown = AsyncMock(
            return_value={
                "snapshot": snapshot_payload,
                "supplemental_markdown_sources": [
                    {
                        "source_name": "测试品牌-天眼查与联网回补.md",
                        "subcategory": "external_enrichment",
                        "source_role": "external_enrichment",
                        "markdown_text": "# 回补\n- 官网: https://example.com",
                    }
                ],
            }
        )
        brand_knowledge_service_module.persist_brand_knowledge_snapshot = lambda *_args, **_kwargs: {
            "brand": {
                "id": 7,
                "brand_code": "BR001",
                "brand_name": "测试品牌",
                "knowledge_revision": "LXKG-CSPP-V1.0.0-20260717152000",
            },
            "brand_id": 7,
            "knowledge_revision": "LXKG-CSPP-V1.0.0-20260717152000",
            "snapshot": snapshot_payload,
        }
        try:
            result = await service.submit_attachment_conflict_resolutions(
                session_id=session_id,
                round_no=1,
                resolutions=[
                    {
                        "conflict_id": "C-BRAND-001",
                        "decision": "choose_option",
                        "selected_option_id": "A",
                    }
                ],
            )
            self.assertEqual(result["status"], "running")
            self.assertEqual(result["knowledge_markdown_status"], "running")
            self.assertEqual(len(service._deps.upload_tasks.callback_rows), 0)

            with patch.object(
                brand_knowledge_service_module.requests,
                "post",
                return_value=types.SimpleNamespace(status_code=200, text="ok"),
            ):
                job_result = await service.process_attachment_conflict_resolution_job(
                    payload={
                        "session_id": session_id,
                        "brand_code": "BR001",
                        "brand_name": "测试品牌",
                        "source_task_id": "task-1",
                        "submitted_round_no": 1,
                        "generation_round_no": 2,
                        "history_resolutions": [],
                        "current_resolutions": [
                            {
                                "conflict_id": "C-BRAND-001",
                                "decision": "choose_option",
                                "selected_option_id": "A",
                            }
                        ],
                        "auto_merged": [],
                        "force_reingest": False,
                    }
                )
        finally:
            brand_knowledge_service_module.generate_brand_knowledge_full_markdown = original_generate
            brand_knowledge_service_module.build_brand_knowledge_snapshot_from_markdown = original_build_snapshot
            brand_knowledge_service_module.persist_brand_knowledge_snapshot = original_persist_snapshot

        self.assertEqual(job_result["status"], "completed")
        self.assertEqual(len(service._deps.upload_tasks.callback_rows), 1)
        callback = next(iter(service._deps.upload_tasks.callback_rows.values()))
        self.assertEqual(callback["callback_type"], brand_knowledge_service_module.ATTACHMENT_CONFLICT_COMPLETED_CALLBACK_TYPE)
        self.assertEqual(callback["status"], "success")
        self.assertEqual(callback["request_payload_json"]["overall_status"], "completed")
        self.assertEqual(callback["request_payload_json"]["knowledge_mete"]["oss_url_md"], "https://oss.example.com/knowledge.md")
        self.assertEqual(
            callback["request_payload_json"]["knowledge_mete"]["version"],
            "LXKG-CSPP-V1.0.0-20260717152000",
        )
        self.assertIn("knowledge", callback["request_payload_json"])
        self.assertEqual(callback["request_payload_json"]["knowledge"]["basic_info"]["brand_name"], "测试品牌")
        self.assertEqual(
            callback["request_payload_json"]["knowledge"]["attachments"]["files"][0]["url"],
            "https://example.com/asset-1.md",
        )

    async def test_submit_attachment_conflict_resolutions_rolls_back_when_enqueue_fails(self) -> None:
        session_id = "bks_enqueue_fails"
        self.session_store.sessions[session_id] = {
            "session_id": session_id,
            "brand_id": 7,
            "brand_code": "BR001",
            "brand_name": "测试品牌",
            "source_task_id": "task-1",
            "session_kind": "attachment_conflict:draft_only",
            "status": "waiting_user_input",
            "current_round": 1,
            "latest_scan_summary": "扫描完成",
            "latest_auto_merged_json": [],
            "latest_conflicts_json": [
                {
                    "conflict_id": "C-BRAND-001",
                    "severity": "hard",
                    "topic": "主体名称冲突",
                    "options": [{"option_id": "A", "content": "口径A"}],
                }
            ],
            "latest_conflict_markdown": "# 待确认冲突",
            "latest_draft_markdown": "扫描完成",
            "resolution_history_json": [],
            "source_documents_json": [
                {
                    "document_id": "asset_21",
                    "asset_id": 21,
                    "original_filename": "资料一.md",
                    "source_role": "attachment_asset",
                    "subcategory": "产品A",
                    "markdown_text": "# 资料一\n冲突内容A",
                }
            ],
            "final_markdown": None,
            "final_oss_key": None,
            "final_full_knowledge_file_id": None,
            "final_document_id": None,
            "latest_assistant_message": "请选择冲突口径。",
            "latest_user_message": "请扫描冲突",
        }
        service = BrandKnowledgeApplicationService(
            BrandKnowledgeApplicationDependencies(
                settings=types.SimpleNamespace(max_upload_size_mb=50),
                brands=_FakeBrands(),
                brand_knowledge_sessions=self.session_store,
                document_registry=types.SimpleNamespace(),
                store=self.vector_store,
                get_full_text=lambda _document_id: "",
                upload_tasks=_FakeUploadTasks(),
                attachment_assets=_FakeAttachmentAssets(),
                brand_full_knowledge=_FakeFullKnowledgeStore(),
                brand_ai_knowledge_ingestion=self.ingestion_service,
                oss_client=_FakeOSSClient(),
                parser=_FakeParser(),
                embeddings=_FakeEmbeddings(),
                brand_knowledge_facts=self.brand_facts_store,
                enqueue_attachment_conflict_resolution_job=_FailingConflictResolutionEnqueuer(),
            )
        )

        with self.assertRaises(TypeError):
            await service.submit_attachment_conflict_resolutions(
                session_id=session_id,
                round_no=1,
                resolutions=[
                    {
                        "conflict_id": "C-BRAND-001",
                        "decision": "choose_option",
                        "selected_option_id": "A",
                    }
                ],
            )

        session = self.session_store.sessions[session_id]
        self.assertEqual(session["status"], "waiting_user_input")
        self.assertEqual(session["current_round"], 1)
        self.assertEqual(session["latest_assistant_message"], "请选择冲突口径。")
        self.assertEqual(session["resolution_history_json"], [])

    async def test_submit_attachment_conflict_resolutions_generates_and_ingests_final_knowledge(self) -> None:
        session_id = "bks_test"
        captured_generation_kwargs: list[dict] = []
        captured_incremental_generation_kwargs: list[dict] = []
        captured_snapshot_markdown_texts: list[str] = []
        captured_snapshot_kwargs: list[dict] = []
        persisted_snapshots: list[dict] = []
        snapshot_payload = {
            "basic_info": {
                "brand_name": "测试品牌",
                "website": ["https://example.com"],
            },
            "products": [],
            "company_profile": {},
            "management_team": [],
            "competitors": [],
            "authority_honors": [],
            "customers_cases": [],
            "sensitive_topics": [],
            "attachments": [
                {
                    "name": "资料一.md",
                    "source_url": "https://example.com/asset-1.md",
                    "type": "attachment_asset",
                }
            ],
            "official_malls": [],
            "official_media_matrix": [],
            "other_info": [],
        }
        self.brand_facts_store.rows = [
            {
                "brand_code": "BR001",
                "brand_name": "测试品牌",
                "fact_scope": "attachment_temp",
                "fact_id": "fact-temp-1",
                "normalized_fact_hash": "fact-temp-1",
                "source_document_id": "asset_21",
                "source_task_id": "task-1",
            }
        ]
        self.session_store.sessions[session_id] = {
            "session_id": session_id,
            "brand_id": 7,
            "brand_code": "BR001",
            "brand_name": "测试品牌",
            "source_task_id": "task-1",
            "session_kind": "attachment_conflict",
            "status": "waiting_user_input",
            "current_round": 1,
            "latest_scan_summary": "扫描完成",
            "latest_auto_merged_json": [
                {
                    "topic": "网址归一化",
                    "category": "format",
                    "resolution": "统一保留官网主域名",
                    "source_files": ["资料一.md"],
                }
            ],
            "latest_conflicts_json": [
                {
                    "conflict_id": "C-BRAND-001",
                    "severity": "hard",
                    "topic": "主体名称冲突",
                    "description": "需要人工确认",
                    "options": [{"option_id": "A", "content": "口径A", "source_files": ["资料一.md"]}],
                }
            ],
            "latest_conflict_markdown": "# 待确认冲突",
            "latest_draft_markdown": "扫描完成",
            "resolution_history_json": [],
            "source_documents_json": [
                {
                    "document_id": "asset_21",
                    "asset_id": 21,
                    "original_filename": "资料一.md",
                    "source_role": "attachment_asset",
                    "subcategory": "产品A",
                    "markdown_text": "# 资料一\n冲突内容A",
                }
            ],
            "final_markdown": None,
            "final_oss_key": None,
            "final_full_knowledge_file_id": None,
            "final_document_id": None,
            "latest_assistant_message": None,
            "latest_user_message": None,
        }

        async def fake_generate_next_brand_full_knowledge(**kwargs):
            captured_incremental_generation_kwargs.append(kwargs)
            return {
                "brand_id": 7,
                "brand_code": "BR001",
                "brand_name": "测试品牌",
                "version_no": 2,
                "file_name": "【测试品牌】品牌AI知识库_V2_20260723.md",
                "knowledge_markdown": "# 正式品牌AI知识库\n已确认内容\n- 回补后的统一口径",
            }

        service = BrandKnowledgeApplicationService(
            BrandKnowledgeApplicationDependencies(
                settings=types.SimpleNamespace(
                    max_upload_size_mb=50,
                    brand_completion_callback_url="https://callback.example.com/hook",
                    brand_completion_callback_timeout_seconds=5.0,
                ),
                brands=_FakeBrands(),
                brand_knowledge_sessions=self.session_store,
                document_registry=types.SimpleNamespace(),
                store=self.vector_store,
                get_full_text=lambda _document_id: "",
                upload_tasks=_FakeUploadTasks(),
                attachment_assets=_FakeAttachmentAssets(),
                brand_full_knowledge=_FakeFullKnowledgeStore(),
                brand_ai_knowledge_ingestion=self.ingestion_service,
                oss_client=_FakeOSSClient(),
                parser=_FakeParser(),
                embeddings=_FakeEmbeddings(),
                brand_knowledge_facts=self.brand_facts_store,
                runtime=types.SimpleNamespace(scheduled_attachment_conflict_callback_retries=set()),
                spawn_background_task=lambda coro: coro.close(),
                build_current_brand_callback_knowledge=lambda *, brand_code: {
                    "basic_info": {"brand_name": "测试品牌", "website": ["https://example.com"]},
                    "attachments": {"files": [{"name": "资料一.md", "url": "https://example.com/asset-1.md"}]},
                },
                enqueue_attachment_conflict_resolution_job=_FakeConflictResolutionEnqueuer(),
                generate_next_brand_full_knowledge=fake_generate_next_brand_full_knowledge,
            )
        )

        original_generate = brand_knowledge_service_module.generate_brand_knowledge_full_markdown
        original_build_snapshot = brand_knowledge_service_module.build_brand_knowledge_snapshot_from_markdown
        original_persist_snapshot = brand_knowledge_service_module.persist_brand_knowledge_snapshot

        async def fake_generate_brand_knowledge_full_markdown(**kwargs):
            captured_generation_kwargs.append(kwargs)
            return {
                "status": "completed",
                "final_markdown": "# 最终知识库\n已确认内容",
            }

        async def fake_build_brand_knowledge_snapshot_from_markdown(*args, **kwargs):
            captured_snapshot_markdown_texts.append(str(kwargs.get("markdown_text") or ""))
            captured_snapshot_kwargs.append(kwargs)
            markdown_text = str(kwargs.get("markdown_text") or "")
            if "正式品牌AI知识库" in markdown_text:
                return {
                    "snapshot": {
                        **snapshot_payload,
                        "basic_info": {
                            "brand_name": "测试品牌",
                            "website": ["https://final.example.com"],
                        },
                        "other_info": [
                            {"title": "最终口径", "content": "已对齐正式品牌AI知识库"}
                        ],
                    },
                    "supplemental_markdown_sources": [],
                }
            return {
                "snapshot": snapshot_payload,
                "supplemental_markdown_sources": [
                    {
                        "source_name": "测试品牌-天眼查与联网回补.md",
                        "subcategory": "external_enrichment",
                        "source_role": "external_enrichment",
                        "markdown_text": "# 回补\n- 官网: https://example.com",
                    }
                ],
            }

        def fake_persist_brand_knowledge_snapshot(*_args, **kwargs):
            snapshot = kwargs["snapshot"]
            persisted_snapshots.append(snapshot)
            return {
                "brand": {
                    "id": 7,
                    "brand_code": "BR001",
                    "brand_name": "测试品牌",
                    "knowledge_revision": "LXKG-CSPP-V1.0.0-20260717152100",
                },
                "brand_id": 7,
                "knowledge_revision": "LXKG-CSPP-V1.0.0-20260717152100",
                "snapshot": snapshot,
            }

        brand_knowledge_service_module.generate_brand_knowledge_full_markdown = fake_generate_brand_knowledge_full_markdown
        brand_knowledge_service_module.build_brand_knowledge_snapshot_from_markdown = fake_build_brand_knowledge_snapshot_from_markdown
        brand_knowledge_service_module.persist_brand_knowledge_snapshot = fake_persist_brand_knowledge_snapshot
        try:
            submit_result = await service.submit_attachment_conflict_resolutions(
                session_id=session_id,
                round_no=1,
                resolutions=[
                    {
                        "conflict_id": "C-BRAND-001",
                        "decision": "choose_option",
                        "selected_option_id": "A",
                    }
                ],
            )
            self.assertEqual(submit_result["status"], "running")
            self.assertEqual(submit_result["knowledge_markdown_status"], "running")

            job_result = await service.process_attachment_conflict_resolution_job(
                payload={
                    "session_id": session_id,
                    "brand_code": "BR001",
                    "brand_name": "测试品牌",
                    "source_task_id": "task-1",
                    "submitted_round_no": 1,
                    "generation_round_no": 2,
                    "history_resolutions": [],
                    "current_resolutions": [
                        {
                            "conflict_id": "C-BRAND-001",
                            "decision": "choose_option",
                            "selected_option_id": "A",
                        }
                    ],
                    "auto_merged": [
                        {
                            "topic": "网址归一化",
                            "category": "format",
                            "resolution": "统一保留官网主域名",
                            "source_files": ["资料一.md"],
                        }
                    ],
                    "force_reingest": False,
                }
            )
        finally:
            brand_knowledge_service_module.generate_brand_knowledge_full_markdown = original_generate
            brand_knowledge_service_module.build_brand_knowledge_snapshot_from_markdown = original_build_snapshot
            brand_knowledge_service_module.persist_brand_knowledge_snapshot = original_persist_snapshot

        self.assertEqual(job_result["status"], "completed")
        self.assertEqual(len(self.ingestion_service.calls), 1)
        self.assertEqual(self.ingestion_service.calls[0]["brand_code"], "BR001")
        self.assertEqual(self.ingestion_service.calls[0]["source_task_id"], "task-1")
        self.assertEqual(self.ingestion_service.calls[0]["filename"], "【测试品牌】品牌AI知识库_V2_20260723.md")
        self.assertEqual(
            self.ingestion_service.calls[0]["staged_markdown"],
            "# 正式品牌AI知识库\n已确认内容\n- 回补后的统一口径",
        )
        self.assertEqual(len(captured_generation_kwargs), 1)
        self.assertEqual(len(captured_incremental_generation_kwargs), 1)
        self.assertEqual(
            captured_generation_kwargs[0]["history_resolutions"],
            [],
        )
        self.assertEqual(
            captured_generation_kwargs[0]["current_resolutions"],
            [
                {
                    "conflict_id": "C-BRAND-001",
                    "decision": "choose_option",
                    "selected_option_id": "A",
                }
            ],
        )
        self.assertEqual(
            captured_generation_kwargs[0]["auto_merged"],
            [
                {
                    "topic": "网址归一化",
                    "category": "format",
                    "resolution": "统一保留官网主域名",
                    "source_files": ["资料一.md"],
                }
            ],
        )
        self.assertEqual(
            captured_incremental_generation_kwargs[0]["supplemental_markdown_sources"],
            [
                {
                    "source_name": "测试品牌-天眼查与联网回补.md",
                    "subcategory": "external_enrichment",
                    "source_role": "external_enrichment",
                    "markdown_text": "# 回补\n- 官网: https://example.com",
                }
            ],
        )
        self.assertEqual(
            captured_snapshot_markdown_texts,
            [
                "# 最终知识库\n已确认内容",
                "# 正式品牌AI知识库\n已确认内容\n- 回补后的统一口径",
            ],
        )
        self.assertIs(captured_snapshot_kwargs[0]["enable_tianyancha"], True)
        self.assertIs(captured_snapshot_kwargs[1]["enable_tianyancha"], False)
        self.assertEqual(len(persisted_snapshots), 1)
        self.assertEqual(
            persisted_snapshots[0]["basic_info"]["website"],
            ["https://final.example.com"],
        )
        self.assertEqual(self.brand_facts_store.rows, [])
        self.assertEqual(self.vector_store.deleted_fact_ids, ["fact-temp-1"])

    def test_get_latest_attachment_conflict_session_returns_active_session(self) -> None:
        self.session_store.sessions["bks_completed"] = {
            "session_id": "bks_completed",
            "brand_id": 7,
            "brand_code": "BR001",
            "brand_name": "测试品牌",
            "source_task_id": "task-old",
            "session_kind": "attachment_conflict",
            "status": "completed",
            "current_round": 2,
            "latest_assistant_message": "已完成",
            "source_documents_json": [],
            "resolution_history_json": [],
            "latest_conflicts_json": [],
            "latest_auto_merged_json": [],
            "latest_conflict_markdown": None,
            "latest_scan_summary": "完成",
            "latest_draft_markdown": None,
            "final_markdown": "# 已完成",
            "final_oss_key": "oss/completed.md",
            "final_full_knowledge_file_id": 99,
            "final_document_id": "doc-completed",
        }
        self.session_store.sessions["bks_waiting"] = {
            "session_id": "bks_waiting",
            "brand_id": 7,
            "brand_code": "BR001",
            "brand_name": "测试品牌",
            "source_task_id": "task-new",
            "session_kind": "attachment_conflict",
            "status": "waiting_user_input",
            "current_round": 1,
            "latest_assistant_message": "待确认",
            "source_documents_json": [],
            "resolution_history_json": [],
            "latest_conflicts_json": [{"conflict_id": "C-1", "topic": "主体名称", "options": []}],
            "latest_auto_merged_json": [],
            "latest_conflict_markdown": "## 待确认",
            "latest_scan_summary": "扫描完成",
            "latest_draft_markdown": None,
            "final_markdown": None,
            "final_oss_key": None,
            "final_full_knowledge_file_id": None,
            "final_document_id": None,
        }

        result = self.service.get_latest_attachment_conflict_session(brand_code="BR001")

        assert result is not None
        self.assertEqual(result["session_id"], "bks_waiting")
        self.assertEqual(result["status"], "waiting_user_input")

    def test_get_latest_attachment_conflict_session_falls_back_to_completed_session(self) -> None:
        self.session_store.sessions["bks_completed"] = {
            "session_id": "bks_completed",
            "brand_id": 7,
            "brand_code": "BR001",
            "brand_name": "测试品牌",
            "source_task_id": "task-only-completed",
            "session_kind": "attachment_conflict",
            "status": "completed",
            "current_round": 2,
            "latest_assistant_message": "已完成",
            "source_documents_json": [],
            "resolution_history_json": [],
            "latest_conflicts_json": [],
            "latest_auto_merged_json": [],
            "latest_conflict_markdown": None,
            "latest_scan_summary": "完成",
            "latest_draft_markdown": None,
            "final_markdown": "# 已完成",
            "final_oss_key": "oss/completed.md",
            "final_full_knowledge_file_id": 99,
            "final_document_id": "doc-completed",
        }

        result = self.service.get_latest_attachment_conflict_session(brand_code="BR001")

        assert result is not None
        self.assertEqual(result["session_id"], "bks_completed")
        self.assertEqual(result["status"], "completed")

    def test_get_latest_attachment_conflict_session_returns_completed_draft_session(self) -> None:
        self.session_store.sessions["bks_draft_completed"] = {
            "session_id": "bks_draft_completed",
            "brand_id": 7,
            "brand_code": "BR001",
            "brand_name": "测试品牌",
            "source_task_id": "task-draft",
            "session_kind": "attachment_conflict:draft_only",
            "status": "completed",
            "current_round": 2,
            "latest_assistant_message": "最终品牌 AI 知识库草稿已生成并上传 OSS。",
            "source_documents_json": [],
            "resolution_history_json": [],
            "latest_conflicts_json": [],
            "latest_auto_merged_json": [],
            "latest_conflict_markdown": None,
            "latest_scan_summary": "完成",
            "latest_draft_markdown": None,
            "final_markdown": "# 草稿已完成",
            "final_oss_key": "oss/draft.md",
            "final_full_knowledge_file_id": 100,
            "final_document_id": None,
        }

        result = self.service.get_latest_attachment_conflict_session(brand_code="BR001")

        assert result is not None
        self.assertEqual(result["session_id"], "bks_draft_completed")
        self.assertEqual(result["session_kind"], "attachment_conflict:draft_only")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["assistant_message"], "最终品牌 AI 知识库草稿已生成并上传 OSS。")

    def test_get_latest_attachment_conflict_session_uses_brand_code_when_brand_name_differs(self) -> None:
        self.session_store.sessions["bks_completed"] = {
            "session_id": "bks_completed",
            "brand_code": "BR001",
            "brand_name": "测试品牌",
            "source_task_id": "task-only-completed",
            "session_kind": "attachment_conflict",
            "status": "completed",
            "current_round": 2,
            "latest_assistant_message": "已完成",
            "source_documents_json": [],
            "resolution_history_json": [],
            "latest_conflicts_json": [],
            "latest_auto_merged_json": [],
            "latest_conflict_markdown": None,
            "latest_scan_summary": "完成",
            "latest_draft_markdown": None,
            "final_markdown": "# 已完成",
            "final_oss_key": "oss/completed.md",
            "final_full_knowledge_file_id": 99,
            "final_document_id": "doc-completed",
        }

        result = self.service.get_latest_attachment_conflict_session(
            brand_code="BR001",
            brand_name="别的品牌",
        )

        assert result is not None
        self.assertEqual(result["session_id"], "bks_completed")
        self.assertEqual(result["brand_code"], "BR001")
        self.assertEqual(result["brand_name"], "测试品牌")
