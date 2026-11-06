from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from knowledge_base.api_app.deps import get_service
from knowledge_base.document.schemas import HealthResponse
from knowledge_base.service import KnowledgeBaseService


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")


@router.get("/health", response_model=HealthResponse)
def health(service: KnowledgeBaseService = Depends(get_service)) -> HealthResponse:
    logger.debug("Health check requested collection_name=%s", service.collection_name)
    return HealthResponse(status="ok", collection_name=service.collection_name)
