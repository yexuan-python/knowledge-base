from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any


logger = logging.getLogger(__name__)

TASK_STATUS_QUEUED = "queued"
TASK_STATUS_PROCESSING = "processing"
TASK_STATUS_COMPLETED = "completed"
TASK_STATUS_COMPLETED_WITH_ERRORS = "completed_with_errors"
TASK_STATUS_FAILED = "failed"

FILE_STATUS_PENDING = "pending"
FILE_STATUS_PROCESSING = "processing"
FILE_STATUS_SUCCESS = "success"
FILE_STATUS_FAILED = "failed"

TASK_TERMINAL_STATUSES = {
    TASK_STATUS_COMPLETED,
    TASK_STATUS_COMPLETED_WITH_ERRORS,
    TASK_STATUS_FAILED,
}
FILE_TERMINAL_STATUSES = {FILE_STATUS_SUCCESS, FILE_STATUS_FAILED}

_TASK_TRANSITIONS: dict[str, set[str]] = {
    TASK_STATUS_QUEUED: {
        TASK_STATUS_PROCESSING,
        TASK_STATUS_COMPLETED,
        TASK_STATUS_FAILED,
    },
    TASK_STATUS_PROCESSING: {
        TASK_STATUS_COMPLETED,
        TASK_STATUS_COMPLETED_WITH_ERRORS,
        TASK_STATUS_FAILED,
    },
    TASK_STATUS_COMPLETED: {TASK_STATUS_COMPLETED},
    TASK_STATUS_COMPLETED_WITH_ERRORS: {TASK_STATUS_COMPLETED_WITH_ERRORS},
    TASK_STATUS_FAILED: {TASK_STATUS_FAILED},
}
_FILE_TRANSITIONS: dict[str, set[str]] = {
    FILE_STATUS_PENDING: {
        FILE_STATUS_PROCESSING,
        FILE_STATUS_SUCCESS,
        FILE_STATUS_FAILED,
    },
    FILE_STATUS_PROCESSING: {
        FILE_STATUS_SUCCESS,
        FILE_STATUS_FAILED,
    },
    FILE_STATUS_SUCCESS: {FILE_STATUS_SUCCESS},
    FILE_STATUS_FAILED: {FILE_STATUS_FAILED},
}


@dataclass(frozen=True)
class UploadTaskCompletion:
    status: str
    counts: dict[str, int]


class UploadTaskLifecycle:
    def __init__(self, *, dependencies: Any) -> None:
        self._deps = dependencies

    def start_task(self, task_id: str) -> dict[str, int]:
        self._transition_task(task_id, TASK_STATUS_PROCESSING)
        return self.refresh_counts(task_id)

    def complete_empty_task(self, task_id: str) -> UploadTaskCompletion:
        counts = self.refresh_counts(task_id)
        self._transition_task(task_id, TASK_STATUS_COMPLETED)
        return UploadTaskCompletion(status=TASK_STATUS_COMPLETED, counts=counts)

    def complete_task_from_file_counts(self, task_id: str) -> UploadTaskCompletion:
        counts = self.refresh_counts(task_id)
        failed_count = int(counts.get("failed_count") or 0)
        final_status = TASK_STATUS_COMPLETED_WITH_ERRORS if failed_count else TASK_STATUS_COMPLETED
        self._transition_task(task_id, final_status)
        return UploadTaskCompletion(status=final_status, counts=counts)

    def fail_task_for_background_exception(self, task_id: str, error_message: str = "后台任务执行异常") -> dict[str, int]:
        self._transition_task(task_id, TASK_STATUS_FAILED, error_message=error_message)
        return self.refresh_counts(task_id)

    def start_file(self, *, task_id: str, file_id: int, current_status: str | None = None) -> dict[str, int]:
        self._transition_file(
            file_id=file_id,
            status=FILE_STATUS_PROCESSING,
            current_status=current_status,
        )
        return self.refresh_counts(task_id)

    def mark_file_success(self, *, task_id: str, file_id: int, **kwargs: Any) -> dict[str, int]:
        self._transition_file(
            file_id=file_id,
            status=FILE_STATUS_SUCCESS,
            current_status=FILE_STATUS_PROCESSING,
            **kwargs,
        )
        return self.refresh_counts(task_id)

    def mark_file_failed(self, *, task_id: str, file_id: int, error_message: str) -> dict[str, int]:
        self._transition_file(
            file_id=file_id,
            status=FILE_STATUS_FAILED,
            current_status=FILE_STATUS_PROCESSING,
            error_message=error_message,
        )
        return self.refresh_counts(task_id)

    def refresh_counts(self, task_id: str) -> dict[str, int]:
        counts = self._deps.upload_tasks.refresh_upload_task_counts(task_id)
        return dict(counts or {})

    def can_transition_task(self, *, current_status: str | None, next_status: str) -> bool:
        if not current_status:
            return True
        return next_status in _TASK_TRANSITIONS.get(current_status, set())

    def can_transition_file(self, *, current_status: str | None, next_status: str) -> bool:
        if not current_status:
            return True
        return next_status in _FILE_TRANSITIONS.get(current_status, set())

    def _transition_task(
        self,
        task_id: str,
        status: str,
        *,
        error_message: str | None = None,
    ) -> None:
        current_status = self._get_task_status(task_id)
        if not self.can_transition_task(current_status=current_status, next_status=status):
            logger.warning(
                "Upload task status transition is unusual task_id=%s current=%s next=%s",
                task_id,
                current_status,
                status,
            )
        self._deps.upload_tasks.update_upload_task_status(task_id, status, error_message)

    def _transition_file(
        self,
        *,
        file_id: int,
        status: str,
        current_status: str | None = None,
        **kwargs: Any,
    ) -> None:
        if not self.can_transition_file(current_status=current_status, next_status=status):
            logger.warning(
                "Upload task file status transition is unusual file_id=%s current=%s next=%s",
                file_id,
                current_status,
                status,
            )
        self._deps.upload_tasks.update_upload_task_file_status(file_id, status, **kwargs)

    def _get_task_status(self, task_id: str) -> str | None:
        if not hasattr(self._deps.upload_tasks, "get_upload_task"):
            return None
        task = self._deps.upload_tasks.get_upload_task(task_id)
        if not isinstance(task, dict):
            return None
        return str(task.get("status") or "").strip() or None
