from __future__ import annotations

import asyncio
import hashlib
import html
import ipaddress
import logging
import re
from typing import Any
from urllib.parse import urlsplit

import requests

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://[^\s<>'\"`，。；、]+", re.IGNORECASE)
_TRAILING_URL_PUNCTUATION = ".,;:!?，。；、：！？)]）】}>\"'"
_MAX_MARKDOWN_CHARS_PER_URL = 12000
_REQUEST_TIMEOUT_SECONDS = 30
_FETCH_CONCURRENCY = 3
_WEB_ARTICLE_EXTRACT_FAILED_MESSAGE = "链接内容提取失败，请复制链接内容到文字要求框"


def extract_instruction_urls(instruction: str, *, max_urls: int | None = None) -> list[str]:
    urls: list[str] = []
    for match in _URL_RE.finditer(str(instruction or "")):
        candidate = match.group(0).strip().rstrip(_TRAILING_URL_PUNCTUATION)
        if not _is_safe_http_url(candidate):
            continue
        if candidate not in urls:
            urls.append(candidate)
        if max_urls is not None and len(urls) >= max_urls:
            break
    return urls


async def build_instruction_web_markdown_sources(
    instruction: str,
    *,
    requests_module: Any | None = None,
    max_urls: int | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    urls = extract_instruction_urls(instruction, max_urls=max_urls)
    if not urls:
        return [], []

    effective_requests = requests_module or requests
    semaphore = asyncio.Semaphore(_FETCH_CONCURRENCY)

    async def _fetch_one(index: int, url: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
        async with semaphore:
            return await asyncio.to_thread(
                _fetch_url_as_markdown_source_or_error,
                url=url,
                index=index,
                requests_module=effective_requests,
            )

    results = await asyncio.gather(*[_fetch_one(index, url) for index, url in enumerate(urls, start=1)])
    source_documents: list[dict[str, Any]] = []
    markdown_sources: list[dict[str, Any]] = []
    for document, source in results:
        source_documents.append(document)
        if source is not None:
            markdown_sources.append(source)
    return source_documents, markdown_sources


def _fetch_url_as_markdown_source_or_error(
    *,
    url: str,
    index: int,
    requests_module: Any,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    try:
        return _fetch_url_as_markdown_source(url=url, index=index, requests_module=requests_module)
    except Exception as exc:
        logger.warning(
            "Failed to fetch instruction URL as markdown index=%s url=%s error_type=%s error=%s",
            index,
            url,
            type(exc).__name__,
            exc,
        )
        return _build_failed_url_source_document(url=url, index=index, exc=exc), None


def _fetch_url_as_markdown_source(
    *,
    url: str,
    index: int,
    requests_module: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    response = requests_module.get(
        url,
        timeout=_REQUEST_TIMEOUT_SECONDS,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (compatible; KnowledgeBaseBot/1.0; "
                "+https://example.com/knowledge-base)"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.5",
        },
    )
    if hasattr(response, "raise_for_status"):
        response.raise_for_status()
    content_type = _header_value(getattr(response, "headers", {}), "content-type")
    text = str(getattr(response, "text", "") or "")
    if not text and getattr(response, "content", None):
        text = bytes(getattr(response, "content")).decode("utf-8", errors="replace")
    if not text.strip():
        raise ValueError("网页内容为空")
    if content_type and not _looks_like_text_content_type(content_type):
        raise ValueError(f"网页 Content-Type 不支持: {content_type}")

    article = _html_to_article_markdown(text, url=url)
    markdown_text = article["markdown_text"].strip()
    if not markdown_text:
        raise ValueError("未抽取到有效网页正文")

    source_name = _source_name_for_display(article.get("title"), url=url, index=index)
    document_id = f"iteration_url:{hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]}"
    source_document = {
        "document_id": document_id,
        "original_filename": f"{source_name}.md",
        "source_type": "web_article",
        "source_role": "iteration_web_article",
        "source_url": url,
        "markdown_text": markdown_text,
    }
    markdown_source = {
        "source_name": f"{source_name}.md",
        "subcategory": "网页正文",
        "source_role": "iteration_web_article",
        "source_url": url,
        "markdown_text": markdown_text,
    }
    return source_document, markdown_source


def _build_failed_url_source_document(*, url: str, index: int, exc: Exception) -> dict[str, Any]:
    document_id = f"iteration_url_failed:{hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]}"
    return {
        "document_id": document_id,
        "original_filename": _failed_source_name_for_display(url=url, index=index),
        "source_type": "web_article_error",
        "source_role": "iteration_web_article_error",
        "source_url": url,
        "error_message": _WEB_ARTICLE_EXTRACT_FAILED_MESSAGE,
        "error_type": type(exc).__name__,
    }


def _is_safe_http_url(value: str) -> bool:
    try:
        parsed = urlsplit(str(value or "").strip())
    except ValueError:
        return False
    if parsed.scheme.lower() not in {"http", "https"}:
        return False
    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        return False
    if hostname in {"localhost", "127.0.0.1", "::1"} or hostname.endswith(".local"):
        return False
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return True
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def _looks_like_text_content_type(content_type: str) -> bool:
    normalized = str(content_type or "").lower()
    return any(
        marker in normalized
        for marker in (
            "text/html",
            "application/xhtml+xml",
            "text/plain",
            "application/xml",
            "text/xml",
        )
    )


def _header_value(headers: Any, key: str) -> str:
    if not headers:
        return ""
    if hasattr(headers, "get"):
        return str(headers.get(key) or headers.get(key.title()) or "").strip()
    return ""


def _html_to_article_markdown(raw_html: str, *, url: str) -> dict[str, str]:
    try:
        from bs4 import BeautifulSoup
    except Exception:
        return _html_to_article_markdown_fallback(raw_html, url=url)

    soup = BeautifulSoup(raw_html, "html.parser")
    for tag in soup(["script", "style", "noscript", "iframe", "svg", "canvas", "form"]):
        tag.decompose()
    for tag in soup.find_all(["header", "footer", "nav", "aside"]):
        tag.decompose()

    title = _extract_soup_title(soup).strip()
    published_at = _extract_soup_meta(
        soup,
        (
            "article:published_time",
            "pubdate",
            "publishdate",
            "publish_date",
            "date",
            "createdate",
            "weibo: article:create_at",
        ),
    ).strip()
    source_name = _extract_soup_meta(
        soup,
        (
            "article:publisher",
            "og:site_name",
            "source",
            "mediaid",
            "author",
        ),
    ).strip()
    article_node = _select_article_node(soup)
    body_markdown = _soup_node_to_markdown(article_node).strip()
    if not body_markdown:
        body_markdown = _normalize_plain_text(article_node.get_text("\n", strip=True))
    body_markdown = _truncate_markdown(body_markdown)

    display_title = _clean_display_text(title) or url
    header_lines = [f"# 网页正文：{display_title}", "", f"- 来源链接：{url}"]
    if source_name:
        header_lines.append(f"- 来源名称：{source_name}")
    if published_at:
        header_lines.append(f"- 发布时间：{published_at}")
    header_lines.extend(["", "## 正文", "", body_markdown])
    return {
        "title": _safe_source_name(display_title or source_name or url),
        "markdown_text": "\n".join(header_lines).strip(),
    }


def _html_to_article_markdown_fallback(raw_html: str, *, url: str) -> dict[str, str]:
    title_match = re.search(r"<title[^>]*>([\s\S]*?)</title>", raw_html or "", flags=re.IGNORECASE)
    title = html.unescape(re.sub(r"\s+", " ", title_match.group(1)).strip()) if title_match else ""
    text = re.sub(r"<script[\s\S]*?</script>", " ", raw_html or "", flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"</(?:p|div|section|article|h[1-6]|li|tr)>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    body = _truncate_markdown(_normalize_plain_text(html.unescape(text)))
    display_title = _clean_display_text(title) or url
    return {
        "title": _safe_source_name(display_title),
        "markdown_text": f"# 网页正文：{display_title}\n\n- 来源链接：{url}\n\n## 正文\n\n{body}".strip(),
    }


def _extract_soup_title(soup: Any) -> str:
    candidates: list[str] = []
    for attrs in (
        {"property": "og:title"},
        {"name": "title"},
        {"name": "ArticleTitle"},
    ):
        tag = soup.find("meta", attrs=attrs)
        value = str(tag.get("content") or "").strip() if tag else ""
        if value:
            candidates.append(_normalize_plain_text(value))
    h1 = soup.find("h1")
    if h1:
        value = h1.get_text(" ", strip=True)
        if value:
            candidates.append(_normalize_plain_text(value))
    if soup.title:
        candidates.append(_normalize_plain_text(soup.title.get_text(" ", strip=True)))
    for candidate in candidates:
        cleaned = _clean_display_text(candidate)
        if cleaned:
            return cleaned
    return ""


def _extract_soup_meta(soup: Any, keys: tuple[str, ...]) -> str:
    normalized_keys = {key.lower() for key in keys}
    for meta in soup.find_all("meta"):
        meta_key = str(meta.get("property") or meta.get("name") or meta.get("itemprop") or "").strip().lower()
        if meta_key not in normalized_keys:
            continue
        value = str(meta.get("content") or "").strip()
        cleaned = _clean_display_text(value)
        if cleaned:
            return cleaned
    return ""


def _select_article_node(soup: Any) -> Any:
    candidates = []
    selectors = (
        "article",
        "main",
        "[id*=article]",
        "[class*=article]",
        "[id*=content]",
        "[class*=content]",
        "[id*=main]",
        "[class*=main]",
        "[class*=text]",
        "[id*=text]",
    )
    for selector in selectors:
        candidates.extend(soup.select(selector))
    if not candidates:
        return soup.body or soup

    def score(node: Any) -> int:
        text = node.get_text("\n", strip=True)
        paragraphs = len(node.find_all(["p", "li"]))
        return len(text) + paragraphs * 80

    return max(candidates, key=score)


def _soup_node_to_markdown(node: Any) -> str:
    try:
        from markdownify import markdownify as markdownify_html
    except Exception:
        return _normalize_plain_text(node.get_text("\n", strip=True))
    markdown_text = markdownify_html(str(node), heading_style="ATX", bullets="-")
    return _normalize_markdown(markdown_text)


def _normalize_markdown(value: str) -> str:
    lines = [line.rstrip() for line in str(value or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    collapsed: list[str] = []
    blank_count = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            blank_count += 1
            if blank_count <= 1:
                collapsed.append("")
            continue
        blank_count = 0
        collapsed.append(stripped)
    return "\n".join(collapsed).strip()


def _normalize_plain_text(value: str) -> str:
    text = re.sub(r"[ \t\f\v]+", " ", str(value or ""))
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def _truncate_markdown(value: str) -> str:
    text = _normalize_markdown(value)
    if len(text) <= _MAX_MARKDOWN_CHARS_PER_URL:
        return text
    return text[:_MAX_MARKDOWN_CHARS_PER_URL].rstrip() + "\n\n[网页正文因长度限制已截断]"


def _safe_source_name(value: str) -> str:
    normalized = _clean_display_text(value)
    normalized = re.sub(r"[\\/:*?\"<>|]+", "_", normalized)
    return normalized[:120].strip(" ._") or "网页正文"


def _source_name_for_display(value: Any, *, url: str, index: int) -> str:
    safe_title = _safe_source_name(str(value or ""))
    if safe_title != "网页正文":
        return safe_title
    host = urlsplit(str(url or "")).netloc.strip() or "web"
    host = re.sub(r"[\\/:*?\"<>|]+", "_", host)
    return f"网页来源-{host}-{index}"


def _failed_source_name_for_display(*, url: str, index: int) -> str:
    host = urlsplit(str(url or "")).netloc.strip() or "web"
    host = re.sub(r"[\\/:*?\"<>|]+", "_", host)
    return f"链接内容提取失败-{host}-{index}"


def _clean_display_text(value: Any) -> str:
    normalized = re.sub(r"\s+", " ", str(value or "")).strip()
    if not normalized:
        return ""
    repaired = _repair_common_mojibake(normalized)
    candidate = repaired if _display_text_score(repaired) > _display_text_score(normalized) else normalized
    if _looks_like_mojibake(candidate):
        return ""
    return candidate


def _repair_common_mojibake(value: str) -> str:
    candidates = [value]
    for source_encoding in ("latin1", "cp1252"):
        for target_encoding in ("utf-8", "gb18030"):
            try:
                candidates.append(value.encode(source_encoding).decode(target_encoding))
            except Exception:
                continue
    return max(candidates, key=_display_text_score)


def _display_text_score(value: str) -> int:
    text = str(value or "")
    chinese_count = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    mojibake_penalty = sum(text.count(marker) for marker in ("Ã", "Â", "â", "ä", "å", "ç", "ð", "�"))
    return chinese_count * 4 - mojibake_penalty * 3 - text.count("?")


def _looks_like_mojibake(value: str) -> bool:
    text = str(value or "")
    if not text:
        return False
    if "�" in text:
        return True
    suspicious_count = sum(text.count(marker) for marker in ("Ã", "Â", "â", "ä", "å", "ç", "ð"))
    chinese_count = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    return suspicious_count >= 2 and chinese_count == 0
