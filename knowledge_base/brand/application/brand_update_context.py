from __future__ import annotations

from typing import Any


class BrandKnowledgeUpdateContextMixin:
    def _align_brand_name_with_brand_code_for_update(
        self,
        *,
        brand_code: str | None,
        brand_name: str,
    ) -> dict[str, Any] | None:
        normalized_brand_code = self._normalize_str(brand_code)
        normalized_brand_name = self._normalize_str(brand_name)
        if not normalized_brand_code or not normalized_brand_name:
            return None

        existing_brand = self._deps.brands.get_brand_by_code(normalized_brand_code)
        if existing_brand is None:
            return None

        current_brand_name = self._brand_name_from_row(existing_brand)
        if current_brand_name and current_brand_name != normalized_brand_name:
            self.rename_brand(
                brand_code=normalized_brand_code,
                new_brand_name=normalized_brand_name,
            )
            refreshed_brand = self._deps.brands.get_brand_by_code(normalized_brand_code)
            if refreshed_brand is not None:
                return refreshed_brand
        return existing_brand

    def _resolve_existing_brand_for_update(
        self,
        *,
        brand_code: str | None,
        brand_name: str,
    ) -> dict[str, Any] | None:
        existing_brand = None
        if brand_code:
            existing_brand = self._deps.brands.get_brand_by_code(brand_code)
        if existing_brand is None:
            existing_brand = self._deps.brands.get_brand_by_name(brand_name)
        return existing_brand

    def _load_update_snapshot(
        self,
        *,
        existing_brand: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, Any], Any, list[dict[str, Any]]]:
        knowledge_map: dict[str, Any] = {}
        existing_attachments: Any = []
        existing_attachment_products: list[dict[str, Any]] = []
        existing_brand_id, existing_products, _knowledge_rows, knowledge_map = self._load_brand_snapshot(
            brand=existing_brand
        )
        if existing_brand_id is not None:
            existing_attachments = knowledge_map.get("attachments") or []
            existing_attachment_products = self._normalize_attachment_products(
                knowledge_map.get(self.ATTACHMENT_PRODUCTS_KNOWLEDGE_TYPE)
            )
        return existing_products, knowledge_map, existing_attachments, existing_attachment_products

    def _build_brand_upsert_payload(
        self,
        *,
        basic_info: Any,
        brand_code: str | None,
        brand_name: str,
        normalized_company_profile: Any,
    ) -> dict[str, Any]:
        brand_alias = self._normalize_str(basic_info.brand_alias) if self._field_was_provided(basic_info, "brand_alias") else None
        brand_logo = self._normalize_str(basic_info.brand_logo) if self._field_was_provided(basic_info, "brand_logo") else None
        website = self._serialize_websites(basic_info.website) if self._field_was_provided(basic_info, "website") else None
        customer_service_hotline = (
            self._normalize_customer_service_hotline(basic_info.customer_service_hotline)
            if self._field_was_provided(basic_info, "customer_service_hotline")
            else None
        )
        official_wechat_account = (
            self._normalize_str(basic_info.official_wechat_account)
            if self._field_was_provided(basic_info, "official_wechat_account")
            else None
        )
        intro = self._normalize_str(basic_info.intro) if self._field_was_provided(basic_info, "intro") else None
        email = self._normalize_str(basic_info.email) if self._field_was_provided(basic_info, "email") else None
        brand_enterprise_entity = (
            self._normalize_str(basic_info.brand_enterprise_entity)
            if self._field_was_provided(basic_info, "brand_enterprise_entity")
            else None
        )
        business_license_image_path = (
            self._normalize_str(basic_info.business_license_image_path)
            if self._field_was_provided(basic_info, "business_license_image_path")
            else None
        )
        if business_license_image_path is None and isinstance(normalized_company_profile, dict):
            business_license_image_path = self._normalize_str(
                normalized_company_profile.get("business_license_image_path")
            )
        industry_id = self._normalize_int(basic_info.industry_id) if self._field_was_provided(basic_info, "industry_id") else None
        english_name = self._normalize_str(basic_info.english_name) if self._field_was_provided(basic_info, "english_name") else None
        positioning = (
            self._normalize_brand_text_multi_value(basic_info.positioning)
            if self._field_was_provided(basic_info, "positioning")
            else None
        )
        advantages = (
            self._normalize_brand_text_multi_value(basic_info.advantages)
            if self._field_was_provided(basic_info, "advantages")
            else None
        )
        mission = (
            self._normalize_brand_text_multi_value(basic_info.mission)
            if self._field_was_provided(basic_info, "mission")
            else None
        )
        vision = (
            self._normalize_brand_text_multi_value(basic_info.vision)
            if self._field_was_provided(basic_info, "vision")
            else None
        )
        target_regions = (
            [item.strip() for item in basic_info.target_regions if item.strip()]
            if self._field_was_provided(basic_info, "target_regions")
            else None
        )
        other_info = (
            self._normalize_brand_other_info_str(basic_info.other_info)
            if self._field_was_provided(basic_info, "other_info")
            else None
        )
        return {
            "brand_code": brand_code,
            "brand_name": brand_name,
            "brand_alias": brand_alias,
            "brand_logo": brand_logo,
            "website": website,
            "customer_service_hotline": customer_service_hotline,
            "official_wechat_account": official_wechat_account,
            "intro": intro,
            "email": email,
            "brand_enterprise_entity": brand_enterprise_entity,
            "business_license_image_path": business_license_image_path,
            "industry_id": industry_id,
            "english_name": english_name,
            "positioning": positioning,
            "advantages": advantages,
            "mission": mission,
            "vision": vision,
            "target_regions": target_regions,
            "other_info": other_info,
            "competitors": None,
        }

    def _track_brand_update(
        self,
        *,
        existing_brand: dict[str, Any],
        brand_upsert_payload: dict[str, Any],
        structured_update_entries: list[dict[str, Any]],
        structured_change_details: list[dict[str, Any]],
    ) -> bool:
        brand_has_change = self._brand_payload_has_positive_change(existing_brand, brand_upsert_payload)
        changed_brand_payload = self._changed_brand_payload(existing_brand, brand_upsert_payload)
        refreshable_changed_brand_payload = {
            key: value
            for key, value in changed_brand_payload.items()
            if key != "industry_id"
        }
        metadata_changed_brand_payload = {
            key: value
            for key, value in changed_brand_payload.items()
            if key == "industry_id"
        }
        if brand_has_change and refreshable_changed_brand_payload:
            self._append_structured_change_detail(
                structured_change_details,
                section="brands",
                title="品牌基础信息",
                action="update",
                before=self._changed_brand_before_payload(existing_brand, refreshable_changed_brand_payload),
                after=refreshable_changed_brand_payload,
            )
            structured_update_entries.append(
                {
                    "section": "brands",
                    "title": "品牌基础信息",
                    "action": "update",
                    "content": refreshable_changed_brand_payload,
                }
            )
        if metadata_changed_brand_payload:
            self._append_structured_change_detail(
                structured_change_details,
                section="brands",
                title="品牌基础信息",
                action="update",
                before=self._changed_brand_before_payload(existing_brand, metadata_changed_brand_payload),
                after=metadata_changed_brand_payload,
                source_type="knowledge_metadata_update",
            )
        return brand_has_change

    def _normalize_request_products(self, products: Any) -> list[dict[str, Any]]:
        if not products:
            return []
        normalized_products: list[dict[str, Any]] = []
        for product in products:
            product_name = self._normalize_str(product.name)
            if not product_name:
                continue
            normalized_products.append(
                {
                    "product_code": self._normalize_str(getattr(product, "product_code", None)),
                    "product_name": product_name,
                    "product_alias": self._normalize_str(product.product_alias),
                    "product_description": self._normalize_str(product.product_description),
                    "product_website": self._normalize_str(product.product_website),
                    "product_images": [item.strip() for item in product.product_images if item.strip()],
                    "price_info": self._normalize_str(product.price_info),
                    "coverage_regions": [item.strip() for item in product.coverage_regions if item.strip()],
                    "product_advantages": self._normalize_str(product.product_advantages),
                    "target_scenarios": self._normalize_str(product.target_scenarios),
                    "service_standard": self._normalize_str(product.service_standard),
                    "service_process": self._normalize_str(product.service_process),
                    "cases_and_reputation": self._normalize_str(product.cases_and_reputation),
                    "certification_info": self._normalize_str(product.certification_info),
                    "core_technology": self._normalize_str(product.core_technology),
                    "other_info": self._normalize_str(product.other_info),
                }
            )
        return normalized_products

    def _apply_product_updates(
        self,
        *,
        request_products: Any,
        existing_products: list[dict[str, Any]],
        resolved_brand_id: int,
        brand_name: str,
        updated_sections: list[str],
        deleted_sections: list[str],
        structured_update_entries: list[dict[str, Any]],
        structured_change_details: list[dict[str, Any]],
    ) -> bool:
        normalized_products = self._normalize_request_products(request_products)
        if len(normalized_products) != len(request_products):
            raise ValueError("products 中每个产品都必须提供名称")

        normalized_existing_products = self._normalize_existing_products_for_diff(existing_products)
        next_codes = {product["product_code"] for product in normalized_products if product["product_code"]}
        next_names = {product["product_name"].casefold() for product in normalized_products}
        uncoded_names = {
            product["product_name"].casefold()
            for product in normalized_products if not product["product_code"]
        }
        has_deletion = any(
            (
                product["product_code"] not in next_codes
                and product["product_name"].casefold() not in uncoded_names
            ) if product["product_code"] else product["product_name"].casefold() not in next_names
            for product in normalized_existing_products
        )
        products_has_change = has_deletion or self._product_payload_has_positive_change(existing_products, normalized_products)
        action = "delete" if has_deletion else "update"
        if products_has_change:
            self._append_structured_change_detail(
                structured_change_details,
                section="products",
                title="产品信息",
                action=action,
                before=normalized_existing_products,
                after=normalized_products,
            )
            structured_update_entries.append(
                {
                    "section": "products",
                    "title": "产品信息",
                    "action": action,
                    "content": normalized_products,
                }
            )
        self._deps.brand_products.sync_brand_products(
            brand_id=resolved_brand_id,
            brand_name=brand_name,
            products=normalized_products,
        )
        if products_has_change:
            updated_sections.append("products")
        if has_deletion:
            deleted_sections.append("products")
        return products_has_change

    def _prepare_other_info_update(
        self,
        *,
        request: Any,
        knowledge_map: dict[str, Any],
        existing_attachment_products: list[dict[str, Any]],
    ) -> tuple[Any, bool, list[dict[str, Any]]]:
        other_info_content = request.other_info
        other_info_was_provided = self._field_was_provided(request, "other_info")
        if other_info_was_provided and self._has_meaningful_payload(request.other_info):
            other_info_content = self._merge_other_info_entries(
                knowledge_map.get("other_info"),
                request.other_info,
            )
        attachment_products_override_provided, attachment_products_override = (
            self._extract_attachment_products_override_from_other_info(request.other_info)
            if other_info_was_provided
            else (False, [])
        )
        attachment_products_content = (
            attachment_products_override
            if attachment_products_override_provided
            else existing_attachment_products
        )
        if other_info_was_provided:
            other_info_content = self._rebuild_other_info_with_attachment_products(
                other_info_content,
                attachment_products_content,
            )
        return other_info_content, attachment_products_override_provided, attachment_products_content
