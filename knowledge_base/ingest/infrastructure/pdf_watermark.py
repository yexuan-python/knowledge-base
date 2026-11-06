from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


WATERMARK_KEYWORDS = (
    "watermark",
    "confidential",
    "internal use only",
    "sample",
    "draft",
    "do not copy",
    "机密",
    "保密",
    "内部资料",
    "内部使用",
    "样张",
    "测试",
    "水印",
    "请勿外传",
    "作废",
    "仅供",
    "未授权",
)

CONTACT_MARKERS = (
    "@",
    "http://",
    "https://",
    "www.",
    "微信",
    "vx",
    "tel",
    "电话",
    "手机",
    "邮箱",
)

SINGLE_PAGE_WATERMARK_TOKENS = (
    "仅",
    "供",
    "仅供",
    "使用",
    "使",
    "用",
    "有效",
    "有效期",
    "期至",
    "至",
    "复印",
    "复",
    "印",
    "无效",
    "无",
    "效",
    "再次",
    "再",
    "次",
    "geo",
    "g",
    "e",
    "o",
)


@dataclass(frozen=True)
class PdfWatermarkCandidate:
    phrase: str
    page_hits: int
    keyword_hit: bool


@dataclass(frozen=True)
class PdfWatermarkReport:
    suspected: bool
    total_pages: int
    candidates: tuple[PdfWatermarkCandidate, ...]
    reason: str = ""


@dataclass(frozen=True)
class WatermarkResidueReport:
    has_residue: bool
    matched_phrases: tuple[str, ...]
    reason: str = ""


def _normalize_phrase(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").strip().lower()
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _looks_like_candidate(phrase: str) -> bool:
    normalized = _normalize_phrase(phrase)
    if not normalized:
        return False
    if len(normalized) < 2 or len(normalized) > 40:
        return False
    if len(normalized.split()) > 8:
        return False
    if re.fullmatch(r"[\W_]+", normalized):
        return False
    if re.fullmatch(r"[\d\s\\-_/.:]+", normalized):
        return False
    return True


def _contains_keyword(phrase: str) -> bool:
    normalized = _normalize_phrase(phrase)
    return any(keyword in normalized for keyword in WATERMARK_KEYWORDS)


def _looks_like_sensitive_repeated_phrase(phrase: str) -> bool:
    normalized = _normalize_phrase(phrase)
    if not normalized:
        return False
    if any(marker in normalized for marker in CONTACT_MARKERS):
        return True
    digits = sum(char.isdigit() for char in normalized)
    if digits >= 6:
        return True
    return False


def _extract_page_phrases(path: Path) -> list[set[str]]:
    import pdfplumber

    pages: list[set[str]] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text(layout=True) or page.extract_text() or ""
            phrases: set[str] = set()
            for raw_line in page_text.splitlines():
                line = _normalize_phrase(raw_line)
                if _looks_like_candidate(line):
                    phrases.add(line)
            pages.append(phrases)
    return pages


def _extract_page_words(path: Path) -> list[list[str]]:
    import pdfplumber

    pages: list[list[str]] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            words = page.extract_words(use_text_flow=True, keep_blank_chars=False)
            page_words: list[str] = []
            for word in words:
                text = _normalize_phrase(str(word.get("text", "")))
                if not text:
                    continue
                page_words.append(text)
            pages.append(page_words)
    return pages


def _is_single_page_repeated_watermark(page_words: Sequence[str]) -> bool:
    if len(page_words) < 80:
        return False

    counts = Counter(page_words)
    repeated_token_hits = 0
    repeated_keyword_groups = 0

    for token in SINGLE_PAGE_WATERMARK_TOKENS:
        hit_count = counts.get(token, 0)
        if hit_count >= 6:
            repeated_token_hits += 1
        if hit_count >= 10:
            repeated_keyword_groups += 1

    has_repeated_letters = all(counts.get(letter, 0) >= 6 for letter in ("g", "e", "o"))
    has_repeated_usage = counts.get("仅", 0) >= 6 and counts.get("供", 0) >= 6 and (
        counts.get("使", 0) >= 6 or counts.get("使用", 0) >= 6
    )
    has_repeated_copy_ban = (
        counts.get("再", 0) >= 6
        and counts.get("次", 0) >= 6
        and counts.get("复", 0) >= 6
        and counts.get("印", 0) >= 6
        and counts.get("无", 0) >= 6
        and counts.get("效", 0) >= 6
    )

    return bool(
        repeated_token_hits >= 8
        or repeated_keyword_groups >= 4
        or (has_repeated_letters and has_repeated_usage)
        or has_repeated_copy_ban
    )


def analyze_pdf_watermark_phrases(page_phrases: Sequence[Iterable[str]]) -> PdfWatermarkReport:
    total_pages = len(page_phrases)
    if total_pages <= 0:
        return PdfWatermarkReport(suspected=False, total_pages=0, candidates=(), reason="empty_pdf")

    page_threshold = max(2, math.ceil(total_pages * 0.3))
    strong_threshold = max(2, math.ceil(total_pages * 0.6))

    counts: dict[str, int] = {}
    for phrases in page_phrases:
        unique_phrases = {_normalize_phrase(phrase) for phrase in phrases if _looks_like_candidate(phrase)}
        for phrase in unique_phrases:
            counts[phrase] = counts.get(phrase, 0) + 1

    candidates: list[PdfWatermarkCandidate] = []
    for phrase, page_hits in counts.items():
        keyword_hit = _contains_keyword(phrase)
        sensitive_hit = _looks_like_sensitive_repeated_phrase(phrase)
        if (
            (keyword_hit and page_hits >= page_threshold)
            or (sensitive_hit and page_hits >= strong_threshold)
        ):
            candidates.append(
                PdfWatermarkCandidate(
                    phrase=phrase,
                    page_hits=page_hits,
                    keyword_hit=keyword_hit,
                )
            )

    candidates.sort(key=lambda item: (-item.page_hits, -int(item.keyword_hit), len(item.phrase), item.phrase))
    suspected = bool(candidates)
    reason = "repeated_watermark_like_phrases" if suspected else "no_repeated_watermark_like_phrases"
    return PdfWatermarkReport(
        suspected=suspected,
        total_pages=total_pages,
        candidates=tuple(candidates),
        reason=reason,
    )


def detect_pdf_watermark_suspect(path: Path) -> PdfWatermarkReport:
    page_phrases = _extract_page_phrases(path)
    report = analyze_pdf_watermark_phrases(page_phrases)
    if report.suspected:
        return report

    if report.total_pages == 1:
        page_words = _extract_page_words(path)
        if page_words and _is_single_page_repeated_watermark(page_words[0]):
            return PdfWatermarkReport(
                suspected=True,
                total_pages=1,
                candidates=(),
                reason="single_page_repeated_watermark_tokens",
            )

    return report


def detect_markdown_watermark_residue(
    markdown_text: str,
    candidates: Sequence[str],
) -> WatermarkResidueReport:
    normalized_text = _normalize_phrase(markdown_text)
    matched_phrases = tuple(
        candidate
        for candidate in candidates
        if candidate and _normalize_phrase(candidate) in normalized_text
    )
    return WatermarkResidueReport(
        has_residue=bool(matched_phrases),
        matched_phrases=matched_phrases,
        reason="watermark_candidate_still_present" if matched_phrases else "watermark_candidate_removed",
    )


def remove_markdown_watermark_residue(
    markdown_text: str,
    candidates: Sequence[str],
) -> str:
    cleaned = str(markdown_text or "")
    for candidate in candidates:
        normalized_candidate = str(candidate or "").strip()
        if not normalized_candidate:
            continue
        cleaned = cleaned.replace(normalized_candidate, "")
        cleaned = cleaned.replace(_normalize_phrase(normalized_candidate), "")
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()
