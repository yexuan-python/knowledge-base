from __future__ import annotations

import unittest

from knowledge_base.brand_knowledge.application.status_queries import (
    BrandKnowledgeStatusQueryDependencies,
    BrandKnowledgeStatusQueryService,
)


class _FakeBackgroundJobStore:
    def __init__(self) -> None:
        self.list_calls: list[dict] = []
        self.count_calls: list[dict] = []

    def list_recent_jobs(
        self,
        *,
        limit=20,
        offset=0,
        statuses=None,
        excluded_statuses=None,
        keyword=None,
        source_ids=None,
    ):
        self.list_calls.append(
            {
                "limit": limit,
                "offset": offset,
                "statuses": statuses,
                "excluded_statuses": excluded_statuses,
                "keyword": keyword,
                "source_ids": source_ids,
            }
        )
        return [
            {
                "job_id": "bg:upload_task_process:task-1",
                "job_type": "upload_task_process",
                "source_type": "upload_task",
                "source_id": "task-1",
                "status": "processing",
                "priority": 100,
                "retry_count": 0,
                "max_retries": 0,
                "payload_json": {"task_id": "task-1"},
                "result_json": {},
            },
            {
                "job_id": "bg:brand_full_knowledge_refresh:brand-1",
                "job_type": "brand_full_knowledge_refresh",
                "source_type": "brand_knowledge",
                "source_id": "brand-1",
                "status": "success",
                "priority": 100,
                "retry_count": 0,
                "max_retries": 3,
                "payload_json": {"brand_code": "100244"},
                "result_json": {},
            },
        ][offset : offset + limit]

    def count_jobs_by_status(self, *, keyword=None, source_ids=None):
        return {"processing": 1, "success": 1}

    def count_jobs(self, *, statuses=None, excluded_statuses=None, keyword=None, source_ids=None):
        self.count_calls.append(
            {
                "statuses": statuses,
                "excluded_statuses": excluded_statuses,
                "keyword": keyword,
                "source_ids": source_ids,
            }
        )
        return 2


class _FakeUploadTaskStore:
    def __init__(self) -> None:
        self.search_calls: list[str] = []

    def search_upload_task_ids(self, keyword):
        self.search_calls.append(keyword)
        return ["task-1"]

    def get_upload_tasks_by_ids(self, task_ids):
        return {
            "task-1": {
                "task_id": "task-1",
                "task_type": "document_upload",
                "status": "processing",
                "file_count": 2,
                "success_count": 1,
                "failed_count": 0,
                "pending_count": 0,
                "processing_count": 1,
                "metadata_json": {"brand_name": "狄耐克", "brand_code": "100244"},
                "error_message": None,
            }
        }

    def list_upload_task_file_summaries_by_task_ids(self, task_ids):
        return {
            "task-1": [
                {
                    "id": 7,
                    "file_index": 0,
                    "original_filename": "品牌AI知识库.md",
                    "file_role": "brand_ai_knowledge",
                    "status": "success",
                    "document_id": "doc-1",
                    "error_message": None,
                },
                {
                    "id": 8,
                    "file_index": 1,
                    "original_filename": "附件.pdf",
                    "file_role": "attachment",
                    "status": "processing",
                    "asset_id": 88,
                    "error_message": None,
                },
            ]
        }


class BackgroundJobStatusQueryTests(unittest.TestCase):
    def test_query_background_jobs_enriches_upload_task_process_jobs(self) -> None:
        background_jobs = _FakeBackgroundJobStore()
        upload_tasks = _FakeUploadTaskStore()
        service = BrandKnowledgeStatusQueryService(
            BrandKnowledgeStatusQueryDependencies(
                background_jobs=background_jobs,
                brand_knowledge_update_audits=None,
                get_latest_attachment_conflict_session=lambda **_kwargs: None,
                upload_tasks=upload_tasks,
            )
        )

        result = service.query_background_jobs(limit=20, offset=0, keyword="附件.pdf")

        upload_job = result["jobs"][0]
        self.assertEqual(upload_job["upload_task"]["task_id"], "task-1")
        self.assertEqual(upload_job["upload_task"]["brand_name"], "狄耐克")
        self.assertEqual(upload_job["upload_task"]["brand_code"], "100244")
        self.assertEqual(upload_job["upload_task"]["files"][0]["file_name"], "品牌AI知识库.md")
        self.assertEqual(upload_job["upload_task"]["files"][1]["asset_id"], 88)
        self.assertNotIn("upload_task", result["jobs"][1])
        self.assertEqual(upload_tasks.search_calls, ["附件.pdf"])
        self.assertEqual(background_jobs.count_calls[-1]["keyword"], "附件.pdf")
        self.assertEqual(background_jobs.count_calls[-1]["source_ids"], ["task-1"])


if __name__ == "__main__":
    unittest.main()
