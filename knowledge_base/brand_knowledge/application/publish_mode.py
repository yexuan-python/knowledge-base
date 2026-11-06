from __future__ import annotations

from typing import Any

PUBLISH_MODE_DRAFT_ONLY = "draft_only"
PUBLISH_MODE_FULL_INGEST = "full_ingest"
PUBLISH_MODES = frozenset({PUBLISH_MODE_DRAFT_ONLY, PUBLISH_MODE_FULL_INGEST})

ATTACHMENT_CONFLICT_SESSION_KIND = "attachment_conflict"
ATTACHMENT_CONFLICT_DRAFT_SESSION_KIND = "attachment_conflict:draft_only"


def normalize_publish_mode(
    publish_mode: str | None,
    *,
    default: str = PUBLISH_MODE_DRAFT_ONLY,
) -> str:
    normalized_default = str(default or PUBLISH_MODE_DRAFT_ONLY).strip() or PUBLISH_MODE_DRAFT_ONLY
    normalized_mode = str(publish_mode or normalized_default).strip() or normalized_default
    if normalized_mode not in PUBLISH_MODES:
        raise ValueError("不支持的知识库发布模式")
    return normalized_mode


def is_draft_only_publish_mode(
    publish_mode: str | None,
    *,
    default: str = PUBLISH_MODE_DRAFT_ONLY,
) -> bool:
    return normalize_publish_mode(publish_mode, default=default) == PUBLISH_MODE_DRAFT_ONLY


def should_ingest_full_knowledge(
    publish_mode: str | None,
    *,
    default: str = PUBLISH_MODE_DRAFT_ONLY,
) -> bool:
    return normalize_publish_mode(publish_mode, default=default) == PUBLISH_MODE_FULL_INGEST


def attachment_conflict_session_kind_for_publish_mode(
    publish_mode: str | None,
    *,
    default: str = PUBLISH_MODE_DRAFT_ONLY,
) -> str:
    if is_draft_only_publish_mode(publish_mode, default=default):
        return ATTACHMENT_CONFLICT_DRAFT_SESSION_KIND
    return ATTACHMENT_CONFLICT_SESSION_KIND


def is_attachment_conflict_session_kind(session_kind: Any) -> bool:
    normalized_kind = str(session_kind or "").strip()
    return (
        normalized_kind == ATTACHMENT_CONFLICT_SESSION_KIND
        or normalized_kind.startswith(f"{ATTACHMENT_CONFLICT_SESSION_KIND}:")
    )


def publish_mode_from_attachment_conflict_session_kind(session_kind: Any) -> str:
    normalized_kind = str(session_kind or "").strip()
    if normalized_kind == ATTACHMENT_CONFLICT_DRAFT_SESSION_KIND:
        return PUBLISH_MODE_DRAFT_ONLY
    return PUBLISH_MODE_FULL_INGEST

