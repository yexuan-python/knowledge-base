from __future__ import annotations

import json
from typing import Any

from knowledge_base.brand.competitor_schema import normalize_competitors_for_storage


class AttachmentDraftConfirmMergeMixin:
    def _merge_prefer_confirmed_value(self, current: Any, candidate: Any) -> Any:
        if isinstance(current, dict) or isinstance(candidate, dict):
            current_dict = current if isinstance(current, dict) else {}
            candidate_dict = candidate if isinstance(candidate, dict) else {}
            merged: dict[str, Any] = {}
            for key in set(current_dict) | set(candidate_dict):
                merged[key] = self._merge_prefer_confirmed_value(current_dict.get(key), candidate_dict.get(key))
            return merged
        if isinstance(current, list) or isinstance(candidate, list):
            return self._merge_jsonish_lists(current, candidate)
        if self._has_meaningful_payload(candidate):
            return candidate
        return current

    def _merge_jsonish_lists(self, current: Any, candidate: Any) -> list[Any]:
        merged: list[Any] = []
        seen: set[str] = set()
        for item in [*self._normalize_jsonish_list(current), *self._normalize_jsonish_list(candidate)]:
            try:
                identity = json.dumps(item, ensure_ascii=False, sort_keys=True)
            except Exception:
                identity = str(item)
            if identity in seen:
                continue
            seen.add(identity)
            merged.append(item)
        return merged

    def _merge_basic_info(
        self,
        current: dict[str, Any],
        candidate: dict[str, Any],
    ) -> dict[str, Any]:
        merged = self._merge_prefer_confirmed_value(current, candidate)
        if not isinstance(merged, dict):
            return {}
        merged["website"] = self._merge_string_lists(
            current.get("website") if isinstance(current, dict) else None,
            candidate.get("website") if isinstance(candidate, dict) else None,
        )
        merged["target_regions"] = self._merge_string_lists(
            current.get("target_regions") if isinstance(current, dict) else None,
            candidate.get("target_regions") if isinstance(candidate, dict) else None,
        )
        return merged

    def _merge_string_lists(self, current: Any, candidate: Any) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for value in [*self._normalize_string_list(current), *self._normalize_string_list(candidate)]:
            if value in seen:
                continue
            seen.add(value)
            merged.append(value)
        return merged

    def _build_case_merge_key(self, item: dict[str, Any]) -> str | None:
        return (
            self._normalize_optional_str(item.get("case_name"))
            or self._normalize_optional_str(item.get("customer_name"))
        )

    def _merge_keyed_list(
        self,
        current: list[dict[str, Any]],
        candidate: list[dict[str, Any]],
        *,
        build_key: Any,
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        index_map: dict[str, int] = {}
        for source in (current, candidate):
            for item in source:
                if not isinstance(item, dict):
                    continue
                key_value = build_key(item)
                if not key_value:
                    continue
                normalized_key = str(key_value).strip().casefold()
                if not normalized_key:
                    continue
                if normalized_key not in index_map:
                    index_map[normalized_key] = len(merged)
                    merged.append(dict(item))
                    continue
                existing_index = index_map[normalized_key]
                merged[existing_index] = self._merge_prefer_confirmed_value(merged[existing_index], item)
        return merged

    def _merge_snapshot(
        self,
        *,
        current_snapshot: dict[str, Any],
        candidate_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        current = self._normalize_snapshot_for_merge(current_snapshot)
        candidate = self._normalize_snapshot_for_merge(candidate_snapshot)
        return {
            "basic_info": self._merge_basic_info(
                current.get("basic_info", {}),
                candidate.get("basic_info", {}),
            ),
            "products": self._merge_keyed_list(
                current.get("products", []),
                candidate.get("products", []),
                build_key=lambda item: self._normalize_optional_str(item.get("name")),
            ),
            "company_profile": self._merge_prefer_confirmed_value(
                current.get("company_profile"),
                candidate.get("company_profile"),
            ),
            "management_team": self._merge_keyed_list(
                current.get("management_team", []),
                candidate.get("management_team", []),
                build_key=lambda item: self._normalize_optional_str(item.get("name")),
            ),
            "competitors": self._merge_keyed_list(
                current.get("competitors", []),
                candidate.get("competitors", []),
                build_key=lambda item: self._normalize_optional_str(item.get("name")),
            ),
            "authority_honors": self._merge_keyed_list(
                current.get("authority_honors", []),
                candidate.get("authority_honors", []),
                build_key=lambda item: (
                    f"{self._normalize_optional_str(item.get('title'))}|{self._normalize_optional_str(item.get('year'))}"
                ),
            ),
            "customers_cases": self._merge_keyed_list(
                current.get("customers_cases", []),
                candidate.get("customers_cases", []),
                build_key=self._build_case_merge_key,
            ),
            "official_malls": self._merge_keyed_list(
                current.get("official_malls", []),
                candidate.get("official_malls", []),
                build_key=lambda item: (
                    self._normalize_optional_str(item.get("store_name"))
                    or self._normalize_optional_str(item.get("platform"))
                ),
            ),
            "official_media_matrix": self._merge_keyed_list(
                current.get("official_media_matrix", []),
                candidate.get("official_media_matrix", []),
                build_key=self._build_media_account_merge_key,
            ),
            "sensitive_topics": {
                key: self._merge_string_lists(
                    current.get("sensitive_topics", {}).get(key),
                    candidate.get("sensitive_topics", {}).get(key),
                )
                for key in (
                    "sensitive_contents",
                    "controversial_events",
                    "forbidden_words",
                    "negative_clarifications",
                    "other_info",
                )
            },
            "attachments": self._normalize_attachment_entries(
                [*current.get("attachments", []), *candidate.get("attachments", [])]
            ),
            "other_info": self._merge_other_info_entries(
                current.get("other_info"),
                candidate.get("other_info"),
            ),
        }

    def _build_update_payload_for_confirm_merge(
        self,
        *,
        merged_snapshot: dict[str, Any],
        candidate_snapshot: dict[str, Any],
        current_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "basic_info": merged_snapshot.get("basic_info") or {},
            "skip_attachment_document_sync": True,
        }
        if self._has_meaningful_payload(candidate_snapshot.get("products")):
            existing_names = self._product_name_keys(current_snapshot.get("products"))
            existing_products = [
                product
                for product in self._normalize_products_for_merge(merged_snapshot.get("products"))
                if (self._normalize_optional_str(product.get("name")) or "").casefold() in existing_names
            ]
            if existing_products:
                payload["products"] = existing_products
        if self._has_meaningful_payload(candidate_snapshot.get("company_profile")):
            payload["company_profile"] = merged_snapshot.get("company_profile") or {}
        if self._has_meaningful_payload(candidate_snapshot.get("management_team")):
            payload["management_team"] = merged_snapshot.get("management_team") or []
        if self._has_meaningful_payload(candidate_snapshot.get("competitors")):
            payload["competitors"] = normalize_competitors_for_storage(merged_snapshot.get("competitors") or [])
        if self._has_meaningful_payload(candidate_snapshot.get("authority_honors")):
            payload["authority_honors"] = merged_snapshot.get("authority_honors") or []
        if self._has_meaningful_payload(candidate_snapshot.get("customers_cases")):
            payload["customers_cases"] = merged_snapshot.get("customers_cases") or []
        if self._has_meaningful_payload(candidate_snapshot.get("official_malls")):
            payload["official_malls"] = merged_snapshot.get("official_malls") or []
        if self._has_meaningful_payload(candidate_snapshot.get("official_media_matrix")):
            payload["official_media_matrix"] = merged_snapshot.get("official_media_matrix") or []
        if self._has_meaningful_payload(candidate_snapshot.get("sensitive_topics")):
            payload["sensitive_topics"] = merged_snapshot.get("sensitive_topics") or {}
        if self._has_meaningful_payload(candidate_snapshot.get("other_info")):
            payload["other_info"] = merged_snapshot.get("other_info") or []
        payload["attachments"] = merged_snapshot.get("attachments") or []
        return payload

    def _product_name_keys(self, products: Any) -> set[str]:
        return {
            (self._normalize_optional_str(product.get("name")) or "").casefold()
            for product in self._normalize_products_for_merge(products)
            if self._normalize_optional_str(product.get("name"))
        }

    def _load_attachment_products(self, *, brand_id: int) -> list[dict[str, Any]]:
        try:
            rows = self._deps.brand_knowledge.get_all_brand_knowledge_json(brand_id=brand_id)
        except AttributeError:
            return []
        for row in rows:
            if str(row.get("knowledge_type") or "").strip() != self.ATTACHMENT_PRODUCTS_KNOWLEDGE_TYPE:
                continue
            return self._normalize_products_for_merge(
                self._parse_json_value(row.get("content_json"), [])
            )
        return []

    def _merge_attachment_products(
        self,
        *,
        existing_attachment_products: list[dict[str, Any]],
        new_attachment_products: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        index_by_name: dict[str, int] = {}

        def add_or_merge(product: dict[str, Any]) -> None:
            name = self._normalize_optional_str(product.get("name"))
            if not name:
                return
            key = name.casefold()
            normalized = self._normalize_products_for_merge([{**product, "name": name}])
            if not normalized:
                return
            product_payload = normalized[0]
            if key not in index_by_name:
                index_by_name[key] = len(merged)
                merged.append(product_payload)
                return
            existing = merged[index_by_name[key]]
            for field, value in product_payload.items():
                if field == "name":
                    continue
                if isinstance(value, list):
                    current_values = existing.get(field)
                    if not isinstance(current_values, list):
                        current_values = []
                    seen_values = {str(item).strip() for item in current_values if str(item).strip()}
                    for item in value:
                        normalized_item = str(item).strip()
                        if normalized_item and normalized_item not in seen_values:
                            current_values.append(normalized_item)
                            seen_values.add(normalized_item)
                    existing[field] = current_values
                elif value and not existing.get(field):
                    existing[field] = value

        for product in existing_attachment_products:
            add_or_merge(product)
        for product in new_attachment_products:
            add_or_merge(product)
        return merged

    def _build_new_attachment_products(
        self,
        *,
        current_snapshot: dict[str, Any],
        candidate_snapshot: dict[str, Any],
        existing_attachment_products: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        upstream_names = self._product_name_keys(current_snapshot.get("products"))
        existing_attachment_names = self._product_name_keys(existing_attachment_products or [])
        existing_names = upstream_names | existing_attachment_names
        new_products: list[dict[str, Any]] = []
        seen_names: set[str] = set()

        candidate_products = [
            *self._normalize_products_for_merge(candidate_snapshot.get("products")),
            *self._extract_attachment_products_from_other_info(candidate_snapshot.get("other_info")),
        ]
        for product in candidate_products:
            name = self._normalize_optional_str(product.get("name"))
            if not name:
                continue
            key = name.casefold()
            if key in existing_names or key in seen_names:
                continue
            seen_names.add(key)
            new_products.append(product)
        return new_products

    def _extract_attachment_products_from_other_info(self, other_info: Any) -> list[dict[str, Any]]:
        products: list[dict[str, Any]] = []
        for item in self._normalize_other_info_for_merge(other_info):
            if self._normalize_optional_str(item.get("title")) != self.ATTACHMENT_PRODUCTS_OTHER_INFO_TITLE:
                continue
            content = item.get("content")
            raw_products = content if isinstance(content, list) else [content]
            products.extend(self._normalize_products_for_merge(raw_products))
        return products

    def _keep_upstream_products_in_products(
        self,
        *,
        candidate_snapshot: dict[str, Any],
        current_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        upstream_names = self._product_name_keys(current_snapshot.get("products"))
        if not upstream_names:
            next_snapshot = dict(candidate_snapshot)
            next_snapshot.pop("products", None)
            return next_snapshot
        if not self._has_meaningful_payload(candidate_snapshot.get("products")):
            return candidate_snapshot
        next_snapshot = dict(candidate_snapshot)
        products = [
            product
            for product in self._normalize_products_for_merge(candidate_snapshot.get("products"))
            if (self._normalize_optional_str(product.get("name")) or "").casefold() in upstream_names
        ]
        if products:
            next_snapshot["products"] = products
        else:
            next_snapshot.pop("products", None)
        return next_snapshot

    def _upsert_attachment_products(
        self,
        *,
        brand_id: int,
        products: list[dict[str, Any]],
    ) -> None:
        self._deps.brand_knowledge.upsert_brand_knowledge_json(
            brand_id=brand_id,
            knowledge_type=self.ATTACHMENT_PRODUCTS_KNOWLEDGE_TYPE,
            content_json=products,
            source_task_id=None,
        )

    def _append_new_attachment_products_to_other_info(
        self,
        *,
        candidate_snapshot: dict[str, Any],
        new_attachment_products: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not new_attachment_products:
            return candidate_snapshot
        next_snapshot = dict(candidate_snapshot)
        other_info = list(next_snapshot.get("other_info")) if isinstance(next_snapshot.get("other_info"), list) else []
        other_info.append(
            {
                "title": self.ATTACHMENT_PRODUCTS_OTHER_INFO_TITLE,
                "content": [
                    self._prune_empty_payload(
                        {
                            "name": product.get("name"),
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
                            "other_info": product.get("other_info"),
                        }
                    )
                    for product in new_attachment_products
                    if self._normalize_optional_str(product.get("name"))
                ],
            }
        )
        next_snapshot["other_info"] = other_info
        return next_snapshot
