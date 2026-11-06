from __future__ import annotations

import asyncio
import ast
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from knowledge_base.shared.utils import normalize_text_sequence


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _MarkdownRenderIndex:
    markdown_text: str
    lines: tuple[str, ...]
    headings: tuple[tuple[int, int, str], ...]


class BrandPathRenderingMixin:
    async def _build_brand_path_index(
        self,
        *,
        brand: dict[str, Any],
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
    ) -> list[dict[str, str]]:
        candidates: list[dict[str, str]] = []
        seen_paths: set[str] = set()
        summary_semaphore = asyncio.Semaphore(self.PATH_INDEX_SUMMARY_MAX_CONCURRENCY)

        def add_item(path: str, title: str, fallback_summary: str) -> None:
            normalized_path = path.strip()
            if not normalized_path or normalized_path in seen_paths:
                return
            seen_paths.add(normalized_path)
            candidates.append(
                {
                    "path": normalized_path,
                    "title": title.strip(),
                    "summary": fallback_summary.strip()[:120],
                }
            )

        company_profile_payload = company_profile if isinstance(company_profile, dict) else {}
        add_item(
            self.BRAND_OVERVIEW_PATH,
            "品牌介绍",
            self._build_text_summary(
                brand.get("intro"),
                company_profile_payload.get("company_intro"),
                company_profile_payload.get("brand_subject_name"),
                fallback="品牌、行业、官网和主体信息介绍。",
            ),
        )
        if self._has_meaningful_payload(company_profile_payload):
            add_item(
                self.COMPANY_PROFILE_PATH,
                "公司档案",
                self._build_text_summary(
                    company_profile_payload.get("company_intro"),
                    company_profile_payload.get("brand_subject_name"),
                    company_profile_payload.get("company_address"),
                    company_profile_payload.get("stock_info"),
                    fallback="企业主体、简介、地址与上市信息。",
                ),
            )

        if isinstance(management_team, list) and management_team:
            add_item(
                self.MANAGEMENT_TEAM_PATH,
                "管理团队",
                "品牌管理团队与核心成员介绍。",
            )

        for product in products:
            product_name = str(product.get("product_name") or "").strip()
            if not product_name:
                continue
            add_item(
                self._build_product_path(product_name),
                product_name,
                self._build_product_summary(product),
            )

        for competitor in competitors:
            competitor_name = str(competitor.get("name") or "").strip()
            if not competitor_name:
                continue
            add_item(
                self._build_competitor_path(competitor_name),
                competitor_name,
                self._build_text_summary(competitor.get("intro"), fallback="竞品资料。"),
            )

        if isinstance(honors, list) and honors:
            add_item(
                self.HONORS_PATH,
                "权威荣誉",
                "品牌荣誉、资质、奖项与认证信息。",
            )

        if isinstance(cases, list) and cases:
            add_item(
                self.CASES_PATH,
                "客户案例",
                "品牌客户案例与合作项目资料。",
            )

        if self._has_sensitive_topics_content(sensitive_topics):
            add_item(
                self.SENSITIVE_TOPICS_PATH,
                "敏感话题",
                "品牌敏感议题、风险点与回应口径。",
            )

        if isinstance(official_malls, list) and official_malls:
            add_item(
                self.OFFICIAL_MALLS_PATH,
                "官方商城",
                "品牌官方商城、店铺平台、主营品类与店铺优势。",
            )

        if isinstance(official_media_matrix, list) and official_media_matrix:
            add_item(
                self.OFFICIAL_MEDIA_MATRIX_PATH,
                "官方媒体与矩阵",
                "品牌官方媒体平台、账号矩阵与关联产品信息。",
            )

        return await asyncio.gather(
            *[
                self._summarize_path_index_item(
                    item=item,
                    summary_semaphore=summary_semaphore,
                    brand=brand,
                    knowledge_revision=knowledge_revision,
                    company_profile=company_profile,
                    management_team=management_team,
                    products=products,
                    competitors=competitors,
                    competitors_content=competitors_content,
                    honors=honors,
                    cases=cases,
                    sensitive_topics=sensitive_topics,
                    attachments=attachments,
                    official_malls=official_malls,
                    official_media_matrix=official_media_matrix,
                    full_knowledge_markdown=full_knowledge_markdown,
                    full_knowledge_markdown_index=full_knowledge_markdown_index,
                )
                for item in candidates
            ]
        )

    async def _summarize_path_index_item(
        self,
        *,
        item: dict[str, str],
        summary_semaphore: asyncio.Semaphore,
        brand: dict[str, Any],
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
        full_knowledge_markdown: str | None,
        full_knowledge_markdown_index: _MarkdownRenderIndex | None,
    ) -> dict[str, str]:
        path = str(item.get("path") or "").strip()
        title = str(item.get("title") or "").strip()
        fallback_summary = str(item.get("summary") or "").strip()
        brand_code = str(self._brand_code_from_row(brand) or "").strip()
        cached_summary = self._get_cached_path_index_summary(
            brand_code=brand_code,
            knowledge_revision=knowledge_revision,
            path=path,
        )
        if cached_summary:
            return {
                "path": path,
                "title": title,
                "summary": cached_summary[:120],
            }
        asset = self._render_brand_asset(
            brand=brand,
            path=path,
            knowledge_revision=knowledge_revision,
            company_profile=company_profile,
            management_team=management_team,
            products=products,
            competitors=competitors,
            competitors_content=competitors_content,
            honors=honors,
            cases=cases,
            sensitive_topics=sensitive_topics,
            attachments=attachments,
            official_malls=official_malls,
            official_media_matrix=official_media_matrix,
            full_knowledge_markdown=full_knowledge_markdown,
            full_knowledge_markdown_index=full_knowledge_markdown_index,
        )
        content = str((asset or {}).get("content") or "").strip()
        summary = fallback_summary or self._fallback_summary_from_content(content, title=title)
        if content:
            try:
                summary_content = self._prepare_path_index_summary_content(content)
                async with summary_semaphore:
                    generated_summary = await self._summarize_text(summary_content, settings=self._deps.settings)
            except Exception:
                generated_summary = ""
            if str(generated_summary or "").strip():
                summary = str(generated_summary).strip()
            elif not summary:
                summary = self._fallback_summary_from_content(content, title=title)
        self._cache_path_index_summary(
            brand_code=brand_code,
            knowledge_revision=knowledge_revision,
            path=path,
            summary=summary,
        )
        return {
            "path": path,
            "title": title,
            "summary": summary[:120],
        }

    @classmethod
    def _fallback_summary_from_content(cls, content: str, *, title: str = "") -> str:
        lines = [line.strip() for line in str(content or "").splitlines()]
        cleaned_lines: list[str] = []
        for line in lines:
            if not line:
                continue
            normalized = line.lstrip("#*- ").strip()
            if not normalized:
                continue
            if title and normalized == title:
                continue
            cleaned_lines.append(normalized)
        if cleaned_lines:
            return " ".join(cleaned_lines)[:120]
        return f"{title}相关资料。" if title else "知识节点摘要。"

    @staticmethod
    def _normalize_display_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            normalized = value.strip()
            if not normalized:
                return ""
            if normalized in {"[]", "{}", "null", "None"}:
                return ""
            parsed_value: Any = None
            parsed = False
            if normalized[:1] in {"[", "{", "("}:
                try:
                    parsed_value = json.loads(normalized)
                    parsed = True
                except json.JSONDecodeError:
                    try:
                        parsed_value = ast.literal_eval(normalized)
                        parsed = True
                    except (SyntaxError, ValueError):
                        parsed = False
            if parsed:
                normalized_sequence = normalize_text_sequence(parsed_value)
                if isinstance(parsed_value, (list, tuple, set)) and not normalized_sequence:
                    return ""
            return normalized
        normalized = str(value).strip()
        return "" if normalized in {"[]", "{}", "null", "None"} else normalized

    @staticmethod
    def _markdown_section(title: str, body: str | None) -> str:
        normalized_body = BrandPathRenderingMixin._normalize_display_text(body)
        if not normalized_body:
            return ""
        return f"## {title}\n\n{normalized_body}"

    @staticmethod
    def _markdown_list(items: list[str]) -> str:
        normalized = [str(item).strip() for item in items if str(item).strip()]
        return "\n".join(f"- {item}" for item in normalized)

    @staticmethod
    def _markdown_links(items: list[str]) -> str:
        normalized = [str(item).strip() for item in items if str(item).strip()]
        return "\n".join(f"- [{item}]({item})" for item in normalized)

    @staticmethod
    def _markdown_key_values(items: list[tuple[str, Any]]) -> str:
        lines: list[str] = []
        for label, value in items:
            normalized = BrandPathRenderingMixin._normalize_display_text(value)
            if not normalized:
                continue
            lines.append(f"- {label}：{normalized}")
        return "\n".join(lines)

    @classmethod
    def _render_entity_path_list(
        cls,
        entities: list[dict[str, Any]],
        *,
        entity_type_label: str,
    ) -> str:
        lines: list[str] = []
        for item in entities:
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            path = str(item.get("path") or "").strip()
            intro = str(item.get("intro") or "").strip()
            line = f"- {name}"
            details: list[str] = []
            if path:
                details.append(f"path：{path}")
            if intro:
                details.append(intro)
            if details:
                line = f"{line}（{'；'.join(details)}）"
            lines.append(line)
        if not lines:
            return ""
        return cls._join_sections(
            [
                f"以下为当前品牌可直接加载的{entity_type_label}节点：",
                "\n".join(lines),
            ]
        )

    @staticmethod
    def _join_sections(sections: list[str]) -> str:
        return "\n\n".join(section for section in sections if section.strip()).strip()

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

    @staticmethod
    def _normalize_markdown_text(markdown_text: str | None) -> str:
        return str(markdown_text or "").replace("\r\n", "\n").replace("\r", "\n").strip()

    @classmethod
    def _build_markdown_render_index(cls, markdown_text: str | None) -> _MarkdownRenderIndex | None:
        normalized_markdown = cls._normalize_markdown_text(markdown_text)
        if not normalized_markdown:
            return None
        return _MarkdownRenderIndex(
            markdown_text=normalized_markdown,
            lines=tuple(normalized_markdown.split("\n")),
            headings=tuple(cls._markdown_heading_spans(normalized_markdown)),
        )

    @staticmethod
    def _normalize_markdown_heading_title(title: str) -> str:
        normalized = str(title or "").replace("\u3000", " ").strip()
        normalized = re.sub(r"[*_`]+", "", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        normalized = re.sub(
            r"^(?:第?[一二三四五六七八九十百千万零〇\d]+(?:\.\d+)*[、.．:\s]*)+",
            "",
            normalized,
        ).strip()
        return re.sub(r"\s+", "", normalized)

    @classmethod
    def _markdown_heading_spans(
        cls,
        markdown_text: str,
    ) -> list[tuple[int, int, str]]:
        spans: list[tuple[int, int, str]] = []
        for line_index, line in enumerate(str(markdown_text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")):
            heading_match = cls._MARKDOWN_HEADING_RE.match(line.strip())
            if not heading_match:
                continue
            spans.append(
                (
                    line_index,
                    len(heading_match.group("level")),
                    cls._normalize_markdown_heading_title(heading_match.group("title")),
                )
            )
        return spans

    @classmethod
    def _find_markdown_section_range(
        cls,
        *,
        headings: list[tuple[int, int, str]],
        lines: list[str],
        titles: list[str],
        start_heading_index: int = 0,
        minimum_level: int = 1,
        limit_line_index: int | None = None,
    ) -> tuple[int, int] | None:
        normalized_titles = [cls._normalize_markdown_heading_title(title) for title in titles if str(title or "").strip()]
        if not normalized_titles:
            return None
        if limit_line_index is None:
            limit_line_index = len(lines)
        target_title = normalized_titles[0]
        for heading_index in range(start_heading_index, len(headings)):
            line_index, level, heading_title = headings[heading_index]
            if line_index >= limit_line_index:
                break
            if level < minimum_level or heading_title != target_title:
                continue
            section_end = limit_line_index
            for next_heading_index in range(heading_index + 1, len(headings)):
                next_line_index, next_level, _ = headings[next_heading_index]
                if next_line_index >= limit_line_index:
                    break
                if next_level <= level:
                    section_end = next_line_index
                    break
            if len(normalized_titles) == 1:
                return line_index, section_end
            nested_range = cls._find_markdown_section_range(
                headings=headings,
                lines=lines,
                titles=normalized_titles[1:],
                start_heading_index=heading_index + 1,
                minimum_level=level + 1,
                limit_line_index=section_end,
            )
            if nested_range is not None:
                return nested_range
        return None

    @classmethod
    def _extract_markdown_section_by_titles(cls, markdown_text: str, titles: list[str]) -> str | None:
        markdown_index = cls._build_markdown_render_index(markdown_text)
        if markdown_index is None:
            return None
        return cls._extract_markdown_section_by_titles_from_index(markdown_index, titles)

    @classmethod
    def _extract_markdown_section_by_titles_from_index(
        cls,
        markdown_index: _MarkdownRenderIndex,
        titles: list[str],
    ) -> str | None:
        section_range = cls._find_markdown_section_range(
            headings=list(markdown_index.headings),
            lines=list(markdown_index.lines),
            titles=titles,
        )
        if section_range is None:
            return None
        start_line, end_line = section_range
        return "\n".join(markdown_index.lines[start_line:end_line]).strip() or None

    @classmethod
    def _extract_named_markdown_bullet_block(cls, markdown_text: str, item_name: str) -> str | None:
        markdown_index = cls._build_markdown_render_index(markdown_text)
        if markdown_index is None:
            return None
        return cls._extract_named_markdown_bullet_block_from_index(markdown_index, item_name)

    @classmethod
    def _extract_named_markdown_bullet_block_from_index(
        cls,
        markdown_index: _MarkdownRenderIndex,
        item_name: str,
    ) -> str | None:
        normalized_item_name = cls._normalize_markdown_heading_title(item_name)
        if not normalized_item_name:
            return None
        captured_lines: list[str] = []
        capture_started = False

        for raw_line in markdown_index.lines:
            stripped_line = raw_line.strip()
            if not capture_started:
                title_match = cls._MARKDOWN_BOLD_BULLET_TITLE_RE.match(stripped_line)
                if title_match is None:
                    continue
                if cls._normalize_markdown_heading_title(title_match.group("title")) != normalized_item_name:
                    continue
                capture_started = True
                continue

            if cls._MARKDOWN_HEADING_RE.match(stripped_line):
                break
            if stripped_line.startswith("|"):
                break

            title_match = cls._MARKDOWN_BOLD_BULLET_TITLE_RE.match(stripped_line)
            field_match = cls._MARKDOWN_BOLD_BULLET_FIELD_RE.match(stripped_line)
            if title_match is not None and field_match is None:
                break

            captured_lines.append(raw_line.rstrip())

        normalized_lines = [line.rstrip() for line in captured_lines]
        content = "\n".join(normalized_lines).strip()
        if not content:
            return None
        return f"# {item_name}\n\n{content}"

    @staticmethod
    def _filter_markdown_section_by_keyword(section_markdown: str, keyword: str) -> str | None:
        normalized_keyword = str(keyword or "").strip()
        normalized_section = str(section_markdown or "").strip()
        if not normalized_section:
            return None
        if not normalized_keyword:
            return normalized_section

        lines = normalized_section.splitlines()
        if not lines:
            return None

        kept_lines: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped.startswith("- "):
                kept_lines.append(line)
                continue
            if normalized_keyword in line:
                kept_lines.append(line)

        if len(kept_lines) <= 1:
            return None
        return "\n".join(kept_lines).strip() or None

    @staticmethod
    def _path_leaf_title(path: str) -> str:
        normalized_path = str(path or "").strip()
        if not normalized_path:
            return ""
        return normalized_path.split("/", 1)[-1].strip()
