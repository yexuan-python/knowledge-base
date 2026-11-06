from __future__ import annotations

import asyncio
import logging
from functools import partial
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from knowledge_base.ingest.application.remote_download import download_remote_content_to_path

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


class AttachmentDraftFlowStorageMixin:
    @staticmethod
    def _build_confirmed_knowledge_object_key(*, brand_name: str, filename: str) -> str:
        category_part = _sanitize_oss_segment(brand_name, default="uncategorized")
        safe_name = _sanitize_oss_segment(Path(filename).name, default="confirmed-knowledge.md")
        return apply_oss_test_prefix(f"{category_part}/confirmed_knowledge/{safe_name}")

    async def _download_attachment(self, *, url: str, destination: Path) -> None:
        await download_remote_content_to_path(
            url=url,
            name=destination.name,
            log_context="attachment_preview",
            destination=destination,
        )

    async def _upload_bytes_with_retry(
        self,
        *,
        data: bytes,
        object_key: str,
        content_type: str,
    ) -> str | None:
        return await asyncio.to_thread(
            self._deps.oss_client.upload_bytes,
            data,
            object_key,
            content_type,
        )

    async def _upload_file_with_retry(
        self,
        *,
        file_path: Path,
        object_key: str,
    ) -> str | None:
        return await asyncio.to_thread(
            self._deps.oss_client.upload_file,
            str(file_path),
            object_key,
        )

    async def _parse_attachment(
        self,
        *,
        brand_name: str,
        name: str,
        url: str,
        destination: Path,
        semaphore: asyncio.Semaphore,
    ) -> dict[str, Any]:
        async with semaphore:
            started_at = perf_counter()
            download_elapsed = 0.0
            parse_elapsed = 0.0
            try:
                logger.info(
                    "Attachment preview item started brand_name=%s attachment=%s local_name=%s",
                    brand_name,
                    name,
                    destination.name,
                )
                download_started_at = perf_counter()
                await self._download_attachment(url=url, destination=destination)
                download_elapsed = perf_counter() - download_started_at
                logger.info(
                    "Attachment preview item downloaded brand_name=%s attachment=%s "
                    "bytes=%s download_elapsed=%.2fs",
                    brand_name,
                    name,
                    destination.stat().st_size if destination.exists() else 0,
                    download_elapsed,
                )
                parse_started_at = perf_counter()
                logger.info(
                    "Attachment preview item parsing started brand_name=%s attachment=%s suffix=%s",
                    brand_name,
                    name,
                    destination.suffix.lower(),
                )
                parsed = await asyncio.to_thread(
                    partial(
                        self._deps.parser.parse_path,
                        destination,
                        source_name=name,
                    )
                )
                parse_elapsed = perf_counter() - parse_started_at
                logger.info(
                    "Attachment preview item parsed brand_name=%s attachment=%s backend=%s "
                    "source_type=%s download_elapsed=%.2fs parse_elapsed=%.2fs total_elapsed=%.2fs "
                    "text_chars=%s markdown_chars=%s",
                    brand_name,
                    name,
                    parsed.metadata.get("parser_backend"),
                    parsed.source_type,
                    download_elapsed,
                    parse_elapsed,
                    perf_counter() - started_at,
                    len(parsed.text or ""),
                    len(parsed.markdown_text or ""),
                )
                return {
                    "name": name,
                    "url": url,
                    "status": "success",
                    "source_type": parsed.source_type,
                    "parser_backend": parsed.metadata.get("parser_backend"),
                    "parsed_text": parsed.text,
                    "markdown_text": parsed.markdown_text,
                }
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "Attachment preview parse failed brand_name=%s attachment=%s "
                    "download_elapsed=%.2fs parse_elapsed=%.2fs total_elapsed=%.2fs",
                    brand_name,
                    name,
                    download_elapsed,
                    parse_elapsed,
                    perf_counter() - started_at,
                )
                return {
                    "name": name,
                    "url": url,
                    "status": "failed",
                    "error_message": str(exc),
                }
            finally:
                destination.unlink(missing_ok=True)

    async def _ingest_preview_markdown_documents(
        self,
        *,
        draft_id: str,
        brand_name: str,
        draft_attachments: list[dict[str, Any]],
        review_id: str | None,
    ) -> list[dict[str, Any]]:
        confirmed_dir = self._confirmed_markdown_dir(draft_id)
        confirmed_dir.mkdir(parents=True, exist_ok=True)
        ingested_documents: list[dict[str, Any]] = []
        for index, item in enumerate(draft_attachments, start=1):
            if str(item.get("status") or "").strip() != "success":
                continue
            original_name = str(item.get("name") or "").strip() or f"attachment-{index}"
            markdown_text = self._normalize_markdown_text(item.get("markdown_text") or item.get("parsed_text"))
            if not markdown_text:
                raise ValueError(f"附件缺少可入库的 Markdown 内容: {original_name}")

            staged_filename = f"{Path(original_name).name}.md"
            staged_path = confirmed_dir / f"{index:03d}-{Path(staged_filename).name}"
            staged_path.write_text(markdown_text, encoding="utf-8")

            metadata = {
                "category": brand_name,
                "knowledge_source": "online_confirmed",
                "knowledge_flow": "attachments_confirm",
                "knowledge_version": "confirmed",
                "attachment_name": original_name,
                "source_url": str(item.get("url") or "").strip() or None,
                "draft_id": draft_id,
                "review_id": review_id,
            }
            if callable(self._deps.ingest_staged_file):
                document = await self._deps.ingest_staged_file(
                    staged_path=staged_path,
                    filename=staged_filename,
                    metadata=metadata,
                    chunk_size=None,
                    chunk_overlap=None,
                    content_type="text/markdown; charset=utf-8",
                )
            elif callable(self._deps.ingest_text_document):
                document = await self._deps.ingest_text_document(
                    text=markdown_text,
                    title=staged_filename,
                    metadata=metadata,
                    chunk_size=None,
                    chunk_overlap=None,
                    document_id=f"confirmed_{uuid4().hex}",
                )
            else:
                raise RuntimeError("neither ingest_staged_file nor ingest_text_document dependency is initialized")
            ingested_documents.append(
                {
                    "name": original_name,
                    "source_url": str(item.get("url") or "").strip() or None,
                    "document_id": document.document_id,
                    "fulltext_key": document.metadata.get("fulltext_key"),
                    "fulltext_url": (
                        self._deps.oss_client.build_object_url(str(document.metadata.get("fulltext_key")))
                        if self._deps.oss_client.enabled and document.metadata.get("fulltext_key")
                        else None
                    ),
                }
            )
        return ingested_documents

    @staticmethod
    def _render_final_markdown(
        *,
        brand_name: str,
        confirmed_text: str,
        attachments: list[dict[str, Any]],
    ) -> str:
        normalized_brand_name = str(brand_name or "").strip()
        normalized_text = str(confirmed_text or "").replace("\r\n", "\n").strip()
        if not normalized_brand_name or not normalized_text:
            return ""

        lines: list[str] = [
            f"# {normalized_brand_name} 品牌知识库",
            "",
            "## 附件确认内容",
            "",
        ]

        for raw_line in normalized_text.split("\n"):
            line = raw_line.strip()
            if not line:
                lines.append("")
                continue
            if line.startswith(("#", "-", "*", ">", "|")):
                lines.append(raw_line.rstrip())
                continue
            if line[:1].isdigit() and ". " in line:
                lines.append(raw_line.rstrip())
                continue

            separator = "：" if "：" in line else ":" if ":" in line else None
            if separator:
                key, value = line.split(separator, 1)
                normalized_key = key.strip()
                normalized_value = value.strip()
                if normalized_key and normalized_value:
                    lines.append(f"- **{normalized_key}**：{normalized_value}")
                    continue
            lines.append(line)

        normalized_attachments = []
        for item in attachments:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            url = str(item.get("url") or "").strip()
            if name or url:
                normalized_attachments.append((name, url))
        if normalized_attachments:
            lines.extend(["", "## 附件来源", ""])
            for name, url in normalized_attachments:
                lines.append(f"- {name}：{url}")

        return "\n".join(lines).strip()

    def _render_snapshot_markdown(
        self,
        *,
        brand_name: str,
        snapshot: dict[str, Any],
    ) -> str:
        normalized_snapshot = self._normalize_snapshot_for_merge(snapshot)
        lines: list[str] = [f"# {brand_name} 附件确认知识", ""]
        for section_key, section_value in normalized_snapshot.items():
            if section_key == "attachments" or not self._has_meaningful_payload(section_value):
                continue
            section_label = self._DIFF_PATH_LABELS.get(section_key, section_key)
            lines.extend([f"## {section_label}", ""])
            lines.extend(self._render_markdown_value(section_value))
            lines.append("")
        return "\n".join(lines).strip()

    def _render_markdown_value(self, value: Any, *, indent: int = 0) -> list[str]:
        prefix = "  " * indent
        if isinstance(value, dict):
            lines: list[str] = []
            for key, item in value.items():
                if not self._has_meaningful_payload(item):
                    continue
                if isinstance(item, (dict, list)):
                    lines.append(f"{prefix}- **{key}**：")
                    lines.extend(self._render_markdown_value(item, indent=indent + 1))
                else:
                    lines.append(f"{prefix}- **{key}**：{item}")
            return lines
        if isinstance(value, list):
            lines: list[str] = []
            for item in value:
                if not self._has_meaningful_payload(item):
                    continue
                if isinstance(item, dict):
                    name = self._normalize_optional_str(
                        item.get("name") or item.get("title") or item.get("case_name") or item.get("customer_name")
                    )
                    if name:
                        lines.append(f"{prefix}- **{name}**")
                    lines.extend(self._render_markdown_value(item, indent=indent + 1))
                elif isinstance(item, list):
                    lines.extend(self._render_markdown_value(item, indent=indent + 1))
                else:
                    lines.append(f"{prefix}- {item}")
            return lines
        return [f"{prefix}- {value}"] if self._has_meaningful_payload(value) else []
