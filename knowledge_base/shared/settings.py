from __future__ import annotations

from typing import Any


DEFAULT_BRAND_FULL_KNOWLEDGE_REFRESH_DELAY_SECONDS = 300


def get_brand_full_knowledge_refresh_delay_seconds(settings: Any) -> int:
    raw_value = getattr(
        settings,
        "brand_full_knowledge_refresh_delay_seconds",
        DEFAULT_BRAND_FULL_KNOWLEDGE_REFRESH_DELAY_SECONDS,
    )
    try:
        delay_seconds = int(raw_value)
    except (TypeError, ValueError):
        return DEFAULT_BRAND_FULL_KNOWLEDGE_REFRESH_DELAY_SECONDS
    return max(0, delay_seconds)
