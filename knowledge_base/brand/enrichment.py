from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from knowledge_base.brand.ai import enrich_brand_fields_from_web
from knowledge_base.shared.utils import normalize_http_url_sequence

if TYPE_CHECKING:
    from knowledge_base.infrastructure.integrations.tianyancha_client import (
        TianyanchaCompanyProfile,
        TianyanchaManagementMember,
    )
    from knowledge_base.service import KnowledgeBaseService


logger = logging.getLogger(__name__)


def _normalize_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_websites(value: Any) -> list[str]:
    return normalize_http_url_sequence(value)


def _pick_primary_website(value: Any) -> str:
    websites = _normalize_websites(value)
    if websites:
        return websites[0]
    return _normalize_str(value)


def _pick_missing_websites(current: Any, incoming: Any) -> list[str]:
    current_value = _normalize_websites(current)
    if current_value:
        return current_value
    return _normalize_websites(incoming)


def _pick_missing(current: Any, incoming: Any) -> str | None:
    current_value = _normalize_str(current)
    if current_value:
        return current_value
    incoming_value = _normalize_str(incoming)
    return incoming_value or None


def _merge_text_missing(current: Any, incoming: Any) -> str | None:
    current_value = _normalize_str(current)
    if current_value:
        return current_value
    incoming_value = _normalize_str(incoming)
    return incoming_value or None


def _build_tianyancha_company_other_info(profile: "TianyanchaCompanyProfile") -> str | None:
    items = [
        ("统一社会信用代码", profile.unified_social_credit_code),
        ("法定代表人", profile.legal_representative),
        ("行业", profile.industry),
        ("行业分类", profile.industry_classification),
        ("人员规模", profile.personnel_scale),
        ("参保人数", profile.insured_count),
        ("标签", profile.company_tags),
        ("邮箱", profile.email),
        ("登记状态", profile.registration_status),
        ("企业类型", profile.company_type),
        ("登记机关", profile.registration_authority),
        ("核准日期", profile.approval_date),
        ("营业期限起", profile.business_term_start),
        ("营业期限止", profile.business_term_end),
    ]
    parts = [f"{label}：{value}" for label, value in items if _normalize_str(value)]
    return "；".join(parts) if parts else None


def _build_management_member_other_info(member: "TianyanchaManagementMember") -> str | None:
    return _normalize_str(member.other_info) or None


def _build_management_member_payload(member: "TianyanchaManagementMember") -> dict[str, Any]:
    return {
        "member_name": _normalize_str(member.name),
        "position": _normalize_str(member.title),
        "profile": _normalize_str(member.profile),
        "introduction_website": "",
        "other_info": _build_management_member_other_info(member) or "",
    }


def _build_competitor_other_info(profile: "TianyanchaCompanyProfile") -> str | None:
    items = [
        ("企业名称", profile.company_name),
        ("法定代表人", profile.legal_representative),
        ("成立日期", profile.established_time),
        ("登记状态", profile.registration_status),
        ("行业", profile.industry),
        ("企业类型", profile.company_type),
        ("注册地址", profile.company_address),
        ("联系电话", profile.customer_service_hotline),
        ("邮箱", profile.email),
    ]
    parts = [f"{label}：{value}" for label, value in items if _normalize_str(value)]
    return "；".join(parts) if parts else None


def _merge_other_info(current: Any, incoming: Any) -> str | None:
    current_value = _normalize_str(current)
    incoming_value = _normalize_str(incoming)
    if not current_value:
        return incoming_value or None
    if not incoming_value:
        return current_value

    parts: list[str] = []
    seen: set[str] = set()
    for value in (current_value, incoming_value):
        for part in [item.strip() for item in value.replace("\n", "；").split("；")]:
            if not part:
                continue
            normalized = part.casefold()
            if normalized in seen:
                continue
            seen.add(normalized)
            parts.append(part)
    return "；".join(parts) if parts else None


def _collect_scalar_fill_log(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    fields: tuple[str, ...],
) -> dict[str, Any]:
    filled: dict[str, Any] = {}
    for field in fields:
        before_value = _normalize_str(before.get(field))
        after_value = _normalize_str(after.get(field))
        if not before_value and after_value:
            filled[field] = after_value
    return filled


def _collect_list_fill_log(
    before_items: list[dict[str, Any]],
    after_items: list[dict[str, Any]],
    *,
    key_field: str,
    fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    before_by_key = {
        _normalize_str(item.get(key_field)).lower(): item
        for item in before_items
        if _normalize_str(item.get(key_field))
    }
    fill_logs: list[dict[str, Any]] = []
    for item in after_items:
        item_key = _normalize_str(item.get(key_field))
        if not item_key:
            continue
        before_item = before_by_key.get(item_key.lower(), {})
        filled_fields = _collect_scalar_fill_log(before_item, item, fields=fields)
        if filled_fields:
            filled_fields[key_field] = item_key
            fill_logs.append(filled_fields)
    return fill_logs


def _build_missing_web_payload(
    *,
    management_team: list[dict[str, Any]],
    competitors: list[dict[str, Any]],
) -> dict[str, Any]:
    missing_management: list[dict[str, Any]] = []
    for item in management_team:
        missing_item = {
            "member_name": _normalize_str(item.get("member_name")),
            "position": "" if not _normalize_str(item.get("position")) else None,
            "profile": "" if not _normalize_str(item.get("profile")) else None,
            "introduction_website": "" if not _normalize_str(item.get("introduction_website")) else None,
            "other_info": "" if not _normalize_str(item.get("other_info")) else None,
        }
        if any(value == "" for key, value in missing_item.items() if key != "member_name"):
            missing_management.append({key: value for key, value in missing_item.items() if value is not None})

    missing_competitors: list[dict[str, Any]] = []
    for item in competitors:
        missing_item = {
            "name": _normalize_str(item.get("name")),
            "competitors_alias": "" if not _normalize_str(item.get("competitors_alias")) else None,
            "competitors_description": "" if not _normalize_str(item.get("competitors_description")) else None,
            "website": "" if not _normalize_str(item.get("website")) else None,
            "competitors_logo": "" if not _normalize_str(item.get("competitors_logo")) else None,
            "competitive_advantages": "" if not _normalize_str(item.get("competitive_advantages")) else None,
            "differentiated_positioning": "" if not _normalize_str(item.get("differentiated_positioning")) else None,
            "comparison_dimensions": "" if not _normalize_str(item.get("comparison_dimensions")) else None,
            "other_info": "" if not _normalize_str(item.get("other_info")) else None,
        }
        if any(value == "" for key, value in missing_item.items() if key != "name"):
            missing_competitors.append({key: value for key, value in missing_item.items() if value is not None})

    missing_payload: dict[str, Any] = {}
    if missing_management:
        missing_payload["management_team"] = missing_management
    if missing_competitors:
        missing_payload["competitors"] = missing_competitors
    return missing_payload


def _apply_web_enrichment_to_management(
    management_team: list[dict[str, Any]],
    web_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    incoming_items = web_payload.get("management_team")
    if not isinstance(incoming_items, list):
        return management_team
    incoming_by_name = {
        _normalize_str(item.get("member_name")).lower(): item
        for item in incoming_items
        if isinstance(item, dict) and _normalize_str(item.get("member_name"))
    }
    enriched: list[dict[str, Any]] = []
    for item in management_team:
        merged = dict(item)
        candidate = incoming_by_name.get(_normalize_str(item.get("member_name")).lower())
        if isinstance(candidate, dict):
            for field in ("position", "profile", "introduction_website", "other_info"):
                merged[field] = _pick_missing(merged.get(field), candidate.get(field))
        enriched.append(merged)
    return enriched


def _apply_web_enrichment_to_competitors(
    competitors: list[dict[str, Any]],
    web_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    incoming_items = web_payload.get("competitors")
    if not isinstance(incoming_items, list):
        return competitors
    incoming_by_name = {
        _normalize_str(item.get("name")).lower(): item
        for item in incoming_items
        if isinstance(item, dict) and _normalize_str(item.get("name"))
    }
    enriched: list[dict[str, Any]] = []
    for item in competitors:
        merged = dict(item)
        candidate = incoming_by_name.get(_normalize_str(item.get("name")).lower())
        if isinstance(candidate, dict):
            for field in (
                "competitors_alias",
                "competitors_description",
                "website",
                "competitors_logo",
                "competitive_advantages",
                "differentiated_positioning",
                "comparison_dimensions",
                "other_info",
            ):
                merged[field] = _pick_missing(merged.get(field), candidate.get(field))
        enriched.append(merged)
    return enriched


async def enrich_brand_from_tianyancha(
    service: "KnowledgeBaseService",
    *,
    brand: dict[str, Any],
    extracted_basic_info: dict[str, Any],
    company_profile: dict[str, Any],
    management_team: list[dict[str, Any]] | None = None,
    competitors: list[dict[str, Any]] | None = None,
    enable_tianyancha: bool = True,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    client = getattr(service, "_tianyancha_client", None)
    current_management_team = [dict(item) for item in (management_team or []) if isinstance(item, dict)]
    current_competitors = [dict(item) for item in (competitors or []) if isinstance(item, dict)]
    if enable_tianyancha and (client is None or not client.enabled()):
        return extracted_basic_info, company_profile, current_management_team, current_competitors

    brand_name = _normalize_str((brand or {}).get("brand_name"))
    enterprise_name = _normalize_str((brand or {}).get("brand_enterprise_entity")) or brand_name
    enriched_basic_info = dict(extracted_basic_info)
    enriched_company_profile = dict(company_profile)
    enriched_management_team = current_management_team
    enriched_competitors = current_competitors

    if enable_tianyancha:
        logger.info(
            "Tianyancha company lookup start brand_name=%s company_name=%s",
            brand_name,
            enterprise_name or None,
        )
        profile: TianyanchaCompanyProfile | None = client.lookup_company_profile(
            brand_name=brand_name,
            company_name=enterprise_name or None,
        )
        logger.info(
            "Tianyancha company lookup %s brand_name=%s company_name=%s",
            "success" if profile is not None else "miss",
            brand_name,
            enterprise_name or None,
        )

        original_basic_info = dict(extracted_basic_info)
        original_company_profile = dict(company_profile)

        if profile is not None:
            enriched_basic_info["english_name"] = _pick_missing(
                enriched_basic_info.get("english_name"),
                profile.english_name,
            )
            enriched_basic_info["brand_logo"] = _pick_missing(
                enriched_basic_info.get("brand_logo"),
                profile.brand_logo,
            )
            enriched_basic_info["website"] = _pick_missing_websites(
                enriched_basic_info.get("website") or (brand or {}).get("website"),
                profile.website,
            )
            enriched_basic_info["customer_service_hotline"] = _pick_missing(
                enriched_basic_info.get("customer_service_hotline"),
                profile.customer_service_hotline,
            )
            enriched_basic_info["official_wechat_account"] = _pick_missing(
                enriched_basic_info.get("official_wechat_account")
                or (brand or {}).get("official_wechat_account"),
                profile.official_wechat_account,
            )

            enriched_company_profile["brand_subject_name"] = _pick_missing(
                enriched_company_profile.get("brand_subject_name"),
                profile.company_name,
            )
            enriched_company_profile["registered_capital"] = _pick_missing(
                enriched_company_profile.get("registered_capital"),
                profile.registered_capital,
            )
            enriched_company_profile["company_intro"] = _pick_missing(
                enriched_company_profile.get("company_intro"),
                profile.company_intro,
            )
            enriched_company_profile["established_time"] = _pick_missing(
                enriched_company_profile.get("established_time"),
                profile.established_time,
            )
            enriched_company_profile["company_address"] = _pick_missing(
                enriched_company_profile.get("company_address"),
                profile.company_address,
            )
            enriched_company_profile["other_info"] = _merge_other_info(
                enriched_company_profile.get("other_info"),
                _build_tianyancha_company_other_info(profile),
            )
            basic_fill_log = _collect_scalar_fill_log(
                original_basic_info,
                enriched_basic_info,
                fields=(
                    "english_name",
                    "brand_logo",
                    "website",
                    "customer_service_hotline",
                    "official_wechat_account",
                ),
            )
            company_fill_log = _collect_scalar_fill_log(
                original_company_profile,
                enriched_company_profile,
                fields=(
                    "brand_subject_name",
                    "registered_capital",
                    "company_intro",
                    "established_time",
                    "company_address",
                    "other_info",
                ),
            )
            logger.info(
                "Tianyancha company enriched brand_name=%s basic_info_filled=%s company_profile_filled=%s",
                brand_name,
                basic_fill_log,
                company_fill_log,
            )

        management_lookup_name = enterprise_name or brand_name
        logger.info(
            "Tianyancha management lookup start brand_name=%s company_name=%s",
            brand_name,
            management_lookup_name or None,
        )
        management_members: list[TianyanchaManagementMember] = client.lookup_company_management(
            brand_name=brand_name,
            company_name=management_lookup_name or None,
        )
        logger.info(
            "Tianyancha management lookup %s brand_name=%s company_name=%s member_count=%s",
            "success" if management_members else "miss",
            brand_name,
            management_lookup_name or None,
            len(management_members),
        )
        members_by_name = {
            _normalize_str(item.name).lower(): item
            for item in management_members
            if _normalize_str(item.name)
        }
        original_management_team = [dict(item) for item in current_management_team]
        enriched_management_team = []
        for item in current_management_team:
            merged = dict(item)
            member = members_by_name.get(_normalize_str(item.get("member_name")).lower())
            if member is not None:
                merged["position"] = _pick_missing(merged.get("position"), member.title)
                merged["profile"] = _merge_text_missing(merged.get("profile"), member.profile)
                merged["other_info"] = _merge_other_info(merged.get("other_info"), _build_management_member_other_info(member))
            enriched_management_team.append(merged)

        existing_member_names = {
            _normalize_str(item.get("member_name")).lower()
            for item in enriched_management_team
            if _normalize_str(item.get("member_name"))
        }
        for member in management_members:
            member_name = _normalize_str(member.name).lower()
            if not member_name or member_name in existing_member_names:
                continue
            enriched_management_team.append(_build_management_member_payload(member))
            existing_member_names.add(member_name)

        management_fill_log = _collect_list_fill_log(
            original_management_team,
            enriched_management_team,
            key_field="member_name",
            fields=("position", "profile", "other_info"),
        )
        if management_fill_log:
            logger.info(
                "Tianyancha management enriched brand_name=%s items=%s",
                brand_name,
                management_fill_log,
            )

        original_competitors = [dict(item) for item in current_competitors]
        enriched_competitors = []
        for item in current_competitors:
            merged = dict(item)
            competitor_name = _normalize_str(item.get("name"))
            if competitor_name:
                logger.info("Tianyancha competitor lookup start competitor_name=%s", competitor_name)
                competitor_profile = client.lookup_company_profile(
                    brand_name=competitor_name,
                    company_name=competitor_name,
                )
                logger.info(
                    "Tianyancha competitor lookup %s competitor_name=%s",
                    "success" if competitor_profile is not None else "miss",
                    competitor_name,
                )
                if competitor_profile is not None:
                    merged["competitors_description"] = _pick_missing(
                        merged.get("competitors_description"),
                        competitor_profile.company_intro,
                    )
                    merged["website"] = _pick_missing(
                        merged.get("website"),
                        competitor_profile.website,
                    )
                    merged["competitors_logo"] = _pick_missing(
                        merged.get("competitors_logo"),
                        competitor_profile.brand_logo,
                    )
                    merged["other_info"] = _pick_missing(
                        merged.get("other_info"),
                        _build_competitor_other_info(competitor_profile),
                    )
            enriched_competitors.append(merged)
        competitor_fill_log = _collect_list_fill_log(
            original_competitors,
            enriched_competitors,
            key_field="name",
            fields=("competitors_description", "website", "competitors_logo", "other_info"),
        )
        if competitor_fill_log:
            logger.info(
                "Tianyancha competitor enriched brand_name=%s items=%s",
                brand_name,
                competitor_fill_log,
            )

    missing_web_payload = _build_missing_web_payload(
        management_team=enriched_management_team,
        competitors=enriched_competitors,
    )
    if missing_web_payload:
        web_payload = {}
        try:
            web_payload = await enrich_brand_fields_from_web(
                brand_name=brand_name,
                company_name=enterprise_name or None,
                official_website=_pick_primary_website((brand or {}).get("website"))
                or _pick_primary_website(enriched_basic_info.get("website")),
                missing_fields=missing_web_payload,
                settings=service._settings,
            )
        except Exception:
            web_payload = {}
            logger.exception("LLM web enrichment failed brand_name=%s", brand_name)
        if isinstance(web_payload, dict):
            logger.info("LLM web enrichment response brand_name=%s filled=%s", brand_name, web_payload)
            enriched_management_team = _apply_web_enrichment_to_management(enriched_management_team, web_payload)
            enriched_competitors = _apply_web_enrichment_to_competitors(enriched_competitors, web_payload)

    return enriched_basic_info, enriched_company_profile, enriched_management_team, enriched_competitors
