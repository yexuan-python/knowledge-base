from __future__ import annotations

import asyncio
import importlib.util
import types
import unittest
from datetime import datetime, timedelta

FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None

if FASTAPI_AVAILABLE:
    from fastapi.testclient import TestClient

    from knowledge_base.api_app.app import create_app
    from knowledge_base.api_app.routers import brand_knowledge as brand_knowledge_router_module
    from knowledge_base.service import KnowledgeBaseService


class StubKnowledgeBaseService:
    def __init__(
        self,
        *,
        preview_result: dict | None = None,
        preview_error: Exception | None = None,
        review_result: dict | None = None,
        review_error: Exception | None = None,
        confirm_result: dict | None = None,
        confirm_error: Exception | None = None,
        attachment_delete_result: dict | None = None,
        attachment_delete_error: Exception | None = None,
        attachment_confirm_result_query: dict | None = None,
        attachment_confirm_result_query_error: Exception | None = None,
        latest_conflict_session_result: dict | None = None,
        latest_conflict_session_error: Exception | None = None,
        start_knowledge_session_result: dict | None = None,
        start_knowledge_session_error: Exception | None = None,
        submit_attachment_conflict_result: dict | None = None,
        submit_attachment_conflict_error: Exception | None = None,
        ) -> None:
        self.preview_result = preview_result
        self.preview_error = preview_error
        self.review_result = review_result
        self.review_error = review_error
        self.confirm_result = confirm_result
        self.confirm_error = confirm_error
        self.attachment_delete_result = attachment_delete_result
        self.attachment_delete_error = attachment_delete_error
        self.attachment_confirm_result_query = attachment_confirm_result_query
        self.attachment_confirm_result_query_error = attachment_confirm_result_query_error
        self.latest_conflict_session_result = latest_conflict_session_result
        self.latest_conflict_session_error = latest_conflict_session_error
        self.start_knowledge_session_result = start_knowledge_session_result
        self.start_knowledge_session_error = start_knowledge_session_error
        self.submit_attachment_conflict_result = submit_attachment_conflict_result
        self.submit_attachment_conflict_error = submit_attachment_conflict_error
        self.preview_calls: list[dict] = []
        self.review_calls: list[dict] = []
        self.confirm_calls: list[dict] = []
        self.attachment_delete_calls: list[dict] = []
        self.attachment_confirm_result_calls: list[str] = []
        self.latest_conflict_session_calls: list[dict] = []
        self.start_knowledge_session_calls: list[dict] = []
        self.submit_attachment_conflict_calls: list[dict] = []
        self.start_calls = 0
        self.stop_calls = 0

    async def start(self) -> None:
        self.start_calls += 1

    async def stop(self) -> None:
        self.stop_calls += 1

    async def preview_parse_brand_attachments(
        self,
        *,
        brand_name: str,
        brand_code: str | None,
        attachments: list[dict[str, str]],
    ) -> dict:
        self.preview_calls.append(
            {
                "brand_name": brand_name,
                "brand_code": brand_code,
                "attachments": attachments,
            }
        )
        if self.preview_error is not None:
            raise self.preview_error
        return self.preview_result or {}

    async def review_brand_attachment_changes(
        self,
        *,
        request,
        draft_id: str,
    ) -> dict:
        self.review_calls.append(
            {
                "draft_id": draft_id,
                "request": request,
            }
        )
        if self.review_error is not None:
            raise self.review_error
        return self.review_result or {}

    async def confirm_save_brand_attachments(
        self,
        *,
        request,
        draft_id: str,
    ) -> dict:
        self.confirm_calls.append(
            {
                "draft_id": draft_id,
                "request": request,
            }
        )
        if self.confirm_error is not None:
            raise self.confirm_error
        return self.confirm_result or {}

    async def delete_documents_by_attachments(
        self,
        *,
        brand_code: str,
        attachments: list[dict[str, str]],
    ) -> dict:
        self.attachment_delete_calls.append(
            {
                "brand_code": brand_code,
                "attachments": attachments,
            }
        )
        if self.attachment_delete_error is not None:
            raise self.attachment_delete_error
        return self.attachment_delete_result or {}

    def get_attachment_confirm_result(self, job_id: str) -> dict | None:
        self.attachment_confirm_result_calls.append(job_id)
        if self.attachment_confirm_result_query_error is not None:
            raise self.attachment_confirm_result_query_error
        return self.attachment_confirm_result_query

    def get_latest_brand_attachment_conflict_session(
        self,
        *,
        brand_code: str,
        brand_name: str | None = None,
    ) -> dict | None:
        self.latest_conflict_session_calls.append(
            {
                "brand_code": brand_code,
                "brand_name": brand_name,
            }
        )
        if self.latest_conflict_session_error is not None:
            raise self.latest_conflict_session_error
        return self.latest_conflict_session_result

    async def start_brand_knowledge_session(
        self,
        *,
        session_type: str,
        task_id: str | None = None,
        brand_code: str | None = None,
        brand_name: str | None = None,
        publish_mode: str | None = None,
        iteration_mode: str | None = None,
        initial_message: str | None = None,
        update_instruction: str | None = None,
    ) -> dict:
        self.start_knowledge_session_calls.append(
            {
                "session_type": session_type,
                "task_id": task_id,
                "brand_code": brand_code,
                "brand_name": brand_name,
                "publish_mode": publish_mode,
                "iteration_mode": iteration_mode,
                "initial_message": initial_message,
                "update_instruction": update_instruction,
            }
        )
        if self.start_knowledge_session_error is not None:
            raise self.start_knowledge_session_error
        return self.start_knowledge_session_result or {}

    async def submit_brand_attachment_conflict_resolutions(
        self,
        *,
        session_id: str,
        round_no: int,
        resolutions: list[dict],
        force_reingest: bool = False,
        publish_mode: str | None = None,
    ) -> dict:
        self.submit_attachment_conflict_calls.append(
            {
                "session_id": session_id,
                "round_no": round_no,
                "resolutions": resolutions,
                "force_reingest": force_reingest,
                "publish_mode": publish_mode,
            }
        )
        if self.submit_attachment_conflict_error is not None:
            raise self.submit_attachment_conflict_error
        return self.submit_attachment_conflict_result or {}


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class BrandKnowledgeRouteTests(unittest.TestCase):
    def _build_client(self, service: StubKnowledgeBaseService) -> TestClient:
        settings = types.SimpleNamespace(dashscope_api_key="test-key")
        app = create_app(settings=settings, service=service)
        app.dependency_overrides[brand_knowledge_router_module.get_service] = lambda: service
        return TestClient(app)

    def test_review_changes_maps_runtime_error_to_409(self) -> None:
        service = StubKnowledgeBaseService(review_error=RuntimeError("knowledge_revision 不匹配，当前 revision=rev-2"))

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/brands/attachments/review-changes",
                json={
                    "draft_id": "bad_123",
                    "candidate_snapshot": {"basic_info": {"advantages": "新优势"}},
                    "brand_name": "示例品牌",
                },
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"detail": "knowledge_revision 不匹配，当前 revision=rev-2"})
        self.assertEqual(service.start_calls, 1)
        self.assertEqual(service.stop_calls, 1)

    def test_preview_parse_returns_200_with_empty_candidate_snapshot(self) -> None:
        service = StubKnowledgeBaseService(
            preview_result={
                "draft_id": "bad_123",
                "brand_name": "示例品牌",
                "candidate_snapshot": {},
                "field_labels": {},
                "knowledge_revision": "rev-1",
            }
        )

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/brands/attachments/preview-parse",
                json={
                    "brand_name": "示例品牌",
                    "brand_code": "BRAND-001",
                    "attachments": [
                        {
                            "name": "品牌资料.pdf",
                            "url": "https://example.com/missing.pdf",
                        }
                    ],
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "draft_id": "bad_123",
                "brand_name": "示例品牌",
                "candidate_snapshot": {},
                "field_labels": {},
                "knowledge_revision": "rev-1",
            },
        )

    def test_preview_parse_returns_official_ai_knowledge_upload_status(self) -> None:
        service = StubKnowledgeBaseService(
            preview_result={
                "brand_name": "燕之屋",
                "status": "true",
            }
        )

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/brands/attachments/preview-parse",
                json={
                    "brand_name": "燕之屋",
                    "brand_code": "100209",
                    "attachments": [
                        {
                            "name": "【燕之屋】品牌AI知识库_V3_20260918.md",
                            "url": "https://example.com/kb.md",
                        }
                    ],
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "brand_name": "燕之屋",
                "status": "true",
            },
        )

    def test_confirm_maps_runtime_error_to_409(self) -> None:
        service = StubKnowledgeBaseService(confirm_error=RuntimeError("knowledge_revision 不匹配，当前 revision=rev-2"))

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/brands/attachments/confirm",
                json={
                    "draft_id": "bad_123",
                    "review_id": "bar_123",
                },
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"detail": "knowledge_revision 不匹配，当前 revision=rev-2"})
        self.assertEqual(service.start_calls, 1)
        self.assertEqual(service.stop_calls, 1)

    def test_get_attachment_confirm_result_returns_lightweight_payload(self) -> None:
        service = StubKnowledgeBaseService(
            attachment_confirm_result_query={
                "code": 0,
                "message": "ok",
                "data": {
                    "version": "LXKG-JPJJ-V1.7.0-20260713145838",
                    "brand_code": None,
                    "brand_id": None,
                    "brand_name": "",
                    "updated_sections": [],
                    "knowledge_revision": "",
                    "final_markdown_oss_key": "",
                    "final_markdown_oss_url": "",
                    "final_document_id": "",
                    "original_attachments": [],
                    "attachment_documents": [],
                    "confirm_callback_status": "",
                    "full_knowledge_refresh_job_id": "",
                    "full_knowledge_refresh_status": "",
                    "oss_url_md": "https://oss.example.com/knowledge/demo.md",
                    "oss_url_pdf": "https://oss.example.com/knowledge/demo.pdf",
                },
            }
        )

        with self._build_client(service) as client:
            response = client.get(
                "/api/v1/brands/attachments/confirm/result/bg:attachment_confirm_full_generation:confirm:job-1"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "code": 0,
                "message": "ok",
                "data": {
                    "version": "LXKG-JPJJ-V1.7.0-20260713145838",
                    "brand_code": None,
                    "brand_id": None,
                    "brand_name": "",
                    "updated_sections": [],
                    "knowledge_revision": "",
                    "final_markdown_oss_key": "",
                    "final_markdown_oss_url": "",
                    "final_document_id": "",
                    "original_attachments": [],
                    "attachment_documents": [],
                    "confirm_callback_status": "",
                    "full_knowledge_refresh_job_id": "",
                    "full_knowledge_refresh_status": "",
                    "oss_url_md": "https://oss.example.com/knowledge/demo.md",
                    "oss_url_pdf": "https://oss.example.com/knowledge/demo.pdf",
                },
            },
        )
        self.assertEqual(
            service.attachment_confirm_result_calls,
            ["bg:attachment_confirm_full_generation:confirm:job-1"],
        )

    def test_get_attachment_confirm_result_maps_invalid_job_type_to_400(self) -> None:
        service = StubKnowledgeBaseService(
            attachment_confirm_result_query_error=ValueError("background job 不是附件确认生成任务")
        )

        with self._build_client(service) as client:
            response = client.get("/api/v1/brands/attachments/confirm/result/bg:upload_task_process:task-1")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "background job 不是附件确认生成任务"})

    def test_get_attachment_confirm_result_uses_status_as_message_on_failure(self) -> None:
        class FakeBackgroundJobStore:
            def get_job(self, job_id: str) -> dict:
                return {
                    "job_id": job_id,
                    "job_type": "attachment_confirm_full_generation",
                    "source_type": "brand_knowledge",
                    "source_id": "confirm:bad_1:bar_1",
                    "status": "failed",
                    "priority": 100,
                    "retry_count": 4,
                    "max_retries": 3,
                    "next_retry_at": None,
                    "locked_by": None,
                    "locked_at": None,
                    "last_error_message": "markdown generation failed",
                    "started_at": None,
                    "finished_at": None,
                    "created_at": None,
                    "updated_at": None,
                    "payload_json": None,
                    "result_json": None,
                }

        service = KnowledgeBaseService.__new__(KnowledgeBaseService)
        service._background_jobs = FakeBackgroundJobStore()

        result = service.get_attachment_confirm_result("bg:attachment_confirm_full_generation:confirm:bad_1:bar_1")

        self.assertEqual(result, {"code": -1, "message": "failed", "data": None})

    def test_brands_attachment_delete_route_replaces_legacy_attachment_delete_route(self) -> None:
        service = StubKnowledgeBaseService(
            attachment_delete_result={
                "brand_code": "BRAND-001",
                "brand_name": "示例品牌",
                "summary": {
                    "requested_count": 1,
                    "deleted_count": 1,
                    "not_found_count": 0,
                    "failed_count": 0,
                    "ambiguous_count": 0,
                },
                "results": [
                    {
                        "name": "示例.pdf",
                        "url": "https://example.com/demo.pdf",
                        "status": "deleted",
                        "detail": "已从品牌知识附件列表移除",
                    }
                ],
            }
        )
        request_payload = {
            "brand_code": "BRAND-001",
            "attachments": [
                {
                    "name": "示例.pdf",
                    "url": "https://example.com/demo.pdf",
                }
            ],
        }

        with self._build_client(service) as client:
            response = client.post("/api/v1/brands/attachments/delete", json=request_payload)
            legacy_response = client.post("/api/v1/attachments/delete", json=request_payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["code"], "200")
        self.assertIsNone(response.json()["data"]["document_id"])
        self.assertEqual(response.json()["data"]["detail"], "已从品牌知识附件列表移除")
        self.assertEqual(legacy_response.status_code, 404)
        self.assertEqual(
            service.attachment_delete_calls,
            [
                {
                    "brand_code": "BRAND-001",
                    "attachments": [
                        {
                            "name": "示例.pdf",
                            "url": "https://example.com/demo.pdf",
                        }
                    ],
                }
            ],
        )

    def test_brands_attachment_delete_route_maps_not_found_to_deleted_for_frontend(self) -> None:
        service = StubKnowledgeBaseService(
            attachment_delete_result={
                "brand_code": "BRAND-001",
                "brand_name": "示例品牌",
                "summary": {
                    "requested_count": 1,
                    "deleted_count": 0,
                    "not_found_count": 1,
                    "failed_count": 0,
                    "ambiguous_count": 0,
                },
                "results": [
                    {
                        "name": "示例.pdf",
                        "url": "https://example.com/demo.pdf",
                        "status": "not_found",
                        "detail": "未找到品牌知识附件记录",
                    }
                ],
            }
        )

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/brands/attachments/delete",
                json={
                    "brand_code": "BRAND-001",
                    "attachments": [
                        {
                            "name": "示例.pdf",
                            "url": "https://example.com/demo.pdf",
                        }
                    ],
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["code"], "200")
        self.assertEqual(response.json()["data"]["status"], "deleted")
        self.assertEqual(response.json()["data"]["detail"], "已从品牌知识附件列表移除")

    def test_get_latest_brand_attachment_conflict_session_returns_session(self) -> None:
        service = StubKnowledgeBaseService(
            latest_conflict_session_result={
                "session_id": "bks_123",
                "brand_code": "BR001",
                "brand_name": "测试品牌",
                "status": "waiting_user_input",
                "round_no": 1,
                "session_kind": "attachment_conflict",
                "source_task_id": "task-1",
                "assistant_message": "请确认冲突。",
                "source_documents": [],
                "conflicts": [
                    {
                        "conflict_id": "C-1",
                        "topic": "主体名称",
                        "severity": "hard",
                        "description": "需要确认",
                        "options": [
                            {
                                "option_id": "A",
                                "content": "方案A",
                                "source_files": ["资料一.md"],
                            }
                        ],
                    }
                ],
                "conflict_markdown": "## 冲突",
                "scan_summary": "扫描完成",
                "auto_merged": [],
                "final_markdown": None,
                "final_oss_key": None,
                "final_filename": None,
                "final_full_knowledge_file_id": None,
                "final_document_id": None,
                "knowledge_oss_url_md": None,
                "knowledge_oss_url_pdf": None,
            }
        )

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/brands/knowledge-base/conflict-session/latest",
                json={"brand_code": "BR001"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["session_id"], "bks_123")
        self.assertEqual(
            service.latest_conflict_session_calls,
            [{"brand_code": "BR001", "brand_name": None}],
        )

    def test_start_brand_knowledge_session_initial_generation(self) -> None:
        service = StubKnowledgeBaseService(
            start_knowledge_session_result={
                "session_id": "bks_123",
                "brand_code": "BR001",
                "brand_name": "测试品牌",
                "status": "waiting_user_input",
                "knowledge_markdown_status": "waiting_user_input",
                "round_no": 1,
                "session_type": "initial_generation",
                "iteration_mode": None,
                "session_kind": "attachment_conflict",
                "source_task_id": "task-1",
                "assistant_message": "请确认冲突。",
                "source_documents": [],
                "conflicts": [],
                "conflict_markdown": None,
                "scan_summary": "扫描完成",
                "auto_merged": [],
                "final_markdown": None,
                "final_oss_key": None,
                "final_filename": None,
                "final_full_knowledge_file_id": None,
                "final_document_id": None,
                "knowledge_oss_url_md": None,
                "knowledge_oss_url_pdf": None,
            }
        )

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/brands/knowledge-base/sessions",
                json={
                    "session_type": "initial_generation",
                    "task_id": "task-1",
                    "initial_message": "请扫描并生成首次知识库",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["session_id"], "bks_123")
        self.assertEqual(response.json()["session_type"], "initial_generation")
        self.assertEqual(
            service.start_knowledge_session_calls,
            [
                {
                    "session_type": "initial_generation",
                    "task_id": "task-1",
                    "brand_code": None,
                    "brand_name": None,
                    "publish_mode": "draft_only",
                    "iteration_mode": None,
                    "initial_message": "请扫描并生成首次知识库",
                    "update_instruction": None,
                }
            ],
        )

    def test_legacy_attachment_conflict_entrypoint_defaults_to_full_ingest(self) -> None:
        class FakeBrandKnowledgeApp:
            def __init__(self) -> None:
                self.calls: list[dict] = []

            async def start_attachment_conflict_session(
                self,
                *,
                task_id: str,
                initial_message: str | None = None,
                publish_mode: str | None = None,
            ) -> dict:
                self.calls.append(
                    {
                        "task_id": task_id,
                        "initial_message": initial_message,
                        "publish_mode": publish_mode,
                    }
                )
                return {"session_id": "bks_legacy", "status": "running"}

        service = KnowledgeBaseService.__new__(KnowledgeBaseService)
        app = FakeBrandKnowledgeApp()
        service._brand_knowledge_app = app

        result = asyncio.run(
            service.start_brand_attachment_conflict_session(
                task_id="task-legacy",
                initial_message="兼容入口默认正式入库",
            )
        )

        self.assertEqual(result["session_id"], "bks_legacy")
        self.assertEqual(
            app.calls,
            [
                {
                    "task_id": "task-legacy",
                    "initial_message": "兼容入口默认正式入库",
                    "publish_mode": "full_ingest",
                }
            ],
        )

    def test_start_brand_knowledge_session_iteration_passes_mode_and_instruction(self) -> None:
        service = StubKnowledgeBaseService(
            start_knowledge_session_result={
                "session_id": "bks_456",
                "brand_code": "BR001",
                "brand_name": "测试品牌",
                "status": "completed",
                "knowledge_markdown_status": "completed",
                "round_no": 1,
                "session_type": "knowledge_iteration",
                "iteration_mode": "attachments_with_instruction",
                "session_kind": "knowledge_iteration:attachments_with_instruction",
                "source_task_id": "task-1",
                "assistant_message": "知识库迭代已完成。",
                "source_documents": [],
                "conflicts": [],
                "conflict_markdown": None,
                "scan_summary": "知识库迭代生成完成。",
                "auto_merged": [],
                "final_markdown": "# 新版知识库",
                "final_oss_key": "kb/final.md",
                "final_filename": None,
                "final_full_knowledge_file_id": None,
                "final_document_id": None,
                "knowledge_oss_url_md": None,
                "knowledge_oss_url_pdf": None,
            }
        )

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/brands/knowledge-base/sessions",
                json={
                    "session_type": "knowledge_iteration",
                    "iteration_mode": "attachments_with_instruction",
                    "brand_code": "BR001",
                    "brand_name": "测试品牌",
                    "task_id": "task-1",
                    "update_instruction": "补充研学内容",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["session_type"], "knowledge_iteration")
        self.assertEqual(response.json()["iteration_mode"], "attachments_with_instruction")
        self.assertEqual(
            service.start_knowledge_session_calls,
            [
                {
                    "session_type": "knowledge_iteration",
                    "task_id": "task-1",
                    "brand_code": "BR001",
                    "brand_name": "测试品牌",
                    "publish_mode": "draft_only",
                    "iteration_mode": "attachments_with_instruction",
                    "initial_message": None,
                    "update_instruction": "补充研学内容",
                }
            ],
        )

    def test_start_brand_knowledge_session_passes_explicit_full_ingest_mode(self) -> None:
        service = StubKnowledgeBaseService(
            start_knowledge_session_result={
                "session_id": "bks_full_ingest",
                "brand_code": "BR001",
                "brand_name": "测试品牌",
                "status": "waiting_user_input",
                "knowledge_markdown_status": "waiting_user_input",
                "round_no": 1,
                "session_type": "initial_generation",
                "iteration_mode": None,
                "session_kind": "attachment_conflict",
                "source_task_id": "task-1",
                "assistant_message": "请确认冲突。",
                "source_documents": [],
                "conflicts": [],
                "conflict_markdown": None,
                "scan_summary": "扫描完成。",
                "auto_merged": [],
                "final_markdown": None,
                "final_oss_key": None,
                "final_filename": None,
                "final_full_knowledge_file_id": None,
                "final_document_id": None,
                "knowledge_oss_url_md": None,
                "knowledge_oss_url_pdf": None,
            }
        )

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/brands/knowledge-base/sessions",
                json={
                    "session_type": "initial_generation",
                    "task_id": "task-1",
                    "publish_mode": "full_ingest",
                    "initial_message": "请扫描并正式入库",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            service.start_knowledge_session_calls,
            [
                {
                    "session_type": "initial_generation",
                    "task_id": "task-1",
                    "brand_code": None,
                    "brand_name": None,
                    "publish_mode": "full_ingest",
                    "iteration_mode": None,
                    "initial_message": "请扫描并正式入库",
                    "update_instruction": None,
                }
            ],
        )

    def test_service_get_latest_brand_attachment_conflict_session_enriches_markdown_status(self) -> None:
        class FakeBrandKnowledgeApp:
            def get_latest_attachment_conflict_session(self, *, brand_code: str, brand_name: str | None = None) -> dict:
                return {
                    "session_id": "bks_123",
                    "brand_code": brand_code,
                    "brand_name": brand_name or "测试品牌",
                    "status": "completed",
                    "round_no": 2,
                    "session_kind": "attachment_conflict",
                    "source_task_id": "task-1",
                    "assistant_message": "已完成。",
                    "source_documents": [],
                    "conflicts": [],
                    "conflict_markdown": None,
                    "scan_summary": "扫描完成",
                    "auto_merged": [],
                    "final_markdown": "# 最终知识库",
                    "final_oss_key": "kb/final.md",
                    "final_filename": "【测试品牌】品牌AI知识库_V2_20260715.md",
                    "final_full_knowledge_file_id": 99,
                    "final_document_id": "doc-99",
                    "knowledge_oss_url_md": "https://oss.example.com/kb/final.md",
                    "knowledge_oss_url_pdf": "https://oss.example.com/kb/final.pdf",
                }

        class FakeBackgroundJobStore:
            def get_latest_job_by_type_and_brand_code(self, *, job_type: str, brand_code: str) -> dict:
                return {
                    "job_type": job_type,
                    "brand_code": brand_code,
                    "status": "processing",
                }

        service = KnowledgeBaseService.__new__(KnowledgeBaseService)
        service._brand_knowledge_app = FakeBrandKnowledgeApp()
        service._background_jobs = FakeBackgroundJobStore()

        result = service.get_latest_brand_attachment_conflict_session(
            brand_code="BR001",
            brand_name="测试品牌",
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual("running", result["status"])
        self.assertEqual("running", result["knowledge_markdown_status"])

    def test_service_get_latest_brand_attachment_conflict_session_defaults_markdown_status_to_skipped(self) -> None:
        class FakeBrandKnowledgeApp:
            def get_latest_attachment_conflict_session(self, *, brand_code: str, brand_name: str | None = None) -> dict:
                return {
                    "session_id": "bks_123",
                    "brand_code": brand_code,
                    "brand_name": brand_name or "测试品牌",
                    "status": "waiting_user_input",
                    "round_no": 1,
                    "session_kind": "attachment_conflict",
                    "source_task_id": "task-1",
                    "assistant_message": "请确认冲突。",
                    "source_documents": [],
                    "conflicts": [],
                    "conflict_markdown": None,
                    "scan_summary": "扫描完成",
                    "auto_merged": [],
                    "final_markdown": None,
                    "final_oss_key": None,
                    "final_filename": None,
                    "final_full_knowledge_file_id": None,
                    "final_document_id": None,
                    "knowledge_oss_url_md": None,
                    "knowledge_oss_url_pdf": None,
                }

        service = KnowledgeBaseService.__new__(KnowledgeBaseService)
        service._brand_knowledge_app = FakeBrandKnowledgeApp()
        service._background_jobs = types.SimpleNamespace(
            get_latest_job_by_type_and_brand_code=lambda **_kwargs: None,
        )

        result = service.get_latest_brand_attachment_conflict_session(
            brand_code="BR001",
            brand_name="测试品牌",
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual("waiting_user_input", result["status"])
        self.assertEqual("waiting_user_input", result["knowledge_markdown_status"])

    def test_service_get_latest_brand_attachment_conflict_session_uses_confirm_pipeline_status(self) -> None:
        class FakeBrandKnowledgeApp:
            def get_latest_attachment_conflict_session(self, *, brand_code: str, brand_name: str | None = None) -> dict:
                return {
                    "session_id": "bks_123",
                    "brand_code": brand_code,
                    "brand_name": brand_name or "测试品牌",
                    "status": "completed",
                    "round_no": 2,
                    "session_kind": "attachment_conflict",
                    "source_task_id": "task-1",
                    "assistant_message": "已完成。",
                    "source_documents": [],
                    "conflicts": [],
                    "conflict_markdown": None,
                    "scan_summary": "扫描完成",
                    "auto_merged": [],
                    "final_markdown": "# 最终知识库",
                    "final_oss_key": "kb/final.md",
                    "final_filename": "【测试品牌】品牌AI知识库_V2_20260715.md",
                    "final_full_knowledge_file_id": 99,
                    "final_document_id": "doc-99",
                    "knowledge_oss_url_md": "https://oss.example.com/kb/final.md",
                    "knowledge_oss_url_pdf": "https://oss.example.com/kb/final.pdf",
                }

        class FakeBackgroundJobStore:
            def get_latest_job_by_type_and_brand_code(self, *, job_type: str, brand_code: str) -> dict | None:
                now = datetime(2026, 7, 22, 12, 0, 0)
                jobs = {
                    "attachment_confirm_pipeline": {
                        "id": 3,
                        "job_type": job_type,
                        "brand_code": brand_code,
                        "status": "processing",
                        "updated_at": now,
                    },
                    "attachment_conflict_resolution": {
                        "id": 2,
                        "job_type": job_type,
                        "brand_code": brand_code,
                        "status": "success",
                        "updated_at": now - timedelta(minutes=2),
                    },
                    "brand_knowledge_update_full_generation": {
                        "id": 1,
                        "job_type": job_type,
                        "brand_code": brand_code,
                        "status": "success",
                        "updated_at": now - timedelta(minutes=5),
                    },
                }
                return jobs.get(job_type)

        service = KnowledgeBaseService.__new__(KnowledgeBaseService)
        service._brand_knowledge_app = FakeBrandKnowledgeApp()
        service._background_jobs = FakeBackgroundJobStore()

        result = service.get_latest_brand_attachment_conflict_session(
            brand_code="BR001",
            brand_name="测试品牌",
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual("running", result["status"])
        self.assertEqual("running", result["knowledge_markdown_status"])

    def test_service_get_latest_brand_attachment_conflict_session_returns_running_empty_state_for_confirm_pipeline(self) -> None:
        class FakeBrandKnowledgeApp:
            def get_latest_attachment_conflict_session(self, *, brand_code: str, brand_name: str | None = None) -> dict | None:
                return None

        class FakeBackgroundJobStore:
            def get_latest_job_by_type_and_brand_code(self, *, job_type: str, brand_code: str) -> dict | None:
                if job_type != "attachment_confirm_pipeline":
                    return None
                return {
                    "id": 5,
                    "job_type": job_type,
                    "brand_code": brand_code,
                    "status": "processing",
                    "updated_at": datetime(2026, 7, 22, 12, 0, 0),
                    "payload_json": {"brand_name": "测试品牌"},
                }

        service = KnowledgeBaseService.__new__(KnowledgeBaseService)
        service._brand_knowledge_app = FakeBrandKnowledgeApp()
        service._background_jobs = FakeBackgroundJobStore()

        result = service.get_latest_brand_attachment_conflict_session(
            brand_code="BR001",
            brand_name=None,
        )

        self.assertEqual(
            result,
            {
                "brand_code": "BR001",
                "brand_name": "测试品牌",
                "status": "running",
                "knowledge_markdown_status": "running",
            },
        )

    def test_service_get_latest_brand_attachment_conflict_session_maps_pending_audits_to_running_over_old_failed_job(self) -> None:
        class FakeBrandKnowledgeApp:
            def get_latest_attachment_conflict_session(self, *, brand_code: str, brand_name: str | None = None) -> dict | None:
                return None

        class FakeBackgroundJobStore:
            def get_latest_job_by_type_and_brand_code(self, *, job_type: str, brand_code: str) -> dict | None:
                if job_type != "attachment_confirm_pipeline":
                    return None
                return {
                    "id": 5,
                    "job_type": job_type,
                    "brand_code": brand_code,
                    "status": "failed",
                    "updated_at": datetime(2026, 8, 3, 20, 26, 49),
                    "payload_json": {"brand_name": "测试品牌"},
                }

        audit_calls: list[dict[str, object]] = []

        class FakeAuditStore:
            def count_unconsumed_for_full_knowledge(self, *, brand_code: str, source_types: list[str]) -> int:
                audit_calls.append(
                    {
                        "brand_code": brand_code,
                        "source_types": source_types,
                    }
                )
                return 1

        service = KnowledgeBaseService.__new__(KnowledgeBaseService)
        service._brand_knowledge_app = FakeBrandKnowledgeApp()
        service._background_jobs = FakeBackgroundJobStore()
        service._brand_knowledge_update_audits = FakeAuditStore()

        result = service.get_latest_brand_attachment_conflict_session(
            brand_code="BR001",
            brand_name=None,
        )

        self.assertEqual(
            result,
            {
                "brand_code": "BR001",
                "brand_name": "测试品牌",
                "status": "running",
                "knowledge_markdown_status": "running",
            },
        )
        self.assertEqual(
            audit_calls,
            [
                {
                    "brand_code": "BR001",
                    "source_types": ["knowledge_update", "attachment_confirm"],
                }
            ],
        )

    def test_get_latest_brand_attachment_conflict_session_maps_empty_result_to_no_conflicts(self) -> None:
        service = StubKnowledgeBaseService(latest_conflict_session_result=None)

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/brands/knowledge-base/conflict-session/latest",
                json={"brand_code": "BR001", "brand_name": "测试品牌"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "brand_code": "BR001",
                "brand_name": "测试品牌",
                "status": "no_conflicts",
                "knowledge_markdown_status": "no_conflicts",
            },
        )

    def test_get_latest_brand_attachment_conflict_session_maps_running_empty_state(self) -> None:
        service = StubKnowledgeBaseService(
            latest_conflict_session_result={
                "brand_code": "BR001",
                "brand_name": "测试品牌",
                "status": "running",
                "knowledge_markdown_status": "running",
            }
        )

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/brands/knowledge-base/conflict-session/latest",
                json={"brand_code": "BR001", "brand_name": "测试品牌"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "brand_code": "BR001",
                "brand_name": "测试品牌",
                "status": "running",
                "knowledge_markdown_status": "running",
            },
        )

    def test_submit_brand_attachment_conflict_resolutions_by_body(self) -> None:
        service = StubKnowledgeBaseService(
            submit_attachment_conflict_result={
                "session_id": "bks_123",
                "brand_code": "BR001",
                "brand_name": "测试品牌",
                "status": "completed",
                "round_no": 2,
                "session_kind": "attachment_conflict",
                "source_task_id": "task-1",
                "assistant_message": "已完成。",
                "source_documents": [],
                "conflicts": [],
                "conflict_markdown": None,
                "scan_summary": "扫描完成",
                "auto_merged": [],
                "final_markdown": "# 最终知识库",
                "final_oss_key": "kb/final.md",
                "final_filename": "【测试品牌】品牌AI知识库_V2_20260715.md",
                "final_full_knowledge_file_id": 99,
                "final_document_id": "doc-99",
                "knowledge_oss_url_md": "https://oss.example.com/kb/final.md",
                "knowledge_oss_url_pdf": "https://oss.example.com/kb/final.pdf",
            }
        )

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/brands/knowledge-base/conflict-sessions/resolutions",
                json={
                    "session_id": "bks_123",
                    "round_no": 1,
                    "force_reingest": True,
                    "resolutions": [
                        {
                            "conflict_id": "C-1",
                            "decision": "choose_option",
                            "selected_option_id": "A",
                        }
                    ],
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "completed")
        self.assertEqual(
            service.submit_attachment_conflict_calls,
            [
                {
                    "session_id": "bks_123",
                    "round_no": 1,
                    "resolutions": [
                        {
                            "conflict_id": "C-1",
                            "decision": "choose_option",
                            "selected_option_id": "A",
                            "final_content": None,
                        }
                    ],
                    "force_reingest": True,
                    "publish_mode": "draft_only",
                }
            ],
        )
