from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from knowledge_base.shared.utils import (
    normalize_hotline_sequence,
    normalize_http_url_sequence,
    normalize_text_sequence,
)

if TYPE_CHECKING:
    from knowledge_base.service import KnowledgeBaseService


logger = logging.getLogger(__name__)


async def build_structured_baseline_markdown(
    service: KnowledgeBaseService,
    *,
    brand: dict[str, Any],
) -> str:
    brand_name = str(brand.get("brand_name") or "").strip()
    brand_code = str(brand.get("brand_code") or "").strip()
    knowledge_revision = str(brand.get("knowledge_revision") or "").strip() or None
    if not brand_name:
        return ""

    if brand_code:
        try:
            meta_payload = await service.get_brand_meta(
                brand_code=brand_code,
                include_path_index=True,
            )
            path_index = meta_payload.get("path_index") if isinstance(meta_payload, dict) else None
            paths = [
                str(item.get("path") or "").strip()
                for item in path_index or []
                if isinstance(item, dict) and str(item.get("path") or "").strip()
            ]
            if paths:
                loaded = service.load_brand_paths(
                    brand_code=brand_code,
                    paths=paths,
                    knowledge_revision=knowledge_revision,
                )
                assets = loaded.get("assets") if isinstance(loaded, dict) else None
                sections = [
                    str(item.get("content") or "").strip()
                    for item in assets or []
                    if isinstance(item, dict) and str(item.get("content") or "").strip()
                ]
                if sections:
                    return "\n\n".join([f"# {brand_name} 当前结构化知识基线", *sections]).strip()
        except Exception:  # noqa: BLE001
            logger.warning(
                "Failed to build structured baseline from brand paths brand_name=%s",
                brand_name,
                exc_info=True,
            )

    return render_structured_baseline_fallback(service, brand=brand)


def render_structured_baseline_fallback(
    service: KnowledgeBaseService,
    *,
    brand: dict[str, Any],
) -> str:
    if not hasattr(service, "_brand_products") or not hasattr(service, "_brand_knowledge"):
        return ""
    brand_id = brand.get("id")
    brand_name = str(brand.get("brand_name") or "").strip()
    if brand_id is None or not brand_name:
        return ""

    products = service._brand_products.get_brand_products(brand_id=int(brand_id))
    knowledge_rows = service._brand_knowledge.get_all_brand_knowledge_json(brand_id=int(brand_id))
    knowledge_map = {
        str(row.get("knowledge_type") or "").strip(): parse_json_value(row.get("content_json"), None)
        for row in knowledge_rows
        if str(row.get("knowledge_type") or "").strip()
    }

    sections: list[str] = [f"# {brand_name} 当前结构化知识基线"]
    basic_info_lines = [
        ("品牌编码", brand.get("brand_code")),
        ("品牌别名", brand.get("brand_alias")),
        ("英文名称", brand.get("english_name")),
        ("官方网站", normalize_websites(brand.get("website"))),
        ("品牌简介", brand.get("intro")),
        ("主体名称", brand.get("brand_enterprise_entity")),
        ("客服热线", brand_multi_value(brand, "customer_service_hotline")),
        ("品牌定位", brand_multi_value(brand, "positioning")),
        ("品牌优势", brand_multi_value(brand, "advantages")),
        ("品牌使命", brand_multi_value(brand, "mission")),
        ("品牌愿景", brand_multi_value(brand, "vision")),
    ]
    basic_lines = []
    for label, raw_value in basic_info_lines:
        rendered = render_value(raw_value)
        if rendered:
            basic_lines.append(f"- **{label}**：{rendered}")
    if basic_lines:
        sections.extend(["", "## 基础信息", "", *basic_lines])

    company_profile = knowledge_map.get("company_profile") or knowledge_map.get("company_info") or {}
    if isinstance(company_profile, dict) and company_profile:
        company_lines = []
        for key, value in company_profile.items():
            rendered = render_value(value)
            if rendered:
                company_lines.append(f"- **{key}**：{rendered}")
        if company_lines:
            sections.extend(["", "## 公司档案", "", *company_lines])

    if products:
        sections.extend(["", "## 产品信息", ""])
        for product in products:
            product_name = str(product.get("product_name") or "").strip()
            if not product_name:
                continue
            sections.append(f"### {product_name}")
            for label, raw_value in (
                ("产品别名", product.get("product_alias")),
                ("产品介绍", product.get("product_description")),
                ("产品官网", normalize_websites(product.get("product_website"))),
                ("产品优势", product.get("product_advantages")),
                ("适用场景", product.get("target_scenarios")),
                ("服务标准", product.get("service_standard")),
                ("服务流程", product.get("service_process")),
                ("案例与口碑", product.get("cases_and_reputation")),
                ("认证信息", product.get("certification_info")),
                ("核心技术", product.get("core_technology")),
                ("其他信息", product.get("other_info")),
            ):
                rendered = render_value(raw_value)
                if rendered:
                    sections.append(f"- **{label}**：{rendered}")
            sections.append("")

    for section_title, section_key in (
        ("管理团队", "management_team"),
        ("竞品信息", "competitors"),
        ("权威荣誉", "authority_honors"),
        ("客户案例", "customers_cases"),
        ("敏感话题", "sensitive_topics"),
        ("附件资料", "attachments"),
        ("官方商城", "official_malls"),
        ("官方媒体与矩阵", "official_media_matrix"),
    ):
        payload = knowledge_map.get(section_key)
        rendered_section = render_json_section(section_title, payload)
        if rendered_section:
            sections.extend(["", rendered_section])

    return "\n".join(sections).strip()


def parse_json_value(raw: Any, default: Any) -> Any:
    if raw is None:
        return default
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return default
    return default


def normalize_websites(value: Any) -> list[str]:
    return normalize_http_url_sequence(value)


def normalize_multi_value(value: Any) -> list[str]:
    return normalize_text_sequence(value)


def brand_multi_value(brand: dict[str, Any], key: str) -> list[str]:
    if key == "customer_service_hotline":
        return normalize_hotline_sequence(brand.get(key))
    return normalize_multi_value(brand.get(key))


def render_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        rendered = [str(item).strip() for item in value if str(item).strip()]
        return "、".join(rendered)
    if isinstance(value, dict):
        parts = []
        for key, nested in value.items():
            nested_rendered = render_value(nested)
            if nested_rendered:
                parts.append(f"{key}: {nested_rendered}")
        return "；".join(parts)
    return str(value).strip()


def render_json_section(title: str, payload: Any) -> str:
    if payload is None:
        return ""
    if isinstance(payload, list):
        lines = [f"## {title}", ""]
        emitted = False
        for item in payload:
            if isinstance(item, dict):
                parts = [
                    f"**{key}**：{rendered}"
                    for key, rendered in (
                        (key, render_value(value))
                        for key, value in item.items()
                    )
                    if rendered
                ]
                if parts:
                    lines.append(f"- {'；'.join(parts)}")
                    emitted = True
            else:
                rendered = render_value(item)
                if rendered:
                    lines.append(f"- {rendered}")
                    emitted = True
        return "\n".join(lines).strip() if emitted else ""
    if isinstance(payload, dict):
        lines = [f"## {title}", ""]
        emitted = False
        for key, value in payload.items():
            rendered = render_value(value)
            if rendered:
                lines.append(f"- **{key}**：{rendered}")
                emitted = True
        return "\n".join(lines).strip() if emitted else ""
    rendered = render_value(payload)
    if not rendered:
        return ""
    return f"## {title}\n\n- {rendered}"


def load_conflicts(raw_conflicts: Any) -> list[dict[str, Any]]:
    if isinstance(raw_conflicts, list):
        return [item for item in raw_conflicts if isinstance(item, dict)]
    if isinstance(raw_conflicts, str) and raw_conflicts.strip():
        try:
            parsed = json.loads(raw_conflicts)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
    return []
