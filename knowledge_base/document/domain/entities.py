from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class IngestedDocument(BaseModel):
    document_id: str
    source_name: str
    source_type: str
    chunk_count: int
    metadata: dict[str, Any] = Field(default_factory=dict)
