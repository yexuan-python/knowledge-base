from __future__ import annotations

from pathlib import Path
from typing import Any

from knowledge_base.infrastructure.embedding import EmbeddingService


DOCMIND_IMAGE_MAX_BYTES = 20 * 1024 * 1024
DOCMIND_IMAGE_TARGET_BYTES = int(19.5 * 1024 * 1024)
IMAGE_TAGGING_MAX_BYTES = 5 * 1024 * 1024
IMAGE_TAGGING_TARGET_BYTES = int(4.5 * 1024 * 1024)


def prepare_image_processing_path(
    original_path: Path,
    *,
    max_bytes: int,
    target_bytes: int,
    purpose: str,
) -> tuple[Path, bool]:
    prepared_path, cleanup_prepared_path = EmbeddingService.prepare_image_path_for_limit(
        str(original_path),
        max_bytes=max_bytes,
        target_bytes=target_bytes,
        purpose=purpose,
    )
    return Path(prepared_path), bool(cleanup_prepared_path)


def should_route_image_to_document_pipeline(parser: Any, suffix: str) -> bool:
    return parser.prefers_document_pipeline(suffix)


def prepare_docmind_image_parsing_path(
    parser: Any,
    original_path: Path,
    suffix: str,
) -> tuple[Path, bool]:
    if not should_route_image_to_document_pipeline(parser, suffix):
        return original_path, False

    return prepare_image_processing_path(
        original_path,
        max_bytes=DOCMIND_IMAGE_MAX_BYTES,
        target_bytes=DOCMIND_IMAGE_TARGET_BYTES,
        purpose="DocMind parsing",
    )


def prepare_image_tagging_path(original_path: Path) -> tuple[Path, bool]:
    return prepare_image_processing_path(
        original_path,
        max_bytes=IMAGE_TAGGING_MAX_BYTES,
        target_bytes=IMAGE_TAGGING_TARGET_BYTES,
        purpose="image tagging",
    )
