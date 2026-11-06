from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from knowledge_base.brand.competitor_schema import normalize_competitors_for_storage
from knowledge_base.brand.knowledge_extraction import (
    _ATTACHMENT_PRODUCTS_KNOWLEDGE_TYPE,
    _KNOWLEDGE_TYPES,
    _apply_extracted_basic_info_to_brand,
    _filter_other_info_entries,
    _merge_other_info_with_attachment_products,
)


class BrandAiKnowledgeIngestionBackfillMixin:
    async def _backfill_brand_knowledge_json_from_full_markdown(
        self,
        *,
        brand: dict[str, Any],
        brand_name: str,
        markdown_text: str,
        source_name: str,
        source_task_id: str | None,
    ) -> None:
        if self._deps.brand_knowledge is None:
            raise RuntimeError("brand_knowledge 未初始化，无法回补 brand_knowledge_json")
        brand_id = brand.get("id")
        brand_code = str(brand.get("brand_code") or "").strip()
        if brand_id is None:
            raise ValueError("品牌缺少 brand_id，无法回补 brand_knowledge_json")
        if not brand_code:
            raise ValueError("品牌缺少 brand_code，无法回补 brand_knowledge_json")

        existing_snapshot = self._load_existing_brand_knowledge_snapshot(brand_id=int(brand_id))
        incoming_snapshot = await self._extract_brand_knowledge_snapshot_from_markdown(
            brand_name=brand_name,
            markdown_text=markdown_text,
            source_name=source_name,
        )
        merged_snapshot = self._merge_full_markdown_backfill_snapshot(
            existing_snapshot=existing_snapshot,
            incoming_snapshot=incoming_snapshot,
        )
        self._sync_full_markdown_basic_info_to_brand(
            brand=brand,
            incoming_snapshot=incoming_snapshot,
        )
        self._backfill_existing_brand_products_from_full_markdown(
            brand_id=int(brand_id),
            brand_name=brand_name,
            incoming_snapshot=incoming_snapshot,
        )
        merged_attachment_products = self._build_attachment_products_from_full_markdown(
            brand_id=int(brand_id),
            existing_snapshot=existing_snapshot,
            incoming_snapshot=incoming_snapshot,
        )
        merged_snapshot["other_info"] = _merge_other_info_with_attachment_products(
            merged_snapshot.get("other_info"),
            merged_attachment_products,
        )
        merged_snapshot["attachment_products"] = merged_attachment_products
        merged_snapshot["other_info"] = _filter_other_info_entries(
            merged_snapshot.get("other_info"),
            snapshot=merged_snapshot,
        )
        for knowledge_type in _KNOWLEDGE_TYPES:
            self._deps.brand_knowledge.upsert_brand_knowledge_json(
                brand_id=int(brand_id),
                knowledge_type=knowledge_type,
                content_json=merged_snapshot.get(knowledge_type),
                source_task_id=source_task_id,
            )
        self._deps.brand_knowledge.upsert_brand_knowledge_json(
            brand_id=int(brand_id),
            knowledge_type=_ATTACHMENT_PRODUCTS_KNOWLEDGE_TYPE,
            content_json=merged_attachment_products,
            source_task_id=source_task_id,
        )

    def _sync_full_markdown_basic_info_to_brand(
        self,
        *,
        brand: dict[str, Any],
        incoming_snapshot: dict[str, Any],
    ) -> None:
        incoming_basic_info = (
            dict(incoming_snapshot.get("basic_info") or {})
            if isinstance(incoming_snapshot.get("basic_info"), dict)
            else {}
        )
        incoming_company_profile = (
            incoming_snapshot.get("company_profile")
            if isinstance(incoming_snapshot.get("company_profile"), dict)
            else {}
        )
        if not incoming_basic_info and not incoming_company_profile:
            return

        # Empty-only backfill should not expand the brand's canonical website list.
        if self._normalize_optional_str(brand.get("website")):
            incoming_basic_info.pop("website", None)

        service_adapter = SimpleNamespace(_brands=self._deps.brands)
        _apply_extracted_basic_info_to_brand(
            service_adapter,
            brand=brand,
            extracted_basic_info=incoming_basic_info,
            company_profile=incoming_company_profile,
        )

    def _merge_full_markdown_backfill_snapshot(
        self,
        *,
        existing_snapshot: dict[str, Any],
        incoming_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        existing = existing_snapshot if isinstance(existing_snapshot, dict) else {}
        incoming = incoming_snapshot if isinstance(incoming_snapshot, dict) else {}
        merged = self._copy_jsonable(existing)
        merged["basic_info"] = self._prefer_incoming_payload(existing.get("basic_info"), incoming.get("basic_info"))
        merged["company_profile"] = self._prefer_incoming_payload(
            existing.get("company_profile"),
            incoming.get("company_profile"),
        )
        for knowledge_type in (
            "management_team",
            "authority_honors",
            "customers_cases",
            "attachments",
            "official_malls",
            "official_media_matrix",
        ):
            merged[knowledge_type] = self._merge_entity_list(
                existing.get(knowledge_type),
                incoming.get(knowledge_type),
                knowledge_type=knowledge_type,
            )
        merged["other_info"] = self._merge_other_info_entries_by_title(
            existing.get("other_info"),
            incoming.get("other_info"),
        )
        merged["sensitive_topics"] = self._merge_backfill_value(
            existing.get("sensitive_topics"),
            incoming.get("sensitive_topics"),
        )
        merged["competitors"] = self._merge_existing_competitors_only(
            existing.get("competitors"),
            incoming.get("competitors"),
        )
        return merged

    def _merge_existing_competitors_only(
        self,
        existing_value: Any,
        incoming_value: Any,
    ) -> list[dict[str, Any]]:
        existing_competitors = normalize_competitors_for_storage(existing_value)
        incoming_competitors = normalize_competitors_for_storage(incoming_value)
        if not existing_competitors:
            return []
        incoming_by_identity: dict[str, dict[str, Any]] = {}
        for item in incoming_competitors:
            for identity in self._build_competitor_identity_keys(item):
                incoming_by_identity.setdefault(identity, item)
        merged_competitors: list[dict[str, Any]] = []
        for existing_item in existing_competitors:
            merged_item = self._copy_jsonable(existing_item)
            incoming_item = None
            for identity in self._build_competitor_identity_keys(existing_item):
                incoming_item = incoming_by_identity.get(identity)
                if isinstance(incoming_item, dict):
                    break
            if isinstance(incoming_item, dict):
                for key, incoming_field_value in incoming_item.items():
                    merged_item[key] = self._fill_missing_value(
                        merged_item.get(key),
                        incoming_field_value,
                    )
            merged_competitors.append(merged_item)
        return merged_competitors

    def _build_competitor_identity_keys(self, item: dict[str, Any]) -> list[str]:
        identities: list[str] = []
        seen: set[str] = set()
        for raw_value in [item.get("name"), *(item.get("aliases") or [])]:
            normalized = str(raw_value or "").strip().casefold()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            identities.append(normalized)
        return identities

    def _build_attachment_products_from_full_markdown(
        self,
        *,
        brand_id: int,
        existing_snapshot: dict[str, Any],
        incoming_snapshot: dict[str, Any],
    ) -> list[dict[str, Any]]:
        whitelist_products = self._load_brand_products_snapshot(brand_id=brand_id)
        whitelist_names = {
            str(item.get("name") or "").strip().casefold()
            for item in whitelist_products
            if str(item.get("name") or "").strip()
        }
        incoming_products: list[Any] = []
        for incoming_key in (_ATTACHMENT_PRODUCTS_KNOWLEDGE_TYPE, "products"):
            incoming_value = incoming_snapshot.get(incoming_key)
            if isinstance(incoming_value, list):
                incoming_products.extend(incoming_value)
        attachment_products: list[dict[str, Any]] = []
        seen_names: set[str] = set()
        existing_attachment_products = (
            existing_snapshot.get(_ATTACHMENT_PRODUCTS_KNOWLEDGE_TYPE)
            if isinstance(existing_snapshot, dict)
            else []
        )
        for item in existing_attachment_products if isinstance(existing_attachment_products, list) else []:
            if not isinstance(item, dict):
                continue
            normalized_item = self._normalize_attachment_product_item(item)
            name = str(normalized_item.get("name") or "").strip()
            if not name:
                continue
            name_key = name.casefold()
            if name_key in seen_names:
                continue
            seen_names.add(name_key)
            attachment_products.append(normalized_item)
        for item in incoming_products:
            if not isinstance(item, dict):
                continue
            normalized_item = self._normalize_attachment_product_item(item)
            name = str(normalized_item.get("name") or "").strip()
            if not name:
                continue
            name_key = name.casefold()
            if name_key in whitelist_names:
                continue
            if name_key in seen_names:
                existing_index = next(
                    index
                    for index, existing_item in enumerate(attachment_products)
                    if str(existing_item.get("name") or "").strip().casefold() == name_key
                )
                attachment_products[existing_index] = self._merge_entity_payload(
                    attachment_products[existing_index],
                    normalized_item,
                )
                continue
            seen_names.add(name_key)
            attachment_products.append(normalized_item)
        return attachment_products

    @classmethod
    def _merge_other_info_entries_by_title(cls, existing_value: Any, incoming_value: Any) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        index_by_title: dict[str, int] = {}
        for item in existing_value if isinstance(existing_value, list) else []:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or item.get("key") or item.get("name") or "").strip()
            if not title:
                continue
            title_key = title.casefold()
            normalized_item = cls._copy_jsonable(item)
            normalized_item["title"] = title
            index_by_title[title_key] = len(merged)
            merged.append(normalized_item)
        for item in incoming_value if isinstance(incoming_value, list) else []:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or item.get("key") or item.get("name") or "").strip()
            if not title:
                continue
            title_key = title.casefold()
            normalized_item = cls._copy_jsonable(item)
            normalized_item["title"] = title
            if title_key in index_by_title:
                merged[index_by_title[title_key]] = normalized_item
                continue
            index_by_title[title_key] = len(merged)
            merged.append(normalized_item)
        return merged

    def _backfill_existing_brand_products_from_full_markdown(
        self,
        *,
        brand_id: int,
        brand_name: str,
        incoming_snapshot: dict[str, Any],
    ) -> None:
        brand_products = getattr(self._deps, "brand_products", None)
        if brand_products is None or not hasattr(brand_products, "upsert_brand_products"):
            return
        existing_products = self._load_brand_products_snapshot(brand_id=brand_id)
        incoming_products = incoming_snapshot.get("products") if isinstance(incoming_snapshot, dict) else []
        if not existing_products or not isinstance(incoming_products, list):
            return
        incoming_by_identity: dict[str, dict[str, Any]] = {}
        for item in incoming_products:
            if not isinstance(item, dict):
                continue
            normalized_item = self._normalize_attachment_product_item(item)
            for identity in self._entity_identity_keys(normalized_item, knowledge_type="products"):
                incoming_by_identity.setdefault(identity, normalized_item)
        if not incoming_by_identity:
            return
        merged_products: list[dict[str, Any]] = []
        has_change = False
        for existing_item in existing_products:
            merged_item = self._copy_jsonable(existing_item)
            incoming_item = None
            for identity in self._entity_identity_keys(merged_item, knowledge_type="products"):
                incoming_item = incoming_by_identity.get(identity)
                if isinstance(incoming_item, dict):
                    break
            if isinstance(incoming_item, dict):
                merged_item = self._merge_entity_payload(merged_item, incoming_item)
                if merged_item != existing_item:
                    has_change = True
            merged_products.append(merged_item)
        if not has_change:
            return
        brand_products.upsert_brand_products(
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
                    "other_info": product.get("other_info"),
                }
                for product in merged_products
                if self._normalize_optional_str(product.get("name"))
            ],
        )

    def _load_brand_products_snapshot(self, *, brand_id: int) -> list[dict[str, Any]]:
        brand_products = getattr(self._deps, "brand_products", None)
        if brand_products is None or not hasattr(brand_products, "get_brand_products"):
            return []
        rows = brand_products.get_brand_products(brand_id=brand_id)
        if not isinstance(rows, list):
            return []
        products: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = self._normalize_optional_str(row.get("product_name"))
            if not name:
                continue
            products.append(
                {
                    "name": name,
                    "product_alias": self._normalize_optional_str(row.get("product_alias")),
                    "product_description": self._normalize_optional_str(row.get("product_description")),
                    "product_website": self._normalize_optional_str(row.get("product_website")),
                    "product_images": self._normalize_sequence_value(row.get("product_images_json")),
                    "price_info": self._normalize_optional_str(row.get("price_info")),
                    "coverage_regions": self._normalize_sequence_value(row.get("coverage_regions_json")),
                    "product_advantages": self._normalize_optional_str(row.get("product_advantages")),
                    "target_scenarios": self._normalize_optional_str(row.get("target_scenarios")),
                    "service_standard": self._normalize_optional_str(row.get("service_standard")),
                    "service_process": self._normalize_optional_str(row.get("service_process")),
                    "cases_and_reputation": self._normalize_optional_str(row.get("cases_and_reputation")),
                    "certification_info": self._normalize_optional_str(row.get("certification_info")),
                    "core_technology": self._normalize_optional_str(row.get("core_technology")),
                    "other_info": self._normalize_optional_str(row.get("other_info")),
                }
            )
        return products

    def _normalize_attachment_product_item(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": self._normalize_optional_str(item.get("name")),
            "product_alias": self._normalize_optional_str(item.get("product_alias")),
            "product_description": self._normalize_optional_str(item.get("product_description")),
            "product_website": self._normalize_optional_str(item.get("product_website")),
            "product_images": self._normalize_sequence_value(item.get("product_images")),
            "price_info": self._normalize_optional_str(item.get("price_info")),
            "coverage_regions": self._normalize_sequence_value(item.get("coverage_regions")),
            "product_advantages": self._normalize_optional_str(item.get("product_advantages")),
            "target_scenarios": self._normalize_optional_str(item.get("target_scenarios")),
            "service_standard": self._normalize_optional_str(item.get("service_standard")),
            "service_process": self._normalize_optional_str(item.get("service_process")),
            "cases_and_reputation": self._normalize_optional_str(item.get("cases_and_reputation")),
            "certification_info": self._normalize_optional_str(item.get("certification_info")),
            "core_technology": self._normalize_optional_str(item.get("core_technology")),
            "other_info": self._normalize_optional_str(item.get("other_info")),
        }

    def _load_existing_brand_knowledge_snapshot(self, *, brand_id: int) -> dict[str, Any]:
        rows = self._deps.brand_knowledge.get_all_brand_knowledge_json(brand_id=brand_id)
        knowledge_map = {
            str(row.get("knowledge_type") or "").strip(): self._parse_content_json(row.get("content_json"))
            for row in rows
            if str(row.get("knowledge_type") or "").strip()
        }
        return {
            "basic_info": {},
            "company_profile": knowledge_map.get("company_profile") or {},
            "management_team": knowledge_map.get("management_team") or [],
            "competitors": knowledge_map.get("competitors") or [],
            "authority_honors": knowledge_map.get("authority_honors") or [],
            "customers_cases": knowledge_map.get("customers_cases") or [],
            "sensitive_topics": knowledge_map.get("sensitive_topics") or [],
            "attachments": knowledge_map.get("attachments") or [],
            "official_malls": knowledge_map.get("official_malls") or [],
            "official_media_matrix": knowledge_map.get("official_media_matrix") or [],
            "other_info": knowledge_map.get("other_info") or [],
            "attachment_products": knowledge_map.get(_ATTACHMENT_PRODUCTS_KNOWLEDGE_TYPE) or [],
        }

    def _load_existing_attachment_products(self, *, brand_id: int) -> list[dict[str, Any]]:
        rows = self._deps.brand_knowledge.get_all_brand_knowledge_json(brand_id=brand_id)
        for row in rows:
            if str(row.get("knowledge_type") or "").strip() != _ATTACHMENT_PRODUCTS_KNOWLEDGE_TYPE:
                continue
            parsed = self._parse_content_json(row.get("content_json"))
            return parsed if isinstance(parsed, list) else []
        return []

    @staticmethod
    def _parse_content_json(value: Any) -> Any:
        if isinstance(value, (dict, list)):
            return value
        if isinstance(value, str) and value.strip():
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return value

    @staticmethod
    def _is_effectively_empty(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return not value.strip()
        if isinstance(value, (list, tuple, set, dict)):
            return len(value) == 0
        return False

    @classmethod
    def _fill_missing_value(cls, existing_value: Any, incoming_value: Any) -> Any:
        if cls._is_effectively_empty(existing_value):
            return cls._copy_jsonable(incoming_value)
        if isinstance(existing_value, dict) and isinstance(incoming_value, dict):
            merged = cls._copy_jsonable(existing_value)
            for key, incoming_item in incoming_value.items():
                merged[key] = cls._fill_missing_value(merged.get(key), incoming_item)
            return merged
        return cls._copy_jsonable(existing_value)

    @classmethod
    def _merge_backfill_value(cls, existing_value: Any, incoming_value: Any) -> Any:
        if cls._is_effectively_empty(incoming_value):
            return cls._copy_jsonable(existing_value)
        if cls._is_effectively_empty(existing_value):
            return cls._copy_jsonable(incoming_value)
        if isinstance(existing_value, dict) and isinstance(incoming_value, dict):
            merged = cls._copy_jsonable(existing_value)
            for key, incoming_item in incoming_value.items():
                merged[key] = cls._merge_backfill_value(merged.get(key), incoming_item)
            return merged
        if isinstance(existing_value, list) and isinstance(incoming_value, list):
            if all(not isinstance(item, dict) for item in [*existing_value, *incoming_value]):
                return cls._merge_unique_scalar_list(existing_value, incoming_value)
            return cls._merge_entity_list(existing_value, incoming_value, knowledge_type="")
        return cls._prefer_incoming_payload(existing_value, incoming_value)

    @classmethod
    def _merge_unique_scalar_list(cls, existing_value: Any, incoming_value: Any) -> list[Any]:
        merged: list[Any] = []
        seen: set[str] = set()
        for item in [
            *(existing_value if isinstance(existing_value, list) else []),
            *(incoming_value if isinstance(incoming_value, list) else []),
        ]:
            key = cls._value_identity(item)
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(cls._copy_jsonable(item))
        return merged

    @classmethod
    def _merge_entity_list(
        cls,
        existing_value: Any,
        incoming_value: Any,
        *,
        knowledge_type: str,
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        index_by_identity: dict[str, int] = {}

        def add_or_merge(item: Any) -> None:
            if not isinstance(item, dict):
                return
            normalized_item = cls._copy_jsonable(item)
            identities = cls._entity_identity_keys(normalized_item, knowledge_type=knowledge_type)
            existing_index = next(
                (index_by_identity[identity] for identity in identities if identity in index_by_identity),
                None,
            )
            if existing_index is None:
                for identity in identities:
                    index_by_identity.setdefault(identity, len(merged))
                merged.append(normalized_item)
                return
            merged[existing_index] = cls._merge_entity_payload(merged[existing_index], normalized_item)
            for identity in identities:
                index_by_identity.setdefault(identity, existing_index)

        for item in existing_value if isinstance(existing_value, list) else []:
            add_or_merge(item)
        for item in incoming_value if isinstance(incoming_value, list) else []:
            add_or_merge(item)
        return merged

    @classmethod
    def _merge_entity_payload(cls, existing_item: dict[str, Any], incoming_item: dict[str, Any]) -> dict[str, Any]:
        merged = cls._copy_jsonable(existing_item)
        for key, incoming_value in incoming_item.items():
            existing_value = merged.get(key)
            if isinstance(existing_value, list) and isinstance(incoming_value, list):
                merged[key] = cls._merge_unique_scalar_list(existing_value, incoming_value)
            elif isinstance(existing_value, dict) and isinstance(incoming_value, dict):
                merged[key] = cls._merge_entity_payload(existing_value, incoming_value)
            else:
                merged[key] = cls._fill_missing_value(existing_value, incoming_value)
        return merged

    @classmethod
    def _entity_identity_keys(cls, item: dict[str, Any], *, knowledge_type: str) -> list[str]:
        values: list[Any]
        if knowledge_type in {"management_team"}:
            values = [item.get("name"), item.get("member_name")]
        elif knowledge_type in {"products", _ATTACHMENT_PRODUCTS_KNOWLEDGE_TYPE}:
            values = [item.get("name"), item.get("product_name"), item.get("product_alias")]
        elif knowledge_type == "attachments":
            values = [
                cls._join_identity_parts(item.get("name"), item.get("url")),
                item.get("name"),
                item.get("url"),
            ]
        elif knowledge_type == "official_malls":
            values = [
                cls._join_identity_parts(item.get("platform"), item.get("store_name")),
                item.get("store_name"),
                item.get("url"),
            ]
        elif knowledge_type == "official_media_matrix":
            values = [
                cls._join_identity_parts(item.get("platform"), item.get("account_name")),
                cls._join_identity_parts(item.get("media_platform"), item.get("account_name")),
                cls._join_identity_parts(item.get("platform"), item.get("account_id")),
                item.get("account_name"),
                item.get("account_id"),
            ]
        elif knowledge_type == "authority_honors":
            values = [
                cls._join_identity_parts(item.get("title"), item.get("year")),
                cls._join_identity_parts(item.get("name"), item.get("year")),
                item.get("title"),
                item.get("name"),
            ]
        elif knowledge_type == "customers_cases":
            values = [
                cls._join_identity_parts(item.get("title"), item.get("customer_name")),
                cls._join_identity_parts(item.get("case_name"), item.get("customer_name")),
                item.get("title"),
                item.get("case_name"),
            ]
        elif knowledge_type == "other_info":
            values = [item.get("title"), item.get("key"), item.get("name")]
        else:
            values = [item.get("name"), item.get("title"), item.get("id")]
        identities: list[str] = []
        seen: set[str] = set()
        for raw_value in values:
            normalized = cls._value_identity(raw_value)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            identities.append(normalized)
        if identities:
            return identities
        fallback = cls._value_identity(item)
        return [fallback] if fallback else []

    @classmethod
    def _join_identity_parts(cls, *parts: Any) -> str | None:
        normalized_parts = [cls._value_identity(part) for part in parts]
        normalized_parts = [part for part in normalized_parts if part]
        if len(normalized_parts) != len(parts):
            return None
        return "::".join(normalized_parts)

    @staticmethod
    def _value_identity(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip().casefold()
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True).strip().casefold()
        except TypeError:
            return str(value).strip().casefold()

    @classmethod
    def _prefer_incoming_payload(cls, existing_value: Any, incoming_value: Any) -> Any:
        if cls._is_effectively_empty(incoming_value):
            return cls._copy_jsonable(existing_value)
        if isinstance(existing_value, dict) and isinstance(incoming_value, dict):
            merged = cls._copy_jsonable(existing_value)
            for key, incoming_item in incoming_value.items():
                merged[key] = cls._prefer_incoming_payload(merged.get(key), incoming_item)
            return merged
        return cls._copy_jsonable(incoming_value)

    @classmethod
    def _copy_jsonable(cls, value: Any) -> Any:
        if value is None:
            return None
        return json.loads(json.dumps(value, ensure_ascii=False))

    @staticmethod
    def _normalize_optional_str(value: Any) -> str | None:
        normalized = str(value).strip() if value is not None else ""
        return normalized or None

    @classmethod
    def _normalize_sequence_value(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            parsed = cls._parse_content_json(value)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
            normalized = value.strip()
            return [normalized] if normalized else []
        if isinstance(value, (list, tuple, set)):
            return [str(item).strip() for item in value if str(item).strip()]
        return []
