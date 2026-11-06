from __future__ import annotations

from typing import Any

from knowledge_base.brand.application.brand_path_rendering import _MarkdownRenderIndex


class BrandAssetRenderingMixin:
    def _get_latest_brand_full_knowledge_markdown(
        self,
        *,
        brand: dict[str, Any],
        brand_code: str,
    ) -> str | None:
        store = self._deps.brand_full_knowledge
        latest_row = None
        if store is not None:
            if hasattr(store, "get_latest_by_brand_code") and brand_code:
                latest_row = store.get_latest_by_brand_code(brand_code=brand_code)
            elif hasattr(store, "get_latest_by_brand_id"):
                brand_id = self._brand_id_from_row(brand)
                if brand_id is not None:
                    latest_row = store.get_latest_by_brand_id(brand_id=brand_id)
        if not latest_row:
            return None
        markdown = str(latest_row.get("content_markdown") or "").strip()
        return markdown or None

    def _render_brand_asset_from_full_markdown(
        self,
        *,
        path: str,
        full_knowledge_markdown: str | None,
        markdown_index: _MarkdownRenderIndex | None = None,
    ) -> str | None:
        resolved_markdown_index = markdown_index or self._build_markdown_render_index(full_knowledge_markdown)
        if resolved_markdown_index is None:
            return None

        normalized_path = str(path or "").strip()
        if not normalized_path:
            return None

        if normalized_path == self.BRAND_OVERVIEW_PATH:
            return resolved_markdown_index.markdown_text

        if normalized_path.startswith("产品信息/"):
            product_name = normalized_path.split("/", 1)[1].strip()
            if product_name:
                product_section = self._extract_markdown_section_by_titles_from_index(
                    resolved_markdown_index,
                    ["产品信息", product_name],
                )
                if product_section:
                    return product_section
                product_block = self._extract_named_markdown_bullet_block_from_index(
                    resolved_markdown_index,
                    product_name,
                )
                if product_block:
                    return product_block
            return self._extract_markdown_section_by_titles_from_index(resolved_markdown_index, ["产品信息"])

        if normalized_path.startswith("竞品信息/"):
            competitor_name = normalized_path.split("/", 1)[1].strip()
            competitor_section = self._extract_markdown_section_by_titles_from_index(
                resolved_markdown_index,
                ["竞品信息"],
            )
            if competitor_section:
                filtered_section = self._filter_markdown_section_by_keyword(competitor_section, competitor_name)
                if filtered_section:
                    return filtered_section
                return competitor_section
            return None

        root_title = self._path_leaf_title(normalized_path)
        if root_title in {
            "公司档案",
            "管理团队",
            "权威荣誉",
            "客户案例",
            "敏感话题",
            "附件资料",
            "官方商城",
            "官方媒体与矩阵",
        }:
            return self._extract_markdown_section_by_titles_from_index(resolved_markdown_index, [root_title])

        return None

    def _render_brand_asset(
        self,
        *,
        brand: dict[str, Any],
        path: str,
        knowledge_revision: str,
        company_profile: Any,
        management_team: Any,
        products: list[dict[str, Any]],
        competitors: list[dict[str, Any]],
        competitors_content: Any,
        honors: Any,
        cases: Any,
        sensitive_topics: Any,
        attachments: Any,
        official_malls: Any,
        official_media_matrix: Any,
        full_knowledge_markdown: str | None = None,
        full_knowledge_markdown_index: _MarkdownRenderIndex | None = None,
    ) -> dict[str, Any] | None:
        company_profile_payload = company_profile if isinstance(company_profile, dict) else {}
        markdown_content = self._render_brand_asset_from_full_markdown(
            path=path,
            full_knowledge_markdown=full_knowledge_markdown,
            markdown_index=full_knowledge_markdown_index,
        )
        if markdown_content:
            return self._build_asset(
                path=path,
                title=self._path_leaf_title(path),
                content=markdown_content,
                knowledge_revision=knowledge_revision,
                updated_at=brand.get("updated_at"),
            )

        if path == self.BRAND_OVERVIEW_PATH:
            target_regions = self.normalize_sequence_value(brand.get("target_regions_json"))
            customer_service_hotline = self._brand_multi_value(brand, "customer_service_hotline")
            positioning = self._brand_multi_value(brand, "positioning")
            advantages = self._brand_multi_value(brand, "advantages")
            mission = self._brand_multi_value(brand, "mission")
            vision = self._brand_multi_value(brand, "vision")
            websites = self._normalize_websites(brand.get("website"))
            company_profile_websites = self._normalize_websites(
                company_profile_payload.get("website") or company_profile_payload.get("official_website")
            )
            overview_websites = websites or company_profile_websites
            content = self._join_sections(
                [
                    f"# 品牌介绍\n\n{self._build_text_summary(brand.get('intro'), company_profile_payload.get('company_intro'), fallback='品牌介绍。')}",
                    self._markdown_section(
                        "基本信息",
                        self._markdown_key_values(
                            [
                                ("品牌名称", str(brand.get("brand_name") or "").strip()),
                                ("品牌别名", "、".join(self._normalize_aliases(brand.get("brand_alias")))),
                                ("英文名称", str(brand.get("english_name") or "").strip()),
                                ("所属行业", self._resolve_industry_name(brand)),
                                ("企业主体", str(company_profile_payload.get("brand_subject_name") or brand.get("brand_enterprise_entity") or "").strip()),
                                ("客服热线", "、".join(customer_service_hotline)),
                                ("知识版本", knowledge_revision),
                            ]
                        ),
                    ),
                    self._markdown_section("官方网站", self._markdown_links(overview_websites)),
                    self._markdown_section("品牌简介", str(brand.get("intro") or company_profile_payload.get("company_intro") or "").strip()),
                    self._markdown_section(
                        "公司档案",
                        self._markdown_key_values(
                            [
                                ("成立时间", company_profile_payload.get("established_time")),
                                ("注册资本", company_profile_payload.get("registered_capital")),
                                ("公司地址", company_profile_payload.get("company_address")),
                                ("上市信息", company_profile_payload.get("stock_info")),
                            ]
                        ),
                    ),
                    self._markdown_section("品牌定位", self._markdown_list(positioning)),
                    self._markdown_section("品牌优势", self._markdown_list(advantages)),
                    self._markdown_section("品牌使命", self._markdown_list(mission)),
                    self._markdown_section("品牌愿景", self._markdown_list(vision)),
                    self._markdown_section("覆盖区域", self._markdown_list(target_regions)),
                    self._markdown_section("重点产品", self._render_entity_path_list(products and [
                        {
                            "name": str(product.get("product_name") or "").strip(),
                            "path": self._build_product_path(str(product.get("product_name") or "").strip()),
                            "intro": self._build_product_summary(product),
                        }
                        for product in products
                        if str(product.get("product_name") or "").strip()
                    ] or [], entity_type_label="产品")),
                    self._markdown_section("主要竞品", self._render_entity_path_list(competitors, entity_type_label="竞品")),
                    self._markdown_section("其他信息", str(brand.get("other_info") or company_profile_payload.get("other_info") or "").strip()),
                ]
            )
            return self._build_asset(path=path, title="品牌介绍", content=content, knowledge_revision=knowledge_revision, updated_at=brand.get("updated_at"))

        if path == self.COMPANY_PROFILE_PATH and self._has_meaningful_payload(company_profile_payload):
            company_profile_websites = self._normalize_websites(
                company_profile_payload.get("website") or company_profile_payload.get("official_website")
            )
            content = self._join_sections(
                [
                    f"# 公司档案\n\n{self._build_text_summary(company_profile_payload.get('company_intro'), company_profile_payload.get('brand_subject_name'), fallback='公司档案资料。')}",
                    self._markdown_section(
                        "基本信息",
                        self._markdown_key_values(
                            [
                                ("企业主体", str(company_profile_payload.get("brand_subject_name") or brand.get("brand_enterprise_entity") or "").strip()),
                                ("成立时间", company_profile_payload.get("established_time")),
                                ("注册资本", company_profile_payload.get("registered_capital")),
                                ("公司地址", company_profile_payload.get("company_address")),
                                ("上市信息", company_profile_payload.get("stock_info")),
                            ]
                        ),
                    ),
                    self._markdown_section("官方网站", self._markdown_links(company_profile_websites)),
                    self._markdown_section("公司简介", str(company_profile_payload.get("company_intro") or "").strip()),
                    self._markdown_section("其他信息", str(company_profile_payload.get("other_info") or "").strip()),
                ]
            )
            return self._build_asset(path=path, title="公司档案", content=content, knowledge_revision=knowledge_revision, updated_at=brand.get("updated_at"))

        if path == self.MANAGEMENT_TEAM_PATH and isinstance(management_team, list) and management_team:
            lines = []
            for item in management_team:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("member_name") or item.get("name") or "").strip()
                if not name:
                    continue
                position = str(item.get("position") or item.get("title") or "").strip()
                profile = str(item.get("profile") or item.get("bio") or "").strip()
                intro_urls = self._normalize_websites(item.get("introduction_website"))
                other_info = str(item.get("other_info") or "").strip()
                source_section = str(item.get("source_section") or "").strip()
                section_lines = [f"### {name}"]
                if position:
                    section_lines.append(f"- 职务：{position}")
                if profile:
                    section_lines.append(f"- 简介：{profile}")
                if intro_urls:
                    section_lines.append(f"- 资料链接：{'；'.join(intro_urls)}")
                if other_info:
                    section_lines.append(f"- 其他信息：{other_info}")
                if source_section:
                    section_lines.append(f"- 来源：{source_section}")
                lines.append("\n".join(section_lines))
            content = self._join_sections([ "# 管理团队", "\n\n".join(lines) ])
            return self._build_asset(path=path, title="管理团队", content=content, knowledge_revision=knowledge_revision, updated_at=brand.get("updated_at"))

        if path == self.HONORS_PATH and isinstance(honors, list) and honors:
            lines = []
            for item in honors:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or "").strip()
                if not title:
                    continue
                description = str(item.get("description") or "").strip()
                year = str(item.get("year") or item.get("awarded_at") or "").strip()
                report_links = self._normalize_websites(item.get("report_link"))
                proof_files = self._normalize_multi_value(item.get("qualification_proof"))
                source_section = str(item.get("source_section") or "").strip()
                section_lines = [f"### {title}"]
                if year:
                    section_lines.append(f"- 时间：{year}")
                if description:
                    section_lines.append(f"- 说明：{description}")
                if report_links:
                    section_lines.append(f"- 报告链接：{'；'.join(report_links)}")
                if proof_files:
                    section_lines.append(f"- 证明材料：{'；'.join(proof_files)}")
                if source_section:
                    section_lines.append(f"- 来源：{source_section}")
                lines.append("\n".join(section_lines))
            content = self._join_sections([ "# 权威荣誉", "\n\n".join(lines) ])
            return self._build_asset(path=path, title="权威荣誉", content=content, knowledge_revision=knowledge_revision, updated_at=brand.get("updated_at"))

        if path == self.CASES_PATH and isinstance(cases, list) and cases:
            lines = []
            for item in cases:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("case_name") or item.get("title") or "").strip()
                if not title:
                    continue
                customer_name = str(item.get("customer_name") or "").strip()
                cooperation_time = str(item.get("cooperation_time") or "").strip()
                cooperation_product = str(item.get("cooperation_product") or "").strip()
                highlight = str(item.get("cooperation_highlight") or item.get("highlights") or "").strip()
                customer_feedback = str(item.get("customer_feedback") or "").strip()
                source_section = str(item.get("source_section") or "").strip()
                section_lines = [f"### {title}"]
                if customer_name:
                    section_lines.append(f"- 客户：{customer_name}")
                if cooperation_time:
                    section_lines.append(f"- 合作时间：{cooperation_time}")
                if cooperation_product:
                    section_lines.append(f"- 合作产品：{cooperation_product}")
                if highlight:
                    section_lines.append(f"- 亮点：{highlight}")
                if customer_feedback:
                    section_lines.append(f"- 客户反馈：{customer_feedback}")
                if source_section:
                    section_lines.append(f"- 来源：{source_section}")
                lines.append("\n".join(section_lines))
            content = self._join_sections([ "# 客户案例", "\n\n".join(lines) ])
            return self._build_asset(path=path, title="客户案例", content=content, knowledge_revision=knowledge_revision, updated_at=brand.get("updated_at"))

        if path == self.SENSITIVE_TOPICS_PATH and self._has_sensitive_topics_content(sensitive_topics):
            content = self._render_sensitive_topics_markdown(sensitive_topics)
            return self._build_asset(path=path, title="敏感话题", content=content, knowledge_revision=knowledge_revision, updated_at=brand.get("updated_at"))

        if path == self.ATTACHMENTS_PATH and isinstance(attachments, list) and attachments:
            lines = []
            for item in attachments:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                url = str(item.get("url") or "").strip()
                description = str(item.get("description") or "").strip()
                file_type = str(item.get("type") or "").strip()
                if not (name or url):
                    continue
                section_lines = [f"### {name or '附件'}"]
                if file_type:
                    section_lines.append(f"- 类型：{file_type}")
                if description:
                    section_lines.append(f"- 说明：{description}")
                if url:
                    section_lines.append(f"- 链接：[{url}]({url})")
                lines.append("\n".join(section_lines))
            content = self._join_sections([ "# 附件资料", "\n".join(lines) ])
            return self._build_asset(path=path, title="附件资料", content=content, knowledge_revision=knowledge_revision, updated_at=brand.get("updated_at"))

        if path == self.OFFICIAL_MALLS_PATH and isinstance(official_malls, list) and official_malls:
            content = self._render_official_malls_markdown(official_malls)
            return self._build_asset(path=path, title="官方商城", content=content, knowledge_revision=knowledge_revision, updated_at=brand.get("updated_at"))

        if path == self.OFFICIAL_MEDIA_MATRIX_PATH and isinstance(official_media_matrix, list) and official_media_matrix:
            content = self._render_official_media_matrix_markdown(official_media_matrix)
            return self._build_asset(path=path, title="官方媒体与矩阵", content=content, knowledge_revision=knowledge_revision, updated_at=brand.get("updated_at"))

        if path.startswith("产品信息/"):
            product_name = path.split("/", 1)[1].strip()
            for product in products:
                if str(product.get("product_name") or "").strip() != product_name:
                    continue
                product_aliases = self._normalize_aliases(product.get("product_alias"))
                product_websites = self._normalize_websites(product.get("product_website"))
                product_images = self.normalize_sequence_value(product.get("product_images_json"))
                coverage_regions = self.normalize_sequence_value(product.get("coverage_regions_json"))
                content = self._join_sections(
                    [
                        f"# {product_name}\n\n{self._build_product_summary(product)}",
                        self._markdown_section(
                            "基本信息",
                            self._markdown_key_values(
                                [
                                    ("产品名称", product_name),
                                    ("产品别名", "、".join(product_aliases)),
                                    ("价格信息", str(product.get("price_info") or "").strip()),
                                    ("覆盖区域", "、".join(coverage_regions)),
                                ]
                            ),
                        ),
                        self._markdown_section("产品官网", self._markdown_links(product_websites)),
                        self._markdown_section("产品图片", self._markdown_links(product_images)),
                        self._markdown_section("产品介绍", str(product.get("product_description") or "").strip()),
                        self._markdown_section("产品优势", str(product.get("product_advantages") or "").strip()),
                        self._markdown_section("适用场景", str(product.get("target_scenarios") or "").strip()),
                        self._markdown_section("服务标准", str(product.get("service_standard") or "").strip()),
                        self._markdown_section("服务流程", str(product.get("service_process") or "").strip()),
                        self._markdown_section("案例与口碑", str(product.get("cases_and_reputation") or "").strip()),
                        self._markdown_section("认证信息", str(product.get("certification_info") or "").strip()),
                        self._markdown_section("核心技术", str(product.get("core_technology") or "").strip()),
                        self._markdown_section("其他信息", str(product.get("other_info") or "").strip()),
                    ]
                )
                return self._build_asset(path=path, title=product_name, content=content, knowledge_revision=knowledge_revision, updated_at=product.get("updated_at") or brand.get("updated_at"))

        if path.startswith("竞品信息/"):
            competitor_name = path.split("/", 1)[1].strip()
            competitor_item = None
            if isinstance(competitors_content, list):
                for item in competitors_content:
                    if isinstance(item, dict) and str(item.get("name") or "").strip() == competitor_name:
                        competitor_item = item
                        break
            if competitor_item is None:
                for item in competitors:
                    if str(item.get("name") or "").strip() == competitor_name:
                        competitor_item = item
                        break
            if isinstance(competitor_item, dict):
                competitor_aliases = self._normalize_aliases(
                    competitor_item.get("aliases") or competitor_item.get("competitors_alias")
                )
                competitor_websites = self._normalize_websites(
                    competitor_item.get("website") or competitor_item.get("official_websites")
                )
                competitor_logo_urls = self._normalize_websites(
                    competitor_item.get("competitors_logo") or competitor_item.get("logo_urls")
                )
                comparison_dimensions = self._normalize_multi_value(
                    competitor_item.get("comparison_dimensions")
                )
                content = self._join_sections(
                    [
                        f"# {competitor_name}\n\n{self._build_text_summary(competitor_item.get('introduction') or competitor_item.get('competitors_description') or competitor_item.get('intro'), fallback='竞品资料。')}",
                        self._markdown_section(
                            "基本信息",
                            self._markdown_key_values(
                                [
                                    ("竞品名称", competitor_name),
                                    ("竞品别名", "、".join(competitor_aliases)),
                                ]
                            ),
                        ),
                        self._markdown_section("竞品介绍", str(competitor_item.get("introduction") or competitor_item.get("competitors_description") or competitor_item.get("intro") or "").strip()),
                        self._markdown_section("官网", self._markdown_links(competitor_websites)),
                        self._markdown_section("品牌标识", self._markdown_links(competitor_logo_urls)),
                        self._markdown_section("竞争优势", str(competitor_item.get("competitive_advantages") or competitor_item.get("strengths") or "").strip()),
                        self._markdown_section("差异化定位", str(competitor_item.get("differentiated_positioning") or "").strip()),
                        self._markdown_section("建议对比维度", self._markdown_list(comparison_dimensions)),
                        self._markdown_section("其他信息", str(competitor_item.get("other_info") or "").strip()),
                    ]
                )
                return self._build_asset(path=path, title=competitor_name, content=content, knowledge_revision=knowledge_revision, updated_at=brand.get("updated_at"))

        return None

    @staticmethod
    def _build_asset(
        *,
        path: str,
        title: str,
        content: str,
        knowledge_revision: str,
        updated_at: Any,
    ) -> dict[str, Any]:
        return {
            "title": title,
            "path": path,
            "content": content.strip(),
            "knowledge_revision": knowledge_revision,
            "updated_at": updated_at,
        }
