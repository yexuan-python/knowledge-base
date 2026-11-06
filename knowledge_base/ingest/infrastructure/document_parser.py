from __future__ import annotations

import csv
import json
import logging
import re
import unicodedata
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import xlrd
from markitdown import MarkItDown
from openpyxl import load_workbook

from knowledge_base.ingest.infrastructure.docmind_client import DocMindClient, DocMindError
from knowledge_base.ingest.infrastructure.pdf_watermark import detect_pdf_watermark_suspect
from knowledge_base.infrastructure.settings import Settings


LOCAL_SUPPORTED_EXTENSIONS = {
    ".csv",
    ".docx",
    ".jpeg",
    ".jpg",
    ".json",
    ".md",
    ".pdf",
    ".png",
    ".txt",
    ".xls",
    ".xlsx",
}

DOCMIND_FALLBACK_EXTENSIONS = {
    ".bmp",
    ".doc",
    ".docx",
    ".epub",
    ".gif",
    ".htm",
    ".html",
    ".jpeg",
    ".jpg",
    ".mobi",
    ".pdf",
    ".png",
    ".ppt",
    ".pptx",
    ".rtf",
    ".txt",
    ".webp",
    ".xls",
    ".xlsx",
}

SUPPORTED_EXTENSIONS = LOCAL_SUPPORTED_EXTENSIONS | DOCMIND_FALLBACK_EXTENSIONS
DOCMIND_PREFERRED_EXTENSIONS = {
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".webp",
}

logger = logging.getLogger(__name__)


class UnsupportedFileTypeError(ValueError):
    """Raised when a file extension is not supported by the parser."""


class NoTextExtractedError(ValueError):
    """Raised when a file can be parsed but yields no usable textual content."""


class WatermarkedDocumentError(ValueError):
    """Raised when a document still contains watermark residue after parsing."""

    def __init__(self, message: str, *, preserve_registry: bool = False) -> None:
        super().__init__(message)
        self.preserve_registry = preserve_registry


@dataclass(frozen=True)
class ParsedDocument:
    text: str
    markdown_text: str
    source_name: str
    source_type: str
    metadata: dict[str, Any]


def _strip_markdown_images(markdown_text: str) -> str:
    text = markdown_text
    text = re.sub(r"!\[[^\]]*]\([^)]*\)", "", text)
    text = re.sub(r"!\[[^\]]*]\[[^\]]*]", "", text)
    text = re.sub(r"<img\b[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^\[[^\]]+]:\s*\S+\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def _read_csv_rows(path: Path) -> list[list[str]]:
    with path.open("r", encoding="utf-8", newline="") as file:
        reader = csv.reader(file)
        return [[cell.strip() for cell in row] for row in reader]


def _rows_to_plain_text(rows: list[list[str]]) -> str:
    rendered_rows = [", ".join(cell for cell in row if cell) for row in rows]
    return "\n".join(row for row in rendered_rows if row.strip())


def _normalize_table_rows(rows: list[list[str]]) -> list[list[str]]:
    normalized = [[str(cell).strip() for cell in row] for row in rows]
    normalized = [row for row in normalized if any(cell for cell in row)]
    if not normalized:
        return []

    width = max(len(row) for row in normalized)
    return [row + [""] * (width - len(row)) for row in normalized]


def _escape_markdown_cell(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")


def _rows_to_markdown_table(rows: list[list[str]]) -> str:
    normalized = _normalize_table_rows(rows)
    if not normalized:
        return ""

    header = normalized[0]
    body = normalized[1:]
    header_line = "| " + " | ".join(_escape_markdown_cell(cell) or " " for cell in header) + " |"
    separator_line = "| " + " | ".join("---" for _ in header) + " |"
    body_lines = [
        "| " + " | ".join(_escape_markdown_cell(cell) or " " for cell in row) + " |"
        for row in body
    ]
    return "\n".join([header_line, separator_line, *body_lines])


def _read_csv(path: Path) -> tuple[str, str]:
    rows = _read_csv_rows(path)
    text = _rows_to_plain_text(rows)
    markdown = _rows_to_markdown_table(rows) or text
    return text, markdown


def _cell_to_text(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else ""


def _find_geo_content_column(cells: list[str]) -> int | None:
    if len(cells) < 3 or cells[0] != "核心维度" or cells[1] != "字段名称":
        return None
    for index, cell in enumerate(cells[2:], start=2):
        if cell == "具体内容" or cell.startswith("填写具体内容"):
            return index
    return None


def _extract_geo_sheet1_rows(sheet: Any) -> list[list[str]] | None:
    extracted_rows: list[list[str]] = []
    content_column: int | None = None

    for row in sheet.iter_rows(values_only=True):
        cells = [_cell_to_text(value) for value in row]
        header_content_column = _find_geo_content_column(cells)
        if header_content_column is not None:
            content_column = header_content_column
            extracted_rows.append(["核心维度", "字段名称", cells[header_content_column]])
            continue

        if content_column is None:
            continue

        dimension = cells[0] if len(cells) > 0 else ""
        field_name = cells[1] if len(cells) > 1 else ""
        content = cells[content_column] if content_column < len(cells) else ""
        if not field_name:
            continue
        extracted_rows.append([dimension, field_name, content])

    return extracted_rows if extracted_rows else None


def _read_xlsx_sheet_rows(sheet: Any, *, normalize_geo_sheet1: bool = False) -> list[list[str]]:
    if normalize_geo_sheet1:
        geo_rows = _extract_geo_sheet1_rows(sheet)
        if geo_rows is not None:
            return geo_rows

    rows: list[list[str]] = []
    for row in sheet.iter_rows(values_only=True):
        cells = [_cell_to_text(value) for value in row]
        if any(cells):
            rows.append(cells)
    return rows


def _read_xlsx(path: Path) -> tuple[str, str]:
    workbook = load_workbook(path, data_only=True)
    text_sections: list[str] = []
    markdown_sections: list[str] = []
    for sheet_index, sheet in enumerate(workbook.worksheets):
        rows = _read_xlsx_sheet_rows(sheet, normalize_geo_sheet1=sheet_index == 0)
        if rows:
            text_sections.append(f"# Sheet: {sheet.title}\n" + _rows_to_plain_text(rows))
            markdown_table = _rows_to_markdown_table(rows)
            markdown_body = markdown_table or _rows_to_plain_text(rows)
            markdown_sections.append(f"# Sheet: {sheet.title}\n\n{markdown_body}")
    return "\n\n".join(text_sections), "\n\n".join(markdown_sections)


def _read_xls(path: Path) -> tuple[str, str]:
    workbook = xlrd.open_workbook(path)
    text_sections: list[str] = []
    markdown_sections: list[str] = []
    for sheet in workbook.sheets():
        rows: list[list[str]] = []
        for row_index in range(sheet.nrows):
            values = [str(cell).strip() for cell in sheet.row_values(row_index)]
            if any(value for value in values):
                rows.append(values)
        if rows:
            text_sections.append(f"# Sheet: {sheet.name}\n" + _rows_to_plain_text(rows))
            markdown_table = _rows_to_markdown_table(rows)
            markdown_body = markdown_table or _rows_to_plain_text(rows)
            markdown_sections.append(f"# Sheet: {sheet.name}\n\n{markdown_body}")
    return "\n\n".join(text_sections), "\n\n".join(markdown_sections)


def _read_json(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class DocumentParser:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._converter = MarkItDown()
        self._docmind = DocMindClient(self._settings)

    def parse_path(
        self,
        path: Path,
        source_name: str | None = None,
        *,
        force_docmind: bool = False,
        source_url: str | None = None,
    ) -> ParsedDocument:
        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            logger.warning("Document parsing rejected path=%s suffix=%s", path, suffix or "<none>")
            raise UnsupportedFileTypeError(
                f"Unsupported file type: {suffix or '<none>'}. "
                f"Supported types: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
            )

        watermark_report = None
        if suffix == ".pdf":
            with suppress(Exception):
                watermark_report = detect_pdf_watermark_suspect(path)
                if (
                    watermark_report.suspected
                    and self._docmind.enabled
                    and self._docmind.supports(suffix)
                ):
                    force_docmind = True

        local_error: Exception | None = None
        text = ""
        markdown_text = ""

        should_try_local = (
            suffix in LOCAL_SUPPORTED_EXTENSIONS
            and not self.prefers_document_pipeline(suffix)
            and not force_docmind
        )
        if should_try_local:
            try:
                text, markdown_text = self._parse_locally(path, suffix)
            except Exception as exc:
                local_error = exc
                logger.warning("Local document parsing failed path=%s error=%s", path, exc, exc_info=True)

        cleaned = self._clean_text(text)
        if cleaned:
            cleaned_markdown = self._clean_markdown(_strip_markdown_images(markdown_text))
            if not cleaned_markdown:
                cleaned_markdown = cleaned

            effective_source_name = source_name or path.name
            metadata: dict[str, Any] = {
                "original_filename": effective_source_name,
                "parser_backend": "local",
            }
            if watermark_report is not None:
                metadata["pdf_watermark_suspected"] = watermark_report.suspected
                metadata["pdf_watermark_reason"] = watermark_report.reason
                metadata["pdf_watermark_candidates"] = [candidate.phrase for candidate in watermark_report.candidates]

            return ParsedDocument(
                text=cleaned,
                markdown_text=cleaned_markdown,
                source_name=effective_source_name,
                source_type=suffix.lstrip("."),
                metadata=metadata,
            )

        docmind_error: Exception | None = None
        if self._docmind.enabled and self._docmind.supports(suffix):
            try:
                docmind_result = self._docmind.parse_file(path, source_url=source_url)
                cleaned = self._clean_text(docmind_result.text)
                cleaned_markdown = self._clean_markdown(_strip_markdown_images(docmind_result.markdown_text))
                if cleaned and not cleaned_markdown:
                    cleaned_markdown = cleaned
                if cleaned:
                    effective_source_name = source_name or path.name
                    metadata = {
                        "original_filename": effective_source_name,
                        "parser_backend": "docmind",
                        "docmind_task_id": docmind_result.task_id,
                    }
                    if watermark_report is not None:
                        metadata["pdf_watermark_suspected"] = watermark_report.suspected
                        metadata["pdf_watermark_reason"] = watermark_report.reason
                        metadata["pdf_watermark_candidates"] = [candidate.phrase for candidate in watermark_report.candidates]
                    logger.info("DocMind fallback succeeded path=%s task_id=%s", path, docmind_result.task_id)
                    return ParsedDocument(
                        text=cleaned,
                        markdown_text=cleaned_markdown,
                        source_name=effective_source_name,
                        source_type=suffix.lstrip("."),
                        metadata=metadata,
                    )
                docmind_error = DocMindError(f"DocMind returned empty content for {path.name}")
            except Exception as exc:
                docmind_error = exc
                logger.warning("DocMind fallback unavailable path=%s error=%s", path, exc)

        logger.warning("Document parsing produced empty content path=%s", path)
        if docmind_error is not None:
            raise NoTextExtractedError(
                f"No textual content could be extracted from {path.name}. "
                f"DocMind fallback also failed: {docmind_error}"
            ) from docmind_error
        if local_error is not None:
            raise NoTextExtractedError(
                f"No textual content could be extracted from {path.name}. "
                f"Local parser error: {local_error}"
            ) from local_error
        docmind_hint = ""
        if suffix in DOCMIND_FALLBACK_EXTENSIONS and not self._docmind.enabled:
            docmind_hint = " DocMind fallback is not configured."
        raise NoTextExtractedError(f"No textual content could be extracted from {path.name}.{docmind_hint}")

    def prefers_document_pipeline(self, suffix: str) -> bool:
        normalized = suffix.lower()
        return (
            normalized in DOCMIND_PREFERRED_EXTENSIONS
            and self._docmind.enabled
            and self._docmind.supports(normalized)
        )

    def _parse_locally(self, path: Path, suffix: str) -> tuple[str, str]:
        if suffix == ".pdf":
            try:
                import pdfplumber
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "Local PDF parsing dependency is missing: pdfplumber. "
                    "Install pdfplumber or enable DocMind fallback."
                ) from exc
            with pdfplumber.open(path) as pdf:
                text_parts = []
                markdown_parts = []
                for page in pdf.pages:
                    tables = page.extract_tables()
                    for table in tables:
                        if table:
                            normalized_rows = [
                                [str(cell).strip() if cell is not None else "" for cell in row]
                                for row in table
                            ]
                            markdown_table = _rows_to_markdown_table(normalized_rows)
                            plain_table = _rows_to_plain_text(normalized_rows)
                            if plain_table:
                                text_parts.append(plain_table)
                            if markdown_table:
                                markdown_parts.append(markdown_table)
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
                        markdown_parts.append(page_text)
            text = "\n\n".join(text_parts)
            markdown_text = "\n\n".join(markdown_parts)
            if not text.strip() or not markdown_text.strip():
                with suppress(Exception):
                    result = self._converter.convert(str(path))
                    fallback_text = getattr(result, "text_content", "")
                    if not text.strip():
                        text = fallback_text
                    if not markdown_text.strip():
                        markdown_text = fallback_text
            return text, markdown_text

        if suffix == ".csv":
            return _read_csv(path)
        if suffix == ".xlsx":
            return _read_xlsx(path)
        if suffix == ".xls":
            return _read_xls(path)
        if suffix == ".json":
            text = _read_json(path)
            try:
                parsed_json = json.loads(text)
                markdown_text = "```json\n" + json.dumps(parsed_json, ensure_ascii=False, indent=2) + "\n```"
            except json.JSONDecodeError:
                markdown_text = "```json\n" + text + "\n```"
            return text, markdown_text
        if suffix in {".md", ".txt"}:
            text = _read_json(path)
            return text, text

        result = self._converter.convert(str(path))
        text = getattr(result, "text_content", "")
        return text, text

    @staticmethod
    def _clean_text(text: str) -> str:
        if text.startswith("\ufeff"):
            text = text[1:]

        text = unicodedata.normalize("NFKC", text)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
        text = re.sub(r"[ \t]+", " ", text)

        lines = text.split("\n")
        stripped_lines = [line.strip() for line in lines]
        non_empty_lines = []
        last_was_empty = False
        for line in stripped_lines:
            if line == "":
                if not last_was_empty:
                    non_empty_lines.append(line)
                    last_was_empty = True
            else:
                non_empty_lines.append(line)
                last_was_empty = False
        cleaned = "\n".join(non_empty_lines)
        cleaned = cleaned.strip()
        cleaned = re.sub(r"[\u200b\u200c\u200d\u2060\uFEFF]", "", cleaned)
        return cleaned

    @staticmethod
    def _clean_markdown(text: str) -> str:
        if text.startswith("\ufeff"):
            text = text[1:]

        text = unicodedata.normalize("NFKC", text)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
        text = re.sub(r"[\u200b\u200c\u200d\u2060\uFEFF]", "", text)
        text = "\n".join(line.rstrip() for line in text.split("\n"))
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
