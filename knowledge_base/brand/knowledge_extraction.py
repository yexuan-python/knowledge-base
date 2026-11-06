from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import logging
import re
import unicodedata
from typing import TYPE_CHECKING, Any

from knowledge_base.brand.competitor_schema import normalize_competitors_for_storage
from knowledge_base.brand.enrichment import enrich_brand_from_tianyancha
from knowledge_base.brand_knowledge.ai import extract_brand_knowledge_from_markdown
from knowledge_base.infrastructure.llm import call_text_llm_json, require_settings
from knowledge_base.shared.utils import (
    KNOWLEDGE_REVISION_CHANGE_ATTACHMENT,
    build_knowledge_revision,
    is_effective_empty_sequence,
    normalize_hotline_sequence,
    normalize_line_delimited_text_sequence,
    normalize_http_url_sequence,
    normalize_text_sequence,
    parse_metadata_json,
)

if TYPE_CHECKING:
    from knowledge_base.service import KnowledgeBaseService


logger = logging.getLogger(__name__)

_KNOWLEDGE_TYPES = (
    "company_profile",
    "management_team",
    "competitors",
    "authority_honors",
    "customers_cases",
    "sensitive_topics",
    "attachments",
    "official_malls",
    "official_media_matrix",
    "other_info",
)
_ATTACHMENT_PRODUCTS_KNOWLEDGE_TYPE = "attachment_products"
_ATTACHMENT_PRODUCTS_OTHER_INFO_TITLE = "附件解析新增产品"
_MARKDOWN_BOLD_HEADING_RE = re.compile(r"^\*\*(.+?)\*\*\s*$")
_EMPTY_OTHER_INFO_MARKERS = {"(空)", "/", "／", "-", "--", "---", "—", "无", "暂无", "n/a", "N/A"}
_OTHER_INFO_MARKDOWN_TABLE_HEADERS = {
    "字段名称",
    "内容",
    "字段",
    "维度",
    "渠道",
    "序号",
    "术语名称",
    "通俗解释",
}
_OTHER_INFO_SEMANTIC_ALIAS_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"品牌推广/公益活动", "品牌推广与公益"}),
    frozenset({"重点合作介绍", "重点合作"}),
    frozenset({"九、服务、价格与政策", "计价模型", "服务政策"}),
)
_OTHER_INFO_TITLE_PREFIX_RE = re.compile(
    r"^(?:第?[一二三四五六七八九十百千万零〇\d]+(?:\.\d+)*[、.．:\s]*)+"
)
_COMPETITOR_COMPARISON_SECTION_TITLE = "4.3 竞品多维对比"
_COMPETITOR_DIFFERENTIATION_SECTION_TITLE = "4.4 优劣势对比"
_COMPETITOR_SUMMARY_SECTION_TITLES = (
    _COMPETITOR_COMPARISON_SECTION_TITLE,
    _COMPETITOR_DIFFERENTIATION_SECTION_TITLE,
)
_COMPETITOR_SECTION_SUMMARY_TIMEOUT_SECONDS = 45
_PRODUCT_DETAIL_REFERENCE_RE = re.compile(
    r"^(?:详见|详情见|见)?\s*3\.2\s*产品\s*(?P<index>\d+)\s*[。.]?$"
)
_PRODUCT_BLOCK_HEADING_RE = re.compile(r"^\s*-\s+\*\*(?P<title>.+?)\*\*\s*$")
_PRODUCT_BLOCK_INLINE_LABEL_RE = re.compile(
    r"^\s*-\s+\*\*(?P<label>.+?)\*\*\s*[：:]\s*(?P<value>.*)$"
)
_PRODUCT_BLOCK_TRAILING_PRICE_RE = re.compile(
    r"\s+\d[\d,.]*(?:\s*[-~]\s*\d[\d,.]*)?\s*元(?:/[mM㎡²0-9]+)?\s*$"
)
_PRODUCT_BLOCK_CAPTURE_LABELS = {
    "产品配置",
    "套餐配置",
    "基础配置",
    "厨柜配置",
    "衣柜配置",
    "木门配置",
    "墙板配置",
    "门板配置",
    "洗涤配置",
}
_PRODUCT_BLOCK_SKIP_LABELS = {
    "板材优势",
    "烤漆优势",
    "套餐优势",
    "适合的设计风格",
    "板材合适家居设计风格",
}

_FILL_EMPTY_LIST_KEY_FIELDS: dict[str, tuple[str, ...]] = {
    "products": ("name", "product_name"),
    "management_team": ("member_name", "name"),
    "authority_honors": ("title", "year"),
    "customers_cases": ("case_name", "customer_name"),
    "attachments": ("name", "source_url", "url"),
    "official_malls": ("store_name", "platform"),
    "official_media_matrix": ("media_platform", "account_name", "account_id"),
    "other_info": ("title", "key", "name"),
}


def _normalize_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_optional_str(value: Any) -> str | None:
    normalized = _normalize_str(value)
    return normalized or None


def _normalize_brand_other_info_scalar(value: Any) -> str | None:
    normalized = _normalize_optional_str(value)
    if normalized is None:
        return None
    if normalized in {"{}", "null", '""', "None"}:
        return None
    if is_effective_empty_sequence(normalized):
        return None
    return normalized


def _normalize_lower_key_part(value: Any) -> str:
    return _normalize_str(value).lower()


def _normalize_aliases(value: Any) -> list[str]:
    return normalize_text_sequence(
        value,
        split_separators=("\n",),
    )


def _normalize_websites(value: Any) -> list[str]:
    return normalize_http_url_sequence(value)


def _normalize_multi_value(value: Any) -> list[str]:
    return normalize_text_sequence(
        value,
        split_separators=("\n",),
    )


def _normalize_customer_service_hotline(value: Any) -> list[str]:
    return normalize_hotline_sequence(value)


def _normalize_brand_text_multi_value(value: Any) -> list[str]:
    return normalize_line_delimited_text_sequence(value)


def _normalize_sequence_value(value: Any) -> list[str]:
    return normalize_text_sequence(value)


def _serialize_websites(value: Any) -> str | None:
    websites = _normalize_websites(value)
    if not websites:
        return None
    return json.dumps(websites, ensure_ascii=False)


def _pick_primary_website(value: Any) -> str | None:
    websites = _normalize_websites(value)
    if websites:
        return websites[0]
    return _normalize_optional_str(value)


def _normalize_optional_int(value: Any) -> int | None:
    normalized = _normalize_optional_str(value)
    if not normalized:
        return None
    try:
        return int(normalized)
    except ValueError:
        return None


def _copy_jsonable(value: Any) -> Any:
    return deepcopy(value)


def _is_effectively_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        normalized = value.strip()
        return not normalized or normalized in {"[]", "{}", "null", '""'}
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def _item_key(item: Any, key_fields: tuple[str, ...]) -> str:
    if not isinstance(item, dict):
        return ""
    parts = [
        _normalize_lower_key_part(item.get(field))
        for field in key_fields
    ]
    return "|".join(parts)


def _fill_missing_value(existing_value: Any, incoming_value: Any) -> Any:
    if _is_effectively_empty(existing_value):
        return _copy_jsonable(incoming_value)
    if isinstance(existing_value, dict) and isinstance(incoming_value, dict):
        return _fill_missing_dict(existing_value, incoming_value)
    return _copy_jsonable(existing_value)


def _fill_missing_dict(existing_value: Any, incoming_value: Any) -> dict[str, Any]:
    existing = dict(existing_value) if isinstance(existing_value, dict) else {}
    incoming = incoming_value if isinstance(incoming_value, dict) else {}
    merged = _copy_jsonable(existing)
    for key, incoming_item in incoming.items():
        existing_item = merged.get(key)
        merged[key] = _fill_missing_value(existing_item, incoming_item)
    return merged


def _merge_existing_list_items_only(
    existing_value: Any,
    incoming_value: Any,
    *,
    key_fields: tuple[str, ...],
) -> list[Any]:
    existing_items = list(existing_value) if isinstance(existing_value, list) else []
    incoming_items = list(incoming_value) if isinstance(incoming_value, list) else []
    if not existing_items:
        return _copy_jsonable(incoming_items)
    if not incoming_items:
        return _copy_jsonable(existing_items)

    incoming_by_key = {
        _item_key(item, key_fields): item
        for item in incoming_items
        if isinstance(item, dict) and _item_key(item, key_fields).strip("|")
    }
    merged_items: list[Any] = []
    for item in existing_items:
        if not isinstance(item, dict):
            merged_items.append(_copy_jsonable(item))
            continue
        key = _item_key(item, key_fields)
        incoming_item = incoming_by_key.get(key)
        if incoming_item is None:
            merged_items.append(_copy_jsonable(item))
            continue
        merged_items.append(_fill_missing_dict(item, incoming_item))
    return merged_items


def _merge_sensitive_topics_fill_empty(existing_value: Any, incoming_value: Any) -> Any:
    existing_items = list(existing_value) if isinstance(existing_value, list) else []
    incoming_items = list(incoming_value) if isinstance(incoming_value, list) else []
    if not existing_items:
        return _copy_jsonable(incoming_items)
    if not incoming_items:
        return _copy_jsonable(existing_items)
    return _merge_existing_list_items_only(
        existing_items,
        incoming_items,
        key_fields=("topic",),
    )


def _normalize_company_profile(raw: Any) -> dict[str, Any]:
    payload = raw if isinstance(raw, dict) else {}
    return {
        "brand_subject_name": _normalize_optional_str(payload.get("brand_subject_name")),
        "business_license_image_path": _normalize_optional_str(payload.get("business_license_image_path")),
        "registered_capital": _normalize_optional_str(payload.get("registered_capital")),
        "stock_info": _normalize_optional_str(payload.get("stock_info")),
        "company_address": _normalize_optional_str(payload.get("company_address")),
        "company_intro": _normalize_optional_str(payload.get("company_intro")),
        "established_time": _normalize_optional_str(payload.get("established_time")),
        "store_distribution": _normalize_optional_str(payload.get("store_distribution")),
        "recent_news": _normalize_optional_str(payload.get("recent_news")),
        "development_concept": _normalize_optional_str(payload.get("development_concept")),
        "corporate_values": _normalize_optional_str(payload.get("corporate_values")),
        "company_mission": _normalize_optional_str(payload.get("company_mission")),
        "development_history": _normalize_optional_str(payload.get("development_history")),
        "other_info": _normalize_optional_str(payload.get("other_info")),
    }


def _normalize_basic_info(raw: Any) -> dict[str, Any]:
    payload = raw if isinstance(raw, dict) else {}
    target_regions = payload.get("target_regions")
    normalized_target_regions: list[str] = []
    if isinstance(target_regions, list):
        normalized_target_regions = [str(item).strip() for item in target_regions if str(item).strip()]
    elif isinstance(target_regions, str):
        normalized_target_regions = [target_regions.strip()] if target_regions.strip() else []

    return {
        "brand_name": _normalize_optional_str(payload.get("brand_name")),
        "brand_alias": _normalize_optional_str(payload.get("brand_alias")),
        "english_name": _normalize_optional_str(payload.get("english_name")),
        "industry_id": _normalize_optional_str(payload.get("industry_id")),
        "brand_logo": _normalize_optional_str(payload.get("brand_logo")),
        "website": _normalize_websites(payload.get("website")),
        "customer_service_hotline": _normalize_customer_service_hotline(payload.get("customer_service_hotline")),
        "official_wechat_account": _normalize_optional_str(payload.get("official_wechat_account")),
        "intro": _normalize_optional_str(payload.get("intro")),
        "email": _normalize_optional_str(payload.get("email")),
        "brand_enterprise_entity": _normalize_optional_str(payload.get("brand_enterprise_entity")),
        "business_license_image_path": _normalize_optional_str(payload.get("business_license_image_path")),
        "positioning": _normalize_brand_text_multi_value(payload.get("positioning")),
        "advantages": _normalize_brand_text_multi_value(payload.get("advantages")),
        "mission": _normalize_brand_text_multi_value(payload.get("mission")),
        "vision": _normalize_brand_text_multi_value(payload.get("vision")),
        "target_regions": normalized_target_regions,
        "other_info": _normalize_optional_str(payload.get("other_info")),
    }


def _normalize_products(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    normalized_products: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        product_name = _normalize_optional_str(item.get("name"))
        product_description = _normalize_optional_str(item.get("product_description"))
        product_images = item.get("product_images")
        normalized_products.append(
            {
                "name": product_name,
                "product_alias": _normalize_optional_str(item.get("product_alias")),
                "product_description": product_description,
                "product_website": _normalize_optional_str(item.get("product_website")),
                "product_images": [
                    str(image).strip() for image in (product_images or [])
                    if isinstance(product_images, list) and str(image).strip()
                ],
                "price_info": _normalize_optional_str(item.get("price_info")),
                "coverage_regions": _normalize_sequence_value(item.get("coverage_regions")),
                "product_advantages": _normalize_optional_str(item.get("product_advantages")),
                "target_scenarios": _normalize_optional_str(item.get("target_scenarios")),
                "service_standard": _normalize_optional_str(item.get("service_standard")),
                "service_process": _normalize_optional_str(item.get("service_process")),
                "cases_and_reputation": _normalize_optional_str(item.get("cases_and_reputation")),
                "certification_info": _normalize_optional_str(item.get("certification_info")),
                "core_technology": _normalize_optional_str(item.get("core_technology")),
                "other_info": _normalize_optional_str(item.get("other_info")),
            }
        )
    return [
        item for item in normalized_products
        if item.get("name") or item.get("product_description")
    ]


def _is_markdown_table_separator(line: str) -> bool:
    stripped = str(line or "").strip()
    return bool(stripped) and re.fullmatch(r"\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?", stripped) is not None


def _split_markdown_table_row(line: str) -> list[str]:
    stripped = str(line or "").strip().strip("|")
    if not stripped:
        return []
    return [cell.strip() for cell in stripped.split("|")]


def _load_markdown_product_detail_reference_map(markdown_text: str) -> dict[int, str | None]:
    lines = str(markdown_text or "").splitlines()
    heading_index = next(
        (
            index
            for index, line in enumerate(lines)
            if "3.2" in str(line) and "详细产品列表" in str(line)
        ),
        None,
    )
    if heading_index is None:
        return {}

    header_index: int | None = None
    headers: list[str] = []
    for index in range(heading_index + 1, len(lines) - 1):
        row_line = lines[index].strip()
        if not row_line:
            continue
        if row_line.startswith("### "):
            break
        if "|" not in row_line or not _is_markdown_table_separator(lines[index + 1]):
            continue
        candidate_headers = _split_markdown_table_row(row_line)
        if not candidate_headers:
            continue
        if "产品名称" not in candidate_headers or "产品特点概要" not in candidate_headers:
            continue
        headers = candidate_headers
        header_index = index
        break

    if header_index is None or not headers:
        return {}

    name_index = headers.index("产品名称")
    description_index = headers.index("产品特点概要")
    detail_map: dict[int, str | None] = {}

    row_number = 0
    for index in range(header_index + 2, len(lines)):
        row_line = lines[index].strip()
        if not row_line:
            if detail_map:
                break
            continue
        if row_line.startswith("### "):
            break
        if not row_line.startswith("|"):
            if detail_map:
                break
            continue
        cells = _split_markdown_table_row(row_line)
        if len(cells) <= max(name_index, description_index):
            continue
        row_number += 1
        detail_map[row_number] = _normalize_optional_str(cells[description_index])
    return detail_map


def _normalize_product_name_key(value: Any) -> str:
    normalized = _normalize_str(value).lower()
    if not normalized:
        return ""
    normalized = normalized.replace("㎡", "m2").replace("m²", "m2")
    return re.sub(r"[\s\u3000`~!@#$%^&*()_\-+=\[\]{}\\|;:'\",.<>/?，。；：、“”‘’（）【】《》、·]+", "", normalized)


def _build_product_name_keys(value: Any) -> set[str]:
    text = _normalize_str(value)
    if not text:
        return set()
    keys = {_normalize_product_name_key(text)}
    stripped_price_text = _PRODUCT_BLOCK_TRAILING_PRICE_RE.sub("", text).strip()
    if stripped_price_text and stripped_price_text != text:
        keys.add(_normalize_product_name_key(stripped_price_text))
    return {item for item in keys if item}


def _normalize_product_block_label(label: str) -> str:
    return _normalize_str(label).strip("：: ")


def _normalize_product_block_text(line: str) -> str:
    normalized = _normalize_str(line)
    if not normalized:
        return ""
    normalized = re.sub(r"^\s*-\s+", "", normalized).strip()
    normalized = re.sub(r"^\*\*(.+?)\*\*$", r"\1", normalized).strip()
    return normalized


def _load_markdown_product_block_description_map(markdown_text: str) -> dict[str, str]:
    lines = str(markdown_text or "").splitlines()
    descriptions: dict[str, str] = {}
    current_keys: set[str] = set()
    captured_lines: list[str] = []
    capture_group_active = False

    def flush() -> None:
        nonlocal captured_lines, capture_group_active, current_keys
        if not current_keys or not captured_lines:
            captured_lines = []
            capture_group_active = False
            return
        normalized_lines: list[str] = []
        seen: set[str] = set()
        for line in captured_lines:
            normalized_line = _normalize_product_block_text(line)
            if not normalized_line:
                continue
            if normalized_line in seen:
                continue
            seen.add(normalized_line)
            normalized_lines.append(normalized_line)
        if normalized_lines:
            description = "；".join(normalized_lines)
            for key in current_keys:
                descriptions[key] = description
        captured_lines = []
        capture_group_active = False

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped_line = line.strip()
        if stripped_line.startswith("### "):
            flush()
            current_keys = set()
            continue

        product_heading_match = _PRODUCT_BLOCK_HEADING_RE.match(stripped_line)
        if product_heading_match is not None:
            flush()
            current_keys = _build_product_name_keys(product_heading_match.group("title"))
            continue

        if not current_keys:
            continue

        inline_label_match = _PRODUCT_BLOCK_INLINE_LABEL_RE.match(stripped_line)
        if inline_label_match is not None:
            label = _normalize_product_block_label(inline_label_match.group("label"))
            value = _normalize_str(inline_label_match.group("value"))
            if label in _PRODUCT_BLOCK_CAPTURE_LABELS:
                if value:
                    captured_lines.append(f"{label}：{value}")
                capture_group_active = True
                continue
            if label in _PRODUCT_BLOCK_SKIP_LABELS:
                capture_group_active = False
                continue
            capture_group_active = False
            continue

        if not stripped_line:
            continue
        if not capture_group_active:
            continue
        captured_lines.append(stripped_line)

    flush()
    return descriptions


def _resolve_attachment_product_reference_descriptions(
    products: list[dict[str, Any]],
    *,
    markdown_text: str,
) -> list[dict[str, Any]]:
    detail_map = _load_markdown_product_detail_reference_map(markdown_text)
    block_map = _load_markdown_product_block_description_map(markdown_text)
    if not products:
        return []

    resolved_products: list[dict[str, Any]] = []
    for product in products:
        if not isinstance(product, dict):
            continue
        resolved_product = dict(product)
        description = _normalize_optional_str(resolved_product.get("product_description"))
        if description:
            match = _PRODUCT_DETAIL_REFERENCE_RE.fullmatch(description)
            if match is not None:
                row_index = int(match.group("index"))
                description = detail_map.get(row_index)
        if not description:
            for key in _build_product_name_keys(resolved_product.get("name")):
                block_description = block_map.get(key)
                if block_description:
                    description = block_description
                    break
        resolved_product["product_description"] = description
        resolved_products.append(resolved_product)
    return resolved_products


def _normalize_list_of_dicts(raw: Any, fields: tuple[str, ...]) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    normalized_items: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        normalized = {
            field: (
                _normalize_related_products(item.get(field))
                if field == "related_products"
                else _normalize_optional_str(item.get(field))
            )
            for field in fields
        }
        if any(value for key, value in normalized.items() if key != "source_section"):
            normalized_items.append(normalized)
    return normalized_items


def _normalize_text_items(value: Any) -> list[str]:
    if isinstance(value, list):
        normalized_items: list[str] = []
        for item in value:
            normalized = _normalize_optional_str(item)
            if normalized:
                normalized_items.append(normalized)
        return normalized_items
    normalized = _normalize_optional_str(value)
    return [normalized] if normalized else []


def _normalize_related_products(value: Any) -> list[Any]:
    if not isinstance(value, list):
        return []
    normalized_items: list[Any] = []
    seen: set[str] = set()
    for item in value:
        normalized_item: Any = None
        if isinstance(item, bool):
            normalized_item = None
        elif isinstance(item, int):
            normalized_item = item
        elif isinstance(item, float):
            normalized_item = int(item) if item.is_integer() else str(item).strip()
        else:
            normalized_text = _normalize_optional_str(item)
            if normalized_text:
                normalized_item = normalized_text
        if normalized_item is None:
            continue
        identity = json.dumps(normalized_item, ensure_ascii=False, sort_keys=True)
        if identity in seen:
            continue
        seen.add(identity)
        normalized_items.append(normalized_item)
    return normalized_items


def _normalize_official_malls(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    normalized_items: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        normalized = {
            "store_name": _normalize_optional_str(item.get("store_name")),
            "platform": _normalize_optional_str(item.get("platform")),
            "homepage_urls": _normalize_text_items(item.get("homepage_urls")),
            "store_ids": _normalize_text_items(item.get("store_ids")),
            "main_categories": _normalize_text_items(item.get("main_categories")),
            "advantages": _normalize_text_items(item.get("advantages")),
            "related_products": _normalize_related_products(item.get("related_products")),
            "other_info": _normalize_text_items(item.get("other_info")),
        }
        if any(
            normalized[field]
            for field in (
                "store_name",
                "platform",
                "homepage_urls",
                "store_ids",
                "main_categories",
                "advantages",
                "related_products",
                "other_info",
            )
        ):
            normalized_items.append(normalized)
    return normalized_items


def _normalize_official_media_matrix(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    normalized_items: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        normalized = {
            "media_platform": _normalize_optional_str(item.get("media_platform")),
            "account_name": _normalize_optional_str(item.get("account_name")),
            "account_id": _normalize_optional_str(item.get("account_id")),
            "is_official": _normalize_optional_str(item.get("is_official")),
            "homepage_urls": _normalize_text_items(item.get("homepage_urls")),
            "fans_count": _normalize_optional_str(item.get("fans_count")),
            "content_focus": _normalize_text_items(item.get("content_focus")),
            "related_products": _normalize_related_products(item.get("related_products")),
            "other_info": _normalize_text_items(item.get("other_info")),
        }
        if any(
            normalized[field]
            for field in (
                "media_platform",
                "account_name",
                "account_id",
                "is_official",
                "homepage_urls",
                "fans_count",
                "content_focus",
                "related_products",
                "other_info",
            )
        ):
            normalized_items.append(normalized)
    return normalized_items


def _normalize_other_info(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, dict):
        iterable = [{"title": key, "content": value} for key, value in raw.items()]
    elif isinstance(raw, list):
        iterable = raw
    else:
        return []

    normalized_items: list[dict[str, Any]] = []
    for item in iterable:
        if not isinstance(item, dict):
            continue
        title = _normalize_optional_str(item.get("title") or item.get("key") or item.get("name"))
        content = item.get("content") if "content" in item else item.get("value")
        normalized_content = _normalize_optional_str(content)
        if not title or not normalized_content:
            continue
        normalized_items.append(
            {
                "title": title,
                "content": normalized_content,
            }
        )
    return normalized_items


def _should_skip_markdown_section_title(title: str) -> bool:
    normalized = _normalize_str(title)
    if not normalized:
        return True
    if normalized.startswith("【") and "品牌AI知识库" in normalized:
        return True
    if normalized.endswith("· 品牌知识库"):
        return True
    return False


def _has_meaningful_payload(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        normalized = _normalize_str(value)
        return bool(normalized and normalized not in _EMPTY_OTHER_INFO_MARKERS)
    if isinstance(value, dict):
        return any(_has_meaningful_payload(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_has_meaningful_payload(item) for item in value)
    return True


def _looks_like_empty_markdown_content(content: Any) -> bool:
    normalized = _normalize_str(content)
    if not normalized:
        return True
    if normalized in _EMPTY_OTHER_INFO_MARKERS:
        return True

    tokens: list[str] = []
    for raw_line in normalized.splitlines():
        stripped_line = raw_line.strip().strip("*").strip()
        if not stripped_line:
            continue
        if re.fullmatch(r"[:\-\s|]+", stripped_line):
            continue
        if "|" in stripped_line:
            for cell in stripped_line.split("|"):
                token = _normalize_str(cell)
                if token:
                    tokens.append(token)
            continue
        token = _normalize_str(re.sub(r"^[\-\*\d.、\s]+", "", stripped_line))
        if token:
            tokens.append(token)

    if not tokens:
        return True

    meaningful_tokens = [
        token for token in tokens
        if token not in _EMPTY_OTHER_INFO_MARKERS
        and token not in _OTHER_INFO_MARKDOWN_TABLE_HEADERS
        and not re.fullmatch(r"[:\-\s]+", token)
    ]
    return len(meaningful_tokens) == 0


def _has_basic_info_value(snapshot: dict[str, Any], key: str) -> bool:
    basic_info = snapshot.get("basic_info") if isinstance(snapshot, dict) else {}
    if not isinstance(basic_info, dict):
        return False
    return _has_meaningful_payload(basic_info.get(key))


def _has_company_profile_value(snapshot: dict[str, Any], key: str) -> bool:
    company_profile = snapshot.get("company_profile") if isinstance(snapshot, dict) else {}
    if not isinstance(company_profile, dict):
        return False
    return _has_meaningful_payload(company_profile.get(key))


def _normalized_other_info_titles(other_info: Any) -> set[str]:
    iterable = other_info.values() if isinstance(other_info, dict) else other_info
    if not isinstance(iterable, list):
        return set()
    normalized_titles: set[str] = set()
    for item in iterable:
        if not isinstance(item, dict):
            continue
        title = _normalize_str(item.get("title") or item.get("key") or item.get("name"))
        if title:
            normalized_titles.add(title)
    return normalized_titles


def _title_alias_already_covered(title: str, existing_titles: set[str]) -> bool:
    normalized_title = _normalize_str(title)
    if not normalized_title or not existing_titles:
        return False
    for alias_group in _OTHER_INFO_SEMANTIC_ALIAS_GROUPS:
        if normalized_title not in alias_group:
            continue
        if any(alias != normalized_title and alias in existing_titles for alias in alias_group):
            return True
    return False


def _normalize_other_info_title_for_semantic_match(title: str) -> str:
    normalized = unicodedata.normalize("NFKC", _normalize_str(title))
    if not normalized:
        return ""
    normalized = normalized.strip("*").strip()
    normalized = _OTHER_INFO_TITLE_PREFIX_RE.sub("", normalized)
    normalized = normalized.replace("／", "/")
    normalized = re.sub(r"\s+", "", normalized)
    return normalized


def _has_management_team_content(snapshot: dict[str, Any]) -> bool:
    management_team = snapshot.get("management_team") if isinstance(snapshot, dict) else []
    if not isinstance(management_team, list):
        return False
    for item in management_team:
        if not isinstance(item, dict):
            continue
        if any(
            _has_meaningful_payload(item.get(key))
            for key in ("member_name", "name", "position", "title", "profile", "bio")
        ):
            return True
    return False


def _is_management_team_title_covered(title: str, snapshot: dict[str, Any]) -> bool:
    if not _has_management_team_content(snapshot):
        return False
    normalized_title = _normalize_other_info_title_for_semantic_match(title)
    if not normalized_title:
        return False
    if any(keyword in normalized_title for keyword in ("管理团队", "核心团队", "高管团队", "核心高管", "创始团队")):
        return True
    management_team = snapshot.get("management_team") if isinstance(snapshot, dict) else []
    member_names = {
        _normalize_other_info_title_for_semantic_match(item.get("member_name") or item.get("name"))
        for item in management_team
        if isinstance(item, dict)
    }
    return normalized_title in member_names


def _classify_standard_other_info_title(title: str) -> str | None:
    normalized_title = _normalize_other_info_title_for_semantic_match(title)
    if not normalized_title:
        return None
    if any(keyword in normalized_title for keyword in ("官网地址", "官方阵地", "官方公众号", "官方微信公众号", "客服热线")):
        return "official_channels"
    if any(keyword in normalized_title for keyword in ("竞品多维对比", "多维对比", "对比维度")):
        return "competitor_comparison"
    if any(keyword in normalized_title for keyword in ("优劣势对比", "差异化定位", "差异化护城河")):
        return "competitor_differentiation"
    if any(keyword in normalized_title for keyword in ("品牌/公司实体", "品牌公司实体", "品牌基础身份")):
        return "brand_company_identity"
    if any(keyword in normalized_title for keyword in ("品牌档案", "品牌定位", "一句话简介", "核心价值主张", "目标区域", "品牌英文名")):
        return "brand_profile"
    if any(keyword in normalized_title for keyword in ("品牌故事/发展里程碑", "品牌故事", "发展里程碑")):
        return "development_history"
    if any(keyword in normalized_title for keyword in ("公司档案", "公司信息", "企业信息", "公司简介", "公司所获荣誉", "公司近期新闻")):
        return "company_profile"
    if any(keyword in normalized_title for keyword in ("产品线", "产品信息")):
        return "products"
    if any(keyword in normalized_title for keyword in ("主要竞争对手", "竞争对手")):
        return "competitors"
    return None


def _is_standard_other_info_title_covered(title: str, snapshot: dict[str, Any]) -> bool:
    normalized_title = _normalize_str(title)
    if not normalized_title:
        return False
    if _is_management_team_title_covered(normalized_title, snapshot):
        return True

    direct_title_checks: tuple[tuple[str, bool], ...] = (
        ("1.1 品牌基础身份", _has_basic_info_value(snapshot, "brand_name") or _has_basic_info_value(snapshot, "brand_alias")),
        ("1.2 官方阵地", _has_basic_info_value(snapshot, "website") or _has_basic_info_value(snapshot, "official_wechat_account") or _has_meaningful_payload(snapshot.get("official_media_matrix"))),
        ("品牌定位(positioning)", _has_basic_info_value(snapshot, "positioning")),
        ("一句话简介(one_liner)", _has_basic_info_value(snapshot, "intro")),
        ("核心价值主张", _has_basic_info_value(snapshot, "advantages")),
        ("目标区域", _has_basic_info_value(snapshot, "target_regions")),
        ("品牌故事/发展里程碑", _has_company_profile_value(snapshot, "development_history")),
        ("1.4 公司档案", _has_company_profile_value(snapshot, "brand_subject_name") or _has_company_profile_value(snapshot, "stock_info") or _has_company_profile_value(snapshot, "company_address")),
        ("公司简介", _has_company_profile_value(snapshot, "company_intro")),
        ("公司所获荣誉", _has_meaningful_payload(snapshot.get("authority_honors"))),
        ("公司近期新闻", _has_company_profile_value(snapshot, "recent_news")),
        ("2.1 产品线(主推)", _has_meaningful_payload(snapshot.get("products")) or _has_meaningful_payload(snapshot.get("attachment_products"))),
        ("4.1 主要竞争对手(12 家)", _has_meaningful_payload(snapshot.get("competitors"))),
        ("品牌英文名", _has_basic_info_value(snapshot, "english_name")),
        ("官网地址", _has_basic_info_value(snapshot, "website")),
        ("官方微信公众号", _has_basic_info_value(snapshot, "official_wechat_account")),
        ("客服热线", _has_basic_info_value(snapshot, "customer_service_hotline")),
    )
    for candidate_title, covered in direct_title_checks:
        if normalized_title == candidate_title and covered:
            return True
    semantic_title = _classify_standard_other_info_title(normalized_title)
    if semantic_title == "official_channels":
        return (
            _has_basic_info_value(snapshot, "website")
            or _has_basic_info_value(snapshot, "official_wechat_account")
            or _has_basic_info_value(snapshot, "customer_service_hotline")
            or _has_meaningful_payload(snapshot.get("official_media_matrix"))
        )
    if semantic_title == "competitor_comparison":
        competitors = snapshot.get("competitors") if isinstance(snapshot, dict) else []
        return any(
            _has_meaningful_payload(item.get("comparison_dimensions"))
            for item in competitors
            if isinstance(item, dict)
        )
    if semantic_title == "competitor_differentiation":
        competitors = snapshot.get("competitors") if isinstance(snapshot, dict) else []
        return any(
            _has_meaningful_payload(item.get("differentiated_positioning"))
            for item in competitors
            if isinstance(item, dict)
        )
    if semantic_title == "brand_company_identity":
        return (
            (_has_basic_info_value(snapshot, "brand_name") or _has_basic_info_value(snapshot, "brand_alias"))
            and (
                _has_company_profile_value(snapshot, "brand_subject_name")
                or _has_company_profile_value(snapshot, "company_address")
                or _has_company_profile_value(snapshot, "established_time")
            )
        )
    if semantic_title == "brand_profile":
        return any(
            (
                _has_basic_info_value(snapshot, "english_name"),
                _has_basic_info_value(snapshot, "positioning"),
                _has_basic_info_value(snapshot, "intro"),
                _has_basic_info_value(snapshot, "advantages"),
                _has_basic_info_value(snapshot, "target_regions"),
            )
        )
    if semantic_title == "development_history":
        return _has_company_profile_value(snapshot, "development_history")
    if semantic_title == "company_profile":
        return any(
            (
                _has_company_profile_value(snapshot, "brand_subject_name"),
                _has_company_profile_value(snapshot, "company_intro"),
                _has_company_profile_value(snapshot, "company_address"),
                _has_company_profile_value(snapshot, "stock_info"),
                _has_company_profile_value(snapshot, "recent_news"),
                _has_meaningful_payload(snapshot.get("authority_honors")),
            )
        )
    if semantic_title == "products":
        return _has_meaningful_payload(snapshot.get("products")) or _has_meaningful_payload(snapshot.get("attachment_products"))
    if semantic_title == "competitors":
        return _has_meaningful_payload(snapshot.get("competitors"))
    return False


def _filter_other_info_entries(
    other_info: Any,
    *,
    snapshot: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if isinstance(other_info, dict):
        iterable = [
            {"title": key, "content": value}
            for key, value in other_info.items()
        ]
    elif isinstance(other_info, list):
        iterable = other_info
    else:
        iterable = []
    snapshot_payload = snapshot if isinstance(snapshot, dict) else {}
    filtered: list[dict[str, Any]] = []
    seen_entries: set[str] = set()
    existing_titles: set[str] = set()

    for item in iterable:
        if not isinstance(item, dict):
            continue
        title = _normalize_str(item.get("title"))
        raw_content = item.get("content") if "content" in item else item.get("value")
        if not title or not _has_meaningful_payload(raw_content):
            continue
        if _looks_like_empty_markdown_content(raw_content):
            continue
        if _title_alias_already_covered(title, existing_titles):
            continue
        if _is_standard_other_info_title_covered(title, snapshot_payload):
            continue
        identity = _other_info_entry_identity(title=title, content=raw_content)
        if identity in seen_entries:
            continue
        filtered.append({"title": title, "content": raw_content})
        seen_entries.add(identity)
        existing_titles.add(title)
    return filtered


def _other_info_entry_identity(*, title: str, content: Any) -> str:
    normalized_title = _normalize_str(title)
    normalized_content = _normalize_str(content)
    return json.dumps(
        {
            "title": normalized_title,
            "content": normalized_content,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _extract_competitor_section_payloads(other_info: Any) -> dict[str, str]:
    iterable = other_info if isinstance(other_info, list) else []
    sections: dict[str, str] = {}
    for item in iterable:
        if not isinstance(item, dict):
            continue
        title = _normalize_str(item.get("title") or item.get("key") or item.get("name"))
        if title not in _COMPETITOR_SUMMARY_SECTION_TITLES:
            continue
        content = item.get("content") if "content" in item else item.get("value")
        if not _has_meaningful_payload(content):
            continue
        if _looks_like_empty_markdown_content(content):
            continue
        sections[title] = _normalize_str(content)
    return sections


def _build_competitor_section_summary_prompt(
    *,
    brand_name: str,
    competitor_names: list[str],
    section_payloads: dict[str, str],
) -> str:
    section_blocks: list[str] = []
    for title in _COMPETITOR_SUMMARY_SECTION_TITLES:
        content = _normalize_str(section_payloads.get(title))
        if not content:
            continue
        section_blocks.extend(
            [
                f"## {title}",
                content,
                "",
            ]
        )

    return f"""
# 角色
你是一名品牌知识结构化助手。

# 任务
请根据给定的品牌竞品章节内容，整理出适合写入竞品结构化字段的精炼结果。

# 目标品牌
{brand_name}

# 已识别竞品
{", ".join(competitor_names) if competitor_names else "未提供"}

# 输出要求
1. 只根据提供内容总结，不能编造。
2. `comparison_dimensions` 只保留“对比维度/比较口径”，每项尽量短，适合放进数组。
3. `differentiated_positioning` 只保留“目标品牌相对竞品的差异化优势/定位”，每项要清晰、去掉 markdown、去掉表格原文、去掉“详见附件”“(空)”等占位语。
4. 如果某一类没有可用内容，输出空数组。
5. 只输出 JSON 对象，不要输出解释文字。

# JSON 结构
{{
  "comparison_dimensions": [],
  "differentiated_positioning": []
}}

# 原始章节
{chr(10).join(section_blocks).strip()}
""".strip()


def _merge_competitor_section_summary(
    competitors: list[dict[str, Any]],
    *,
    comparison_dimensions: list[str],
    differentiated_positioning: list[str],
) -> list[dict[str, Any]]:
    comparison_text = "；".join(_normalize_text_items(comparison_dimensions))
    differentiated_text = "；".join(_normalize_text_items(differentiated_positioning))
    merged: list[dict[str, Any]] = []
    for item in competitors:
        if not isinstance(item, dict):
            continue
        if not _normalize_str(item.get("name")):
            continue
        candidate = dict(item)
        if comparison_text:
            candidate["comparison_dimensions"] = _merge_texts(
                candidate.get("comparison_dimensions"),
                comparison_text,
            )
        if differentiated_text:
            candidate["differentiated_positioning"] = _merge_texts(
                candidate.get("differentiated_positioning"),
                differentiated_text,
            )
        merged.append(candidate)
    return merged


async def _summarize_competitor_sections_into_snapshot(
    snapshot: dict[str, Any],
    *,
    brand_name: str,
    settings: Any,
) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        return snapshot
    raw_competitors = snapshot.get("competitors")
    competitors = normalize_competitors_for_storage(raw_competitors)
    if not competitors:
        return snapshot

    section_payloads = _extract_competitor_section_payloads(snapshot.get("other_info"))
    if not section_payloads:
        return snapshot

    competitor_names = [
        _normalize_str(item.get("name"))
        for item in competitors
        if isinstance(item, dict) and _normalize_str(item.get("name"))
    ]
    if not competitor_names:
        return snapshot

    try:
        resolved_settings = require_settings(settings)
        prompt = _build_competitor_section_summary_prompt(
            brand_name=brand_name,
            competitor_names=competitor_names,
            section_payloads=section_payloads,
        )
        parsed = await asyncio.wait_for(
            asyncio.to_thread(
                call_text_llm_json,
                prompt,
                settings=resolved_settings,
            ),
            timeout=_COMPETITOR_SECTION_SUMMARY_TIMEOUT_SECONDS,
        )
    except Exception as exc:  # pragma: no cover - exercised via tests with patched callers
        logger.warning(
            "Competitor section summary skipped for brand=%s due to LLM error: %s",
            brand_name,
            exc,
        )
        return snapshot

    comparison_dimensions = _normalize_text_items(
        parsed.get("comparison_dimensions") if isinstance(parsed, dict) else None
    )
    differentiated_positioning = _normalize_text_items(
        parsed.get("differentiated_positioning") if isinstance(parsed, dict) else None
    )
    if not comparison_dimensions and not differentiated_positioning:
        return snapshot

    consumed_titles: set[str] = set()
    if comparison_dimensions:
        consumed_titles.add(_COMPETITOR_COMPARISON_SECTION_TITLE)
    if differentiated_positioning:
        consumed_titles.add(_COMPETITOR_DIFFERENTIATION_SECTION_TITLE)

    other_info = snapshot.get("other_info")
    if isinstance(other_info, list):
        remaining_other_info = [
            item
            for item in other_info
            if not (
                isinstance(item, dict)
                and _normalize_str(item.get("title") or item.get("key") or item.get("name")) in consumed_titles
            )
        ]
    else:
        remaining_other_info = other_info

    updated_snapshot = dict(snapshot)
    updated_snapshot["competitors"] = _merge_competitor_section_summary(
        raw_competitors if isinstance(raw_competitors, list) else competitors,
        comparison_dimensions=comparison_dimensions,
        differentiated_positioning=differentiated_positioning,
    )
    updated_snapshot["other_info"] = _filter_other_info_entries(
        remaining_other_info,
        snapshot=updated_snapshot,
    )
    return updated_snapshot


def _extract_markdown_sections_as_other_info(markdown_text: str) -> list[dict[str, Any]]:
    lines = [line.rstrip() for line in str(markdown_text or "").splitlines()]
    sections: list[dict[str, Any]] = []
    current_title: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_title, current_lines
        if not current_title:
            current_lines = []
            return
        content = "\n".join(line for line in current_lines).strip()
        if content and not _should_skip_markdown_section_title(current_title):
            sections.append(
                {
                    "title": current_title,
                    "content": content,
                }
            )
        current_title = None
        current_lines = []

    for line in lines:
        heading_match = _MARKDOWN_BOLD_HEADING_RE.match(line.strip())
        if heading_match:
            flush()
            current_title = _normalize_str(heading_match.group(1))
            current_lines = []
            continue
        if current_title is not None:
            current_lines.append(line)
    flush()
    return sections


def _merge_markdown_sections_into_other_info(
    other_info: Any,
    *,
    markdown_text: str,
    snapshot: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    normalized_other_info = _filter_other_info_entries(other_info, snapshot=snapshot)
    seen_entries = {
        _other_info_entry_identity(
            title=item.get("title") or item.get("key") or item.get("name"),
            content=item.get("content") if "content" in item else item.get("value"),
        )
        for item in normalized_other_info
        if isinstance(item, dict)
    }
    existing_titles = _normalized_other_info_titles(normalized_other_info)
    for item in _extract_markdown_sections_as_other_info(markdown_text):
        title = _normalize_str(item.get("title"))
        content = _normalize_str(item.get("content"))
        if not title or not content:
            continue
        if _looks_like_empty_markdown_content(content):
            continue
        if _title_alias_already_covered(title, existing_titles):
            continue
        if _is_standard_other_info_title_covered(title, snapshot or {}):
            continue
        identity = _other_info_entry_identity(title=title, content=content)
        if identity in seen_entries:
            continue
        normalized_other_info.append(item)
        seen_entries.add(identity)
        existing_titles.add(title)
    return _filter_other_info_entries(normalized_other_info, snapshot=snapshot)


def _merge_attachment_products(
    existing_products: Any,
    incoming_products: Any,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    index_by_name: dict[str, int] = {}

    def add_or_merge(product: Any) -> None:
        normalized_products = _normalize_products([product])
        if not normalized_products:
            return
        normalized_product = normalized_products[0]
        product_name = _normalize_optional_str(normalized_product.get("name"))
        if not product_name:
            return
        key = product_name.casefold()
        existing_index = index_by_name.get(key)
        if existing_index is None:
            index_by_name[key] = len(merged)
            merged.append(normalized_product)
            return
        current = merged[existing_index]
        for field in (
            "product_alias",
            "product_description",
            "product_website",
            "price_info",
            "product_advantages",
            "target_scenarios",
            "service_standard",
            "service_process",
            "cases_and_reputation",
            "certification_info",
            "core_technology",
            "other_info",
        ):
            current[field] = _merge_optional_string(current.get(field), normalized_product.get(field))
        current["product_images"] = _merge_text_lists(
            current.get("product_images"),
            normalized_product.get("product_images"),
        )
        current["coverage_regions"] = _merge_text_lists(
            current.get("coverage_regions"),
            normalized_product.get("coverage_regions"),
        )

    for product in list(existing_products) if isinstance(existing_products, list) else []:
        add_or_merge(product)
    for product in list(incoming_products) if isinstance(incoming_products, list) else []:
        add_or_merge(product)
    return merged


def _load_attachment_products_from_rows(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    for row in rows:
        if str((row or {}).get("knowledge_type") or "").strip() != _ATTACHMENT_PRODUCTS_KNOWLEDGE_TYPE:
            continue
        return _normalize_products(_load_content_json((row or {}).get("content_json")))
    return []


def _merge_other_info_with_attachment_products(
    other_info: Any,
    attachment_products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized_other_info = list(other_info) if isinstance(other_info, list) else []
    merged_other_info: list[dict[str, Any]] = []
    attachment_title_key = _ATTACHMENT_PRODUCTS_OTHER_INFO_TITLE.casefold()
    for item in normalized_other_info:
        if not isinstance(item, dict):
            continue
        title = _normalize_optional_str(item.get("title") or item.get("key") or item.get("name"))
        if title and title.casefold() == attachment_title_key:
            continue
        merged_other_info.append(item)
    if attachment_products:
        merged_other_info.append(
            {
                "title": _ATTACHMENT_PRODUCTS_OTHER_INFO_TITLE,
                "content": _copy_jsonable(attachment_products),
            }
        )
    return merged_other_info


def _merge_optional_string(current: str | None, incoming: str | None) -> str | None:
    if not current:
        return incoming
    if not incoming:
        return current
    if incoming == current:
        return current
    return incoming if len(incoming) > len(current) else current


def _merge_texts(current: str | None, incoming: str | None) -> str | None:
    current_value = _normalize_optional_str(current)
    incoming_value = _normalize_optional_str(incoming)
    if not current_value:
        return incoming_value
    if not incoming_value or incoming_value == current_value:
        return current_value
    if incoming_value in current_value:
        return current_value
    if current_value in incoming_value:
        return incoming_value
    return f"{current_value}；{incoming_value}"


def _merge_website_lists(current: Any, incoming: Any) -> list[str]:
    return _normalize_websites([current, incoming])


def _merge_text_lists(current: Any, incoming: Any) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for source in (current, incoming):
        for item in _normalize_text_items(source):
            if item in seen:
                continue
            seen.add(item)
            merged.append(item)
    return merged


def _merge_related_product_lists(current: Any, incoming: Any) -> list[Any]:
    merged: list[Any] = []
    seen: set[str] = set()
    for source in (current, incoming):
        for item in _normalize_related_products(source):
            identity = json.dumps(item, ensure_ascii=False, sort_keys=True)
            if identity in seen:
                continue
            seen.add(identity)
            merged.append(item)
    return merged


def _append_source_file(item: dict[str, Any], source_file: str) -> None:
    files = item.setdefault("source_files", [])
    if not isinstance(files, list):
        files = []
        item["source_files"] = files
    if source_file and source_file not in files:
        files.append(source_file)


def _merge_company_profile(base: dict[str, Any], incoming: dict[str, Any], source_file: str) -> dict[str, Any]:
    for field in (
        "brand_subject_name",
        "business_license_image_path",
        "registered_capital",
        "stock_info",
        "company_address",
        "company_intro",
        "established_time",
        "store_distribution",
        "recent_news",
        "development_concept",
        "corporate_values",
        "company_mission",
        "development_history",
        "other_info",
    ):
        if field in {"company_intro", "recent_news", "development_history"}:
            base[field] = _merge_texts(base.get(field), incoming.get(field))
        else:
            base[field] = _merge_optional_string(base.get(field), incoming.get(field))
    _append_source_file(base, source_file)
    return base


def _dedupe_key(item: dict[str, Any], fields: tuple[str, ...]) -> str:
    return "|".join(_normalize_str(item.get(field)).lower() for field in fields)


def _merge_list_items(
    existing_items: list[dict[str, Any]],
    incoming_items: list[dict[str, Any]],
    *,
    key_fields: tuple[str, ...],
    long_text_fields: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {
        _dedupe_key(item, key_fields): dict(item)
        for item in existing_items
        if _dedupe_key(item, key_fields).strip("|")
    }

    for item in incoming_items:
        key = _dedupe_key(item, key_fields)
        if not key.strip("|"):
            continue
        candidate = dict(item)
        source_file = _normalize_str(candidate.pop("source_file", ""))
        existing = merged.get(key)
        if existing is None:
            existing = dict(candidate)
            existing.setdefault("source_files", [])
            merged[key] = existing
        else:
            for field, value in candidate.items():
                if field == "source_files":
                    continue
                if field in long_text_fields:
                    existing[field] = _merge_texts(existing.get(field), value)
                else:
                    existing[field] = _merge_optional_string(existing.get(field), value)
        _append_source_file(existing, source_file)

    return list(merged.values())


def _merge_official_malls(
    existing_items: list[dict[str, Any]],
    incoming_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    ordered_keys: list[str] = []
    for item in existing_items + incoming_items:
        if not isinstance(item, dict):
            continue
        store_name = _normalize_optional_str(item.get("store_name"))
        platform = _normalize_optional_str(item.get("platform"))
        homepage_urls = _normalize_text_items(item.get("homepage_urls"))
        key = (
            f"{_normalize_lower_key_part(store_name)}|"
            f"{_normalize_lower_key_part(platform)}|"
            f"{'|'.join(_normalize_lower_key_part(url) for url in homepage_urls[:1])}"
        )
        if not key.strip("|"):
            continue
        existing = merged.get(key)
        if existing is None:
            merged[key] = {
                "store_name": store_name,
                "platform": platform,
                "homepage_urls": homepage_urls,
                "main_categories": _normalize_text_items(item.get("main_categories")),
                "advantages": _normalize_text_items(item.get("advantages")),
                "related_products": _normalize_related_products(item.get("related_products")),
                "other_info": _normalize_text_items(item.get("other_info")),
            }
            ordered_keys.append(key)
            continue
        existing["store_name"] = _merge_optional_string(existing.get("store_name"), store_name)
        existing["platform"] = _merge_optional_string(existing.get("platform"), platform)
        existing["homepage_urls"] = _merge_text_lists(existing.get("homepage_urls"), homepage_urls)
        existing["main_categories"] = _merge_text_lists(existing.get("main_categories"), item.get("main_categories"))
        existing["advantages"] = _merge_text_lists(existing.get("advantages"), item.get("advantages"))
        existing["related_products"] = _merge_related_product_lists(
            existing.get("related_products"),
            item.get("related_products"),
        )
        existing["other_info"] = _merge_text_lists(existing.get("other_info"), item.get("other_info"))
    return [merged[key] for key in ordered_keys]


def _merge_official_media_matrix(
    existing_items: list[dict[str, Any]],
    incoming_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    ordered_keys: list[str] = []
    for item in existing_items + incoming_items:
        if not isinstance(item, dict):
            continue
        media_platform = _normalize_optional_str(item.get("media_platform"))
        account_name = _normalize_optional_str(item.get("account_name"))
        account_id = _normalize_optional_str(item.get("account_id"))
        key = (
            f"{_normalize_lower_key_part(media_platform)}|"
            f"{_normalize_lower_key_part(account_name)}|"
            f"{_normalize_lower_key_part(account_id)}"
        )
        if not key.strip("|"):
            continue
        existing = merged.get(key)
        if existing is None:
            merged[key] = {
                "media_platform": media_platform,
                "account_name": account_name,
                "account_id": account_id,
                "is_official": _normalize_optional_str(item.get("is_official")),
                "related_products": _normalize_related_products(item.get("related_products")),
                "other_info": _normalize_text_items(item.get("other_info")),
            }
            ordered_keys.append(key)
            continue
        existing["media_platform"] = _merge_optional_string(existing.get("media_platform"), media_platform)
        existing["account_name"] = _merge_optional_string(existing.get("account_name"), account_name)
        existing["account_id"] = _merge_optional_string(existing.get("account_id"), account_id)
        existing["is_official"] = _merge_optional_string(
            existing.get("is_official"),
            _normalize_optional_str(item.get("is_official")),
        )
        existing["related_products"] = _merge_related_product_lists(
            existing.get("related_products"),
            item.get("related_products"),
        )
        existing["other_info"] = _merge_text_lists(existing.get("other_info"), item.get("other_info"))
    return [merged[key] for key in ordered_keys]


def _merge_other_info(
    existing_items: list[dict[str, Any]],
    incoming_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in existing_items + incoming_items:
        if not isinstance(item, dict):
            continue
        title = _normalize_optional_str(item.get("title") or item.get("key") or item.get("name"))
        content = _normalize_optional_str(item.get("content") if "content" in item else item.get("value"))
        if not title or not content:
            continue
        identity = _other_info_entry_identity(title=title, content=content)
        if identity in seen:
            continue
        seen.add(identity)
        merged.append(
            {
                "title": title,
                "content": content,
            }
        )
    return merged


def _normalize_extraction_result(raw: dict[str, Any], *, source_file: str) -> dict[str, Any]:
    normalized = {
        "basic_info": _normalize_basic_info(raw.get("basic_info")),
        "products": _normalize_products(raw.get("products")),
        "company_profile": _normalize_company_profile(raw.get("company_profile")),
        "management_team": _normalize_list_of_dicts(
            raw.get("management_team"),
            ("member_name", "position", "profile", "introduction_website", "other_info", "source_section"),
        ),
        "competitors": _normalize_list_of_dicts(
            raw.get("competitors"),
            (
                "name",
                "competitors_alias",
                "competitors_description",
                "website",
                "competitors_logo",
                "competitive_advantages",
                "differentiated_positioning",
                "comparison_dimensions",
                "other_info",
                "source_section",
            ),
        ),
        "authority_honors": _normalize_list_of_dicts(
            raw.get("authority_honors"),
            (
                "title",
                "description",
                "report_link",
                "year",
                "qualification_proof",
                "issuing_authority",
                "other_info",
                "source_section",
            ),
        ),
        "customers_cases": _normalize_list_of_dicts(
            raw.get("customers_cases"),
            (
                "case_name",
                "cooperation_time",
                "customer_name",
                "cooperation_product",
                "cooperation_highlight",
                "customer_feedback",
                "case_link",
                "related_products",
                "other_info",
                "source_section",
            ),
        ),
        "sensitive_topics": _normalize_list_of_dicts(
            raw.get("sensitive_topics"),
            ("topic", "description", "forbidden_terms", "history_negative_clarification", "other_info", "source_section"),
        ),
        "official_malls": _normalize_official_malls(raw.get("official_malls")),
        "official_media_matrix": _normalize_official_media_matrix(raw.get("official_media_matrix")),
        "other_info": _normalize_other_info(raw.get("other_info")),
    }

    for section_name in (
        "management_team",
        "competitors",
        "authority_honors",
        "customers_cases",
        "sensitive_topics",
    ):
        for item in normalized[section_name]:
            item["source_file"] = source_file
    return normalized


def _normalize_attachment_entry(file_item: dict[str, Any], *, full_text: str | None) -> dict[str, Any]:
    return {
        "name": _normalize_optional_str(file_item.get("original_filename")),
        "document_id": _normalize_optional_str(file_item.get("document_id")),
        "source_type": _normalize_optional_str(file_item.get("source_type")) or "brand",
        "file_size": file_item.get("file_size"),
        "summary": None,
        "source_url": None,
        "subcategory": None,
        "fulltext_length": len(full_text or ""),
    }


def _merge_brand_knowledge(*, base: dict[str, Any], extracted: dict[str, Any]) -> dict[str, Any]:
    for field in (
        "brand_name",
        "brand_alias",
        "english_name",
        "industry_id",
        "brand_logo",
        "customer_service_hotline",
        "official_wechat_account",
        "intro",
        "email",
        "brand_enterprise_entity",
        "business_license_image_path",
        "positioning",
        "advantages",
        "mission",
        "vision",
        "other_info",
    ):
        base["basic_info"][field] = _merge_optional_string(
            base["basic_info"].get(field),
            extracted["basic_info"].get(field),
        )
    base["basic_info"]["website"] = _merge_website_lists(
        base["basic_info"].get("website"),
        extracted["basic_info"].get("website"),
    )
    if not base["basic_info"]["target_regions"] and extracted["basic_info"].get("target_regions"):
        base["basic_info"]["target_regions"] = list(extracted["basic_info"]["target_regions"])

    extracted_products = extracted["products"]
    existing_products_by_name = {
        _normalize_str(product.get("name")).lower(): product
        for product in base["products"]
        if _normalize_str(product.get("name"))
    }
    for product in extracted_products:
        key = _normalize_str(product.get("name")).lower()
        if key and key in existing_products_by_name:
            existing_product = existing_products_by_name[key]
            for field in (
                "product_alias",
                "product_description",
                "product_website",
                "price_info",
                "product_advantages",
                "target_scenarios",
                "service_standard",
                "service_process",
                "cases_and_reputation",
                "certification_info",
                "core_technology",
                "other_info",
            ):
                existing_product[field] = _merge_optional_string(existing_product.get(field), product.get(field))
            if not existing_product.get("product_images") and product.get("product_images"):
                existing_product["product_images"] = list(product["product_images"])
            if not existing_product.get("coverage_regions") and product.get("coverage_regions"):
                existing_product["coverage_regions"] = list(product["coverage_regions"])
        else:
            base["products"].append(dict(product))

    base["company_profile"] = _merge_company_profile(
        base["company_profile"],
        extracted["company_profile"],
        extracted["source_file"],
    )
    base["management_team"] = _merge_list_items(
        base["management_team"],
        extracted["management_team"],
        key_fields=("member_name",),
        long_text_fields=("profile",),
    )
    base["competitors"] = _merge_list_items(
        base["competitors"],
        extracted["competitors"],
        key_fields=("name",),
        long_text_fields=("competitors_description", "competitive_advantages", "differentiated_positioning", "comparison_dimensions"),
    )
    base["authority_honors"] = _merge_list_items(
        base["authority_honors"],
        extracted["authority_honors"],
        key_fields=("title", "year"),
        long_text_fields=("description",),
    )
    base["customers_cases"] = _merge_list_items(
        base["customers_cases"],
        extracted["customers_cases"],
        key_fields=("case_name", "customer_name"),
        long_text_fields=("cooperation_highlight", "customer_feedback"),
    )
    base["sensitive_topics"] = _merge_list_items(
        base["sensitive_topics"],
        extracted["sensitive_topics"],
        key_fields=("topic",),
        long_text_fields=("description", "forbidden_terms", "history_negative_clarification"),
    )
    base["official_malls"] = _merge_official_malls(
        base["official_malls"],
        extracted["official_malls"],
    )
    base["official_media_matrix"] = _merge_official_media_matrix(
        base["official_media_matrix"],
        extracted["official_media_matrix"],
    )
    base["other_info"] = _merge_other_info(
        base["other_info"],
        extracted["other_info"],
    )
    return base


def _build_empty_knowledge() -> dict[str, Any]:
    return {
        "basic_info": {
            "brand_name": None,
            "brand_alias": None,
            "english_name": None,
            "industry_id": None,
            "brand_logo": None,
            "website": [],
            "customer_service_hotline": None,
            "official_wechat_account": None,
            "intro": None,
            "email": None,
            "brand_enterprise_entity": None,
            "business_license_image_path": None,
            "positioning": None,
            "advantages": None,
            "mission": None,
            "vision": None,
            "target_regions": [],
            "other_info": None,
        },
        "products": [],
        "company_profile": {
            "brand_subject_name": None,
            "business_license_image_path": None,
            "registered_capital": None,
            "stock_info": None,
            "company_address": None,
            "company_intro": None,
            "established_time": None,
            "store_distribution": None,
            "recent_news": None,
            "development_concept": None,
            "corporate_values": None,
            "company_mission": None,
            "development_history": None,
            "other_info": None,
            "source_files": [],
        },
        "management_team": [],
        "competitors": [],
        "authority_honors": [],
        "customers_cases": [],
        "sensitive_topics": [],
        "attachments": [],
        "official_malls": [],
        "official_media_matrix": [],
        "other_info": [],
    }


def _sanitize_final_payload(payload: dict[str, Any]) -> dict[str, Any]:
    company_profile = dict(payload["company_profile"])
    if not any(value for key, value in company_profile.items() if key != "source_files"):
        company_profile = {}
    return {
        "basic_info": payload["basic_info"],
        "products": payload["products"],
        "company_profile": company_profile,
        "management_team": payload["management_team"],
        "competitors": payload["competitors"],
        "authority_honors": payload["authority_honors"],
        "customers_cases": payload["customers_cases"],
        "sensitive_topics": payload["sensitive_topics"],
        "attachments": payload["attachments"],
        "official_malls": payload["official_malls"],
        "official_media_matrix": payload["official_media_matrix"],
        "other_info": payload["other_info"],
    }


def _has_meaningful_value(value: Any) -> bool:
    if value in (None, "", [], {}):
        return False
    if isinstance(value, list):
        return any(_has_meaningful_value(item) for item in value)
    if isinstance(value, dict):
        return any(_has_meaningful_value(item) for item in value.values())
    return True


def _value_changed(before: Any, after: Any) -> bool:
    return json.dumps(before, ensure_ascii=False, sort_keys=True) != json.dumps(
        after,
        ensure_ascii=False,
        sort_keys=True,
    )


def _format_markdown_value(value: Any) -> str:
    if isinstance(value, list):
        normalized_items = [
            _normalize_optional_str(item) if not isinstance(item, dict) else json.dumps(item, ensure_ascii=False, sort_keys=True)
            for item in value
            if _has_meaningful_value(item)
        ]
        return "；".join(item for item in normalized_items if item)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return _normalize_str(value)


def _normalize_snapshot_attachments(entries: Any) -> list[dict[str, Any]]:
    if not isinstance(entries, list):
        return []
    normalized_entries: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in entries:
        if not isinstance(item, dict):
            continue
        name = _normalize_optional_str(item.get("name") or item.get("original_filename"))
        source_url = _normalize_optional_str(item.get("source_url") or item.get("url"))
        subcategory = _normalize_optional_str(item.get("subcategory"))
        dedupe_key = (name or "", source_url or "", subcategory or "")
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized_entries.append(
            {
                "name": name,
                "source_url": source_url,
                "subcategory": subcategory,
                "type": _normalize_optional_str(item.get("type") or item.get("source_type")),
                "description": _normalize_optional_str(item.get("description")),
            }
        )
    return normalized_entries


def _build_external_enrichment_markdown_sources(
    *,
    brand_name: str,
    before_snapshot: dict[str, Any],
    after_snapshot: dict[str, Any],
) -> list[dict[str, Any]]:
    lines = [f"# {brand_name} 天眼查与联网回补补充信息"]

    basic_info_labels = (
        ("brand_alias", "品牌别名"),
        ("english_name", "英文名称"),
        ("brand_logo", "品牌 Logo"),
        ("website", "品牌官网"),
        ("customer_service_hotline", "客服热线"),
        ("official_wechat_account", "官方微信"),
        ("email", "联系邮箱"),
        ("brand_enterprise_entity", "品牌主体"),
        ("business_license_image_path", "营业执照"),
        ("industry_id", "行业 ID"),
        ("positioning", "品牌定位"),
        ("advantages", "品牌优势"),
        ("mission", "品牌使命"),
        ("vision", "品牌愿景"),
        ("target_regions", "目标区域"),
        ("other_info", "其他基础信息"),
    )
    basic_lines: list[str] = []
    before_basic = before_snapshot.get("basic_info") if isinstance(before_snapshot.get("basic_info"), dict) else {}
    after_basic = after_snapshot.get("basic_info") if isinstance(after_snapshot.get("basic_info"), dict) else {}
    for field, label in basic_info_labels:
        before_value = before_basic.get(field)
        after_value = after_basic.get(field)
        if _has_meaningful_value(after_value) and _value_changed(before_value, after_value):
            basic_lines.append(f"- {label}: {_format_markdown_value(after_value)}")
    if basic_lines:
        lines.extend(["", "## 基础信息回补", *basic_lines])

    company_labels = (
        ("brand_subject_name", "品牌主体名称"),
        ("registered_capital", "注册资本"),
        ("company_intro", "公司简介"),
        ("established_time", "成立时间"),
        ("company_address", "公司地址"),
        ("stock_info", "股权信息"),
        ("store_distribution", "门店分布"),
        ("recent_news", "近期动态"),
        ("development_concept", "发展理念"),
        ("corporate_values", "企业价值观"),
        ("company_mission", "公司使命"),
        ("development_history", "发展历程"),
        ("other_info", "其他公司信息"),
    )
    company_lines: list[str] = []
    before_company = (
        before_snapshot.get("company_profile") if isinstance(before_snapshot.get("company_profile"), dict) else {}
    )
    after_company = after_snapshot.get("company_profile") if isinstance(after_snapshot.get("company_profile"), dict) else {}
    for field, label in company_labels:
        before_value = before_company.get(field)
        after_value = after_company.get(field)
        if _has_meaningful_value(after_value) and _value_changed(before_value, after_value):
            company_lines.append(f"- {label}: {_format_markdown_value(after_value)}")
    if company_lines:
        lines.extend(["", "## 公司信息回补", *company_lines])

    def _append_list_section(
        *,
        section_title: str,
        item_key: str,
        fields: tuple[tuple[str, str], ...],
        before_items: Any,
        after_items: Any,
    ) -> None:
        if not isinstance(after_items, list):
            return
        before_by_key = {
            _normalize_str(item.get(item_key)).lower(): item
            for item in before_items
            if isinstance(before_items, list) and isinstance(item, dict) and _normalize_str(item.get(item_key))
        }
        section_lines: list[str] = []
        for item in after_items:
            if not isinstance(item, dict):
                continue
            item_name = _normalize_optional_str(item.get(item_key))
            if not item_name:
                continue
            before_item = before_by_key.get(item_name.lower(), {})
            changed_lines: list[str] = []
            for field, label in fields:
                before_value = before_item.get(field)
                after_value = item.get(field)
                if _has_meaningful_value(after_value) and _value_changed(before_value, after_value):
                    changed_lines.append(f"- {label}: {_format_markdown_value(after_value)}")
            if changed_lines:
                section_lines.extend(["", f"### {item_name}", *changed_lines])
        if section_lines:
            lines.extend(["", f"## {section_title}", *section_lines])

    _append_list_section(
        section_title="管理团队回补",
        item_key="member_name",
        fields=(
            ("position", "职位"),
            ("profile", "简介"),
            ("introduction_website", "介绍链接"),
            ("other_info", "其他信息"),
        ),
        before_items=before_snapshot.get("management_team"),
        after_items=after_snapshot.get("management_team"),
    )
    _append_list_section(
        section_title="竞品信息回补",
        item_key="name",
        fields=(
            ("competitors_alias", "竞品别名"),
            ("competitors_description", "竞品介绍"),
            ("website", "竞品官网"),
            ("competitors_logo", "竞品 Logo"),
            ("competitive_advantages", "竞品优势"),
            ("differentiated_positioning", "差异化定位"),
            ("comparison_dimensions", "对比维度"),
            ("other_info", "其他信息"),
        ),
        before_items=before_snapshot.get("competitors"),
        after_items=after_snapshot.get("competitors"),
    )

    if len(lines) == 1:
        return []
    return [
        {
            "source_name": f"{brand_name}-天眼查与联网回补.md",
            "subcategory": "external_enrichment",
            "source_role": "external_enrichment",
            "markdown_text": "\n".join(lines).strip(),
        }
    ]


def _load_content_json(raw: Any) -> Any:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    return raw


def _brand_value(brand: dict[str, Any], key: str) -> Any:
    return brand.get(key) if isinstance(brand, dict) else None


def _brand_sequence_value(service: KnowledgeBaseService, brand: dict[str, Any], key: str) -> list[str]:
    return _normalize_sequence_value(_brand_value(brand, key))


def _brand_multi_value(brand: dict[str, Any], key: str) -> list[str]:
    value = _brand_value(brand, key)
    if key == "customer_service_hotline":
        return _normalize_customer_service_hotline(value)
    if key in {"positioning", "advantages", "mission", "vision"}:
        return _normalize_brand_text_multi_value(value)
    return _normalize_multi_value(value)


def _prefer_incoming_scalar(incoming: Any, existing: Any) -> Any:
    normalized_incoming = _normalize_optional_str(incoming)
    if normalized_incoming is not None:
        return normalized_incoming
    return existing


def _prefer_incoming_sequence(incoming: Any, existing: Any) -> list[str]:
    if _has_meaningful_value(incoming):
        return _normalize_multi_value(incoming)
    return existing


def _prefer_incoming_hotline_sequence(incoming: Any, existing: Any) -> list[str]:
    if _has_meaningful_value(incoming):
        return normalize_hotline_sequence(incoming)
    return existing


def _build_brand_product_payloads(service: KnowledgeBaseService, products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for product in products:
        payloads.append(
            {
                "name": _normalize_optional_str(product.get("product_name")),
                "product_alias": _normalize_optional_str(product.get("product_alias")),
                "product_description": _normalize_optional_str(product.get("product_description")),
                "product_website": _normalize_optional_str(product.get("product_website")),
                "product_images": _normalize_sequence_value(product.get("product_images_json")),
                "price_info": _normalize_optional_str(product.get("price_info")),
                "coverage_regions": _normalize_sequence_value(product.get("coverage_regions_json")),
                "product_advantages": _normalize_optional_str(product.get("product_advantages")),
                "target_scenarios": _normalize_optional_str(product.get("target_scenarios")),
                "service_standard": _normalize_optional_str(product.get("service_standard")),
                "service_process": _normalize_optional_str(product.get("service_process")),
                "cases_and_reputation": _normalize_optional_str(product.get("cases_and_reputation")),
                "certification_info": _normalize_optional_str(product.get("certification_info")),
                "core_technology": _normalize_optional_str(product.get("core_technology")),
            }
        )
    return payloads


def _load_requested_products(task_payload: Any) -> list[dict[str, Any]]:
    if not isinstance(task_payload, dict):
        return []
    raw_products = task_payload.get("requested_products")
    if not isinstance(raw_products, list):
        return []
    requested_products: list[dict[str, Any]] = []
    for item in raw_products:
        if not isinstance(item, dict):
            continue
        name = _normalize_optional_str(item.get("product_name") or item.get("name"))
        if not name:
            continue
        requested_products.append(
            {
                "name": name,
                "product_alias": _normalize_optional_str(item.get("product_alias")),
                "product_description": _normalize_optional_str(item.get("product_description")),
                "product_website": _normalize_optional_str(item.get("product_website") or item.get("product_link")),
                "product_images": [
                    str(image).strip()
                    for image in (item.get("product_images") or [])
                    if str(image).strip()
                ],
                "price_info": _normalize_optional_str(item.get("price_info")),
                "coverage_regions": [
                    str(region).strip()
                    for region in (item.get("coverage_regions") or [])
                    if str(region).strip()
                ],
                "product_advantages": _normalize_optional_str(item.get("product_advantages")),
                "target_scenarios": _normalize_optional_str(item.get("target_scenarios")),
                "service_standard": _normalize_optional_str(item.get("service_standard")),
                "service_process": _normalize_optional_str(item.get("service_process")),
                "cases_and_reputation": _normalize_optional_str(item.get("cases_and_reputation")),
                "certification_info": _normalize_optional_str(item.get("certification_info")),
                "core_technology": _normalize_optional_str(item.get("core_technology")),
            }
        )
    return requested_products


def _load_requested_competitors(task_payload: Any) -> list[dict[str, Any]]:
    if not isinstance(task_payload, dict):
        return []
    raw_competitors = task_payload.get("requested_competitors")
    if not isinstance(raw_competitors, list):
        return []
    requested_competitors: list[dict[str, Any]] = []
    for item in raw_competitors:
        if not isinstance(item, dict):
            continue
        name = _normalize_optional_str(item.get("name"))
        if not name:
            continue
        requested_competitors.append(
            {
                "name": name,
                "website": _normalize_optional_str(item.get("website")),
            }
        )
    return requested_competitors


def _build_requested_product_keys(requested_products: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for product in requested_products:
        for field in ("name", "product_alias"):
            value = _normalize_str(product.get(field))
            if value:
                keys.add(value.lower())
    return keys


def _build_requested_competitor_keys(requested_competitors: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for competitor in requested_competitors:
        for field in ("name", "website"):
            value = _normalize_str(competitor.get(field))
            if value:
                keys.add(value.lower())
    return keys


def _filter_products_to_requested(
    products: list[dict[str, Any]],
    requested_products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not requested_products:
        return []
    requested_keys = _build_requested_product_keys(requested_products)
    filtered_products: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for product in products:
        if not isinstance(product, dict):
            continue
        candidate_keys = {
            _normalize_str(product.get("name")).lower(),
            _normalize_str(product.get("product_alias")).lower(),
        }
        candidate_keys.discard("")
        if not candidate_keys.intersection(requested_keys):
            continue
        product_name = _normalize_str(product.get("name")).lower()
        if product_name and product_name in seen_names:
            continue
        if product_name:
            seen_names.add(product_name)
        filtered_products.append(dict(product))
    return filtered_products


def _filter_existing_products_to_requested(
    service: KnowledgeBaseService,
    existing_products: list[dict[str, Any]],
    requested_products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not requested_products:
        return []
    requested_keys = _build_requested_product_keys(requested_products)
    filtered_products: list[dict[str, Any]] = []
    for product in existing_products:
        payload = _build_brand_product_payloads(service, [product])[0]
        candidate_keys = {
            _normalize_str(payload.get("name")).lower(),
            _normalize_str(payload.get("product_alias")).lower(),
        }
        candidate_keys.discard("")
        if candidate_keys.intersection(requested_keys):
            filtered_products.append(product)
    return filtered_products


def _merge_requested_products_with_extracted(
    requested_products: list[dict[str, Any]],
    extracted_products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged_products = [dict(product) for product in requested_products]
    extracted_by_key: dict[str, dict[str, Any]] = {}
    for product in extracted_products:
        if not isinstance(product, dict):
            continue
        for field in ("name", "product_alias"):
            value = _normalize_str(product.get(field))
            if value:
                extracted_by_key.setdefault(value.lower(), product)

    for product in merged_products:
        matched = None
        for field in ("name", "product_alias"):
            value = _normalize_str(product.get(field))
            if value and value.lower() in extracted_by_key:
                matched = extracted_by_key[value.lower()]
                break
        if not matched:
            continue
        for field in (
            "product_alias",
            "product_description",
            "product_website",
            "price_info",
            "product_advantages",
            "target_scenarios",
            "service_standard",
            "service_process",
            "cases_and_reputation",
            "certification_info",
            "core_technology",
        ):
            product[field] = matched.get(field) or product.get(field)
        if not product.get("product_images") and matched.get("product_images"):
            product["product_images"] = list(matched["product_images"])
        if not product.get("coverage_regions") and matched.get("coverage_regions"):
            product["coverage_regions"] = list(matched["coverage_regions"])
    return merged_products


def _filter_competitors_to_requested(
    competitors: list[dict[str, Any]],
    requested_competitors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not requested_competitors:
        return []
    requested_keys = _build_requested_competitor_keys(requested_competitors)
    filtered_competitors: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for competitor in competitors:
        if not isinstance(competitor, dict):
            continue
        candidate_keys = {
            _normalize_str(competitor.get("name")).lower(),
            _normalize_str(competitor.get("website")).lower(),
        }
        candidate_keys.discard("")
        if not candidate_keys.intersection(requested_keys):
            continue
        competitor_name = _normalize_str(competitor.get("name")).lower()
        if competitor_name and competitor_name in seen_names:
            continue
        if competitor_name:
            seen_names.add(competitor_name)
        filtered_competitors.append(dict(competitor))
    return filtered_competitors


def _normalize_requested_competitor_seed(competitor: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": _normalize_optional_str(competitor.get("name")),
        "competitors_alias": "",
        "competitors_description": "",
        "website": _normalize_optional_str(competitor.get("website")),
        "competitors_logo": "",
        "competitive_advantages": "",
        "differentiated_positioning": "",
        "comparison_dimensions": "",
        "source_section": "upload_request",
    }


def _merge_requested_competitors_with_extracted(
    requested_competitors: list[dict[str, Any]],
    extracted_competitors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    index_by_key: dict[str, int] = {}

    def _candidate_keys(item: dict[str, Any]) -> set[str]:
        keys = {
            _normalize_str(item.get("name")).lower(),
            _normalize_str(item.get("website")).lower(),
        }
        keys.discard("")
        return keys

    def _add_or_merge(item: dict[str, Any]) -> None:
        if not isinstance(item, dict):
            return
        keys = _candidate_keys(item)
        if not keys:
            return
        existing_index = next((index_by_key[key] for key in keys if key in index_by_key), None)
        if existing_index is None:
            merged.append(dict(item))
            new_index = len(merged) - 1
            for key in keys:
                index_by_key[key] = new_index
            return

        existing = merged[existing_index]
        for field, value in item.items():
            if field in {
                "competitors_description",
                "competitive_advantages",
                "differentiated_positioning",
                "comparison_dimensions",
            }:
                existing[field] = _merge_texts(existing.get(field), value)
            else:
                existing[field] = _merge_optional_string(existing.get(field), value)
        for key in _candidate_keys(existing):
            index_by_key[key] = existing_index

    for competitor in requested_competitors:
        seed = _normalize_requested_competitor_seed(competitor)
        if seed.get("name"):
            _add_or_merge(seed)
    for competitor in extracted_competitors:
        _add_or_merge(competitor)
    return merged


def _apply_extracted_basic_info_to_brand(
    service: KnowledgeBaseService,
    *,
    brand: dict[str, Any],
    extracted_basic_info: dict[str, Any],
    company_profile: dict[str, Any] | None = None,
    knowledge_revision: str | None = None,
) -> None:
    company_profile_payload = company_profile or {}
    target_regions = _brand_sequence_value(service, brand, "target_regions_json")
    existing_customer_service_hotline = _brand_multi_value(brand, "customer_service_hotline")
    existing_positioning = _brand_multi_value(brand, "positioning")
    existing_advantages = _brand_multi_value(brand, "advantages")
    existing_mission = _brand_multi_value(brand, "mission")
    existing_vision = _brand_multi_value(brand, "vision")
    incoming_intro = extracted_basic_info.get("intro") or company_profile_payload.get("company_intro")
    incoming_brand_enterprise_entity = (
        extracted_basic_info.get("brand_enterprise_entity")
        or company_profile_payload.get("brand_subject_name")
    )
    incoming_business_license_image_path = (
        extracted_basic_info.get("business_license_image_path")
        or company_profile_payload.get("business_license_image_path")
    )
    incoming_other_info = _normalize_brand_other_info_scalar(extracted_basic_info.get("other_info"))
    service._brands.upsert_brand(
        brand_code=_normalize_optional_str(_brand_value(brand, "brand_code")),
        brand_name=_normalize_str(_brand_value(brand, "brand_name")),
        brand_alias=_normalize_optional_str(_brand_value(brand, "brand_alias")) or extracted_basic_info.get("brand_alias"),
        website=_serialize_websites(
            _merge_website_lists(
                _brand_value(brand, "website"),
                extracted_basic_info.get("website"),
            )
        ),
        customer_service_hotline=_prefer_incoming_hotline_sequence(
            extracted_basic_info.get("customer_service_hotline"),
            existing_customer_service_hotline,
        ),
        official_wechat_account=_prefer_incoming_scalar(
            extracted_basic_info.get("official_wechat_account"),
            _normalize_optional_str(_brand_value(brand, "official_wechat_account")),
        ),
        intro=_normalize_optional_str(_brand_value(brand, "intro")) or incoming_intro,
        email=_prefer_incoming_scalar(
            extracted_basic_info.get("email"),
            _normalize_optional_str(_brand_value(brand, "email")),
        ),
        brand_enterprise_entity=_prefer_incoming_scalar(
            incoming_brand_enterprise_entity,
            _normalize_optional_str(_brand_value(brand, "brand_enterprise_entity")),
        ),
        business_license_image_path=_prefer_incoming_scalar(
            incoming_business_license_image_path,
            _normalize_optional_str(_brand_value(brand, "business_license_image_path")),
        ),
        industry_id=_normalize_optional_int(_brand_value(brand, "industry_id"))
        or _normalize_optional_int(extracted_basic_info.get("industry_id")),
        knowledge_revision=knowledge_revision,
        brand_logo=_normalize_optional_str(_brand_value(brand, "brand_logo")) or extracted_basic_info.get("brand_logo"),
        english_name=_prefer_incoming_scalar(
            extracted_basic_info.get("english_name"),
            _normalize_optional_str(_brand_value(brand, "english_name")),
        ),
        positioning=_prefer_incoming_sequence(extracted_basic_info.get("positioning"), existing_positioning),
        advantages=_prefer_incoming_sequence(extracted_basic_info.get("advantages"), existing_advantages),
        mission=_prefer_incoming_sequence(extracted_basic_info.get("mission"), existing_mission),
        vision=_prefer_incoming_sequence(extracted_basic_info.get("vision"), existing_vision),
        target_regions=_prefer_incoming_sequence(extracted_basic_info.get("target_regions"), target_regions),
        other_info=_prefer_incoming_scalar(
            incoming_other_info,
            _normalize_brand_other_info_scalar(_brand_value(brand, "other_info")),
        ),
        competitors=None,
    )


def _apply_extracted_products_to_brand_products(
    service: KnowledgeBaseService,
    *,
    brand_id: int,
    brand_name: str,
    existing_products: list[dict[str, Any]],
    extracted_products: list[dict[str, Any]],
    allow_new_products: bool = True,
) -> None:
    if not extracted_products:
        return
    merged_products = _build_brand_product_payloads(service, existing_products)
    products_by_name = {
        _normalize_str(product.get("name")).lower(): product
        for product in merged_products
        if _normalize_str(product.get("name"))
    }
    for extracted in extracted_products:
        name = _normalize_str(extracted.get("name"))
        key = name.lower()
        if key and key in products_by_name:
            existing = products_by_name[key]
            for field in (
                "product_alias",
                "product_description",
                "product_website",
                "price_info",
                "product_advantages",
                "target_scenarios",
                "service_standard",
                "service_process",
                "cases_and_reputation",
                "certification_info",
                "core_technology",
            ):
                existing[field] = existing.get(field) or extracted.get(field)
            if not existing.get("product_images") and extracted.get("product_images"):
                existing["product_images"] = list(extracted["product_images"])
            if not existing.get("coverage_regions") and extracted.get("coverage_regions"):
                existing["coverage_regions"] = list(extracted["coverage_regions"])
            if not existing.get("name"):
                existing["name"] = name
        elif allow_new_products:
            merged_products.append(dict(extracted))
            if key:
                products_by_name[key] = merged_products[-1]

    service._brand_products.upsert_brand_products(
        brand_id=brand_id,
        brand_name=brand_name,
        products=[
            {
                "product_name": product.get("name"),
                "product_alias": product.get("product_alias"),
                "product_description": product.get("product_description"),
                "product_website": product.get("product_website"),
                "product_images": product.get("product_images") or [],
                "price_info": product.get("price_info"),
                "coverage_regions": product.get("coverage_regions") or [],
                "product_advantages": product.get("product_advantages"),
                "target_scenarios": product.get("target_scenarios"),
                "service_standard": product.get("service_standard"),
                "service_process": product.get("service_process"),
                "cases_and_reputation": product.get("cases_and_reputation"),
                "certification_info": product.get("certification_info"),
                "core_technology": product.get("core_technology"),
            }
            for product in merged_products
            if _normalize_str(product.get("name"))
        ],
    )


def _build_basic_info_from_brand(service: KnowledgeBaseService, brand: dict[str, Any], extracted_basic_info: dict[str, Any]) -> dict[str, Any]:
    return {
        "brand_name": _normalize_optional_str(_brand_value(brand, "brand_name")) or extracted_basic_info.get("brand_name"),
        "brand_alias": _normalize_optional_str(_brand_value(brand, "brand_alias")) or extracted_basic_info.get("brand_alias"),
        "english_name": _normalize_optional_str(_brand_value(brand, "english_name")) or extracted_basic_info.get("english_name"),
        "industry_id": _normalize_optional_str(_brand_value(brand, "industry_id")) or extracted_basic_info.get("industry_id"),
        "brand_logo": _normalize_optional_str(_brand_value(brand, "brand_logo")) or extracted_basic_info.get("brand_logo"),
        "website": _merge_website_lists(
            _brand_value(brand, "website"),
            extracted_basic_info.get("website"),
        ),
        "customer_service_hotline": (
            _brand_multi_value(brand, "customer_service_hotline")
            or extracted_basic_info.get("customer_service_hotline")
            or []
        ),
        "official_wechat_account": _normalize_optional_str(_brand_value(brand, "official_wechat_account"))
        or extracted_basic_info.get("official_wechat_account"),
        "intro": _normalize_optional_str(_brand_value(brand, "intro")) or extracted_basic_info.get("intro"),
        "email": _normalize_optional_str(_brand_value(brand, "email")) or extracted_basic_info.get("email"),
        "brand_enterprise_entity": _normalize_optional_str(_brand_value(brand, "brand_enterprise_entity"))
        or extracted_basic_info.get("brand_enterprise_entity"),
        "business_license_image_path": _normalize_optional_str(_brand_value(brand, "business_license_image_path"))
        or extracted_basic_info.get("business_license_image_path"),
        "positioning": _brand_multi_value(brand, "positioning") or extracted_basic_info.get("positioning") or [],
        "advantages": _brand_multi_value(brand, "advantages") or extracted_basic_info.get("advantages") or [],
        "mission": _brand_multi_value(brand, "mission") or extracted_basic_info.get("mission") or [],
        "vision": _brand_multi_value(brand, "vision") or extracted_basic_info.get("vision") or [],
        "target_regions": _brand_sequence_value(service, brand, "target_regions_json") or extracted_basic_info.get("target_regions") or [],
        "other_info": _normalize_optional_str(_brand_value(brand, "other_info")) or extracted_basic_info.get("other_info"),
    }


def _build_products_from_brand_products(
    service: KnowledgeBaseService,
    existing_products: list[dict[str, Any]],
    extracted_products: list[dict[str, Any]],
    *,
    allow_new_products: bool = True,
) -> list[dict[str, Any]]:
    extracted_by_name = {
        _normalize_str(product.get("name")).lower(): product
        for product in extracted_products
        if _normalize_str(product.get("name"))
    }
    merged_products = _build_brand_product_payloads(service, existing_products)
    for product in merged_products:
        name = _normalize_str(product.get("name"))
        extracted = extracted_by_name.get(name.lower()) if name else None
        if not extracted:
            continue
        for field in (
            "product_alias",
            "product_description",
            "product_website",
        ):
            product[field] = product.get(field) or extracted.get(field)
        if not product.get("product_images") and extracted.get("product_images"):
            product["product_images"] = list(extracted["product_images"])
        if not product.get("coverage_regions") and extracted.get("coverage_regions"):
            product["coverage_regions"] = list(extracted["coverage_regions"])

        # base_info 优先使用 brand_products；knowledge 优先使用 LLM，缺失时回退到 brand_products
        for field in (
            "price_info",
            "product_advantages",
            "target_scenarios",
            "service_standard",
            "service_process",
            "cases_and_reputation",
            "certification_info",
            "core_technology",
        ):
            product[field] = extracted.get(field) or product.get(field)

    existing_names = { _normalize_str(product.get("name")).lower() for product in merged_products if _normalize_str(product.get("name")) }
    if allow_new_products:
        for extracted in extracted_products:
            name = _normalize_str(extracted.get("name"))
            if name and name.lower() not in existing_names:
                merged_products.append(dict(extracted))
    return merged_products


def _build_whitelist_products_for_snapshot(
    service: KnowledgeBaseService,
    *,
    existing_products: list[dict[str, Any]],
    extracted_products: list[dict[str, Any]],
    requested_products: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    if requested_products is not None:
        if not requested_products:
            return []
        filtered_requested_products = _merge_requested_products_with_extracted(
            requested_products,
            _filter_products_to_requested(extracted_products, requested_products),
        )
        return _build_products_from_brand_products(
            service,
            _filter_existing_products_to_requested(service, existing_products, filtered_requested_products),
            filtered_requested_products,
            allow_new_products=True,
        )
    if not existing_products:
        return []
    return _build_products_from_brand_products(
        service,
        existing_products,
        extracted_products,
        allow_new_products=False,
    )


async def build_brand_knowledge_snapshot_from_markdown(
    service: Any,
    *,
    brand_name: str,
    markdown_text: str,
    source_name: str,
    attachments: list[dict[str, Any]] | None = None,
    requested_products: list[dict[str, Any]] | None = None,
    requested_competitors: list[dict[str, Any]] | None = None,
    enable_tianyancha: bool = True,
) -> dict[str, Any]:
    normalized_brand_name = _normalize_str(brand_name)
    if not normalized_brand_name:
        raise ValueError("brand_name 不能为空")
    normalized_markdown = str(markdown_text or "").strip()
    if not normalized_markdown:
        raise ValueError("markdown_text 不能为空")

    brand = service._brands.get_brand_by_name(normalized_brand_name)
    if not brand or brand.get("id") is None:
        raise ValueError(f"品牌不存在 brand_name={normalized_brand_name}")
    brand_id = int(brand["id"])
    brand_code = _normalize_str(brand.get("brand_code"))
    if not brand_code:
        raise ValueError(f"品牌缺少 brand_code brand_name={normalized_brand_name}")
    existing_products = service._brand_products.get_brand_products(brand_id=brand_id)
    existing_rows = service._brand_knowledge.get_all_brand_knowledge_json(brand_id=brand_id)
    existing_attachment_products = _load_attachment_products_from_rows(existing_rows)

    extracted_raw = await extract_brand_knowledge_from_markdown(
        normalized_markdown,
        brand_name=normalized_brand_name,
        source_name=source_name,
        subcategory=None,
        settings=service._settings,
    )
    extracted = _normalize_extraction_result(extracted_raw, source_file=source_name)
    extracted["source_file"] = source_name

    aggregated = _build_empty_knowledge()
    aggregated = _merge_brand_knowledge(base=aggregated, extracted=extracted)
    aggregated["attachments"] = _normalize_snapshot_attachments(attachments)

    base_snapshot = _sanitize_final_payload(aggregated)
    extracted_products = aggregated["products"]
    merged_attachment_products = _merge_attachment_products(
        existing_attachment_products,
        extracted_products,
    )
    base_snapshot["products"] = _build_whitelist_products_for_snapshot(
        service,
        existing_products=existing_products,
        extracted_products=extracted_products,
        requested_products=requested_products,
    )
    base_snapshot["other_info"] = _merge_other_info_with_attachment_products(
        base_snapshot.get("other_info"),
        merged_attachment_products,
    )
    base_snapshot["other_info"] = _filter_other_info_entries(
        base_snapshot.get("other_info"),
        snapshot=base_snapshot,
    )
    base_snapshot["attachment_products"] = merged_attachment_products

    extracted_competitors = aggregated["competitors"]
    if requested_competitors is not None:
        extracted_competitors = _filter_competitors_to_requested(extracted_competitors, requested_competitors)
        extracted_competitors = _merge_requested_competitors_with_extracted(
            requested_competitors,
            extracted_competitors,
        )
    base_snapshot["competitors"] = extracted_competitors
    base_snapshot = await _summarize_competitor_sections_into_snapshot(
        base_snapshot,
        brand_name=normalized_brand_name,
        settings=service._settings,
    )

    (
        enriched_basic_info,
        enriched_company_profile,
        enriched_management_team,
        enriched_competitors,
    ) = await enrich_brand_from_tianyancha(
        service,
        brand=brand,
        extracted_basic_info=base_snapshot["basic_info"],
        company_profile=base_snapshot["company_profile"],
        management_team=base_snapshot["management_team"],
        competitors=base_snapshot["competitors"],
        enable_tianyancha=enable_tianyancha,
    )
    final_snapshot = dict(base_snapshot)
    final_snapshot["basic_info"] = enriched_basic_info
    final_snapshot["company_profile"] = enriched_company_profile
    final_snapshot["management_team"] = enriched_management_team
    final_snapshot["competitors"] = enriched_competitors
    supplemental_markdown_sources = _build_external_enrichment_markdown_sources(
        brand_name=normalized_brand_name,
        before_snapshot=base_snapshot,
        after_snapshot=final_snapshot,
    )

    return {
        "brand": brand,
        "brand_id": brand_id,
        "existing_products": existing_products,
        "snapshot": final_snapshot,
        "supplemental_markdown_sources": supplemental_markdown_sources,
    }


async def extract_brand_knowledge_snapshot_from_markdown(
    *,
    brand_name: str,
    markdown_text: str,
    source_name: str,
    settings: Any,
) -> dict[str, Any]:
    normalized_brand_name = _normalize_str(brand_name)
    if not normalized_brand_name:
        raise ValueError("brand_name 不能为空")
    normalized_markdown = str(markdown_text or "").strip()
    if not normalized_markdown:
        raise ValueError("markdown_text 不能为空")

    extracted_raw = await extract_brand_knowledge_from_markdown(
        normalized_markdown,
        brand_name=normalized_brand_name,
        source_name=source_name,
        subcategory=None,
        settings=settings,
    )
    extracted = _normalize_extraction_result(extracted_raw, source_file=source_name)
    extracted["source_file"] = source_name

    aggregated = _build_empty_knowledge()
    aggregated = _merge_brand_knowledge(base=aggregated, extracted=extracted)
    aggregated["attachments"] = []
    snapshot = _sanitize_final_payload(aggregated)
    attachment_products = _merge_attachment_products([], snapshot.get("products"))
    snapshot["products"] = []
    snapshot["other_info"] = _merge_other_info_with_attachment_products(
        snapshot.get("other_info"),
        attachment_products,
    )
    snapshot["other_info"] = _filter_other_info_entries(
        snapshot.get("other_info"),
        snapshot=snapshot,
    )
    snapshot["attachment_products"] = _resolve_attachment_product_reference_descriptions(
        attachment_products,
        markdown_text=normalized_markdown,
    )
    snapshot["competitors"] = normalize_competitors_for_storage(snapshot.get("competitors"))
    snapshot = await _summarize_competitor_sections_into_snapshot(
        snapshot,
        brand_name=normalized_brand_name,
        settings=settings,
    )
    return snapshot


def merge_brand_knowledge_snapshot_fill_empty_only(
    *,
    existing_snapshot: dict[str, Any] | None,
    incoming_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    existing = existing_snapshot if isinstance(existing_snapshot, dict) else {}
    incoming = incoming_snapshot if isinstance(incoming_snapshot, dict) else {}
    merged = _copy_jsonable(existing)

    merged["basic_info"] = _fill_missing_dict(existing.get("basic_info"), incoming.get("basic_info"))
    merged["company_profile"] = _fill_missing_dict(existing.get("company_profile"), incoming.get("company_profile"))

    for section_name, key_fields in _FILL_EMPTY_LIST_KEY_FIELDS.items():
        if section_name == "other_info":
            merged[section_name] = _filter_other_info_entries(_merge_other_info(
                _normalize_other_info(existing.get(section_name)),
                _normalize_other_info(incoming.get(section_name)),
            ), snapshot=merged)
            continue
        merged[section_name] = _merge_existing_list_items_only(
            existing.get(section_name),
            incoming.get(section_name),
            key_fields=key_fields,
        )

    existing_competitors = existing.get("competitors")
    incoming_competitors = incoming.get("competitors")
    if isinstance(existing_competitors, list) and existing_competitors:
        merged["competitors"] = _copy_jsonable(existing_competitors)
    else:
        merged["competitors"] = _copy_jsonable(incoming_competitors or [])

    merged["sensitive_topics"] = _merge_sensitive_topics_fill_empty(
        existing.get("sensitive_topics"),
        incoming.get("sensitive_topics"),
    )

    for knowledge_type in _KNOWLEDGE_TYPES:
        if knowledge_type not in merged:
            merged[knowledge_type] = _copy_jsonable(incoming.get(knowledge_type))
    return merged


def persist_brand_knowledge_snapshot(
    service: Any,
    *,
    brand_name: str,
    snapshot: dict[str, Any],
    source_task_id: str | None = None,
) -> dict[str, Any]:
    normalized_brand_name = _normalize_str(brand_name)
    if not normalized_brand_name:
        raise ValueError("brand_name 不能为空")
    if not isinstance(snapshot, dict):
        raise ValueError("snapshot 必须是对象")

    brand = service._brands.get_brand_by_name(normalized_brand_name)
    if not brand or brand.get("id") is None:
        raise ValueError(f"品牌不存在 brand_name={normalized_brand_name}")
    brand_id = int(brand["id"])
    existing_rows = service._brand_knowledge.get_all_brand_knowledge_json(brand_id=brand_id)
    existing_attachment_products = _load_attachment_products_from_rows(existing_rows)
    existing_brand_products = service._brand_products.get_brand_products(brand_id=brand_id)

    basic_info = snapshot.get("basic_info") if isinstance(snapshot.get("basic_info"), dict) else {}
    company_profile = snapshot.get("company_profile") if isinstance(snapshot.get("company_profile"), dict) else {}
    products = snapshot.get("products") if isinstance(snapshot.get("products"), list) else []
    attachment_products = (
        snapshot.get(_ATTACHMENT_PRODUCTS_KNOWLEDGE_TYPE)
        if isinstance(snapshot.get(_ATTACHMENT_PRODUCTS_KNOWLEDGE_TYPE), list)
        else products
    )
    merged_attachment_products = _merge_attachment_products(
        existing_attachment_products,
        attachment_products,
    )

    _apply_extracted_basic_info_to_brand(
        service,
        brand=brand,
        extracted_basic_info=basic_info,
        company_profile=company_profile,
    )
    if existing_brand_products:
        _apply_extracted_products_to_brand_products(
            service,
            brand_id=brand_id,
            brand_name=normalized_brand_name,
            existing_products=existing_brand_products,
            extracted_products=products,
            allow_new_products=False,
        )

    refreshed_brand = service._brands.get_brand_by_name(normalized_brand_name) or brand
    refreshed_products = service._brand_products.get_brand_products(brand_id=brand_id)
    persisted_snapshot = dict(snapshot)
    persisted_snapshot["basic_info"] = _build_basic_info_from_brand(service, refreshed_brand, basic_info)
    persisted_snapshot["products"] = _build_whitelist_products_for_snapshot(
        service,
        existing_products=refreshed_products,
        extracted_products=products,
        requested_products=None,
    )
    persisted_snapshot["competitors"] = normalize_competitors_for_storage(persisted_snapshot.get("competitors"))
    persisted_snapshot["other_info"] = _merge_other_info_with_attachment_products(
        persisted_snapshot.get("other_info"),
        merged_attachment_products,
    )
    persisted_snapshot["other_info"] = _filter_other_info_entries(
        persisted_snapshot.get("other_info"),
        snapshot=persisted_snapshot,
    )
    persisted_snapshot[_ATTACHMENT_PRODUCTS_KNOWLEDGE_TYPE] = merged_attachment_products
    for knowledge_type in _KNOWLEDGE_TYPES:
        service._brand_knowledge.upsert_brand_knowledge_json(
            brand_id=brand_id,
            knowledge_type=knowledge_type,
            content_json=persisted_snapshot.get(knowledge_type),
            source_task_id=source_task_id,
        )
    service._brand_knowledge.upsert_brand_knowledge_json(
        brand_id=brand_id,
        knowledge_type=_ATTACHMENT_PRODUCTS_KNOWLEDGE_TYPE,
        content_json=merged_attachment_products,
        source_task_id=source_task_id,
    )

    knowledge_revision = build_knowledge_revision(
        brand_code=_normalize_optional_str(_brand_value(refreshed_brand, "brand_code")),
        brand_name=normalized_brand_name,
        current_revision=_normalize_optional_str(_brand_value(refreshed_brand, "knowledge_revision")),
        change_type=KNOWLEDGE_REVISION_CHANGE_ATTACHMENT,
    )
    _apply_extracted_basic_info_to_brand(
        service,
        brand=refreshed_brand,
        extracted_basic_info=basic_info,
        company_profile=company_profile,
        knowledge_revision=knowledge_revision,
    )
    final_brand = service._brands.get_brand_by_name(normalized_brand_name) or refreshed_brand
    persisted_snapshot["basic_info"] = _build_basic_info_from_brand(service, final_brand, basic_info)

    return {
        "brand": final_brand,
        "brand_id": brand_id,
        "knowledge_revision": knowledge_revision,
        "snapshot": persisted_snapshot,
    }


async def extract_brand_knowledge_for_task(
    service: KnowledgeBaseService,
    *,
    task_id: str,
) -> dict[str, Any]:
    task = service._upload_tasks.get_upload_task(task_id)
    if not task:
        raise ValueError(f"上传任务不存在 task_id={task_id}")

    metadata = parse_metadata_json(task.get("metadata_json"))
    brand_name = _normalize_str(metadata.get("category"))
    if not brand_name:
        raise ValueError("上传任务缺少品牌 category")

    brand = service._brands.get_brand_by_name(brand_name)
    if not brand or brand.get("id") is None:
        raise ValueError(f"品牌不存在 brand_name={brand_name}")
    brand_id = int(brand["id"])
    brand_code = _normalize_str(brand.get("brand_code"))
    if not brand_code:
        raise ValueError(f"品牌缺少 brand_code brand_name={brand_name}")
    existing_products = service._brand_products.get_brand_products(brand_id=brand_id)

    existing_rows = service._brand_knowledge.get_all_brand_knowledge_json(brand_id=brand_id)
    existing_by_type = {
        str(row.get("knowledge_type") or ""): row
        for row in existing_rows
        if str(row.get("source_task_id") or "") == task_id
    }
    if all(knowledge_type in existing_by_type for knowledge_type in _KNOWLEDGE_TYPES):
        return {
            knowledge_type: _load_content_json(existing_by_type[knowledge_type].get("content_json"))
            for knowledge_type in _KNOWLEDGE_TYPES
        }

    files = service._upload_tasks.get_upload_task_files(task_id)
    task_payload = metadata.get("_task_payload")
    file_metadata_by_index: dict[str, Any] = {}
    if isinstance(task_payload, dict):
        raw_file_metadata_by_index = task_payload.get("file_metadata_by_index")
        if isinstance(raw_file_metadata_by_index, dict):
            file_metadata_by_index = raw_file_metadata_by_index
    requested_products = _load_requested_products(task_payload)
    requested_competitors = _load_requested_competitors(task_payload)
    existing_attachment_products = _load_attachment_products_from_rows(existing_rows)

    aggregated = _build_empty_knowledge()
    attachments: list[dict[str, Any]] = []
    extracted_attachment_products: list[dict[str, Any]] = []

    for file_item in files:
        if str(file_item.get("status") or "") != "success":
            continue
        file_overrides = file_metadata_by_index.get(str(file_item.get("file_index")), {})
        if not isinstance(file_overrides, dict) or not _normalize_str(file_overrides.get("source_url")):
            continue
        document_id = _normalize_str(file_item.get("document_id"))
        if not document_id:
            continue
        full_text = service.get_full_text(document_id)
        attachment_entry = _normalize_attachment_entry(file_item, full_text=full_text)
        attachment_entry["source_url"] = _normalize_optional_str(file_overrides.get("source_url"))
        attachment_entry["subcategory"] = _normalize_optional_str(file_overrides.get("subcategory"))
        attachments.append(attachment_entry)
        if not full_text:
            continue

        doc_info = service._get_document_info(document_id)
        doc_metadata = parse_metadata_json(doc_info.get("metadata_json")) if doc_info else {}
        source_name = _normalize_str(file_item.get("original_filename")) or document_id
        extracted_raw = await extract_brand_knowledge_from_markdown(
            full_text,
            brand_name=brand_name,
            source_name=source_name,
            subcategory=_normalize_optional_str(doc_metadata.get("subcategory")),
            settings=service._settings,
        )
        extracted = _normalize_extraction_result(extracted_raw, source_file=source_name)
        extracted["other_info"] = _merge_markdown_sections_into_other_info(
            extracted.get("other_info"),
            markdown_text=full_text,
            snapshot=extracted,
        )
        extracted_attachment_products = _merge_attachment_products(
            extracted_attachment_products,
            extracted.get("products"),
        )
        extracted["products"] = _filter_products_to_requested(extracted["products"], requested_products)
        extracted["source_file"] = source_name
        aggregated = _merge_brand_knowledge(base=aggregated, extracted=extracted)

    aggregated["attachments"] = attachments
    final_payload = _sanitize_final_payload(aggregated)
    merged_attachment_products = _merge_attachment_products(
        existing_attachment_products,
        extracted_attachment_products,
    )
    final_payload["other_info"] = _merge_other_info_with_attachment_products(
        final_payload.get("other_info"),
        merged_attachment_products,
    )
    final_payload["products"] = _filter_products_to_requested(final_payload["products"], requested_products)
    final_payload["competitors"] = _merge_requested_competitors_with_extracted(
        requested_competitors,
        final_payload["competitors"],
    )
    final_payload = await _summarize_competitor_sections_into_snapshot(
        final_payload,
        brand_name=brand_name,
        settings=service._settings,
    )
    (
        enriched_basic_info,
        enriched_company_profile,
        enriched_management_team,
        enriched_competitors,
    ) = await enrich_brand_from_tianyancha(
        service,
        brand=brand,
        extracted_basic_info=final_payload["basic_info"],
        company_profile=final_payload["company_profile"],
        management_team=final_payload["management_team"],
        competitors=final_payload["competitors"],
    )
    final_payload["basic_info"] = enriched_basic_info
    final_payload["company_profile"] = enriched_company_profile
    final_payload["management_team"] = enriched_management_team
    final_payload["competitors"] = enriched_competitors

    _apply_extracted_basic_info_to_brand(
        service,
        brand=brand,
        extracted_basic_info=final_payload["basic_info"],
        company_profile=final_payload["company_profile"],
    )
    if requested_products:
        requested_products = _merge_requested_products_with_extracted(
            requested_products,
            final_payload["products"],
        )
        _apply_extracted_products_to_brand_products(
            service,
            brand_id=brand_id,
            brand_name=brand_name,
            existing_products=_filter_existing_products_to_requested(service, existing_products, requested_products),
            extracted_products=requested_products,
        )
    refreshed_brand = service._brands.get_brand_by_name(brand_name) or brand
    refreshed_products = service._brand_products.get_brand_products(brand_id=brand_id) if requested_products else []
    final_payload["basic_info"] = _build_basic_info_from_brand(service, refreshed_brand, final_payload["basic_info"])
    if requested_products:
        final_payload["products"] = _build_products_from_brand_products(
            service,
            _filter_existing_products_to_requested(service, refreshed_products, requested_products),
            requested_products,
        )
    else:
        final_payload["products"] = []
    final_payload["other_info"] = _filter_other_info_entries(
        final_payload.get("other_info"),
        snapshot=final_payload,
    )
    final_payload["other_info"] = [
        item
        for item in final_payload["other_info"]
        if _normalize_str(item.get("title")) != _ATTACHMENT_PRODUCTS_OTHER_INFO_TITLE
    ]
    for knowledge_type in _KNOWLEDGE_TYPES:
        service._brand_knowledge.upsert_brand_knowledge_json(
            brand_id=brand_id,
            knowledge_type=knowledge_type,
            content_json=final_payload[knowledge_type],
            source_task_id=task_id,
        )
    service._brand_knowledge.upsert_brand_knowledge_json(
        brand_id=brand_id,
        knowledge_type=_ATTACHMENT_PRODUCTS_KNOWLEDGE_TYPE,
        content_json=merged_attachment_products,
        source_task_id=task_id,
    )

    knowledge_revision = build_knowledge_revision(
        brand_code=_normalize_optional_str(_brand_value(refreshed_brand, "brand_code")),
        brand_name=brand_name,
        current_revision=_normalize_optional_str(_brand_value(refreshed_brand, "knowledge_revision")),
        change_type=KNOWLEDGE_REVISION_CHANGE_ATTACHMENT,
    )
    _apply_extracted_basic_info_to_brand(
        service,
        brand=refreshed_brand,
        extracted_basic_info=enriched_basic_info,
        company_profile=final_payload["company_profile"],
        knowledge_revision=knowledge_revision,
    )

    logger.info(
        "Brand knowledge extracted task_id=%s brand_id=%s attachment_count=%s",
        task_id,
        brand_id,
        len(attachments),
    )
    return final_payload
