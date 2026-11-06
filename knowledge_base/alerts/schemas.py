from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DocumentAlert(BaseModel):
    id: int | None = None
    alert_type: str = Field(..., max_length=64)
    alert_name: str = Field(..., max_length=128)
    dedupe_key: str = Field(..., max_length=255)
    task_id: str | None = Field(None, max_length=128)
    document_id: str | None = Field(None, max_length=128)
    document_name: str = Field(..., max_length=128)
    reason: str | None = None
    payload_json: dict[str, Any]
    send_status: str
    send_response: str | None = None
    send_error: str | None = None
    created_at: datetime | None = None
    sent_at: datetime | None = None
