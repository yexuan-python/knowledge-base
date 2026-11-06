from __future__ import annotations

from typing import Any, Mapping

import requests


def post_json_text_response(
    url: str,
    payload: Mapping[str, Any],
    *,
    timeout_seconds: float,
    headers: Mapping[str, str] | None = None,
) -> tuple[int, str]:
    response = requests.post(
        url,
        json=dict(payload),
        headers=dict(headers) if headers else None,
        timeout=timeout_seconds,
    )
    return response.status_code, response.text
