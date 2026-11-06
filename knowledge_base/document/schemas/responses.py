from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    collection_name: str


class SearchResultMetadata(BaseModel):
    brand_id: str | int | None = None
    brand_code: str | None = None
    brand_name: str | None = None
    product_code: str | None = None
    product_name: str | None = None
    kb_version: str | None = None
    section_title: str | None = None
    source_url: str | None = None
    content_hash: str | None = None


class SearchResultItem(BaseModel):
    chunk_id: str | None = None
    content: str
    score: float | None = None
    brand_name: str | None = None
    category: str | None = None
    metadata: SearchResultMetadata | None = None


class SearchResponse(BaseModel):
    code: int = 0
    message: str = "ok"
    data: list[SearchResultItem] = Field(default_factory=list)


class ImageSearchResultItem(BaseModel):
    asset_id: int
    document_id: str
    score: float | None = None
    brand_code: str | None = None
    brand_name: str | None = None
    product_code: str | None = None
    product_name: str | None = None
    subcategory: str | None = None
    original_filename: str | None = None
    oss_url: str | None = None
    source_url: str | None = None
    content_type: str | None = None
    file_size: int | None = None
    image_summary: str | None = None
    image_tags: list[str] = Field(default_factory=list)


class ImageSearchResponse(BaseModel):
    code: int = 0
    message: str = "ok"
    data: list[ImageSearchResultItem] = Field(default_factory=list)


class BrandFactsResponse(BaseModel):
    brand_code: str | None = None
    brand_name: str | None = None
    category: str | None = None
    product_code: str | None = None
    query: str | None = None
    facts: list[dict | str] = Field(default_factory=list)


class BrandFactsIngestResponse(BaseModel):
    status: str
    brand_code: str
    brand_name: str
    document_id: str
    fact_count: int
    deleted_fact_count: int
    content_hash: str
    content_type: str | None = None
    file_hash: str | None = None
    file_size: int | None = None
    file_name: str | None = None


class AttachmentDeleteResultItem(BaseModel):
    name: str
    url: str | None = None
    status: str
    document_id: str | None = None
    matched_document_ids: list[str] = Field(default_factory=list)
    detail: str | None = None


class AttachmentDeleteSummary(BaseModel):
    requested_count: int
    deleted_count: int
    not_found_count: int
    failed_count: int
    ambiguous_count: int


class AttachmentDeleteResponse(BaseModel):
    brand_code: str
    brand_name: str
    summary: AttachmentDeleteSummary
    results: list[AttachmentDeleteResultItem] = Field(default_factory=list)


class AttachmentDeleteDataItem(BaseModel):
    brand_code: str
    brand_name: str
    name: str
    url: str | None = None
    status: str
    document_id: str | None = None
    matched_document_ids: list[str] = Field(default_factory=list)
    detail: str = ""


class AttachmentDeleteApiResponse(BaseModel):
    code: str
    message: str
    data: AttachmentDeleteDataItem | list[AttachmentDeleteDataItem] | None = None
