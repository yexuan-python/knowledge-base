from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable


logger = logging.getLogger(__name__)


class UploadTaskQueueCoordinator:
    def __init__(
        self,
        *,
        dependencies: Any,
        lifecycle: Any,
        process_upload_task: Callable[[str], Awaitable[None]],
    ) -> None:
        self._deps = dependencies
        self._lifecycle = lifecycle
        self._process_upload_task = process_upload_task

    async def schedule_upload_task(self, task_id: str) -> None:
        if callable(self._deps.enqueue_upload_task_process_job):
            logger.info("Upload task delegated to background job task_id=%s", task_id)
            await self._deps.enqueue_upload_task_process_job(task_id)
            return

        async with self._deps.queue_lock:
            if task_id in self._deps.queued_task_ids:
                logger.info("Upload task already queued task_id=%s", task_id)
                return
            self._deps.queued_task_ids.add(task_id)
            await self._deps.queue.put(task_id)
        logger.info("Upload task queued in memory task_id=%s", task_id)

    async def upload_worker(self) -> None:
        while True:
            task_id = await self._deps.queue.get()
            logger.info("Upload worker picked task_id=%s", task_id)
            async with self._deps.queue_lock:
                self._deps.queued_task_ids.discard(task_id)
            try:
                await self._process_upload_task(task_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Upload task failed unexpectedly task_id=%s", task_id)
                self._lifecycle.fail_task_for_background_exception(task_id)
            finally:
                self._deps.queue.task_done()
