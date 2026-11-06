from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from knowledge_base.shared.utils import parse_metadata_json


logger = logging.getLogger(__name__)


class AttachmentConflictSourcesMixin:
    def _knowledge_snapshot_service_proxy(self) -> Any:
        return SimpleNamespace(
            _brands=self._deps.brands,
            _brand_products=self._deps.brand_products,
            _brand_knowledge=self._deps.brand_knowledge,
            _settings=self._deps.settings,
            _tianyancha_client=self._deps.tianyancha_client,
        )

    @staticmethod
    def _build_snapshot_attachments(source_documents: Any) -> list[dict[str, Any]]:
        if not isinstance(source_documents, list):
            return []
        attachments: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for item in source_documents:
            if not isinstance(item, dict):
                continue
            name = str(item.get("original_filename") or item.get("source_name") or "").strip()
            source_url = str(item.get("source_url") or "").strip()
            subcategory = str(item.get("subcategory") or "").strip()
            dedupe_key = (name, source_url, subcategory)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            attachments.append(
                {
                    "name": name,
                    "source_url": source_url or None,
                    "subcategory": subcategory or None,
                    "type": str(item.get("source_type") or item.get("source_role") or "").strip() or None,
                }
            )
        return attachments

    async def _parse_attachment_asset_source(
        self,
        *,
        asset_row: dict[str, Any],
        subcategory: str | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        filename = str(asset_row.get("original_filename") or "").strip() or f"asset-{asset_row.get('id')}"
        parsed_markdown = self._normalize_markdown_text(asset_row.get("parsed_markdown"))
        parsed_source_type = str(asset_row.get("parsed_source_type") or "").strip() or None
        if parsed_markdown:
            source_type = parsed_source_type or Path(filename).suffix.lstrip(".") or "text"
            asset_id = int(asset_row.get("id") or 0)
            source_document = {
                "document_id": f"asset_{asset_id}",
                "asset_id": asset_id,
                "original_filename": filename,
                "source_type": source_type,
                "fulltext_key": asset_row.get("fulltext_key"),
                "source_url": asset_row.get("source_url"),
                "oss_url": asset_row.get("oss_url"),
                "subcategory": subcategory,
                "source_role": "attachment_asset",
                "markdown_text": parsed_markdown,
            }
            markdown_source = {
                "source_name": filename,
                "subcategory": subcategory,
                "source_role": "attachment_asset",
                "markdown_text": parsed_markdown,
            }
            return source_document, markdown_source

        fulltext_key = str(asset_row.get("fulltext_key") or "").strip()
        if fulltext_key:
            if self._deps.oss_client is None or not getattr(self._deps.oss_client, "enabled", False):
                raise ValueError("OSS 未启用，无法读取附件 converted Markdown")
            fulltext_data = await asyncio.to_thread(self._deps.oss_client.get_object, fulltext_key)
            markdown_text = self._normalize_markdown_text(
                fulltext_data.decode("utf-8") if fulltext_data else ""
            )
            if markdown_text:
                asset_id = int(asset_row.get("id") or 0)
                source_type = parsed_source_type or "markdown"
                if self._deps.attachment_assets is not None and asset_row.get("id") is not None:
                    self._deps.attachment_assets.update_parsed_content(
                        asset_id=int(asset_row["id"]),
                        parsed_source_type=source_type,
                        parsed_markdown=markdown_text,
                        converted_version=int(asset_row.get("converted_version") or 0) or None,
                        fulltext_key=fulltext_key,
                        fulltext_url=str(asset_row.get("fulltext_url") or "").strip() or None,
                    )
                source_document = {
                    "document_id": f"asset_{asset_id}",
                    "asset_id": asset_id,
                    "original_filename": filename,
                    "source_type": source_type,
                    "fulltext_key": fulltext_key,
                    "source_url": asset_row.get("source_url"),
                    "oss_url": asset_row.get("oss_url"),
                    "subcategory": subcategory,
                    "source_role": "attachment_asset",
                    "markdown_text": markdown_text,
                }
                markdown_source = {
                    "source_name": filename,
                    "subcategory": subcategory,
                    "source_role": "attachment_asset",
                    "markdown_text": markdown_text,
                }
                return source_document, markdown_source

        oss_key = str(asset_row.get("oss_key") or "").strip()
        if self._deps.oss_client is None or not getattr(self._deps.oss_client, "enabled", False):
            raise ValueError("OSS 未启用，无法读取附件资产")
        if not oss_key:
            raise ValueError(f"附件资产缺少 oss_key：{filename}")
        suffix = Path(filename).suffix.lower()
        temp_path = await asyncio.to_thread(
            self._deps.oss_client.download_object_to_temp_file,
            oss_key,
            suffix=suffix or ".tmp",
        )
        if temp_path is None:
            raise ValueError(f"无法从 OSS 读取附件资产：{filename}")

        try:
            if suffix in {".md", ".txt"}:
                markdown_text = await asyncio.to_thread(temp_path.read_text, encoding="utf-8")
                source_type = suffix.lstrip(".") or "text"
            else:
                parsed = await asyncio.to_thread(
                    self._deps.parser.parse_path,
                    temp_path,
                    filename,
                    source_url=asset_row.get("source_url"),
                )
                markdown_text = self._normalize_markdown_text(
                    getattr(parsed, "markdown_text", "") or getattr(parsed, "text", "")
                )
                source_type = str(getattr(parsed, "source_type", "") or suffix.lstrip(".") or "text")
        finally:
            temp_path.unlink(missing_ok=True)

        markdown_text = self._normalize_markdown_text(markdown_text)
        if not markdown_text:
            raise ValueError(f"无法解析出有效文本：{filename}")

        if self._deps.attachment_assets is not None and asset_row.get("id") is not None:
            self._deps.attachment_assets.update_parsed_content(
                asset_id=int(asset_row["id"]),
                parsed_source_type=source_type,
                parsed_markdown=markdown_text,
                converted_version=int(asset_row.get("converted_version") or 0) or None,
                fulltext_key=fulltext_key or None,
                fulltext_url=str(asset_row.get("fulltext_url") or "").strip() or None,
            )

        asset_id = int(asset_row.get("id") or 0)
        source_document = {
            "document_id": f"asset_{asset_id}",
            "asset_id": asset_id,
            "original_filename": filename,
            "source_type": source_type,
            "fulltext_key": fulltext_key or None,
            "source_url": asset_row.get("source_url"),
            "oss_url": asset_row.get("oss_url"),
            "subcategory": subcategory,
            "source_role": "attachment_asset",
            "markdown_text": markdown_text,
        }
        markdown_source = {
            "source_name": filename,
            "subcategory": subcategory,
            "source_role": "attachment_asset",
            "markdown_text": markdown_text,
        }
        return source_document, markdown_source

    async def _load_attachment_task_sources(
        self,
        *,
        task_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        task = self._deps.upload_tasks.get_upload_task(task_id)
        if not task:
            raise ValueError("task_id 对应的上传任务不存在")
        task_type = str(task.get("task_type") or "").strip()
        if task_type == "brand_ai_knowledge_upload":
            raise ValueError("正式知识库上传任务不需要启动附件冲突会话")

        task_metadata = parse_metadata_json(task.get("metadata_json"))
        brand_code = str(task_metadata.get("brand_code") or "").strip()
        brand_name = str(task_metadata.get("brand_name") or task_metadata.get("category") or "").strip()
        if not brand_code or not brand_name:
            raise ValueError("上传任务缺少 brand_code 或 brand_name")

        brand = self._deps.brands.get_brand_by_code(brand_code)
        if not brand:
            raise ValueError("品牌不存在，请先建品牌")
        persisted_brand_name = str(brand.get("brand_name") or "").strip()
        if persisted_brand_name != brand_name:
            raise ValueError("上传任务中的 brand_code / brand_name 与品牌主数据不匹配")

        files = self._deps.upload_tasks.get_upload_task_files(task_id)
        if not files:
            raise ValueError("上传任务下没有可用附件")

        attachment_files = [
            item
            for item in files
            if str(item.get("file_role") or "").strip() == "attachment"
            and str(item.get("status") or "").strip() == "success"
        ]
        if not attachment_files:
            raise ValueError("当前上传任务没有可用于冲突扫描的普通附件")

        attachment_assets = self._deps.attachment_assets.list_by_upload_task_id(upload_task_id=task_id)
        assets_by_file_id = {
            int(item.get("upload_task_file_id") or 0): item
            for item in attachment_assets
            if item.get("upload_task_file_id") is not None
        }
        file_metadata_by_index = {}
        task_payload = task_metadata.get("_task_payload")
        if isinstance(task_payload, dict):
            candidate = task_payload.get("file_metadata_by_index")
            if isinstance(candidate, dict):
                file_metadata_by_index = candidate

        source_documents: list[dict[str, Any]] = []
        markdown_sources: list[dict[str, Any]] = []
        for file_item in attachment_files:
            upload_task_file_id = int(file_item.get("id") or 0)
            asset_row = assets_by_file_id.get(upload_task_file_id)
            if asset_row is None:
                continue
            file_index = str(file_item.get("file_index") or "")
            file_meta = file_metadata_by_index.get(file_index) if file_index else None
            subcategory = None
            if isinstance(file_meta, dict):
                subcategory = str(file_meta.get("subcategory") or file_meta.get("product_name") or "").strip() or None
            source_document, markdown_source = await self._parse_attachment_asset_source(
                asset_row=asset_row,
                subcategory=subcategory,
            )
            source_documents.append(source_document)
            markdown_sources.append(markdown_source)

        if not markdown_sources:
            raise ValueError("当前上传任务没有可读取的附件 Markdown 源")
        return task, brand, source_documents, markdown_sources

    def _load_session_markdown_sources(self, source_documents: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str | None]:
        markdown_sources: list[dict[str, Any]] = []
        base_knowledge_markdown: str | None = None
        for item in source_documents:
            if not isinstance(item, dict):
                continue
            source_name = str(item.get("original_filename") or item.get("document_id") or "").strip()
            full_text = str(item.get("markdown_text") or "").strip()
            if not full_text:
                document_id = str(item.get("document_id") or "").strip()
                if document_id and callable(self._deps.get_full_text):
                    full_text = str(self._deps.get_full_text(document_id) or "").strip()
            if not full_text:
                continue
            source_role = str(item.get("source_role") or "").strip()
            if source_role == "base_knowledge" and not base_knowledge_markdown:
                base_knowledge_markdown = full_text
            markdown_sources.append(
                {
                    "source_name": source_name,
                    "subcategory": item.get("subcategory"),
                    "source_role": source_role,
                    "markdown_text": full_text,
                }
            )
        return markdown_sources, base_knowledge_markdown

    @staticmethod
    def _build_attachment_scan_markdown(markdown_sources: list[dict[str, Any]]) -> str:
        sections: list[str] = []
        for index, item in enumerate(markdown_sources, start=1):
            if not isinstance(item, dict):
                continue
            markdown_text = str(item.get("markdown_text") or "").strip()
            if not markdown_text:
                continue
            source_name = str(item.get("source_name") or f"attachment-{index}").strip()
            subcategory = str(item.get("subcategory") or "").strip()
            header = f"## 附件来源 {index}: {source_name}"
            if subcategory:
                header = f"{header} / {subcategory}"
            sections.append(f"{header}\n\n{markdown_text}")
        return "\n\n".join(sections).strip()

    async def _build_attachment_conflict_scan_markdown_sources(
        self,
        *,
        brand_name: str,
        source_documents: list[dict[str, Any]],
        markdown_sources: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        scan_markdown_sources = [dict(item) for item in markdown_sources if isinstance(item, dict)]
        if not scan_markdown_sources:
            return []
        if self._deps.brand_products is None:
            return scan_markdown_sources

        combined_markdown = self._build_attachment_scan_markdown(scan_markdown_sources)
        if not combined_markdown:
            return scan_markdown_sources

        try:
            snapshot_result = await self._build_brand_knowledge_snapshot_from_markdown(
                brand_name=brand_name,
                markdown_text=combined_markdown,
                source_name=f"{brand_name}-attachment-conflict-scan.md",
                attachments=self._build_snapshot_attachments(source_documents),
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "Failed to build external enrichment scan sources brand_name=%s",
                brand_name,
            )
            return scan_markdown_sources

        supplemental_markdown_sources = [
            dict(item)
            for item in (snapshot_result.get("supplemental_markdown_sources") or [])
            if isinstance(item, dict) and str(item.get("markdown_text") or "").strip()
        ]
        if not supplemental_markdown_sources:
            return scan_markdown_sources
        return [*scan_markdown_sources, *supplemental_markdown_sources]
