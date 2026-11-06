from __future__ import annotations

from typing import Final


FIELD_HINT_SPECS: Final[tuple[dict[str, object], ...]] = (
    {"id": "brand_name", "aliases": ("品牌标准名", "品牌名称"), "output": "basic_info.brand_name"},
    {"id": "brand_alias", "aliases": ("品牌别名", "品牌简称", "曾用名"), "output": "basic_info.brand_alias"},
    {"id": "brand_logo", "aliases": ("品牌 Logo", "品牌标识", "logo"), "output": "basic_info.brand_logo"},
    {"id": "brand_english_name", "aliases": ("品牌英文名", "英文名", "英文简称"), "output": "basic_info.english_name"},
    {"id": "brand_website", "aliases": ("官网地址", "官网", "官方网站", "品牌官网", "官网链接"), "output": "basic_info.website"},
    {"id": "brand_hotline", "aliases": ("客服热线", "客服电话", "服务热线", "联系电话"), "output": "basic_info.customer_service_hotline"},
    {"id": "brand_official_wechat", "aliases": ("官方微信公众号", "公众号", "官方微信"), "output": "basic_info.official_wechat_account"},
    {"id": "brand_intro", "aliases": ("品牌介绍", "品牌简介", "品牌概述"), "output": "basic_info.intro"},
    {"id": "brand_email", "aliases": ("邮箱", "电子邮箱", "联系邮箱"), "output": "basic_info.email"},
    {"id": "brand_entity", "aliases": ("品牌主体", "企业主体", "品牌所属公司"), "output": "basic_info.brand_enterprise_entity"},
    {"id": "brand_license", "aliases": ("品牌营业执照", "主体营业执照图片"), "output": "basic_info.business_license_image_path"},
    {"id": "brand_positioning", "aliases": ("品牌定位", "定位"), "output": "basic_info.positioning"},
    {"id": "brand_advantages", "aliases": ("核心价值主张", "品牌优势", "品牌卖点", "竞争优势"), "output": "basic_info.advantages"},
    {"id": "brand_mission", "aliases": ("品牌使命", "使命"), "output": "basic_info.mission"},
    {"id": "brand_vision", "aliases": ("品牌愿景", "愿景"), "output": "basic_info.vision"},
    {"id": "brand_target_regions", "aliases": ("目标区域", "覆盖区域", "服务区域", "全国/区域范围"), "output": "basic_info.target_regions"},
    {"id": "company_subject", "aliases": ("公司主体", "公司主体全称", "企业主体", "品牌主体名称"), "output": "company_profile.brand_subject_name"},
    {"id": "company_license", "aliases": ("营业执照", "营业执照图片", "主体营业执照"), "output": "company_profile.business_license_image_path"},
    {"id": "company_stock_info", "aliases": ("股票/上市信息", "上市信息", "股票代码", "证券代码", "上市地点", "上市日期"), "output": "company_profile.stock_info"},
    {"id": "company_address", "aliases": ("公司地址", "注册地址", "办公地址", "总部地址"), "output": "company_profile.company_address"},
    {"id": "company_intro", "aliases": ("公司简介", "企业简介", "主体简介"), "output": "company_profile.company_intro"},
    {"id": "company_established_time", "aliases": ("成立时间", "创立时间", "创办时间"), "output": "company_profile.established_time"},
    {"id": "company_store_distribution", "aliases": ("门店分布", "门店数量", "网点分布", "渠道分布"), "output": "company_profile.store_distribution"},
    {"id": "company_recent_news", "aliases": ("近期动态", "新闻动态", "品牌新闻", "公司新闻", "近期新闻", "公司近期新闻"), "output": "company_profile.recent_news"},
    {"id": "company_development_concept", "aliases": ("发展理念", "经营理念"), "output": "company_profile.development_concept"},
    {"id": "company_corporate_values", "aliases": ("企业价值观", "公司价值观", "核心价值观"), "output": "company_profile.corporate_values"},
    {"id": "company_mission", "aliases": ("公司使命", "企业使命"), "output": "company_profile.company_mission"},
    {"id": "company_development_history", "aliases": ("发展历程", "品牌历程", "里程碑", "大事记", "发展里程碑", "品牌故事"), "output": "company_profile.development_history"},
    {"id": "management_team_core", "aliases": ("核心高管", "创始人", "董事长", "副董事长", "总裁", "CEO", "管理团队"), "output": "management_team[].member_name / management_team[].position"},
    {"id": "management_team_profile", "aliases": ("成员简介", "个人简介", "高管简介", "履历"), "output": "management_team[].profile"},
    {"id": "management_team_intro_link", "aliases": ("团队介绍链接", "人物介绍链接", "个人主页"), "output": "management_team[].introduction_website"},
    {"id": "product_name", "aliases": ("产品名称", "产品标准名", "商品名称", "SKU 名称", "服务名称"), "output": "products[].name"},
    {"id": "product_alias", "aliases": ("产品别名", "产品简称", "产品标签", "系列名", "款式名"), "output": "products[].product_alias"},
    {"id": "product_description", "aliases": ("产品介绍", "产品简介", "产品描述", "商品说明"), "output": "products[].product_description"},
    {"id": "product_website", "aliases": ("产品网站", "产品链接", "商品链接", "产品官网", "购买链接"), "output": "products[].product_website"},
    {"id": "product_images", "aliases": ("产品图片", "商品图片", "产品图", "图片链接"), "output": "products[].product_images"},
    {"id": "product_price", "aliases": ("价格", "规格", "包装规格", "售价", "价格体系", "套餐价", "月套餐", "年套餐"), "output": "products[].price_info"},
    {"id": "product_coverage_regions", "aliases": ("产品覆盖区域", "销售区域", "适售区域"), "output": "products[].coverage_regions"},
    {"id": "product_advantages", "aliases": ("卖点", "产品优势", "产品亮点", "产品特点", "核心优势"), "output": "products[].product_advantages"},
    {"id": "product_target_scenarios", "aliases": ("适用人群", "适用场景", "目标人群", "使用场景"), "output": "products[].target_scenarios"},
    {"id": "product_service_standard", "aliases": ("服务标准", "交付标准", "配送标准", "包装标准"), "output": "products[].service_standard"},
    {"id": "product_service_process", "aliases": ("服务流程", "服务 SOP", "流程节点", "使用流程", "购买流程"), "output": "products[].service_process"},
    {"id": "product_cases_and_reputation", "aliases": ("案例口碑", "用户口碑", "客户评价", "产品案例", "用户反馈"), "output": "products[].cases_and_reputation"},
    {"id": "product_certification", "aliases": ("产品认证", "获奖认证", "认证信息", "检测报告"), "output": "products[].certification_info"},
    {"id": "product_core_technology", "aliases": ("核心技术", "专利", "工艺", "技术专利", "配方技术"), "output": "products[].core_technology"},
    {"id": "competitor_name", "aliases": ("竞品", "竞争对手", "竞品名称", "对标品牌"), "output": "competitors[].name"},
    {"id": "competitor_alias", "aliases": ("竞品别名", "竞品简称"), "output": "competitors[].competitors_alias"},
    {"id": "competitor_description", "aliases": ("竞品介绍", "竞品描述"), "output": "competitors[].competitors_description"},
    {"id": "competitor_website", "aliases": ("竞品官网", "竞品链接"), "output": "competitors[].website"},
    {"id": "competitor_logo", "aliases": ("竞品 Logo", "竞品标识"), "output": "competitors[].competitors_logo"},
    {"id": "competitor_advantages", "aliases": ("竞品优势", "竞争优势", "对方优势"), "output": "competitors[].competitive_advantages"},
    {"id": "competitor_differentiated_positioning", "aliases": ("差异化定位", "差异点", "品牌差异"), "output": "competitors[].differentiated_positioning"},
    {"id": "competitor_comparison_dimensions", "aliases": ("对比维度", "建议对比维度", "对比口径", "允许对比的维度"), "output": "competitors[].comparison_dimensions"},
    {"id": "honor_core", "aliases": ("荣誉", "奖项", "认证", "权威背书", "行业标准", "专利数量", "榜单排名", "第一/首家/开创者", "国家级", "行业首家", "通过认证"), "output": "authority_honors[].title / authority_honors[].description"},
    {"id": "honor_year", "aliases": ("获奖时间", "授予时间", "认证时间", "上榜时间", "获取时间"), "output": "authority_honors[].year"},
    {"id": "honor_report_link", "aliases": ("报告链接", "报道链接", "可核验出处", "来源链接"), "output": "authority_honors[].report_link"},
    {"id": "honor_qualification_proof", "aliases": ("资质证明", "证书", "证明文件", "证书编号"), "output": "authority_honors[].qualification_proof"},
    {"id": "honor_issuing_authority", "aliases": ("授予机构", "颁发机构", "认证机构", "调研机构", "数据来源"), "output": "authority_honors[].issuing_authority"},
    {"id": "customer_case_name", "aliases": ("客户案例", "合作案例", "案例名称"), "output": "customers_cases[].case_name"},
    {"id": "customer_case_time", "aliases": ("合作时间", "服务时间"), "output": "customers_cases[].cooperation_time"},
    {"id": "customer_case_customer_name", "aliases": ("客户名称", "合作客户"), "output": "customers_cases[].customer_name"},
    {"id": "customer_case_product", "aliases": ("合作产品", "服务产品"), "output": "customers_cases[].cooperation_product"},
    {"id": "customer_case_highlight", "aliases": ("合作亮点", "项目亮点"), "output": "customers_cases[].cooperation_highlight"},
    {"id": "customer_case_feedback", "aliases": ("客户反馈", "客户评价", "客户证言"), "output": "customers_cases[].customer_feedback"},
    {"id": "customer_case_link", "aliases": ("案例链接", "案例报道"), "output": "customers_cases[].case_link"},
    {"id": "customer_case_related_products", "aliases": ("关联产品", "相关产品"), "output": "customers_cases[].related_products"},
    {"id": "mall_store_name", "aliases": ("官网商城", "天猫旗舰店", "京东旗舰店", "抖音商城", "小程序商城", "微信小店", "店铺名称", "购买店铺", "官方商城"), "output": "official_malls[].store_name"},
    {"id": "mall_platform", "aliases": ("平台", "商城平台", "电商平台", "开店平台"), "output": "official_malls[].platform"},
    {"id": "mall_homepage_urls", "aliases": ("店铺链接", "商城链接", "主页链接", "购买入口"), "output": "official_malls[].homepage_urls"},
    {"id": "mall_store_ids", "aliases": ("店铺 ID", "店铺编号", "店铺号"), "output": "official_malls[].store_ids"},
    {"id": "mall_main_categories", "aliases": ("主营类目", "主营品类"), "output": "official_malls[].main_categories"},
    {"id": "mall_advantages", "aliases": ("店铺优势", "商城优势", "渠道优势"), "output": "official_malls[].advantages"},
    {"id": "mall_related_products", "aliases": ("商城关联产品", "店铺相关产品"), "output": "official_malls[].related_products"},
    {"id": "media_account", "aliases": ("微信公众号", "微信视频号", "视频号", "抖音号", "小红书", "微博", "搜狐号", "头条号", "百家号", "网易号", "B站", "快手", "官方账号", "媒体矩阵", "内容平台账号"), "output": "official_media_matrix[].media_platform / official_media_matrix[].account_name"},
    {"id": "media_account_id", "aliases": ("账号 ID", "账号编号", "账号", "平台号"), "output": "official_media_matrix[].account_id"},
    {"id": "media_is_official", "aliases": ("是否官方", "官方认证", "蓝 V", "认证主体"), "output": "official_media_matrix[].is_official"},
    {"id": "media_homepage_urls", "aliases": ("账号主页", "主页链接", "媒体主页链接"), "output": "official_media_matrix[].homepage_urls"},
    {"id": "media_fans_count", "aliases": ("粉丝数", "关注数"), "output": "official_media_matrix[].fans_count"},
    {"id": "media_content_focus", "aliases": ("内容方向", "内容重点", "发布内容", "账号定位"), "output": "official_media_matrix[].content_focus"},
    {"id": "media_related_products", "aliases": ("媒体关联产品", "账号相关产品"), "output": "official_media_matrix[].related_products"},
    {"id": "sensitive_forbidden_terms", "aliases": ("敏感词", "禁用词", "极限词", "禁止表述"), "output": "sensitive_topics[].forbidden_terms"},
    {"id": "sensitive_controversial", "aliases": ("争议事件", "风险话题", "危机事件", "负面事件", "禁忌元素", "敏感内容"), "output": "sensitive_topics[].topic / sensitive_topics[].description"},
    {"id": "sensitive_negative_clarification", "aliases": ("负面澄清", "统一口径", "历史负面澄清", "回应口径"), "output": "sensitive_topics[].history_negative_clarification"},
    {"id": "global_other_info", "aliases": ("服务 IP", "特色服务", "会员权益", "退费政策", "退款政策", "售后政策", "术语表", "词汇表", "视觉元素", "代言人", "安全边界", "无法明确归入以上标准字段的信息"), "output": "other_info"},
)


def build_hint_lines() -> list[str]:
    return [
        f"{'、'.join(str(alias) for alias in spec['aliases'])} -> {spec['output']}"
        for spec in FIELD_HINT_SPECS
    ]


def hint_aliases_for_ids(*hint_ids: str) -> tuple[str, ...]:
    selected = {str(hint_id).strip() for hint_id in hint_ids if str(hint_id).strip()}
    aliases: list[str] = []
    seen: set[str] = set()
    for spec in FIELD_HINT_SPECS:
        if str(spec["id"]) not in selected:
            continue
        for alias in spec["aliases"]:
            normalized = str(alias).strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            aliases.append(normalized)
    return tuple(aliases)
