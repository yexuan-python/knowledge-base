from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

from knowledge_base.shared.utils import build_fulltext_object_key, build_original_object_key


class DocumentAttachmentAssetProcessor:
    def __init__(self, *, dependencies: Any) -> None:
        self._deps = dependencies

    async def process_document_attachment_asset_file(
        self,
        *,
        task_id: str,
        file_id: int,
        filename: str,
        temporary_path: Path,
        source_url: str | None,
        brand_code: str,
        brand_name: str,
        resolved_content_type: str,
        resolved_file_hash: str,
        resolved_file_size: int,
        converted_version: int,
    ) -> dict[str, Any]:
        oss_client = self._deps.oss_client
        attachment_assets = self._deps.attachment_assets
        if oss_client is None or not getattr(oss_client, "enabled", False):
            raise ValueError("OSS 未启用，无法上传附件")
        if attachment_assets is None:
            raise ValueError("brand_attachment_assets 未初始化")

        upload_document_id = f"attachment_{uuid4().hex}"
        original_object_key = build_original_object_key(
            category=brand_name,
            subcategory=None,
            filename=filename,
            document_id=upload_document_id,
            converted_version=converted_version,
        )
        uploaded_original_key = await asyncio.to_thread(
            oss_client.upload_file,
            str(temporary_path),
            original_object_key,
            resolved_content_type,
        )
        if not uploaded_original_key:
            raise ValueError(f"附件原文上传 OSS 失败: {filename}")
        original_oss_url = oss_client.build_object_url(uploaded_original_key)

        suffix = Path(filename).suffix.lower()
        if suffix in {".md", ".txt"}:
            parsed_markdown = await asyncio.to_thread(temporary_path.read_text, encoding="utf-8")
            parsed_source_type = suffix.lstrip(".") or "text"
        else:
            if self._deps.parser is None:
                raise ValueError("parser 未初始化，无法解析附件 Markdown")
            parsed = await asyncio.to_thread(
                self._deps.parser.parse_path,
                temporary_path,
                filename,
                source_url=source_url,
            )
            parsed_markdown = str(getattr(parsed, "markdown_text", "") or getattr(parsed, "text", "") or "").strip()
            parsed_source_type = str(
                getattr(parsed, "source_type", "") or suffix.lstrip(".") or "text"
            ).strip() or "text"

        parsed_markdown = str(parsed_markdown or "").strip()
        if not parsed_markdown:
            raise ValueError(f"无法解析出有效 Markdown：{filename}")

        fulltext_key = build_fulltext_object_key(
            category=brand_name,
            subcategory=None,
            filename=filename,
            document_id=upload_document_id,
            converted_version=converted_version,
        )
        uploaded_fulltext_key = await asyncio.to_thread(
            oss_client.upload_bytes,
            parsed_markdown.encode("utf-8"),
            fulltext_key,
            "text/markdown; charset=utf-8",
        )
        if not uploaded_fulltext_key:
            raise ValueError(f"附件解析 Markdown 上传 OSS 失败: {filename}")
        fulltext_url = oss_client.build_object_url(uploaded_fulltext_key)

        asset_id = attachment_assets.create_asset(
            brand_code=brand_code,
            brand_name=brand_name,
            upload_task_id=task_id,
            upload_task_file_id=file_id,
            original_filename=filename,
            content_type=resolved_content_type,
            parsed_source_type=parsed_source_type,
            parsed_markdown=parsed_markdown,
            converted_version=converted_version,
            fulltext_key=uploaded_fulltext_key,
            fulltext_url=fulltext_url,
            file_size=resolved_file_size,
            file_hash=resolved_file_hash,
            oss_key=uploaded_original_key,
            oss_url=original_oss_url,
            source_url=source_url,
        )
        return {
            "asset_id": asset_id,
            "oss_key": uploaded_original_key,
            "oss_url": original_oss_url,
            "fulltext_key": uploaded_fulltext_key,
            "fulltext_url": fulltext_url,
            "file_hash": resolved_file_hash,
            "file_size": resolved_file_size,
            "content_type": resolved_content_type,
            "converted_version": converted_version,
            "parsed_source_type": parsed_source_type,
            "source_type": "attachment",
        }
