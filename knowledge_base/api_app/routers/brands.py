from __future__ import annotations

import asyncio
import logging
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from knowledge_base.api_app.deps import get_service
from knowledge_base.brand.schemas import (
    BrandDeleteRequest,
    BrandDeleteResponse,
    BrandLatestAiKnowledgeDataResponse,
    BrandLatestAiKnowledgeRequest,
    BrandOfficialMallsDataResponse,
    BrandOfficialMallsRequest,
    BrandListItem,
    BrandListResponse,
    BrandMetaDataResponse,
    BrandPathsLoadDataResponse,
    BrandPathsLoadRequest,
    BrandRenameRequest,
    BrandRenameResponse,
    BrandUploadRequest,
)
from knowledge_base.upload_task.schemas import (
    UploadTaskCreateResponse,
)
from knowledge_base.service import KnowledgeBaseService


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")


def _error_response(*, code: int, message: str) -> dict:
    return {
        "code": code,
        "message": message,
        "data": None,
    }


@router.get("/brands", response_model=BrandListResponse, status_code=200)
async def list_brands(
    keyword: str | None = Query(default=None),
    service: KnowledgeBaseService = Depends(get_service),
) -> BrandListResponse:
    items = await service.list_brands(keyword=keyword)
    return BrandListResponse(
        keyword=keyword,
        brands=[BrandListItem(**item) for item in items],
    )


@router.get("/brands/{brand_code}/meta", status_code=200)
async def get_brand_meta(
    brand_code: str,
    include_path_index: bool = Query(default=True),
    service: KnowledgeBaseService = Depends(get_service),
) -> dict:
    try:
        result = await service.get_brand_meta(
            brand_code=brand_code,
            include_path_index=include_path_index,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content=_error_response(code=40001, message=str(exc)),
        )
    if result is None:
        return JSONResponse(
            status_code=404,
            content=_error_response(code=40401, message="brand_code 不存在"),
        )

    response_data = BrandMetaDataResponse(**result).model_dump(exclude_none=True)
    if not include_path_index:
        response_data.pop("path_index", None)
    return {
        "code": 0,
        "message": "ok",
        "data": response_data,
    }


@router.post("/brands/{brand_code}/paths-load", status_code=200)
async def load_brand_paths(
    brand_code: str,
    request: BrandPathsLoadRequest,
    service: KnowledgeBaseService = Depends(get_service),
) -> dict:
    try:
        result = await asyncio.to_thread(
            service.load_brand_paths,
            brand_code=brand_code,
            paths=request.paths,
            knowledge_revision=request.knowledge_revision,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content=_error_response(code=40001, message=str(exc)),
        )
    except RuntimeError as exc:
        return JSONResponse(
            status_code=409,
            content=_error_response(code=40901, message=str(exc)),
        )
    if result is None:
        return JSONResponse(
            status_code=404,
            content=_error_response(code=40401, message="brand_code 不存在"),
        )

    return {
        "code": 0,
        "message": "ok",
        "data": BrandPathsLoadDataResponse(**result).model_dump(),
    }


@router.post("/brands/ai-knowledge/latest", status_code=200)
async def get_latest_ai_knowledge(
    request: BrandLatestAiKnowledgeRequest,
    service: KnowledgeBaseService = Depends(get_service),
) -> dict:
    try:
        result = await service.get_latest_ai_knowledge(brand_code=request.brand_code)
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content=_error_response(code=40001, message=str(exc)),
        )
    except RuntimeError as exc:
        return JSONResponse(
            status_code=500,
            content=_error_response(code=50001, message=str(exc)),
        )
    if result is None:
        return JSONResponse(
            status_code=404,
            content=_error_response(code=40401, message="brand_code 不存在"),
        )
    if not result.get("oss_key") or not result.get("oss_url"):
        return JSONResponse(
            status_code=404,
            content=_error_response(code=40402, message="品牌 AI 知识库 Markdown 不存在"),
        )
    return {
        "code": 0,
        "message": "ok",
        "data": BrandLatestAiKnowledgeDataResponse(**result).model_dump(),
    }


@router.post("/brands/official-malls", status_code=200)
async def get_brand_official_malls(
    request: BrandOfficialMallsRequest,
    service: KnowledgeBaseService = Depends(get_service),
) -> dict:
    try:
        result = await service.get_brand_official_malls(brand_code=request.brand_code)
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content=_error_response(code=40001, message=str(exc)),
        )
    if result is None:
        return JSONResponse(
            status_code=404,
            content=_error_response(code=40401, message="brand_code 不存在"),
        )
    return {
        "code": 0,
        "message": "ok",
        "data": BrandOfficialMallsDataResponse(**result).model_dump(),
    }


@router.post("/brands/upload", response_model=UploadTaskCreateResponse, status_code=202)
async def upload_brand(
    request: BrandUploadRequest,
    service: KnowledgeBaseService = Depends(get_service),
) -> UploadTaskCreateResponse:
    logger.info("/brands/upload request_json=%s", json.dumps(request.model_dump(), ensure_ascii=False))
    try:
        task = await service.enqueue_brand_upload_task(request)
    except ValueError as exc:
        logger.warning(
            "Brand upload rejected brand_name=%s attachment_count=%s reason=%s",
            request.brand_name,
            len(request.attachments),
            exc,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return task


@router.post("/brands/delete", response_model=BrandDeleteResponse, status_code=200)
async def delete_brand(
    request: BrandDeleteRequest,
    service: KnowledgeBaseService = Depends(get_service),
) -> BrandDeleteResponse:
    try:
        result = await service.delete_brand(request)
    except ValueError as exc:
        logger.warning(
            "Brand delete rejected brand_name=%s dry_run=%s reason=%s",
            request.brand_name,
            request.dry_run,
            exc,
        )
        detail = str(exc)
        status_code = 404 if "不存在" in detail else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return BrandDeleteResponse(**result)


@router.post("/brands/rename", response_model=BrandRenameResponse, status_code=200)
async def rename_brand(
    request: BrandRenameRequest,
    service: KnowledgeBaseService = Depends(get_service),
) -> BrandRenameResponse:
    try:
        result = await service.rename_brand(request)
    except ValueError as exc:
        logger.warning(
            "Brand rename rejected brand_code=%s new_brand_name=%s reason=%s",
            request.brand_code,
            request.new_brand_name,
            exc,
        )
        detail = str(exc)
        status_code = 409 if "已存在" in detail else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="brand_code 对应的品牌不存在")
    response_payload = dict(result)
    response_payload["executed"] = bool(response_payload.get("updated_tables"))
    response_payload["message"] = (
        "品牌名称更新完成。"
        if response_payload["executed"]
        else "品牌名称未变化，无需更新。"
    )
    return BrandRenameResponse(**response_payload)
