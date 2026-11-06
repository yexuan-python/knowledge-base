from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class BrandKnowledgeSessionCreateRequest(BaseModel):
    brand_code: str | None = Field(default=None, description="品牌编码；知识库迭代纯文字模式必填其一")
    brand_name: str | None = Field(default=None, description="品牌名称；知识库迭代纯文字模式必填其一")
    session_type: Literal["initial_generation", "knowledge_iteration"] = Field(description="知识会话类型")
    publish_mode: Literal["draft_only", "full_ingest"] = Field(
        default="draft_only",
        description="生成结果处理模式；新知识库会话 API 默认 draft_only=仅生成草稿并上传OSS，full_ingest=完整正式入库",
    )
    iteration_mode: Literal["attachments_only", "attachments_with_instruction", "instruction_only"] | None = Field(
        default=None,
        description="知识库迭代模式：A=attachments_only，B=attachments_with_instruction，C=instruction_only",
    )
    task_id: str | None = Field(default=None, min_length=1, description="附件来源上传任务ID；第一次生成和迭代 A/B 必填")
    initial_message: str | None = Field(default=None, description="可选说明；迭代时可作为更新要求")
    update_instruction: str | None = Field(default=None, description="知识库迭代的文字要求")


class BrandKnowledgeConflictSessionCreateRequest(BaseModel):
    task_id: str = Field(min_length=1, description="普通附件上传任务ID")
    initial_message: str | None = Field(default=None, description="可选说明，默认执行冲突扫描")


class BrandLatestConflictSessionRequest(BaseModel):
    brand_code: str = Field(min_length=1, description="品牌编码")
    brand_name: str | None = Field(default=None, description="可选品牌名称；仅用于无会话结果时的展示兜底，查询以 brand_code 为准")


class BrandKnowledgeResolutionItem(BaseModel):
    conflict_id: str = Field(min_length=1)
    decision: str = Field(min_length=1, description="choose_option / keep_both / manual")
    selected_option_id: str | None = None
    final_content: str | None = None


class BrandAttachmentConflictResolutionSubmitRequest(BaseModel):
    session_id: str = Field(min_length=1, description="附件冲突会话ID")
    round_no: int = Field(ge=1)
    resolutions: list[BrandKnowledgeResolutionItem] = Field(default_factory=list)
    force_reingest: bool = Field(default=False, description="如最终正式知识库内容相同，是否强制重建")
    publish_mode: Literal["draft_only", "full_ingest"] = Field(
        default="draft_only",
        description="生成结果处理模式；冲突决议提交 API 默认 draft_only=仅生成草稿并上传OSS，full_ingest=完整正式入库",
    )
