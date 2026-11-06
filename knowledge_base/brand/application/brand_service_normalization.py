from __future__ import annotations

import json
from typing import Any

from knowledge_base.shared.utils import (
    is_effective_empty_sequence,
    normalize_hotline_sequence,
    normalize_http_url_sequence,
    normalize_line_delimited_text_sequence,
    normalize_text_sequence,
)


class BrandServiceNormalizationMixin:
    @staticmethod
    def _has_meaningful_payload(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, tuple, set, dict)):
            return len(value) > 0
        return True

    @staticmethod
    def _normalize_str(value: Any) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @classmethod
    def _normalize_brand_other_info_str(cls, value: Any) -> str | None:
        normalized = cls._normalize_str(value)
        if normalized is None:
            return None
        if normalized in {"{}", "null", '""', "None"}:
            return None
        if is_effective_empty_sequence(normalized):
            return None
        return normalized

    @staticmethod
    def _normalize_multi_value(value: Any) -> list[str]:
        return normalize_text_sequence(value)

    @classmethod
    def _normalize_optional_multi_value(cls, value: Any) -> list[str]:
        return cls._normalize_multi_value(value)

    @staticmethod
    def _normalize_customer_service_hotline(value: Any) -> list[str]:
        return normalize_hotline_sequence(value)

    @staticmethod
    def _normalize_brand_text_multi_value(value: Any) -> list[str]:
        return normalize_line_delimited_text_sequence(value)

    @classmethod
    def _brand_multi_value(cls, brand: dict[str, Any], key: str) -> list[str]:
        if key == "target_regions":
            json_value = brand.get("target_regions_json")
            if json_value is not None:
                return cls.normalize_sequence_value(json_value)
        if key == "customer_service_hotline":
            return cls._normalize_customer_service_hotline(brand.get(key))
        if key in {"positioning", "advantages", "mission", "vision"}:
            return cls._normalize_brand_text_multi_value(brand.get(key))
        return cls._normalize_multi_value(brand.get(key))

    @staticmethod
    def _normalize_int(value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, int):
            return value
        normalized = str(value).strip()
        if not normalized:
            return None
        try:
            return int(normalized)
        except ValueError:
            return None

    @staticmethod
    def _normalize_aliases(value: Any) -> list[str]:
        return normalize_text_sequence(
            value,
            split_separators=("\n",),
        )

    @staticmethod
    def _normalize_websites(value: Any) -> list[str]:
        return normalize_http_url_sequence(value)

    @classmethod
    def _serialize_websites(cls, value: Any) -> str | None:
        websites = cls._normalize_websites(value)
        if not websites:
            return None
        return json.dumps(websites, ensure_ascii=False)

    @staticmethod
    def _normalize_text_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        normalized = str(value or "").strip()
        return [normalized] if normalized else []

    @classmethod
    def _normalize_company_profile_update_payload(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        business_license_image_path = cls._normalize_str(normalized.get("business_license_image_path"))
        if not business_license_image_path:
            business_license_image_path = cls._normalize_str(normalized.get("business_license_url"))
        if business_license_image_path:
            normalized["business_license_image_path"] = business_license_image_path
        normalized.pop("business_license_url", None)
        return normalized

    @classmethod
    def _normalize_sensitive_topics_payload(cls, value: Any) -> dict[str, list[str]]:
        if hasattr(value, "model_dump"):
            value = value.model_dump()

        normalized = {
            "sensitive_contents": [],
            "controversial_events": [],
            "forbidden_words": [],
            "negative_clarifications": [],
            "other_info": [],
        }
        if isinstance(value, dict):
            for key in normalized:
                normalized[key] = cls._normalize_text_list(value.get(key))
            return normalized

        if isinstance(value, list):
            sensitive_contents: list[str] = []
            controversial_events: list[str] = []
            forbidden_words: list[str] = []
            negative_clarifications: list[str] = []
            other_info: list[str] = []
            for item in value:
                if not isinstance(item, dict):
                    continue
                sensitive_contents.extend(cls._normalize_text_list(item.get("topic")))
                controversial_events.extend(cls._normalize_text_list(item.get("description")))
                forbidden_words.extend(
                    cls._normalize_text_list(item.get("forbidden_words") or item.get("forbidden_terms"))
                )
                negative_clarifications.extend(
                    cls._normalize_text_list(
                        item.get("negative_clarifications") or item.get("history_negative_clarification")
                    )
                )
                other_info.extend(cls._normalize_text_list(item.get("other_info")))
            normalized["sensitive_contents"] = cls._normalize_text_list(sensitive_contents)
            normalized["controversial_events"] = cls._normalize_text_list(controversial_events)
            normalized["forbidden_words"] = cls._normalize_text_list(forbidden_words)
            normalized["negative_clarifications"] = cls._normalize_text_list(negative_clarifications)
            normalized["other_info"] = cls._normalize_text_list(other_info)
        return normalized

    @staticmethod
    def _is_duplicate_attachment_upload_error(exc: Exception) -> bool:
        message = str(exc)
        return "发现相同文件已存在" in message or "当前批次存在重复文件" in message

    @classmethod
    def _jsonable_for_compare(cls, value: Any) -> Any:
        if isinstance(value, str):
            parsed = cls._parse_json_value(value, None)
            if parsed is not None:
                return cls._jsonable_for_compare(parsed)
            return value.strip()
        if isinstance(value, dict):
            return {
                str(key): cls._jsonable_for_compare(item)
                for key, item in value.items()
                if cls._has_meaningful_payload(item)
            }
        if isinstance(value, (list, tuple, set)):
            return [
                cls._jsonable_for_compare(item)
                for item in value
                if cls._has_meaningful_payload(item)
            ]
        return value

    @classmethod
    def _normalized_values_equal(cls, left: Any, right: Any) -> bool:
        return cls._jsonable_for_compare(left) == cls._jsonable_for_compare(right)

    @classmethod
    def _has_material_change(cls, existing_value: Any, next_value: Any) -> bool:
        return not cls._normalized_values_equal(existing_value, next_value)

    @classmethod
    def _has_positive_change(cls, existing_value: Any, next_value: Any) -> bool:
        if not cls._has_meaningful_payload(next_value):
            return False
        existing_normalized = cls._jsonable_for_compare(existing_value)
        next_normalized = cls._jsonable_for_compare(next_value)
        return cls._has_positive_delta(existing_normalized, next_normalized)

    @classmethod
    def _has_positive_delta(cls, existing_value: Any, next_value: Any) -> bool:
        if not cls._has_meaningful_payload(next_value):
            return False
        if isinstance(next_value, dict):
            existing_dict = existing_value if isinstance(existing_value, dict) else {}
            for key, next_item in next_value.items():
                if not cls._has_meaningful_payload(next_item):
                    continue
                if key not in existing_dict:
                    return True
                if cls._has_positive_delta(existing_dict.get(key), next_item):
                    return True
            return False
        if isinstance(next_value, list):
            existing_items = existing_value if isinstance(existing_value, list) else []
            unmatched_existing = list(existing_items)
            for next_item in next_value:
                if not cls._has_meaningful_payload(next_item):
                    continue
                matched_index = next(
                    (
                        index
                        for index, existing_item in enumerate(unmatched_existing)
                        if cls._normalized_values_equal(existing_item, next_item)
                    ),
                    None,
                )
                if matched_index is None:
                    return True
                unmatched_existing.pop(matched_index)
            return False
        return not cls._normalized_values_equal(existing_value, next_value)

    @classmethod
    def _has_removal_delta(cls, existing_value: Any, next_value: Any) -> bool:
        if not cls._has_meaningful_payload(existing_value):
            return False
        existing_normalized = cls._jsonable_for_compare(existing_value)
        next_normalized = cls._jsonable_for_compare(next_value)
        if isinstance(existing_normalized, dict):
            next_dict = next_normalized if isinstance(next_normalized, dict) else {}
            for key, existing_item in existing_normalized.items():
                if key not in next_dict:
                    return True
                if not cls._has_meaningful_payload(next_dict.get(key)):
                    return True
                if cls._has_removal_delta(existing_item, next_dict.get(key)):
                    return True
            return False
        if isinstance(existing_normalized, list):
            next_items = next_normalized if isinstance(next_normalized, list) else []
            unmatched_next = list(next_items)
            for existing_item in existing_normalized:
                matched_index = next(
                    (
                        index
                        for index, next_item in enumerate(unmatched_next)
                        if cls._normalized_values_equal(existing_item, next_item)
                    ),
                    None,
                )
                if matched_index is None:
                    return True
                unmatched_next.pop(matched_index)
            return False
        return False

    @classmethod
    def _has_sensitive_topics_content(cls, value: Any) -> bool:
        normalized = cls._normalize_sensitive_topics_payload(value)
        return any(bool(normalized[key]) for key in normalized)

    @classmethod
    def _serialize_sensitive_topics_payload(cls, value: Any) -> dict[str, list[str]]:
        normalized = cls._normalize_sensitive_topics_payload(value)
        if not cls._has_sensitive_topics_content(normalized):
            return {}
        return normalized

    @classmethod
    def _render_sensitive_topics_markdown(cls, value: Any) -> str:
        normalized = cls._normalize_sensitive_topics_payload(value)
        sections = (
            ("敏感内容", normalized["sensitive_contents"]),
            ("争议事件", normalized["controversial_events"]),
            ("禁用词", normalized["forbidden_words"]),
            ("负面澄清口径", normalized["negative_clarifications"]),
            ("其他信息", normalized["other_info"]),
        )
        blocks = [
            cls._markdown_section(title, cls._markdown_list(items))
            for title, items in sections
            if items
        ]
        return cls._join_sections(["# 敏感话题", *blocks])

    @staticmethod
    def _json_markdown_block(value: Any) -> str:
        return "```json\n" + json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n```"

    @classmethod
    def _changed_brand_payload(cls, existing_brand: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        changed: dict[str, Any] = {}
        existing_key_map = {
            "target_regions": "target_regions_json",
        }
        for key, next_value in payload.items():
            if key == "competitors" or not cls._has_meaningful_payload(next_value):
                continue
            existing_key = existing_key_map.get(key, key)
            existing_value = (
                cls._brand_multi_value(existing_brand, key)
                if key in {"customer_service_hotline", "positioning", "advantages", "mission", "vision", "target_regions"}
                else existing_brand.get(existing_key)
            )
            if cls._has_material_change(existing_value, next_value):
                changed[key] = next_value
        return changed

    @classmethod
    def _changed_brand_before_payload(
        cls,
        existing_brand: dict[str, Any],
        changed_payload: dict[str, Any],
    ) -> dict[str, Any]:
        before: dict[str, Any] = {}
        existing_key_map = {
            "target_regions": "target_regions_json",
        }
        for key in changed_payload:
            if key == "competitors":
                continue
            existing_key = existing_key_map.get(key, key)
            existing_value = (
                cls._brand_multi_value(existing_brand, key)
                if key in {"customer_service_hotline", "positioning", "advantages", "mission", "vision", "target_regions"}
                else existing_brand.get(existing_key)
            )
            before[key] = cls._jsonable_for_compare(existing_value)
        return before

    @classmethod
    def _normalize_existing_products_for_diff(
        cls,
        existing_products: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        normalized_products: list[dict[str, Any]] = []
        for product in existing_products:
            if not isinstance(product, dict):
                continue
            product_name = cls._normalize_str(product.get("product_name"))
            if not product_name:
                continue
            normalized_products.append(
                {
                    "product_code": cls._normalize_str(product.get("product_code")),
                    "product_name": product_name,
                    "product_alias": cls._normalize_str(product.get("product_alias")),
                    "product_description": cls._normalize_str(product.get("product_description")),
                    "product_website": cls._normalize_str(product.get("product_website")),
                    "product_images": cls.normalize_sequence_value(product.get("product_images_json")),
                    "price_info": cls._normalize_str(product.get("price_info")),
                    "coverage_regions": cls.normalize_sequence_value(product.get("coverage_regions_json")),
                    "product_advantages": cls._normalize_str(product.get("product_advantages")),
                    "target_scenarios": cls._normalize_str(product.get("target_scenarios")),
                    "service_standard": cls._normalize_str(product.get("service_standard")),
                    "service_process": cls._normalize_str(product.get("service_process")),
                    "cases_and_reputation": cls._normalize_str(product.get("cases_and_reputation")),
                    "certification_info": cls._normalize_str(product.get("certification_info")),
                    "core_technology": cls._normalize_str(product.get("core_technology")),
                    "other_info": cls._normalize_str(product.get("other_info")),
                }
            )
        return normalized_products

    @classmethod
    def _append_structured_change_detail(
        cls,
        change_details: list[dict[str, Any]],
        *,
        section: str,
        title: str,
        action: str,
        before: Any,
        after: Any,
        source_type: str | None = None,
    ) -> None:
        detail = {
            "section": str(section or "").strip(),
            "title": str(title or section).strip(),
            "action": str(action or "update").strip(),
            "before": cls._jsonable_for_compare(before),
            "after": cls._jsonable_for_compare(after),
        }
        normalized_source_type = str(source_type or "").strip()
        if normalized_source_type:
            detail["source_type"] = normalized_source_type
        change_details.append(detail)

    @classmethod
    def _render_structured_update_delta_markdown(
        cls,
        *,
        brand_name: str,
        entries: list[dict[str, Any]],
        deleted_sections: list[str] | None = None,
    ) -> str:
        normalized_entries = [
            entry for entry in entries
            if isinstance(entry, dict) and str(entry.get("section") or "").strip()
        ]
        normalized_deleted_sections = [
            str(section or "").strip()
            for section in deleted_sections or []
            if str(section or "").strip()
        ]
        if not normalized_entries and not normalized_deleted_sections:
            return ""

        lines: list[str] = [
            f"# {brand_name} 本次结构化知识变更",
            "",
            "本文件只包含本次更新涉及的结构化内容；未列出的 section 请沿用上一版品牌 AI 知识库。",
        ]
        if normalized_deleted_sections:
            lines.extend(
                [
                    "",
                    "## 本次明确删除或收缩的 section",
                    "",
                    *[f"- {section}" for section in normalized_deleted_sections],
                ]
            )
        for entry in normalized_entries:
            section = str(entry.get("section") or "").strip()
            title = str(entry.get("title") or section).strip()
            action = str(entry.get("action") or "update").strip()
            lines.extend(
                [
                    "",
                    f"## {title}",
                    "",
                    f"- section：`{section}`",
                    f"- change_type：`{action}`",
                    "",
                    "本次更新后的内容：",
                    cls._json_markdown_block(entry.get("content")),
                ]
            )
        return "\n".join(lines).strip()

    @classmethod
    def _classify_structured_update_mode(
        cls,
        *,
        entries: list[dict[str, Any]],
        deleted_sections: list[str] | None = None,
    ) -> str:
        normalized_entries = [
            entry
            for entry in entries
            if isinstance(entry, dict) and str(entry.get("section") or "").strip()
        ]
        normalized_deleted_sections = {
            str(section or "").strip()
            for section in deleted_sections or []
            if str(section or "").strip()
        }
        if not normalized_entries and not normalized_deleted_sections:
            return "noop"
        if not normalized_deleted_sections:
            return "update"
        has_non_deleted_updates = any(
            str(entry.get("section") or "").strip() not in normalized_deleted_sections
            for entry in normalized_entries
        )
        return "change" if has_non_deleted_updates else "delete"

    @staticmethod
    def _field_was_provided(model: Any, field_name: str) -> bool:
        fields_set = getattr(model, "model_fields_set", None)
        if fields_set is None:
            fields_set = getattr(model, "__fields_set__", None)
        if fields_set is None:
            fields_set = getattr(model, "__dict__", {}).keys()
        return field_name in fields_set

    @classmethod
    def _explicit_empty_payload(cls, value: Any) -> Any:
        normalized = cls._jsonable_for_compare(value)
        if isinstance(normalized, dict):
            return {}
        if isinstance(normalized, list):
            return []
        return None

    @classmethod
    def _resolve_section_update_action(
        cls,
        *,
        request: Any,
        knowledge_type: str,
        content: Any,
        existing_content: Any,
        clearable_types: set[str],
    ) -> tuple[bool, Any, bool, bool]:
        was_provided = cls._field_was_provided(request, knowledge_type)
        if not was_provided:
            return False, None, False, False
        if cls._has_meaningful_payload(content):
            has_change = cls._has_material_change(existing_content, content)
            had_content = cls._has_meaningful_payload(existing_content)
            has_deletion = had_content and cls._has_removal_delta(existing_content, content)
            return True, content, has_change, has_deletion
        if knowledge_type not in clearable_types:
            return False, None, False, False
        empty_payload = cls._explicit_empty_payload(existing_content)
        had_content = cls._has_meaningful_payload(existing_content)
        has_change = cls._has_material_change(existing_content, empty_payload)
        return True, empty_payload, has_change, had_content

    @staticmethod
    def _normalize_attachment_entries(value: Any) -> list[dict[str, str]]:
        if not isinstance(value, list):
            return []
        normalized_by_url: dict[str, dict[str, str]] = {}
        for item in value:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            url = str(item.get("url") or "").strip()
            if not name or not url:
                continue
            if url in normalized_by_url:
                normalized_by_url.pop(url)
            normalized_by_url[url] = {"name": name, "url": url}
        return list(normalized_by_url.values())

    @classmethod
    def _brand_payload_has_positive_change(cls, existing_brand: dict[str, Any], payload: dict[str, Any]) -> bool:
        comparable_fields = (
            ("brand_code", "brand_code"),
            ("brand_alias", "brand_alias"),
            ("brand_logo", "brand_logo"),
            ("website", "website"),
            ("customer_service_hotline", "customer_service_hotline"),
            ("official_wechat_account", "official_wechat_account"),
            ("intro", "intro"),
            ("email", "email"),
            ("brand_enterprise_entity", "brand_enterprise_entity"),
            ("business_license_image_path", "business_license_image_path"),
            ("english_name", "english_name"),
            ("positioning", "positioning"),
            ("advantages", "advantages"),
            ("mission", "mission"),
            ("vision", "vision"),
            ("target_regions", "target_regions_json"),
            ("other_info", "other_info"),
        )
        for payload_key, existing_key in comparable_fields:
            next_value = payload.get(payload_key)
            existing_value = (
                cls._brand_multi_value(existing_brand, payload_key)
                if payload_key in {"customer_service_hotline", "positioning", "advantages", "mission", "vision", "target_regions"}
                else existing_brand.get(existing_key)
            )
            if payload_key in {"customer_service_hotline", "positioning", "advantages", "mission", "vision", "target_regions"}:
                if cls._has_positive_change(existing_value, next_value):
                    return True
                continue
            if cls._has_positive_change(existing_value, next_value):
                return True
        return False

    @classmethod
    def _product_payload_has_positive_change(
        cls,
        existing_products: list[dict[str, Any]],
        next_products: list[dict[str, Any]],
    ) -> bool:
        existing_by_code = {
            str(item.get("product_code") or "").strip(): item
            for item in existing_products if str(item.get("product_code") or "").strip()
        }
        existing_by_name = {
            str(item.get("product_name") or "").strip().casefold(): item
            for item in existing_products
            if str(item.get("product_name") or "").strip()
        }
        comparable_fields = (
            ("product_alias", "product_alias"),
            ("product_description", "product_description"),
            ("product_website", "product_website"),
            ("product_images", "product_images_json"),
            ("price_info", "price_info"),
            ("coverage_regions", "coverage_regions_json"),
            ("product_advantages", "product_advantages"),
            ("target_scenarios", "target_scenarios"),
            ("service_standard", "service_standard"),
            ("service_process", "service_process"),
            ("cases_and_reputation", "cases_and_reputation"),
            ("certification_info", "certification_info"),
            ("core_technology", "core_technology"),
            ("other_info", "other_info"),
        )
        for product in next_products:
            product_name = str(product.get("product_name") or "").strip()
            if not product_name:
                continue
            product_code = str(product.get("product_code") or "").strip()
            existing_product = existing_by_code.get(product_code) if product_code else None
            if existing_product is None:
                existing_product = existing_by_name.get(product_name.casefold())
                if product_code and existing_product and str(existing_product.get("product_code") or "").strip():
                    return True
            if existing_product is None:
                return True
            if product_name != str(existing_product.get("product_name") or "").strip():
                return True
            for payload_key, existing_key in comparable_fields:
                if cls._has_positive_change(existing_product.get(existing_key), product.get(payload_key)):
                    return True
        return False

    @classmethod
    def _attachments_have_positive_change(cls, current_attachments: Any, next_attachments: Any) -> bool:
        current_items = cls._normalize_attachment_entries(current_attachments)
        next_items = cls._normalize_attachment_entries(next_attachments)
        current_keys = {item["url"] for item in current_items}
        next_keys = {item["url"] for item in next_items}
        return bool(next_keys - current_keys)

    @classmethod
    def _normalize_other_info_entries(cls, value: Any) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        if isinstance(value, dict):
            iterable = [
                {
                    "title": key,
                    "content": item,
                }
                for key, item in value.items()
            ]
        elif isinstance(value, list):
            iterable = value
        else:
            return []

        seen: dict[str, int] = {}
        for item in iterable:
            if not isinstance(item, dict):
                continue
            raw_title = item.get("title") or item.get("key") or item.get("name")
            title = cls._normalize_str(str(raw_title)) if raw_title is not None else None
            raw_content = item.get("content") if "content" in item else item.get("value")
            if title is None or not cls._has_meaningful_payload(raw_content):
                continue
            content = cls._normalize_other_info_content(raw_content)
            entry = {
                "title": title,
                "content": content,
            }
            identity = title.casefold()
            if identity in seen:
                entries[seen[identity]] = entry
            else:
                seen[identity] = len(entries)
                entries.append(entry)
        return entries

    @classmethod
    def _normalize_other_info_content(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            return [
                item
                for item in (cls._normalize_other_info_content(item) for item in value)
                if cls._has_meaningful_payload(item)
            ]
        if isinstance(value, dict):
            return {
                str(key).strip(): cls._normalize_other_info_content(item)
                for key, item in value.items()
                if str(key).strip() and cls._has_meaningful_payload(item)
            }
        return value

    @classmethod
    def _merge_other_info_entries(cls, current: Any, incoming: Any) -> list[dict[str, Any]]:
        merged = cls._normalize_other_info_entries(current)
        index_map = {
            str(item.get("title") or "").strip().casefold(): index
            for index, item in enumerate(merged)
            if str(item.get("title") or "").strip()
        }
        for item in cls._normalize_other_info_entries(incoming):
            title = str(item.get("title") or "").strip()
            identity = title.casefold()
            if identity in index_map:
                merged[index_map[identity]] = item
            else:
                index_map[identity] = len(merged)
                merged.append(item)
        return merged

    @classmethod
    def _normalize_attachment_product_name(cls, value: Any) -> str:
        if not isinstance(value, dict):
            return ""
        return str(value.get("name") or value.get("product_name") or "").strip()

    @classmethod
    def _normalize_attachment_product_payload(cls, value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        name = cls._normalize_attachment_product_name(value)
        if not name:
            return None
        payload: dict[str, Any] = {"name": name}
        for field in cls._ATTACHMENT_PRODUCT_TEXT_FIELDS:
            field_value = value.get(field)
            if field == "product_website" and not field_value:
                field_value = value.get("product_link")
            if field == "product_advantages" and not field_value:
                field_value = value.get("advantages")
            if field == "target_scenarios" and not field_value:
                field_value = value.get("scenarios")
            payload[field] = cls._normalize_str(field_value)
        for field in cls._ATTACHMENT_PRODUCT_LIST_FIELDS:
            field_value = value.get(field)
            if field == "product_images" and field_value is None:
                field_value = value.get("product_images_json")
            if field == "coverage_regions" and field_value is None:
                field_value = value.get("coverage_regions_json")
            payload[field] = cls.normalize_sequence_value(field_value)
        return payload

    @classmethod
    def _normalize_attachment_products(cls, value: Any) -> list[dict[str, Any]]:
        if isinstance(value, dict):
            iterable = [value]
        elif isinstance(value, list):
            iterable = value
        else:
            return []
        normalized: list[dict[str, Any]] = []
        seen_names: set[str] = set()
        for item in iterable:
            normalized_item = cls._normalize_attachment_product_payload(item)
            if normalized_item is None:
                continue
            key = normalized_item["name"].casefold()
            if key in seen_names:
                continue
            seen_names.add(key)
            normalized.append(normalized_item)
        return normalized

    @classmethod
    def _extract_attachment_products_override_from_other_info(
        cls,
        value: Any,
    ) -> tuple[bool, list[dict[str, Any]]]:
        if isinstance(value, dict):
            iterable = [
                {
                    "title": key,
                    "content": item,
                }
                for key, item in value.items()
            ]
        elif isinstance(value, list):
            iterable = value
        else:
            return False, []
        target_title = cls.ATTACHMENT_PRODUCTS_OTHER_INFO_TITLE.casefold()
        found = False
        normalized_products: list[dict[str, Any]] = []
        for item in iterable:
            if not isinstance(item, dict):
                continue
            raw_title = item.get("title") or item.get("key") or item.get("name")
            title = cls._normalize_str(raw_title)
            if not title or title.casefold() != target_title:
                continue
            found = True
            raw_content = item.get("content") if "content" in item else item.get("value")
            parsed_content = raw_content
            if isinstance(parsed_content, str):
                json_value = cls._parse_json_value(parsed_content, None)
                if isinstance(json_value, (dict, list)):
                    parsed_content = json_value
            normalized_products = cls._normalize_attachment_products(parsed_content)
        return found, normalized_products

    @classmethod
    def _rebuild_other_info_with_attachment_products(
        cls,
        other_info: Any,
        attachment_products: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        target_title = cls.ATTACHMENT_PRODUCTS_OTHER_INFO_TITLE.casefold()
        rebuilt: list[dict[str, Any]] = []
        for item in cls._normalize_other_info_entries(other_info):
            title = str(item.get("title") or "").strip()
            if title and title.casefold() == target_title:
                continue
            rebuilt.append(item)
        if attachment_products:
            rebuilt.append(
                {
                    "title": cls.ATTACHMENT_PRODUCTS_OTHER_INFO_TITLE,
                    "content": attachment_products,
                }
            )
        return rebuilt

    @classmethod
    def _build_attachment_product_callback_snapshot(
        cls,
        *,
        brand_products: list[dict[str, Any]],
        knowledge_map: dict[str, Any],
    ) -> dict[str, Any]:
        products_snapshot: list[dict[str, Any]] = []
        for product in brand_products:
            if not isinstance(product, dict):
                continue
            name = str(product.get("product_name") or "").strip()
            if not name:
                continue
            products_snapshot.append(
                {
                    "product_code": cls._normalize_str(product.get("product_code")),
                    "name": name,
                    "product_alias": cls._normalize_str(product.get("product_alias")),
                    "product_description": cls._normalize_str(product.get("product_description")),
                    "product_website": cls._normalize_str(product.get("product_website")),
                    "product_images": cls.normalize_sequence_value(product.get("product_images_json")),
                    "price_info": cls._normalize_str(product.get("price_info")),
                    "coverage_regions": cls.normalize_sequence_value(product.get("coverage_regions_json")),
                    "product_advantages": cls._normalize_str(product.get("product_advantages")),
                    "target_scenarios": cls._normalize_str(product.get("target_scenarios")),
                    "service_standard": cls._normalize_str(product.get("service_standard")),
                    "service_process": cls._normalize_str(product.get("service_process")),
                    "cases_and_reputation": cls._normalize_str(product.get("cases_and_reputation")),
                    "certification_info": cls._normalize_str(product.get("certification_info")),
                    "core_technology": cls._normalize_str(product.get("core_technology")),
                    "other_info": cls._normalize_str(product.get("other_info")),
                }
            )
        return {
            "basic_info": {},
            "products": products_snapshot,
            "company_profile": knowledge_map.get("company_profile") or knowledge_map.get("company_info") or {},
            "management_team": knowledge_map.get("management_team") or [],
            "competitors": knowledge_map.get("competitors") or [],
            "authority_honors": knowledge_map.get("authority_honors") or knowledge_map.get("honors") or [],
            "customers_cases": knowledge_map.get("customers_cases") or knowledge_map.get("cases") or [],
            "sensitive_topics": knowledge_map.get("sensitive_topics") or {},
            "attachments": knowledge_map.get("attachments") or [],
            "official_malls": knowledge_map.get("official_malls") or [],
            "official_media_matrix": knowledge_map.get("official_media_matrix") or [],
            "other_info": knowledge_map.get("other_info") or [],
        }

    @staticmethod
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
                normalized_text = str(item or "").strip()
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
