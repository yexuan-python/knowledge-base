from __future__ import annotations

import re
from typing import Any


class AttachmentDraftSnapshotOtherInfoMixin:
    def _normalize_other_info_for_merge(self, value: Any) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        if isinstance(value, dict):
            iterable = [{"title": key, "content": item} for key, item in value.items()]
        elif isinstance(value, list):
            iterable = value
        else:
            return []

        seen: dict[str, int] = {}
        for item in iterable:
            if not isinstance(item, dict):
                continue
            title = self._normalize_other_info_title(item.get("title") or item.get("key") or item.get("name"))
            raw_value = item.get("content") if "content" in item else item.get("value")
            if not title or not self._has_meaningful_payload(raw_value):
                continue
            if title == self.ATTACHMENT_PRODUCTS_OTHER_INFO_TITLE:
                normalized_content = self._normalize_products_for_merge(
                    raw_value if isinstance(raw_value, list) else [raw_value]
                )
            else:
                normalized_content = self._normalize_other_info_value(raw_value)
            if not self._has_meaningful_payload(normalized_content):
                continue
            normalized_entry = {
                "title": title,
                "content": normalized_content,
            }
            identity = title.casefold()
            if identity in seen and title == self._OTHER_INFO_GENERIC_TITLE:
                suffix_index = 2
                while True:
                    title = f"{self._OTHER_INFO_GENERIC_TITLE}{self._other_info_suffix(suffix_index)}"
                    identity = title.casefold()
                    if identity not in seen:
                        normalized_entry["title"] = title
                        break
                    suffix_index += 1
            if identity in seen:
                entries[seen[identity]] = normalized_entry
            else:
                seen[identity] = len(entries)
                entries.append(normalized_entry)
        return entries

    def _normalize_other_info_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            return "\n".join(self._flatten_other_info_texts(value))
        if isinstance(value, dict):
            return "\n".join(self._flatten_other_info_texts(value))
        return value

    @classmethod
    def _is_other_info_placeholder_text(cls, value: Any) -> bool:
        text = cls._normalize_optional_str(value)
        if not text:
            return True
        return text in {
            "信息标题",
            "信息内容",
            "其他信息",
            "其他信息二",
            "title",
            "content",
            "key",
            "value",
        }

    @classmethod
    def _flatten_other_info_texts(cls, value: Any) -> list[str]:
        texts: list[str] = []
        seen: set[str] = set()

        def add_text(item: Any) -> None:
            text = cls._normalize_optional_str(item)
            if not text or cls._is_other_info_placeholder_text(text) or text in seen:
                return
            seen.add(text)
            texts.append(text)

        def visit(item: Any) -> None:
            if item is None:
                return
            if isinstance(item, str):
                add_text(item)
                return
            if isinstance(item, (int, float, bool)):
                add_text(item)
                return
            if isinstance(item, list):
                for child in item:
                    visit(child)
                return
            if isinstance(item, dict):
                raw_title = item.get("title") or item.get("key") or item.get("name")
                raw_content = item.get("content") if "content" in item else item.get("value")
                if raw_content is not None:
                    nested_before = len(texts)
                    visit(raw_content)
                    if len(texts) == nested_before and not cls._is_other_info_placeholder_text(raw_title):
                        add_text(raw_title)
                    return
                for key, child in item.items():
                    nested_texts = cls._flatten_other_info_texts(child)
                    normalized_key = cls._normalize_optional_str(key)
                    if normalized_key and not cls._is_other_info_placeholder_text(normalized_key):
                        for nested_text in nested_texts:
                            add_text(f"{normalized_key}：{nested_text}")
                    else:
                        for nested_text in nested_texts:
                            add_text(nested_text)
                return
            add_text(item)

        visit(value)
        return texts

    def _merge_other_info_entries(self, current: Any, candidate: Any) -> list[dict[str, Any]]:
        merged = self._normalize_other_info_for_merge(current)
        index_map = {
            str(item.get("title") or "").strip().casefold(): index
            for index, item in enumerate(merged)
            if str(item.get("title") or "").strip()
        }
        for item in self._normalize_other_info_for_merge(candidate):
            title = str(item.get("title") or "").strip()
            identity = title.casefold()
            if identity in index_map:
                merged[index_map[identity]] = item
            else:
                index_map[identity] = len(merged)
                merged.append(item)
        return merged

    @staticmethod
    def _other_info_title(item: dict[str, Any]) -> str:
        return str(item.get("title") or "").strip()

    @staticmethod
    def _contains_cjk(value: str) -> bool:
        return any(
            ("\u3400" <= char <= "\u4dbf")
            or ("\u4e00" <= char <= "\u9fff")
            or ("\uf900" <= char <= "\ufaff")
            for char in value
        )

    @classmethod
    def _normalize_other_info_title(cls, value: Any) -> str | None:
        title = cls._normalize_optional_str(value)
        if not title:
            return None
        title = cls._trim_template_title_annotations(title)
        if cls._contains_cjk(title):
            return title
        normalized_key = "".join(
            char.lower() if char.isalnum() else "_"
            for char in title
        ).strip("_")
        compact_key = normalized_key.replace("_", "")
        return (
            cls._OTHER_INFO_TITLE_TRANSLATIONS.get(normalized_key)
            or cls._OTHER_INFO_TITLE_TRANSLATIONS.get(compact_key)
            or cls._OTHER_INFO_GENERIC_TITLE
        )

    @classmethod
    def _other_info_suffix(cls, index: int) -> str:
        if 1 <= index <= len(cls._CHINESE_NUMERALS):
            return cls._CHINESE_NUMERALS[index - 1]
        return "十" + cls._CHINESE_NUMERALS[(index - 11) % len(cls._CHINESE_NUMERALS)]

    @classmethod
    def _comparison_texts(cls, value: Any) -> set[str]:
        if value is None:
            return set()
        if isinstance(value, str):
            text = value.strip()
            return {text} if text else set()
        if isinstance(value, (list, tuple, set)):
            texts: set[str] = set()
            for item in value:
                texts.update(cls._comparison_texts(item))
            return texts
        if isinstance(value, dict):
            texts: set[str] = set()
            for item in value.values():
                texts.update(cls._comparison_texts(item))
            return texts
        text = str(value).strip()
        return {text} if text else set()

    def _standard_field_values_by_label(self, snapshot: dict[str, Any]) -> dict[str, set[str]]:
        values_by_label: dict[str, set[str]] = {}

        def add_value(path: str, value: Any) -> None:
            if not path or path == "other_info" or path.startswith("other_info."):
                return
            label = self._PREVIEW_FIELD_LABELS.get(path)
            if not label:
                return
            texts = self._comparison_texts(value)
            if texts:
                values_by_label.setdefault(label, set()).update(texts)

        def visit(value: Any, path: str) -> None:
            if path == "other_info" or path.startswith("other_info."):
                return
            if isinstance(value, dict):
                for key, child in value.items():
                    visit(child, f"{path}.{key}" if path else str(key))
                return
            if isinstance(value, list):
                if all(not isinstance(item, dict) for item in value):
                    add_value(path, value)
                    return
                for item in value:
                    if isinstance(item, dict):
                        visit(item, f"{path}[]")
                return
            add_value(path, value)

        if isinstance(snapshot, dict):
            for key, value in snapshot.items():
                visit(value, str(key))
        return values_by_label

    def _is_standard_field_duplicate_other_info(
        self,
        *,
        snapshot: dict[str, Any],
        item: dict[str, Any],
        standard_values_by_label: dict[str, set[str]] | None = None,
    ) -> bool:
        title = self._other_info_title(item)
        if not title:
            return False
        values_by_label = standard_values_by_label or self._standard_field_values_by_label(snapshot)
        standard_values = values_by_label.get(title)
        if not standard_values:
            return False
        content_values = self._comparison_texts(item.get("content"))
        return bool(content_values and content_values.issubset(standard_values))

    def _sanitize_candidate_other_info(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(snapshot, dict):
            return {}
        entries = self._normalize_other_info_for_merge(snapshot.get("other_info"))
        if not entries:
            sanitized = dict(snapshot)
            sanitized.pop("other_info", None)
            return sanitized

        values_by_label = self._standard_field_values_by_label(snapshot)
        filtered = [
            item for item in entries
            if not self._is_standard_field_duplicate_other_info(
                snapshot=snapshot,
                item=item,
                standard_values_by_label=values_by_label,
            )
        ]

        sanitized = dict(snapshot)
        if filtered:
            sanitized["other_info"] = filtered
        else:
            sanitized.pop("other_info", None)
        return sanitized

    @classmethod
    def _is_reference_placeholder_text(cls, value: Any) -> bool:
        text = cls._normalize_optional_str(value) or ""
        if not text:
            return True
        normalized = re.sub(r"\s+", "", text)
        return bool(
            re.fullmatch(r"详见[「【\[].+[」】\]]", normalized)
            or re.fullmatch(r"见[「【\[].+[」】\]]", normalized)
        )

    @classmethod
    def _clean_metadata_prefixes(cls, value: Any) -> str:
        text = cls._normalize_optional_str(value) or ""
        if not text:
            return ""
        cleaned_lines: list[str] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            line = re.sub(r"^(出处/证明|链接)\s*[：:]\s*", "", line)
            line = re.sub(r"^\*\s*(备注|来源|查询网站|查询站)\s*[：:]\s*", "", line)
            cleaned_lines.append(line.strip())
        return "\n".join(line for line in cleaned_lines if line).strip()

    @classmethod
    def _remove_reference_placeholder_lines(cls, value: Any) -> str:
        text = cls._normalize_optional_str(value) or ""
        if not text:
            return ""
        kept_lines = [
            line.strip()
            for line in text.splitlines()
            if line.strip() and not cls._is_reference_placeholder_text(line)
        ]
        return "\n".join(kept_lines).strip()

    @classmethod
    def _normalize_claim_block(cls, value: Any) -> str:
        text = cls._remove_reference_placeholder_lines(value)
        if not text:
            return ""
        lines = [
            cls._normalize_geo_cell_text(re.sub(r"^\s*\d+[、.．]\s*", "", raw_line))
            for raw_line in text.splitlines()
        ]
        lines = [line for line in lines if line]
        if not lines:
            return ""
        return "，".join(lines)

    @classmethod
    def _claim_canonical_text(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        replacements = {
            "十年": "10年",
            "七年": "7年",
            "六年": "6年",
            "五年": "5年",
            "四年": "4年",
            "三年": "3年",
            "两年": "2年",
            "二年": "2年",
            "一年": "1年",
        }
        for source, target in replacements.items():
            text = text.replace(source, target)
        text = text.replace("（", "(").replace("）", ")")
        return re.sub(r"[\s,，;；:：。.!！?？\"'“”‘’]+", "", text)

    @classmethod
    def _extract_claim_segments(cls, value: Any) -> list[str]:
        text = cls._remove_reference_placeholder_lines(value)
        if not text:
            return []
        normalized: list[str] = []
        seen: set[str] = set()
        for raw_line in text.splitlines():
            line = cls._normalize_geo_cell_text(re.sub(r"^\s*\d+[、.．]\s*", "", raw_line))
            if not line:
                continue
            parts = [line]
            for part in parts:
                cleaned = re.sub(r"\s+", "", part).strip()
                if not cleaned:
                    continue
                canonical = cls._claim_canonical_text(cleaned)
                if not canonical or canonical in seen:
                    continue
                seen.add(canonical)
                normalized.append(cleaned)
        return normalized

    @classmethod
    def _compact_claim_list(cls, values: list[str]) -> list[str]:
        flattened: list[str] = []
        seen_canonical: set[str] = set()
        for value in values:
            for segment in cls._extract_claim_segments(value):
                canonical = cls._claim_canonical_text(segment)
                if not canonical or canonical in seen_canonical:
                    continue
                seen_canonical.add(canonical)
                flattened.append(segment)

        if not flattened:
            return []

        kept: list[str] = []
        kept_canonical: list[str] = []
        for segment in sorted(flattened, key=len, reverse=True):
            canonical = cls._claim_canonical_text(segment)
            if any(canonical != existing and canonical in existing for existing in kept_canonical):
                continue
            kept.append(segment)
            kept_canonical.append(canonical)

        ordered_kept = [segment for segment in flattened if segment in set(kept)]
        summary = "；".join(ordered_kept).strip("；")
        return [summary] if summary else []

    @classmethod
    def _trim_template_title_annotations(cls, value: str) -> str:
        title = str(value or "").strip()
        if not title:
            return ""
        return re.sub(
            r"[（(]\s*(?:可以是\s*)?(?:excel|xlsx|表格|链接|url|附件)[^)）]*[)）]\s*$",
            "",
            title,
            flags=re.IGNORECASE,
        ).strip()

    @classmethod
    def _is_resource_distribution_entry(cls, title: Any, content: Any) -> bool:
        normalized_title = cls._normalize_optional_str(title) or ""
        normalized_content = cls._normalize_optional_str(content) or ""
        if not normalized_content:
            return False
        lowered_content = normalized_content.casefold()
        content_hit = any(keyword.casefold() in lowered_content for keyword in cls._OTHER_INFO_RESOURCE_CONTENT_KEYWORDS)
        if content_hit:
            return True
        if not normalized_title:
            return False
        lowered_title = normalized_title.casefold()
        return any(keyword.casefold() in lowered_title for keyword in cls._OTHER_INFO_RESOURCE_TITLE_KEYWORDS) and bool(
            cls._extract_urls_from_text(normalized_content)
        )

    def _build_media_account_merge_key(self, item: dict[str, Any]) -> str:
        homepage_urls = self._normalize_string_list(item.get("homepage_urls"))
        primary_url = homepage_urls[0] if homepage_urls else ""
        return "|".join(
            part for part in (
                self._normalize_optional_str(item.get("media_platform")),
                self._normalize_optional_str(item.get("account_name")),
                self._normalize_optional_str(item.get("account_id")),
                primary_url,
            ) if part
        )

    def _refine_preview_candidate_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        normalized = self._normalize_snapshot_for_merge(snapshot)
        basic_info = dict(normalized.get("basic_info") or {}) if isinstance(normalized.get("basic_info"), dict) else {}
        other_info_entries = self._normalize_other_info_for_merge(normalized.get("other_info"))
        competitors = self._normalize_competitors_for_merge(normalized.get("competitors"))
        authority_honors = self._normalize_authority_honors_for_merge(normalized.get("authority_honors"))
        for field_name in ("customer_service_hotline", "positioning", "advantages", "mission", "vision"):
            cleaned_values = [
                cleaned
                for cleaned in (
                    self._remove_reference_placeholder_lines(item)
                    for item in self._normalize_string_list(basic_info.get(field_name))
                )
                if cleaned
            ]
            if cleaned_values:
                basic_info[field_name] = cleaned_values
            else:
                basic_info.pop(field_name, None)
        if authority_honors:
            for item in authority_honors:
                item["description"] = self._clean_metadata_prefixes(item.get("description"))

        competitor_strengths: list[str] = []
        competitor_diffs: list[str] = []
        retained_other_info: list[dict[str, Any]] = []

        for entry in other_info_entries:
            title = self._other_info_title(entry)
            content = self._normalize_other_info_value(entry.get("content"))
            text_content = (
                str(content or "").strip()
                if not isinstance(content, list)
                else "\n".join(str(item).strip() for item in content if str(item).strip())
            )
            normalized_title = self._normalize_geo_label(title)
            if not text_content:
                continue
            if normalized_title.startswith("主张与证据"):
                normalized_claim = self._normalize_claim_block(text_content)
                if not normalized_claim:
                    continue
                self._append_unique_values(competitor_strengths, [normalized_claim])
                continue
            if title in self._OTHER_INFO_COMPETITOR_ADVANTAGE_TITLES:
                normalized_claim = self._normalize_claim_block(text_content)
                if normalized_claim:
                    self._append_unique_values(competitor_strengths, [normalized_claim])
                continue
            if title in self._OTHER_INFO_COMPETITOR_DIFF_TITLES:
                normalized_claim = self._normalize_claim_block(text_content)
                if normalized_claim:
                    self._append_unique_values(competitor_diffs, [normalized_claim])
                continue
            if title in {"选择品牌类", "价格/套餐", "销售希望多宣传点"} and self._is_reference_placeholder_text(text_content):
                continue
            if title in {"售后/质保", "计价模型"}:
                continue
            if self._is_resource_distribution_entry(title, text_content):
                continue
            if self._is_reference_placeholder_text(text_content) and normalized_title in {"主张与证据", "选择品牌类", "销售希望多宣传点"}:
                continue
            retained_other_info.append({"title": title, "content": content})

        if competitors and (competitor_strengths or competitor_diffs):
            enriched_competitors: list[dict[str, Any]] = []
            for item in competitors:
                merged_item = dict(item)
                merged_item["strengths"] = (
                    self._compact_claim_list(competitor_strengths)
                    if competitor_strengths else self._compact_claim_list(item.get("strengths"))
                )
                merged_item["differentiated_positioning"] = (
                    self._compact_claim_list(competitor_diffs)
                    if competitor_diffs else self._compact_claim_list(item.get("differentiated_positioning"))
                )
                enriched_competitors.append(merged_item)
            competitors = enriched_competitors

        refined_snapshot = {
            **normalized,
            "basic_info": basic_info,
            "competitors": competitors,
            "authority_honors": authority_honors,
            "other_info": retained_other_info,
        }
        return self._sanitize_candidate_other_info(self._prune_empty_payload(refined_snapshot))

    def _extract_other_info_text_by_titles(self, other_info: Any, titles: set[str]) -> str | None:
        normalized_titles = {title.casefold() for title in titles}
        for item in self._normalize_other_info_for_merge(other_info):
            if self._other_info_title(item).casefold() not in normalized_titles:
                continue
            content = item.get("content")
            if isinstance(content, list):
                text = "；".join(str(value).strip() for value in content if str(value).strip())
            else:
                text = str(content or "").strip()
            if text:
                return text
        return None

    def _exclude_other_info_titles(self, other_info: Any, titles: set[str]) -> list[dict[str, Any]]:
        normalized_titles = {title.casefold() for title in titles}
        return [
            item for item in self._normalize_other_info_for_merge(other_info)
            if self._other_info_title(item).casefold() not in normalized_titles
        ]

    def _prune_empty_payload(self, value: Any) -> Any:
        if isinstance(value, dict):
            pruned: dict[str, Any] = {}
            for key, item in value.items():
                normalized_item = self._prune_empty_payload(item)
                if self._has_meaningful_payload(normalized_item):
                    pruned[key] = normalized_item
            return pruned
        if isinstance(value, list):
            pruned_list = [self._prune_empty_payload(item) for item in value]
            return [item for item in pruned_list if self._has_meaningful_payload(item)]
        if isinstance(value, str):
            return value.strip()
        return value
