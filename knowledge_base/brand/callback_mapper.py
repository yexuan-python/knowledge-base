from __future__ import annotations

import json
import re
import unicodedata
from typing import TYPE_CHECKING, Any

from knowledge_base.brand.competitor_schema import normalize_competitors_for_storage
from knowledge_base.brand.knowledge_extraction import (
    _ATTACHMENT_PRODUCTS_OTHER_INFO_TITLE,
    _filter_other_info_entries,
)
from knowledge_base.shared.utils import (
    is_effective_empty_sequence,
    normalize_hotline_sequence,
    normalize_http_url_sequence,
    normalize_line_delimited_text_sequence,
    normalize_text_sequence,
    parse_jsonish_literal,
    parse_metadata_json,
)

if TYPE_CHECKING:
    from knowledge_base.service import KnowledgeBaseService


def _required_str(value: Any) -> str:
    text = str(value).strip() if value is not None else ""
    return text or " "


def _optional_str(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _parse_sequence_literal(value: str) -> Any:
    return parse_jsonish_literal(value)


def _normalize_sequence_value(value: Any) -> list[str]:
    return normalize_text_sequence(value)


def _is_empty_array_marker(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return is_effective_empty_sequence(value)


def _normalize_sequence_items(value: Any) -> list[Any]:
    if _is_empty_array_marker(value):
        return []
    if isinstance(value, str):
        normalized = value.strip()
        parsed = _parse_sequence_literal(normalized)
        if isinstance(parsed, (list, tuple, set)):
            normalized_items: list[Any] = []
            for item in parsed:
                normalized_items.extend(_normalize_sequence_items(item))
            return normalized_items
        if isinstance(parsed, dict):
            return [parsed]
        if parsed is not None and parsed != normalized:
            return _normalize_sequence_items(parsed)
        return [normalized]
    if isinstance(value, (list, tuple, set)):
        normalized_items: list[Any] = []
        for item in value:
            normalized_items.extend(_normalize_sequence_items(item))
        return normalized_items
    if isinstance(value, dict):
        return [value]
    return [value]


def _normalize_callback_list(value: Any) -> list[Any]:
    normalized_items: list[Any] = []
    seen: set[str] = set()
    for item in _normalize_sequence_items(value):
        if _is_empty_array_marker(item):
            continue
        if isinstance(item, dict):
            normalized_item = {
                str(key).strip(): item_value
                for key, item_value in item.items()
                if str(key).strip() and not _is_empty_array_marker(item_value)
            }
            if not normalized_item:
                continue
        else:
            normalized_text = _optional_str(item)
            if not normalized_text:
                continue
            normalized_item = normalized_text
        try:
            identity = json.dumps(normalized_item, ensure_ascii=False, sort_keys=True)
        except Exception:
            identity = str(normalized_item)
        if identity in seen:
            continue
        seen.add(identity)
        normalized_items.append(normalized_item)
    return normalized_items


def _normalize_single_or_list(value: Any) -> list[str]:
    return [str(item).strip() for item in _normalize_callback_list(value) if str(item).strip()]


def _merge_normalized_text_lists(*values: Any) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for value in values:
        for item in _normalize_single_or_list(value):
            key = item.casefold()
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
    return merged


def _merge_normalized_website_lists(*values: Any) -> list[str]:
    return normalize_http_url_sequence(list(values))


def _normalize_single_or_line_list(value: Any) -> list[str]:
    return [str(item).strip() for item in normalize_line_delimited_text_sequence(value) if str(item).strip()]


def _normalize_proof_files(value: Any) -> list[dict[str, str]]:
    if isinstance(value, list):
        files: list[dict[str, str]] = []
        for item in value:
            if isinstance(item, dict):
                name = _optional_str(item.get("name"))
                url = _optional_str(item.get("url"))
                if name or url:
                    files.append({"name": name, "url": url})
                    continue
            for normalized in _normalize_sequence_value(item):
                files.append({"name": "", "url": normalized})
        return files
    if isinstance(value, dict):
        name = _optional_str(value.get("name"))
        url = _optional_str(value.get("url"))
        return [{"name": name, "url": url}] if name or url else []

    normalized_items = _normalize_sequence_value(value)
    return [{"name": "", "url": item} for item in normalized_items]


def _build_callback_attachments(service: KnowledgeBaseService, task_id: str) -> list[dict[str, str]]:
    task = service._upload_tasks.get_upload_task(task_id)
    metadata = parse_metadata_json(task.get("metadata_json")) if task else {}
    task_payload = metadata.get("_task_payload") if isinstance(metadata, dict) else None
    file_metadata_by_index: dict[str, Any] = {}
    if isinstance(task_payload, dict):
        raw_file_metadata_by_index = task_payload.get("file_metadata_by_index")
        if isinstance(raw_file_metadata_by_index, dict):
            file_metadata_by_index = raw_file_metadata_by_index

    files = service._upload_tasks.get_upload_task_files(task_id)
    attachments: list[dict[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for file_item in files:
        file_index = str(file_item.get("file_index"))
        file_overrides = file_metadata_by_index.get(file_index, {})
        if not isinstance(file_overrides, dict):
            continue
        source_url = _optional_str(file_overrides.get("source_url"))
        if not source_url:
            continue
        if _optional_str(file_overrides.get("subcategory")):
            continue
        name = _required_str(file_item.get("original_filename"))
        dedupe_key = (name, source_url)
        if dedupe_key in seen_pairs:
            continue
        seen_pairs.add(dedupe_key)
        attachments.append(
            {
                "name": name,
                "url": source_url,
                "type": _optional_str(file_item.get("source_type")),
                "description": "",
            }
        )
    return attachments


def _build_callback_attachments_from_entries(entries: Any) -> list[dict[str, str]]:
    if not isinstance(entries, list):
        return []
    attachments: list[dict[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for item in entries:
        if not isinstance(item, dict):
            continue
        name = _required_str(item.get("name"))
        url = _optional_str(item.get("url") or item.get("source_url"))
        if not url:
            continue
        dedupe_key = (name, url)
        if dedupe_key in seen_pairs:
            continue
        seen_pairs.add(dedupe_key)
        attachments.append(
            {
                "name": name,
                "url": url,
                "type": _optional_str(item.get("type")),
                "description": _optional_str(item.get("description")),
            }
        )
    return attachments


def _merge_sensitive_topic_values(values: list[str]) -> str:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _optional_str(value)
        if not normalized:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return "；".join(deduped)


def _normalize_text_list(value: Any) -> list[str]:
    return [str(item).strip() for item in _normalize_callback_list(value) if str(item).strip()]


def _normalize_customer_service_hotline_list(value: Any) -> list[str]:
    return [str(item).strip() for item in normalize_hotline_sequence(value) if str(item).strip()]


_DISPLAY_MULTI_VALUE_PUNCT_TRANSLATION = str.maketrans(
    {
        "，": ",",
        "；": ";",
        "：": ":",
        "（": "(",
        "）": ")",
        "【": "[",
        "】": "]",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
    }
)


def _normalize_display_multi_value_key(value: Any) -> str:
    text = _optional_str(value)
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.translate(_DISPLAY_MULTI_VALUE_PUNCT_TRANSLATION)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized.casefold()


def _dedupe_display_multi_values(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _optional_str(value)
        if not normalized:
            continue
        dedupe_key = _normalize_display_multi_value_key(normalized)
        if not dedupe_key or dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        deduped.append(normalized)
    return deduped


_ATTACHMENT_POINTER_ONLY_RE = re.compile(r"^(?:详?情?见附件|详见附件|见附件)(?:[。.!！]?|\s*)$")
_PLACEHOLDER_SECTION_SUMMARY_RE = re.compile(
    r"^[\*\s]*销售希望多宣传的(?:六大)?方向[。.!！]?[\*\s]*$"
)
_CALLBACK_OTHER_INFO_EMPTY_SECTION_TITLES = {
    "八、案例、口碑与深度知识",
    "十、视觉资产与安全边界",
}


def _brand_multi_value(
    brand: dict[str, Any],
    basic_info: dict[str, Any],
    key: str,
) -> list[str]:
    normalize_list = _normalize_customer_service_hotline_list if key == "customer_service_hotline" else _normalize_text_list
    normalized = normalize_list(basic_info.get(key))
    if normalized:
        return normalized
    return normalize_list(brand.get(key))


def _brand_multi_value_for_display(
    brand: dict[str, Any],
    basic_info: dict[str, Any],
    key: str,
) -> list[str]:
    return _dedupe_display_multi_values(
        _brand_multi_value(
            brand,
            basic_info,
            key,
        )
    )


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
            normalized_item = int(item) if item.is_integer() else _optional_str(item)
        else:
            normalized_text = _optional_str(item)
            if normalized_text:
                normalized_item = normalized_text
        if normalized_item is None:
            continue
        try:
            import json

            identity = json.dumps(normalized_item, ensure_ascii=False, sort_keys=True)
        except Exception:
            identity = str(normalized_item)
        if identity in seen:
            continue
        seen.add(identity)
        normalized_items.append(normalized_item)
    return normalized_items


def _build_callback_sensitive_topics(extracted: dict[str, Any]) -> dict[str, Any]:
    raw_items = extracted.get("sensitive_topics")
    if isinstance(raw_items, dict):
        return {
            "sensitive_contents": _normalize_text_list(raw_items.get("sensitive_contents")),
            "controversial_events": _normalize_text_list(raw_items.get("controversial_events")),
            "forbidden_words": _normalize_text_list(raw_items.get("forbidden_words")),
            "negative_clarifications": _normalize_text_list(raw_items.get("negative_clarifications")),
            "other_info": _normalize_text_list(raw_items.get("other_info")),
        }
    items = [item for item in raw_items if isinstance(item, dict)] if isinstance(raw_items, list) else []
    if not items:
        return {}
    return {
        "sensitive_contents": _normalize_text_list(
            _merge_sensitive_topic_values([item.get("topic") for item in items])
        ),
        "controversial_events": _normalize_text_list(
            _merge_sensitive_topic_values([item.get("description") for item in items])
        ),
        "forbidden_words": _normalize_text_list(
            _merge_sensitive_topic_values([item.get("forbidden_words") or item.get("forbidden_terms") for item in items])
        ),
        "negative_clarifications": _normalize_text_list(
            _merge_sensitive_topic_values([item.get("history_negative_clarification") for item in items])
        ),
        "other_info": [],
    }


def _build_callback_basic_info(
    brand: dict[str, Any] | None,
    basic_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    brand = brand or {}
    basic_info = basic_info or {}
    callback_other_info_source = basic_info.get("other_info") if "other_info" in basic_info else brand.get("other_info")
    callback_other_info = _normalize_text_list(callback_other_info_source)
    extra_info = {
        "brand_english_name": _optional_str(basic_info.get("english_name") or brand.get("english_name")),
        "official_wechat": _optional_str(
            basic_info.get("official_wechat_account") or brand.get("official_wechat_account")
        ),
        "brand_positioning": _brand_multi_value_for_display(brand, basic_info, "positioning"),
        "brand_advantage": _brand_multi_value_for_display(brand, basic_info, "advantages"),
        "brand_mission": _brand_multi_value_for_display(brand, basic_info, "mission"),
        "brand_vision": _brand_multi_value_for_display(brand, basic_info, "vision"),
        "target_region": _normalize_text_list(basic_info.get("target_regions") or brand.get("target_regions_json")),
    }
    if callback_other_info:
        extra_info["other_info"] = callback_other_info
    return {
        "industry_id": _optional_str(basic_info.get("industry_id") or brand.get("industry_id")),
        "brand_name": _optional_str(basic_info.get("brand_name") or brand.get("brand_name")),
        "brand_alias": _optional_str(basic_info.get("brand_alias") or brand.get("brand_alias")),
        "brand_logo": _optional_str(basic_info.get("brand_logo") or brand.get("brand_logo")),
        "website": _merge_normalized_website_lists(brand.get("website"), basic_info.get("website")),
        "customer_service_hotline": _brand_multi_value(
            brand,
            basic_info,
            "customer_service_hotline",
        ),
        "intro": _optional_str(basic_info.get("intro") or brand.get("intro")),
        "email": _optional_str(basic_info.get("email") or brand.get("email")),
        "enterprise_subject": _optional_str(
            basic_info.get("brand_enterprise_entity") or brand.get("brand_enterprise_entity")
        ),
        "business_license_url": _optional_str(
            basic_info.get("business_license_image_path") or brand.get("business_license_image_path")
        ),
        "extra_info": extra_info,
    }


def _build_callback_company_profile(brand: dict[str, Any] | None, extracted: dict[str, Any]) -> dict[str, Any]:
    brand = brand or {}
    company_profile_raw = extracted.get("company_profile") if isinstance(extracted.get("company_profile"), dict) else {}
    company_addresses = _normalize_single_or_list(company_profile_raw.get("company_address"))
    recent_news = _normalize_single_or_list(company_profile_raw.get("recent_news"))
    development_history = _normalize_single_or_line_list(company_profile_raw.get("development_history"))
    return {
        "subject_info": _optional_str(
            company_profile_raw.get("brand_subject_name") or brand.get("brand_enterprise_entity")
        ),
        "business_license_url": _optional_str(
            company_profile_raw.get("business_license_image_path") or brand.get("business_license_image_path")
        ),
        "stock_info": _optional_str(company_profile_raw.get("stock_info")),
        "company_addresses": company_addresses,
        "company_intro": _optional_str(company_profile_raw.get("company_intro")),
        "founded_at": _optional_str(company_profile_raw.get("established_time")),
        "store_distribution": _normalize_text_list(company_profile_raw.get("store_distribution")),
        "recent_news": recent_news,
        "development_philosophy": _normalize_text_list(company_profile_raw.get("development_concept")),
        "company_values": _normalize_text_list(company_profile_raw.get("corporate_values")),
        "company_mission": _normalize_text_list(company_profile_raw.get("company_mission")),
        "development_history": development_history,
        "other_info": _normalize_text_list(company_profile_raw.get("other_info")),
    }


def _build_callback_management_team(extracted: dict[str, Any]) -> dict[str, Any]:
    members: list[dict[str, Any]] = []
    for item in extracted.get("management_team", []):
        if not isinstance(item, dict):
            continue
        members.append(
            {
                "name": _optional_str(item.get("member_name") or item.get("name")),
                "title": _optional_str(item.get("position") or item.get("title")),
                "bio": _optional_str(item.get("profile") or item.get("bio")),
                "intro_urls": _normalize_single_or_list(item.get("introduction_website") or item.get("intro_urls")),
                "other_info": _normalize_text_list(item.get("other_info")),
            }
        )
    return {"members": members}


def _build_callback_competitors(extracted: dict[str, Any]) -> dict[str, Any]:
    competitors: list[dict[str, Any]] = []
    for item in normalize_competitors_for_storage(extracted.get("competitors", [])):
        competitors.append(
            {
                "name": _optional_str(item.get("name")),
                "aliases": _normalize_single_or_list(item.get("aliases")),
                "introduction": _optional_str(item.get("introduction")),
                "official_websites": _normalize_single_or_list(item.get("official_websites")),
                "logo_urls": _normalize_single_or_list(item.get("logo_urls")),
                "strengths": _normalize_text_list(item.get("strengths")),
                "differentiated_positioning": _normalize_text_list(item.get("differentiated_positioning")),
                "comparison_dimensions": _normalize_text_list(item.get("comparison_dimensions")),
                "other_info": _normalize_text_list(item.get("other_info")),
            }
        )
    return {"competitors": competitors}


def _build_callback_authority_honors(extracted: dict[str, Any]) -> dict[str, Any]:
    honors: list[dict[str, Any]] = []
    for item in extracted.get("authority_honors", []):
        if not isinstance(item, dict):
            continue
        honors.append(
            {
                "title": _optional_str(item.get("title")),
                "descriptions": _normalize_single_or_list(item.get("description")),
                "report_links": _normalize_single_or_list(item.get("report_link")),
                "awarded_at": _optional_str(item.get("year")),
                "proof_files": _normalize_proof_files(item.get("qualification_proof")),
                "other_info": [],
            }
        )
    return {"honors": honors}


def _build_callback_customers_cases(extracted: dict[str, Any]) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for item in extracted.get("customers_cases", []):
        if not isinstance(item, dict):
            continue
        cases.append(
            {
                "title": _optional_str(item.get("case_name")),
                "cooperation_time": _optional_str(item.get("cooperation_time")),
                "customer_name": _optional_str(item.get("customer_name")),
                "cooperation_products": _normalize_single_or_list(item.get("cooperation_product")),
                "highlights": _normalize_text_list(item.get("cooperation_highlight")),
                "customer_reviews": _normalize_text_list(item.get("customer_feedback")),
                "other_info": [],
            }
        )
    return {"cases": cases}


def _build_callback_products(extracted: dict[str, Any]) -> list[dict[str, Any]]:
    products: list[dict[str, Any]] = []
    for item in extracted.get("products", []):
        if not isinstance(item, dict):
            continue
        name = _optional_str(item.get("name"))
        products.append(
            {
                "base_info": {
                    "name": name,
                    "target_label": name,
                    "product_description": _optional_str(item.get("product_description")),
                    "product_link": _optional_str(item.get("product_website")),
                    "product_images": _normalize_single_or_list(item.get("product_images")),
                    "coverage_regions": _normalize_single_or_list(item.get("coverage_regions")),
                },
                "knowledge": {
                    "price_info": {
                        "summary": _optional_str(item.get("price_info")),
                    },
                    "advantages": _normalize_callback_list(item.get("product_advantages")),
                    "scenarios": _normalize_callback_list(item.get("target_scenarios")),
                    "service_standards": _normalize_callback_list(item.get("service_standard")),
                    "service_processes": _normalize_callback_list(item.get("service_process")),
                    "cases_reputation": _normalize_callback_list(item.get("cases_and_reputation")),
                    "awards_certifications": _normalize_callback_list(item.get("certification_info")),
                    "technologies_patents": _normalize_callback_list(item.get("core_technology")),
                    "other_info": _normalize_callback_list(item.get("other_info")),
                },
            }
        )
    return products


def _build_callback_attachments_payload(service: KnowledgeBaseService, task_id: str) -> dict[str, Any]:
    return {
        "files": _build_callback_attachments(service, task_id),
    }


def _build_callback_attachments_payload_from_entries(entries: Any) -> dict[str, Any]:
    return {
        "files": _build_callback_attachments_from_entries(entries),
    }


def _build_callback_official_malls(extracted: dict[str, Any]) -> list[dict[str, Any]]:
    malls: list[dict[str, Any]] = []
    for item in extracted.get("official_malls", []):
        if not isinstance(item, dict):
            continue
        malls.append(
            {
                "store_name": _optional_str(item.get("store_name")),
                "platform": _optional_str(item.get("platform")),
                "homepage_urls": _normalize_single_or_list(item.get("homepage_urls")),
                "store_ids": _normalize_text_list(item.get("store_ids")),
                "main_categories": _normalize_text_list(item.get("main_categories")),
                "advantages": _normalize_text_list(item.get("advantages")),
                "related_products": _normalize_related_products(item.get("related_products")),
                "other_info": _normalize_text_list(item.get("other_info")),
            }
        )
    return [
        mall for mall in malls
        if any(
            mall.get(field)
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
        )
    ]


def _build_callback_official_media_matrix(extracted: dict[str, Any]) -> list[dict[str, Any]]:
    accounts: list[dict[str, Any]] = []
    for item in extracted.get("official_media_matrix", []):
        if not isinstance(item, dict):
            continue
        accounts.append(
            {
                "media_platform": _optional_str(item.get("media_platform")),
                "account_name": _optional_str(item.get("account_name")),
                "account_id": _optional_str(item.get("account_id")),
                "is_official": _optional_str(item.get("is_official")),
                "homepage_urls": _normalize_single_or_list(item.get("homepage_urls")),
                "fans_count": _optional_str(item.get("fans_count")),
                "content_focus": _normalize_text_list(item.get("content_focus")),
                "related_products": _normalize_related_products(item.get("related_products")),
                "other_info": _normalize_text_list(item.get("other_info")),
            }
        )
    return [
        account for account in accounts
        if any(
            account.get(field)
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
        )
    ]


def _build_callback_other_info(extracted: dict[str, Any]) -> list[dict[str, Any]]:
    value = extracted.get("other_info")
    if isinstance(value, dict):
        iterable = [{"title": key, "content": item} for key, item in value.items()]
    elif isinstance(value, list):
        iterable = value
    else:
        return []

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in iterable:
        if not isinstance(item, dict):
            continue
        title = _optional_str(item.get("title") or item.get("key") or item.get("name"))
        content = item.get("content") if "content" in item else item.get("value")
        if not title or content in (None, "", [], {}):
            continue
        entry = {
            "title": title,
            "content": content,
        }
        try:
            identity = json.dumps(entry, ensure_ascii=False, sort_keys=True)
        except Exception:
            identity = f"{title.casefold()}::{content}"
        if identity in seen:
            continue
        seen.add(identity)
        normalized.append(entry)
    filtered = _filter_other_info_entries(
        normalized,
        snapshot=extracted,
    )
    return [
        item for item in filtered
        if not _should_skip_callback_other_info_entry(item, extracted)
    ]


def _is_attachment_pointer_only(value: Any) -> bool:
    normalized = _optional_str(value)
    if not normalized:
        return True
    return _ATTACHMENT_POINTER_ONLY_RE.fullmatch(normalized) is not None


def _is_placeholder_section_summary(value: Any) -> bool:
    normalized = _optional_str(value)
    if not normalized:
        return True
    return _PLACEHOLDER_SECTION_SUMMARY_RE.fullmatch(normalized) is not None


def _split_lines(value: Any) -> list[str]:
    return [line.rstrip() for line in _optional_str(value).splitlines()]


def _table_has_substantive_payload(content: Any) -> bool:
    for raw_line in _split_lines(content):
        stripped = raw_line.strip()
        if not stripped:
            continue
        if re.fullmatch(r"[:\-\s|]+", stripped):
            continue
        cells = [cell.strip() for cell in stripped.split("|") if cell.strip()]
        for cell in cells:
            if cell in {"维度", "字段", "内容", "渠道", "序号"}:
                continue
            if _ATTACHMENT_POINTER_ONLY_RE.fullmatch(cell):
                continue
            if cell == "(空)":
                continue
            if cell.endswith("1/2/3") or cell in {
                "官方宣传物料",
                "品牌视觉元素",
                "禁忌元素/敏感内容",
                "历史负面及澄清",
                "案例与素材 1/2/3",
                "好评素材包",
                "视觉资产",
                "安全边界",
            }:
                continue
            return True
    return False


def _competitors_have_callback_field(snapshot: dict[str, Any], field_name: str) -> bool:
    competitors = snapshot.get("competitors")
    if not isinstance(competitors, list):
        return False
    return any(
        _normalize_text_list(item.get(field_name))
        for item in normalize_competitors_for_storage(competitors)
    )


def _should_skip_callback_other_info_entry(item: dict[str, Any], snapshot: dict[str, Any]) -> bool:
    title = _optional_str(item.get("title"))
    content = item.get("content")
    if not title:
        return True
    if title == "官方宣传物料" and _is_attachment_pointer_only(content):
        return True
    if title == "三、重点宣传方向" and _is_placeholder_section_summary(content):
        return True
    if title == "4.3 竞品多维对比" and _competitors_have_callback_field(snapshot, "comparison_dimensions"):
        return True
    if title == "4.4 优劣势对比" and _competitors_have_callback_field(snapshot, "differentiated_positioning"):
        return True
    if title in _CALLBACK_OTHER_INFO_EMPTY_SECTION_TITLES and not _table_has_substantive_payload(content):
        return True
    return False


def _build_other_info_filter_snapshot(
    brand: dict[str, Any] | None,
    extracted: dict[str, Any],
) -> dict[str, Any]:
    brand = brand or {}
    basic_info = extracted.get("basic_info") if isinstance(extracted.get("basic_info"), dict) else {}
    company_profile = extracted.get("company_profile") if isinstance(extracted.get("company_profile"), dict) else {}
    return {
        "basic_info": {
            "brand_name": basic_info.get("brand_name") or brand.get("brand_name"),
            "brand_alias": basic_info.get("brand_alias") or brand.get("brand_alias"),
            "website": basic_info.get("website") or brand.get("website"),
            "official_wechat_account": (
                basic_info.get("official_wechat_account") or brand.get("official_wechat_account")
            ),
            "intro": basic_info.get("intro") or brand.get("intro"),
            "positioning": basic_info.get("positioning") or brand.get("positioning"),
            "advantages": basic_info.get("advantages") or brand.get("advantages"),
            "target_regions": basic_info.get("target_regions") or brand.get("target_regions_json"),
            "english_name": basic_info.get("english_name") or brand.get("english_name"),
            "customer_service_hotline": (
                basic_info.get("customer_service_hotline") or brand.get("customer_service_hotline")
            ),
        },
        "company_profile": company_profile,
        "products": extracted.get("products") if isinstance(extracted.get("products"), list) else [],
        "attachment_products": (
            extracted.get("attachment_products")
            if isinstance(extracted.get("attachment_products"), list)
            else []
        ),
        "management_team": (
            extracted.get("management_team")
            if isinstance(extracted.get("management_team"), list)
            else []
        ),
        "competitors": extracted.get("competitors") if isinstance(extracted.get("competitors"), list) else [],
        "authority_honors": (
            extracted.get("authority_honors") if isinstance(extracted.get("authority_honors"), list) else []
        ),
        "official_media_matrix": (
            extracted.get("official_media_matrix")
            if isinstance(extracted.get("official_media_matrix"), list)
            else []
        ),
        "other_info": extracted.get("other_info") if isinstance(extracted.get("other_info"), list) else [],
    }


def format_brand_callback_knowledge(
    service: KnowledgeBaseService,
    task_id: str,
    extracted: dict[str, Any],
    *,
    knowledge_markdown_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task = service._upload_tasks.get_upload_task(task_id)
    metadata = parse_metadata_json(task.get("metadata_json")) if task else {}
    brand_code = str(metadata.get("brand_code") or "").strip()
    brand_name = str(metadata.get("category") or "").strip()
    brand = service._brands.get_brand_by_name(brand_name) if brand_name else None
    other_info_filter_snapshot = _build_other_info_filter_snapshot(brand, extracted)
    extracted_basic_info = extracted.get("basic_info") if isinstance(extracted.get("basic_info"), dict) else None

    payload = {
        "basic_info": _build_callback_basic_info(brand, extracted_basic_info),
        "company_profile": _build_callback_company_profile(brand, extracted),
        "management_team": _build_callback_management_team(extracted),
        "competitors": _build_callback_competitors(extracted),
        "authority_honors": _build_callback_authority_honors(extracted),
        "customers_cases": _build_callback_customers_cases(extracted),
        "products": _build_callback_products(extracted),
        "sensitive_topics": _build_callback_sensitive_topics(extracted),
        "attachments": _build_callback_attachments_payload(service, task_id),
        "official_malls": _build_callback_official_malls(extracted),
        "official_media_matrix": _build_callback_official_media_matrix(extracted),
        "other_info": _build_callback_other_info(other_info_filter_snapshot),
    }
    return payload


def format_brand_callback_knowledge_from_snapshot(
    *,
    brand: dict[str, Any] | None,
    knowledge_snapshot: dict[str, Any],
) -> dict[str, Any]:
    snapshot = knowledge_snapshot if isinstance(knowledge_snapshot, dict) else {}
    other_info_filter_snapshot = _build_other_info_filter_snapshot(brand, snapshot)
    return {
        "basic_info": _build_callback_basic_info(
            brand,
            snapshot.get("basic_info") if isinstance(snapshot.get("basic_info"), dict) else None,
        ),
        "company_profile": _build_callback_company_profile(brand, snapshot),
        "management_team": _build_callback_management_team(snapshot),
        "competitors": _build_callback_competitors(snapshot),
        "authority_honors": _build_callback_authority_honors(snapshot),
        "customers_cases": _build_callback_customers_cases(snapshot),
        "products": _build_callback_products(snapshot),
        "sensitive_topics": _build_callback_sensitive_topics(snapshot),
        "attachments": _build_callback_attachments_payload_from_entries(snapshot.get("attachments")),
        "official_malls": _build_callback_official_malls(snapshot),
        "official_media_matrix": _build_callback_official_media_matrix(snapshot),
        "other_info": _build_callback_other_info(other_info_filter_snapshot),
    }
