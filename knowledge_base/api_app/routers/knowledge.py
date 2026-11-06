from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from knowledge_base.api_app.deps import get_service
from knowledge_base.brand.schemas import KnowledgeUpdateRequest
from knowledge_base.service import KnowledgeBaseService


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")


@router.post("/knowledge/update", response_model=dict, status_code=200)
async def update_knowledge(
    request: KnowledgeUpdateRequest,
    service: KnowledgeBaseService = Depends(get_service),
) -> dict[str, object]:
    # HTTP callers send the complete product list; an omitted list means empty.
    # Mark only products as supplied so internal partial updates stay compatible.
    request = request.model_copy(update={"products": request.products})
    logger.info(
        "knowledge/update request brand_code=%s brand_name=%s products_count=%s attachments_count=%s other_info_count=%s source_type=%s skip_attachment_document_sync=%s skip_full_ai_knowledge_sync=%s",
        request.basic_info.brand_code,
        request.basic_info.brand_name,
        len(request.products or []),
        len(request.attachments or []),
        len(request.other_info or []),
        request.source_type,
        request.skip_attachment_document_sync,
        request.skip_full_ai_knowledge_sync,
    )
    try:
        result = await service.update_knowledge(request)
    except ValueError as exc:
        logger.warning(
            "Knowledge update rejected brand_code=%s brand_name=%s reason=%s",
            request.basic_info.brand_code,
            request.basic_info.brand_name,
            exc,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result
