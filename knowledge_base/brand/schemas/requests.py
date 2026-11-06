from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


ScalarText = str | list[str]


class BrandAttachment(BaseModel):
    name: str = Field(min_length=1)
    url: str = Field(min_length=1)


class BrandCompetitor(BaseModel):
    name: str = Field(min_length=1)
    website: str | None = None


class BrandProduct(BaseModel):
    product_code: str | None = None
    name: str | None = None
    product_alias: str | None = None
    product_images: list[str] = Field(default_factory=list)
    product_description: str | None = None
    product_link: str | None = None
    attachments: list[BrandAttachment] = Field(default_factory=list)
    competitors: list[BrandCompetitor] = Field(default_factory=list)


class BrandUploadRequest(BaseModel):
    brand_code: str | None = None
    brand_name: str = Field(min_length=1)
    force_reingest: bool = False
    brand_alias: str | None = None
    industry_id: int | None = None
    industry_code: str | None = None
    industry_name: str | None = None
    brand_logo: str | None = None
    website: list[str] = Field(default_factory=list)
    enterprise_subject: str | None = None
    business_license_url: str | None = None
    intro: str | None = None
    email: str | None = None
    products: list[BrandProduct] = Field(default_factory=list)
    competitors: list[BrandCompetitor] = Field(default_factory=list)
    attachments: list[BrandAttachment] = Field(default_factory=list)


class BrandDeleteRequest(BaseModel):
    brand_name: str = Field(min_length=1, description="品牌名称")
    dry_run: bool = Field(
        default=False,
        description="兼容当前接口约定：false 表示仅预览删除范围，true 表示执行真实删除",
    )


class BrandRenameRequest(BaseModel):
    brand_code: str = Field(min_length=1, description="品牌业务编码")
    new_brand_name: str = Field(min_length=1, description="新的品牌名称")


class KnowledgeProduct(BaseModel):
    product_code: str | None = None
    name: str | None = None
    product_alias: str | None = None
    product_description: str | None = None
    product_website: str | None = None
    product_images: list[str] = Field(default_factory=list)
    price_info: str | None = None
    coverage_regions: list[str] = Field(default_factory=list)
    product_advantages: str | None = None
    target_scenarios: str | None = None
    service_standard: str | None = None
    service_process: str | None = None
    cases_and_reputation: str | None = None
    certification_info: str | None = None
    core_technology: str | None = None
    other_info: str | None = None


class KnowledgeBasicInfo(BaseModel):
    brand_code: str | None = None
    brand_name: str = Field(min_length=1)
    brand_alias: str | None = None
    brand_logo: str | None = None
    website: list[str] = Field(default_factory=list)
    customer_service_hotline: ScalarText | None = None
    official_wechat_account: str | None = None
    intro: str | None = None
    email: str | None = None
    brand_enterprise_entity: str | None = None
    business_license_image_path: str | None = None
    industry_id: str | None = None
    english_name: str | None = None
    positioning: ScalarText | None = None
    advantages: ScalarText | None = None
    mission: ScalarText | None = None
    vision: ScalarText | None = None
    target_regions: list[str] = Field(default_factory=list)
    other_info: str | None = None


class KnowledgeSensitiveTopics(BaseModel):
    sensitive_contents: list[str] = Field(default_factory=list)
    controversial_events: list[str] = Field(default_factory=list)
    forbidden_words: list[str] = Field(default_factory=list)
    negative_clarifications: list[str] = Field(default_factory=list)
    other_info: list[str] = Field(default_factory=list)


class KnowledgeUpdateRequest(BaseModel):
    basic_info: KnowledgeBasicInfo
    products: list[KnowledgeProduct] = Field(
        default_factory=list,
        description="接口按完整产品列表同步，缺失的旧产品会删除；未传或空数组均清空该品牌产品",
    )
    company_profile: dict[str, Any] | None = None
    management_team: list[dict[str, Any]] = Field(default_factory=list)
    competitors: list[dict[str, Any]] = Field(default_factory=list)
    authority_honors: list[dict[str, Any]] = Field(default_factory=list)
    customers_cases: list[dict[str, Any]] = Field(default_factory=list)
    official_media_matrix: list[dict[str, Any]] = Field(default_factory=list)
    official_malls: list[dict[str, Any]] = Field(default_factory=list)
    sensitive_topics: KnowledgeSensitiveTopics = Field(default_factory=KnowledgeSensitiveTopics)
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    other_info: list[dict[str, Any]] = Field(default_factory=list)
    source_type: str | None = None
    source_task_id: str | None = None
    source_job_id: str | None = None
    source_name: str | None = None
    source_oss_key: str | None = None
    skip_attachment_document_sync: bool = False
    skip_full_ai_knowledge_sync: bool = False


class BrandPathsLoadRequest(BaseModel):
    knowledge_revision: str | None = None
    paths: list[str] = Field(default_factory=list)


class BrandLatestAiKnowledgeRequest(BaseModel):
    brand_code: str = Field(min_length=1)


class BrandOfficialMallsRequest(BaseModel):
    brand_code: str = Field(min_length=1)
