from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from knowledge_base.brand.knowledge_extraction import build_brand_knowledge_snapshot_from_markdown
from knowledge_base.brand_knowledge.ai import extract_brand_knowledge_from_markdown
from knowledge_base.brand_knowledge.application.attachment_confirm_callbacks import (
    CONFIRM_CALLBACK_TYPE,
    AttachmentDraftConfirmCallbackMixin,
)
from knowledge_base.brand_knowledge.application.attachment_draft_runtime import AttachmentDraftRuntimeMixin
from knowledge_base.brand_knowledge.application.attachment_flow_helpers import (
    AttachmentDraftFlowHelpersMixin,
)
from knowledge_base.brand_knowledge.application.attachment_flow_storage import (
    AttachmentDraftFlowStorageMixin,
)
from knowledge_base.brand_knowledge.application.attachment_flow_structured_parse import (
    AttachmentDraftStructuredParseMixin,
)
from knowledge_base.brand_knowledge.application.attachment_snapshot import AttachmentDraftSnapshotMixin
from knowledge_base.brand_knowledge.application.attachment_confirm_merge import (
    AttachmentDraftConfirmMergeMixin,
)
from knowledge_base.brand_knowledge.application.attachment_confirm_pipeline import (
    AttachmentDraftConfirmPipelineMixin,
)
from knowledge_base.brand_knowledge.application.attachment_preview_parse import (
    AttachmentDraftPreviewParseMixin,
)
from knowledge_base.brand_knowledge.application.attachment_review import (
    AttachmentDraftReviewMixin,
)
from knowledge_base.brand_knowledge.field_hints import hint_aliases_for_ids
from knowledge_base.ingest.application.remote_download import download_remote_content_to_path
from knowledge_base.shared.utils import (
    is_effective_empty_sequence,
    normalize_line_delimited_text_sequence,
    normalize_text_sequence,
    parse_jsonish_literal,
)
try:
    from knowledge_base.shared.utils import apply_oss_test_prefix
except ImportError:  # pragma: no cover - test stubs may not expose this helper
    def apply_oss_test_prefix(object_key: str) -> str:
        return object_key
logger = logging.getLogger(__name__)


def _sanitize_oss_segment(value: str | None, *, default: str) -> str:
    candidate = (value or "").strip().strip("/\\")
    candidate = candidate.replace("/", "_").replace("\\", "_")
    return candidate or default


@dataclass(frozen=True)
class AttachmentDraftDependencies:
    settings: Any
    parser: Any
    oss_client: Any
    brands: Any
    brand_products: Any
    brand_knowledge: Any
    update_knowledge: Any
    tianyancha_client: Any = None
    brand_full_knowledge: Any = None
    ingest_text_document: Any = None
    ingest_staged_file: Any = None
    build_next_brand_full_knowledge: Any = None
    enqueue_brand_full_knowledge_refresh_job: Any = None
    enqueue_attachment_confirm_pipeline_job: Any = None
    enqueue_attachment_confirm_job: Any = None
    runtime: Any = None
    spawn_background_task: Any = None
    upload_tasks: Any = None


class AttachmentDraftService(
    AttachmentDraftConfirmCallbackMixin,
    AttachmentDraftConfirmMergeMixin,
    AttachmentDraftConfirmPipelineMixin,
    AttachmentDraftFlowHelpersMixin,
    AttachmentDraftFlowStorageMixin,
    AttachmentDraftStructuredParseMixin,
    AttachmentDraftPreviewParseMixin,
    AttachmentDraftReviewMixin,
    AttachmentDraftRuntimeMixin,
    AttachmentDraftSnapshotMixin,
):
    PREVIEW_PARSE_MAX_CONCURRENCY = 3
    PREVIEW_PARSE_MAX_CONCURRENCY_CAP = 6
    ATTACHMENT_DRAFT_TTL_SECONDS = 24 * 60 * 60
    ATTACHMENT_PRODUCTS_KNOWLEDGE_TYPE = "attachment_products"
    ATTACHMENT_PRODUCTS_OTHER_INFO_TITLE = "附件解析新增产品"
    _DRAFT_ACTIVE_STATUSES = {"pending_review", "reviewed"}
    _ATTACHMENT_PRODUCT_FIELD_ALIASES = {
        "name": ("产品名称", "名称"),
        "product_alias": ("产品别名", "产品别名及曾用名"),
        "product_description": ("产品介绍", "产品描述", "产品说明"),
        "product_website": ("产品网站", "产品链接", "产品官网"),
        "product_images": ("产品图片", "产品图"),
        "price_info": ("价格信息", "价格"),
        "coverage_regions": ("产品覆盖区域", "覆盖区域"),
        "product_advantages": ("产品优势", "优势"),
        "target_scenarios": ("适用场景/人群", "适用场景", "目标人群"),
        "service_standard": ("产品服务标准", "服务标准"),
        "service_process": ("产品服务流程", "服务流程"),
        "cases_and_reputation": ("产品案例与口碑", "案例与口碑"),
        "certification_info": ("获奖与认证信息", "认证信息", "获奖认证"),
        "core_technology": ("核心技术/专利名称", "核心技术", "专利名称"),
        "other_info": ("其他信息",),
    }
    _OTHER_INFO_GENERIC_TITLE = "其他信息"
    _OTHER_INFO_TITLE_TRANSLATIONS = {
        "brand": "品牌",
        "brand_name": "品牌名称",
        "brandname": "品牌名称",
        "brand_alias": "品牌别名及曾用名",
        "brandalias": "品牌别名及曾用名",
        "brand_description": "品牌介绍",
        "branddescription": "品牌介绍",
        "brand_intro": "品牌介绍",
        "brandintro": "品牌介绍",
        "intro": "品牌介绍",
        "description": "说明",
        "file_name": "文件名称",
        "filename": "文件名称",
        "source_name": "文件名称",
        "sourcename": "文件名称",
        "source": "来源",
        "subcategory": "子分类 / 产品线",
        "sub_category": "子分类 / 产品线",
        "subcategory_product_line": "子分类 / 产品线",
        "product_line": "产品线",
        "productline": "产品线",
        "industry": "所属行业",
        "industry_id": "所属行业",
        "industryid": "所属行业",
        "website": "品牌官网",
        "official_website": "品牌官网",
        "officialwebsite": "品牌官网",
        "email": "邮箱",
        "phone": "联系电话",
        "hotline": "客服热线",
        "customer_service_hotline": "客服热线",
        "customerservicehotline": "客服热线",
        "official_wechat": "官方微信公众号",
        "officialwechat": "官方微信公众号",
        "company_name": "公司名称",
        "companyname": "公司名称",
        "subject_info": "品牌主体名称",
        "subjectinfo": "品牌主体名称",
        "founded_at": "成立时间",
        "foundedat": "成立时间",
        "established_time": "成立时间",
        "establishedtime": "成立时间",
        "address": "公司地址",
        "company_address": "公司地址",
        "companyaddress": "公司地址",
        "mission": "品牌使命",
        "vision": "品牌愿景",
        "values": "企业价值观",
        "other_info": "其他信息",
        "otherinfo": "其他信息",
    }
    _OTHER_INFO_CONTENT_FIELD_LABELS = {
        "usage_method": "食用/使用方法",
        "usagemethod": "食用/使用方法",
        "eating_method": "食用方法",
        "eatingmethod": "食用方法",
        "serving_method": "食用方法",
        "servingmethod": "食用方法",
        "ingredient": "成分/配料",
        "ingredients": "成分/配料",
        "ingredient_highlights": "成分亮点",
        "ingredienthighlights": "成分亮点",
        "formula": "配方",
        "nutrition": "营养信息",
        "nutrition_info": "营养信息",
        "nutritioninfo": "营养信息",
        "suitable_people": "适用人群",
        "suitablepeople": "适用人群",
        "target_people": "目标人群",
        "targetpeople": "目标人群",
        "contraindications": "禁忌说明",
        "warning": "注意事项",
        "warnings": "注意事项",
        "precautions": "注意事项",
        "storage_method": "储存方式",
        "storagemethod": "储存方式",
        "storage": "储存方式",
        "shelf_life": "保质期",
        "shelflife": "保质期",
        "specification": "规格",
        "specifications": "规格",
        "package_specification": "包装规格",
        "packagespecification": "包装规格",
        "packaging": "包装信息",
        "origin": "产地",
        "place_of_origin": "产地",
        "placeoforigin": "产地",
        "manufacturer": "生产厂家",
        "producer": "生产厂家",
        "production_license": "生产许可证",
        "productionlicense": "生产许可证",
        "standard": "执行标准",
        "product_standard": "执行标准",
        "productstandard": "执行标准",
        "quality_standard": "质量标准",
        "qualitystandard": "质量标准",
        "certification": "认证信息",
        "certifications": "认证信息",
        "research_report": "研究报告",
        "researchreport": "研究报告",
        "report": "报告信息",
        "awards": "获奖信息",
        "honors": "荣誉信息",
        "selling_points": "卖点",
        "sellingpoints": "卖点",
        "highlights": "亮点",
        "features": "特点",
        "benefits": "功效/利益点",
        "function": "功能",
        "functions": "功能",
        "efficacy": "功效",
        "recommendation": "推荐说明",
        "recommendations": "推荐说明",
        "notes": "备注",
        "remark": "备注",
        "remarks": "备注",
        "source": "来源",
        "source_section": "来源章节",
        "sourcesection": "来源章节",
    }
    _CHINESE_NUMERALS = ("一", "二", "三", "四", "五", "六", "七", "八", "九", "十")
    _GEO_EMPTY_CELL_VALUES = {"", "-", "/", "无", "暂无", "待补充", "待确认", "n/a", "na", "null"}
    _MEDIA_PLATFORM_KEYWORDS = (
        "微信公众号",
        "视频号",
        "抖音",
        "小红书",
        "微博",
        "搜狐号",
        "腾讯号",
        "头条号",
        "百家号",
        "网易号",
        "B站",
        "快手",
    )

    def _knowledge_snapshot_service_proxy(self) -> Any:
        return SimpleNamespace(
            _brands=self._deps.brands,
            _brand_products=self._deps.brand_products,
            _brand_knowledge=self._deps.brand_knowledge,
            _settings=self._deps.settings,
            _tianyancha_client=self._deps.tianyancha_client,
        )
    _MEDIA_PLATFORM_DOMAINS = (
        ("mp.weixin.qq.com", "微信公众号"),
        ("weixin.qq.com", "微信公众号"),
        ("channels.weixin.qq.com", "视频号"),
        ("weixinvideo.com", "视频号"),
        ("douyin.com", "抖音"),
        ("xiaohongshu.com", "小红书"),
        ("weibo.com", "微博"),
        ("sohu.com", "搜狐号"),
        ("toutiao.com", "头条号"),
        ("baidu.com", "百家号"),
        ("163.com", "网易号"),
        ("bilibili.com", "B站"),
        ("kuaishou.com", "快手"),
    )
    _GEO_PLACEHOLDER_FIELD_KEYWORDS = (
        "字段名称",
        "具体内容",
        "填写具体内容",
        "客户填写",
        "建议上传",
        "附件/链接",
    )
    _GENERIC_HONOR_SECTION_TITLES = {
        "权威背书资料",
        "权威背书资料原件/链接/可核验出处",
        "公司所获荣誉",
        "荣誉列表",
    }
    _OTHER_INFO_COMPETITOR_ADVANTAGE_TITLES = {
        "核心产品优势",
    }
    _OTHER_INFO_COMPETITOR_DIFF_TITLES = {
        "差异化“护城河”",
        "差异化\"护城河\"",
        "差异化护城河",
    }
    _OTHER_INFO_RESOURCE_TITLE_KEYWORDS = (
        "宣传物料",
        "品牌资料",
        "素材",
        "资料包",
        "下载",
    )
    _OTHER_INFO_RESOURCE_CONTENT_KEYWORDS = (
        "提取码",
        "百度网盘",
        "pan.baidu.com",
        "夸克",
        "quark",
        "aliyundrive",
        "阿里云盘",
        "123pan.com",
        "123684.com",
        "123云盘",
        "蓝奏云",
        "lanzou",
    )
    _COMPANY_ADDRESS_HINT_KEYWORDS = hint_aliases_for_ids("company_address")
    _COMPANY_RECENT_NEWS_HINT_KEYWORDS = hint_aliases_for_ids("company_recent_news")
    _COMPANY_DEVELOPMENT_HISTORY_HINT_KEYWORDS = hint_aliases_for_ids("company_development_history")
    _COMPETITOR_NAME_HINT_KEYWORDS = hint_aliases_for_ids("competitor_name")
    _COMPETITOR_COMPARISON_HINT_KEYWORDS = hint_aliases_for_ids("competitor_comparison_dimensions")
    _MEDIA_ACCOUNT_HINT_KEYWORDS = hint_aliases_for_ids("media_account")
    _PRODUCT_WEBSITE_HINT_KEYWORDS = hint_aliases_for_ids("product_website")
    _PRODUCT_PRICE_HINT_KEYWORDS = hint_aliases_for_ids("product_price")
    _PRODUCT_ADVANTAGES_HINT_KEYWORDS = hint_aliases_for_ids("product_advantages")
    _PRODUCT_TARGET_SCENARIOS_HINT_KEYWORDS = hint_aliases_for_ids("product_target_scenarios")
    _PRODUCT_SERVICE_STANDARD_HINT_KEYWORDS = hint_aliases_for_ids("product_service_standard")
    _PRODUCT_SERVICE_PROCESS_HINT_KEYWORDS = hint_aliases_for_ids("product_service_process")
    _PRODUCT_CERTIFICATION_HINT_KEYWORDS = hint_aliases_for_ids("product_certification")
    _PRODUCT_CORE_TECH_HINT_KEYWORDS = hint_aliases_for_ids("product_core_technology")
    _SENSITIVE_FORBIDDEN_HINT_KEYWORDS = hint_aliases_for_ids("sensitive_forbidden_terms")
    _SENSITIVE_CONTROVERSIAL_HINT_KEYWORDS = hint_aliases_for_ids("sensitive_controversial")
    _SENSITIVE_NEGATIVE_CLARIFICATION_HINT_KEYWORDS = hint_aliases_for_ids("sensitive_negative_clarification")
    _EXACT_DATE_PATTERNS = (
        re.compile(r"(?<!\d)((?:19|20)\d{2})年([01]?\d)月([0-3]?\d)日"),
        re.compile(r"(?<!\d)((?:19|20)\d{2})[-/.]([01]?\d)[-/.]([0-3]?\d)(?!\d)"),
    )
    _EXACT_MONTH_PATTERN = re.compile(r"(?<!\d)((?:19|20)\d{2})年([01]?\d)月")
    _CONFIRM_CALLBACK_RETRY_DELAYS_SECONDS = (6, 12, 18)
    _REVIEW_WARNING_MESSAGES = [
        "请务必核对修改的信息，确保内容与品牌官方一致，避免错误或过时信息。",
        "系统仅提供信息聚合服务，最终内容以您确认的为准。",
    ]
    _DIFF_PATH_LABELS = {
        "basic_info": "基础信息",
        "extra_info": "基础扩展信息",
        "company_profile": "公司档案",
        "subject_info": "品牌主体名称",
        "business_license_url": "主体营业执照图片",
        "company_addresses": "公司地址",
        "founded_at": "成立时间",
        "development_philosophy": "发展理念",
        "company_values": "企业价值观",
        "products": "产品",
        "base_info": "产品基础信息",
        "knowledge": "产品知识",
        "management_team": "管理团队",
        "members": "团队成员",
        "competitors": "竞品信息",
        "honors": "荣誉列表",
        "cases": "案例列表",
        "authority_honors": "权威荣誉",
        "customers_cases": "客户案例",
        "sensitive_topics": "敏感话题",
        "attachments": "附件资料",
        "files": "附件列表",
        "other_info": "其他信息",
        "official_malls": "官方商城",
        "official_media_matrix": "官方媒体与矩阵",
        "brand_code": "品牌编码",
        "brand_name": "品牌名称",
        "brand_alias": "品牌别名及曾用名",
        "brand_logo": "品牌 Logo",
        "website": "品牌官网",
        "intro": "品牌介绍",
        "email": "邮箱",
        "customer_service_hotline": "客服热线",
        "official_wechat_account": "官方微信公众号",
        "official_wechat": "官方微信公众号",
        "brand_enterprise_entity": "品牌主体名称",
        "business_license_image_path": "主体营业执照图片",
        "industry_id": "所属行业",
        "english_name": "品牌英文名",
        "brand_english_name": "品牌英文名",
        "positioning": "品牌定位",
        "brand_positioning": "品牌定位",
        "advantages": "品牌优势",
        "brand_advantage": "品牌优势",
        "mission": "品牌使命",
        "brand_mission": "品牌使命",
        "vision": "品牌愿景",
        "brand_vision": "品牌愿景",
        "target_regions": "目标区域",
        "target_region": "目标区域",
        "stock_info": "股票/上市信息",
        "brand_subject_name": "品牌主体名称",
        "company_address": "公司地址",
        "company_intro": "公司简介",
        "established_time": "成立时间",
        "store_distribution": "门店分布",
        "recent_news": "近期动态",
        "development_concept": "发展理念",
        "corporate_values": "企业价值观",
        "company_mission": "公司使命",
        "development_history": "发展历程",
        "name": "名称",
        "title": "标题",
        "content": "内容",
        "description": "说明",
        "report_link": "报告链接",
        "year": "时间",
        "qualification_proof": "资质证明",
        "issuing_authority": "授予机构",
        "profile": "简介",
        "bio": "成员介绍",
        "introduction_website": "介绍链接",
        "intro_urls": "介绍网站",
        "product_alias": "产品别名",
        "target_label": "产品标签",
        "product_description": "产品介绍",
        "product_website": "产品网站",
        "product_link": "产品网站",
        "product_images": "产品图片",
        "price_info": "价格信息",
        "coverage_regions": "覆盖区域",
        "product_advantages": "产品优势",
        "scenarios": "适用场景/人群",
        "target_scenarios": "适用场景/人群",
        "service_standards": "产品服务标准",
        "service_standard": "服务标准",
        "service_processes": "产品服务流程",
        "service_process": "服务流程",
        "cases_reputation": "产品案例与口碑",
        "cases_and_reputation": "案例与口碑",
        "awards_certifications": "获奖与认证信息",
        "certification_info": "认证信息",
        "technologies_patents": "核心技术/专利名称",
        "core_technology": "核心技术/专利名称",
        "comparison_dimensions": "对比维度",
        "differentiated_positioning": "差异化定位",
        "strengths": "优势",
        "competitors_alias": "竞品别名",
        "competitors_description": "竞品描述",
        "competitive_advantages": "竞品优势",
        "case_name": "案例名称",
        "title": "标题",
        "descriptions": "荣誉介绍",
        "report_links": "报道链接",
        "awarded_at": "获取时间",
        "proof_files": "资质证明",
        "cooperation_time": "合作时间",
        "customer_name": "客户名称",
        "cooperation_products": "合作产品",
        "cooperation_product": "合作产品",
        "highlights": "合作亮点",
        "cooperation_highlight": "合作亮点",
        "customer_reviews": "客户评价",
        "customer_feedback": "客户反馈",
        "case_link": "案例链接",
        "related_products": "关联产品",
        "store_name": "店铺名称",
        "platform": "平台",
        "homepage_urls": "主页链接",
        "store_ids": "店铺 ID",
        "main_categories": "主营类目",
        "account_name": "账号名称",
        "media_platform": "媒体平台",
        "account_id": "账号 ID",
        "is_official": "是否官方",
        "fans_count": "粉丝量",
        "content_focus": "内容方向",
        "sensitive_contents": "敏感内容",
        "controversial_events": "争议事件",
        "forbidden_words": "禁用词",
        "negative_clarifications": "负面澄清",
    }
    _DIFF_LABEL_CONTAINER_SEGMENTS = {
        "extra_info",
        "base_info",
        "knowledge",
        "price_info",
        "members",
        "competitors",
        "honors",
        "cases",
        "files",
    }
    _DIFF_FIELD_PATH_ALIASES = {
        "basic_info.english_name": "basic_info.extra_info.brand_english_name",
        "basic_info.official_wechat_account": "basic_info.extra_info.official_wechat",
        "basic_info.positioning": "basic_info.extra_info.brand_positioning",
        "basic_info.advantages": "basic_info.extra_info.brand_advantage",
        "basic_info.mission": "basic_info.extra_info.brand_mission",
        "basic_info.vision": "basic_info.extra_info.brand_vision",
        "basic_info.target_regions": "basic_info.extra_info.target_region",
        "basic_info.other_info": "basic_info.extra_info.other_info",
        "company_profile.brand_subject_name": "company_profile.subject_info",
        "company_profile.business_license_image_path": "company_profile.business_license_url",
        "company_profile.company_address": "company_profile.company_addresses",
        "company_profile.established_time": "company_profile.founded_at",
        "company_profile.development_concept": "company_profile.development_philosophy",
        "company_profile.corporate_values": "company_profile.company_values",
    }
    _PRODUCT_DIFF_FIELD_PATH_ALIASES = {
        "name": "base_info.name",
        "product_alias": "base_info.target_label",
        "product_description": "base_info.product_description",
        "product_website": "base_info.product_link",
        "product_images": "base_info.product_images",
        "coverage_regions": "base_info.coverage_regions",
        "price_info": "knowledge.price_info.summary",
        "product_advantages": "knowledge.advantages",
        "target_scenarios": "knowledge.scenarios",
        "service_standard": "knowledge.service_standards",
        "service_process": "knowledge.service_processes",
        "cases_and_reputation": "knowledge.cases_reputation",
        "certification_info": "knowledge.awards_certifications",
        "core_technology": "knowledge.technologies_patents",
        "other_info": "knowledge.other_info",
    }
    _MANAGEMENT_TEAM_DIFF_FIELD_PATH_ALIASES = {
        "name": "name",
        "title": "title",
        "profile": "bio",
        "introduction_website": "intro_urls",
        "other_info": "other_info",
    }
    _COMPETITOR_DIFF_FIELD_PATH_ALIASES = {
        "name": "name",
        "aliases": "aliases",
        "introduction": "introduction",
        "official_websites": "official_websites",
        "logo_urls": "logo_urls",
        "strengths": "strengths",
        "differentiated_positioning": "differentiated_positioning",
        "comparison_dimensions": "comparison_dimensions",
        "other_info": "other_info",
    }
    _AUTHORITY_HONOR_DIFF_FIELD_PATH_ALIASES = {
        "title": "title",
        "year": "awarded_at",
        "description": "descriptions",
        "report_link": "report_links",
        "qualification_proof": "proof_files",
        "other_info": "other_info",
    }
    _CUSTOMER_CASE_DIFF_FIELD_PATH_ALIASES = {
        "case_name": "title",
        "cooperation_time": "cooperation_time",
        "customer_name": "customer_name",
        "cooperation_product": "cooperation_products",
        "cooperation_highlight": "highlights",
        "customer_feedback": "customer_reviews",
        "other_info": "other_info",
    }
    _PREVIEW_FIELD_LABELS = {
        "basic_info": "品牌基础信息",
        "basic_info.industry_id": "所属行业",
        "basic_info.brand_name": "品牌名称",
        "basic_info.brand_alias": "品牌别名及曾用名",
        "basic_info.brand_logo": "品牌 logo",
        "basic_info.website": "品牌官网",
        "basic_info.intro": "品牌介绍",
        "basic_info.email": "邮箱",
        "basic_info.customer_service_hotline": "客服热线",
        "basic_info.extra_info": "基础扩展信息",
        "basic_info.extra_info.brand_english_name": "品牌英文名",
        "basic_info.extra_info.official_wechat": "官方微信公众号",
        "basic_info.extra_info.brand_positioning": "品牌定位",
        "basic_info.extra_info.brand_advantage": "品牌优势",
        "basic_info.extra_info.brand_mission": "品牌使命",
        "basic_info.extra_info.brand_vision": "品牌愿景",
        "basic_info.extra_info.target_region": "目标区域",
        "basic_info.extra_info.other_info": "其他信息",
        "company_profile": "公司信息",
        "company_profile.subject_info": "品牌主体名称",
        "company_profile.business_license_url": "主体营业执照图片",
        "company_profile.stock_info": "股票/上市信息",
        "company_profile.company_addresses": "公司地址",
        "company_profile.company_intro": "公司简介",
        "company_profile.founded_at": "成立时间",
        "company_profile.store_distribution": "门店分布",
        "company_profile.recent_news": "近期动态",
        "company_profile.development_philosophy": "发展理念",
        "company_profile.company_values": "企业价值观",
        "company_profile.company_mission": "公司使命",
        "company_profile.development_history": "发展历程",
        "company_profile.other_info": "其他信息",
        "products": "产品信息",
        "products[].base_info": "产品基础信息",
        "products[].base_info.name": "产品名称",
        "products[].base_info.target_label": "产品标签",
        "products[].base_info.product_description": "产品介绍",
        "products[].base_info.product_link": "产品网站",
        "products[].base_info.product_images": "产品图片",
        "products[].base_info.coverage_regions": "产品覆盖区域",
        "products[].knowledge": "产品知识",
        "products[].knowledge.price_info": "价格信息",
        "products[].knowledge.price_info.summary": "价格信息",
        "products[].knowledge.advantages": "产品优势",
        "products[].knowledge.scenarios": "适用场景/人群",
        "products[].knowledge.service_standards": "产品服务标准",
        "products[].knowledge.service_processes": "产品服务流程",
        "products[].knowledge.cases_reputation": "产品案例与口碑",
        "products[].knowledge.awards_certifications": "获奖与认证信息",
        "products[].knowledge.technologies_patents": "核心技术/专利名称",
        "products[].knowledge.other_info": "其他信息",
        "management_team": "管理团队",
        "management_team.members": "团队成员",
        "management_team.members[].name": "成员名称",
        "management_team.members[].title": "成员职务",
        "management_team.members[].bio": "成员介绍",
        "management_team.members[].intro_urls": "介绍网站",
        "management_team.members[].other_info": "其他信息",
        "competitors": "竞品信息",
        "competitors.competitors": "竞品列表",
        "competitors.competitors[].name": "竞品名称",
        "competitors.competitors[].aliases": "竞品别名",
        "competitors.competitors[].introduction": "竞品介绍",
        "competitors.competitors[].official_websites": "官网链接",
        "competitors.competitors[].logo_urls": "竞品 logo",
        "competitors.competitors[].strengths": "竞争优势",
        "competitors.competitors[].differentiated_positioning": "差异化定位",
        "competitors.competitors[].comparison_dimensions": "建议对比维度",
        "competitors.competitors[].other_info": "其他信息",
        "authority_honors": "权威背书与荣誉",
        "authority_honors.honors": "荣誉列表",
        "authority_honors.honors[].title": "荣誉名称",
        "authority_honors.honors[].descriptions": "荣誉介绍",
        "authority_honors.honors[].report_links": "报道链接",
        "authority_honors.honors[].awarded_at": "获取时间",
        "authority_honors.honors[].proof_files": "资质证明",
        "authority_honors.honors[].other_info": "其他信息",
        "customers_cases": "合作客户与案例",
        "customers_cases.cases": "案例列表",
        "customers_cases.cases[].title": "案例名称",
        "customers_cases.cases[].cooperation_time": "合作时间",
        "customers_cases.cases[].customer_name": "客户名称",
        "customers_cases.cases[].cooperation_products": "合作产品",
        "customers_cases.cases[].highlights": "合作亮点",
        "customers_cases.cases[].customer_reviews": "客户评价",
        "customers_cases.cases[].other_info": "其他信息",
        "sensitive_topics": "敏感话题",
        "sensitive_topics.sensitive_contents": "敏感内容",
        "sensitive_topics.controversial_events": "争议事件",
        "sensitive_topics.forbidden_words": "禁用语",
        "sensitive_topics.negative_clarifications": "负面澄清",
        "sensitive_topics.other_info": "其他信息",
        "attachments": "附件资料",
        "attachments.files": "附件列表",
        "attachments.files[].name": "附件名称",
        "attachments.files[].url": "附件链接",
        "attachments.files[].type": "附件类型",
        "attachments.files[].description": "附件说明",
        "official_malls": "官方商城",
        "official_malls[].store_name": "店铺名称",
        "official_malls[].platform": "开店平台",
        "official_malls[].homepage_urls": "店铺主页链接",
        "official_malls[].store_ids": "店铺 ID",
        "official_malls[].main_categories": "主营品类",
        "official_malls[].advantages": "店铺优势",
        "official_malls[].related_products": "关联产品",
        "official_malls[].other_info": "其他信息",
        "official_media_matrix": "官方媒体与矩阵",
        "official_media_matrix[].media_platform": "媒体平台",
        "official_media_matrix[].account_name": "账号名称",
        "official_media_matrix[].account_id": "账号 ID",
        "official_media_matrix[].is_official": "是否品牌官方账号",
        "official_media_matrix[].homepage_urls": "账号主页链接",
        "official_media_matrix[].fans_count": "粉丝量",
        "official_media_matrix[].content_focus": "内容方向",
        "official_media_matrix[].related_products": "关联产品",
        "official_media_matrix[].other_info": "其他信息",
        "other_info[].content[].name": "产品名称",
        "other_info[].content[].product_alias": "产品别名",
        "other_info[].content[].product_description": "产品介绍",
        "other_info[].content[].product_website": "产品网站",
        "other_info[].content[].product_images": "产品图片",
        "other_info[].content[].price_info": "价格信息",
        "other_info[].content[].coverage_regions": "产品覆盖区域",
        "other_info[].content[].product_advantages": "产品优势",
        "other_info[].content[].target_scenarios": "适用场景/人群",
        "other_info[].content[].service_standard": "产品服务标准",
        "other_info[].content[].service_process": "产品服务流程",
        "other_info[].content[].cases_and_reputation": "产品案例与口碑",
        "other_info[].content[].certification_info": "获奖与认证信息",
        "other_info[].content[].core_technology": "核心技术/专利名称",
        "other_info[].content[].other_info": "其他信息",
    }

    def __init__(self, dependencies: AttachmentDraftDependencies) -> None:
        self._deps = dependencies
