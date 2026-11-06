from __future__ import annotations

import types
import unittest

from knowledge_base.upload_task.application.lifecycle import (
    FILE_STATUS_FAILED,
    FILE_STATUS_PENDING,
    FILE_STATUS_PROCESSING,
    FILE_STATUS_SUCCESS,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_COMPLETED_WITH_ERRORS,
    TASK_STATUS_FAILED,
    TASK_STATUS_PROCESSING,
    TASK_STATUS_QUEUED,
    UploadTaskLifecycle,
)


class _FakeUploadTaskStore:
    def __init__(self) -> None:
        self.task = {
            "task_id": "task-1",
            "status": TASK_STATUS_QUEUED,
            "error_message": None,
        }
        self.files = [
            {"id": 1, "status": FILE_STATUS_PENDING},
            {"id": 2, "status": FILE_STATUS_PENDING},
        ]
        self.task_status_updates: list[tuple[str, str, str | None]] = []
        self.file_status_updates: list[tuple[int, str, dict]] = []

    def get_upload_task(self, task_id: str):
        if task_id != self.task["task_id"]:
            return None
        return dict(self.task)

    def refresh_upload_task_counts(self, task_id: str):
        if task_id != self.task["task_id"]:
            return None
        return {
            "file_count": len(self.files),
            "success_count": sum(1 for item in self.files if item["status"] == FILE_STATUS_SUCCESS),
            "failed_count": sum(1 for item in self.files if item["status"] == FILE_STATUS_FAILED),
            "pending_count": sum(1 for item in self.files if item["status"] == FILE_STATUS_PENDING),
            "processing_count": sum(1 for item in self.files if item["status"] == FILE_STATUS_PROCESSING),
        }

    def update_upload_task_status(self, task_id: str, status: str, error_message=None):
        self.task_status_updates.append((task_id, status, error_message))
        if task_id == self.task["task_id"]:
            self.task["status"] = status
            self.task["error_message"] = error_message

    def update_upload_task_file_status(self, file_id: int, status: str, **kwargs):
        self.file_status_updates.append((file_id, status, kwargs))
        for item in self.files:
            if int(item["id"]) == file_id:
                item["status"] = status
                item.update(kwargs)
                break


class UploadTaskLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.upload_tasks = _FakeUploadTaskStore()
        self.lifecycle = UploadTaskLifecycle(dependencies=types.SimpleNamespace(upload_tasks=self.upload_tasks))

    def test_defines_legal_task_and_file_transitions(self) -> None:
        self.assertTrue(
            self.lifecycle.can_transition_task(
                current_status=TASK_STATUS_QUEUED,
                next_status=TASK_STATUS_PROCESSING,
            )
        )
        self.assertFalse(
            self.lifecycle.can_transition_task(
                current_status=TASK_STATUS_COMPLETED,
                next_status=TASK_STATUS_FAILED,
            )
        )
        self.assertTrue(
            self.lifecycle.can_transition_file(
                current_status=FILE_STATUS_PENDING,
                next_status=FILE_STATUS_PROCESSING,
            )
        )
        self.assertFalse(
            self.lifecycle.can_transition_file(
                current_status=FILE_STATUS_SUCCESS,
                next_status=FILE_STATUS_FAILED,
            )
        )

    def test_completes_task_from_file_counts_with_errors(self) -> None:
        self.lifecycle.start_task("task-1")
        self.lifecycle.start_file(task_id="task-1", file_id=1, current_status=FILE_STATUS_PENDING)
        self.lifecycle.mark_file_success(task_id="task-1", file_id=1, document_id="doc-1")
        self.lifecycle.start_file(task_id="task-1", file_id=2, current_status=FILE_STATUS_PENDING)
        self.lifecycle.mark_file_failed(task_id="task-1", file_id=2, error_message="parse failed")

        completion = self.lifecycle.complete_task_from_file_counts("task-1")

        self.assertEqual(completion.status, TASK_STATUS_COMPLETED_WITH_ERRORS)
        self.assertEqual(completion.counts["success_count"], 1)
        self.assertEqual(completion.counts["failed_count"], 1)
        self.assertEqual(self.upload_tasks.task["status"], TASK_STATUS_COMPLETED_WITH_ERRORS)
        self.assertEqual(self.upload_tasks.files[0]["document_id"], "doc-1")
        self.assertEqual(self.upload_tasks.files[1]["error_message"], "parse failed")

    def test_completes_empty_task(self) -> None:
        self.upload_tasks.files = []

        completion = self.lifecycle.complete_empty_task("task-1")

        self.assertEqual(completion.status, TASK_STATUS_COMPLETED)
        self.assertEqual(completion.counts["file_count"], 0)
        self.assertEqual(self.upload_tasks.task["status"], TASK_STATUS_COMPLETED)

    def test_marks_background_exception_as_failed_and_refreshes_counts(self) -> None:
        self.lifecycle.start_task("task-1")

        counts = self.lifecycle.fail_task_for_background_exception("task-1")

        self.assertEqual(self.upload_tasks.task["status"], TASK_STATUS_FAILED)
        self.assertEqual(self.upload_tasks.task["error_message"], "后台任务执行异常")
        self.assertEqual(counts["pending_count"], 2)
