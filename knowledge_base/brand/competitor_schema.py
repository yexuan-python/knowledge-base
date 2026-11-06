from __future__ import annotations

from typing import Any

from knowledge_base.shared.utils import normalize_text_sequence


def _optional_str(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _normalize_text_list(value: Any) -> list[str]:
    return normalize_text_sequence(
        value,
        split_separators=("\n",),
    )


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        normalized = str(value).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def normalize_competitor_item(item: dict[str, Any]) -> dict[str, Any]:
    name = _optional_str(item.get("name"))
    if not name:
        return {}
    normalized = {
        "name": name,
        "aliases": _dedupe_preserve_order(
            _normalize_text_list(item.get("aliases") if item.get("aliases") is not None else item.get("competitors_alias"))
        ),
        "introduction": _optional_str(
            item.get("introduction")
            if item.get("introduction") is not None
            else item.get("competitors_description") or item.get("intro")
        ),
        "official_websites": _dedupe_preserve_order(
            _normalize_text_list(
                item.get("official_websites") if item.get("official_websites") is not None else item.get("website")
            )
        ),
        "logo_urls": _dedupe_preserve_order(
            _normalize_text_list(item.get("logo_urls") if item.get("logo_urls") is not None else item.get("competitors_logo"))
        ),
        "strengths": _dedupe_preserve_order(
            _normalize_text_list(
                item.get("strengths") if item.get("strengths") is not None else item.get("competitive_advantages")
            )
        ),
        "differentiated_positioning": _dedupe_preserve_order(
            _normalize_text_list(item.get("differentiated_positioning"))
        ),
        "comparison_dimensions": _dedupe_preserve_order(
            _normalize_text_list(item.get("comparison_dimensions"))
        ),
        "other_info": _dedupe_preserve_order(_normalize_text_list(item.get("other_info"))),
    }
    source_section = _optional_str(item.get("source_section"))
    if source_section:
        normalized["source_section"] = source_section
    return normalized


def normalize_competitors_for_storage(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict) and isinstance(value.get("competitors"), list):
        items = value.get("competitors")
    else:
        items = value
    if not isinstance(items, list):
        return []
    normalized: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        normalized_item = normalize_competitor_item(item)
        name = str(normalized_item.get("name") or "").strip()
        if not name:
            continue
        key = name.casefold()
        if key in seen_names:
            continue
        seen_names.add(key)
        normalized.append(normalized_item)
    return normalized
