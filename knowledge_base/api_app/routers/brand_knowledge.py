from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from knowledge_base.api_app.deps import get_service
from knowledge_base.brand_knowledge.schemas import (
    AttachmentConfirmResultResponse,
    AttachmentConfirmSaveRequest,
    AttachmentConfirmSaveResponse,
    BrandAttachmentConflictResolutionSubmitRequest,
    BrandLatestConflictSessionRequest,
    AttachmentPreviewParseRequest,
    AttachmentPreviewParseResponse,
    AttachmentReviewChangesRequest,
    AttachmentReviewChangesResponse,
    BrandKnowledgeConflictSessionCreateRequest,
    BrandKnowledgeSessionCreateRequest,
    BrandKnowledgeSessionEmptyResponse,
    BrandKnowledgeSessionResponse,
)
from knowledge_base.service import KnowledgeBaseService


router = APIRouter(prefix="/api/v1")


@router.post(
    "/brands/attachments/preview-parse",
    response_model=AttachmentPreviewParseResponse,
    response_model_exclude_none=True,
    status_code=200,
)
async def preview_parse_brand_attachments(
    request: AttachmentPreviewParseRequest,
    service: KnowledgeBaseService = Depends(get_service),
):
    try:
        result = await service.preview_parse_brand_attachments(
            brand_name=request.brand_name,
            brand_code=request.brand_code,
            attachments=[item.model_dump() for item in request.attachments],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result.get("status") == "true":
        return JSONResponse(
            status_code=200,
            content={
                "brand_name": result.get("brand_name"),
                "status": "true",
            },
        )
    return AttachmentPreviewParseResponse(**result)


@router.post("/brands/attachments/confirm", response_model=AttachmentConfirmSaveResponse, status_code=200)
async def confirm_save_brand_attachments(
    request: AttachmentConfirmSaveRequest,
    service: KnowledgeBaseService = Depends(get_service),
) -> AttachmentConfirmSaveResponse:
    try:
        result = await service.confirm_save_brand_attachments(
            request=request,
            draft_id=request.draft_id,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "不存在" in detail or "过期" in detail else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return AttachmentConfirmSaveResponse(**result)


@router.get("/brands/attachments/confirm/result/{job_id}", response_model=AttachmentConfirmResultResponse, status_code=200)
def get_brand_attachment_confirm_result(
    job_id: str,
    service: KnowledgeBaseService = Depends(get_service),
) -> AttachmentConfirmResultResponse:
    try:
        result = service.get_attachment_confirm_result(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="background job 不存在")
    return AttachmentConfirmResultResponse(**result)


@router.post("/brands/attachments/review-changes", response_model=AttachmentReviewChangesResponse, status_code=200)
async def review_brand_attachment_changes(
    request: AttachmentReviewChangesRequest,
    service: KnowledgeBaseService = Depends(get_service),
) -> AttachmentReviewChangesResponse:
    try:
        result = await service.review_brand_attachment_changes(
            request=request,
            draft_id=request.draft_id,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "不存在" in detail or "过期" in detail else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return AttachmentReviewChangesResponse(**result)


@router.post("/brands/knowledge-base/sessions", response_model=BrandKnowledgeSessionResponse, status_code=200)
async def start_brand_knowledge_session(
    request: BrandKnowledgeSessionCreateRequest,
    service: KnowledgeBaseService = Depends(get_service),
) -> BrandKnowledgeSessionResponse:
    try:
        result = await service.start_brand_knowledge_session(
            session_type=request.session_type,
            task_id=request.task_id,
            brand_code=request.brand_code,
            brand_name=request.brand_name,
            publish_mode=request.publish_mode,
            iteration_mode=request.iteration_mode,
            initial_message=request.initial_message,
            update_instruction=request.update_instruction,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "不存在" in detail else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return BrandKnowledgeSessionResponse(**result)


@router.post("/brands/knowledge-base/conflict-sessions", response_model=BrandKnowledgeSessionResponse, status_code=200)
async def start_brand_attachment_conflict_session(
    request: BrandKnowledgeConflictSessionCreateRequest,
    service: KnowledgeBaseService = Depends(get_service),
) -> BrandKnowledgeSessionResponse:
    try:
        result = await service.start_brand_attachment_conflict_session(
            task_id=request.task_id,
            initial_message=request.initial_message,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "不存在" in detail else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return BrandKnowledgeSessionResponse(**result)


@router.post(
    "/brands/knowledge-base/conflict-session/latest",
    response_model=BrandKnowledgeSessionResponse | BrandKnowledgeSessionEmptyResponse,
    status_code=200,
)
async def get_latest_brand_attachment_conflict_session(
    request: BrandLatestConflictSessionRequest,
    service: KnowledgeBaseService = Depends(get_service),
) -> BrandKnowledgeSessionResponse | BrandKnowledgeSessionEmptyResponse:
    try:
        result = service.get_latest_brand_attachment_conflict_session(
            brand_code=request.brand_code,
            brand_name=request.brand_name,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "不存在" in detail else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    if result is None:
        return BrandKnowledgeSessionEmptyResponse(
            brand_code=request.brand_code,
            brand_name=request.brand_name or "",
            status="no_conflicts",
            knowledge_markdown_status="no_conflicts",
        )
    if not str(result.get("session_id") or "").strip():
        return BrandKnowledgeSessionEmptyResponse(**result)
    return BrandKnowledgeSessionResponse(**result)


@router.post("/brands/knowledge-base/conflict-sessions/resolutions", response_model=BrandKnowledgeSessionResponse, status_code=200)
async def submit_brand_attachment_conflict_resolutions_by_body(
    request: BrandAttachmentConflictResolutionSubmitRequest,
    service: KnowledgeBaseService = Depends(get_service),
) -> BrandKnowledgeSessionResponse:
    try:
        result = await service.submit_brand_attachment_conflict_resolutions(
            session_id=request.session_id,
            round_no=request.round_no,
            resolutions=[item.model_dump() for item in request.resolutions],
            force_reingest=bool(request.force_reingest),
            publish_mode=request.publish_mode,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "不存在" in detail else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return BrandKnowledgeSessionResponse(**result)
