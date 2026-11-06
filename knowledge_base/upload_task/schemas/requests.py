from __future__ import annotations

from pydantic import BaseModel, Field


class UploadTaskStatusRequest(BaseModel):
    task_id: str = Field(..., description="上传任务 ID")
