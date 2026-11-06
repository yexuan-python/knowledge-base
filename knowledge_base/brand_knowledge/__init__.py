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
    module = import_module("knowledge_base.brand_knowledge.application")
    return getattr(module, name)
