from __future__ import annotations

import types
import unittest

from fastapi.testclient import TestClient

from knowledge_base.api_app.app import create_app
from knowledge_base.api_app.routers import background_jobs as background_jobs_router_module


class StubKnowledgeBaseService:
    def __init__(self, *, job_result: dict | None = None, job_list: list[dict] | None = None) -> None:
        self.job_result = job_result
        self.job_list = job_list or []
        self.job_calls: list[str] = []
        self.list_calls: list[int] = []
        self.start_calls = 0
        self.stop_calls = 0

    async def start(self) -> None:
        self.start_calls += 1

    async def stop(self) -> None:
        self.stop_calls += 1

    def get_background_job(self, job_id: str) -> dict | None:
        self.job_calls.append(job_id)
        return self.job_result

    def list_background_jobs(self, *, limit: int = 20) -> list[dict]:
        self.list_calls.append(limit)
        return self.job_list[:limit]

    def query_background_jobs(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        statuses: list[str] | None = None,
        excluded_statuses: list[str] | None = None,
        keyword: str | None = None,
    ) -> dict:
        self.list_calls.append(limit)
        return {
            "jobs": self.job_list[offset : offset + limit],
            "limit": limit,
            "offset": offset,
            "total": len(self.job_list),
            "status_counts": {"processing": 1},
        }


class BackgroundJobRouteTests(unittest.TestCase):
    def _build_client(self, service: StubKnowledgeBaseService) -> TestClient:
        settings = types.SimpleNamespace(dashscope_api_key="test-key")
        app = create_app(settings=settings, service=service)
        app.dependency_overrides[background_jobs_router_module.get_service] = lambda: service
        return TestClient(app)

    def test_get_background_job_returns_status_and_result(self) -> None:
        service = StubKnowledgeBaseService(
            job_result={
                "job_id": "bg:upload_task_process:task-1",
                "job_type": "upload_task_process",
                "source_type": "upload_task",
                "source_id": "task-1",
                "status": "success",
                "priority": 100,
                "retry_count": 0,
                "max_retries": 0,
                "next_retry_at": None,
                "locked_by": None,
                "locked_at": None,
                "last_error_message": None,
                "started_at": "2026-07-13 14:30:00",
                "finished_at": "2026-07-13 14:31:00",
                "created_at": "2026-07-13 14:29:59",
                "updated_at": "2026-07-13 14:31:00",
                "payload": {"task_id": "task-1"},
                "result": {"task_id": "task-1", "status": "completed"},
            }
        )

        with self._build_client(service) as client:
            response = client.get("/api/v1/background-jobs/bg:upload_task_process:task-1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["job_id"], "bg:upload_task_process:task-1")
        self.assertEqual(response.json()["status"], "success")
        self.assertEqual(response.json()["payload"], {"task_id": "task-1"})
        self.assertEqual(response.json()["result"], {"task_id": "task-1", "status": "completed"})
        self.assertEqual(service.job_calls, ["bg:upload_task_process:task-1"])
        self.assertEqual(service.start_calls, 1)
        self.assertEqual(service.stop_calls, 1)

    def test_get_background_job_returns_404_when_missing(self) -> None:
        service = StubKnowledgeBaseService(job_result=None)

        with self._build_client(service) as client:
            response = client.get("/api/v1/background-jobs/missing")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "background job 不存在"})
        self.assertEqual(service.job_calls, ["missing"])

    def test_list_background_jobs_returns_recent_jobs(self) -> None:
        service = StubKnowledgeBaseService(
            job_list=[
                {
                    "job_id": "bg:upload_task_process:task-1",
                    "job_type": "upload_task_process",
                    "source_type": "upload_task",
                    "source_id": "task-1",
                    "status": "processing",
                    "priority": 100,
                    "retry_count": 0,
                    "max_retries": 0,
                    "next_retry_at": None,
                    "locked_by": "worker-1",
                    "locked_at": "2026-07-13 14:30:00",
                    "last_error_message": None,
                    "started_at": "2026-07-13 14:30:00",
                    "finished_at": None,
                    "created_at": "2026-07-13 14:29:59",
                    "updated_at": "2026-07-13 14:30:00",
                    "payload": {"task_id": "task-1"},
                    "result": {},
                    "upload_task": {
                        "task_id": "task-1",
                        "task_type": "document_upload",
                        "status": "processing",
                        "file_count": 1,
                        "success_count": 0,
                        "failed_count": 0,
                        "pending_count": 1,
                        "processing_count": 0,
                        "brand_code": "100244",
                        "brand_name": "狄耐克",
                        "metadata": {"brand_name": "狄耐克", "brand_code": "100244"},
                        "error_message": None,
                        "created_at": "2026-07-13 14:29:59",
                        "updated_at": "2026-07-13 14:30:00",
                        "files": [
                            {
                                "file_id": 1,
                                "file_index": 0,
                                "file_name": "附件.pdf",
                                "file_role": "attachment",
                                "status": "pending",
                            }
                        ],
                    },
                }
            ]
        )

        with self._build_client(service) as client:
            response = client.get("/api/v1/background-jobs?limit=5&offset=0&status=processing")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["limit"], 5)
        self.assertEqual(response.json()["offset"], 0)
        self.assertEqual(response.json()["total"], 1)
        self.assertEqual(response.json()["status_counts"], {"processing": 1})
        self.assertEqual(response.json()["jobs"][0]["job_id"], "bg:upload_task_process:task-1")
        self.assertEqual(response.json()["jobs"][0]["status"], "processing")
        self.assertEqual(response.json()["jobs"][0]["upload_task"]["brand_name"], "狄耐克")
        self.assertEqual(response.json()["jobs"][0]["upload_task"]["files"][0]["file_name"], "附件.pdf")
        self.assertEqual(service.list_calls, [5])

    def test_list_background_jobs_rejects_unknown_status_filter(self) -> None:
        service = StubKnowledgeBaseService(job_list=[])

        with self._build_client(service) as client:
            response = client.get("/api/v1/background-jobs?status=unknown")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "不支持的 background job 状态筛选"})


if __name__ == "__main__":
    unittest.main()
