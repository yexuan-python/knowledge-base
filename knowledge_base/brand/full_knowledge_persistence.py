from __future__ import annotations

import asyncio
import inspect
import logging
from time import perf_counter
from typing import TYPE_CHECKING, Any, Awaitable, Callable

import pymysql

from knowledge_base.brand.full_knowledge_filenames import (
    build_brand_full_knowledge_filename,
    build_brand_full_knowledge_oss_key,
    build_brand_full_knowledge_pdf_filename,
)

if TYPE_CHECKING:
    from knowledge_base.service import KnowledgeBaseService


logger = logging.getLogger(__name__)
RenderPdfBytes = Callable[..., Awaitable[bytes]]


def build_existing_full_knowledge_payload(
    service: KnowledgeBaseService,
    *,
    existing: dict[str, Any],
    load_conflicts: Callable[[Any], list[dict[str, Any]]],
) -> dict[str, Any]:
    existing_oss_key_md = str(existing.get("oss_key") or "").strip()
    existing_oss_url_md = str(existing.get("oss_url") or "").strip() or None
    existing_pdf_file_name = str(existing.get("pdf_file_name") or "").strip() or None
    existing_oss_key_pdf = str(existing.get("pdf_oss_key") or "").strip() or None
    existing_oss_url_pdf = str(existing.get("pdf_oss_url") or "").strip() or None
    if service.oss_client.enabled and existing_oss_key_md:
        existing_oss_url_md = service.oss_client.build_object_url(existing_oss_key_md)
    if service.oss_client.enabled and existing_oss_key_pdf:
        existing_oss_url_pdf = service.oss_client.build_object_url(existing_oss_key_pdf)
    return {
        "brand_id": int(existing.get("brand_id") or 0),
        "brand_code": str(existing.get("brand_code") or "").strip() or None,
        "brand_name": str(existing.get("brand_name") or ""),
        "version_no": int(existing.get("version_no") or 1),
        "file_name": str(existing.get("file_name") or ""),
        "pdf_file_name": existing_pdf_file_name,
        "knowledge_markdown": str(existing.get("content_markdown") or ""),
        "knowledge_oss_key_md": existing_oss_key_md or None,
        "knowledge_oss_url_md": existing_oss_url_md,
        "knowledge_oss_key_pdf": existing_oss_key_pdf,
        "knowledge_oss_url_pdf": existing_oss_url_pdf,
        "conflicts": load_conflicts(existing.get("conflicts_json")),
        "change_origin": str(existing.get("change_origin") or "").strip() or None,
    }


def get_full_knowledge_by_brand_task(
    service: KnowledgeBaseService,
    *,
    brand: dict[str, Any],
    brand_code: str,
    source_task_id: str,
) -> dict[str, Any] | None:
    store = service._brand_full_knowledge
    if hasattr(store, "get_by_brand_code_and_task_id") and brand_code:
        return store.get_by_brand_code_and_task_id(
            brand_code=brand_code,
            source_task_id=source_task_id,
        )
    brand_id = brand.get("id")
    if brand_id is not None and hasattr(store, "get_by_brand_id_and_task_id"):
        return store.get_by_brand_id_and_task_id(
            brand_id=int(brand_id),
            source_task_id=source_task_id,
        )
    return None


def get_latest_full_knowledge(
    service: KnowledgeBaseService,
    *,
    brand: dict[str, Any],
    brand_code: str,
) -> dict[str, Any] | None:
    store = service._brand_full_knowledge
    if hasattr(store, "get_latest_by_brand_code") and brand_code:
        return store.get_latest_by_brand_code(brand_code=brand_code)
    brand_id = brand.get("id")
    if brand_id is not None and hasattr(store, "get_latest_by_brand_id"):
        return store.get_latest_by_brand_id(brand_id=int(brand_id))
    return None


def get_next_full_knowledge_version_no(
    service: KnowledgeBaseService,
    *,
    brand: dict[str, Any],
    brand_code: str,
) -> int:
    store = service._brand_full_knowledge
    if hasattr(store, "get_next_version_no_by_brand_code") and brand_code:
        return store.get_next_version_no_by_brand_code(brand_code=brand_code)
    brand_id = brand.get("id")
    if brand_id is None or not hasattr(store, "get_next_version_no"):
        raise ValueError(f"无法确定品牌版本号 brand_code={brand_code}")
    return store.get_next_version_no(brand_id=int(brand_id))


def store_supports_brand_code_create(store: Any) -> bool:
    create_method = getattr(store, "create_brand_full_knowledge_file", None)
    if create_method is None:
        return False
    try:
        signature = inspect.signature(create_method)
    except (TypeError, ValueError):
        return True
    return "brand_code" in signature.parameters


def store_supports_change_origin_create(store: Any) -> bool:
    create_method = getattr(store, "create_brand_full_knowledge_file", None)
    if create_method is None:
        return False
    try:
        signature = inspect.signature(create_method)
    except (TypeError, ValueError):
        return True
    return "change_origin" in signature.parameters


def create_brand_full_knowledge_file(
    service: KnowledgeBaseService,
    *,
    brand_id: int,
    brand_code: str,
    brand_name: str,
    version_no: int,
    pdf_file_name: str | None,
    file_name: str,
    oss_key: str | None,
    oss_url: str | None,
    pdf_oss_key: str | None,
    pdf_oss_url: str | None,
    content_markdown: str,
    conflict_count: int,
    conflicts_json: Any,
    source_task_id: str | None,
    change_origin: str = "frontend",
) -> int:
    payload = {
        "brand_id": brand_id,
        "brand_name": brand_name,
        "version_no": version_no,
        "file_name": file_name,
        "pdf_file_name": pdf_file_name,
        "oss_key": oss_key,
        "oss_url": oss_url,
        "pdf_oss_key": pdf_oss_key,
        "pdf_oss_url": pdf_oss_url,
        "content_markdown": content_markdown,
        "conflict_count": conflict_count,
        "conflicts_json": conflicts_json,
        "source_task_id": source_task_id,
    }
    store = service._brand_full_knowledge
    if store_supports_brand_code_create(store):
        payload["brand_code"] = brand_code
    if store_supports_change_origin_create(store):
        payload["change_origin"] = change_origin
    return store.create_brand_full_knowledge_file(**payload)


async def delete_oss_object_if_possible(service: KnowledgeBaseService, object_key: str | None) -> bool:
    normalized_key = str(object_key or "").strip()
    if not normalized_key:
        return False
    delete_object = getattr(service.oss_client, "delete_object", None)
    if delete_object is None:
        return False
    return bool(await asyncio.to_thread(delete_object, normalized_key))


async def persist_brand_full_knowledge_markdown(
    service: KnowledgeBaseService,
    *,
    brand_id: int,
    brand_code: str,
    brand_name: str,
    final_markdown: str,
    conflicts: list[dict[str, Any]] | None,
    source_task_id: str | None,
    upload_error_prefix: str,
    render_pdf_bytes: RenderPdfBytes,
    load_conflicts: Callable[[Any], list[dict[str, Any]]],
    change_origin: str = "frontend",
) -> dict[str, Any]:
    version_no = get_next_full_knowledge_version_no(
        service,
        brand={"id": brand_id, "brand_code": brand_code},
        brand_code=brand_code,
    )
    file_name = build_brand_full_knowledge_filename(
        brand_name=brand_name,
        version_no=version_no,
    )
    pdf_file_name = build_brand_full_knowledge_pdf_filename(markdown_file_name=file_name)
    oss_key = build_brand_full_knowledge_oss_key(
        brand_name=brand_name,
        file_name=file_name,
    )
    pdf_oss_key = build_brand_full_knowledge_oss_key(
        brand_name=brand_name,
        file_name=pdf_file_name,
    )
    persist_started_at = perf_counter()
    pdf_started_at = perf_counter()
    pdf_bytes = await render_pdf_bytes(
        final_markdown,
        title=file_name,
        settings=service._settings,
    )
    pdf_elapsed = perf_counter() - pdf_started_at
    oss_url = None
    pdf_oss_url = None
    uploaded_key = None
    uploaded_pdf_key = None
    if service.oss_client.enabled:
        md_upload_started_at = perf_counter()
        uploaded_key = await asyncio.to_thread(
            service.oss_client.upload_bytes,
            final_markdown.encode("utf-8"),
            oss_key,
            "text/markdown; charset=utf-8",
        )
        if not uploaded_key:
            raise ValueError(f"{upload_error_prefix} Markdown 上传 OSS 失败")
        oss_url = service.oss_client.build_object_url(uploaded_key)
        md_upload_elapsed = perf_counter() - md_upload_started_at
        pdf_upload_started_at = perf_counter()
        uploaded_pdf_key = await asyncio.to_thread(
            service.oss_client.upload_bytes,
            pdf_bytes,
            pdf_oss_key,
            "application/pdf",
        )
        if not uploaded_pdf_key:
            if uploaded_key:
                await delete_oss_object_if_possible(service, uploaded_key)
            raise ValueError(f"{upload_error_prefix} PDF 上传 OSS 失败")
        pdf_oss_url = service.oss_client.build_object_url(uploaded_pdf_key)
        pdf_upload_elapsed = perf_counter() - pdf_upload_started_at
    else:
        md_upload_elapsed = 0.0
        pdf_upload_elapsed = 0.0

    db_started_at = perf_counter()
    normalized_conflicts = conflicts or []
    try:
        create_brand_full_knowledge_file(
            service,
            brand_id=brand_id,
            brand_code=brand_code,
            brand_name=brand_name,
            version_no=version_no,
            file_name=file_name,
            pdf_file_name=pdf_file_name,
            oss_key=oss_key if service.oss_client.enabled else None,
            oss_url=oss_url,
            pdf_oss_key=pdf_oss_key if service.oss_client.enabled else None,
            pdf_oss_url=pdf_oss_url,
            content_markdown=final_markdown,
            conflict_count=len(normalized_conflicts),
            conflicts_json=normalized_conflicts,
            source_task_id=source_task_id,
            change_origin=change_origin,
        )
    except pymysql.err.IntegrityError:
        if source_task_id:
            existing = get_full_knowledge_by_brand_task(
                service,
                brand={"id": brand_id, "brand_code": brand_code},
                brand_code=brand_code,
                source_task_id=source_task_id,
            )
            if existing:
                existing_oss_key = str(existing.get("oss_key") or "").strip()
                existing_pdf_oss_key = str(existing.get("pdf_oss_key") or "").strip()
                if service.oss_client.enabled:
                    if uploaded_key and uploaded_key != existing_oss_key:
                        await delete_oss_object_if_possible(service, uploaded_key)
                    if uploaded_pdf_key and uploaded_pdf_key != existing_pdf_oss_key:
                        await delete_oss_object_if_possible(service, uploaded_pdf_key)
                return build_existing_full_knowledge_payload(
                    service,
                    existing=existing,
                    load_conflicts=load_conflicts,
                )
        if service.oss_client.enabled:
            if uploaded_key:
                await delete_oss_object_if_possible(service, uploaded_key)
            if uploaded_pdf_key:
                await delete_oss_object_if_possible(service, uploaded_pdf_key)
        raise
    except Exception:
        if service.oss_client.enabled:
            if uploaded_key:
                await delete_oss_object_if_possible(service, uploaded_key)
            if uploaded_pdf_key:
                await delete_oss_object_if_possible(service, uploaded_pdf_key)
        raise
    db_elapsed = perf_counter() - db_started_at
    logger.info(
        "Brand full knowledge persisted brand_name=%s source_task_id=%s version_no=%s pdf_render_seconds=%.3f md_upload_seconds=%.3f pdf_upload_seconds=%.3f db_seconds=%.3f total_seconds=%.3f markdown_chars=%s pdf_bytes=%s",
        brand_name,
        source_task_id,
        version_no,
        pdf_elapsed,
        md_upload_elapsed,
        pdf_upload_elapsed,
        db_elapsed,
        perf_counter() - persist_started_at,
        len(final_markdown),
        len(pdf_bytes),
    )
    return {
        "brand_id": brand_id,
        "brand_code": brand_code,
        "brand_name": brand_name,
        "version_no": version_no,
        "file_name": file_name,
        "pdf_file_name": pdf_file_name,
        "knowledge_markdown": final_markdown,
        "knowledge_oss_key_md": oss_key if service.oss_client.enabled else None,
        "knowledge_oss_url_md": oss_url,
        "knowledge_oss_key_pdf": pdf_oss_key if service.oss_client.enabled else None,
        "knowledge_oss_url_pdf": pdf_oss_url,
        "conflicts": normalized_conflicts,
        "change_origin": str(change_origin or "").strip() or None,
    }
