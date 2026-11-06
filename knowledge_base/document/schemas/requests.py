from __future__ import annotations

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=50)
    document_ids: list[str] | None = None
    source_types: list[str] | None = None
    brand_code: str | None = None
    brand_name: str | None = None
    category: str | None = Field(None, description="兼容旧字段：品牌名称")
    product_code: str | None = None
    subcategory: str | None = None


class ImageSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=10, ge=1, le=50)
    document_ids: list[str] | None = None
    brand_code: str | None = None
    brand_name: str | None = None
    category: str | None = Field(None, description="兼容旧字段：品牌名称")
    product_code: str | None = None
    subcategory: str | None = None


class AttachmentDeleteItem(BaseModel):
    name: str = Field(..., min_length=1, description="附件原始文件名")
    url: str | None = Field(None, description="可选附件 URL；传入后优先按 name + url 精确删除")


class AttachmentDeleteRequest(BaseModel):
    brand_code: str = Field(..., min_length=1, description="品牌编码")
    attachments: list[AttachmentDeleteItem] = Field(..., min_length=1, description="待删除附件列表")


class BrandFactsSearchRequest(BaseModel):
    brand_code: str | None = Field(None, description="品牌编码")
    brand_name: str | None = Field(None, description="品牌名称")
    category: str | None = Field(None, description="兼容旧字段：分类名称")
    product_code: str | None = Field(None, description="产品编码")
    query: str = Field(..., min_length=1, description="搜索查询")
    top_k: int = Field(5, ge=1, le=50, description="返回最相关的事实数量")


class CategorySearchRequest(BrandFactsSearchRequest):
    pass
