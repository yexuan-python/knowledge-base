from __future__ import annotations

import importlib
import re
from datetime import datetime

KNOWLEDGE_REVISION_CHANGE_MANUAL = 1
KNOWLEDGE_REVISION_CHANGE_ATTACHMENT = 2

_REVISION_PREFIX = "LXKG"
_REVISION_PATTERN = re.compile(
    r"^LXKG-(?P<brand_abbr>[A-Z0-9]+)-V(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)-(?P<timestamp>\d{14})$"
)
_ASCII_SANITIZE_PATTERN = re.compile(r"[^0-9A-Za-z]+")
_CJK_PATTERN = re.compile(r"[\u3400-\u4DBF\u4E00-\u9FFF]")


def _load_pypinyin() -> tuple[object, object]:
    try:
        module = importlib.import_module("pypinyin")
    except ModuleNotFoundError as exc:
        raise RuntimeError("pypinyin is required to build knowledge_revision from Chinese brand names") from exc
    return module.Style, module.lazy_pinyin


def _normalize_ascii_token(value: str) -> str:
    return _ASCII_SANITIZE_PATTERN.sub("", value).upper()


def build_brand_abbr(*, brand_name: str | None = None, brand_code: str | None = None) -> str:
    normalized_brand_name = (brand_name or "").strip()
    if normalized_brand_name:
        style_cls, lazy_pinyin = _load_pypinyin()
        tokens = lazy_pinyin(
            normalized_brand_name,
            style=style_cls.FIRST_LETTER,
            errors=lambda value: list(value),
        )
        normalized = _normalize_ascii_token("".join(tokens))
        if normalized:
            return normalized
        if _CJK_PATTERN.search(normalized_brand_name):
            raise ValueError("brand_name 无法生成有效的品牌缩写")

    normalized_brand_code = _normalize_ascii_token((brand_code or "").strip())
    if normalized_brand_code:
        return normalized_brand_code
    return "BRAND"


def _parse_revision_parts(revision: str | None) -> tuple[int, int, int] | None:
    normalized = (revision or "").strip()
    if not normalized:
        return None
    match = _REVISION_PATTERN.match(normalized)
    if match is None:
        return None
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
    )


def _apply_change(
    *,
    current_revision: str | None,
    change_type: int | None,
) -> tuple[int, int, int]:
    parsed = _parse_revision_parts(current_revision)
    if parsed is None:
        return (1, 0, 0)

    major, minor, patch = parsed
    if change_type == KNOWLEDGE_REVISION_CHANGE_ATTACHMENT:
        minor += 1
        patch = 0
    elif change_type == KNOWLEDGE_REVISION_CHANGE_MANUAL:
        patch += 1

    if patch >= 10:
        minor += 1
        patch = 0
    if minor >= 10:
        major += 1
        minor = 0
        patch = 0
    return (major, minor, patch)


def build_knowledge_revision(
    *,
    brand_code: str | None = None,
    brand_name: str | None = None,
    current_revision: str | None = None,
    change_type: int | None = None,
    now: datetime | None = None,
) -> str:
    brand_abbr = build_brand_abbr(brand_name=brand_name, brand_code=brand_code)
    major, minor, patch = _apply_change(
        current_revision=current_revision,
        change_type=change_type,
    )
    timestamp = (now or datetime.now()).strftime("%Y%m%d%H%M%S")
    return f"{_REVISION_PREFIX}-{brand_abbr}-V{major}.{minor}.{patch}-{timestamp}"
