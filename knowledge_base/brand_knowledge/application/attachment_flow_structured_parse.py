from __future__ import annotations

from typing import Any


class AttachmentDraftStructuredParseMixin:
    def _extract_sheet1_candidate_snapshot(
        self,
        *,
        rows: list[list[str]],
        brand_name: str,
        brand_code: str | None,
    ) -> dict[str, Any]:
        snapshot = self._build_empty_snapshot(brand_name=brand_name, brand_code=brand_code)
        indexed_competitors: dict[str, dict[str, Any]] = {}
        fallback_competitor_dimensions: list[str] = []
        for row in rows[1:]:
            dimension = self._normalize_geo_cell_text(row[0] if len(row) > 0 else "")
            field_name = self._normalize_geo_cell_text(row[1] if len(row) > 1 else "")
            content = self._normalize_geo_cell_text(row[2] if len(row) > 2 else "")
            if self._is_placeholder_sheet1_field(field_name, content):
                continue
            normalized_field = self._normalize_geo_label(field_name)
            normalized_dimension = self._normalize_geo_label(dimension)
            lower_bundle = f"{normalized_dimension}|{normalized_field}"
            urls = self._extract_urls_from_text(content)

            if "品牌标准名" in normalized_field or "品牌名称" in normalized_field:
                subject_name, resolved_brand_name = self._split_brand_subject_and_name(content)
                if resolved_brand_name:
                    snapshot["basic_info"]["brand_name"] = resolved_brand_name
                if subject_name:
                    snapshot["company_profile"]["brand_subject_name"] = subject_name
                continue
            if "品牌别名" in normalized_field or "品牌简称" in normalized_field:
                snapshot["basic_info"]["brand_alias"] = content
                continue
            if "品牌英文名" in normalized_field or normalized_field == "英文名":
                snapshot["basic_info"]["english_name"] = content
                continue
            if "官网地址" in normalized_field or ("官网" in normalized_field and "商城" not in normalized_field):
                snapshot["basic_info"]["website"] = urls or self._split_text_values(content)
                continue
            if "微信公众号" in normalized_field:
                snapshot["basic_info"]["official_wechat_account"] = content.split("\n", 1)[0].strip()
                continue
            if "客服" in normalized_field and ("热线" in normalized_field or "电话" in normalized_field):
                snapshot["basic_info"]["customer_service_hotline"] = self._split_text_values(content)
                continue
            if "品牌定位" in normalized_field or normalized_field == "定位":
                snapshot["basic_info"]["positioning"] = self._split_text_values(content)
                continue
            if any(keyword in normalized_field for keyword in ("品牌优势", "卖点", "核心价值主张", "竞争优势")):
                snapshot["basic_info"]["advantages"] = self._split_text_values(content)
                continue
            if "品牌使命" in normalized_field or normalized_field == "使命":
                snapshot["basic_info"]["mission"] = self._split_text_values(content)
                continue
            if "品牌愿景" in normalized_field or normalized_field == "愿景":
                snapshot["basic_info"]["vision"] = self._split_text_values(content)
                continue
            if any(keyword in normalized_field for keyword in ("目标区域", "覆盖区域", "服务区域", "目标市场")):
                snapshot["basic_info"]["target_regions"] = self._split_text_values(content)
                continue
            if any(keyword in normalized_field for keyword in ("品牌主体", "企业主体", "公司主体", "品牌主体名称")):
                snapshot["company_profile"]["brand_subject_name"] = content
                continue
            if "上市" in lower_bundle or "股票" in normalized_field:
                snapshot["company_profile"]["stock_info"] = content
                continue
            if any(keyword in normalized_field for keyword in self._COMPANY_ADDRESS_HINT_KEYWORDS):
                snapshot["company_profile"]["company_address"] = content
                continue
            if any(keyword in normalized_field for keyword in ("公司简介", "企业简介", "主体简介", "品牌介绍", "品牌简介", "品牌概述")):
                snapshot["company_profile"]["company_intro"] = content
                continue
            if any(keyword in normalized_field for keyword in ("成立时间", "创立时间", "创办时间")):
                snapshot["company_profile"]["established_time"] = content
                continue
            if any(keyword in normalized_field for keyword in ("门店分布", "门店数量", "网点分布", "渠道分布")):
                snapshot["company_profile"]["store_distribution"] = content
                continue
            if any(keyword in normalized_field for keyword in self._COMPANY_RECENT_NEWS_HINT_KEYWORDS):
                snapshot["company_profile"]["recent_news"] = content
                continue
            if any(keyword in normalized_field for keyword in self._COMPANY_DEVELOPMENT_HISTORY_HINT_KEYWORDS):
                snapshot["company_profile"]["development_history"] = content
                continue
            if any(keyword in lower_bundle for keyword in ("高管", "创始人", "董事长", "总裁", "ceo", "管理团队")):
                snapshot["management_team"].extend(
                    self._extract_management_members_from_text(content, source_section=field_name)
                )
                continue
            if any(keyword in lower_bundle for keyword in (self._COMPETITOR_NAME_HINT_KEYWORDS + self._COMPETITOR_COMPARISON_HINT_KEYWORDS)):
                index = self._extract_trailing_index(field_name) or self._extract_trailing_index(dimension) or ""
                if any(keyword in normalized_field for keyword in self._COMPETITOR_COMPARISON_HINT_KEYWORDS):
                    dimensions = self._split_text_values(content) or [content]
                    if index:
                        entry = indexed_competitors.setdefault(
                            index,
                            {
                                "name": "",
                                "comparison_dimensions": [],
                                "source_section": field_name,
                            },
                        )
                        self._append_unique_values(entry["comparison_dimensions"], dimensions)
                    else:
                        self._append_unique_values(fallback_competitor_dimensions, dimensions)
                    continue
                if any(keyword in normalized_field for keyword in self._COMPETITOR_NAME_HINT_KEYWORDS):
                    competitor_names = self._split_text_values(content) or [content]
                    for competitor_name in competitor_names:
                        entry = indexed_competitors.setdefault(
                            index or competitor_name,
                            {
                                "name": "",
                                "comparison_dimensions": [],
                                "source_section": field_name,
                            },
                        )
                        if not entry.get("name"):
                            entry["name"] = competitor_name
                    continue
            if any(
                keyword in lower_bundle for keyword in (
                    self._SENSITIVE_FORBIDDEN_HINT_KEYWORDS
                    + self._SENSITIVE_CONTROVERSIAL_HINT_KEYWORDS
                    + self._SENSITIVE_NEGATIVE_CLARIFICATION_HINT_KEYWORDS
                )
            ):
                sensitive_buckets = self._extract_sensitive_topic_buckets(field_name, content)
                for key, values in sensitive_buckets.items():
                    self._append_unique_values(snapshot["sensitive_topics"][key], values)
                continue
            media_platform = self._infer_media_platform(field_name, content)
            if (media_platform or any(keyword in normalized_field for keyword in self._MEDIA_ACCOUNT_HINT_KEYWORDS)) and "商城" not in normalized_field and "店" not in normalized_field:
                snapshot["official_media_matrix"].extend(self._extract_media_entries_from_sheet1(field_name, content))
                continue
            if any(keyword in lower_bundle for keyword in ("商城", "旗舰店", "小店", "购买店铺", "天猫", "京东")):
                snapshot["official_malls"].append(
                    {
                        "store_name": content.split("\n", 1)[0].strip(),
                        "platform": self._infer_media_platform(field_name, content) or field_name,
                        "homepage_urls": urls,
                        "store_ids": [],
                        "main_categories": [],
                        "advantages": [],
                        "related_products": [],
                        "other_info": [],
                    }
                )
                continue
            if self._should_capture_authority_honor(dimension, field_name, content):
                snapshot["authority_honors"].append(
                    {
                        "title": field_name,
                        "year": self._prefer_specific_award_date(None, field_name, content),
                        "description": content,
                        "report_link": "；".join(urls),
                        "qualification_proof": "",
                        "source_section": dimension or field_name,
                    }
                )
                continue
            if self._should_skip_other_info_field(field_name, content):
                continue
            snapshot["other_info"].append({"title": field_name, "content": content})
        for index, item in indexed_competitors.items():
            competitor_name = self._normalize_optional_str(item.get("name"))
            comparison_dimensions = self._normalize_string_list(item.get("comparison_dimensions"))
            if not competitor_name:
                continue
            if not comparison_dimensions and fallback_competitor_dimensions and index in {"1", "一"}:
                comparison_dimensions = list(fallback_competitor_dimensions)
            snapshot["competitors"].append(
                {
                    "name": competitor_name,
                    "comparison_dimensions": comparison_dimensions,
                    "source_section": self._normalize_optional_str(item.get("source_section")),
                }
            )
        return self._sanitize_candidate_other_info(self._prune_empty_payload(snapshot))

    def _extract_generic_table_candidate(
        self,
        *,
        sheet_title: str,
        rows: list[list[str]],
        brand_name: str,
        brand_code: str | None,
    ) -> dict[str, Any]:
        promoted_rows = self._maybe_promote_secondary_header_row(rows)
        headers = promoted_rows[0]
        data_rows = promoted_rows[1:]
        table_type = self._table_header_identity(headers, sheet_title)
        if not table_type:
            return {}
        snapshot = self._build_empty_snapshot(brand_name=brand_name, brand_code=brand_code)
        header_labels = [self._normalize_geo_cell_text(header) for header in headers]
        for row in data_rows:
            row_map = {
                header_labels[index]: self._normalize_geo_cell_text(row[index] if index < len(row) else "")
                for index in range(len(header_labels))
                if self._normalize_geo_cell_text(header_labels[index])
            }
            if table_type == "products":
                name_header = self._find_matching_header(row_map, ("产品名", "产品名称", "商品名", "sku", "名称"))
                if not name_header or not row_map.get(name_header):
                    continue
                line_header = self._find_matching_header(row_map, ("产品线", "系列"))
                sequence_header = self._find_matching_header(row_map, ("序号", "编号"))
                price_header = self._find_matching_header(row_map, self._PRODUCT_PRICE_HINT_KEYWORDS + ("价",))
                website_header = self._find_matching_header(row_map, self._PRODUCT_WEBSITE_HINT_KEYWORDS + ("链接", "网址"))
                advantages_header = self._find_matching_header(row_map, self._PRODUCT_ADVANTAGES_HINT_KEYWORDS + ("添加",))
                scenarios_header = self._find_matching_header(row_map, self._PRODUCT_TARGET_SCENARIOS_HINT_KEYWORDS)
                service_standard_header = self._find_matching_header(row_map, self._PRODUCT_SERVICE_STANDARD_HINT_KEYWORDS + ("包装", "保质期", "储存条件"))
                service_process_header = self._find_matching_header(row_map, self._PRODUCT_SERVICE_PROCESS_HINT_KEYWORDS + ("流程", "节点"))
                certification_header = self._find_matching_header(row_map, self._PRODUCT_CERTIFICATION_HINT_KEYWORDS + ("获奖", "检测", "证书"))
                technology_header = self._find_matching_header(row_map, self._PRODUCT_CORE_TECH_HINT_KEYWORDS + ("技术", "配方"))
                excluded = {
                    header for header in (
                        name_header,
                        line_header,
                        sequence_header,
                        price_header,
                        website_header,
                        advantages_header,
                        scenarios_header,
                        service_standard_header,
                        service_process_header,
                        certification_header,
                        technology_header,
                    ) if header
                }
                website_urls = self._extract_urls_from_text(row_map.get(website_header, "")) if website_header else []
                snapshot["products"].append(
                    {
                        "name": row_map.get(name_header),
                        "product_alias": row_map.get(line_header, "") if line_header else "",
                        "product_description": self._join_row_details(row_map, excluded) or "",
                        "product_website": "; ".join(website_urls or self._extract_urls_from_text("\n".join(row_map.values()))),
                        "product_images": [],
                        "price_info": row_map.get(price_header, "") if price_header else "",
                        "coverage_regions": [],
                        "product_advantages": row_map.get(advantages_header, "") if advantages_header else "",
                        "target_scenarios": row_map.get(scenarios_header, "") if scenarios_header else "",
                        "service_standard": row_map.get(service_standard_header, "") if service_standard_header else "",
                        "service_process": row_map.get(service_process_header, "") if service_process_header else "",
                        "cases_and_reputation": "",
                        "certification_info": row_map.get(certification_header, "") if certification_header else "",
                        "core_technology": row_map.get(technology_header, "") if technology_header else "",
                        "other_info": self._join_row_details(row_map, {name_header}) or "",
                    }
                )
                continue
            if table_type == "authority_honors":
                title_header = self._find_matching_header(row_map, ("类目", "奖项", "荣誉", "认证", "背书", "名称", "标题"))
                if not title_header or not row_map.get(title_header):
                    continue
                description = self._join_row_details(row_map, {title_header}) or row_map.get(title_header)
                urls = self._extract_urls_from_text("\n".join(row_map.values()))
                snapshot["authority_honors"].append(
                    {
                        "title": row_map.get(title_header),
                        "year": self._prefer_specific_award_date(None, row_map.get(title_header), description),
                        "description": description,
                        "report_link": "；".join(urls),
                        "qualification_proof": "",
                        "source_section": sheet_title,
                    }
                )
                continue
            if table_type == "official_media_matrix":
                platform_header = self._find_matching_header(row_map, ("平台", "媒体平台", "账号平台"))
                name_header = self._find_matching_header(row_map, ("账号名称", "账号名", "官方账号", "账号"))
                if not (platform_header or name_header):
                    continue
                snapshot["official_media_matrix"].append(
                    {
                        "media_platform": row_map.get(platform_header, "") if platform_header else self._infer_media_platform(sheet_title),
                        "account_name": row_map.get(name_header, "") if name_header else "",
                        "account_id": row_map.get(self._find_matching_header(row_map, ("账号id", "账号编号", "平台号")) or "", ""),
                        "is_official": row_map.get(self._find_matching_header(row_map, ("官方", "认证", "蓝v")) or "", ""),
                        "homepage_urls": self._extract_urls_from_text("\n".join(row_map.values())),
                        "fans_count": row_map.get(self._find_matching_header(row_map, ("粉丝", "关注")) or "", ""),
                        "content_focus": self._split_text_values(row_map.get(self._find_matching_header(row_map, ("内容方向", "内容重点", "定位")) or "")),
                        "related_products": [],
                        "other_info": [],
                    }
                )
                continue
            if table_type == "official_malls":
                store_header = self._find_matching_header(row_map, ("店铺", "店铺名称", "商城", "旗舰店", "店名"))
                platform_header = self._find_matching_header(row_map, ("平台", "商城平台", "电商平台"))
                if not (store_header or platform_header):
                    continue
                snapshot["official_malls"].append(
                    {
                        "store_name": row_map.get(store_header, "") if store_header else "",
                        "platform": row_map.get(platform_header, "") if platform_header else "",
                        "homepage_urls": self._extract_urls_from_text("\n".join(row_map.values())),
                        "store_ids": self._split_text_values(row_map.get(self._find_matching_header(row_map, ("店铺id", "店铺号", "店铺编号")) or "")),
                        "main_categories": self._split_text_values(row_map.get(self._find_matching_header(row_map, ("主营品类", "主营类目")) or "")),
                        "advantages": self._split_text_values(row_map.get(self._find_matching_header(row_map, ("店铺优势", "商城优势", "优势")) or "")),
                        "related_products": [],
                        "other_info": [],
                    }
                )
                continue
            if table_type == "competitors":
                name_header = self._find_matching_header(row_map, ("竞品", "竞争对手", "对标品牌", "名称"))
                if not name_header or not row_map.get(name_header):
                    continue
                snapshot["competitors"].append(
                    {
                        "name": row_map.get(name_header),
                        "aliases": self._split_text_values(row_map.get(self._find_matching_header(row_map, ("别名", "简称")) or "")),
                        "introduction": row_map.get(self._find_matching_header(row_map, ("介绍", "描述")) or "", ""),
                        "official_websites": self._extract_urls_from_text(row_map.get(self._find_matching_header(row_map, ("官网", "链接", "网址")) or "", "")),
                        "strengths": self._split_text_values(row_map.get(self._find_matching_header(row_map, ("优势", "强项")) or "")),
                        "differentiated_positioning": self._split_text_values(row_map.get(self._find_matching_header(row_map, ("差异化", "差异点", "定位")) or "")),
                        "comparison_dimensions": self._split_text_values(
                            row_map.get(self._find_matching_header(row_map, ("对比维度", "建议对比维度", "对比口径")) or "")
                        ),
                        "source_section": sheet_title,
                    }
                )
                continue
            if table_type == "sensitive_topics":
                topic_header = self._find_matching_header(row_map, ("争议", "风险", "敏感", "话题", "事件"))
                forbidden_header = self._find_matching_header(row_map, ("极限词", "禁用词", "禁止表述", "敏感词"))
                clarification_header = self._find_matching_header(row_map, ("负面澄清", "统一口径", "回应口径"))
                description_header = self._find_matching_header(row_map, ("描述", "说明", "内容"))
                if not any((topic_header, forbidden_header, clarification_header, description_header)):
                    continue
                self._append_unique_values(
                    snapshot["sensitive_topics"]["sensitive_contents"],
                    self._split_text_values(row_map.get(topic_header, "") or row_map.get(description_header, "")),
                )
                self._append_unique_values(
                    snapshot["sensitive_topics"]["controversial_events"],
                    self._split_text_values(row_map.get(topic_header, "")),
                )
                self._append_unique_values(
                    snapshot["sensitive_topics"]["forbidden_words"],
                    self._split_text_values(row_map.get(forbidden_header, "")),
                )
                self._append_unique_values(
                    snapshot["sensitive_topics"]["negative_clarifications"],
                    self._split_text_values(row_map.get(clarification_header, "")),
                )
                continue
            if table_type == "customers_cases":
                case_header = self._find_matching_header(row_map, ("案例", "案例名称", "项目"))
                customer_header = self._find_matching_header(row_map, ("客户", "合作客户"))
                if not (case_header or customer_header):
                    continue
                snapshot["customers_cases"].append(
                    {
                        "case_name": row_map.get(case_header, "") if case_header else "",
                        "cooperation_time": row_map.get(self._find_matching_header(row_map, ("合作时间", "服务时间", "时间")) or "", ""),
                        "customer_name": row_map.get(customer_header, "") if customer_header else "",
                        "cooperation_product": row_map.get(self._find_matching_header(row_map, ("合作产品", "服务产品")) or "", ""),
                        "cooperation_highlight": row_map.get(self._find_matching_header(row_map, ("亮点", "成果", "成效")) or "", ""),
                        "customer_feedback": row_map.get(self._find_matching_header(row_map, ("反馈", "评价", "证言")) or "", ""),
                        "source_section": sheet_title,
                    }
                )
                continue
            if table_type == "management_team":
                name_header = self._find_matching_header(row_map, ("姓名", "成员", "高管", "创始人"))
                if not name_header or not row_map.get(name_header):
                    continue
                snapshot["management_team"].append(
                    {
                        "name": row_map.get(name_header),
                        "title": row_map.get(self._find_matching_header(row_map, ("职务", "职位", "头衔")) or "", ""),
                        "profile": row_map.get(self._find_matching_header(row_map, ("简介", "履历", "介绍")) or "", ""),
                        "introduction_website": "; ".join(self._extract_urls_from_text("\n".join(row_map.values()))),
                        "source_section": sheet_title,
                        "other_info": "",
                    }
                )
        return self._sanitize_candidate_other_info(self._prune_empty_payload(snapshot))

    def _extract_structured_candidate_from_xlsx_markdown(
        self,
        *,
        markdown_text: str,
        brand_name: str,
        brand_code: str | None,
    ) -> tuple[dict[str, Any], str]:
        sections = self._split_sheet_sections(markdown_text)
        if not sections:
            return {}, self._normalize_markdown_text(markdown_text)
        aggregated_snapshot = self._build_empty_snapshot(brand_name=brand_name, brand_code=brand_code)
        residual_sections: list[str] = []
        consumed_any = False
        for section in sections:
            rows = self._parse_markdown_table_rows(section.get("body"))
            section_snapshot: dict[str, Any] = {}
            if rows and self._is_geo_sheet1_rows(rows):
                section_snapshot = self._extract_sheet1_candidate_snapshot(
                    rows=rows,
                    brand_name=brand_name,
                    brand_code=brand_code,
                )
            elif rows:
                section_snapshot = self._extract_generic_table_candidate(
                    sheet_title=section.get("title", ""),
                    rows=rows,
                    brand_name=brand_name,
                    brand_code=brand_code,
                )
            if self._has_meaningful_payload(section_snapshot):
                aggregated_snapshot = self._merge_snapshot(
                    current_snapshot=aggregated_snapshot,
                    candidate_snapshot=section_snapshot,
                )
                consumed_any = True
                continue
            residual_sections.append(section.get("raw", ""))
        residual_markdown = "\n\n".join(section for section in residual_sections if section).strip()
        if not consumed_any:
            return {}, self._normalize_markdown_text(markdown_text)
        return (
            self._sanitize_candidate_other_info(self._prune_empty_payload(aggregated_snapshot)),
            residual_markdown,
        )

    def _extract_structured_candidate_from_parsed_items(
        self,
        *,
        parsed_items: list[dict[str, Any]],
        brand_name: str,
        brand_code: str | None,
    ) -> tuple[dict[str, Any], str]:
        aggregated_snapshot = self._build_empty_snapshot(brand_name=brand_name, brand_code=brand_code)
        residual_parts: list[str] = []
        consumed_any = False
        for item in parsed_items:
            if not isinstance(item, dict) or str(item.get("status") or "").strip() != "success":
                continue
            markdown_text = self._normalize_markdown_text(item.get("markdown_text") or item.get("parsed_text"))
            if not markdown_text:
                continue
            if str(item.get("source_type") or "").strip().lower() != "xlsx":
                residual_parts.append(markdown_text)
                continue
            structured_snapshot, residual_markdown = self._extract_structured_candidate_from_xlsx_markdown(
                markdown_text=markdown_text,
                brand_name=brand_name,
                brand_code=brand_code,
            )
            if self._has_meaningful_payload(structured_snapshot):
                consumed_any = True
                aggregated_snapshot = self._merge_snapshot(
                    current_snapshot=aggregated_snapshot,
                    candidate_snapshot=structured_snapshot,
                )
            if residual_markdown:
                residual_parts.append(residual_markdown)
        return (
            self._sanitize_candidate_other_info(self._prune_empty_payload(aggregated_snapshot)) if consumed_any else {},
            "\n\n".join(part for part in residual_parts if part).strip(),
        )
