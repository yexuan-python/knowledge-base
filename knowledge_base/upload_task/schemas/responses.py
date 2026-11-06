from __future__ import annotations

from pydantic import BaseModel, Field


class UploadTaskCreateResponse(BaseModel):
    task_id: str
    status: str
    file_count: int
    message: str


class UploadTaskFileStatus(BaseModel):
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
    oss_key: str | None = None
    oss_url: str | None = None
    knowledge_markdown_oss_url: str | None = None
    knowledge_pdf_oss_url: str | None = None
    asset_id: int | None = None
    full_knowledge_file_id: int | None = None
    brand_name: str | None = None
    brand_code: str | None = None
    current_step: str | None = None
    parse_status: str | None = None
    pdf_status: str | None = None
    ingest_status: str | None = None
    mysql_status: str | None = None
    milvus_status: str | None = None
    cleanup_status: str | None = None
    is_latest: bool | None = None
    error_message: str | None = None
    facts_status: str | None = None
    facts_error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class UploadTaskStatusResponse(BaseModel):
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
    knowledge_session_id: str | None = None
    knowledge_session_status: str | None = None
    error_message: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    files: list[UploadTaskFileStatus] = Field(default_factory=list)
