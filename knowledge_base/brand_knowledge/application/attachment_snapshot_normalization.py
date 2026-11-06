from __future__ import annotations

from typing import Any

from knowledge_base.brand.competitor_schema import normalize_competitors_for_storage


class AttachmentDraftSnapshotNormalizationMixin:
    @classmethod
    def _has_meaningful_payload(cls, value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            text = value.strip()
            if not text or not cls._normalize_jsonish_list(text):
                return False
            return True
        if isinstance(value, list):
            return any(cls._has_meaningful_payload(item) for item in value)
        if isinstance(value, dict):
            return any(cls._has_meaningful_payload(item) for item in value.values())
        return True

    def _normalize_snapshot_for_merge(self, snapshot: dict[str, Any] | None) -> dict[str, Any]:
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        return {
            "basic_info": (
                dict(snapshot.get("basic_info") or {})
                if isinstance(snapshot.get("basic_info"), dict) else {}
            ),
            "products": self._normalize_products_for_merge(snapshot.get("products")),
            "company_profile": (
                dict(snapshot.get("company_profile") or {})
                if isinstance(snapshot.get("company_profile"), dict) else {}
            ),
            "management_team": self._normalize_management_team_for_merge(snapshot.get("management_team")),
            "competitors": self._normalize_competitors_for_merge(snapshot.get("competitors")),
            "authority_honors": self._normalize_authority_honors_for_merge(snapshot.get("authority_honors")),
            "customers_cases": self._normalize_customers_cases_for_merge(snapshot.get("customers_cases")),
            "official_malls": (
                [dict(item) for item in snapshot.get("official_malls", []) if isinstance(item, dict)]
                if isinstance(snapshot.get("official_malls"), list) else []
            ),
            "official_media_matrix": (
                [dict(item) for item in snapshot.get("official_media_matrix", []) if isinstance(item, dict)]
                if isinstance(snapshot.get("official_media_matrix"), list) else []
            ),
            "sensitive_topics": self._normalize_sensitive_topics_for_merge(snapshot.get("sensitive_topics")),
            "attachments": self._normalize_attachment_entries(snapshot.get("attachments")),
            "other_info": self._normalize_other_info_for_merge(snapshot.get("other_info")),
        }

    @classmethod
    def _product_value(cls, item: dict[str, Any], key: str) -> Any:
        if key in item:
            return item.get(key)
        for alias in cls._ATTACHMENT_PRODUCT_FIELD_ALIASES.get(key, ()):
            if alias in item:
                return item.get(alias)
        return None

    def _normalize_products_for_merge(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        normalized: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            name = self._normalize_optional_str(self._product_value(item, "name"))
            if not name:
                continue
            normalized.append(
                {
                    "name": name,
                    "product_alias": self._normalize_optional_str(self._product_value(item, "product_alias")),
                    "product_description": self._normalize_optional_str(self._product_value(item, "product_description")),
                    "product_website": self._normalize_optional_str(
                        self._product_value(item, "product_website") or item.get("product_link")
                    ),
                    "product_images": self._normalize_string_list(self._product_value(item, "product_images")),
                    "price_info": self._normalize_optional_str(self._product_value(item, "price_info")),
                    "coverage_regions": self._normalize_string_list(self._product_value(item, "coverage_regions")),
                    "product_advantages": self._normalize_optional_str(
                        self._product_value(item, "product_advantages") or item.get("advantages")
                    ),
                    "target_scenarios": self._normalize_optional_str(
                        self._product_value(item, "target_scenarios") or item.get("scenarios")
                    ),
                    "service_standard": self._normalize_optional_str(self._product_value(item, "service_standard")),
                    "service_process": self._normalize_optional_str(self._product_value(item, "service_process")),
                    "cases_and_reputation": self._normalize_optional_str(
                        self._product_value(item, "cases_and_reputation")
                    ),
                    "certification_info": self._normalize_optional_str(
                        self._product_value(item, "certification_info")
                    ),
                    "core_technology": self._normalize_optional_str(self._product_value(item, "core_technology")),
                    "other_info": self._normalize_optional_str(self._product_value(item, "other_info")),
                }
            )
        return normalized

    def _normalize_management_team_for_merge(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        normalized: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            name = self._normalize_optional_str(item.get("name") or item.get("member_name"))
            if not name:
                continue
            normalized.append(
                {
                    "name": name,
                    "title": self._normalize_optional_str(item.get("title") or item.get("position")),
                    "profile": self._normalize_optional_str(item.get("profile") or item.get("bio")),
                    "introduction_website": self._normalize_optional_str(
                        item.get("introduction_website") or item.get("intro_urls")
                    ),
                    "source_section": self._normalize_optional_str(item.get("source_section")),
                    "other_info": self._normalize_optional_str(item.get("other_info")),
                }
            )
        return normalized

    def _normalize_competitors_for_merge(self, value: Any) -> list[dict[str, Any]]:
        return normalize_competitors_for_storage(value)

    def _normalize_authority_honors_for_merge(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        normalized: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            title = self._normalize_optional_str(item.get("title"))
            if not title:
                continue
            description = item.get("description") if item.get("description") is not None else item.get("descriptions")
            normalized.append(
                {
                    "title": title,
                    "year": self._prefer_specific_award_date(
                        item.get("year") or item.get("awarded_at"),
                        title,
                        description,
                    ),
                    "description": description,
                    "report_link": (
                        item.get("report_link")
                        if item.get("report_link") is not None else item.get("report_links")
                    ),
                    "qualification_proof": (
                        item.get("qualification_proof")
                        if item.get("qualification_proof") is not None else item.get("proof_files")
                    ),
                    "source_section": self._normalize_optional_str(item.get("source_section")),
                }
            )
        return normalized

    def _normalize_customers_cases_for_merge(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        normalized: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            case_name = self._normalize_optional_str(item.get("case_name") or item.get("title"))
            customer_name = self._normalize_optional_str(item.get("customer_name"))
            if not case_name and not customer_name:
                continue
            normalized.append(
                {
                    "case_name": case_name,
                    "cooperation_time": self._normalize_optional_str(item.get("cooperation_time")),
                    "customer_name": customer_name,
                    "cooperation_product": (
                        item.get("cooperation_product")
                        if item.get("cooperation_product") is not None else item.get("cooperation_products")
                    ),
                    "cooperation_highlight": (
                        item.get("cooperation_highlight")
                        if item.get("cooperation_highlight") is not None else item.get("highlights")
                    ),
                    "customer_feedback": (
                        item.get("customer_feedback")
                        if item.get("customer_feedback") is not None else item.get("customer_reviews")
                    ),
                    "source_section": self._normalize_optional_str(item.get("source_section")),
                }
            )
        return normalized

    def _normalize_sensitive_topics_for_merge(self, value: Any) -> dict[str, list[str]]:
        if isinstance(value, dict):
            return {
                "sensitive_contents": self._normalize_string_list(value.get("sensitive_contents")),
                "controversial_events": self._normalize_string_list(value.get("controversial_events")),
                "forbidden_words": self._normalize_string_list(value.get("forbidden_words")),
                "negative_clarifications": self._normalize_string_list(value.get("negative_clarifications")),
                "other_info": self._normalize_string_list(value.get("other_info")),
            }
        if isinstance(value, list):
            return {
                "sensitive_contents": self._normalize_text_list_from_dicts(value, "topic"),
                "controversial_events": self._normalize_text_list_from_dicts(value, "description"),
                "forbidden_words": self._normalize_text_list_from_dicts(value, "forbidden_words")
                or self._normalize_text_list_from_dicts(value, "forbidden_terms"),
                "negative_clarifications": self._normalize_text_list_from_dicts(
                    value,
                    "history_negative_clarification",
                ),
                "other_info": [],
            }
        return {
            "sensitive_contents": [],
            "controversial_events": [],
            "forbidden_words": [],
            "negative_clarifications": [],
            "other_info": [],
        }
