from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import Any

from knowledge_base.shared.utils import parse_metadata_json

CallbackPostResult = tuple[int | None, str | None] | tuple[int | None, str | None, str | None]
CallbackPost = Callable[[str, dict[str, Any], float], CallbackPostResult]


def seconds_until(next_retry_at: Any) -> float:
    if not isinstance(next_retry_at, datetime):
        return 0.0
    return max(0.0, (next_retry_at - datetime.now()).total_seconds())


def load_callback_payload(callback: dict[str, Any], *, label: str) -> dict[str, Any]:
    payload = parse_metadata_json(callback.get("request_payload_json"))
    if not payload:
        raise ValueError(f"{label} callback 缺少 request_payload_json")
    return payload


async def deliver_upload_task_callback(
    *,
    callback_store: Any | None,
    task_id: str | None,
    callback_type: str | None,
    callback_url: str,
    payload: dict[str, Any],
    timeout_seconds: float,
    retry_delays_seconds: Sequence[int],
    post_callback: CallbackPost,
    missing_url_error: str,
    max_retries: int | None = None,
    non_2xx_error_message: str | None = "auto",
    raise_on_failure: bool = False,
    include_response_body: bool = False,
) -> dict[str, Any]:
    normalized_url = str(callback_url or "").strip()
    if not normalized_url:
        return _result(
            status="skipped",
            response_code=None,
            error=missing_url_error,
            response_body=None,
            include_response_body=include_response_body,
        )

    can_persist = callback_store is not None and bool(task_id) and bool(callback_type)
    retry_count = 0
    if can_persist:
        callback_store.upsert_upload_task_callback(
            task_id=task_id,
            callback_type=callback_type,
            callback_url=normalized_url,
            request_payload_json=payload,
            status="pending",
        )
        callback = callback_store.get_upload_task_callback(task_id=task_id, callback_type=callback_type)
        retry_count = int((callback or {}).get("retry_count") or 0)

    try:
        post_result = await asyncio.to_thread(
            post_callback,
            normalized_url,
            payload,
            timeout_seconds,
        )
        response_code, response_body, error_message = _normalize_post_result(post_result)
    except Exception as exc:  # noqa: BLE001
        result = _record_failure(
            callback_store=callback_store if can_persist else None,
            task_id=task_id,
            callback_type=callback_type,
            payload=payload,
            retry_count=retry_count,
            retry_delays_seconds=retry_delays_seconds,
            max_retries=max_retries,
            response_code=None,
            response_body=None,
            error_message=str(exc),
            include_response_body=include_response_body,
        )
        if raise_on_failure:
            raise
        return result

    if error_message:
        result = _record_failure(
            callback_store=callback_store if can_persist else None,
            task_id=task_id,
            callback_type=callback_type,
            payload=payload,
            retry_count=retry_count,
            retry_delays_seconds=retry_delays_seconds,
            max_retries=max_retries,
            response_code=response_code,
            response_body=response_body,
            error_message=error_message,
            include_response_body=include_response_body,
        )
        if raise_on_failure:
            raise RuntimeError(error_message)
        return result

    if response_code is not None and 200 <= response_code < 300:
        if can_persist:
            callback_store.update_upload_task_callback_result(
                task_id=task_id,
                callback_type=callback_type,
                request_payload_json=payload,
                status="success",
                retry_count=retry_count,
                next_retry_at=None,
                last_response_code=response_code,
                last_response_body=response_body,
                last_error_message=None,
                sent_at=datetime.now(),
            )
        return _result(
            status="success",
            response_code=response_code,
            error=None,
            response_body=response_body,
            include_response_body=include_response_body,
        )

    resolved_error_message = (
        f"callback response code={response_code}"
        if non_2xx_error_message == "auto"
        else non_2xx_error_message
    )
    result = _record_failure(
        callback_store=callback_store if can_persist else None,
        task_id=task_id,
        callback_type=callback_type,
        payload=payload,
        retry_count=retry_count,
        retry_delays_seconds=retry_delays_seconds,
        max_retries=max_retries,
        response_code=response_code,
        response_body=response_body,
        error_message=resolved_error_message,
        include_response_body=include_response_body,
    )
    if raise_on_failure:
        raise RuntimeError(f"callback response code={response_code}")
    return result


def _normalize_post_result(result: CallbackPostResult) -> tuple[int | None, str | None, str | None]:
    if len(result) == 3:
        response_code, response_body, error_message = result
        return response_code, response_body, error_message
    response_code, response_body = result
    return response_code, response_body, None


def _record_failure(
    *,
    callback_store: Any | None,
    task_id: str | None,
    callback_type: str | None,
    payload: dict[str, Any],
    retry_count: int,
    retry_delays_seconds: Sequence[int],
    max_retries: int | None,
    response_code: int | None,
    response_body: str | None,
    error_message: str | None,
    include_response_body: bool,
) -> dict[str, Any]:
    next_retry_count = retry_count + 1
    retry_limit = len(retry_delays_seconds) if max_retries is None else max(0, int(max_retries))
    can_retry = callback_store is not None and next_retry_count <= retry_limit
    next_retry_at = None
    status = "failed"
    if can_retry:
        delay_index = min(next_retry_count - 1, max(len(retry_delays_seconds) - 1, 0))
        delay_seconds = retry_delays_seconds[delay_index] if retry_delays_seconds else 0
        next_retry_at = datetime.now() + timedelta(seconds=delay_seconds)
        status = "retrying"

    if callback_store is not None:
        callback_store.update_upload_task_callback_result(
            task_id=task_id,
            callback_type=callback_type,
            request_payload_json=payload,
            status=status,
            retry_count=next_retry_count,
            next_retry_at=next_retry_at,
            last_response_code=response_code,
            last_response_body=response_body,
            last_error_message=error_message,
            sent_at=None,
        )

    return _result(
        status=status,
        response_code=response_code,
        error=error_message,
        response_body=response_body,
        include_response_body=include_response_body,
    )


def _result(
    *,
    status: str,
    response_code: int | None,
    error: str | None,
    response_body: str | None,
    include_response_body: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": status,
        "response_code": response_code,
        "error": error,
    }
    if include_response_body:
        result["response_body"] = response_body
    return result
