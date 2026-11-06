from __future__ import annotations

import json
from typing import Any

from knowledge_base.shared.utils import normalize_text_sequence


class BrandServiceSupportMixin:
    @classmethod
    def _normalize_official_malls(cls, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        normalized_items: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            normalized = {
                "store_name": str(item.get("store_name") or "").strip(),
                "platform": str(item.get("platform") or "").strip(),
                "homepage_urls": cls._normalize_multi_value(item.get("homepage_urls")),
                "store_ids": cls._normalize_multi_value(item.get("store_ids")),
                "main_categories": cls._normalize_multi_value(item.get("main_categories")),
                "advantages": cls._normalize_multi_value(item.get("advantages")),
                "related_products": cls._normalize_related_products(item.get("related_products")),
                "other_info": cls._normalize_multi_value(item.get("other_info")),
            }
            if any(normalized.values()):
                normalized_items.append(normalized)
        return normalized_items

    @classmethod
    def _normalize_official_media_matrix(cls, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        normalized_items: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            normalized = {
                "media_platform": str(item.get("media_platform") or "").strip(),
                "account_name": str(item.get("account_name") or "").strip(),
                "account_id": str(item.get("account_id") or "").strip(),
                "is_official": str(item.get("is_official") or "").strip(),
                "homepage_urls": cls._normalize_multi_value(item.get("homepage_urls")),
                "fans_count": str(item.get("fans_count") or "").strip(),
                "content_focus": cls._normalize_multi_value(item.get("content_focus")),
                "related_products": cls._normalize_related_products(item.get("related_products")),
                "other_info": cls._normalize_multi_value(item.get("other_info")),
            }
            if any(normalized.values()):
                normalized_items.append(normalized)
        return normalized_items

    @classmethod
    def _render_related_products(cls, value: Any) -> str:
        return "、".join(str(item).strip() for item in cls._normalize_related_products(value) if str(item).strip())

    @classmethod
    def _render_official_malls_markdown(cls, value: Any) -> str:
        malls = cls._normalize_official_malls(value)
        if not malls:
            return ""
        sections: list[str] = ["# 官方商城"]
        for mall in malls:
            title = mall.get("store_name") or mall.get("platform") or "官方商城"
            lines = [f"## {title}"]
            if mall.get("platform"):
                lines.append(f"- 开店平台：{mall['platform']}")
            if mall.get("homepage_urls"):
                lines.append(f"- 店铺主页链接：{'；'.join(mall['homepage_urls'])}")
            if mall.get("store_ids"):
                lines.append(f"- 店铺 ID：{'、'.join(mall['store_ids'])}")
            if mall.get("main_categories"):
                lines.append(f"- 主营品类：{'、'.join(mall['main_categories'])}")
            if mall.get("advantages"):
                lines.append(f"- 店铺优势：{'、'.join(mall['advantages'])}")
            related_products = cls._render_related_products(mall.get("related_products"))
            if related_products:
                lines.append(f"- 关联产品：{related_products}")
            if mall.get("other_info"):
                lines.append(f"- 其他信息：{'、'.join(mall['other_info'])}")
            sections.append("\n".join(lines))
        return cls._join_sections(sections)

    @classmethod
    def _render_official_media_matrix_markdown(cls, value: Any) -> str:
        accounts = cls._normalize_official_media_matrix(value)
        if not accounts:
            return ""
        sections: list[str] = ["# 官方媒体与矩阵"]
        for account in accounts:
            title = account.get("account_name") or account.get("media_platform") or "官方账号"
            lines = [f"## {title}"]
            if account.get("media_platform"):
                lines.append(f"- 媒体平台：{account['media_platform']}")
            if account.get("account_id"):
                lines.append(f"- 账号 ID：{account['account_id']}")
            if account.get("is_official"):
                lines.append(f"- 是否品牌官方账号：{account['is_official']}")
            if account.get("homepage_urls"):
                lines.append(f"- 账号主页链接：{'；'.join(account['homepage_urls'])}")
            if account.get("fans_count"):
                lines.append(f"- 粉丝量：{account['fans_count']}")
            if account.get("content_focus"):
                lines.append(f"- 内容方向：{'、'.join(account['content_focus'])}")
            related_products = cls._render_related_products(account.get("related_products"))
            if related_products:
                lines.append(f"- 关联产品：{related_products}")
            if account.get("other_info"):
                lines.append(f"- 其他信息：{'、'.join(account['other_info'])}")
            sections.append("\n".join(lines))
        return cls._join_sections(sections)

    def _attachment_document_already_exists(
        self,
        *,
        brand_name: str,
        attachment_name: str,
        attachment_url: str,
    ) -> bool:
        registry = self._deps.document_registry
        finder = getattr(registry, "find_latest_success_documents_by_filename", None)
        if not callable(finder):
            return False
        matches = finder(
            attachment_name,
            category=brand_name,
            source_url=attachment_url,
        )
        return bool(matches)

    def _resolve_industry_name(self, brand: dict[str, Any]) -> str:
        industry_name = str(brand.get("industry") or "").strip()
        if industry_name:
            return industry_name

        industry_id = self._normalize_int(brand.get("industry_id"))
        if industry_id is None:
            return ""
        industry = self._deps.industries.get_industry_by_id(industry_id)
        if not industry:
            return ""
        return str(industry.get("name") or "").strip()

    @staticmethod
    def _has_competitors_content(value: Any) -> bool:
        if isinstance(value, list):
            if not value:
                return False
            for item in value:
                if isinstance(item, dict):
                    if any(
                        str(item.get(key) or "").strip()
                        for key in ("name", "competitors_name", "introduction", "competitors_description")
                    ):
                        return True
                    continue
                if str(item or "").strip():
                    return True
            return False
        if isinstance(value, dict):
            return any(str(item or "").strip() for item in value.values())
        return bool(str(value or "").strip())

    @staticmethod
    def _build_product_path(product_name: str) -> str:
        return f"产品信息/{product_name}"

    @staticmethod
    def _build_competitor_path(competitor_name: str) -> str:
        return f"竞品信息/{competitor_name}"

    @staticmethod
    def _build_text_summary(*values: Any, fallback: str = "") -> str:
        for value in values:
            text = str(value or "").strip()
            if text:
                return text[:120]
        return fallback

    def _build_product_summary(self, product: dict[str, Any]) -> str:
        return self._build_text_summary(
            product.get("product_description"),
            product.get("product_advantages"),
            product.get("target_scenarios"),
            fallback="品牌产品或服务介绍。",
        )

    def _build_competitor_entities(
        self,
        *,
        competitors_content: Any,
        fallback_names: Any,
    ) -> list[dict[str, Any]]:
        entities: list[dict[str, Any]] = []
        seen_names: set[str] = set()

        if isinstance(competitors_content, list):
            for item in competitors_content:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                if not name or name in seen_names:
                    continue
                seen_names.add(name)
                aliases = item.get("aliases")
                if not aliases:
                    aliases = item.get("competitors_alias")
                intro = (
                    item.get("introduction")
                    or item.get("competitors_description")
                    or item.get("differentiated_positioning")
                    or item.get("competitive_advantages")
                )
                entities.append(
                    {
                        "name": name,
                        "aliases": self._normalize_aliases(aliases),
                        "path": self._build_competitor_path(name),
                        "intro": self._build_text_summary(intro, fallback="竞品资料。"),
                    }
                )

        if not entities and isinstance(fallback_names, list):
            for item in fallback_names:
                name = str(item or "").strip()
                if not name or name in seen_names:
                    continue
                seen_names.add(name)
                entities.append(
                    {
                        "name": name,
                        "aliases": [],
                        "path": self._build_competitor_path(name),
                        "intro": "竞品资料。",
                    }
                )

        return entities

    @staticmethod
    def normalize_sequence_value(value: Any) -> list[str]:
        return normalize_text_sequence(value)

    @staticmethod
    def _parse_json_value(raw: Any, default: Any) -> Any:
        if raw is None:
            return default
        if isinstance(raw, (dict, list)):
            return raw
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return default
            return parsed
        return default
