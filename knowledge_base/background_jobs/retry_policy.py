from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


DEFAULT_RETRY_DELAYS_SECONDS = (60, 120, 180, 300)


@dataclass(frozen=True)
class BackgroundJobRetryDecision:
    retry_count: int
    should_retry: bool
    next_retry_at: datetime | None


@dataclass(frozen=True)
class BackgroundJobRetryPolicy:
    retry_delays_seconds: tuple[int, ...] = DEFAULT_RETRY_DELAYS_SECONDS

    def decide(self, *, job: dict[str, Any], now: datetime | None = None) -> BackgroundJobRetryDecision:
        retry_count = int(job.get("retry_count") or 0) + 1
        max_retries = int(job.get("max_retries") or len(self.retry_delays_seconds))
        if retry_count <= max_retries:
            decision_time = now or datetime.now()
            delay_seconds = self.retry_delays_seconds[
                min(retry_count - 1, len(self.retry_delays_seconds) - 1)
            ]
            return BackgroundJobRetryDecision(
                retry_count=retry_count,
                should_retry=True,
                next_retry_at=decision_time + timedelta(seconds=delay_seconds),
            )
        return BackgroundJobRetryDecision(
            retry_count=retry_count,
            should_retry=False,
            next_retry_at=None,
        )
