from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from knowledge_base.api_app.deps import get_service
from knowledge_base.background_jobs.schemas import BackgroundJobListResponse, BackgroundJobResponse
from knowledge_base.service import KnowledgeBaseService


router = APIRouter(prefix="/api/v1")

_BACKGROUND_JOB_STATUS_FILTERS: dict[str, tuple[list[str] | None, list[str] | None]] = {
    "all": (None, None),
    "waiting": (["waiting", "retrying"], None),
    "processing": (["processing"], None),
    "success": (["success"], None),
    "failed": (["failed"], None),
    "other": (None, ["waiting", "retrying", "processing", "success", "failed"]),
}


@router.get("/background-jobs", response_model=BackgroundJobListResponse, status_code=200)
def list_background_jobs(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    status: str = Query(default="all"),
    keyword: str | None = Query(default=None, max_length=256),
    service: KnowledgeBaseService = Depends(get_service),
) -> BackgroundJobListResponse:
    normalized_status = str(status or "all").strip()
    if normalized_status not in _BACKGROUND_JOB_STATUS_FILTERS:
        raise HTTPException(status_code=400, detail="不支持的 background job 状态筛选")
    included_statuses, excluded_statuses = _BACKGROUND_JOB_STATUS_FILTERS[normalized_status]
    result = service.query_background_jobs(
        limit=limit,
        offset=offset,
        statuses=included_statuses,
        excluded_statuses=excluded_statuses,
        keyword=keyword,
    )
    return BackgroundJobListResponse(
        jobs=[BackgroundJobResponse(**job) for job in result.get("jobs", [])],
        limit=int(result.get("limit") or limit),
        offset=int(result.get("offset") or offset),
        total=int(result.get("total") or 0),
        status_counts=dict(result.get("status_counts") or {}),
    )


@router.get("/background-jobs/{job_id}", response_model=BackgroundJobResponse, status_code=200)
def get_background_job(
    job_id: str,
    service: KnowledgeBaseService = Depends(get_service),
) -> BackgroundJobResponse:
    result = service.get_background_job(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="background job 不存在")
    return BackgroundJobResponse(**result)
