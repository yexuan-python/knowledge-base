from __future__ import annotations

import asyncio
import html
import importlib.util
import logging
from pathlib import Path
import platform
import re
from typing import Any

from knowledge_base.infrastructure.settings import Settings


logger = logging.getLogger(__name__)

_PDF_RENDER_CSS = """
    :root {
        color-scheme: light;
        font-family: "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", -apple-system, BlinkMacSystemFont, sans-serif;
        color: #1f2937;
        background: #ffffff;
    }
    @page {
        size: A4;
        margin: 16mm 14mm 18mm;
    }
    * {
        box-sizing: border-box;
    }
    body {
        margin: 0;
        font-size: 13px;
        line-height: 1.72;
        color: #1f2937;
        background: #ffffff;
        word-break: break-word;
    }
    main {
        width: 100%;
    }
    h1, h2, h3, h4, h5, h6 {
        color: #0f172a;
        line-height: 1.35;
        margin: 1.2em 0 0.55em;
        page-break-after: avoid;
    }
    h1 {
        font-size: 24px;
        padding-bottom: 0.35em;
        border-bottom: 1px solid #dbe4ee;
    }
    h2 {
        font-size: 19px;
        padding-left: 0.45em;
        border-left: 4px solid #2563eb;
    }
    h3 {
        font-size: 16px;
    }
    h4, h5, h6 {
        font-size: 14px;
    }
    p, ul, ol, blockquote, pre, table {
        margin: 0 0 0.95em;
    }
    ul, ol {
        padding-left: 1.45em;
    }
    li + li {
        margin-top: 0.28em;
    }
    blockquote {
        margin-left: 0;
        padding: 0.1em 0 0.1em 1em;
        border-left: 3px solid #cbd5e1;
        color: #475569;
        background: #f8fafc;
    }
    code {
        font-family: "SFMono-Regular", "Menlo", "Monaco", "Consolas", monospace;
        font-size: 0.92em;
        background: #eff3f8;
        border-radius: 4px;
        padding: 0.1em 0.35em;
    }
    pre {
        overflow: hidden;
        padding: 0.9em 1em;
        border-radius: 8px;
        background: #0f172a;
        color: #e2e8f0;
        white-space: pre-wrap;
    }
    pre code {
        padding: 0;
        background: transparent;
        color: inherit;
    }
    hr {
        border: none;
        border-top: 1px solid #dbe4ee;
        margin: 1.25em 0;
    }
    a {
        color: #1d4ed8;
        text-decoration: none;
    }
    table {
        width: 100%;
        border-collapse: collapse;
        table-layout: fixed;
        font-size: 12px;
    }
    thead {
        display: table-header-group;
    }
    tr {
        page-break-inside: avoid;
    }
    th, td {
        border: 1px solid #cbd5e1;
        padding: 0.55em 0.65em;
        text-align: left;
        vertical-align: top;
    }
    th {
        background: #eff6ff;
        color: #0f172a;
    }
    tbody tr:nth-child(even) td {
        background: #f8fafc;
    }
"""
_INLINE_LITERAL_ASTERISK_TOKEN_RE = re.compile(r"(?<!\S)(?=[^\s]*\d)[^\s*]+(?:\*[^\s*]+)+(?!\S)")
_INLINE_LITERAL_ASTERISK_PLACEHOLDER = "KBLITERALASTERISKPLACEHOLDER"
_SUPERSCRIPT_TRANSLATION = str.maketrans("0123456789+-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻")
_SUBSCRIPT_TRANSLATION = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
_CHEMICAL_ELEMENT_SYMBOLS = frozenset(
    {
        "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne",
        "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar", "K", "Ca",
        "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
        "Ga", "Ge", "As", "Se", "Br", "Kr", "Rb", "Sr", "Y", "Zr",
        "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn",
        "Sb", "Te", "I", "Xe", "Cs", "Ba", "La", "Ce", "Pr", "Nd",
        "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb",
        "Lu", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg",
        "Tl", "Pb", "Bi", "Po", "At", "Rn", "Fr", "Ra", "Ac", "Th",
        "Pa", "U", "Np", "Pu", "Am", "Cm", "Bk", "Cf", "Es", "Fm",
        "Md", "No", "Lr", "Rf", "Db", "Sg", "Bh", "Hs", "Mt", "Ds",
        "Rg", "Cn", "Nh", "Fl", "Mc", "Lv", "Ts", "Og",
    }
)
_PDF_DISPLAY_UNIT_BASES = (
    "pm",
    "nm",
    "um",
    "μm",
    "mm",
    "cm",
    "dm",
    "m",
    "km",
    "in",
    "ft",
    "yd",
    "mi",
)
_PDF_DISPLAY_UNIT_EXPONENT_RE = re.compile(
    rf"(?P<prefix>[/单每]?)"
    rf"(?<![A-Za-z])"
    rf"(?P<unit>{'|'.join(_PDF_DISPLAY_UNIT_BASES)})"
    rf"(?P<exp>[23])"
    rf"(?![0-9A-Za-z])",
    re.IGNORECASE,
)
_PDF_DISPLAY_DENOMINATOR_UNIT_EXPONENT_RE = re.compile(
    r"(?P<prefix>/)(?P<unit>s|sec|min|h|hr|d)(?:\^)?(?P<exp>[23])(?![0-9A-Za-z])",
    re.IGNORECASE,
)
_PDF_DISPLAY_FORMULA_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<token>[A-Za-z0-9()[\]·.^+-]{2,})(?![A-Za-z0-9])"
)
_PDF_DISPLAY_FORMULA_BODY_TOKEN_RE = re.compile(r"[A-Z][a-z]?|\d+|\(|\)|\[|\]|·|\.")
_PDF_DISPLAY_SIMPLE_FORMULA_WHITELIST = frozenset({"H2", "N2", "O2", "F2", "Cl2", "Br2", "I2", "O3"})


def _normalize_pdf_display_units(text: str) -> str:
    normalized = str(text or "")
    if not normalized:
        return ""

    def replace_unit(match: re.Match[str]) -> str:
        prefix = match.group("prefix") or ""
        unit = match.group("unit") or ""
        exp = match.group("exp") or ""
        unit_start = match.start("unit")
        if not prefix:
            preceding_token_chars: list[str] = []
            cursor = unit_start - 1
            while cursor >= 0 and match.string[cursor].isalnum():
                preceding_token_chars.append(match.string[cursor])
                cursor -= 1
            preceding_token = "".join(reversed(preceding_token_chars))
            if any(char.isalpha() and char.isascii() for char in preceding_token):
                return match.group(0)
        normalized_unit = unit
        if unit.lower() == "um":
            normalized_unit = "μm"
        elif unit.lower() == "μm":
            normalized_unit = "μm"
        elif unit.isupper():
            normalized_unit = unit
        else:
            normalized_unit = unit.lower()

        if normalized_unit == "m" and exp == "2" and prefix in {"/", "单", "每"}:
            return f"{prefix}㎡"

        superscript = "²" if exp == "2" else "³"
        return f"{prefix}{normalized_unit}{superscript}"

    normalized = _PDF_DISPLAY_UNIT_EXPONENT_RE.sub(replace_unit, normalized)
    normalized = _PDF_DISPLAY_DENOMINATOR_UNIT_EXPONENT_RE.sub(
        lambda match: f"{match.group('prefix')}{str(match.group('unit') or '').lower()}{'²' if match.group('exp') == '2' else '³'}",
        normalized,
    )

    def replace_formula_token(match: re.Match[str]) -> str:
        token = match.group("token") or ""
        normalized_token = _normalize_pdf_display_formula_token(token)
        return normalized_token or token

    return _PDF_DISPLAY_FORMULA_TOKEN_RE.sub(replace_formula_token, normalized)


def _normalize_pdf_display_formula_token(token: str) -> str | None:
    normalized = str(token or "").strip()
    if not normalized or "/" in normalized or not any(char.isdigit() for char in normalized):
        return None
    if re.match(r"^[A-Z]{3,}(?=\d)", normalized):
        return None

    body = normalized
    charge = ""

    if "^" in normalized:
        caret_match = re.fullmatch(r"(?P<body>[A-Za-z0-9()[\]·.]+)\^(?P<charge>\d*[+-])", normalized)
        if not caret_match:
            return None
        body = str(caret_match.group("body") or "")
        charge = str(caret_match.group("charge") or "")
    elif normalized.endswith(("+", "-")):
        sign_match = re.fullmatch(r"(?P<body>[A-Za-z0-9()[\]·.]+)(?P<charge>[+-])", normalized)
        if not sign_match:
            return None
        body = str(sign_match.group("body") or "")
        charge = str(sign_match.group("charge") or "")

    matches = list(_PDF_DISPLAY_FORMULA_BODY_TOKEN_RE.finditer(body))
    if not matches or "".join(item.group(0) for item in matches) != body:
        return None

    element_tokens = [item.group(0) for item in matches if re.fullmatch(r"[A-Z][a-z]?", item.group(0))]
    if not element_tokens:
        return None
    if any(item not in _CHEMICAL_ELEMENT_SYMBOLS for item in element_tokens):
        return None
    if len(element_tokens) < 2 and body not in _PDF_DISPLAY_SIMPLE_FORMULA_WHITELIST and "(" not in body and "[" not in body:
        return None

    rendered_parts: list[str] = []
    previous_token_type: str | None = None
    for item in matches:
        part = item.group(0)
        if re.fullmatch(r"[A-Z][a-z]?", part):
            rendered_parts.append(part)
            previous_token_type = "element"
            continue
        if part in {")", "]"}:
            rendered_parts.append(part)
            previous_token_type = "group_close"
            continue
        if part in {"(", "["}:
            rendered_parts.append(part)
            previous_token_type = "group_open"
            continue
        if part in {"·", "."}:
            rendered_parts.append("·" if part == "." else part)
            previous_token_type = "separator"
            continue
        if part.isdigit():
            if previous_token_type in {"element", "group_close"}:
                rendered_parts.append(part.translate(_SUBSCRIPT_TRANSLATION))
            else:
                rendered_parts.append(part)
            previous_token_type = "number"
            continue
        return None

    if not charge:
        return "".join(rendered_parts)
    return "".join(rendered_parts) + charge.translate(_SUPERSCRIPT_TRANSLATION)


def _render_inline_markdown(text: str) -> str:
    escaped = html.escape(_normalize_pdf_display_units(str(text or "")), quote=False)
    placeholders: dict[str, str] = {}

    def _stash(fragment: str) -> str:
        key = f"__kb_html_fragment_{len(placeholders)}__"
        placeholders[key] = fragment
        return key

    escaped = re.sub(
        r"`([^`]+)`",
        lambda match: _stash(f"<code>{match.group(1)}</code>"),
        escaped,
    )
    escaped = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda match: _stash(
            f'<a href="{html.escape(html.unescape(match.group(2)).strip(), quote=True)}">{match.group(1)}</a>'
        ),
        escaped,
    )
    escaped = _INLINE_LITERAL_ASTERISK_TOKEN_RE.sub(
        lambda match: match.group(0).replace("*", _INLINE_LITERAL_ASTERISK_PLACEHOLDER),
        escaped,
    )
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"__(.+?)__", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<em>\1</em>", escaped)
    escaped = re.sub(r"(?<!_)_(?!\s)(.+?)(?<!\s)_(?!_)", r"<em>\1</em>", escaped)
    escaped = escaped.replace(_INLINE_LITERAL_ASTERISK_PLACEHOLDER, "*")

    for key, fragment in placeholders.items():
        escaped = escaped.replace(key, fragment)
    return escaped


def _is_table_separator(line: str) -> bool:
    normalized = str(line or "").strip()
    return bool(normalized and "-" in normalized and re.fullmatch(r"[\|\-\:\s]+", normalized))


def _parse_table_row(line: str) -> list[str]:
    normalized = str(line or "").strip()
    if normalized.startswith("|"):
        normalized = normalized[1:]
    if normalized.endswith("|"):
        normalized = normalized[:-1]
    return [cell.strip() for cell in normalized.split("|")]


def _markdown_to_html_blocks(markdown_text: str) -> str:
    lines = str(markdown_text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    parts: list[str] = []
    paragraph_lines: list[str] = []
    list_items: list[str] = []
    list_tag: str | None = None
    index = 0

    def _flush_paragraph() -> None:
        nonlocal paragraph_lines
        if not paragraph_lines:
            return
        combined = " ".join(line.strip() for line in paragraph_lines if line.strip())
        if combined:
            parts.append(f"<p>{_render_inline_markdown(combined)}</p>")
        paragraph_lines = []

    def _flush_list() -> None:
        nonlocal list_items, list_tag
        if not list_items or not list_tag:
            list_items = []
            list_tag = None
            return
        rendered_items = "".join(f"<li>{_render_inline_markdown(item)}</li>" for item in list_items)
        parts.append(f"<{list_tag}>{rendered_items}</{list_tag}>")
        list_items = []
        list_tag = None

    def _flush_all() -> None:
        _flush_paragraph()
        _flush_list()

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if not stripped:
            _flush_all()
            index += 1
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading_match:
            _flush_all()
            level = len(heading_match.group(1))
            parts.append(f"<h{level}>{_render_inline_markdown(heading_match.group(2).strip())}</h{level}>")
            index += 1
            continue

        if re.fullmatch(r"(\*\s*){3,}|(-\s*){3,}|(_\s*){3,}", stripped):
            _flush_all()
            parts.append("<hr />")
            index += 1
            continue

        if stripped.startswith("```"):
            _flush_all()
            code_lines: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code_lines.append(lines[index])
                index += 1
            parts.append(f"<pre><code>{html.escape(chr(10).join(code_lines))}</code></pre>")
            if index < len(lines):
                index += 1
            continue

        if stripped.startswith(">"):
            _flush_all()
            quote_lines: list[str] = []
            while index < len(lines) and lines[index].strip().startswith(">"):
                quote_lines.append(re.sub(r"^\s*>\s?", "", lines[index]))
                index += 1
            parts.append(f"<blockquote>{_markdown_to_html_blocks(chr(10).join(quote_lines))}</blockquote>")
            continue

        if "|" in stripped and index + 1 < len(lines) and _is_table_separator(lines[index + 1]):
            _flush_all()
            header_cells = _parse_table_row(stripped)
            index += 2
            body_rows: list[list[str]] = []
            while index < len(lines):
                candidate = lines[index].strip()
                if not candidate or "|" not in candidate:
                    break
                body_rows.append(_parse_table_row(candidate))
                index += 1
            header_html = "".join(f"<th>{_render_inline_markdown(cell)}</th>" for cell in header_cells)
            body_html = "".join(
                "<tr>"
                + "".join(f"<td>{_render_inline_markdown(cell)}</td>" for cell in row)
                + "</tr>"
                for row in body_rows
            )
            parts.append(
                "<table><thead><tr>"
                + header_html
                + "</tr></thead><tbody>"
                + body_html
                + "</tbody></table>"
            )
            continue

        unordered_match = re.match(r"^[-+*]\s+(.*)$", stripped)
        ordered_match = re.match(r"^\d+\.\s+(.*)$", stripped)
        if unordered_match or ordered_match:
            item_text = (unordered_match or ordered_match).group(1).strip()
            candidate_list_tag = "ul" if unordered_match else "ol"
            if paragraph_lines:
                _flush_paragraph()
            if list_tag and list_tag != candidate_list_tag:
                _flush_list()
            list_tag = candidate_list_tag
            list_items.append(item_text)
            index += 1
            continue

        if list_items:
            _flush_list()
        paragraph_lines.append(line)
        index += 1

    _flush_all()
    return "".join(parts)


def _render_markdown_to_html_document(markdown_text: str, *, title: str) -> str:
    body_html = _markdown_to_html_blocks(markdown_text)
    return (
        "<!doctype html>"
        '<html lang="zh-CN">'
        "<head>"
        '<meta charset="utf-8" />'
        f"<title>{html.escape(title)}</title>"
        f"<style>{_PDF_RENDER_CSS}</style>"
        "</head>"
        "<body><main>"
        f"{body_html}"
        "</main></body></html>"
    )


def _collect_pdf_renderer_diagnostics() -> dict[str, Any]:
    cache_root = Path.home() / "Library" / "Caches" / "ms-playwright"
    chromium_dirs = sorted(
        path.name
        for path in cache_root.glob("chromium-*")
    ) if cache_root.exists() else []
    headless_shell_dirs = sorted(
        path.name
        for path in cache_root.glob("chromium_headless_shell-*")
    ) if cache_root.exists() else []
    return {
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "playwright_installed": bool(importlib.util.find_spec("playwright")),
        "playwright_cache_root": str(cache_root),
        "playwright_cache_root_exists": cache_root.exists(),
        "chromium_cache_dirs": chromium_dirs,
        "headless_shell_cache_dirs": headless_shell_dirs,
    }


def _format_pdf_renderer_diagnostics(diagnostics: dict[str, Any]) -> str:
    parts = [
        f"platform={diagnostics.get('platform')}",
        f"python_version={diagnostics.get('python_version')}",
        f"playwright_installed={diagnostics.get('playwright_installed')}",
        f"playwright_cache_root={diagnostics.get('playwright_cache_root')}",
        f"playwright_cache_root_exists={diagnostics.get('playwright_cache_root_exists')}",
        f"chromium_cache_dirs={diagnostics.get('chromium_cache_dirs')}",
        f"headless_shell_cache_dirs={diagnostics.get('headless_shell_cache_dirs')}",
    ]
    return "; ".join(parts)


def _build_playwright_pdf_error_message(
    *,
    exc: Exception,
    diagnostics: dict[str, Any],
    render_timeout_seconds: int,
) -> str:
    base_message = str(exc).strip() or exc.__class__.__name__
    hints: list[str] = []

    if isinstance(exc, asyncio.TimeoutError):
        hints.append(f"PDF 渲染超时，超过 {render_timeout_seconds}s，可考虑调大 KB_PDF_RENDER_TIMEOUT_SECONDS。")
    if isinstance(exc, ModuleNotFoundError):
        hints.append("当前 Python 环境缺少 playwright 包，请先安装依赖。")

    lowered = base_message.lower()
    if "executable doesn't exist" in lowered or "playwright install" in lowered:
        hints.append("Playwright 浏览器未安装，请执行 `python -m playwright install chromium`。")
    if "permission denied" in lowered or "machportrendezvousserver" in lowered:
        hints.append("当前运行环境限制了 Chromium 子进程启动；请在目标服务器环境直接执行自检脚本确认权限。")
    if "target page, context or browser has been closed" in lowered:
        hints.append("浏览器进程启动后立刻退出，常见原因是系统权限限制、缺少运行库或浏览器安装损坏。")

    diagnostics_text = _format_pdf_renderer_diagnostics(diagnostics)
    hint_text = " ".join(hints).strip()
    if hint_text:
        return f"{base_message} | {hint_text} | diagnostics: {diagnostics_text}"
    return f"{base_message} | diagnostics: {diagnostics_text}"


async def render_brand_full_knowledge_pdf_bytes(
    markdown_text: str,
    *,
    title: str,
    settings: Settings,
) -> bytes:
    html_document = _render_markdown_to_html_document(markdown_text, title=title)
    render_timeout_seconds = max(5, int(getattr(settings, "pdf_render_timeout_seconds", 45) or 45))
    diagnostics = _collect_pdf_renderer_diagnostics()

    try:
        from playwright.async_api import async_playwright
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised in runtime env
        message = _build_playwright_pdf_error_message(
            exc=exc,
            diagnostics=diagnostics,
            render_timeout_seconds=render_timeout_seconds,
        )
        logger.error("Brand knowledge PDF renderer unavailable: %s", message, exc_info=True)
        raise ValueError(
            "缺少 Playwright 依赖，无法生成品牌知识库 PDF。"
            "请安装 playwright，并执行 `playwright install chromium`。"
            f" diagnostics: {_format_pdf_renderer_diagnostics(diagnostics)}"
        ) from exc

    async def _render() -> bytes:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.set_content(html_document, wait_until="domcontentloaded")
                pdf_bytes = await page.pdf(
                    format="A4",
                    print_background=True,
                    prefer_css_page_size=True,
                )
            finally:
                await browser.close()
        if not pdf_bytes:
            raise ValueError("Playwright PDF 渲染失败: 未生成有效 PDF 字节")
        return pdf_bytes

    try:
        return await asyncio.wait_for(_render(), timeout=render_timeout_seconds)
    except asyncio.TimeoutError as exc:
        message = _build_playwright_pdf_error_message(
            exc=exc,
            diagnostics=diagnostics,
            render_timeout_seconds=render_timeout_seconds,
        )
        logger.error("Brand knowledge PDF render timeout title=%s: %s", title, message, exc_info=True)
        raise ValueError(message) from exc
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, ValueError):
            raise
        message = _build_playwright_pdf_error_message(
            exc=exc,
            diagnostics=diagnostics,
            render_timeout_seconds=render_timeout_seconds,
        )
        logger.error("Brand knowledge PDF render failed title=%s: %s", title, message, exc_info=True)
        raise ValueError(f"Playwright PDF 渲染失败: {message}") from exc
