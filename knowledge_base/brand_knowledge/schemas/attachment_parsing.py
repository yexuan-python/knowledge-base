from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AttachmentPreviewItem(BaseModel):
    name: str = Field(min_length=1)
    url: str = Field(min_length=1)


class AttachmentPreviewParseRequest(BaseModel):
    brand_name: str = Field(min_length=1)
    brand_code: str | None = None
    attachments: list[AttachmentPreviewItem] = Field(default_factory=list)

class AttachmentPreviewParseResponse(BaseModel):
    draft_id: str | None = None
    brand_name: str
    status: str | None = None
    candidate_snapshot: dict[str, Any] = Field(default_factory=dict)
    field_labels: dict[str, str] = Field(default_factory=dict)
    knowledge_revision: str | None = None


class AttachmentReviewChangeSummary(BaseModel):
    added_field_count: int = 0
    modified_field_count: int = 0
    deleted_field_count: int = 0


class AttachmentReviewChangeItem(BaseModel):
    field_path: str
    field_label: str | None = None
    change_type: str
    old_value: Any | None = None
    new_value: Any | None = None


class AttachmentReviewChangesRequest(BaseModel):
    draft_id: str = Field(min_length=1)
    candidate_snapshot: dict[str, Any] = Field(default_factory=dict)
    brand_code: str | None = None
    brand_name: str | None = None
    knowledge_revision: str | None = None


class AttachmentReviewChangesResponse(BaseModel):
    review_id: str
    draft_id: str
    brand_code: str | None = None
    brand_name: str
    knowledge_revision: str | None = None
    summary: AttachmentReviewChangeSummary = Field(default_factory=AttachmentReviewChangeSummary)
    changes: list[AttachmentReviewChangeItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    can_confirm: bool = True


class AttachmentConfirmSaveRequest(BaseModel):
    draft_id: str = Field(min_length=1)
    review_id: str | None = None
    confirmed_text: str | None = Field(default=None, description="已废弃；确认保存必须传 review_id")
    brand_name: str | None = Field(default=None, description="可选品牌名称；不传时默认使用 preview-parse 草稿中的 brand_name")
    knowledge_revision: str | None = None


class AttachmentConfirmSaveResponse(BaseModel):
    draft_id: str
    brand_code: str | None = None
    brand_id: int | None = None
    brand_name: str
    status: str
    updated_sections: list[str] = Field(default_factory=list)
    knowledge_revision: str | None = None
    final_markdown_oss_key: str | None = None
    final_markdown_oss_url: str | None = None
    final_document_id: str | None = None
    original_attachments: list[dict[str, Any]] = Field(default_factory=list)
    attachment_documents: list[dict[str, Any]] = Field(default_factory=list)
    background_job_id: str | None = None
    background_job_status: str | None = None
    full_knowledge_refresh_job_id: str | None = None
    full_knowledge_refresh_status: str | None = None
    confirm_callback_status: str | None = None


class AttachmentConfirmResultData(BaseModel):
    version: str = ""
    brand_code: str | None = None
    brand_id: int | None = None
    brand_name: str = ""
    updated_sections: list[str] = Field(default_factory=list)
    knowledge_revision: str = ""
    final_markdown_oss_key: str = ""
    final_markdown_oss_url: str = ""
    final_document_id: str = ""
    original_attachments: list[dict[str, Any]] = Field(default_factory=list)
    attachment_documents: list[dict[str, Any]] = Field(default_factory=list)
    confirm_callback_status: str = ""
    full_knowledge_refresh_job_id: str = ""
    full_knowledge_refresh_status: str = ""
    oss_url_md: str = ""
    oss_url_pdf: str = ""


class AttachmentConfirmResultResponse(BaseModel):
    code: int
    message: str
    data: AttachmentConfirmResultData | None = None
