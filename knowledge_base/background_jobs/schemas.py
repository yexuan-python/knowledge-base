from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class BackgroundJobUploadTaskFileSummary(BaseModel):
    file_id: int
    file_index: int
    file_name: str
    file_role: str | None = None
    status: str
    file_size: int | None = None
    file_hash: str | None = None
    content_type: str | None = None
    converted_version: int | None = None
    document_id: str | None = None
    source_type: str | None = None
    chunk_count: int | None = None
    asset_id: int | None = None
    full_knowledge_file_id: int | None = None
    error_message: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class BackgroundJobUploadTaskSummary(BaseModel):
    task_id: str
    task_type: str | None = None
    status: str
    file_count: int
    success_count: int
    failed_count: int
    pending_count: int
    processing_count: int
    brand_code: str | None = None
    brand_name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    files: list[BackgroundJobUploadTaskFileSummary] = Field(default_factory=list)


class BackgroundJobResponse(BaseModel):
    job_id: str
    job_type: str
    source_type: str | None = None
    source_id: str | None = None
    status: str
    priority: int = 100
    retry_count: int = 0
    max_retries: int = 0
    next_retry_at: str | None = None
    locked_by: str | None = None
    locked_at: str | None = None
    last_error_message: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    upload_task: BackgroundJobUploadTaskSummary | None = None


class BackgroundJobListResponse(BaseModel):
    jobs: list[BackgroundJobResponse] = Field(default_factory=list)
    limit: int = 20
    offset: int = 0
    total: int = 0
    status_counts: dict[str, int] = Field(default_factory=dict)
