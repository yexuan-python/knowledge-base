from __future__ import annotations

from datetime import datetime, timedelta

from knowledge_base.background_jobs.retry_policy import BackgroundJobRetryPolicy


def test_retry_policy_schedules_next_retry_with_backoff() -> None:
    policy = BackgroundJobRetryPolicy(retry_delays_seconds=(60, 120, 180, 300))
    now = datetime(2026, 10, 8, 12, 0, 0)

    decision = policy.decide(job={"retry_count": 0, "max_retries": 4}, now=now)

    assert decision.retry_count == 1
    assert decision.should_retry is True
    assert decision.next_retry_at == now + timedelta(seconds=60)


def test_retry_policy_reuses_last_delay_when_attempt_exceeds_delay_table() -> None:
    policy = BackgroundJobRetryPolicy(retry_delays_seconds=(60, 120))
    now = datetime(2026, 10, 8, 12, 0, 0)

    decision = policy.decide(job={"retry_count": 2, "max_retries": 4}, now=now)

    assert decision.retry_count == 3
    assert decision.should_retry is True
    assert decision.next_retry_at == now + timedelta(seconds=120)


def test_retry_policy_marks_failed_after_max_retries() -> None:
    policy = BackgroundJobRetryPolicy(retry_delays_seconds=(60, 120, 180, 300))
    now = datetime(2026, 10, 8, 12, 0, 0)

    decision = policy.decide(job={"retry_count": 4, "max_retries": 4}, now=now)

    assert decision.retry_count == 5
    assert decision.should_retry is False
    assert decision.next_retry_at is None
