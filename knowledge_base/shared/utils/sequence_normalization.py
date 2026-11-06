from __future__ import annotations

import ast
import json
from typing import Any

_EMPTY_SEQUENCE_MARKERS = frozenset({
    "[]",
    '"[]"',
    "'[]'",
    '["[]"]',
    "['[]']",
})


def parse_jsonish_literal(value: str) -> Any:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    try:
        return json.loads(normalized)
    except Exception:
        pass
    try:
        return ast.literal_eval(normalized)
    except Exception:
        return None


def is_effective_empty_sequence(value: Any) -> bool:
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return False
        if normalized in _EMPTY_SEQUENCE_MARKERS:
            return True
        parsed = parse_jsonish_literal(normalized)
        if parsed is None or parsed == normalized:
            return False
        return is_effective_empty_sequence(parsed)
    if isinstance(value, (list, tuple, set)):
        if not value:
            return True
        return all(is_effective_empty_sequence(item) for item in value)
    return False


def normalize_text_sequence(
    value: Any,
    *,
    split_separators: tuple[str, ...] | None = None,
) -> list[str]:
    if value is None or is_effective_empty_sequence(value):
        return []
    if isinstance(value, (list, tuple, set)):
        normalized_items: list[str] = []
        for item in value:
            normalized_items.extend(
                normalize_text_sequence(item, split_separators=split_separators)
            )
        return normalized_items
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return []
        parsed = parse_jsonish_literal(normalized)
        if parsed is not None and parsed != normalized:
            if isinstance(parsed, dict):
                return [normalized]
            return normalize_text_sequence(parsed, split_separators=split_separators)
        if split_separators:
            for separator in split_separators:
                if separator not in normalized:
                    continue
                normalized_items: list[str] = []
                for part in normalized.split(separator):
                    normalized_items.extend(
                        normalize_text_sequence(part, split_separators=split_separators)
                    )
                return normalized_items
        return [normalized]
    normalized = str(value).strip()
    return [normalized] if normalized else []


def normalize_line_delimited_text_sequence(value: Any) -> list[str]:
    return normalize_text_sequence(value, split_separators=("\n",))


def normalize_hotline_sequence(value: Any) -> list[str]:
    return normalize_text_sequence(
        value,
        split_separators=("\n", ",", "，", "、", " "),
    )
