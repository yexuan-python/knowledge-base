from __future__ import annotations

import hashlib
import json
from typing import Any

from knowledge_base.brand.application.brand_scope import resolve_brand_scope_from_codes
from knowledge_base.document.schemas import SearchRequest


class BrandStructuredSearchMixin:
    @staticmethod
    def _query_contains_any(normalized_query: str, keywords: tuple[str, ...]) -> bool:
        return any(keyword in normalized_query for keyword in keywords)

    @classmethod
    def _normalize_structured_content(cls, content: Any) -> str:
        if isinstance(content, str):
            return content
        normalized_content = cls._prune_empty_structured_content(content)
        return cls._stringify_structured_content(normalized_content)

    @classmethod
    def _prune_empty_structured_content(cls, value: Any) -> Any:
        if isinstance(value, dict):
            normalized: dict[str, Any] = {}
            for key, item in value.items():
                pruned_item = cls._prune_empty_structured_content(item)
                if cls._has_meaningful_payload(pruned_item):
                    normalized[str(key)] = pruned_item
            return normalized
        if isinstance(value, list):
            normalized_items = [cls._prune_empty_structured_content(item) for item in value]
            return [item for item in normalized_items if cls._has_meaningful_payload(item)]
        return value

    @classmethod
    def _stringify_structured_content(cls, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            if not value:
                return ""
            if all(not isinstance(item, (dict, list)) for item in value):
                return "、".join(str(item).strip() for item in value if str(item).strip())
            return "；".join(
                rendered
                for rendered in (cls._stringify_structured_content(item) for item in value)
                if rendered
            )
        if isinstance(value, dict):
            if cls._looks_like_competitor_item(value):
                return cls._stringify_competitor_item(value)
            field_labels = {
                "name": "名称",
                "aliases": "别名",
                "introduction": "介绍",
                "official_websites": "官网",
                "logo_urls": "Logo",
                "strengths": "优势",
                "other_info": "其他信息",
                "comparison_dimensions": "对比维度",
                "differentiated_positioning": "差异化定位",
                "competitors_name": "名称",
                "competitors_alias": "别名",
                "competitors_description": "介绍",
                "website": "官网",
                "competitors_logo": "Logo",
                "competitive_advantages": "优势",
            }
            parts: list[str] = []
            for key, item in value.items():
                rendered = cls._stringify_structured_content(item)
                if not rendered:
                    continue
                label = field_labels.get(str(key), str(key))
                parts.append(f"{label}：{rendered}")
            return "；".join(parts)
        return str(value).strip()

    @staticmethod
    def _looks_like_competitor_item(value: dict[str, Any]) -> bool:
        competitor_keys = {
            "name",
            "aliases",
            "introduction",
            "official_websites",
            "logo_urls",
            "strengths",
            "other_info",
            "comparison_dimensions",
            "differentiated_positioning",
            "competitors_name",
            "competitors_alias",
            "competitors_description",
            "website",
            "competitors_logo",
            "competitive_advantages",
        }
        return bool(competitor_keys.intersection(value.keys())) and bool(
            str(value.get("name") or value.get("competitors_name") or "").strip()
        )

    @classmethod
    def _stringify_competitor_item(cls, item: dict[str, Any]) -> str:
        name = str(item.get("name") or item.get("competitors_name") or "").strip()
        if not name:
            return ""

        aliases = cls._normalize_aliases(item.get("aliases") or item.get("competitors_alias"))
        websites = cls._normalize_websites(item.get("official_websites") or item.get("website"))
        logo_urls = cls._normalize_websites(item.get("logo_urls") or item.get("competitors_logo"))
        strengths = cls._normalize_multi_value(item.get("strengths") or item.get("competitive_advantages"))
        comparison_dimensions = cls._normalize_multi_value(item.get("comparison_dimensions"))
        differentiated_positioning = cls._normalize_multi_value(item.get("differentiated_positioning"))
        other_info = cls._normalize_multi_value(item.get("other_info"))
        introduction = str(item.get("introduction") or item.get("competitors_description") or "").strip()

        details: list[str] = []
        if aliases:
            details.append(f"别名：{'、'.join(aliases)}")
        if introduction:
            details.append(f"介绍：{introduction}")
        if strengths:
            details.append(f"优势：{'、'.join(strengths)}")
        if differentiated_positioning:
            details.append(f"差异化定位：{'、'.join(differentiated_positioning)}")
        if comparison_dimensions:
            details.append(f"对比维度：{'、'.join(comparison_dimensions)}")
        if websites:
            details.append(f"官网：{'、'.join(websites)}")
        if logo_urls:
            details.append(f"Logo：{'、'.join(logo_urls)}")
        if other_info:
            details.append(f"其他信息：{'、'.join(other_info)}")
        if not details:
            return name
        return f"{name}（{'；'.join(details)}）"

    @staticmethod
    def _structured_query_target_tags(normalized_query: str) -> set[str]:
        tag_mappings = (
            (
                "brand_basic",
                (
                    "品牌名称",
                    "品牌名",
                    "官网",
                    "官网链接",
                    "官网地址",
                    "网址",
                    "英文名",
                    "企业主体",
                    "主体名称",
                    "行业",
                    "所属行业",
                    "品牌定位",
                    "核心优势",
                    "品牌优势",
                    "品牌使命",
                    "品牌愿景",
                ),
            ),
            ("company_profile", ("公司档案", "公司信息", "企业信息")),
            ("competitors", ("竞品", "竞争对手", "对比", "差异")),
            ("customers_cases", ("合作客户", "客户案例", "合作案例")),
            ("management_team", ("管理团队",)),
            ("authority_honors", ("荣誉", "背书", "奖项", "认证", "权威", "资质", "证书")),
            ("milestones", ("里程碑", "发展历程", "大事件", "关键节点")),
            ("coverage", ("覆盖区域", "覆盖地域", "覆盖城市", "区域覆盖", "服务范围")),
            ("target_users", ("目标用户", "目标客户", "用户群体", "适用人群")),
            ("scenarios", ("应用场景", "使用场景", "核心场景", "适用场景")),
            ("common_objections", ("常见用户质疑", "用户质疑", "用户疑虑", "常见问题")),
            ("sensitive_topics", ("敏感话题", "敏感", "风险", "争议", "舆情", "投诉")),
            ("attachments", ("相关附件", "附件", "手册", "图册", "资料", "pdf")),
            ("official_malls", ("官方商城", "商城", "店铺", "旗舰店", "开店平台", "主营品类", "店铺优势")),
            ("official_media_matrix", ("官方媒体", "媒体矩阵", "账号矩阵", "媒体平台", "公众号", "微博", "小红书", "抖音")),
            (
                "product",
                ("产品", "产品信息", "产品介绍", "价格", "产品价格", "主要产品", "主要服务", "产品矩阵", "核心品类", "主营品类"),
            ),
        )
        target_tags: set[str] = set()
        for tag, keywords in tag_mappings:
            if any(keyword in normalized_query for keyword in keywords):
                target_tags.add(tag)
        return target_tags

    def search_structured(self, request: SearchRequest) -> list[dict[str, Any]]:
        brand_name = str(getattr(request, "brand_name", None) or request.category or "").strip()
        scope = resolve_brand_scope_from_codes(
            self._deps,
            brand_code=getattr(request, "brand_code", None),
            brand_name=getattr(request, "brand_name", None),
            category=getattr(request, "category", None),
            product_code=getattr(request, "product_code", None),
        )
        brand = scope.brand

        if scope.product_code:
            if brand is None:
                return []
            brand_name = str(scope.brand_name or "").strip()
        elif scope.brand_code and brand is not None:
            if not brand:
                return []
            brand_name = str(scope.brand_name or "").strip()

        if not brand_name and brand is None:
            return []
        if brand is None:
            brand = self._deps.brands.get_brand_by_name(brand_name)
        if not brand:
            return []

        brand_id, products, knowledge_rows, _knowledge_map = self._load_brand_snapshot(brand=brand)
        if brand_id is None:
            return []
        brand_code = self._brand_code_from_row(brand)
        normalized_query = (request.query or "").strip()
        target_tags = self._structured_query_target_tags(normalized_query)
        knowledge_revision = str(brand.get("knowledge_revision") or "").strip() or None
        structured_candidates: list[dict[str, Any]] = []
        knowledge_type_configs: dict[str, dict[str, Any]] = {
            "company_profile": {
                "display_name": "公司档案",
                "keywords": ("公司档案", "公司信息", "企业信息", "品牌主题名称", "主体名称", "总部", "成立", "上市"),
                "score": 0.99,
                "tags": ("company_profile",),
            },
            "company_info": {
                "display_name": "公司档案",
                "keywords": ("公司档案", "公司信息", "企业信息", "品牌主题名称", "主体名称", "总部", "成立", "上市"),
                "score": 0.99,
                "tags": ("company_profile",),
            },
            "management_team": {
                "display_name": "管理团队",
                "keywords": ("管理团队", "高管", "团队", "董事长", "总经理", "负责人"),
                "score": 0.98,
                "tags": ("management_team",),
            },
            "competitors": {
                "display_name": "竞品信息",
                "keywords": ("竞品", "竞争对手", "对比", "差异"),
                "score": 0.98,
                "tags": ("competitors",),
            },
            "authority_honors": {
                "display_name": "权威背书与荣誉",
                "keywords": ("荣誉", "背书", "奖项", "认证", "权威", "资质", "证书"),
                "score": 0.97,
                "tags": ("authority_honors",),
            },
            "honors": {
                "display_name": "权威背书与荣誉",
                "keywords": ("荣誉", "背书", "奖项", "认证", "权威", "资质", "证书"),
                "score": 0.97,
                "tags": ("authority_honors",),
            },
            "customers_cases": {
                "display_name": "合作客户与案例",
                "keywords": ("客户", "合作客户", "案例", "项目", "合作案例"),
                "score": 0.97,
                "tags": ("customers_cases",),
            },
            "cases": {
                "display_name": "合作客户与案例",
                "keywords": ("客户", "合作客户", "案例", "项目", "合作案例"),
                "score": 0.97,
                "tags": ("customers_cases",),
            },
            "sensitive_topics": {
                "display_name": "敏感话题",
                "keywords": ("敏感", "风险", "争议", "舆情", "投诉", "常见用户质疑", "用户质疑", "用户疑虑", "常见问题"),
                "score": 0.96,
                "tags": ("sensitive_topics", "common_objections"),
            },
            "attachments": {
                "display_name": "相关附件",
                "keywords": ("附件", "相关附件", "手册", "图册", "pdf", "资料"),
                "score": 0.95,
                "tags": ("attachments",),
            },
            "official_malls": {
                "display_name": "官方商城",
                "keywords": ("官方商城", "商城", "店铺", "旗舰店", "开店平台", "主营品类", "店铺优势"),
                "score": 0.96,
                "tags": ("official_malls",),
            },
            "official_media_matrix": {
                "display_name": "官方媒体与矩阵",
                "keywords": ("官方媒体", "媒体矩阵", "账号矩阵", "媒体平台", "公众号", "微博", "小红书", "抖音"),
                "score": 0.96,
                "tags": ("official_media_matrix",),
            },
        }
        brand_field_configs = (
            ("brand_name", "品牌名称", ("品牌名称", "品牌名"), 1.0, ("brand_basic",)),
            ("brand_alias", "品牌别名及曾用名", ("品牌别名", "曾用名", "别名"), 0.98, ("brand_basic",)),
            ("brand_logo", "品牌Logo", ("logo", "Logo", "品牌logo", "品牌Logo"), 0.96, ("brand_basic",)),
            ("website", "品牌官网", ("官网", "官方网站", "品牌官网", "官网链接", "官网地址", "网址"), 0.97, ("brand_basic",)),
            ("customer_service_hotline", "客服热线", ("客服热线", "热线", "客服电话"), 0.97, ("brand_basic",)),
            ("official_wechat_account", "官方微信公众号", ("微信公众号", "官方微信", "公众号"), 0.97, ("brand_basic",)),
            ("brand_enterprise_entity", "品牌企业主体", ("企业主体", "主体名称", "品牌主体", "企业名称", "公司主体"), 1.0, ("brand_basic",)),
            ("business_license_image_path", "营业执照图片路径", ("营业执照", "执照", "营业证照"), 1.0, ("brand_basic",)),
            ("english_name", "品牌英文名", ("英文名", "英文名称", "英文"), 0.98, ("brand_basic",)),
            ("industry_id", "所属行业", ("行业", "所属行业", "赛道"), 0.98, ("brand_basic",)),
            ("positioning", "品牌定位", ("品牌定位", "定位", "品牌力"), 0.99, ("brand_basic",)),
            ("advantages", "品牌优势", ("品牌优势", "核心优势", "优势", "品牌力"), 1.0, ("brand_basic",)),
            ("mission", "品牌使命", ("品牌使命", "使命"), 0.96, ("brand_basic",)),
            ("vision", "品牌愿景", ("品牌愿景", "愿景"), 0.96, ("brand_basic",)),
            ("intro", "品牌介绍", ("品牌介绍", "简介", "介绍"), 0.94, ("brand_basic",)),
            ("target_regions_json", "覆盖地域", ("目标区域", "区域", "覆盖区域", "覆盖地域", "覆盖城市", "服务范围", "目标市场"), 0.97, ("brand_basic", "coverage")),
            ("other_info", "其他信息", ("其他信息", "补充信息"), 0.9, ("brand_basic",)),
        )
        for field_name, label, keywords, score, tags in brand_field_configs:
            value = brand.get(field_name)
            if value is None or value == "":
                continue
            if field_name == "industry_id":
                value = self._resolve_industry_name(brand)
                if not value:
                    continue
            if field_name == "website":
                normalized_websites = self._normalize_websites(value)
                value = "；".join(normalized_websites) if normalized_websites else ""
                if not value:
                    continue
            if field_name in {"customer_service_hotline", "positioning", "advantages", "mission", "vision"}:
                if field_name in {"positioning", "advantages", "mission", "vision"}:
                    normalized_values = self._normalize_brand_text_multi_value(value)
                else:
                    normalized_values = self._normalize_multi_value(value)
                value = "、".join(normalized_values)
                if not value:
                    continue
            if field_name == "target_regions_json":
                normalized_regions = self.normalize_sequence_value(value)
                value = "、".join(normalized_regions) if normalized_regions else ""
                if not value:
                    continue
            structured_candidates.append(
                {
                    "text": f"{label}：{value}",
                    "score": score,
                    "keywords": keywords,
                    "tags": tags,
                    "section_title": label,
                }
            )

        for product in products:
            product_name = str(product.get("product_name") or "").strip()
            product_code = str(product.get("product_code") or "").strip()
            coverage_regions = self.normalize_sequence_value(product.get("coverage_regions") or product.get("coverage_regions_json"))
            target_scenarios = str(product.get("target_scenarios") or "").strip()
            product_description = str(product.get("product_description") or "").strip()
            product_lines = [
                f"产品编码：{product_code}" if product_code else None,
                f"产品名称：{product_name}" if product_name else None,
                f"产品别名：{product.get('product_alias')}" if product.get("product_alias") else None,
                f"产品介绍：{product_description}" if product_description else None,
                f"产品网站：{product.get('product_website')}" if product.get("product_website") else None,
                f"价格信息：{product.get('price_info')}" if product.get("price_info") else None,
                f"产品优势：{product.get('product_advantages')}" if product.get("product_advantages") else None,
                f"覆盖地域：{'、'.join(coverage_regions)}" if coverage_regions else None,
                f"适用场景：{target_scenarios}" if target_scenarios else None,
                f"服务标准：{product.get('service_standard')}" if product.get("service_standard") else None,
                f"服务流程：{product.get('service_process')}" if product.get("service_process") else None,
            ]
            product_text = "\n".join(line for line in product_lines if line)
            if not product_text:
                continue
            structured_candidates.append(
                {
                    "text": product_text,
                    "score": 0.95 if self._query_contains_any(normalized_query, ("产品", "产品信息", "产品介绍")) else 0.93,
                    "keywords": (
                        "产品", "产品信息", "产品介绍", "主要产品", "主要服务", "产品矩阵", "价格", "产品价格", "产品优势",
                        "核心品类", "主营品类", "覆盖地域", "覆盖区域", "目标用户", "目标客户", "用户群体", "适用场景",
                        "应用场景", "使用场景", "核心场景", "服务标准", "服务流程", product_name,
                    ),
                    "tags": ("product",),
                    "section_title": product_name or "产品信息",
                }
            )
            if product_name:
                structured_candidates.append(
                    {
                        "text": f"核心品类：{product_name}",
                        "score": 0.98,
                        "keywords": ("核心品类", "主营品类", "品类", "主要产品", product_name),
                        "tags": ("product",),
                        "section_title": "核心品类",
                    }
                )
                summary_parts = [part for part in (product_name, product_description) if part]
                if summary_parts:
                    structured_candidates.append(
                        {
                            "text": f"主要产品/服务：{'。'.join(summary_parts)}",
                            "score": 0.97,
                            "keywords": ("主要产品", "主要服务", "产品介绍", "产品信息", "产品矩阵", product_name),
                            "tags": ("product",),
                            "section_title": "主要产品/服务",
                        }
                    )
            if coverage_regions:
                structured_candidates.append(
                    {
                        "text": f"覆盖地域：{'、'.join(coverage_regions)}",
                        "score": 0.97,
                        "keywords": ("覆盖地域", "覆盖区域", "覆盖城市", "区域覆盖", "服务范围"),
                        "tags": ("coverage",),
                        "section_title": "覆盖地域",
                    }
                )
            if target_scenarios:
                structured_candidates.append(
                    {
                        "text": f"核心应用场景：{target_scenarios}",
                        "score": 0.97,
                        "keywords": ("应用场景", "使用场景", "核心场景", "适用场景", "目标用户", "目标客户", "用户群体", "适用人群"),
                        "tags": ("scenarios", "target_users"),
                        "section_title": "核心应用场景",
                    }
                )

        for row in knowledge_rows:
            raw_content = row.get("content_json")
            if isinstance(raw_content, str):
                try:
                    content = json.loads(raw_content)
                except json.JSONDecodeError:
                    content = raw_content
            else:
                content = raw_content
            knowledge_type = str(row.get("knowledge_type") or "")
            if knowledge_type == "competitors" and not self._has_competitors_content(content):
                continue
            config = knowledge_type_configs.get(
                knowledge_type,
                {"display_name": knowledge_type, "keywords": (knowledge_type,), "score": 0.9, "tags": (knowledge_type,)},
            )
            structured_candidates.append(
                {
                    "text": f"{config['display_name']}：{self._normalize_structured_content(content)}",
                    "score": float(config["score"]),
                    "keywords": tuple(config["keywords"]),
                    "tags": tuple(config["tags"]),
                    "section_title": str(config["display_name"]),
                }
            )
            if knowledge_type in {"authority_honors", "honors"}:
                normalized_content = self._normalize_structured_content(content)
                structured_candidates.append(
                    {
                        "text": f"资质与里程碑：{normalized_content}",
                        "score": 0.97,
                        "keywords": ("资质", "认证", "证书", "里程碑", "发展历程"),
                        "tags": ("authority_honors", "milestones"),
                        "section_title": "资质与里程碑",
                    }
                )
            if knowledge_type == "sensitive_topics":
                structured_candidates.append(
                    {
                        "text": f"常见用户质疑：{self._normalize_structured_content(content)}",
                        "score": 0.96,
                        "keywords": ("常见用户质疑", "用户质疑", "用户疑虑", "常见问题"),
                        "tags": ("common_objections", "sensitive_topics"),
                        "section_title": "常见用户质疑",
                    }
                )

        if not structured_candidates:
            return []

        matched_texts: list[dict[str, Any]] = []
        for index, candidate in enumerate(structured_candidates):
            candidate_tags = set(candidate.get("tags", ()))
            if target_tags and not candidate_tags.intersection(target_tags):
                continue
            if "competitors" in target_tags and "competitors" not in candidate_tags:
                continue
            if not self._query_contains_any(normalized_query, tuple(candidate["keywords"])):
                continue
            content = str(candidate["text"] or "").strip()
            if not content:
                continue
            matched_texts.append(
                {
                    "chunk_id": f"structured:{brand_code or brand_id}:{index}",
                    "content": content,
                    "score": float(candidate["score"]),
                    "brand_name": brand_name,
                    "category": brand_name,
                    "metadata": {
                        "brand_id": brand_id,
                        "brand_code": brand_code,
                        "brand_name": brand_name,
                        "kb_version": knowledge_revision,
                        "section_title": str(candidate.get("section_title") or "").strip() or None,
                        "source_url": None,
                        "content_hash": f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}",
                    },
                }
            )

        matched_texts.sort(key=lambda item: (float(item["score"]), len(str(item["content"]))), reverse=True)
        return matched_texts[: request.top_k]
