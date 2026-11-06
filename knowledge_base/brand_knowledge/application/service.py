from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import requests as requests

from knowledge_base.brand.ai_knowledge_filename import parse_ai_knowledge_filename
from knowledge_base.brand.knowledge_extraction import (
    build_brand_knowledge_snapshot_from_markdown,
    persist_brand_knowledge_snapshot,
)
from knowledge_base.brand.callback_mapper import format_brand_callback_knowledge_from_snapshot
from knowledge_base.brand_knowledge.ai import (
    generate_brand_knowledge_full_markdown,
    generate_brand_knowledge_patch_markdown,
    generate_brand_knowledge_round,
    scan_brand_knowledge_conflicts,
)
from knowledge_base.brand_knowledge.application.attachment_conflict_facts import (
    AttachmentConflictFactsMixin,
)
from knowledge_base.brand_knowledge.application.attachment_conflict_resolution import (
    AttachmentConflictResolutionMixin,
)
from knowledge_base.brand_knowledge.application.attachment_conflict_sources import (
    AttachmentConflictSourcesMixin,
)
from knowledge_base.brand_knowledge.application.attachment_conflict_callbacks import (
    ATTACHMENT_CONFLICT_COMPLETED_CALLBACK_TYPE,
    ATTACHMENT_CONFLICT_WAITING_CALLBACK_TYPE,
    BRAND_KNOWLEDGE_COMPLETED_CALLBACK_TYPE,
    BRAND_KNOWLEDGE_STATUS_CALLBACK_TYPE,
    BrandKnowledgeAttachmentConflictCallbackMixin,
)
from knowledge_base.brand_knowledge.application.brand_knowledge_session_view import (
    BrandKnowledgeSessionViewMixin,
)
from knowledge_base.brand_knowledge.application.instruction_web_sources import (
    build_instruction_web_markdown_sources,
)
from knowledge_base.brand_knowledge.application.publish_mode import (
    PUBLISH_MODE_FULL_INGEST,
    attachment_conflict_session_kind_for_publish_mode,
    is_attachment_conflict_session_kind,
    is_draft_only_publish_mode,
    normalize_publish_mode,
    publish_mode_from_attachment_conflict_session_kind,
    should_ingest_full_knowledge,
)
from knowledge_base.shared.utils import build_brand_ai_knowledge_markdown_object_key

logger = logging.getLogger(__name__)

_KNOWLEDGE_ITERATION_MODES = {
    "attachments_only",
    "attachments_with_instruction",
    "instruction_only",
}
_WEB_ARTICLE_ERROR_SOURCE_TYPE = "web_article_error"
_WEB_ARTICLE_ERROR_SOURCE_ROLE = "iteration_web_article_error"
_WEB_ARTICLE_ERROR_MESSAGE = "链接内容提取失败，请复制链接内容到文字要求框"


@dataclass(frozen=True)
class BrandKnowledgeApplicationDependencies:
    settings: Any
    brands: Any
    brand_knowledge_sessions: Any
    document_registry: Any
    brand_products: Any = None
    brand_knowledge: Any = None
    tianyancha_client: Any = None
    store: Any = None
    get_full_text: Any = None
    upload_tasks: Any = None
    attachment_assets: Any = None
    brand_full_knowledge: Any = None
    brand_ai_knowledge_ingestion: Any = None
    oss_client: Any = None
    parser: Any = None
    embeddings: Any = None
    brand_knowledge_facts: Any = None
    background_jobs: Any = None
    enqueue_attachment_conflict_resolution_job: Any = None
    runtime: Any = None
    spawn_background_task: Any = None
    build_current_brand_callback_knowledge: Any = None
    build_next_brand_full_knowledge: Any = None
    generate_next_brand_full_knowledge: Any = None


class BrandKnowledgeApplicationService(
    AttachmentConflictFactsMixin,
    AttachmentConflictResolutionMixin,
    AttachmentConflictSourcesMixin,
    BrandKnowledgeAttachmentConflictCallbackMixin,
    BrandKnowledgeSessionViewMixin,
):
    def __init__(self, dependencies: BrandKnowledgeApplicationDependencies) -> None:
        self._deps = dependencies

    async def _build_brand_knowledge_snapshot_from_markdown(
        self,
        *,
        brand_name: str,
        markdown_text: str,
        source_name: str,
        attachments: list[dict[str, Any]] | None = None,
        enable_tianyancha: bool = True,
    ) -> dict[str, Any]:
        return await build_brand_knowledge_snapshot_from_markdown(
            self._knowledge_snapshot_service_proxy(),
            brand_name=brand_name,
            markdown_text=markdown_text,
            source_name=source_name,
            attachments=attachments,
            enable_tianyancha=enable_tianyancha,
        )

    async def _generate_brand_knowledge_full_markdown(
        self,
        *,
        brand_name: str,
        markdown_sources: list[dict[str, Any]],
        history_resolutions: list[dict[str, Any]],
        current_resolutions: list[dict[str, Any]],
        auto_merged: list[dict[str, Any]],
    ) -> dict[str, Any]:
        from knowledge_base.brand_knowledge.application import service as service_module

        return await service_module.generate_brand_knowledge_full_markdown(
            brand_name=brand_name,
            markdown_sources=markdown_sources,
            history_resolutions=history_resolutions,
            current_resolutions=current_resolutions,
            auto_merged=auto_merged,
            settings=self._deps.settings,
        )

    async def _generate_brand_knowledge_patch_markdown(
        self,
        *,
        brand_name: str,
        markdown_sources: list[dict[str, Any]],
        base_knowledge_markdown: str,
        history_resolutions: list[dict[str, Any]] | None = None,
        current_resolutions: list[dict[str, Any]] | None = None,
        auto_merged: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        from knowledge_base.brand_knowledge.application import service as service_module

        return await service_module.generate_brand_knowledge_patch_markdown(
            brand_name=brand_name,
            markdown_sources=markdown_sources,
            base_knowledge_markdown=base_knowledge_markdown,
            history_resolutions=history_resolutions or [],
            current_resolutions=current_resolutions or [],
            auto_merged=auto_merged or [],
            settings=self._deps.settings,
        )

    def _persist_brand_knowledge_snapshot(
        self,
        *,
        brand_name: str,
        snapshot: dict[str, Any],
        source_task_id: str,
    ) -> dict[str, Any]:
        return persist_brand_knowledge_snapshot(
            self._knowledge_snapshot_service_proxy(),
            brand_name=brand_name,
            snapshot=snapshot,
            source_task_id=source_task_id,
        )

    @staticmethod
    def _format_brand_callback_knowledge_from_snapshot(
        *,
        brand: dict[str, Any],
        knowledge_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        return format_brand_callback_knowledge_from_snapshot(
            brand=brand,
            knowledge_snapshot=knowledge_snapshot,
        )

    @staticmethod
    def _knowledge_iteration_session_kind(iteration_mode: str) -> str:
        return f"knowledge_iteration:{iteration_mode}"

    @staticmethod
    def _normalize_publish_mode(publish_mode: str | None) -> str:
        return normalize_publish_mode(publish_mode)

    @staticmethod
    def _is_draft_only_publish_mode(publish_mode: str | None) -> bool:
        return is_draft_only_publish_mode(publish_mode)

    @staticmethod
    def _should_ingest_full_knowledge(publish_mode: str | None) -> bool:
        return should_ingest_full_knowledge(publish_mode)

    @staticmethod
    def _attachment_conflict_session_kind(*, publish_mode: str | None = None) -> str:
        return attachment_conflict_session_kind_for_publish_mode(publish_mode)

    @staticmethod
    def _is_attachment_conflict_session_kind(session_kind: Any) -> bool:
        return is_attachment_conflict_session_kind(session_kind)

    @staticmethod
    def _publish_mode_from_attachment_conflict_session_kind(session_kind: Any) -> str:
        return publish_mode_from_attachment_conflict_session_kind(session_kind)

    @staticmethod
    def _build_instruction_markdown_source(instruction: str) -> tuple[dict[str, Any], dict[str, Any]]:
        normalized_instruction = str(instruction or "").strip()
        markdown_text = f"# 本轮迭代要求\n\n{normalized_instruction}"
        source_document = {
            "document_id": "iteration_instruction",
            "original_filename": "本轮迭代要求.md",
            "source_type": "text_instruction",
            "source_role": "iteration_instruction",
            "markdown_text": markdown_text,
        }
        markdown_source = {
            "source_name": "本轮迭代要求.md",
            "subcategory": "本轮要求",
            "source_role": "iteration_instruction",
            "markdown_text": markdown_text,
        }
        return source_document, markdown_source

    def _resolve_iteration_brand(
        self,
        *,
        brand_code: str | None,
        brand_name: str | None,
    ) -> dict[str, Any]:
        normalized_brand_code = str(brand_code or "").strip()
        normalized_brand_name = str(brand_name or "").strip()
        brand = None
        if normalized_brand_code:
            brand = self._deps.brands.get_brand_by_code(normalized_brand_code)
        if brand is None and normalized_brand_name and hasattr(self._deps.brands, "get_brand_by_name"):
            brand = self._deps.brands.get_brand_by_name(normalized_brand_name)
        if not brand:
            raise ValueError("品牌不存在，请先建品牌")
        if normalized_brand_code and str(brand.get("brand_code") or "").strip() != normalized_brand_code:
            raise ValueError("品牌编码与品牌主数据不匹配")
        if normalized_brand_name and str(brand.get("brand_name") or "").strip() != normalized_brand_name:
            raise ValueError("品牌名称与品牌主数据不匹配")
        return brand

    def _load_latest_base_knowledge_markdown(self, *, brand: dict[str, Any]) -> tuple[dict[str, Any], str]:
        store = self._deps.brand_full_knowledge
        if store is None:
            raise ValueError("正式知识库依赖未初始化")
        latest = None
        brand_code = str(brand.get("brand_code") or "").strip()
        origin_lookup_supported = False
        if brand_code and hasattr(store, "get_latest_by_brand_code_and_origin_including_skipped"):
            origin_lookup_supported = True
            latest = store.get_latest_by_brand_code_and_origin_including_skipped(
                brand_code=brand_code,
                change_origin="frontend",
            )
        if (
            latest is None
            and hasattr(store, "get_latest_by_brand_id_and_origin_including_skipped")
            and brand.get("id") is not None
        ):
            origin_lookup_supported = True
            latest = store.get_latest_by_brand_id_and_origin_including_skipped(
                brand_id=int(brand["id"]),
                change_origin="frontend",
            )
        if latest is None and brand_code and hasattr(store, "get_latest_by_brand_code_and_origin"):
            origin_lookup_supported = True
            latest = store.get_latest_by_brand_code_and_origin(
                brand_code=brand_code,
                change_origin="frontend",
            )
        if latest is None and hasattr(store, "get_latest_by_brand_id_and_origin") and brand.get("id") is not None:
            origin_lookup_supported = True
            latest = store.get_latest_by_brand_id_and_origin(
                brand_id=int(brand["id"]),
                change_origin="frontend",
            )
        if latest is None and not origin_lookup_supported and brand_code and hasattr(store, "get_latest_by_brand_code"):
            latest = store.get_latest_by_brand_code(brand_code=brand_code)
        if latest is None and not origin_lookup_supported and hasattr(store, "get_latest_by_brand_id") and brand.get("id") is not None:
            latest = store.get_latest_by_brand_id(brand_id=int(brand["id"]))
        if not latest:
            raise ValueError("当前品牌暂无可迭代的前端来源知识库，请先完成第一次生成")
        markdown_text = str(latest.get("content_markdown") or "").strip()
        if not markdown_text:
            raise ValueError("当前品牌最新前端来源知识库内容为空，无法迭代")
        return latest, markdown_text

    def _build_next_iteration_filename(
        self,
        *,
        brand: dict[str, Any],
        latest_base: dict[str, Any] | None = None,
    ) -> str:
        store = self._deps.brand_full_knowledge
        brand_code = str(brand.get("brand_code") or "").strip()
        brand_name = str(brand.get("brand_name") or "").strip()
        latest_version_no = int((latest_base or {}).get("version_no") or 0)
        if latest_version_no > 0:
            version_no = latest_version_no + 1
        elif hasattr(store, "get_next_version_no_by_brand_code") and brand_code:
            version_no = store.get_next_version_no_by_brand_code(brand_code=brand_code)
        else:
            version_no = store.get_next_version_no(brand_id=int(brand["id"]))
        return self._build_final_knowledge_filename(brand_name, version_no=version_no)

    async def _ingest_attachment_conflict_final_markdown(
        self,
        *,
        session_id: str,
        filename: str,
        brand_code: str,
        brand_name: str,
        markdown_text: str,
        force_reingest: bool,
        source_task_id: str | None,
        change_origin: str,
    ) -> dict[str, Any]:
        ingestion_service = self._deps.brand_ai_knowledge_ingestion
        if ingestion_service is None:
            raise ValueError("正式知识库入库依赖未初始化")

        ingest_generated_markdown = getattr(ingestion_service, "ingest_generated_markdown", None)
        if callable(ingest_generated_markdown):
            return await ingest_generated_markdown(
                task_id=session_id,
                upload_task_file_id=0,
                filename=filename,
                brand_code=brand_code,
                brand_name=brand_name,
                markdown_text=markdown_text,
                force_reingest=force_reingest,
                source_task_id=source_task_id,
                change_origin=change_origin,
                job_id=f"brand-ai-kb-session:{session_id}"[:128],
            )

        ingest_upload_task_file = getattr(ingestion_service, "ingest_upload_task_file", None)
        if not callable(ingest_upload_task_file):
            raise AttributeError("brand_ai_knowledge_ingestion 缺少可用的正式知识库入库方法")

        normalized_markdown_text = str(markdown_text or "").strip()
        if not normalized_markdown_text:
            raise ValueError("markdown_text 不能为空")

        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".md") as tmp:
                tmp.write(normalized_markdown_text.encode("utf-8"))
                temp_path = Path(tmp.name)
            return await ingest_upload_task_file(
                task_id=session_id,
                upload_task_file_id=0,
                filename=filename,
                brand_code=brand_code,
                brand_name=brand_name,
                force_reingest=force_reingest,
                staged_path=temp_path,
                source_url=None,
                content_type="text/markdown; charset=utf-8",
                source_task_id=source_task_id,
                change_origin=change_origin,
                job_id=f"brand-ai-kb-session:{session_id}"[:128],
            )
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    async def _store_generated_markdown_draft(
        self,
        *,
        session_id: str,
        filename: str,
        brand: dict[str, Any],
        brand_code: str,
        brand_name: str,
        markdown_text: str,
        source_task_id: str | None,
        change_origin: str,
    ) -> dict[str, Any]:
        normalized_markdown = str(markdown_text or "").strip()
        if not normalized_markdown:
            raise ValueError("markdown_text 不能为空")
        if self._deps.brand_full_knowledge is None:
            raise ValueError("正式知识库文件记录依赖未初始化")
        if self._deps.oss_client is None or not getattr(self._deps.oss_client, "enabled", False):
            raise ValueError("OSS 依赖未初始化，无法上传知识库草稿")

        parsed_filename = parse_ai_knowledge_filename(filename)
        if parsed_filename is None:
            raise ValueError("正式知识库文件名不符合规范")
        if parsed_filename.brand_name != brand_name:
            raise ValueError("文件名中的品牌名与请求中的 brand_name 不一致")

        get_next_revision_no = getattr(self._deps.brand_full_knowledge, "get_next_revision_no", None)
        revision_no = 1
        if callable(get_next_revision_no) and brand_code:
            revision_no = int(
                get_next_revision_no(
                    brand_code=brand_code,
                    version_no=parsed_filename.version_no,
                    knowledge_date=parsed_filename.knowledge_date,
                )
                or 1
            )
        object_filename = filename
        if revision_no > 1:
            filename_path = Path(filename)
            object_filename = f"{filename_path.stem}_R{revision_no}{filename_path.suffix}"
        markdown_oss_key = build_brand_ai_knowledge_markdown_object_key(
            brand_name=brand_name,
            filename=object_filename,
        )
        uploaded_key = await asyncio.to_thread(
            self._deps.oss_client.upload_bytes,
            normalized_markdown.encode("utf-8"),
            markdown_oss_key,
            "text/markdown; charset=utf-8",
        )
        if not uploaded_key:
            raise ValueError(f"知识库草稿 Markdown 上传 OSS 失败: {filename}")
        markdown_oss_url = (
            self._deps.oss_client.build_object_url(uploaded_key)
            if hasattr(self._deps.oss_client, "build_object_url")
            else None
        )
        content_hash = hashlib.sha256(normalized_markdown.encode("utf-8")).hexdigest()
        try:
            full_knowledge_file_id = self._deps.brand_full_knowledge.create_brand_full_knowledge_file(
                brand_id=int(brand["id"]) if brand.get("id") is not None else None,
                brand_code=brand_code,
                brand_name=brand_name,
                version_no=parsed_filename.version_no,
                knowledge_date=parsed_filename.knowledge_date,
                revision_no=revision_no,
                file_name=filename,
                source_ext=parsed_filename.suffix.lower(),
                pdf_file_name=None,
                oss_key=uploaded_key,
                oss_url=str(markdown_oss_url or ""),
                pdf_oss_key=None,
                pdf_oss_url=None,
                content_markdown=normalized_markdown,
                content_hash=content_hash,
                document_id=None,
                is_latest=False,
                ingest_status="skipped",
                milvus_status="skipped",
                facts_status="skipped",
                conflict_count=0,
                conflicts_json=[],
                source_task_id=source_task_id or session_id,
                change_origin=change_origin,
                error_message="draft_only: skipped vector/fact/search ingestion",
            )
        except Exception:
            delete_object = getattr(self._deps.oss_client, "delete_object", None)
            if callable(delete_object):
                try:
                    await asyncio.to_thread(delete_object, uploaded_key)
                except Exception as cleanup_exc:  # noqa: BLE001
                    logger.warning(
                        "Failed to cleanup uploaded draft markdown after DB insert failure session_id=%s oss_key=%s error=%s",
                        session_id,
                        uploaded_key,
                        cleanup_exc,
                        exc_info=True,
                    )
            raise
        return {
            "status": "success",
            "skipped": True,
            "skip_reason": "draft_only",
            "document_id": None,
            "full_knowledge_file_id": full_knowledge_file_id,
            "markdown_oss_key": uploaded_key,
            "markdown_oss_url": str(markdown_oss_url or ""),
            "pdf_oss_key": None,
            "pdf_oss_url": None,
        }

    async def start_knowledge_iteration_session(
        self,
        *,
        brand_code: str | None = None,
        brand_name: str | None = None,
        task_id: str | None = None,
        publish_mode: str | None = None,
        iteration_mode: str | None = None,
        initial_message: str | None = None,
        update_instruction: str | None = None,
    ) -> dict[str, Any]:
        if self._deps.brand_ai_knowledge_ingestion is None or self._deps.brand_full_knowledge is None:
            raise ValueError("正式知识库入库依赖未初始化")

        normalized_task_id = str(task_id or "").strip()
        normalized_instruction = str(update_instruction or initial_message or "").strip()
        normalized_mode = str(iteration_mode or "").strip()
        normalized_publish_mode = self._normalize_publish_mode(publish_mode)
        if not normalized_mode:
            if normalized_task_id and normalized_instruction:
                normalized_mode = "attachments_with_instruction"
            elif normalized_task_id:
                normalized_mode = "attachments_only"
            else:
                normalized_mode = "instruction_only"
        if normalized_mode not in _KNOWLEDGE_ITERATION_MODES:
            raise ValueError("不支持的知识库迭代模式")
        if normalized_mode in {"attachments_only", "attachments_with_instruction"} and not normalized_task_id:
            raise ValueError("知识库迭代 A/B 模式 task_id 不能为空")
        if normalized_mode in {"attachments_with_instruction", "instruction_only"} and not normalized_instruction:
            raise ValueError("知识库迭代 B/C 模式 update_instruction 不能为空")

        source_documents: list[dict[str, Any]] = []
        markdown_sources: list[dict[str, Any]] = []
        if normalized_mode in {"attachments_only", "attachments_with_instruction"}:
            _, brand, source_documents, markdown_sources = await self._load_attachment_task_sources(
                task_id=normalized_task_id,
            )
            provided_brand_code = str(brand_code or "").strip()
            provided_brand_name = str(brand_name or "").strip()
            if provided_brand_code and str(brand.get("brand_code") or "").strip() != provided_brand_code:
                raise ValueError("上传任务品牌编码与本次选择品牌不匹配")
            if provided_brand_name and str(brand.get("brand_name") or "").strip() != provided_brand_name:
                raise ValueError("上传任务品牌名称与本次选择品牌不匹配")
        else:
            brand = self._resolve_iteration_brand(
                brand_code=brand_code,
                brand_name=brand_name,
            )

        if normalized_mode in {"attachments_with_instruction", "instruction_only"}:
            instruction_document, instruction_source = self._build_instruction_markdown_source(normalized_instruction)
            source_documents.append(instruction_document)
            markdown_sources.append(instruction_source)
            web_source_documents, web_markdown_sources = await build_instruction_web_markdown_sources(
                normalized_instruction
            )
            source_documents.extend(web_source_documents)
            markdown_sources.extend(web_markdown_sources)
        if not markdown_sources:
            raise ValueError("知识库迭代缺少可用来源")
        failed_web_source_documents = [
            document
            for document in source_documents
            if str(document.get("source_type") or "") == _WEB_ARTICLE_ERROR_SOURCE_TYPE
            or str(document.get("source_role") or "") == _WEB_ARTICLE_ERROR_SOURCE_ROLE
        ]

        latest_base, base_markdown = self._load_latest_base_knowledge_markdown(brand=brand)
        resolved_brand_name = str(brand.get("brand_name") or "").strip()
        normalized_brand_code = str(brand.get("brand_code") or "").strip() or None
        session_id = f"bks_{uuid4().hex}"
        source_task_id = normalized_task_id or session_id
        user_message = normalized_instruction or "请基于本轮附件资料迭代生成新版品牌 AI 知识库。"
        session_kind = self._knowledge_iteration_session_kind(normalized_mode)
        has_failed_web_sources = bool(failed_web_source_documents)
        failed_web_source_urls = [
            str(document.get("source_url") or "").strip()
            for document in failed_web_source_documents
            if str(document.get("source_url") or "").strip()
        ]
        failed_web_source_message = "部分链接内容提取失败，本轮尚未生成知识库。请复制失败链接正文到文字要求框后重新提交。"
        if failed_web_source_urls:
            failed_web_source_message = (
                "以下链接内容提取失败，本轮尚未生成知识库。请复制失败链接正文到文字要求框后重新提交：\n"
                + "\n".join(f"- {url}" for url in failed_web_source_urls)
            )
        initial_status = "waiting_user_input" if has_failed_web_sources else "running"
        initial_assistant_message = (
            failed_web_source_message
            if has_failed_web_sources
            else "正在根据本轮资料生成新版品牌 AI 知识库。"
        )

        self._deps.brand_knowledge_sessions.create_session(
            session_id=session_id,
            brand_id=int(brand["id"]) if brand.get("id") is not None else None,
            brand_code=normalized_brand_code,
            brand_name=resolved_brand_name,
            source_task_id=source_task_id,
            session_kind=session_kind,
            status=initial_status,
            current_round=1,
            initial_user_message=user_message,
            latest_user_message=user_message,
            latest_assistant_message=initial_assistant_message,
            source_documents=[
                {
                    "document_id": f"base_knowledge:{latest_base.get('id') or 'latest'}",
                    "original_filename": str(latest_base.get("file_name") or "最新正式品牌AI知识库.md"),
                    "source_type": "brand_ai_knowledge",
                    "source_role": "base_knowledge",
                    "markdown_text": base_markdown,
                },
                *source_documents,
            ],
        )

        request_payload = {
            "brand_code": normalized_brand_code,
            "brand_name": resolved_brand_name,
            "source_task_id": source_task_id,
            "session_type": "knowledge_iteration",
            "iteration_mode": normalized_mode,
            "stage": "knowledge_iteration_generate",
            "source_count": len(markdown_sources),
            "base_full_knowledge_file_id": latest_base.get("id"),
            "base_file_name": latest_base.get("file_name"),
            "update_instruction": normalized_instruction or None,
            "publish_mode": normalized_publish_mode,
        }
        if has_failed_web_sources:
            response_payload = {
                "status": "waiting_user_input",
                "message": initial_assistant_message,
                "failed_web_sources": [
                    {
                        "document_id": document.get("document_id"),
                        "source_url": document.get("source_url"),
                        "original_filename": document.get("original_filename"),
                        "error_message": document.get("error_message") or _WEB_ARTICLE_ERROR_MESSAGE,
                        "error_type": document.get("error_type"),
                    }
                    for document in failed_web_source_documents
                ],
            }
            self._deps.brand_knowledge_sessions.create_round(
                session_id=session_id,
                round_no=1,
                stage="web_source_extract",
                request_payload={
                    **request_payload,
                    "stage": "knowledge_iteration_web_source_extract",
                    "failed_url_count": len(failed_web_source_documents),
                },
                response_payload=response_payload,
                user_message_text=user_message,
                assistant_message_text=initial_assistant_message,
                draft_markdown=None,
                conflicts=[],
                conflict_markdown=None,
            )
            return self.get_knowledge_session(session_id=session_id) or {
                "session_id": session_id,
                "brand_code": normalized_brand_code,
                "brand_name": resolved_brand_name,
                "status": "waiting_user_input",
                "round_no": 1,
                "session_type": "knowledge_iteration",
                "iteration_mode": normalized_mode,
                "session_kind": session_kind,
                "source_task_id": source_task_id,
                "assistant_message": initial_assistant_message,
                "source_documents": source_documents,
                "conflicts": [],
                "auto_merged": [],
                "conflict_markdown": None,
                "scan_summary": None,
            }

        try:
            if self._is_draft_only_publish_mode(normalized_publish_mode):
                response_payload = await generate_brand_knowledge_patch_markdown(
                    brand_name=resolved_brand_name,
                    markdown_sources=markdown_sources,
                    base_knowledge_markdown=base_markdown,
                    settings=self._deps.settings,
                )
            else:
                response_payload = await generate_brand_knowledge_round(
                    brand_name=resolved_brand_name,
                    markdown_sources=markdown_sources,
                    base_knowledge_markdown=base_markdown,
                    settings=self._deps.settings,
                )
            normalized_payload = self._normalize_session_payload(
                response_payload,
                allow_completed=True,
                fallback_summary="知识库迭代生成完成。",
            )
            final_markdown = normalized_payload["final_markdown"]
            if not final_markdown:
                raise ValueError("未生成有效的新版品牌 AI 知识库 Markdown")

            final_filename = self._build_next_iteration_filename(brand=brand, latest_base=latest_base)
            if self._is_draft_only_publish_mode(normalized_publish_mode):
                ingest_result = await self._store_generated_markdown_draft(
                    session_id=session_id,
                    filename=final_filename,
                    brand=brand,
                    brand_code=normalized_brand_code or "",
                    brand_name=resolved_brand_name,
                    markdown_text=final_markdown,
                    source_task_id=source_task_id,
                    change_origin="frontend",
                )
                assistant_message = "知识库迭代已完成，已生成可下载的品牌 AI 知识库草稿。"
            else:
                ingest_result = await self._ingest_attachment_conflict_final_markdown(
                    session_id=session_id,
                    filename=final_filename,
                    brand_code=normalized_brand_code or "",
                    brand_name=resolved_brand_name,
                    markdown_text=final_markdown,
                    force_reingest=False,
                    source_task_id=source_task_id,
                    change_origin="frontend",
                )
                assistant_message = "知识库迭代已完成，已生成新版正式品牌 AI 知识库。"
            self._deps.brand_knowledge_sessions.create_round(
                session_id=session_id,
                round_no=1,
                stage="knowledge_iteration_finalize",
                request_payload=request_payload,
                response_payload={**response_payload, "ingest_result": ingest_result},
                user_message_text=user_message,
                assistant_message_text=assistant_message,
                draft_markdown=final_markdown,
                conflicts=[],
                conflict_markdown=None,
            )
            self._deps.brand_knowledge_sessions.update_session_progress(
                session_id=session_id,
                status="completed",
                current_round=1,
                latest_draft_markdown="知识库迭代生成完成。",
                latest_conflicts=[],
                latest_conflict_markdown=None,
                latest_scan_summary="知识库迭代生成完成。",
                latest_auto_merged=[],
                latest_user_message=user_message,
                latest_assistant_message=assistant_message,
                final_markdown=final_markdown,
                final_oss_key=ingest_result.get("markdown_oss_key"),
                final_full_knowledge_file_id=ingest_result.get("full_knowledge_file_id"),
                final_document_id=ingest_result.get("document_id"),
            )
        except Exception:
            self._deps.brand_knowledge_sessions.update_session_progress(
                session_id=session_id,
                status="failed",
                current_round=1,
                latest_draft_markdown=None,
                latest_conflicts=[],
                latest_conflict_markdown=None,
                latest_scan_summary=None,
                latest_auto_merged=[],
                latest_user_message=user_message,
                latest_assistant_message="知识库迭代生成失败。",
            )
            raise

        return self.get_knowledge_session(session_id=session_id) or {
            "session_id": session_id,
            "brand_code": normalized_brand_code,
            "brand_name": resolved_brand_name,
            "status": "completed",
            "round_no": 1,
            "session_type": "knowledge_iteration",
            "iteration_mode": normalized_mode,
            "session_kind": session_kind,
            "source_task_id": source_task_id,
            "assistant_message": assistant_message,
            "source_documents": source_documents,
            "conflicts": [],
            "auto_merged": [],
            "conflict_markdown": None,
            "scan_summary": "知识库迭代生成完成。",
        }

    @staticmethod
    def _attachment_temp_fact_source_key(source_document: dict[str, Any]) -> str:
        document_id = str(source_document.get("document_id") or "").strip()
        if document_id:
            return f"document_id:{document_id}"
        asset_id = str(source_document.get("asset_id") or "").strip()
        if asset_id:
            return f"asset_id:{asset_id}"
        source_name = str(source_document.get("original_filename") or "").strip()
        if source_name:
            return f"source_name:{source_name}"
        return f"source_object:{id(source_document)}"

    async def start_attachment_conflict_session(
        self,
        *,
        task_id: str,
        initial_message: str | None = None,
        publish_mode: str | None = PUBLISH_MODE_FULL_INGEST,
    ) -> dict[str, Any]:
        # Historical compatibility: direct callers of this application method
        # default to a formal ingest. New route schemas default to draft_only
        # and pass that mode explicitly through start_knowledge_session().
        if self._deps.upload_tasks is None or self._deps.attachment_assets is None:
            raise ValueError("附件冲突会话依赖未初始化")
        normalized_task_id = str(task_id or "").strip()
        if not normalized_task_id:
            raise ValueError("task_id 不能为空")
        normalized_publish_mode = self._normalize_publish_mode(publish_mode)
        normalized_initial_message = (
            (initial_message or "").strip()
            or "请先扫描普通附件中的冲突；如果没有需要人工确认的冲突，就直接生成最终知识库。"
        )

        existing_session = self._deps.brand_knowledge_sessions.get_latest_by_source_task_id(
            source_task_id=normalized_task_id,
            session_kind=self._attachment_conflict_session_kind(publish_mode=normalized_publish_mode),
        )
        if existing_session is not None and str(existing_session.get("status") or "") != "failed":
            existing_session_id = str(existing_session.get("session_id") or "").strip()
            if existing_session_id:
                return self.get_knowledge_session(session_id=existing_session_id) or {
                    "session_id": existing_session_id,
                    "brand_code": str(existing_session.get("brand_code") or "").strip() or None,
                    "brand_name": str(existing_session.get("brand_name") or "").strip(),
                    "status": str(existing_session.get("status") or ""),
                    "round_no": int(existing_session.get("current_round") or 0),
                    "session_type": "initial_generation",
                    "iteration_mode": None,
                    "session_kind": str(existing_session.get("session_kind") or "").strip() or "attachment_conflict",
                    "source_task_id": normalized_task_id,
                    "assistant_message": str(existing_session.get("latest_assistant_message") or "") or None,
                    "source_documents": [],
                    "conflicts": [],
                    "auto_merged": [],
                    "conflict_markdown": existing_session.get("latest_conflict_markdown"),
                    "scan_summary": str(existing_session.get("latest_scan_summary") or "").strip() or None,
                    "final_markdown": existing_session.get("final_markdown"),
                    "final_oss_key": existing_session.get("final_oss_key"),
                }

        _, brand, source_documents, markdown_sources = await self._load_attachment_task_sources(
            task_id=normalized_task_id,
        )
        resolved_brand_name = str(brand.get("brand_name") or "").strip()
        brand_code = str(brand.get("brand_code") or "").strip() or None
        scan_markdown_sources = await self._build_attachment_conflict_scan_markdown_sources(
            brand_name=resolved_brand_name,
            source_documents=source_documents,
            markdown_sources=markdown_sources,
        )

        session_id = f"bks_{uuid4().hex}"
        self._deps.brand_knowledge_sessions.create_session(
            session_id=session_id,
            brand_id=int(brand["id"]) if brand.get("id") is not None else None,
            brand_code=brand_code,
            brand_name=resolved_brand_name,
            source_task_id=normalized_task_id,
            session_kind=self._attachment_conflict_session_kind(publish_mode=normalized_publish_mode),
            status="running",
            current_round=1,
            initial_user_message=normalized_initial_message,
            latest_user_message=normalized_initial_message,
            latest_assistant_message=None,
            source_documents=source_documents,
        )

        request_payload = {
            "brand_code": brand_code,
            "brand_name": resolved_brand_name,
            "source_task_id": normalized_task_id,
            "round_no": 1,
            "initial_message": normalized_initial_message,
            "stage": "attachment_scan_conflicts",
            "history_resolutions": [],
            "current_resolutions": [],
            "source_count": len(markdown_sources),
            "scan_source_count": len(scan_markdown_sources),
            "publish_mode": normalized_publish_mode,
        }
        try:
            response_payload = await scan_brand_knowledge_conflicts(
                brand_name=resolved_brand_name,
                markdown_sources=scan_markdown_sources,
                settings=self._deps.settings,
            )
            normalized_payload = self._normalize_session_payload(
                response_payload,
                allow_completed=False,
                fallback_summary=str(response_payload.get("scan_summary") or "").strip() or None,
            )
            status = str(normalized_payload["status"])
            working_summary = normalized_payload["working_summary"]
            scan_summary = normalized_payload["scan_summary"]
            auto_merged = normalized_payload["auto_merged"]
            conflicts = normalized_payload["conflicts"]
            conflict_markdown = normalized_payload["conflict_markdown"]
            assistant_message = self._build_assistant_message(
                status=status,
                round_no=1,
                conflicts=conflicts,
                conflict_markdown=conflict_markdown,
                final_markdown=None,
            )
            self._deps.brand_knowledge_sessions.create_round(
                session_id=session_id,
                round_no=1,
                stage="attachment_initial",
                request_payload=request_payload,
                response_payload=response_payload,
                user_message_text=normalized_initial_message,
                assistant_message_text=assistant_message,
                draft_markdown=working_summary,
                conflicts=conflicts,
                conflict_markdown=conflict_markdown,
            )
            self._deps.brand_knowledge_sessions.update_session_progress(
                session_id=session_id,
                status=status,
                current_round=1,
                latest_draft_markdown=working_summary,
                latest_conflicts=conflicts,
                latest_conflict_markdown=conflict_markdown,
                latest_scan_summary=scan_summary,
                latest_auto_merged=auto_merged,
                latest_user_message=normalized_initial_message,
                latest_assistant_message=assistant_message,
            )
            if status == "no_conflicts":
                return await self.submit_attachment_conflict_resolutions(
                    session_id=session_id,
                    round_no=1,
                    resolutions=[],
                    force_reingest=False,
                    publish_mode=normalized_publish_mode,
                )
            if status == "waiting_user_input":
                if self._should_ingest_full_knowledge(normalized_publish_mode):
                    callback_payload = self._build_attachment_conflict_waiting_callback_payload(
                        session_id=session_id,
                        brand_code=brand_code,
                        status=status,
                    )
                    callback_task_id = self._attachment_conflict_callback_task_id(
                        session_id=session_id,
                        stage="waiting",
                    )
                    callback_result = await self._send_attachment_conflict_callback(
                        payload=callback_payload,
                        callback_type=BRAND_KNOWLEDGE_STATUS_CALLBACK_TYPE,
                        callback_task_id=callback_task_id,
                    )
                    if callback_result.get("status") in {"failed", "retrying"}:
                        self._schedule_attachment_conflict_callback_retries_if_needed(
                            callback_task_id=callback_task_id,
                            callback_type=BRAND_KNOWLEDGE_STATUS_CALLBACK_TYPE,
                        )
        except Exception:
            self._deps.brand_knowledge_sessions.update_session_progress(
                session_id=session_id,
                status="failed",
                current_round=1,
                latest_draft_markdown=None,
                latest_conflicts=[],
                latest_conflict_markdown=None,
                latest_user_message=normalized_initial_message,
                latest_assistant_message="附件冲突扫描会话创建失败。",
            )
            raise

        return self.get_knowledge_session(session_id=session_id) or {
            "session_id": session_id,
            "brand_code": brand_code,
            "brand_name": resolved_brand_name,
            "status": "failed",
            "round_no": 1,
            "session_type": "initial_generation",
            "iteration_mode": None,
            "session_kind": self._attachment_conflict_session_kind(publish_mode=normalized_publish_mode),
            "source_task_id": normalized_task_id,
            "assistant_message": "附件冲突扫描会话创建失败。",
            "source_documents": source_documents,
            "conflicts": [],
            "auto_merged": [],
            "conflict_markdown": None,
            "scan_summary": None,
            "final_markdown": None,
            "final_oss_key": None,
        }

    async def submit_attachment_conflict_resolutions(
        self,
        *,
        session_id: str,
        round_no: int,
        resolutions: list[dict[str, Any]],
        force_reingest: bool = False,
        publish_mode: str | None = None,
    ) -> dict[str, Any]:
        if not callable(self._deps.enqueue_attachment_conflict_resolution_job):
            raise RuntimeError("attachment conflict resolution background job dependency is not initialized")
        if self._deps.brand_ai_knowledge_ingestion is None or self._deps.brand_full_knowledge is None:
            raise ValueError("正式知识库入库依赖未初始化")
        session = self._deps.brand_knowledge_sessions.get_session(session_id)
        if not session:
            raise ValueError("session_id 不存在")
        if not self._is_attachment_conflict_session_kind(session.get("session_kind")):
            raise ValueError("当前会话不是附件冲突会话")
        if str(session.get("status") or "") not in {"waiting_user_input", "no_conflicts"}:
            raise ValueError("当前会话不处于可生成正式知识库的状态")
        if int(session.get("current_round") or 0) != round_no:
            raise ValueError("round_no 与当前会话轮次不匹配")

        source_documents = self._parse_json_value(session.get("source_documents_json"), [])
        if not isinstance(source_documents, list) or not source_documents:
            raise ValueError("会话源文档缺失")
        markdown_sources, _ = self._load_session_markdown_sources(source_documents)
        if not markdown_sources:
            raise ValueError("无法读取会话源 Markdown")

        history_resolutions = self._parse_json_value(session.get("resolution_history_json"), [])
        if not isinstance(history_resolutions, list):
            history_resolutions = []
        previous_status = str(session.get("status") or "")
        previous_round = int(session.get("current_round") or 0)
        previous_latest_conflicts = self._parse_json_value(session.get("latest_conflicts_json"), [])
        if not isinstance(previous_latest_conflicts, list):
            previous_latest_conflicts = []
        previous_latest_draft_markdown = str(session.get("latest_draft_markdown") or "") or None
        previous_latest_conflict_markdown = session.get("latest_conflict_markdown")
        previous_latest_scan_summary = str(session.get("latest_scan_summary") or "") or None
        previous_latest_user_message = str(session.get("latest_user_message") or "") or None
        previous_latest_assistant_message = str(session.get("latest_assistant_message") or "") or None
        auto_merged = self._normalize_auto_merged(
            self._parse_json_value(session.get("latest_auto_merged_json"), [])
        )
        normalized_publish_mode = (
            self._normalize_publish_mode(publish_mode)
            if publish_mode is not None
            else self._publish_mode_from_attachment_conflict_session_kind(session.get("session_kind"))
        )
        updated_resolution_history = [*history_resolutions, {"round_no": round_no, "resolutions": resolutions}]

        next_round = round_no + 1
        self._deps.brand_knowledge_sessions.update_session_progress(
            session_id=session_id,
            status="running",
            current_round=next_round,
            latest_draft_markdown=str(session.get("latest_draft_markdown") or "") or None,
            latest_conflicts=[],
            latest_conflict_markdown=None,
            latest_scan_summary=str(session.get("latest_scan_summary") or "") or None,
            latest_user_message=json.dumps(resolutions, ensure_ascii=False),
            latest_assistant_message="正在根据冲突扫描结果生成最终正式知识库。",
            resolution_history=updated_resolution_history,
        )
        try:
            await self._deps.enqueue_attachment_conflict_resolution_job(
                session_id=session_id,
                brand_code=str(session.get("brand_code") or "").strip() or None,
                brand_name=str(session.get("brand_name") or "").strip(),
                source_task_id=str(session.get("source_task_id") or "").strip() or None,
                submitted_round_no=round_no,
                generation_round_no=next_round,
                history_resolutions=history_resolutions,
                current_resolutions=resolutions,
                auto_merged=auto_merged,
                force_reingest=force_reingest,
                publish_mode=normalized_publish_mode,
            )
        except Exception:
            self._deps.brand_knowledge_sessions.update_session_progress(
                session_id=session_id,
                status=previous_status,
                current_round=previous_round,
                latest_draft_markdown=previous_latest_draft_markdown,
                latest_conflicts=previous_latest_conflicts,
                latest_conflict_markdown=previous_latest_conflict_markdown,
                latest_scan_summary=previous_latest_scan_summary,
                latest_auto_merged=auto_merged,
                latest_user_message=previous_latest_user_message,
                latest_assistant_message=previous_latest_assistant_message,
                resolution_history=history_resolutions,
            )
            raise
        result = self.get_knowledge_session(session_id=session_id)
        if result is None:
            raise ValueError("session_id 不存在")
        result["knowledge_markdown_status"] = "running"
        return result
