from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI

from knowledge_base.composition import build_infrastructure
from knowledge_base.infrastructure import Settings, get_settings, setup_logging
from knowledge_base.service import KnowledgeBaseService


def configure_logging(settings: Settings | None = None) -> Settings:
    resolved_settings = settings or get_settings()
    log_file = Path(resolved_settings.log_dir) / "app.log"
    setup_logging(level=resolved_settings.log_level, log_file=str(log_file))
    return resolved_settings


def build_service(settings: Settings | None = None) -> KnowledgeBaseService:
    resolved_settings = settings or get_settings()
    infrastructure = build_infrastructure(resolved_settings)
    return KnowledgeBaseService(resolved_settings, infrastructure)


@lru_cache(maxsize=1)
def get_service() -> KnowledgeBaseService:
    return build_service()


def create_api_app() -> FastAPI:
    settings = configure_logging()
    service = get_service()
    from knowledge_base.api_app.app import create_app

    return create_app(settings=settings, service=service)


__all__ = [
    "build_service",
    "configure_logging",
    "create_api_app",
    "get_service",
]
