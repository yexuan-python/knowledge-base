from __future__ import annotations

from typing import Any


class AttachmentDraftSnapshotContextMixin:
    def _resolve_brand_record(
        self,
        *,
        brand_code: str | None,
        brand_name: str,
    ) -> dict[str, Any]:
        normalized_brand_code = str(brand_code or "").strip()
        normalized_brand_name = str(brand_name or "").strip()
        brand = None
        if normalized_brand_code:
            brand = self._deps.brands.get_brand_by_code(normalized_brand_code)
        if brand is None and normalized_brand_name:
            brand = self._deps.brands.get_brand_by_name(normalized_brand_name)
        if not isinstance(brand, dict):
            raise ValueError("没有这个品牌，无法对比现有知识")
        return brand

    def _build_current_snapshot(
        self,
        *,
        brand: dict[str, Any],
    ) -> tuple[dict[str, Any], str | None]:
        brand_id = brand.get("id")
        if brand_id is None:
            raise ValueError("品牌数据缺少 brand_id")

        products = self._deps.brand_products.get_brand_products(brand_id=int(brand_id))
        knowledge_rows = self._deps.brand_knowledge.get_all_brand_knowledge_json(brand_id=int(brand_id))
        knowledge_map = {
            str(row.get("knowledge_type") or "").strip(): self._parse_json_value(row.get("content_json"), None)
            for row in knowledge_rows
            if str(row.get("knowledge_type") or "").strip()
        }

        snapshot = {
            "basic_info": {
                "brand_code": self._normalize_optional_str(brand.get("brand_code")),
                "brand_name": self._normalize_optional_str(brand.get("brand_name")),
                "brand_alias": self._normalize_optional_str(brand.get("brand_alias")),
                "brand_logo": self._normalize_optional_str(brand.get("brand_logo")),
                "website": self._normalize_string_list(brand.get("website")),
                "customer_service_hotline": self._normalize_customer_service_hotline_list(
                    brand.get("customer_service_hotline")
                ),
                "official_wechat_account": self._normalize_optional_str(brand.get("official_wechat_account")),
                "intro": self._normalize_optional_str(brand.get("intro")),
                "email": self._normalize_optional_str(brand.get("email")),
                "brand_enterprise_entity": self._normalize_optional_str(brand.get("brand_enterprise_entity")),
                "business_license_image_path": self._normalize_optional_str(brand.get("business_license_image_path")),
                "industry_id": self._normalize_optional_str(brand.get("industry_id")),
                "english_name": self._normalize_optional_str(brand.get("english_name")),
                "positioning": self._normalize_string_list(brand.get("positioning")),
                "advantages": self._normalize_string_list(brand.get("advantages")),
                "mission": self._normalize_string_list(brand.get("mission")),
                "vision": self._normalize_string_list(brand.get("vision")),
                "target_regions": self._normalize_string_list(brand.get("target_regions_json")),
                "other_info": self._normalize_optional_str(brand.get("other_info")),
            },
            "products": [
                {
                    "name": self._normalize_optional_str(product.get("product_name")),
                    "product_alias": self._normalize_optional_str(product.get("product_alias")),
                    "product_description": self._normalize_optional_str(product.get("product_description")),
                    "product_website": self._normalize_optional_str(product.get("product_website")),
                    "product_images": self._normalize_string_list(product.get("product_images_json")),
                    "price_info": self._normalize_optional_str(product.get("price_info")),
                    "coverage_regions": self._normalize_string_list(product.get("coverage_regions_json")),
                    "product_advantages": self._normalize_optional_str(product.get("product_advantages")),
                    "target_scenarios": self._normalize_optional_str(product.get("target_scenarios")),
                    "service_standard": self._normalize_optional_str(product.get("service_standard")),
                    "service_process": self._normalize_optional_str(product.get("service_process")),
                    "cases_and_reputation": self._normalize_optional_str(product.get("cases_and_reputation")),
                    "certification_info": self._normalize_optional_str(product.get("certification_info")),
                    "core_technology": self._normalize_optional_str(product.get("core_technology")),
                    "other_info": self._normalize_optional_str(product.get("other_info")),
                }
                for product in products
                if self._normalize_optional_str(product.get("product_name"))
            ],
            "company_profile": self._parse_json_value(knowledge_map.get("company_profile"), {}) or {},
            "management_team": self._parse_json_value(knowledge_map.get("management_team"), []) or [],
            "competitors": self._parse_json_value(knowledge_map.get("competitors"), []) or [],
            "authority_honors": self._parse_json_value(knowledge_map.get("authority_honors"), []) or [],
            "customers_cases": self._parse_json_value(knowledge_map.get("customers_cases"), []) or [],
            "official_malls": self._parse_json_value(knowledge_map.get("official_malls"), []) or [],
            "official_media_matrix": self._parse_json_value(knowledge_map.get("official_media_matrix"), []) or [],
            "sensitive_topics": self._parse_json_value(knowledge_map.get("sensitive_topics"), {}) or {},
            "attachments": self._normalize_attachment_entries(
                self._parse_json_value(knowledge_map.get("attachments"), []) or []
            ),
            "other_info": self._normalize_other_info_for_merge(knowledge_map.get("other_info")),
        }
        knowledge_revision = self._normalize_optional_str(brand.get("knowledge_revision"))
        return snapshot, knowledge_revision

    def _build_empty_snapshot(self, *, brand_name: str | None = None, brand_code: str | None = None) -> dict[str, Any]:
        return {
            "basic_info": {
                "brand_code": self._normalize_optional_str(brand_code),
                "brand_name": self._normalize_optional_str(brand_name),
            },
            "products": [],
            "company_profile": {},
            "management_team": [],
            "competitors": [],
            "authority_honors": [],
            "customers_cases": [],
            "official_malls": [],
            "official_media_matrix": [],
            "sensitive_topics": self._normalize_sensitive_topics_for_merge({}),
            "attachments": [],
            "other_info": [],
        }

    def _try_build_current_snapshot(
        self,
        *,
        brand_code: str | None,
        brand_name: str,
    ) -> tuple[dict[str, Any], str | None, dict[str, Any] | None]:
        try:
            brand = self._resolve_brand_record(brand_code=brand_code, brand_name=brand_name)
            current_snapshot, knowledge_revision = self._build_current_snapshot(brand=brand)
            return current_snapshot, knowledge_revision, brand
        except (AttributeError, ValueError):
            return self._build_empty_snapshot(brand_name=brand_name, brand_code=brand_code), None, None
