from __future__ import annotations

import re
from typing import Any

from knowledge_base.brand.callback_mapper import format_brand_callback_knowledge_from_snapshot


class AttachmentDraftSnapshotConversionMixin:
    def _build_external_candidate_snapshot(self, internal_snapshot: dict[str, Any]) -> dict[str, Any]:
        callback_snapshot = format_brand_callback_knowledge_from_snapshot(
            brand=None,
            knowledge_snapshot=internal_snapshot,
        )
        return self._sanitize_candidate_other_info(self._prune_empty_payload(callback_snapshot))

    def _looks_like_callback_snapshot(self, snapshot: dict[str, Any]) -> bool:
        basic_info = snapshot.get("basic_info")
        company_profile = snapshot.get("company_profile")
        management_team = snapshot.get("management_team")
        competitors = snapshot.get("competitors")
        authority_honors = snapshot.get("authority_honors")
        customers_cases = snapshot.get("customers_cases")
        attachments = snapshot.get("attachments")
        return any(
            (
                isinstance(basic_info, dict) and isinstance(basic_info.get("extra_info"), dict),
                isinstance(company_profile, dict)
                and any(key in company_profile for key in ("subject_info", "business_license_url", "founded_at")),
                isinstance(management_team, dict) and isinstance(management_team.get("members"), list),
                isinstance(competitors, dict) and isinstance(competitors.get("competitors"), list),
                isinstance(authority_honors, dict) and isinstance(authority_honors.get("honors"), list),
                isinstance(customers_cases, dict) and isinstance(customers_cases.get("cases"), list),
                isinstance(attachments, dict) and isinstance(attachments.get("files"), list),
            )
        )

    def _text_or_join(self, value: Any) -> str | None:
        values = self._normalize_string_list(value)
        if not values:
            return None
        return "；".join(values)

    def _text_or_join_lines(self, value: Any) -> str | None:
        values = self._split_line_text_values(value)
        if not values:
            return None
        return "\n".join(values)

    @classmethod
    def _extract_specific_award_date(cls, value: Any) -> str | None:
        text = "\n".join(cls._comparison_texts(value))
        if not text:
            return None
        for pattern in cls._EXACT_DATE_PATTERNS:
            match = pattern.search(text)
            if match:
                year, month, day = match.groups()
                return f"{year}年{int(month)}月{int(day)}日"
        match = cls._EXACT_MONTH_PATTERN.search(text)
        if match:
            year, month = match.groups()
            return f"{year}年{int(month)}月"
        return None

    @classmethod
    def _prefer_specific_award_date(cls, raw_year: Any, *source_values: Any) -> str | None:
        year = cls._normalize_optional_str(raw_year)
        specific_date = cls._extract_specific_award_date(source_values)
        if not specific_date:
            return year
        if not year:
            return specific_date
        if re.fullmatch(r"(?:19|20)\d{2}", year) and specific_date.startswith(year):
            return specific_date
        return year

    def _callback_files_to_attachments(self, value: Any) -> list[dict[str, Any]]:
        files = value.get("files") if isinstance(value, dict) else value
        if not isinstance(files, list):
            return []
        attachments: list[dict[str, Any]] = []
        for item in files:
            if not isinstance(item, dict):
                continue
            name = self._normalize_optional_str(item.get("name"))
            url = self._normalize_optional_str(item.get("url") or item.get("source_url"))
            if not name and not url:
                continue
            attachments.append(
                {
                    "name": name or "未命名附件",
                    "url": url or "",
                    "type": self._normalize_optional_str(item.get("type")),
                    "description": self._normalize_optional_str(item.get("description")),
                }
            )
        return attachments

    def _convert_callback_snapshot_to_internal(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        basic_info_raw = snapshot.get("basic_info") if isinstance(snapshot.get("basic_info"), dict) else {}
        extra_info = basic_info_raw.get("extra_info") if isinstance(basic_info_raw.get("extra_info"), dict) else {}
        company_profile_raw = (
            snapshot.get("company_profile") if isinstance(snapshot.get("company_profile"), dict) else {}
        )
        management_team_raw = snapshot.get("management_team")
        competitors_raw = snapshot.get("competitors")
        authority_honors_raw = snapshot.get("authority_honors")
        customers_cases_raw = snapshot.get("customers_cases")

        products: list[dict[str, Any]] = []
        for item in snapshot.get("products", []) if isinstance(snapshot.get("products"), list) else []:
            if not isinstance(item, dict):
                continue
            base_info = item.get("base_info") if isinstance(item.get("base_info"), dict) else item
            knowledge = item.get("knowledge") if isinstance(item.get("knowledge"), dict) else {}
            price_info = knowledge.get("price_info") if isinstance(knowledge.get("price_info"), dict) else {}
            name = self._normalize_optional_str(base_info.get("name"))
            if not name:
                continue
            products.append(
                {
                    "name": name,
                    "product_alias": self._normalize_optional_str(base_info.get("target_label")),
                    "product_description": self._normalize_optional_str(base_info.get("product_description")),
                    "product_website": self._normalize_optional_str(base_info.get("product_link")),
                    "product_images": self._normalize_string_list(base_info.get("product_images")),
                    "coverage_regions": self._normalize_string_list(base_info.get("coverage_regions")),
                    "price_info": self._normalize_optional_str(price_info.get("summary")),
                    "product_advantages": self._text_or_join(knowledge.get("advantages")),
                    "target_scenarios": self._text_or_join(knowledge.get("scenarios")),
                    "service_standard": self._text_or_join(knowledge.get("service_standards")),
                    "service_process": self._text_or_join(knowledge.get("service_processes")),
                    "cases_and_reputation": self._text_or_join(knowledge.get("cases_reputation")),
                    "certification_info": self._text_or_join(knowledge.get("awards_certifications")),
                    "core_technology": self._text_or_join(knowledge.get("technologies_patents")),
                    "other_info": self._text_or_join(knowledge.get("other_info")),
                }
            )

        management_members = (
            management_team_raw.get("members")
            if isinstance(management_team_raw, dict) and isinstance(management_team_raw.get("members"), list)
            else management_team_raw
        )
        management_members = management_members if isinstance(management_members, list) else []
        management_team = [
            {
                "name": self._normalize_optional_str(item.get("name")),
                "title": self._normalize_optional_str(item.get("title")),
                "profile": self._normalize_optional_str(item.get("bio") or item.get("profile")),
                "introduction_website": self._text_or_join(item.get("intro_urls") or item.get("introduction_website")),
                "other_info": self._text_or_join(item.get("other_info")),
            }
            for item in management_members
            if isinstance(item, dict) and self._normalize_optional_str(item.get("name"))
        ]

        competitor_items = (
            competitors_raw.get("competitors")
            if isinstance(competitors_raw, dict) and isinstance(competitors_raw.get("competitors"), list)
            else competitors_raw
        )
        competitor_items = competitor_items if isinstance(competitor_items, list) else []
        competitors = [
            {
                "name": self._normalize_optional_str(item.get("name")),
                "aliases": self._normalize_string_list(item.get("aliases") or item.get("competitors_alias")),
                "introduction": self._normalize_optional_str(item.get("introduction") or item.get("competitors_description")),
                "official_websites": self._normalize_string_list(item.get("official_websites") or item.get("website")),
                "logo_urls": self._normalize_string_list(item.get("logo_urls") or item.get("competitors_logo")),
                "strengths": self._normalize_string_list(item.get("strengths") or item.get("competitive_advantages")),
                "differentiated_positioning": self._normalize_string_list(item.get("differentiated_positioning")),
                "comparison_dimensions": self._normalize_string_list(
                    item.get("comparison_dimensions") or item.get("comparison_dimensions")
                ),
            }
            for item in competitor_items
            if isinstance(item, dict) and self._normalize_optional_str(item.get("name"))
        ]

        honor_items = (
            authority_honors_raw.get("honors")
            if isinstance(authority_honors_raw, dict) and isinstance(authority_honors_raw.get("honors"), list)
            else authority_honors_raw
        )
        honor_items = honor_items if isinstance(honor_items, list) else []
        authority_honors: list[dict[str, Any]] = []
        for item in honor_items:
            if not isinstance(item, dict):
                continue
            title = self._normalize_optional_str(item.get("title"))
            if not title:
                continue
            description = self._text_or_join(item.get("descriptions") or item.get("description"))
            report_link = self._text_or_join(item.get("report_links") or item.get("report_link"))
            qualification_proof = (
                item.get("proof_files") if item.get("proof_files") is not None else item.get("qualification_proof")
            )
            authority_honors.append(
                {
                    "title": title,
                    "year": self._prefer_specific_award_date(
                        item.get("awarded_at") or item.get("year"),
                        title,
                        description,
                    ),
                    "description": description,
                    "report_link": report_link,
                    "qualification_proof": qualification_proof,
                }
            )

        case_items = (
            customers_cases_raw.get("cases")
            if isinstance(customers_cases_raw, dict) and isinstance(customers_cases_raw.get("cases"), list)
            else customers_cases_raw
        )
        case_items = case_items if isinstance(case_items, list) else []
        customers_cases = [
            {
                "case_name": self._normalize_optional_str(item.get("title") or item.get("case_name")),
                "cooperation_time": self._normalize_optional_str(item.get("cooperation_time")),
                "customer_name": self._normalize_optional_str(item.get("customer_name")),
                "cooperation_product": self._text_or_join(item.get("cooperation_products") or item.get("cooperation_product")),
                "cooperation_highlight": self._text_or_join(item.get("highlights") or item.get("cooperation_highlight")),
                "customer_feedback": self._text_or_join(item.get("customer_reviews") or item.get("customer_feedback")),
            }
            for item in case_items
            if isinstance(item, dict)
            and (
                self._normalize_optional_str(item.get("title") or item.get("case_name"))
                or self._normalize_optional_str(item.get("customer_name"))
            )
        ]

        return self._normalize_snapshot_for_merge(
            {
                "basic_info": {
                    "brand_name": self._normalize_optional_str(basic_info_raw.get("brand_name")),
                    "brand_alias": self._normalize_optional_str(basic_info_raw.get("brand_alias")),
                    "brand_logo": self._normalize_optional_str(basic_info_raw.get("brand_logo")),
                    "website": self._normalize_string_list(basic_info_raw.get("website")),
                    "intro": self._normalize_optional_str(basic_info_raw.get("intro")),
                    "industry_id": self._normalize_optional_str(basic_info_raw.get("industry_id")),
                    "english_name": self._normalize_optional_str(extra_info.get("brand_english_name")),
                    "official_wechat_account": self._normalize_optional_str(extra_info.get("official_wechat")),
                    "positioning": self._normalize_string_list(extra_info.get("brand_positioning")),
                    "advantages": self._normalize_string_list(extra_info.get("brand_advantage")),
                    "mission": self._normalize_string_list(extra_info.get("brand_mission")),
                    "vision": self._normalize_string_list(extra_info.get("brand_vision")),
                    "target_regions": self._normalize_string_list(extra_info.get("target_region")),
                    "other_info": self._text_or_join(extra_info.get("other_info")),
                },
                "products": products,
                "company_profile": {
                    "brand_subject_name": self._normalize_optional_str(company_profile_raw.get("subject_info")),
                    "business_license_image_path": self._normalize_optional_str(company_profile_raw.get("business_license_url")),
                    "company_address": self._text_or_join(company_profile_raw.get("company_addresses")),
                    "company_intro": self._normalize_optional_str(company_profile_raw.get("company_intro")),
                    "established_time": self._normalize_optional_str(company_profile_raw.get("founded_at")),
                    "store_distribution": self._text_or_join(company_profile_raw.get("store_distribution")),
                    "recent_news": self._text_or_join(company_profile_raw.get("recent_news")),
                    "development_concept": self._text_or_join(company_profile_raw.get("development_philosophy")),
                    "corporate_values": self._text_or_join(company_profile_raw.get("company_values")),
                    "company_mission": self._text_or_join(company_profile_raw.get("company_mission")),
                    "development_history": self._text_or_join(company_profile_raw.get("development_history")),
                    "other_info": self._text_or_join(company_profile_raw.get("other_info")),
                },
                "management_team": management_team,
                "competitors": competitors,
                "authority_honors": authority_honors,
                "customers_cases": customers_cases,
                "sensitive_topics": snapshot.get("sensitive_topics"),
                "attachments": self._callback_files_to_attachments(snapshot.get("attachments")),
                "other_info": self._normalize_other_info_for_merge(snapshot.get("other_info")),
            }
        )

    def _normalize_candidate_snapshot_input(self, snapshot: dict[str, Any] | None) -> dict[str, Any]:
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        if self._looks_like_callback_snapshot(snapshot):
            return self._sanitize_candidate_other_info(self._convert_callback_snapshot_to_internal(snapshot))
        return self._sanitize_candidate_other_info(self._normalize_snapshot_for_merge(snapshot))
