from __future__ import annotations

import logging
import json
from math import ceil
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from knowledge_base.api_app.deps import get_service
from knowledge_base.infrastructure import Settings
from knowledge_base.infrastructure.embedding import EmbeddingRateLimitedError
from knowledge_base.api_app.routers import (
    background_jobs_router,
    brand_knowledge_router,
    brands_router,
    documents_router,
    health_router,
    knowledge_router,
)
from knowledge_base.service import KnowledgeBaseService


logger = logging.getLogger(__name__)
UPLOAD_VALIDATION_ALERT_PATH = "/api/v1/brands/upload"


def _sanitize_validation_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _sanitize_validation_value(item)
            for key, item in value.items()
            if key != "input"
        }
    if isinstance(value, list):
        return [_sanitize_validation_value(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_validation_value(item) for item in value]
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
        return text if text.strip() else None
    return value


def _request_validation_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    return _sanitize_validation_value(exc.errors())


def _request_validation_body(exc: RequestValidationError) -> Any:
    body = getattr(exc, "body", None)
    if isinstance(body, bytes):
        text = body.decode("utf-8", errors="replace")
        if not text.strip():
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    return body


async def _handle_request_validation_error(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    request_body = _request_validation_body(exc)
    errors = _request_validation_errors(exc)
    logger.warning(
        "Request validation failed method=%s path=%s query=%s content_type=%s content_length=%s client=%s errors=%s",
        request.method,
        request.url.path,
        dict(request.query_params),
        request.headers.get("content-type"),
        request.headers.get("content-length"),
        request.client.host if request.client else None,
        errors,
    )
    alert_app = getattr(getattr(request.app.state, "kb_service", None), "_alert_app", None)
    if alert_app is not None and request.method.upper() == "POST" and request.url.path == UPLOAD_VALIDATION_ALERT_PATH:
        try:
            await alert_app.notify_request_validation_failure(
                method=request.method,
                path=request.url.path,
                query_params=dict(request.query_params),
                content_type=request.headers.get("content-type"),
                content_length=request.headers.get("content-length"),
                client_host=request.client.host if request.client else None,
                errors=errors,
                request_body=request_body,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "Failed to send request validation alert method=%s path=%s",
                request.method,
                request.url.path,
            )
    return JSONResponse(
        status_code=422,
        content={"detail": errors},
    )


async def _handle_embedding_rate_limited_error(
    request: Request,
    exc: EmbeddingRateLimitedError,
) -> JSONResponse:
    retry_after_seconds = max(1, int(ceil(getattr(exc, "retry_after_seconds", 0.0) or 0.0)))
    logger.warning(
        "Embedding rate limited method=%s path=%s retry_after_seconds=%s client=%s message=%s",
        request.method,
        request.url.path,
        retry_after_seconds,
        request.client.host if request.client else None,
        exc,
    )
    return JSONResponse(
        status_code=503,
        content={
            "code": "embedding_rate_limited",
            "message": "embedding 服务限流，请稍后重试",
            "data": None,
        },
        headers={
            "Retry-After": str(retry_after_seconds),
        },
    )


def _build_lifespan(
    *,
    settings: Settings,
    service: KnowledgeBaseService,
):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Manage API startup and shutdown hooks."""
        if not settings.dashscope_api_key:
            logger.warning("DASHSCOPE_API_KEY is not set. Embedding and AI functions will fail.")
        await service.start()
        try:
            yield
        finally:
            await service.stop()

    return lifespan


def create_app(
    *,
    settings: Settings,
    service: KnowledgeBaseService | None = None,
) -> FastAPI:
    resolved_service = service or get_service()
    app = FastAPI(
        title="Milvus Knowledge Base",
        version="0.1.0",
        description="Upload common document formats, store vectors in Milvus Lite, and query with semantic search.",
        lifespan=_build_lifespan(settings=settings, service=resolved_service),
    )
    app.state.settings = settings
    app.state.kb_service = resolved_service
    app.add_exception_handler(RequestValidationError, _handle_request_validation_error)
    app.add_exception_handler(EmbeddingRateLimitedError, _handle_embedding_rate_limited_error)
    cors_allow_origins = list(getattr(settings, "cors_allow_origins", ()))
    if cors_allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_allow_origins,
            allow_credentials=bool(getattr(settings, "cors_allow_credentials", True)),
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(health_router)
    app.include_router(documents_router)
    app.include_router(brands_router)
    app.include_router(brand_knowledge_router)
    app.include_router(knowledge_router)
    app.include_router(background_jobs_router)

    return app
