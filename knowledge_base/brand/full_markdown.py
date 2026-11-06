from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
import re
from time import perf_counter
from typing import TYPE_CHECKING, Any

from knowledge_base.brand_knowledge.ai import (
    generate_brand_ai_knowledge_from_merged_sources,
    generate_brand_ai_knowledge_from_structured_change,
    generate_brand_ai_knowledge_from_structured_deletion,
    generate_brand_ai_knowledge_from_structured_update,
    generate_brand_ai_knowledge_patch_from_structured_update,
    generate_brand_knowledge_round,
)
from knowledge_base.shared.utils import parse_metadata_json
from knowledge_base.brand.full_knowledge_baseline import (
    brand_multi_value as _brand_multi_value,
    build_structured_baseline_markdown as _build_structured_baseline_markdown,
    load_conflicts as _load_conflicts,
    normalize_multi_value as _normalize_multi_value,
    normalize_websites as _normalize_websites,
    parse_json_value as _parse_json_value,
    render_json_section as _render_json_section,
    render_structured_baseline_fallback as _render_structured_baseline_fallback,
    render_value as _render_value,
)
from knowledge_base.brand.full_knowledge_filenames import (
    build_brand_full_knowledge_filename,
    build_brand_full_knowledge_oss_key,
    build_brand_full_knowledge_pdf_filename,
)
from knowledge_base.brand.full_knowledge_pdf_renderer import (
    _build_playwright_pdf_error_message,
    _collect_pdf_renderer_diagnostics,
    _format_pdf_renderer_diagnostics,
    _markdown_to_html_blocks,
    _normalize_pdf_display_formula_token,
    _normalize_pdf_display_units,
    _render_inline_markdown,
    _render_markdown_to_html_document,
    render_brand_full_knowledge_pdf_bytes,
)
from knowledge_base.brand.full_knowledge_persistence import (
    build_existing_full_knowledge_payload as _build_existing_full_knowledge_payload,
    create_brand_full_knowledge_file as _create_brand_full_knowledge_file,
    delete_oss_object_if_possible as _delete_oss_object_if_possible,
    get_full_knowledge_by_brand_task as _get_full_knowledge_by_brand_task,
    get_latest_full_knowledge as _get_latest_full_knowledge,
    get_next_full_knowledge_version_no as _get_next_full_knowledge_version_no,
    persist_brand_full_knowledge_markdown,
    store_supports_brand_code_create as _store_supports_brand_code_create,
)

if TYPE_CHECKING:
    from knowledge_base.service import KnowledgeBaseService


logger = logging.getLogger(__name__)
_FULL_MARKDOWN_RETRY_DELAYS_SECONDS = (1, 2, 4)
_PATCH_MARKDOWN_RETRY_DELAYS_SECONDS = (10, 20)


def _filter_structured_markdown_for_deleted_sections(
    structured_markdown: str,
    *,
    deleted_sections: list[str] | None = None,
) -> str:
    normalized_markdown = str(structured_markdown or "").strip()
    normalized_deleted_sections = {
        str(section or "").strip()
        for section in deleted_sections or []
        if str(section or "").strip()
    }
    if not normalized_markdown or not normalized_deleted_sections:
        return normalized_markdown

    blocks = normalized_markdown.split("\n## ")
    header_block = blocks[0].strip()
    kept_blocks: list[str] = [header_block] if header_block else []

    for raw_block in blocks[1:]:
        block = "## " + raw_block.strip()
        if block.startswith("## 本次明确删除或收缩的 section"):
            kept_blocks.append(block)
            continue
        match = re.search(r"- section：`([^`]+)`", block)
        if match and str(match.group(1) or "").strip() in normalized_deleted_sections:
            kept_blocks.append(block)

    return "\n\n".join(part for part in kept_blocks if part).strip()


def _filter_structured_markdown_for_non_deleted_sections(
    structured_markdown: str,
    *,
    deleted_sections: list[str] | None = None,
) -> str:
    normalized_markdown = str(structured_markdown or "").strip()
    normalized_deleted_sections = {
        str(section or "").strip()
        for section in deleted_sections or []
        if str(section or "").strip()
    }
    if not normalized_markdown:
        return ""
    if not normalized_deleted_sections:
        return normalized_markdown

    blocks = normalized_markdown.split("\n## ")
    header_block = blocks[0].strip()
    kept_blocks: list[str] = []

    for raw_block in blocks[1:]:
        block = "## " + raw_block.strip()
        if block.startswith("## 本次明确删除或收缩的 section"):
            continue
        match = re.search(r"- section：`([^`]+)`", block)
        if match and str(match.group(1) or "").strip() not in normalized_deleted_sections:
            kept_blocks.append(block)

    if not kept_blocks:
        return ""
    return "\n\n".join(
        part
        for part in ([header_block] + kept_blocks)
        if part
    ).strip()


def _classify_structured_update_mode(
    *,
    deleted_sections: list[str] | None = None,
    non_deleted_structured_markdown: str = "",
) -> str:
    normalized_deleted_sections = [
        str(section or "").strip()
        for section in deleted_sections or []
        if str(section or "").strip()
    ]
    if not normalized_deleted_sections:
        return "update"
    return "change" if str(non_deleted_structured_markdown or "").strip() else "delete"


def _should_use_structured_update_patch(
    *,
    base_markdown: str,
    structured_knowledge_markdown: str,
    update_reason: str,
) -> bool:
    normalized_update_reason = str(update_reason or "knowledge_update").strip() or "knowledge_update"
    if normalized_update_reason == "attachment_confirm":
        return False
    return bool(str(base_markdown or "").strip() and str(structured_knowledge_markdown or "").strip())


def has_structured_brand_task_inputs(task_metadata: dict[str, Any]) -> bool:
    if not isinstance(task_metadata, dict):
        return False

    for key in ("intro", "brand_enterprise_entity"):
        if str(task_metadata.get(key) or "").strip():
            return True

    websites = task_metadata.get("website")
    if isinstance(websites, list) and any(str(item).strip() for item in websites):
        return True

    competitors = task_metadata.get("competitors")
    if isinstance(competitors, list) and any(str(item).strip() for item in competitors):
        return True

    task_payload = task_metadata.get("_task_payload")
    if not isinstance(task_payload, dict):
        return False

    requested_products = task_payload.get("requested_products")
    if not isinstance(requested_products, list):
        return False

    for product in requested_products:
        if not isinstance(product, dict):
            continue
        if any(
            str(product.get(field) or "").strip()
            for field in ("product_name", "product_alias", "product_description", "product_website")
        ):
            return True
        images = product.get("product_images")
        if isinstance(images, list) and any(str(item).strip() for item in images):
            return True
        product_competitors = product.get("competitors")
        if isinstance(product_competitors, list) and any(
            isinstance(item, dict) and str(item.get("name") or "").strip()
            for item in product_competitors
        ):
            return True

    return False


async def _persist_brand_full_knowledge_markdown(
    service: KnowledgeBaseService,
    *,
    brand_id: int,
    brand_code: str,
    brand_name: str,
    final_markdown: str,
    conflicts: list[dict[str, Any]] | None,
    source_task_id: str | None,
    upload_error_prefix: str,
    change_origin: str = "frontend",
) -> dict[str, Any]:
    return await persist_brand_full_knowledge_markdown(
        service,
        brand_id=brand_id,
        brand_code=brand_code,
        brand_name=brand_name,
        final_markdown=final_markdown,
        conflicts=conflicts,
        source_task_id=source_task_id,
        upload_error_prefix=upload_error_prefix,
        render_pdf_bytes=render_brand_full_knowledge_pdf_bytes,
        load_conflicts=_load_conflicts,
        change_origin=change_origin,
    )


async def build_full_brand_knowledge_markdown_from_confirmed_markdown(
    service: KnowledgeBaseService,
    *,
    brand_name: str,
    confirmed_markdown: str,
    supplemental_markdown_sources: list[dict[str, Any]] | None = None,
    source_task_id: str | None = None,
    change_origin: str = "api",
) -> dict[str, Any]:
    generated_payload = await generate_full_brand_knowledge_markdown_from_confirmed_markdown(
        service,
        brand_name=brand_name,
        confirmed_markdown=confirmed_markdown,
        supplemental_markdown_sources=supplemental_markdown_sources,
        source_task_id=source_task_id,
    )
    return await _persist_brand_full_knowledge_markdown(
        service,
        brand_id=int(generated_payload["brand_id"]),
        brand_code=str(generated_payload["brand_code"]),
        brand_name=str(generated_payload["brand_name"]),
        final_markdown=str(generated_payload["knowledge_markdown"]),
        conflicts=[],
        source_task_id=source_task_id,
        upload_error_prefix="增量品牌知识库",
        change_origin=change_origin,
    )


async def generate_full_brand_knowledge_markdown_from_confirmed_markdown(
    service: KnowledgeBaseService,
    *,
    brand_name: str,
    confirmed_markdown: str,
    supplemental_markdown_sources: list[dict[str, Any]] | None = None,
    source_task_id: str | None = None,
    change_origin: str = "api",
) -> dict[str, Any]:
    normalized_brand_name = str(brand_name or "").strip()
    normalized_confirmed_markdown = str(confirmed_markdown or "").strip()
    if not normalized_brand_name:
        raise ValueError("brand_name 不能为空")
    if not normalized_confirmed_markdown:
        raise ValueError("confirmed_markdown 不能为空")

    brand = service._brands.get_brand_by_name(normalized_brand_name)
    if not brand or brand.get("id") is None:
        raise ValueError(f"品牌不存在 brand_name={normalized_brand_name}")
    brand_id = int(brand["id"])
    brand_code = str(brand.get("brand_code") or "").strip()
    if not brand_code:
        raise ValueError(f"品牌缺少 brand_code brand_name={normalized_brand_name}")

    latest = _get_latest_full_knowledge(
        service,
        brand=brand,
        brand_code=brand_code,
    )
    base_markdown = str((latest or {}).get("content_markdown") or "").strip()
    if not base_markdown:
        base_markdown = await _build_structured_baseline_markdown(service, brand=brand)
    if not base_markdown:
        raise ValueError(f"品牌缺少可用的全量知识库基线 brand_name={normalized_brand_name}")

    markdown_sources = [
        {
            "source_name": f"{normalized_brand_name}-confirmed-knowledge.md",
            "subcategory": "confirmed_knowledge",
            "markdown_text": normalized_confirmed_markdown,
        },
        *(supplemental_markdown_sources or []),
    ]

    final_markdown = ""
    last_error: Exception | None = None
    for attempt_no, delay_seconds in enumerate(_FULL_MARKDOWN_RETRY_DELAYS_SECONDS, start=1):
        try:
            final_payload = await generate_brand_knowledge_round(
                brand_name=normalized_brand_name,
                markdown_sources=markdown_sources,
                base_knowledge_markdown=base_markdown,
                settings=service._settings,
            )
            final_markdown = str(final_payload.get("final_markdown") or "").strip()
            if not final_markdown:
                raise ValueError("未生成有效的增量品牌知识库 Markdown")
            last_error = None
            break
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.warning(
                "Incremental brand markdown generation failed brand_name=%s attempt=%s/%s error=%s",
                normalized_brand_name,
                attempt_no,
                len(_FULL_MARKDOWN_RETRY_DELAYS_SECONDS),
                exc,
                exc_info=True,
            )
            if attempt_no >= len(_FULL_MARKDOWN_RETRY_DELAYS_SECONDS):
                break
            await asyncio.sleep(delay_seconds)

    if last_error is not None:
        raise ValueError(
            f"增量品牌知识库 Markdown 生成失败，已重试 {len(_FULL_MARKDOWN_RETRY_DELAYS_SECONDS)} 次: {last_error}"
        ) from last_error

    version_no = _get_next_full_knowledge_version_no(
        service,
        brand={"id": brand_id, "brand_code": brand_code},
        brand_code=brand_code,
    )
    file_name = build_brand_full_knowledge_filename(
        brand_name=normalized_brand_name,
        version_no=version_no,
    )
    return {
        "brand_id": brand_id,
        "brand_code": brand_code,
        "brand_name": normalized_brand_name,
        "version_no": version_no,
        "file_name": file_name,
        "knowledge_markdown": final_markdown,
        "source_task_id": source_task_id,
        "change_origin": change_origin,
    }


async def build_full_brand_knowledge_markdown_from_update(
    service: KnowledgeBaseService,
    *,
    brand_name: str,
    structured_knowledge_markdown: str = "",
    update_reason: str = "knowledge_update",
    source_task_id: str | None = None,
    change_origin: str = "api",
    knowledge_revision: str | None = None,
    deleted_sections: list[str] | None = None,
) -> dict[str, Any]:
    generated_payload = await generate_full_brand_knowledge_markdown_from_update(
        service,
        brand_name=brand_name,
        structured_knowledge_markdown=structured_knowledge_markdown,
        update_reason=update_reason,
        source_task_id=source_task_id,
        change_origin=change_origin,
        knowledge_revision=knowledge_revision,
        deleted_sections=deleted_sections,
    )
    return await _persist_brand_full_knowledge_markdown(
        service,
        brand_id=int(generated_payload["brand_id"]),
        brand_code=str(generated_payload["brand_code"]),
        brand_name=str(generated_payload["brand_name"]),
        final_markdown=str(generated_payload["knowledge_markdown"]),
        conflicts=[],
        source_task_id=source_task_id,
        upload_error_prefix="新版品牌 AI 知识库",
        change_origin=change_origin,
    )


async def generate_full_brand_knowledge_markdown_from_update(
    service: KnowledgeBaseService,
    *,
    brand_name: str,
    structured_knowledge_markdown: str = "",
    update_reason: str = "knowledge_update",
    source_task_id: str | None = None,
    change_origin: str = "api",
    knowledge_revision: str | None = None,
    deleted_sections: list[str] | None = None,
) -> dict[str, Any]:
    started_at = perf_counter()
    normalized_brand_name = str(brand_name or "").strip()
    if not normalized_brand_name:
        raise ValueError("brand_name 不能为空")

    brand = service._brands.get_brand_by_name(normalized_brand_name)
    if not brand or brand.get("id") is None:
        raise ValueError(f"品牌不存在 brand_name={normalized_brand_name}")
    brand_id = int(brand["id"])
    brand_code = str(brand.get("brand_code") or "").strip()
    if not brand_code:
        raise ValueError(f"品牌缺少 brand_code brand_name={normalized_brand_name}")

    latest = _get_latest_full_knowledge(
        service,
        brand=brand,
        brand_code=brand_code,
    )
    base_markdown = str((latest or {}).get("content_markdown") or "").strip()
    normalized_structured_markdown = str(structured_knowledge_markdown or "").strip()
    if not normalized_structured_markdown:
        raise ValueError("structured_knowledge_markdown 不能为空")
    if not base_markdown and not normalized_structured_markdown:
        raise ValueError(f"品牌缺少可用的结构化知识基线 brand_name={normalized_brand_name}")

    final_markdown = ""
    last_error: Exception | None = None
    has_deletions = bool(deleted_sections)
    deletion_only_structured_markdown = (
        _filter_structured_markdown_for_deleted_sections(
            normalized_structured_markdown,
            deleted_sections=deleted_sections,
        )
        if has_deletions
        else normalized_structured_markdown
    )
    non_deleted_structured_markdown = (
        _filter_structured_markdown_for_non_deleted_sections(
            normalized_structured_markdown,
            deleted_sections=deleted_sections,
        )
        if has_deletions
        else normalized_structured_markdown
    )
    has_non_deleted_updates = bool(non_deleted_structured_markdown)
    structured_update_mode = _classify_structured_update_mode(
        deleted_sections=deleted_sections,
        non_deleted_structured_markdown=non_deleted_structured_markdown,
    )
    should_try_patch_update = _should_use_structured_update_patch(
        base_markdown=base_markdown,
        structured_knowledge_markdown=normalized_structured_markdown,
        update_reason=update_reason,
    )
    logger.info(
        "knowledge/update LLM dispatch brand_id=%s brand_code=%s brand_name=%s mode=%s update_reason=%s patch_candidate=%s deleted_sections=%s previous_chars=%s structured_chars=%s",
        brand_id,
        brand_code,
        normalized_brand_name,
        structured_update_mode,
        update_reason,
        should_try_patch_update,
        json.dumps(deleted_sections or [], ensure_ascii=False),
        len(base_markdown),
        len(normalized_structured_markdown),
    )

    async def _generate_full_markdown_payload() -> dict[str, Any]:
        if update_reason == "brand_full_knowledge_refresh":
            return await generate_brand_ai_knowledge_from_merged_sources(
                brand_name=normalized_brand_name,
                previous_ai_knowledge_markdown=base_markdown,
                structured_knowledge_markdown=normalized_structured_markdown,
                knowledge_revision=knowledge_revision or str(brand.get("knowledge_revision") or "").strip(),
                update_reason=update_reason,
                settings=service._settings,
                deleted_sections=deleted_sections or [],
            )
        if has_deletions and has_non_deleted_updates:
            return await generate_brand_ai_knowledge_from_structured_change(
                brand_name=normalized_brand_name,
                previous_ai_knowledge_markdown=base_markdown,
                structured_knowledge_markdown=normalized_structured_markdown,
                knowledge_revision=knowledge_revision or str(brand.get("knowledge_revision") or "").strip(),
                update_reason=update_reason,
                settings=service._settings,
                deleted_sections=deleted_sections or [],
            )
        if has_deletions:
            return await generate_brand_ai_knowledge_from_structured_deletion(
                brand_name=normalized_brand_name,
                previous_ai_knowledge_markdown=base_markdown,
                structured_knowledge_markdown=deletion_only_structured_markdown,
                knowledge_revision=knowledge_revision or str(brand.get("knowledge_revision") or "").strip(),
                update_reason=update_reason,
                settings=service._settings,
                deleted_sections=deleted_sections or [],
            )
        return await generate_brand_ai_knowledge_from_structured_update(
            brand_name=normalized_brand_name,
            previous_ai_knowledge_markdown=base_markdown,
            structured_knowledge_markdown=normalized_structured_markdown,
            knowledge_revision=knowledge_revision or str(brand.get("knowledge_revision") or "").strip(),
            update_reason=update_reason,
            settings=service._settings,
        )

    generation_strategies = ("patch", "full_fallback") if should_try_patch_update else ("full",)
    for generation_strategy in generation_strategies:
        retry_delays_seconds = (
            _PATCH_MARKDOWN_RETRY_DELAYS_SECONDS
            if generation_strategy == "patch"
            else _FULL_MARKDOWN_RETRY_DELAYS_SECONDS[:-1]
        )
        max_attempts = len(retry_delays_seconds) + 1
        for attempt_no in range(1, max_attempts + 1):
            try:
                llm_started_at = perf_counter()
                if generation_strategy == "patch":
                    final_payload = await generate_brand_ai_knowledge_patch_from_structured_update(
                        brand_name=normalized_brand_name,
                        previous_ai_knowledge_markdown=base_markdown,
                        structured_knowledge_markdown=normalized_structured_markdown,
                        knowledge_revision=knowledge_revision or str(brand.get("knowledge_revision") or "").strip(),
                        update_reason=update_reason,
                        settings=service._settings,
                        deleted_sections=deleted_sections or [],
                    )
                else:
                    final_payload = await _generate_full_markdown_payload()
                final_markdown = str(final_payload.get("final_markdown") or "").strip()
                if not final_markdown:
                    raise ValueError("未生成有效的新版品牌 AI 知识库 Markdown")
                logger.info(
                    "AI knowledge update LLM completed brand_name=%s attempt=%s strategy=%s seconds=%.3f previous_chars=%s structured_chars=%s supplemental_count=%s has_deletions=%s",
                    normalized_brand_name,
                    attempt_no,
                    generation_strategy,
                    perf_counter() - llm_started_at,
                    len(base_markdown),
                    len(normalized_structured_markdown),
                    0,
                    has_deletions,
                )
                last_error = None
                break
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning(
                    "Updated brand AI knowledge generation failed brand_name=%s strategy=%s attempt=%s/%s error=%s",
                    normalized_brand_name,
                    generation_strategy,
                    attempt_no,
                    max_attempts,
                    exc,
                    exc_info=True,
                )
                if attempt_no >= max_attempts:
                    break
                await asyncio.sleep(retry_delays_seconds[attempt_no - 1])
        if last_error is None:
            break
        if generation_strategy == "patch":
            logger.warning(
                "Structured update patch generation exhausted, falling back to full generation brand_name=%s attempts=%s",
                normalized_brand_name,
                max_attempts,
            )

    if last_error is not None:
        raise ValueError(
            f"新版品牌 AI 知识库 Markdown 生成失败，已重试 {len(_FULL_MARKDOWN_RETRY_DELAYS_SECONDS)} 次: {last_error}"
        ) from last_error

    version_no = _get_next_full_knowledge_version_no(
        service,
        brand={"id": brand_id, "brand_code": brand_code},
        brand_code=brand_code,
    )
    file_name = build_brand_full_knowledge_filename(
        brand_name=normalized_brand_name,
        version_no=version_no,
    )
    logger.info(
        "AI knowledge update markdown generated brand_name=%s source_task_id=%s total_seconds=%.3f",
        normalized_brand_name,
        source_task_id,
        perf_counter() - started_at,
    )
    return {
        "brand_id": brand_id,
        "brand_code": brand_code,
        "brand_name": normalized_brand_name,
        "version_no": version_no,
        "file_name": file_name,
        "knowledge_markdown": final_markdown,
        "source_task_id": source_task_id,
        "change_origin": change_origin,
    }
