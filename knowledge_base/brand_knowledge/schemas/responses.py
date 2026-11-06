from __future__ import annotations

from pydantic import BaseModel


class BrandKnowledgeConflictOption(BaseModel):
    option_id: str
    content: str
    source_files: list[str] = []


class BrandKnowledgeConflictItem(BaseModel):
    conflict_id: str
    topic: str
    severity: str | None = None
    description: str | None = None
    options: list[BrandKnowledgeConflictOption] = []


class BrandKnowledgeAutoMergedItem(BaseModel):
    topic: str
    category: str
    resolution: str
    source_files: list[str] = []


class BrandKnowledgeSourceDocumentItem(BaseModel):
    document_id: str
    original_filename: str
    source_type: str | None = None
    fulltext_key: str | None = None
    source_url: str | None = None
    subcategory: str | None = None
    asset_id: int | None = None
    oss_url: str | None = None
    source_role: str | None = None


class BrandKnowledgeSessionResponse(BaseModel):
    session_id: str
    brand_code: str | None = None
    brand_name: str
    status: str
    knowledge_markdown_status: str | None = None
    round_no: int
    session_type: str | None = None
    iteration_mode: str | None = None
    session_kind: str | None = None
    source_task_id: str | None = None
    assistant_message: str | None = None
    source_documents: list[BrandKnowledgeSourceDocumentItem] = []
    conflicts: list[BrandKnowledgeConflictItem] = []
    conflict_markdown: str | None = None
    scan_summary: str | None = None
    auto_merged: list[BrandKnowledgeAutoMergedItem] = []
    final_markdown: str | None = None
    final_oss_key: str | None = None
    final_filename: str | None = None
    final_full_knowledge_file_id: int | None = None
    final_document_id: str | None = None
    knowledge_oss_url_md: str | None = None
    knowledge_oss_url_pdf: str | None = None


class BrandKnowledgeSessionEmptyResponse(BaseModel):
    brand_code: str | None = None
    brand_name: str
    status: str
    knowledge_markdown_status: str | None = None
