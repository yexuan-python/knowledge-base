from __future__ import annotations

import logging
import json
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from knowledge_base.api_app.deps import get_service
from knowledge_base.api_app.parsing import parse_metadata
from knowledge_base.document.schemas import (
    AttachmentDeleteApiResponse,
    AttachmentDeleteDataItem,
    AttachmentDeleteRequest,
    AttachmentDeleteResponse,
    BrandFactsResponse,
    BrandFactsIngestResponse,
    BrandFactsSearchRequest,
    ImageSearchRequest,
    ImageSearchResponse,
    ImageSearchResultItem,
    SearchResponse,
    SearchResultItem,
    SearchResultMetadata,
    SearchRequest,
)
from knowledge_base.upload_task.schemas import (
    UploadTaskCreateResponse,
    UploadTaskStatusRequest,
    UploadTaskStatusResponse,
)
from knowledge_base.service import KnowledgeBaseService


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")


def _error_response(*, code: str, message: str) -> dict[str, object]:
    return {
        "code": code,
        "message": message,
        "data": None,
    }


def _resolve_brand_name(*, brand_name: str | None, category: str | None) -> str | None:
    return str(brand_name or category or "").strip() or None


def _facts_without_metadata(facts: list[dict | str]) -> list[dict | str]:
    sanitized: list[dict | str] = []
    for item in facts:
        if isinstance(item, dict):
            sanitized.append({key: value for key, value in item.items() if key != "metadata"})
        else:
            sanitized.append(item)
    return sanitized


async def _build_brand_facts_response(
    *,
    request: BrandFactsSearchRequest,
    service: KnowledgeBaseService,
) -> BrandFactsResponse:
    resolved_brand_name = _resolve_brand_name(brand_name=request.brand_name, category=request.category)
    resolved_brand_code = str(request.brand_code or "").strip() or None
    resolved_product_code = str(request.product_code or "").strip() or None
    if not (resolved_brand_name or resolved_brand_code or resolved_product_code):
        raise HTTPException(status_code=400, detail="brand_code、brand_name、category、product_code 至少传一个")
    try:
        result = await service.search_facts(
            brand_code=resolved_brand_code,
            brand_name=resolved_brand_name,
            category=request.category,
            product_code=resolved_product_code,
            query=request.query,
            top_k=request.top_k,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    response_brand_code = resolved_brand_code
    response_brand_name = resolved_brand_name
    for item in result:
        metadata = item.get("metadata") if isinstance(item, dict) else None
        if not isinstance(metadata, dict):
            continue
        response_brand_code = response_brand_code or str(metadata.get("brand_code") or "").strip() or None
        response_brand_name = response_brand_name or str(metadata.get("brand_name") or "").strip() or None
        if response_brand_code and response_brand_name:
            break
    return BrandFactsResponse(
        brand_code=response_brand_code,
        brand_name=response_brand_name,
        category=response_brand_name,
        product_code=resolved_product_code,
        query=request.query,
        facts=_facts_without_metadata(result),
    )


@router.post("/documents/upload", response_model=UploadTaskCreateResponse, status_code=202)
async def ingest_upload(
    files: Annotated[list[UploadFile], File(...)],
    metadata: Annotated[str | None, Form()] = None,
    chunk_size: Annotated[int | None, Form()] = None,
    chunk_overlap: Annotated[int | None, Form()] = None,
    service: KnowledgeBaseService = Depends(get_service),
) -> UploadTaskCreateResponse:
    parsed_metadata = parse_metadata(metadata)
    try:
        task = await service.enqueue_upload_task(
            files=files,
            metadata=parsed_metadata,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
    except ValueError as exc:
        logger.warning(
            "Upload ingest rejected filenames=%s reason=%s",
            [file.filename for file in files],
            exc,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return task


@router.post("/brands/facts/upload", response_model=BrandFactsIngestResponse, status_code=200)
async def ingest_brand_facts_only(
    files: Annotated[list[UploadFile], File(...)],
    metadata: Annotated[str | None, Form()] = None,
    service: KnowledgeBaseService = Depends(get_service),
) -> BrandFactsIngestResponse:
    parsed_metadata = parse_metadata(metadata)
    logger.info(
        "Brand facts upload request received file_count=%s filenames=%s brand_code=%s brand_name=%s",
        len(files),
        [file.filename for file in files],
        parsed_metadata.get("brand_code"),
        parsed_metadata.get("brand_name") or parsed_metadata.get("category"),
    )
    try:
        result = await service.ingest_brand_facts_only(
            files=files,
            metadata=parsed_metadata,
        )
    except ValueError as exc:
        logger.warning(
            "Brand facts upload rejected filenames=%s reason=%s",
            [file.filename for file in files],
            exc,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logger.info(
        "Brand facts upload request completed file_count=%s brand_code=%s brand_name=%s document_id=%s fact_count=%s deleted_fact_count=%s",
        len(files),
        result.get("brand_code"),
        result.get("brand_name"),
        result.get("document_id"),
        result.get("fact_count"),
        result.get("deleted_fact_count"),
    )
    return BrandFactsIngestResponse(**result)


@router.post("/documents/upload-tasks", response_model=UploadTaskStatusResponse)
def get_upload_task_status(
    request: UploadTaskStatusRequest,
    service: KnowledgeBaseService = Depends(get_service),
) -> UploadTaskStatusResponse:
    logger.info("/documents/upload-tasks request_json=%s", json.dumps(request.model_dump(), ensure_ascii=False))
    task = service.get_upload_task_status(request.task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Upload task not found")
    return UploadTaskStatusResponse(**task)


@router.post("/search", response_model=SearchResponse, response_model_exclude_none=True)
async def search(
    payload: SearchRequest,
    service: KnowledgeBaseService = Depends(get_service),
) -> SearchResponse:
    try:
        result = await service.search(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    resolved_brand_name = _resolve_brand_name(brand_name=payload.brand_name, category=payload.category)
    logger.info(
        "Search completed result_count=%s brand_name=%s",
        len(result),
        resolved_brand_name,
    )
    return SearchResponse(
        code=0,
        message="ok",
        data=[
            SearchResultItem(
                chunk_id=item.get("chunk_id"),
                content=str(item.get("content") or ""),
                score=float(item["score"]) if item.get("score") is not None else None,
                brand_name=_resolve_brand_name(
                    brand_name=item.get("brand_name"),
                    category=item.get("category"),
                ),
                category=_resolve_brand_name(
                    brand_name=item.get("brand_name"),
                    category=item.get("category"),
                ),
                metadata=SearchResultMetadata(**item["metadata"]) if isinstance(item.get("metadata"), dict) else None,
            )
            for item in result
            if str(item.get("content") or "").strip()
        ],
    )


@router.post("/images/search", response_model=ImageSearchResponse, response_model_exclude_none=True)
async def search_images(
    payload: ImageSearchRequest,
    service: KnowledgeBaseService = Depends(get_service),
) -> ImageSearchResponse:
    try:
        result = await service.search_images(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    resolved_brand_name = _resolve_brand_name(brand_name=payload.brand_name, category=payload.category)
    logger.info(
        "Image search completed result_count=%s brand_name=%s",
        len(result),
        resolved_brand_name,
    )
    return ImageSearchResponse(
        code=0,
        message="ok",
        data=[
            ImageSearchResultItem(**item)
            for item in result
            if int(item.get("asset_id") or 0) > 0
        ],
    )


@router.post("/brands/attachments/delete", response_model=AttachmentDeleteApiResponse, status_code=200)
async def delete_attachment(
    request: AttachmentDeleteRequest,
    service: KnowledgeBaseService = Depends(get_service),
) -> AttachmentDeleteApiResponse | JSONResponse:
    try:
        result = await service.delete_documents_by_attachments(
            brand_code=request.brand_code,
            attachments=[item.model_dump() for item in request.attachments],
        )
    except ValueError as exc:
        detail = str(exc)
        if "品牌不存在" in detail:
            return JSONResponse(
                status_code=404,
                content=_error_response(code="404", message="品牌不存在"),
            )
        return JSONResponse(
            status_code=400,
            content=_error_response(code="400", message="参数错误"),
        )

    response_payload = AttachmentDeleteResponse.model_validate(result)
    items = [
        AttachmentDeleteDataItem(
            brand_code=response_payload.brand_code,
            brand_name=response_payload.brand_name,
            name=item.name,
            url=item.url,
            status=_normalize_attachment_delete_status(item.status),
            document_id=item.document_id,
            matched_document_ids=item.matched_document_ids,
            detail=(
                item.detail
                if _normalize_attachment_delete_status(item.status) == item.status
                else _build_attachment_delete_detail(_normalize_attachment_delete_status(item.status))
            ) or _build_attachment_delete_detail(_normalize_attachment_delete_status(item.status)),
        )
        for item in response_payload.results
    ]
    data: AttachmentDeleteDataItem | list[AttachmentDeleteDataItem] | None
    if not items:
        data = None
    elif len(items) == 1:
        data = items[0]
    else:
        data = items
    return AttachmentDeleteApiResponse(
        code="200",
        message="成功",
        data=data,
    )


def _build_attachment_delete_detail(status: str) -> str:
    if status == "deleted":
        return "已从品牌知识附件列表移除"
    if status == "not_found":
        return "未找到该附件"
    if status == "ambiguous":
        return "匹配到多条附件记录，请人工确认"
    if status == "failed":
        return "删除失败"
    return ""


def _normalize_attachment_delete_status(status: str) -> str:
    if status == "not_found":
        # External delete API is idempotent for the frontend: a missing mount
        # is reported the same way as an already-removed attachment.
        return "deleted"
    return status


@router.post("/brands/facts", response_model=BrandFactsResponse, response_model_exclude_none=True)
@router.post("/categories/facts", response_model=BrandFactsResponse, response_model_exclude_none=True)
async def get_brand_facts_merged(
    request: BrandFactsSearchRequest,
    service: KnowledgeBaseService = Depends(get_service),
) -> BrandFactsResponse:
    return await _build_brand_facts_response(
        request=request,
        service=service,
    )
