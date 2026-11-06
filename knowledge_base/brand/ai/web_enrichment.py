from __future__ import annotations

import asyncio
import json
import re
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

from knowledge_base.infrastructure.llm import call_text_llm_json, require_settings
from knowledge_base.infrastructure.settings import Settings


def _normalize_url(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _extract_links(html: str, *, base_url: str) -> list[str]:
    links: list[str] = []
    for match in re.finditer(r'href=["\']([^"\']+)["\']', html or "", re.IGNORECASE):
        href = str(match.group(1) or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        absolute_url = urljoin(base_url, href)
        if absolute_url.startswith(("http://", "https://")) and absolute_url not in links:
            links.append(absolute_url)
    return links


def _normalize_page_text(html: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", html or "", flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _fetch_source_pages(
    *,
    brand_name: str,
    company_name: str | None,
    official_website: str | None,
    requests_module: Any,
) -> list[dict[str, str]]:
    normalized_brand_name = str(brand_name or "").strip()
    normalized_company_name = str(company_name or "").strip()
    normalized_website = _normalize_url(official_website)
    source_pages: list[dict[str, str]] = []
    visited_urls: set[str] = set()

    def _add_page(url: str, text: str) -> None:
        normalized_url = str(url or "").strip()
        normalized_text = str(text or "").strip()
        if not normalized_url or not normalized_text or normalized_url in visited_urls:
            return
        visited_urls.add(normalized_url)
        source_pages.append({"url": normalized_url, "text": normalized_text})

    def _get_response(url: str, **kwargs: Any) -> Any:
        response = requests_module.get(url, **kwargs)
        response.raise_for_status()
        return response

    if normalized_website:
        try:
            website_response = _get_response(normalized_website, timeout=10)
        except Exception:
            website_response = None
        if website_response is not None:
            _add_page(normalized_website, _normalize_page_text(getattr(website_response, "text", "")))
            parsed_website = urlparse(normalized_website)
            candidate_links = _extract_links(getattr(website_response, "text", ""), base_url=normalized_website)
            for link in candidate_links[:8]:
                parsed_link = urlparse(link)
                if parsed_link.netloc != parsed_website.netloc:
                    continue
                if not any(keyword in parsed_link.path.lower() for keyword in ("team", "about", "company", "brand")):
                    continue
                try:
                    linked_response = _get_response(link, timeout=10)
                except Exception:
                    continue
                _add_page(link, _normalize_page_text(getattr(linked_response, "text", "")))

    search_queries = [f"{normalized_brand_name} 官网".strip()]
    if normalized_company_name:
        search_queries.append(f"{normalized_company_name} 国家企业信用信息公示系统")
    else:
        search_queries.append(f"{normalized_brand_name} 国家企业信用信息公示系统")

    for query in search_queries:
        try:
            search_response = _get_response(
                "https://duckduckgo.com/html/",
                params={"q": query},
                timeout=10,
            )
        except Exception:
            continue
        for link in _extract_links(getattr(search_response, "text", ""), base_url="https://duckduckgo.com/html/")[:5]:
            if link in visited_urls:
                continue
            try:
                page_response = _get_response(link, timeout=10)
            except Exception:
                continue
            _add_page(link, _normalize_page_text(getattr(page_response, "text", "")))

    return [item for item in source_pages if item["text"]]


def _build_source_prompt(
    *,
    brand_name: str,
    company_name: str | None,
    official_website: str | None,
    missing_fields: dict[str, Any],
    source_pages: list[dict[str, str]],
) -> str:
    source_blocks = []
    for index, item in enumerate(source_pages, start=1):
        source_blocks.append(
            "\n".join(
                [
                    f"来源 {index} URL: {item['url']}",
                    f"来源 {index} 内容: {item['text'][:4000]}",
                ]
            )
        )

    return f"""
你是专注【GEO 生成引擎优化】的资深联网信息研究员，仅负责通过联网搜索补全品牌知识库缺失字段。

规则：
1. 只能补全 missing_fields 中当前为空的字段，不允许输出未请求字段。
2. 只能依据下面提供的公开网页来源作答，严禁使用模型内置知识脑补。
3. 来源优先级：品牌官网 > 主体公司官网 > 政府/国家企业信息公示类页面。
4. 如果来源无法支持某个字段，保留空字符串、空数组、空对象，不要编造。
5. 必须输出严格 JSON，不要输出解释文字或代码块。

品牌名称：{brand_name}
品牌所属主体公司全称：{company_name or "未提供"}
品牌官方域名：{official_website or "未提供"}

当前待补空字段：
{json.dumps(missing_fields, ensure_ascii=False)}

公开网页来源：
{chr(10).join(source_blocks)}

请严格输出一个 JSON 对象，结构必须与 missing_fields 一致。
""".strip()


async def enrich_brand_fields_from_web(
    *,
    brand_name: str,
    company_name: str | None,
    official_website: str | None,
    missing_fields: dict[str, Any],
    settings: Settings | None = None,
    requests_module: Any | None = None,
    text_json_caller: Any | None = None,
) -> dict[str, Any]:
    resolved_settings = require_settings(settings)
    normalized_brand_name = str(brand_name or "").strip()
    normalized_company_name = str(company_name or "").strip()
    normalized_website = _normalize_url(official_website)
    if not normalized_brand_name:
        return {}
    if not isinstance(missing_fields, dict) or not missing_fields:
        return {}
    effective_requests_module = requests_module or requests
    effective_text_json_caller = text_json_caller or call_text_llm_json

    def _call_api() -> dict[str, Any]:
        source_pages = _fetch_source_pages(
            brand_name=normalized_brand_name,
            company_name=normalized_company_name or None,
            official_website=normalized_website or None,
            requests_module=effective_requests_module,
        )
        if not source_pages:
            return {}

        prompt = _build_source_prompt(
            brand_name=normalized_brand_name,
            company_name=normalized_company_name or None,
            official_website=normalized_website or None,
            missing_fields=missing_fields,
            source_pages=source_pages,
        )
        parsed = effective_text_json_caller(prompt, settings=resolved_settings)
        if not isinstance(parsed, dict):
            raise ValueError("联网补全结果不是合法 JSON 对象")
        return parsed

    return await asyncio.to_thread(_call_api)
