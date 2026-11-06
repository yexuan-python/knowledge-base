from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class BrandListItem(BaseModel):
    id: int
    brand_code: str | None = None
    brand_name: str
    brand_alias: str | None = None
    website: list[str] = Field(default_factory=list)
    intro: str | None = None
    updated_at: datetime | None = None


class BrandListResponse(BaseModel):
    keyword: str | None = None
    brands: list[BrandListItem] = Field(default_factory=list)


class BrandMetaEntity(BaseModel):
    product_code: str | None = None
    name: str
    aliases: list[str] = Field(default_factory=list)
    path: str | None = None
    intro: str | None = None


class BrandMetaPayload(BaseModel):
    brand_code: str
    brand_name: str
    brand_aliases: list[str] = Field(default_factory=list)
    brand_english_name: str = ""
    industry: str = ""
    official_websites: list[str] = Field(default_factory=list)
    knowledge_revision: str = ""
    company_subject_name: str = ""
    company_profile: dict[str, Any] = Field(default_factory=dict)
    products: list[BrandMetaEntity] = Field(default_factory=list)
    competitors: list[BrandMetaEntity] = Field(default_factory=list)


class BrandPathIndexItem(BaseModel):
    path: str
    title: str
    summary: str


class BrandMetaDataResponse(BaseModel):
    meta: BrandMetaPayload
    path_index: list[BrandPathIndexItem] = Field(default_factory=list)


class BrandAssetItem(BaseModel):
    title: str
    path: str
    content: str
    knowledge_revision: str
    updated_at: datetime | None = None


class BrandMissingPathItem(BaseModel):
    path: str
    reason: str


class BrandPathsLoadDataResponse(BaseModel):
    assets: list[BrandAssetItem] = Field(default_factory=list)
    missing_paths: list[BrandMissingPathItem] = Field(default_factory=list)


class BrandLatestAiKnowledgeDataResponse(BaseModel):
    brand_code: str
    brand_name: str
    brand_id: int | None = None
    file_name: str
    oss_key: str
    oss_url: str
    version_no: int | None = None
    created_at: datetime | None = None
    source: str = "brand_full_knowledge_files"


class BrandOfficialMallItem(BaseModel):
    store_name: str = ""
    platform: str = ""
    homepage_urls: list[str] = Field(default_factory=list)
    store_ids: list[str] = Field(default_factory=list)
    main_categories: list[str] = Field(default_factory=list)
    advantages: list[str] = Field(default_factory=list)
    related_products: list[int | str] = Field(default_factory=list)
    other_info: list[str] = Field(default_factory=list)


class BrandOfficialMallsDataResponse(BaseModel):
    brand_code: str
    brand_name: str
    knowledge_revision: str = ""
    official_malls: list[BrandOfficialMallItem] = Field(default_factory=list)


class BrandDeleteCounts(BaseModel):
    brands: int = 0
    brand_products: int = 0
    brand_knowledge_json: int = 0
    brand_attachment_assets: int = 0
    brand_knowledge_sessions: int = 0
    brand_knowledge_session_rounds: int = 0
    brand_knowledge_facts: int = 0
    documents: int = 0
    document_registry: int = 0
    document_categories: int = 0
    document_fact_relations: int = 0
    brand_full_knowledge_files: int = 0
    brand_knowledge_ingestion_jobs: int = 0
    background_jobs: int = 0
    upload_tasks: int = 0
    upload_task_files: int = 0
    upload_task_callbacks: int = 0
    ai_knowledge_oss_objects: int = 0
    confirmed_knowledge_oss_objects: int = 0
    oss_objects: int = 0


class BrandRenameCounts(BaseModel):
    brands: int = 0
    brand_products: int = 0
    brand_full_knowledge_files: int = 0
    brand_knowledge_facts: int = 0
    brand_attachment_assets: int = 0
    brand_knowledge_ingestion_jobs: int = 0
    brand_knowledge_sessions: int = 0
    document_registry: int = 0
    document_categories: int = 0
    background_jobs: int = 0
    upload_tasks: int = 0


class BrandRenameResponse(BaseModel):
    brand_code: str
    brand_id: int | None = None
    old_brand_name: str
    brand_name: str
    executed: bool
    message: str
    counts: BrandRenameCounts
    updated_tables: list[str] = Field(default_factory=list)


class BrandDeleteResponse(BaseModel):
    brand_code: str | None = None
    brand_id: int | None = None
    brand_name: str
    dry_run: bool
    executed: bool
    message: str
    counts: BrandDeleteCounts
