from __future__ import annotations

import json
import re
from typing import Any

from knowledge_base.shared.utils import (
    is_effective_empty_sequence,
    normalize_hotline_sequence,
    normalize_line_delimited_text_sequence,
    normalize_text_sequence,
    parse_jsonish_literal,
)


class AttachmentDraftFlowHelpersMixin:
    def _build_preview_field_labels(self, candidate_snapshot: dict[str, Any]) -> dict[str, str]:
        labels: dict[str, str] = {}

        def other_info_content_label(path: str) -> str | None:
            content_prefixes = ("other_info[].content[].", "other_info[].content.")
            if not path.startswith(content_prefixes):
                return None
            raw_key = path.rsplit(".", 1)[-1].replace("[]", "").strip()
            if not raw_key:
                return None
            if self._contains_cjk(raw_key):
                return raw_key
            normalized_key = "".join(
                char.lower() if char.isalnum() else "_"
                for char in raw_key
            ).strip("_")
            compact_key = normalized_key.replace("_", "")
            return (
                self._OTHER_INFO_CONTENT_FIELD_LABELS.get(normalized_key)
                or self._OTHER_INFO_CONTENT_FIELD_LABELS.get(compact_key)
                or "补充信息"
            )

        def add_path(path: str) -> None:
            if (
                (path == "other_info" or path.startswith("other_info.") or path.startswith("other_info[]"))
                and not path.startswith(("other_info[].content[].", "other_info[].content."))
            ):
                return
            label = self._PREVIEW_FIELD_LABELS.get(path) or other_info_content_label(path)
            if label is not None:
                labels[path] = label

        def visit(value: Any, path: str) -> None:
            if not path:
                return
            add_path(path)
            if isinstance(value, dict):
                for key, child in value.items():
                    child_path = f"{path}.{key}" if path else str(key)
                    visit(child, child_path)
                return
            if isinstance(value, list):
                item_path = f"{path}[]"
                for item in value:
                    if isinstance(item, dict):
                        visit(item, item_path)
                    elif item not in (None, "", [], {}):
                        add_path(path)

        if not isinstance(candidate_snapshot, dict):
            return labels
        for key, value in candidate_snapshot.items():
            visit(value, str(key))
        return labels

    @staticmethod
    def _normalize_optional_str(value: Any) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @staticmethod
    def _normalize_escaped_line_breaks(value: Any) -> str:
        return (
            str(value or "")
            .replace("\\r\\n", "\n")
            .replace("\\n", "\n")
            .replace("\\r", "\n")
        )

    @staticmethod
    def _normalize_string_list(value: Any) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in normalize_text_sequence(value):
            if item in seen:
                continue
            seen.add(item)
            normalized.append(item)
        return normalized

    @staticmethod
    def _normalize_customer_service_hotline_list(value: Any) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in normalize_hotline_sequence(value):
            if item in seen:
                continue
            seen.add(item)
            normalized.append(item)
        return normalized

    @classmethod
    def _normalize_jsonish_list(cls, value: Any) -> list[Any]:
        if value is None or is_effective_empty_sequence(value):
            return []
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return []
            parsed = parse_jsonish_literal(text)
            if isinstance(parsed, list):
                return cls._normalize_jsonish_list(parsed)
            if isinstance(parsed, dict):
                return [parsed]
            if parsed is not None and parsed != text:
                return cls._normalize_jsonish_list(parsed)
            return [text]
        if isinstance(value, list):
            normalized: list[Any] = []
            seen: set[str] = set()
            for item in value:
                for normalized_item in cls._normalize_jsonish_list(item):
                    if isinstance(normalized_item, str) and normalized_item.strip() in {"", "[]"}:
                        continue
                    try:
                        identity = json.dumps(normalized_item, ensure_ascii=False, sort_keys=True)
                    except Exception:
                        identity = str(normalized_item)
                    if identity in seen:
                        continue
                    seen.add(identity)
                    normalized.append(normalized_item)
            return normalized
        if isinstance(value, dict):
            return [value]
        normalized = str(value).strip()
        return [normalized] if normalized else []

    @staticmethod
    def _normalize_attachment_entries(value: Any) -> list[dict[str, str]]:
        if not isinstance(value, list):
            return []
        normalized: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for item in value:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            url = str(item.get("url") or item.get("source_url") or "").strip()
            if not name and not url:
                continue
            identity = (name, url)
            if identity in seen:
                continue
            seen.add(identity)
            normalized.append(
                {
                    "name": name,
                    "url": url,
                }
            )
        return normalized

    @staticmethod
    def _normalize_text_list_from_dicts(items: Any, field_name: str) -> list[str]:
        if not isinstance(items, list):
            return []
        normalized: list[str] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            text = str(item.get(field_name) or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            normalized.append(text)
        return normalized

    @staticmethod
    def _parse_json_value(raw: Any, default: Any) -> Any:
        if raw is None:
            return default
        if isinstance(raw, (dict, list)):
            return raw
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return default
            return parsed
        return default

    @staticmethod
    def _build_combined_markdown(
        *,
        brand_name: str,
        parsed_items: list[dict[str, Any]],
    ) -> str:
        sections: list[str] = []
        for item in parsed_items:
            if not isinstance(item, dict):
                continue
            if str(item.get("status") or "").strip() != "success":
                continue
            markdown_text = str(item.get("markdown_text") or "").strip()
            parsed_text = str(item.get("parsed_text") or "").strip()
            body = markdown_text or parsed_text
            if not body:
                continue
            sections.append(body)
        return "\n\n".join(sections).strip()

    @classmethod
    def _normalize_geo_cell_text(cls, value: Any) -> str:
        text = (
            cls._normalize_escaped_line_breaks(value)
            .replace("<br>", "\n")
            .replace("<br/>", "\n")
            .replace("<br />", "\n")
            .strip()
        )
        return "" if text.casefold() in cls._GEO_EMPTY_CELL_VALUES else text

    @classmethod
    def _split_markdown_row(cls, line: str) -> list[str]:
        if not line.strip().startswith("|"):
            return []
        stripped = line.strip().strip("|")
        cells = re.split(r"(?<!\\)\|", stripped)
        return [
            cls._normalize_geo_cell_text(cell.replace("\\|", "|").replace("\\\\", "\\"))
            for cell in cells
        ]

    @classmethod
    def _is_markdown_separator_row(cls, cells: list[str]) -> bool:
        if not cells:
            return False
        return all(bool(re.fullmatch(r":?-{3,}:?", cell.strip())) for cell in cells if cell.strip())

    @classmethod
    def _parse_markdown_table_rows(cls, markdown_text: str) -> list[list[str]]:
        lines = [line for line in str(markdown_text or "").splitlines() if line.strip()]
        table_lines = [line for line in lines if line.lstrip().startswith("|")]
        if len(table_lines) < 2:
            return []
        rows = [cls._split_markdown_row(line) for line in table_lines]
        rows = [row for row in rows if row]
        if len(rows) < 2 or not cls._is_markdown_separator_row(rows[1]):
            return []
        return [rows[0], *rows[2:]]

    @classmethod
    def _split_sheet_sections(cls, markdown_text: str) -> list[dict[str, str]]:
        normalized = str(markdown_text or "").strip()
        if not normalized:
            return []
        matches = list(re.finditer(r"(?m)^# Sheet:\s*(.+?)\s*$", normalized))
        if not matches:
            return []
        sections: list[dict[str, str]] = []
        for index, match in enumerate(matches):
            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
            raw_section = normalized[start:end].strip()
            body = raw_section.split("\n", 1)[1].strip() if "\n" in raw_section else ""
            sections.append(
                {
                    "title": cls._normalize_optional_str(match.group(1)) or "",
                    "body": body,
                    "raw": raw_section,
                }
            )
        return sections

    @classmethod
    def _normalize_geo_label(cls, value: Any) -> str:
        text = cls._normalize_optional_str(value) or ""
        text = re.sub(r"[（(][^)）]*[)）]", "", text)
        return re.sub(r"\s+", "", text).replace("：", ":").strip()

    @classmethod
    def _extract_urls_from_text(cls, value: Any) -> list[str]:
        text = cls._normalize_optional_str(cls._normalize_escaped_line_breaks(value)) or ""
        if not text:
            return []
        urls = re.findall(r"https?://[^\s)）>]+", text)
        normalized: list[str] = []
        seen: set[str] = set()
        for url in urls:
            cleaned = url.rstrip("，。；;,)")
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                normalized.append(cleaned)
        return normalized

    @classmethod
    def _split_text_values(cls, value: Any) -> list[str]:
        text = cls._normalize_optional_str(cls._normalize_escaped_line_breaks(value)) or ""
        if not text:
            return []
        parts = text.splitlines()
        normalized: list[str] = []
        seen: set[str] = set()
        for part in parts:
            cleaned = cls._normalize_geo_cell_text(part)
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            normalized.append(cleaned)
        return normalized

    @classmethod
    def _split_line_text_values(cls, value: Any) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        source_value = cls._normalize_escaped_line_breaks(value) if isinstance(value, str) else value
        for item in normalize_line_delimited_text_sequence(source_value):
            cleaned = cls._normalize_geo_cell_text(item)
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            normalized.append(cleaned)
        return normalized

    @classmethod
    def _append_unique_values(cls, target: list[str], values: list[str]) -> None:
        seen = {cls._normalize_optional_str(item) for item in target if cls._normalize_optional_str(item)}
        for value in values:
            cleaned = cls._normalize_optional_str(value)
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            target.append(cleaned)

    @classmethod
    def _join_row_details(cls, row: dict[str, str], excluded_headers: set[str]) -> str | None:
        parts: list[str] = []
        for header, value in row.items():
            if header in excluded_headers:
                continue
            cleaned = cls._normalize_geo_cell_text(value)
            if not cleaned:
                continue
            parts.append(f"{header}：{cleaned}")
        joined = "；".join(parts).strip()
        return joined or None

    @classmethod
    def _is_geo_sheet1_rows(cls, rows: list[list[str]]) -> bool:
        if not rows:
            return False
        header = [cls._normalize_geo_label(cell) for cell in rows[0]]
        return (
            len(header) >= 3
            and header[0] == "核心维度"
            and header[1] == "字段名称"
            and "具体内容" in header[2]
        )

    @classmethod
    def _maybe_promote_secondary_header_row(cls, rows: list[list[str]]) -> list[list[str]]:
        if len(rows) < 3:
            return rows
        second = rows[1]
        non_empty = sum(1 for cell in second if cls._normalize_geo_cell_text(cell))
        if non_empty < max(2, len(second) // 3):
            return rows
        if cls._normalize_geo_cell_text(second[0]) or cls._normalize_geo_cell_text(second[1]):
            return rows
        combined_header: list[str] = []
        for first, nested in zip(rows[0], second, strict=False):
            first_text = cls._normalize_geo_cell_text(first)
            nested_text = cls._normalize_geo_cell_text(nested)
            combined_header.append(
                f"{first_text} {nested_text}".strip() if first_text and nested_text else (nested_text or first_text)
            )
        return [combined_header, *rows[2:]]

    @classmethod
    def _table_header_identity(cls, headers: list[str], sheet_title: str) -> str | None:
        normalized_headers = [cls._normalize_geo_label(header) for header in headers]
        joined_headers = " ".join(normalized_headers).casefold()
        title = cls._normalize_geo_label(sheet_title).casefold()
        scores = {
            "products": sum(
                1 for keyword in ("产品", "sku", "配料", "成分", "规格", "营养", "原料")
                if keyword in joined_headers or keyword in title
            ),
            "authority_honors": sum(
                1 for keyword in ("荣誉", "奖项", "认证", "背书", "类目", "证明", "证书", "专利", "标准")
                if keyword in joined_headers or keyword in title
            ),
            "official_media_matrix": sum(
                1 for keyword in ("账号", "平台", "粉丝", "主页", "链接", "公众号", "抖音", "微博", "视频号")
                if keyword in joined_headers or keyword in title
            ),
            "official_malls": sum(
                1 for keyword in ("店铺", "商城", "旗舰店", "主营品类", "主营类目", "购买入口", "电商")
                if keyword in joined_headers or keyword in title
            ),
            "customers_cases": sum(
                1 for keyword in ("客户", "案例", "合作", "项目", "反馈")
                if keyword in joined_headers or keyword in title
            ),
            "management_team": sum(
                1 for keyword in ("姓名", "成员", "职务", "职位", "头衔", "简介", "履历")
                if keyword in joined_headers or keyword in title
            ),
            "competitors": sum(
                1 for keyword in ("竞品", "竞争对手", "对标", "对比维度", "差异化")
                if keyword in joined_headers or keyword in title
            ),
            "sensitive_topics": sum(
                1 for keyword in ("敏感", "禁忌", "极限词", "风险", "危机", "负面", "澄清")
                if keyword in joined_headers or keyword in title
            ),
        }
        best_type = max(scores, key=scores.get)
        return best_type if scores[best_type] >= 2 else None

    @classmethod
    def _find_matching_header(cls, row: dict[str, str], keywords: tuple[str, ...]) -> str | None:
        for header in row:
            normalized = cls._normalize_geo_label(header).casefold()
            if any(keyword.casefold() in normalized for keyword in keywords):
                return header
        return None

    @classmethod
    def _infer_media_platform(cls, field_name: str, content: str = "") -> str | None:
        combined = f"{field_name}\n{content}"
        for keyword in cls._MEDIA_PLATFORM_KEYWORDS:
            if keyword in combined:
                return keyword
        if "官方账号" in field_name:
            suffix = field_name.split("—", 1)[-1]
            suffix = suffix.split("-", 1)[-1] if suffix == field_name else suffix
            return cls._normalize_optional_str(suffix)
        return None

    @classmethod
    def _infer_media_platform_from_url(cls, url: str) -> str | None:
        candidate = str(url or "").strip().lower()
        if not candidate:
            return None
        for domain, platform in cls._MEDIA_PLATFORM_DOMAINS:
            if domain in candidate:
                return platform
        return None

    @classmethod
    def _is_placeholder_sheet1_field(cls, field_name: str, content: str) -> bool:
        normalized_field = cls._normalize_geo_label(field_name)
        normalized_content = cls._normalize_optional_str(content) or ""
        if not normalized_field or not normalized_content:
            return True
        if any(keyword in normalized_field for keyword in cls._GEO_PLACEHOLDER_FIELD_KEYWORDS):
            return True
        if normalized_field in {"字段名称", "具体内容"}:
            return True
        return False

    @classmethod
    def _extract_trailing_index(cls, value: str) -> str | None:
        candidate = cls._normalize_optional_str(value) or ""
        if not candidate:
            return None
        match = re.search(r"(\d+|[一二三四五六七八九十]+)\s*$", candidate)
        if not match:
            return None
        raw = match.group(1)
        if raw.isdigit():
            return raw
        if raw in cls._CHINESE_NUMERALS:
            return str(cls._CHINESE_NUMERALS.index(raw) + 1)
        return raw

    @classmethod
    def _extract_media_entries_from_sheet1(cls, field_name: str, content: str) -> list[dict[str, Any]]:
        normalized_content = cls._normalize_geo_cell_text(content)
        urls = cls._extract_urls_from_text(normalized_content)
        if not urls and not cls._infer_media_platform(field_name, normalized_content):
            return []
        non_url_lines = [
            line for line in (cls._normalize_geo_cell_text(part) for part in normalized_content.splitlines())
            if line and line not in urls
        ]
        account_name = non_url_lines[0] if non_url_lines else ""
        platform_from_field = cls._infer_media_platform(field_name, "")
        entries: list[dict[str, Any]] = []
        if len(urls) <= 1:
            platform_from_url = cls._infer_media_platform_from_url(urls[0]) if urls else None
            entries.append(
                {
                    "media_platform": platform_from_url or platform_from_field or cls._infer_media_platform(field_name, normalized_content) or "",
                    "account_name": account_name,
                    "account_id": "",
                    "is_official": "是",
                    "homepage_urls": urls,
                    "fans_count": "",
                    "content_focus": [],
                    "related_products": [],
                    "other_info": [],
                }
            )
            return entries
        for url in urls:
            platform = cls._infer_media_platform_from_url(url) or platform_from_field or cls._infer_media_platform(field_name, normalized_content) or ""
            entries.append(
                {
                    "media_platform": platform,
                    "account_name": account_name,
                    "account_id": "",
                    "is_official": "是",
                    "homepage_urls": [url],
                    "fans_count": "",
                    "content_focus": [],
                    "related_products": [],
                    "other_info": [],
                }
            )
        return entries

    @classmethod
    def _extract_sensitive_topic_buckets(cls, field_name: str, content: str) -> dict[str, list[str]]:
        buckets = {
            "sensitive_contents": [],
            "controversial_events": [],
            "forbidden_words": [],
            "negative_clarifications": [],
            "other_info": [],
        }
        normalized_field = cls._normalize_geo_label(field_name)
        lines = []
        for segment in str(content or "").splitlines():
            cleaned = cls._normalize_geo_cell_text(re.sub(r"^\s*\d+[、.．]?\s*", "", segment))
            if cleaned:
                lines.append(cleaned)
        if not lines and content:
            lines = cls._split_text_values(content)
        for line in lines:
            if any(keyword in normalized_field or keyword in line for keyword in ("极限词", "禁用词", "禁止表述", "敏感词")):
                buckets["forbidden_words"].append(line)
                continue
            if any(keyword in normalized_field or keyword in line for keyword in ("负面澄清", "统一口径", "回应口径")):
                buckets["negative_clarifications"].append(line)
                continue
            if any(keyword in normalized_field or keyword in line for keyword in ("争议", "危机", "负面事件", "血燕", "拉踩", "诋毁")):
                buckets["controversial_events"].append(line)
                continue
            buckets["sensitive_contents"].append(line)
        return buckets

    @classmethod
    def _should_capture_authority_honor(cls, dimension: str, field_name: str, content: str) -> bool:
        normalized_dimension = cls._normalize_geo_label(dimension)
        normalized_field = cls._normalize_geo_label(field_name)
        normalized_content = cls._normalize_optional_str(content) or ""
        if not normalized_field or not normalized_content:
            return False
        if normalized_field in cls._GENERIC_HONOR_SECTION_TITLES:
            return False
        if normalized_field in {"交付标准", "服务标准", "配送标准", "包装标准"}:
            return False
        if normalized_content.startswith("详见【") and normalized_field in cls._GENERIC_HONOR_SECTION_TITLES:
            return False
        keywords = ("荣誉", "奖项", "认证", "背书", "专利", "第一", "首家", "开创者", "上市", "标准牵头", "知识产权")
        return any(keyword in normalized_field for keyword in keywords) or any(keyword in normalized_dimension for keyword in keywords)

    @classmethod
    def _should_skip_other_info_field(cls, field_name: str, content: str) -> bool:
        normalized_field = cls._normalize_geo_label(field_name)
        normalized_content = cls._normalize_optional_str(content) or ""
        if not normalized_field or not normalized_content:
            return True
        if any(keyword in normalized_field for keyword in cls._GEO_PLACEHOLDER_FIELD_KEYWORDS):
            return True
        if normalized_field in cls._GENERIC_HONOR_SECTION_TITLES and normalized_content.startswith("详见【"):
            return True
        return False

    @classmethod
    def _split_brand_subject_and_name(cls, value: str) -> tuple[str | None, str | None]:
        text = cls._normalize_optional_str(value) or ""
        if not text:
            return None, None
        for separator in ("+", "＋", "|", "｜", "/", "／"):
            if separator not in text:
                continue
            parts = [part.strip() for part in text.split(separator) if part.strip()]
            if len(parts) >= 2:
                return parts[0], parts[-1]
        return None, text

    @classmethod
    def _extract_management_members_from_text(cls, value: str, *, source_section: str | None = None) -> list[dict[str, Any]]:
        members: list[dict[str, Any]] = []
        for line in str(value or "").splitlines():
            cleaned = cls._normalize_geo_cell_text(line)
            if not cleaned:
                continue
            name_match = re.search(r"([A-Za-z\u4e00-\u9fff·]{2,20})$", cleaned)
            if not name_match:
                members.append(
                    {
                        "name": cleaned,
                        "title": "",
                        "profile": "",
                        "source_section": source_section or "",
                    }
                )
                continue
            name = name_match.group(1).strip()
            title = cleaned[: name_match.start()].strip(" ：:,-")
            members.append(
                {
                    "name": name,
                    "title": title,
                    "profile": "",
                    "source_section": source_section or "",
                }
            )
        return members

    @staticmethod
    def _normalize_markdown_text(value: Any) -> str:
        return str(value or "").replace("\r\n", "\n").strip()

    @classmethod
    def _build_diff_field_label(cls, field_path: str) -> str:
        if not field_path:
            return ""
        parts = field_path.split(".")
        label_parts: list[str] = []
        for index, part in enumerate(parts):
            raw_prefix = part.split("[", 1)[0]
            if index > 0 and raw_prefix in cls._DIFF_LABEL_CONTAINER_SEGMENTS:
                continue
            translated = cls._DIFF_PATH_LABELS.get(raw_prefix, raw_prefix)
            if "[" in part:
                suffix = part[part.index("[") :]
                label_parts.append(f"{translated}{suffix}")
            else:
                label_parts.append(translated)
        return " / ".join(label_parts)

    @classmethod
    def _rewrite_list_item_diff_path(
        cls,
        field_path: str,
        *,
        section: str,
        container: str | None,
        aliases: dict[str, str],
    ) -> str:
        prefix = f"{section}["
        if not field_path.startswith(prefix):
            return field_path
        section_end = field_path.find("].")
        if section_end < 0:
            return field_path
        item_identity = field_path[len(section): section_end + 1]
        leaf_path = field_path[section_end + 2 :]
        aliased_leaf_path = aliases.get(leaf_path)
        if not aliased_leaf_path:
            return field_path
        if container:
            return f"{section}.{container}{item_identity}.{aliased_leaf_path}"
        return f"{section}{item_identity}.{aliased_leaf_path}"

    @classmethod
    def _build_external_diff_field_path(cls, field_path: str) -> str:
        if not field_path:
            return ""
        aliased_path = cls._DIFF_FIELD_PATH_ALIASES.get(field_path)
        if aliased_path:
            return aliased_path
        for section, container, aliases in (
            ("products", None, cls._PRODUCT_DIFF_FIELD_PATH_ALIASES),
            ("management_team", "members", cls._MANAGEMENT_TEAM_DIFF_FIELD_PATH_ALIASES),
            ("competitors", "competitors", cls._COMPETITOR_DIFF_FIELD_PATH_ALIASES),
            ("authority_honors", "honors", cls._AUTHORITY_HONOR_DIFF_FIELD_PATH_ALIASES),
            ("customers_cases", "cases", cls._CUSTOMER_CASE_DIFF_FIELD_PATH_ALIASES),
        ):
            rewritten_path = cls._rewrite_list_item_diff_path(
                field_path,
                section=section,
                container=container,
                aliases=aliases,
            )
            if rewritten_path != field_path:
                return rewritten_path
        return field_path

    @classmethod
    def _build_entity_scope_map(
        cls,
        items: Any,
        *,
        name_field: str,
        alias_field: str | None = None,
    ) -> tuple[set[str], dict[str, str]]:
        canonical_names: set[str] = set()
        alias_map: dict[str, str] = {}
        if not isinstance(items, list):
            return canonical_names, alias_map

        for item in items:
            if not isinstance(item, dict):
                continue
            canonical_name = cls._normalize_optional_str(item.get(name_field))
            if not canonical_name:
                continue
            canonical_names.add(canonical_name)
            alias_map[canonical_name.casefold()] = canonical_name
            if not alias_field:
                continue
            aliases = cls._normalize_string_list(item.get(alias_field))
            for alias in aliases:
                normalized_alias = alias.strip()
                if normalized_alias:
                    alias_map[normalized_alias.casefold()] = canonical_name
        return canonical_names, alias_map

    @classmethod
    def _has_meaningful_value(cls, value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            text = value.strip()
            if not text or not cls._normalize_jsonish_list(text):
                return False
            return True
        if isinstance(value, list):
            return bool(value)
        if isinstance(value, dict):
            return bool(value)
        return True

    @classmethod
    def _flatten_non_empty_fields(
        cls,
        value: Any,
        *,
        prefix: str,
        list_item_keys: dict[str, str],
    ) -> dict[str, Any]:
        flattened: dict[str, Any] = {}
        if value is None:
            return flattened

        if isinstance(value, dict):
            for key, nested in value.items():
                if key == "attachments":
                    continue
                next_prefix = f"{prefix}.{key}" if prefix else str(key)
                flattened.update(
                    cls._flatten_non_empty_fields(
                        nested,
                        prefix=next_prefix,
                        list_item_keys=list_item_keys,
                    )
                )
            return flattened

        if isinstance(value, list):
            if not value:
                return flattened
            if all(not isinstance(item, dict) for item in value):
                normalized_list = [str(item).strip() for item in value if str(item).strip()]
                if normalized_list and prefix:
                    flattened[prefix] = normalized_list
                return flattened

            list_key = list_item_keys.get(prefix)
            if not list_key:
                if prefix:
                    flattened[prefix] = value
                return flattened
            for item in value:
                if not isinstance(item, dict):
                    continue
                item_key_value = str(item.get(list_key) or "").strip()
                if not item_key_value:
                    continue
                item_prefix = f"{prefix}[{item_key_value}]"
                flattened.update(
                    cls._flatten_non_empty_fields(
                        item,
                        prefix=item_prefix,
                        list_item_keys=list_item_keys,
                    )
                )
            return flattened

        if prefix and cls._has_meaningful_value(value):
            flattened[prefix] = value
        return flattened
