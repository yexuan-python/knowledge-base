from __future__ import annotations

from typing import Any


class AttachmentDraftSnapshotPayloadMixin:
    def _build_update_payload_from_extracted(
        self,
        *,
        extracted: dict[str, Any],
        brand_name: str,
        brand_code: str | None,
        draft_attachments: list[dict[str, Any]],
        current_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        raw_basic_info = extracted.get("basic_info") if isinstance(extracted.get("basic_info"), dict) else {}
        raw_company_profile = (
            extracted.get("company_profile") if isinstance(extracted.get("company_profile"), dict) else {}
        )
        industry_other_info_titles = {"所属行业", "行业"}
        extracted_other_info = self._exclude_other_info_titles(
            extracted.get("other_info"),
            industry_other_info_titles,
        )
        industry_from_other_info = self._extract_other_info_text_by_titles(
            extracted.get("other_info"),
            industry_other_info_titles,
        )

        basic_info = {
            "brand_code": self._normalize_optional_str(brand_code),
            "brand_name": brand_name,
            "industry_id": self._normalize_optional_str(raw_basic_info.get("industry_id")) or industry_from_other_info,
            "website": self._normalize_string_list(raw_basic_info.get("website")),
            "customer_service_hotline": self._normalize_customer_service_hotline_list(
                raw_basic_info.get("customer_service_hotline")
            ),
            "official_wechat_account": self._normalize_optional_str(raw_basic_info.get("official_wechat_account")),
            "email": self._normalize_optional_str(raw_basic_info.get("email")),
            "brand_enterprise_entity": self._normalize_optional_str(raw_company_profile.get("brand_subject_name")),
            "business_license_image_path": self._normalize_optional_str(raw_company_profile.get("business_license_image_path")),
            "english_name": self._normalize_optional_str(raw_basic_info.get("english_name")),
            "positioning": self._normalize_string_list(raw_basic_info.get("positioning")),
            "advantages": self._normalize_string_list(raw_basic_info.get("advantages")),
            "mission": self._normalize_string_list(raw_basic_info.get("mission")),
            "vision": self._normalize_string_list(raw_basic_info.get("vision")),
            "target_regions": self._normalize_string_list(raw_basic_info.get("target_regions")),
        }

        existing_products = (
            current_snapshot.get("products")
            if isinstance(current_snapshot.get("products"), list) else []
        )
        _, product_name_alias_map = self._build_entity_scope_map(
            existing_products,
            name_field="name",
            alias_field="product_alias",
        )

        products: list[dict[str, Any]] = []
        seen_product_names: set[str] = set()
        for item in extracted.get("products", []):
            if not isinstance(item, dict):
                continue
            extracted_product_name = self._normalize_optional_str(item.get("name"))
            if not extracted_product_name:
                continue
            product_name = product_name_alias_map.get(extracted_product_name.casefold()) or extracted_product_name
            if product_name in seen_product_names:
                continue
            seen_product_names.add(product_name)
            products.append(
                {
                    "name": product_name,
                    "product_alias": self._normalize_optional_str(item.get("product_alias")),
                    "product_description": self._normalize_optional_str(item.get("product_description")),
                    "product_website": self._normalize_optional_str(item.get("product_website")),
                    "product_images": self._normalize_string_list(item.get("product_images")),
                    "price_info": self._normalize_optional_str(item.get("price_info")),
                    "coverage_regions": self._normalize_string_list(item.get("coverage_regions")),
                    "product_advantages": self._normalize_optional_str(item.get("product_advantages")),
                    "target_scenarios": self._normalize_optional_str(item.get("target_scenarios")),
                    "service_standard": self._normalize_optional_str(item.get("service_standard")),
                    "service_process": self._normalize_optional_str(item.get("service_process")),
                    "cases_and_reputation": self._normalize_optional_str(item.get("cases_and_reputation")),
                    "certification_info": self._normalize_optional_str(item.get("certification_info")),
                    "core_technology": self._normalize_optional_str(item.get("core_technology")),
                    "other_info": self._normalize_optional_str(item.get("other_info")),
                }
            )

        company_profile = {
            "brand_subject_name": self._normalize_optional_str(raw_company_profile.get("brand_subject_name")),
            "business_license_image_path": self._normalize_optional_str(raw_company_profile.get("business_license_image_path")),
            "company_address": self._normalize_optional_str(raw_company_profile.get("company_address")),
            "company_intro": self._normalize_optional_str(raw_company_profile.get("company_intro")),
            "established_time": self._normalize_optional_str(raw_company_profile.get("established_time")),
            "store_distribution": self._normalize_optional_str(raw_company_profile.get("store_distribution")),
            "recent_news": self._normalize_optional_str(raw_company_profile.get("recent_news")),
            "development_concept": self._normalize_optional_str(raw_company_profile.get("development_concept")),
            "corporate_values": self._normalize_optional_str(raw_company_profile.get("corporate_values")),
            "company_mission": self._normalize_optional_str(raw_company_profile.get("company_mission")),
            "development_history": self._normalize_optional_str(raw_company_profile.get("development_history")),
            "other_info": self._normalize_optional_str(raw_company_profile.get("other_info")),
        }

        management_team = [
            {
                "name": self._normalize_optional_str(item.get("member_name")),
                "title": self._normalize_optional_str(item.get("position")),
                "profile": self._normalize_optional_str(item.get("profile")),
                "introduction_website": self._normalize_optional_str(item.get("introduction_website")),
                "source_section": self._normalize_optional_str(item.get("source_section")),
            }
            for item in extracted.get("management_team", [])
            if isinstance(item, dict) and self._normalize_optional_str(item.get("member_name"))
        ]

        existing_competitors = (
            current_snapshot.get("competitors")
            if isinstance(current_snapshot.get("competitors"), list) else []
        )
        _, competitor_name_alias_map = self._build_entity_scope_map(
            existing_competitors,
            name_field="name",
            alias_field="aliases",
        )
        competitors: list[dict[str, Any]] = []
        seen_competitor_names: set[str] = set()
        for item in extracted.get("competitors", []):
            if not isinstance(item, dict):
                continue
            extracted_competitor_name = self._normalize_optional_str(item.get("name"))
            if not extracted_competitor_name:
                continue
            competitor_name = (
                competitor_name_alias_map.get(extracted_competitor_name.casefold()) or extracted_competitor_name
            )
            if competitor_name in seen_competitor_names:
                continue
            seen_competitor_names.add(competitor_name)
            competitors.append(
                {
                    "name": competitor_name,
                    "aliases": self._normalize_string_list(item.get("aliases") or item.get("competitors_alias")),
                    "introduction": self._normalize_optional_str(
                        item.get("introduction") or item.get("competitors_description")
                    ),
                    "official_websites": self._normalize_string_list(
                        item.get("official_websites") or item.get("website")
                    ),
                    "logo_urls": self._normalize_string_list(item.get("logo_urls") or item.get("competitors_logo")),
                    "strengths": self._normalize_string_list(
                        item.get("strengths") or item.get("competitive_advantages")
                    ),
                    "differentiated_positioning": self._normalize_string_list(item.get("differentiated_positioning")),
                    "comparison_dimensions": self._normalize_string_list(item.get("comparison_dimensions")),
                    "source_section": self._normalize_optional_str(item.get("source_section")),
                }
            )

        authority_honors: list[dict[str, Any]] = []
        for item in extracted.get("authority_honors", []):
            if not isinstance(item, dict):
                continue
            title = self._normalize_optional_str(item.get("title"))
            if not title:
                continue
            description = self._normalize_optional_str(item.get("description"))
            authority_honors.append(
                {
                    "title": title,
                    "year": self._prefer_specific_award_date(
                        item.get("year"),
                        title,
                        description,
                    ),
                    "description": description,
                    "report_link": self._normalize_optional_str(item.get("report_link")),
                    "qualification_proof": self._normalize_optional_str(item.get("qualification_proof")),
                    "source_section": self._normalize_optional_str(item.get("source_section")),
                }
            )

        customers_cases = [
            {
                "case_name": self._normalize_optional_str(item.get("case_name")),
                "cooperation_time": self._normalize_optional_str(item.get("cooperation_time")),
                "customer_name": self._normalize_optional_str(item.get("customer_name")),
                "cooperation_product": self._normalize_optional_str(item.get("cooperation_product")),
                "cooperation_highlight": self._normalize_optional_str(item.get("cooperation_highlight")),
                "customer_feedback": self._normalize_optional_str(item.get("customer_feedback")),
                "source_section": self._normalize_optional_str(item.get("source_section")),
            }
            for item in extracted.get("customers_cases", [])
            if isinstance(item, dict)
            and (
                self._normalize_optional_str(item.get("case_name"))
                or self._normalize_optional_str(item.get("customer_name"))
            )
        ]

        sensitive_topics = {
            "sensitive_contents": self._normalize_text_list_from_dicts(extracted.get("sensitive_topics"), "topic"),
            "controversial_events": self._normalize_text_list_from_dicts(
                extracted.get("sensitive_topics"),
                "description",
            ),
            "forbidden_words": self._normalize_text_list_from_dicts(
                extracted.get("sensitive_topics"),
                "forbidden_terms",
            ),
            "negative_clarifications": self._normalize_text_list_from_dicts(
                extracted.get("sensitive_topics"),
                "history_negative_clarification",
            ),
            "other_info": [],
        }
        official_malls = [
            {
                "store_name": self._normalize_optional_str(item.get("store_name")),
                "platform": self._normalize_optional_str(item.get("platform")),
                "homepage_urls": self._normalize_string_list(item.get("homepage_urls")),
                "store_ids": self._normalize_string_list(item.get("store_ids")),
                "main_categories": self._normalize_string_list(item.get("main_categories")),
                "advantages": self._normalize_string_list(item.get("advantages")),
                "related_products": self._normalize_string_list(item.get("related_products")),
                "other_info": self._normalize_string_list(item.get("other_info")),
            }
            for item in extracted.get("official_malls", [])
            if isinstance(item, dict)
            and (
                self._normalize_optional_str(item.get("store_name"))
                or self._normalize_optional_str(item.get("platform"))
                or self._normalize_string_list(item.get("homepage_urls"))
            )
        ]
        official_media_matrix = [
            {
                "media_platform": self._normalize_optional_str(item.get("media_platform")),
                "account_name": self._normalize_optional_str(item.get("account_name")),
                "account_id": self._normalize_optional_str(item.get("account_id")),
                "is_official": self._normalize_optional_str(item.get("is_official")),
                "homepage_urls": self._normalize_string_list(item.get("homepage_urls")),
                "fans_count": self._normalize_optional_str(item.get("fans_count")),
                "content_focus": self._normalize_string_list(item.get("content_focus")),
                "related_products": self._normalize_string_list(item.get("related_products")),
                "other_info": self._normalize_string_list(item.get("other_info")),
            }
            for item in extracted.get("official_media_matrix", [])
            if isinstance(item, dict)
            and (
                self._normalize_optional_str(item.get("media_platform"))
                or self._normalize_optional_str(item.get("account_name"))
                or self._normalize_optional_str(item.get("account_id"))
            )
        ]

        payload = {
            "basic_info": basic_info,
            "products": products,
            "company_profile": company_profile,
            "management_team": management_team,
            "competitors": competitors,
            "authority_honors": authority_honors,
            "customers_cases": customers_cases,
            "official_malls": official_malls,
            "official_media_matrix": official_media_matrix,
            "sensitive_topics": sensitive_topics,
            "attachments": self._normalize_attachment_entries(draft_attachments),
            "other_info": extracted_other_info,
        }
        return self._sanitize_candidate_other_info(payload)
