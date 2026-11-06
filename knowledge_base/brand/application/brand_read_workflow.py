from __future__ import annotations

import asyncio
from typing import Any

from knowledge_base.shared.utils import normalize_text_sequence


class BrandReadWorkflowMixin:
    def _load_brand_snapshot(
        self,
        *,
        brand: dict[str, Any],
    ) -> tuple[int | None, list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        brand_id = self._brand_id_from_row(brand)
        if brand_id is None:
            return None, [], [], {}
        products = list(self._deps.brand_products.get_brand_products(brand_id=brand_id) or [])
        knowledge_rows = list(self._deps.brand_knowledge.get_all_brand_knowledge_json(brand_id=brand_id) or [])
        knowledge_map = {
            str(row.get("knowledge_type") or "").strip(): self._parse_json_value(row.get("content_json"), None)
            for row in knowledge_rows
            if str(row.get("knowledge_type") or "").strip()
        }
        return brand_id, products, knowledge_rows, knowledge_map

    async def _load_brand_snapshot_async(
        self,
        *,
        brand: dict[str, Any],
    ) -> tuple[int | None, list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        return await asyncio.to_thread(self._load_brand_snapshot, brand=brand)

    async def _resolve_industry_name_async(self, brand: dict[str, Any]) -> str:
        return await asyncio.to_thread(self._resolve_industry_name, brand)

    @staticmethod
    def _normalize_meta_aliases(value: Any) -> list[str]:
        return normalize_text_sequence(
            value,
            split_separators=("\n", ",", "，", "、"),
        )

    def _build_display_products(
        self,
        *,
        brand_products: list[dict[str, Any]],
        attachment_products: Any,
    ) -> list[dict[str, Any]]:
        display_products: list[dict[str, Any]] = []
        seen_names: set[str] = set()

        def add_product(product: dict[str, Any], *, is_attachment_product: bool) -> None:
            product_name = str(product.get("product_name") or product.get("name") or "").strip()
            if not product_name:
                return
            product_key = product_name.casefold()
            if product_key in seen_names:
                return
            seen_names.add(product_key)
            if not is_attachment_product:
                display_products.append(product)
                return
            display_products.append(
                {
                    "product_name": product_name,
                    "product_alias": product.get("product_alias"),
                    "product_description": product.get("product_description"),
                    "product_website": product.get("product_website") or product.get("product_link"),
                    "product_images_json": (
                        product.get("product_images_json")
                        if product.get("product_images_json") is not None
                        else product.get("product_images")
                    ),
                    "price_info": product.get("price_info"),
                    "coverage_regions_json": (
                        product.get("coverage_regions_json")
                        if product.get("coverage_regions_json") is not None
                        else product.get("coverage_regions")
                    ),
                    "product_advantages": product.get("product_advantages") or product.get("advantages"),
                    "target_scenarios": product.get("target_scenarios") or product.get("scenarios"),
                    "service_standard": product.get("service_standard"),
                    "service_process": product.get("service_process"),
                    "cases_and_reputation": product.get("cases_and_reputation"),
                    "certification_info": product.get("certification_info"),
                    "core_technology": product.get("core_technology"),
                    "other_info": product.get("other_info"),
                    "updated_at": product.get("updated_at"),
                }
            )

        for product in brand_products:
            if isinstance(product, dict):
                add_product(product, is_attachment_product=False)

        if isinstance(attachment_products, list):
            for product in attachment_products:
                if isinstance(product, dict):
                    add_product(product, is_attachment_product=True)

        return display_products

    def _build_brand_render_payload(
        self,
        *,
        brand: dict[str, Any],
        knowledge_map: dict[str, Any],
        brand_products: list[dict[str, Any]],
    ) -> dict[str, Any]:
        products = self._build_display_products(
            brand_products=brand_products,
            attachment_products=knowledge_map.get(self.ATTACHMENT_PRODUCTS_KNOWLEDGE_TYPE),
        )
        company_profile = knowledge_map.get("company_profile") or knowledge_map.get("company_info") or {}
        management_team = knowledge_map.get("management_team") or []
        competitors_content = knowledge_map.get("competitors") or []
        honors = knowledge_map.get("authority_honors") or knowledge_map.get("honors") or []
        cases = knowledge_map.get("customers_cases") or knowledge_map.get("cases") or []
        sensitive_topics = knowledge_map.get("sensitive_topics") or {}
        attachments = knowledge_map.get("attachments") or []
        official_malls = self._normalize_official_malls(knowledge_map.get("official_malls"))
        official_media_matrix = self._normalize_official_media_matrix(knowledge_map.get("official_media_matrix"))
        competitor_entities = self._build_competitor_entities(
            competitors_content=competitors_content,
            fallback_names=self._parse_json_value(brand.get("competitors_json"), []),
        )
        return {
            "products": products,
            "company_profile": company_profile,
            "management_team": management_team,
            "competitors_content": competitors_content,
            "competitor_entities": competitor_entities,
            "honors": honors,
            "cases": cases,
            "sensitive_topics": sensitive_topics,
            "attachments": attachments,
            "official_malls": official_malls,
            "official_media_matrix": official_media_matrix,
        }

    async def get_brand_meta(
        self,
        *,
        brand_code: str,
        include_path_index: bool = True,
    ) -> dict[str, Any] | None:
        normalized_brand_code = (brand_code or "").strip()
        if not normalized_brand_code:
            raise ValueError("brand_code 不能为空")

        brand = await asyncio.to_thread(
            self._deps.brands.get_brand_by_code,
            normalized_brand_code,
        )
        if not brand:
            return None

        (_, products, _knowledge_rows, knowledge_map), industry_name = await asyncio.gather(
            self._load_brand_snapshot_async(brand=brand),
            self._resolve_industry_name_async(brand),
        )
        render_payload = self._build_brand_render_payload(
            brand=brand,
            knowledge_map=knowledge_map,
            brand_products=products,
        )

        meta = {
            "brand_code": str(brand.get("brand_code") or normalized_brand_code),
            "brand_name": str(brand.get("brand_name") or "").strip(),
            "brand_aliases": self._normalize_meta_aliases(brand.get("brand_alias")),
            "brand_english_name": str(brand.get("english_name") or "").strip(),
            "industry": industry_name,
            "official_websites": self._normalize_websites(brand.get("website")),
            "knowledge_revision": str(brand.get("knowledge_revision") or "").strip(),
            "company_subject_name": str(
                render_payload["company_profile"].get("brand_subject_name")
                or brand.get("brand_enterprise_entity")
                or ""
            ).strip(),
            "company_profile": render_payload["company_profile"],
            "products": [
                self._build_meta_product_entity(product)
                for product in render_payload["products"]
                if str(product.get("product_name") or "").strip()
            ],
            "competitors": render_payload["competitor_entities"],
        }

        data = {"meta": meta}
        if include_path_index:
            latest_full_markdown = await asyncio.to_thread(
                self._get_latest_brand_full_knowledge_markdown,
                brand=brand,
                brand_code=normalized_brand_code,
            )
            latest_full_markdown_index = self._build_markdown_render_index(latest_full_markdown)
            data["path_index"] = await self._build_brand_path_index(
                brand=brand,
                knowledge_revision=meta["knowledge_revision"],
                company_profile=render_payload["company_profile"],
                management_team=render_payload["management_team"],
                products=render_payload["products"],
                competitors=render_payload["competitor_entities"],
                competitors_content=render_payload["competitors_content"],
                honors=render_payload["honors"],
                cases=render_payload["cases"],
                sensitive_topics=render_payload["sensitive_topics"],
                attachments=render_payload["attachments"],
                official_malls=render_payload["official_malls"],
                official_media_matrix=render_payload["official_media_matrix"],
                full_knowledge_markdown=latest_full_markdown,
                full_knowledge_markdown_index=latest_full_markdown_index,
            )
        return data

    def _build_meta_product_entity(self, product: dict[str, Any]) -> dict[str, Any]:
        product_name = str(product.get("product_name") or "").strip()
        entity = {
            "name": product_name,
            "aliases": self._normalize_meta_aliases(product.get("product_alias")),
            "path": self._build_product_path(product_name),
            "intro": self._build_product_summary(product),
        }
        product_code = str(product.get("product_code") or "").strip()
        if product_code:
            entity["product_code"] = product_code
        return entity

    async def get_brand_official_malls(
        self,
        *,
        brand_code: str,
    ) -> dict[str, Any] | None:
        normalized_brand_code = (brand_code or "").strip()
        if not normalized_brand_code:
            raise ValueError("brand_code 不能为空")

        brand = await asyncio.to_thread(
            self._deps.brands.get_brand_by_code,
            normalized_brand_code,
        )
        if not brand:
            return None

        (_, _products, _knowledge_rows, knowledge_map), _industry_name = await asyncio.gather(
            self._load_brand_snapshot_async(brand=brand),
            self._resolve_industry_name_async(brand),
        )
        return {
            "brand_code": str(brand.get("brand_code") or normalized_brand_code),
            "brand_name": str(brand.get("brand_name") or "").strip(),
            "knowledge_revision": str(brand.get("knowledge_revision") or "").strip(),
            "official_malls": self._normalize_official_malls(knowledge_map.get("official_malls")),
        }

    def load_brand_paths(
        self,
        *,
        brand_code: str,
        paths: list[str],
        knowledge_revision: str | None = None,
    ) -> dict[str, Any] | None:
        normalized_brand_code = (brand_code or "").strip()
        if not normalized_brand_code:
            raise ValueError("brand_code 不能为空")
        normalized_paths = [str(path).strip() for path in paths if str(path).strip()]
        if not normalized_paths:
            raise ValueError("paths 不能为空")

        brand = self._deps.brands.get_brand_by_code(normalized_brand_code)
        if not brand:
            return None

        current_revision = str(brand.get("knowledge_revision") or "").strip()
        if knowledge_revision and current_revision and knowledge_revision.strip() != current_revision:
            raise RuntimeError(f"knowledge_revision 不匹配，当前 revision={current_revision}")

        resolved_assets: list[dict[str, Any] | None] = [None] * len(normalized_paths)
        missing_asset_requests: list[tuple[int, str]] = []
        for index, path in enumerate(normalized_paths):
            cached_asset = self._get_cached_brand_path_asset(
                brand_code=normalized_brand_code,
                knowledge_revision=current_revision,
                path=path,
            )
            if cached_asset is None:
                missing_asset_requests.append((index, path))
                continue
            resolved_assets[index] = cached_asset

        missing_paths: list[dict[str, str]] = []
        if missing_asset_requests:
            brand_id, products, _knowledge_rows, knowledge_map = self._load_brand_snapshot(brand=brand)
            if brand_id is None:
                return None
            latest_full_markdown = self._get_latest_brand_full_knowledge_markdown(
                brand=brand,
                brand_code=normalized_brand_code,
            )
            latest_full_markdown_index = self._build_markdown_render_index(latest_full_markdown)
            render_payload = self._build_brand_render_payload(
                brand=brand,
                knowledge_map=knowledge_map,
                brand_products=products,
            )
            rendered_assets_by_path: dict[str, dict[str, Any] | None] = {}

            for index, path in missing_asset_requests:
                asset = rendered_assets_by_path.get(path)
                if path not in rendered_assets_by_path:
                    asset = self._render_brand_asset(
                        brand=brand,
                        path=path,
                        knowledge_revision=current_revision,
                        company_profile=render_payload["company_profile"],
                        management_team=render_payload["management_team"],
                        products=render_payload["products"],
                        competitors=render_payload["competitor_entities"],
                        competitors_content=render_payload["competitors_content"],
                        honors=render_payload["honors"],
                        cases=render_payload["cases"],
                        sensitive_topics=render_payload["sensitive_topics"],
                        attachments=render_payload["attachments"],
                        official_malls=render_payload["official_malls"],
                        official_media_matrix=render_payload["official_media_matrix"],
                        full_knowledge_markdown=latest_full_markdown,
                        full_knowledge_markdown_index=latest_full_markdown_index,
                    )
                    rendered_assets_by_path[path] = asset
                    if asset is not None:
                        self._cache_brand_path_asset(
                            brand_code=normalized_brand_code,
                            knowledge_revision=current_revision,
                            path=path,
                            asset=asset,
                        )
                if asset is None:
                    missing_paths.append({"path": path, "reason": "not_found"})
                else:
                    resolved_assets[index] = asset

        assets = [asset for asset in resolved_assets if asset is not None]
        return {
            "assets": assets,
            "missing_paths": missing_paths,
        }
