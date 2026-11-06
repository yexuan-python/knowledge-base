from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from knowledge_base.brand.ai_knowledge_filename import parse_ai_knowledge_filename


@dataclass(frozen=True)
class AttachmentPreviewEntryDependencies:
    brands: Any
    upload_task_application: Any
    attachment_draft_application: Any


class AttachmentPreviewEntryService:
    def __init__(self, dependencies: AttachmentPreviewEntryDependencies) -> None:
        self._deps = dependencies

    async def preview_parse_brand_attachments(
        self,
        *,
        brand_name: str,
        brand_code: str | None,
        attachments: list[dict[str, str]],
    ) -> dict[str, Any]:
        official_attachment = self.resolve_official_ai_knowledge_preview_attachment(attachments)
        if official_attachment is not None:
            parsed_filename = official_attachment["parsed_filename"]
            resolved_brand_name = str(parsed_filename.brand_name or "").strip()
            resolved_brand_code = str(brand_code or "").strip()
            if not resolved_brand_code:
                if self._deps.brands is None:
                    raise ValueError("品牌不存在，请先建品牌")
                brand = self._deps.brands.get_brand_by_name(resolved_brand_name)
                if not brand:
                    raise ValueError("品牌不存在，请先建品牌")
                resolved_brand_code = str(brand.get("brand_code") or "").strip()
            if not resolved_brand_code:
                raise ValueError("brand_code 不能为空")
            if self._deps.upload_task_application is None:
                raise RuntimeError("upload task application is not initialized")
            await self._deps.upload_task_application.enqueue_brand_ai_knowledge_url_task(
                filename=official_attachment["name"],
                source_url=official_attachment["url"],
                brand_code=resolved_brand_code,
                brand_name=resolved_brand_name,
                force_reingest=False,
            )
            return {
                "brand_name": resolved_brand_name,
                "status": "true",
            }
        return await self._deps.attachment_draft_application.preview_parse(
            brand_name=brand_name,
            brand_code=brand_code,
            attachments=attachments,
        )

    @staticmethod
    def resolve_official_ai_knowledge_preview_attachment(
        attachments: list[dict[str, str]],
    ) -> dict[str, Any] | None:
        valid_attachments: list[dict[str, Any]] = []
        official_attachments: list[dict[str, Any]] = []
        for attachment in attachments:
            name = str(attachment.get("name") or "").strip()
            url = str(attachment.get("url") or "").strip()
            if not name or not url:
                continue
            item = {"name": name, "url": url}
            valid_attachments.append(item)
            parsed_filename = parse_ai_knowledge_filename(name)
            if parsed_filename is not None and parsed_filename.normalized_extension == "md":
                item["parsed_filename"] = parsed_filename
                official_attachments.append(item)
        if not official_attachments:
            return None
        if len(valid_attachments) != 1:
            raise ValueError("正式品牌AI知识库文件请单独上传")
        return official_attachments[0]
