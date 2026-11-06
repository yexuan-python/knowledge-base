from __future__ import annotations

import asyncio
import types
import unittest
from contextlib import suppress

from knowledge_base.upload_task.application.queue_coordinator import UploadTaskQueueCoordinator


class _FakeLifecycle:
    def __init__(self) -> None:
        self.failed_task_ids: list[str] = []

    def fail_task_for_background_exception(self, task_id: str):
        self.failed_task_ids.append(task_id)
        return {}


class UploadTaskQueueCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_schedule_delegates_to_background_job_when_available(self) -> None:
        delegated_task_ids: list[str] = []

        async def enqueue_background_job(task_id: str) -> None:
            delegated_task_ids.append(task_id)

        deps = types.SimpleNamespace(
            enqueue_upload_task_process_job=enqueue_background_job,
            queue=asyncio.Queue(),
            queued_task_ids=set(),
            queue_lock=asyncio.Lock(),
        )
        coordinator = UploadTaskQueueCoordinator(
            dependencies=deps,
            lifecycle=_FakeLifecycle(),
            process_upload_task=lambda _task_id: None,
        )

        await coordinator.schedule_upload_task("task-1")

        self.assertEqual(delegated_task_ids, ["task-1"])
        self.assertEqual(deps.queue.qsize(), 0)
        self.assertEqual(deps.queued_task_ids, set())

    async def test_schedule_deduplicates_in_memory_queue(self) -> None:
        deps = types.SimpleNamespace(
            enqueue_upload_task_process_job=None,
            queue=asyncio.Queue(),
            queued_task_ids=set(),
            queue_lock=asyncio.Lock(),
        )
        coordinator = UploadTaskQueueCoordinator(
            dependencies=deps,
            lifecycle=_FakeLifecycle(),
            process_upload_task=lambda _task_id: None,
        )

        await coordinator.schedule_upload_task("task-1")
        await coordinator.schedule_upload_task("task-1")

        self.assertEqual(deps.queue.qsize(), 1)
        self.assertEqual(deps.queued_task_ids, {"task-1"})
        self.assertEqual(await deps.queue.get(), "task-1")
        deps.queue.task_done()

    async def test_worker_marks_task_failed_when_processing_raises(self) -> None:
        lifecycle = _FakeLifecycle()
        processed_task_ids: list[str] = []

        async def process_upload_task(task_id: str) -> None:
            processed_task_ids.append(task_id)
            raise RuntimeError("boom")

        deps = types.SimpleNamespace(
            enqueue_upload_task_process_job=None,
            queue=asyncio.Queue(),
            queued_task_ids={"task-1"},
            queue_lock=asyncio.Lock(),
        )
        coordinator = UploadTaskQueueCoordinator(
            dependencies=deps,
            lifecycle=lifecycle,
            process_upload_task=process_upload_task,
        )

        await deps.queue.put("task-1")
        worker_task = asyncio.create_task(coordinator.upload_worker())
        await deps.queue.join()
        worker_task.cancel()
        with suppress(asyncio.CancelledError):
            await worker_task

        self.assertEqual(processed_task_ids, ["task-1"])
        self.assertEqual(lifecycle.failed_task_ids, ["task-1"])
        self.assertEqual(deps.queued_task_ids, set())
