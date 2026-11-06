from __future__ import annotations

from importlib import import_module
from typing import Any


__all__ = [
    "AttachmentDraftDependencies",
    "AttachmentDraftService",
    "BrandKnowledgeApplicationDependencies",
    "BrandKnowledgeApplicationService",
]


def __getattr__(name: str) -> Any:
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name = "knowledge_base.brand_knowledge.application.attachment_flow"
    if name in {"BrandKnowledgeApplicationDependencies", "BrandKnowledgeApplicationService"}:
        module_name = "knowledge_base.brand_knowledge.application.service"
    module = import_module(module_name)
    return getattr(module, name)
