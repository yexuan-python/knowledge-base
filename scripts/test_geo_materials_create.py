#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
import random
import re
import sys
import time
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


MAX_UPLOAD_FILES = 10
IMAGE_MAX_BYTES = 5 * 1024 * 1024
IMAGE_TARGET_BYTES = int(4.5 * 1024 * 1024)
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".heic", ".heif"}

mimetypes.add_type("image/heic", ".heic")
mimetypes.add_type("image/heif", ".heif")


@dataclass(frozen=True)
class PreparedUpload:
    original_path: Path
    upload_path: Path
    upload_filename: str
    mime_type: str
    field_name: str
    item: dict[str, Any]
    cleanup_upload_path: bool


@dataclass(frozen=True)
class BatchExecutionResult:
    batch_index: int
    batch_count: int
    file_count: int
    ok: bool
    status_code: int | None
    response_body: Any
    success_files: list[dict[str, Any]]
    failed_files: list[dict[str, Any]]
    deleted_files: list[str]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "测试 `POST /api/assets/manual-upload` 的素材上传。"
            "支持手工传单/多文件，也支持读取目录后自动压缩图片、调用 LLM 生成描述和标签后逐张上传。"
        )
    )
    parser.add_argument(
        "--endpoint",
        default="http://127.0.0.1:9067/api/assets/manual-upload",
        help="接口地址，默认使用本地 `manual-upload` 接口。",
    )
    parser.add_argument(
        "--brand-code",
        required=True,
        help="兼容旧脚本保留；默认会映射为请求头 `X-Tenant-Id`，例如 `100052`。",
    )
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--file",
        action="append",
        type=Path,
        help="要上传的文件路径，可重复传入，最多 10 个。",
    )
    source_group.add_argument(
        "--dir",
        type=Path,
        help="图片目录；脚本会读取目录下全部图片并自动压缩、识图、打标签，再按批次上传。",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=MAX_UPLOAD_FILES,
        help=f"目录自动模式下每批上传多少张，默认 {MAX_UPLOAD_FILES}，最大 {MAX_UPLOAD_FILES}。",
    )
    parser.add_argument(
        "--batch-interval-seconds",
        type=int,
        default=0,
        help="兼容旧参数保留；目录模式现在默认使用 3-9 秒随机等待，不再使用这个固定间隔。",
    )
    parser.add_argument(
        "--file-field",
        default="file_0",
        help="兼容旧脚本保留；`manual-upload` 实际固定发送为 `file`。",
    )
    parser.add_argument(
        "--asset-type",
        default="image",
        choices=("image", "video"),
        help="手工模式 items 中的 asset_type，默认 image。",
    )
    parser.add_argument(
        "--title",
        help="手工模式 items 中的 title；单文件不传时默认使用文件名。",
    )
    parser.add_argument(
        "--description",
        help="手工模式 items 中的 description。",
    )
    parser.add_argument(
        "--note",
        help="手工模式 items 中的 note。",
    )
    parser.add_argument(
        "--final-tags-json",
        help="手工模式 items 中 final_tags 的 JSON 字符串。",
    )
    parser.add_argument(
        "--batch-tag",
        action="append",
        default=[],
        help="可选；给本次上传的每张图片追加一个固定标签，可重复传入。",
    )
    parser.add_argument(
        "--batch-tags",
        help="可选；给本次上传的每张图片追加固定标签，逗号、顿号或换行分隔。",
    )
    parser.add_argument(
        "--items-json",
        help=(
            "手工模式可选；直接传完整 items JSON 字符串。"
            "可以传单个对象或数组；多文件时数组长度需要和文件数一致。"
        ),
    )
    parser.add_argument(
        "--category-hint",
        help="目录自动模式下传给 LLM 的分类提示；不传时默认使用 brand_code。",
    )
    parser.add_argument(
        "--subcategory-hint",
        help="目录自动模式下传给 LLM 的子分类提示。",
    )
    parser.add_argument(
        "--llm-model",
        help="目录自动模式下覆盖默认图片识别模型。",
    )
    parser.add_argument(
        "--llm-max-tags",
        type=int,
        help="目录自动模式下单图最多生成多少个标签；不传则使用项目默认配置。",
    )
    parser.add_argument(
        "--final-tags-dimension",
        default="scene",
        help="目录自动模式下自动生成 final_tags 时使用的维度，默认 `scene`。",
    )
    parser.add_argument(
        "--brand-id",
        help="兼容旧接口请求头；不传时默认使用 `brand_code`。",
    )
    parser.add_argument(
        "--tenant-id",
        help="可选；覆盖请求头 `X-Tenant-Id`。",
    )
    parser.add_argument(
        "--library-id",
        default="default",
        help="请求头 `X-Library-Id`，默认 `default`。",
    )
    parser.add_argument(
        "--user-id",
        help="可选；请求头 `X-User-Id`。",
    )
    parser.add_argument(
        "--authorization",
        help="可选；请求头 `Authorization`，例如 `Bearer xxx`。",
    )
    parser.add_argument(
        "--referer",
        default="https://geo-preview.heartbitai.com/settings/brand-management",
        help="可选；请求头 `Referer`。",
    )
    parser.add_argument(
        "--origin",
        default="https://geo-preview.heartbitai.com",
        help="可选；请求头 `Origin`。",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=60.0,
        help="请求超时时间，默认 60 秒。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将要发送的 headers / data / files，不实际发请求。",
    )
    parser.add_argument(
        "--result-json",
        type=Path,
        help="可选；把最终汇总结果写入指定 JSON 文件。",
    )
    parser.add_argument(
        "--delete-success-files",
        action="store_true",
        help="上传成功后删除原始图片；目录模式建议开启。",
    )
    return parser


def _normalize_optional_text(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _parse_json_payload(raw_value: str | None, *, field_name: str) -> Any | None:
    normalized = _normalize_optional_text(raw_value)
    if normalized is None:
        return None
    try:
        return json.loads(normalized)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field_name} 不是合法 JSON: {normalized}") from exc


def _parse_tag_values(raw_values: Any) -> list[str]:
    if raw_values is None:
        return []
    values = raw_values if isinstance(raw_values, list) else [raw_values]
    tags: list[str] = []
    for value in values:
        for part in re.split(r"[，,、\n]+", str(value or "")):
            tag = part.strip()
            if tag and tag not in tags:
                tags.append(tag)
    return tags


def _normalize_batch_tags(args: argparse.Namespace) -> list[str]:
    return _parse_tag_values([*(getattr(args, "batch_tag", None) or []), getattr(args, "batch_tags", None)])


def _build_headers(args: argparse.Namespace) -> dict[str, str]:
    tenant_id = _normalize_optional_text(args.tenant_id) or args.brand_code.strip()
    brand_id = _normalize_optional_text(args.brand_id) or args.brand_code.strip()
    headers = {"accept": "application/json, text/plain, */*"}
    authorization = _normalize_optional_text(args.authorization)
    if authorization is not None:
        headers["Authorization"] = authorization
    if tenant_id:
        headers["X-Tenant-Id"] = tenant_id
    if brand_id:
        headers["X-Brand-Id"] = brand_id
    library_id = _normalize_optional_text(args.library_id)
    if library_id is not None:
        headers["X-Library-Id"] = library_id
    user_id = _normalize_optional_text(args.user_id)
    if user_id is not None:
        headers["X-User-Id"] = user_id
    referer = _normalize_optional_text(args.referer)
    origin = _normalize_optional_text(args.origin)
    if referer is not None:
        headers["Referer"] = referer
    if origin is not None:
        headers["Origin"] = origin
    return headers


def _sanitize_headers_for_preview(headers: dict[str, str]) -> dict[str, str]:
    preview = dict(headers)
    if "Authorization" in preview:
        preview["Authorization"] = "<redacted>"
    return preview


def _is_image_path(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES


def _resolve_input_files(args: argparse.Namespace) -> list[Path]:
    if args.dir is not None:
        directory = args.dir
        if not directory.exists():
            raise ValueError(f"目录不存在: {directory}")
        if not directory.is_dir():
            raise ValueError(f"不是有效目录: {directory}")
        file_paths = sorted(path for path in directory.iterdir() if _is_image_path(path))
        if not file_paths:
            raise ValueError(f"目录下没有可上传图片: {directory}")
        return file_paths

    file_paths = list(args.file or [])
    if not file_paths:
        raise ValueError("至少需要传 1 个文件")
    if len(file_paths) > MAX_UPLOAD_FILES:
        raise ValueError(f"一次最多上传 {MAX_UPLOAD_FILES} 个文件")
    for file_path in file_paths:
        if not file_path.exists():
            raise ValueError(f"文件不存在: {file_path}")
        if not file_path.is_file():
            raise ValueError(f"不是有效文件: {file_path}")
    return file_paths


def _normalize_item(item: dict[str, Any], *, default_file_field: str) -> dict[str, Any]:
    normalized = dict(item)
    asset_type = str(normalized.get("asset_type") or "").strip()
    title = str(normalized.get("title") or "").strip()
    if not asset_type:
        raise ValueError("items 中缺少 asset_type")
    if not title:
        raise ValueError("items 中缺少 title")

    normalized["asset_type"] = asset_type
    normalized["title"] = title
    normalized["file_field"] = str(normalized.get("file_field") or "").strip() or default_file_field

    description = _normalize_optional_text(normalized.get("description"))
    if description is not None:
        normalized["description"] = description
    else:
        normalized.pop("description", None)

    note = _normalize_optional_text(normalized.get("note"))
    if note is not None:
        normalized["note"] = note
    else:
        normalized.pop("note", None)

    final_tags = normalized.get("final_tags")
    if isinstance(final_tags, str):
        parsed_final_tags = _parse_json_payload(final_tags, field_name="final_tags")
        normalized["final_tags"] = parsed_final_tags

    return normalized


def _build_manual_items_json(args: argparse.Namespace, *, file_paths: list[Path]) -> str:
    batch_tags = _normalize_batch_tags(args)
    dimension_code = _normalize_optional_text(args.final_tags_dimension) or "scene"
    parsed_items = _parse_json_payload(args.items_json, field_name="items")
    if parsed_items is not None:
        if isinstance(parsed_items, dict):
            parsed_items = [parsed_items]
        if not isinstance(parsed_items, list):
            raise ValueError("items 必须是对象或数组")
        if len(parsed_items) != len(file_paths):
            raise ValueError(f"items 数量必须和文件数一致，当前 items={len(parsed_items)} files={len(file_paths)}")

        normalized_items: list[dict[str, Any]] = []
        for index, item in enumerate(parsed_items):
            if not isinstance(item, dict):
                raise ValueError(f"items[{index}] 不是对象")
            fallback = args.file_field if len(file_paths) == 1 else f"file_{index}"
            normalized_item = _normalize_item(item, default_file_field=fallback)
            if batch_tags and "final_tags" in normalized_item:
                normalized_item["final_tags"] = _merge_final_tags(
                    normalized_item.get("final_tags"),
                    extra_tags=batch_tags,
                    dimension_code=dimension_code,
                )
            normalized_items.append(normalized_item)
        return json.dumps(normalized_items, ensure_ascii=False)

    if len(file_paths) > 1 and _normalize_optional_text(args.title) is not None:
        raise ValueError("多文件手工模式下请使用 --items-json 分别指定 title")

    description = _normalize_optional_text(args.description)
    note = _normalize_optional_text(args.note)
    final_tags = _parse_json_payload(args.final_tags_json, field_name="final_tags")
    items: list[dict[str, Any]] = []
    for index, file_path in enumerate(file_paths):
        file_field = args.file_field if len(file_paths) == 1 else f"file_{index}"
        item: dict[str, Any] = {
            "asset_type": args.asset_type,
            "title": _normalize_optional_text(args.title) or file_path.name,
            "file_field": file_field,
        }
        if description is not None:
            item["description"] = description
        if note is not None:
            item["note"] = note
        if final_tags is not None:
            item["final_tags"] = _merge_final_tags(
                final_tags,
                extra_tags=batch_tags,
                dimension_code=dimension_code,
            )
        items.append(item)
    return json.dumps(items, ensure_ascii=False)


def _extract_file_field_names(items_json: str, *, file_count: int, default_single_file_field: str) -> list[str]:
    parsed_items = json.loads(items_json)
    if not isinstance(parsed_items, list):
        raise ValueError("items 必须是数组")
    if len(parsed_items) != file_count:
        raise ValueError(f"items 数量必须和文件数一致，当前 items={len(parsed_items)} files={file_count}")

    field_names: list[str] = []
    for index, item in enumerate(parsed_items):
        if not isinstance(item, dict):
            raise ValueError(f"items[{index}] 不是对象")
        fallback = default_single_file_field if file_count == 1 else f"file_{index}"
        field_name = str(item.get("file_field") or "").strip() or fallback
        field_names.append(field_name)

    if len(set(field_names)) != len(field_names):
        raise ValueError("items 中的 file_field 不能重复")
    return field_names


def _build_tag_code(tag_name: str, *, index: int) -> str:
    normalized = re.sub(r"\s+", "_", tag_name.strip())
    normalized = re.sub(r"[^\w\u4e00-\u9fff-]+", "", normalized)
    normalized = normalized.strip("_-")
    return (normalized or f"tag_{index + 1}")[:128]


def _build_final_tags(tags: list[str], *, dimension_code: str) -> list[dict[str, Any]]:
    create_tags = [
        {
            "code": _build_tag_code(tag, index=index),
            "name": tag,
            "synopsis": "",
            "parent_id": None,
            "aliases": [],
        }
        for index, tag in enumerate(tags)
    ]
    return [
        {
            "dimension_code": dimension_code,
            "create_tags": create_tags,
        }
    ]


def _merge_final_tags(
    final_tags: Any,
    *,
    extra_tags: list[str],
    dimension_code: str,
) -> list[dict[str, Any]]:
    if not extra_tags:
        return final_tags if isinstance(final_tags, list) else []

    merged: list[dict[str, Any]] = []
    existing_names: set[str] = set()
    target_group: dict[str, Any] | None = None

    if isinstance(final_tags, list):
        for group in final_tags:
            if not isinstance(group, dict):
                continue
            copied_group = dict(group)
            create_tags = copied_group.get("create_tags")
            copied_create_tags = (
                [dict(item) for item in create_tags if isinstance(item, dict)]
                if isinstance(create_tags, list)
                else []
            )
            copied_group["create_tags"] = copied_create_tags
            for item in copied_create_tags:
                name = str(item.get("name") or "").strip()
                if name:
                    existing_names.add(name)
            if str(copied_group.get("dimension_code") or "").strip() == dimension_code and target_group is None:
                target_group = copied_group
            merged.append(copied_group)

    if target_group is None:
        target_group = {"dimension_code": dimension_code, "create_tags": []}
        merged.append(target_group)

    create_tags = target_group.setdefault("create_tags", [])
    if not isinstance(create_tags, list):
        create_tags = []
        target_group["create_tags"] = create_tags

    next_index = len(existing_names)
    for tag in extra_tags:
        if tag in existing_names:
            continue
        create_tags.append(
            {
                "code": _build_tag_code(tag, index=next_index),
                "name": tag,
                "synopsis": "",
                "parent_id": None,
                "aliases": [],
            }
        )
        existing_names.add(tag)
        next_index += 1

    return merged


def _resolve_upload_filename(original_path: Path, upload_path: Path) -> str:
    if upload_path == original_path:
        return original_path.name
    suffix = upload_path.suffix.lower() or ".jpg"
    return f"{original_path.stem}{suffix}"


def _resolve_image_content_type(path: Path, fallback_name: str) -> str:
    guessed_content_type = mimetypes.guess_type(path.name)[0]
    normalized_guessed = str(guessed_content_type or "").strip().lower()
    if normalized_guessed.startswith("image/"):
        return normalized_guessed
    fallback_content_type = mimetypes.guess_type(fallback_name)[0]
    normalized_fallback = str(fallback_content_type or "").strip().lower()
    if normalized_fallback.startswith("image/"):
        return normalized_fallback
    return "image/jpeg"


def _format_path_for_log(path: Path) -> str:
    return repr(str(path))


def _print_auto_image_progress(*, index: int, total: int, original_path: Path) -> None:
    print(
        f"自动识图中（第 {index + 1}/{total} 张）：{_format_path_for_log(original_path)}",
        file=sys.stderr,
        flush=True,
    )


def _print_auto_image_failure(*, index: int, total: int, original_path: Path, error: Exception) -> None:
    print(
        f"自动识图失败（第 {index + 1}/{total} 张）：{_format_path_for_log(original_path)}；错误：{error}",
        file=sys.stderr,
        flush=True,
    )


def _print_auto_image_skipped(*, index: int, total: int, original_path: Path, error: Exception) -> None:
    print(
        f"自动处理失败，已跳过（第 {index}/{total} 张）：{_format_path_for_log(original_path)}；错误：{error}",
        file=sys.stderr,
        flush=True,
    )


def _print_auto_skipped_summary(results: list[BatchExecutionResult]) -> None:
    skipped_files: list[dict[str, Any]] = []
    for result in results:
        for failed_file in result.failed_files:
            if failed_file.get("status") == "preprocess_failed":
                skipped_files.append(failed_file)

    if not skipped_files:
        return

    print("以下图片自动处理失败，需手动上传：", file=sys.stderr)
    for failed_file in skipped_files:
        path = failed_file.get("path") or failed_file.get("filename") or "<unknown>"
        message = failed_file.get("message") or ""
        print(f"- {path}: {message}", file=sys.stderr)


def _build_auto_preprocess_failed_result(
    *,
    batch_index: int,
    batch_count: int,
    batch_files: list[Path],
    error: Exception,
) -> BatchExecutionResult:
    failed_path = batch_files[0]
    return BatchExecutionResult(
        batch_index=batch_index,
        batch_count=batch_count,
        file_count=len(batch_files),
        ok=False,
        status_code=None,
        response_body=str(error),
        success_files=[],
        failed_files=[
            {
                "index": None,
                "filename": failed_path.name,
                "path": str(failed_path),
                "success": False,
                "status_code": None,
                "asset_id": None,
                "status": "preprocess_failed",
                "processing_status": None,
                "governance_status": None,
                "availability_status": None,
                "message": str(error),
            }
        ],
        deleted_files=[],
    )


async def _prepare_auto_uploads(
    args: argparse.Namespace,
    *,
    file_paths: list[Path],
    settings: Any,
) -> list[PreparedUpload]:
    try:
        from knowledge_base.ingest.ai import describe_image
        from knowledge_base.infrastructure.embedding import EmbeddingService
    except ModuleNotFoundError as exc:
        missing_name = getattr(exc, "name", "") or str(exc)
        raise ValueError(
            "自动目录模式依赖缺失，无法执行图片压缩和 LLM 识图。"
            f"当前缺少模块: {missing_name}"
        ) from exc

    category_hint = _normalize_optional_text(args.category_hint) or args.brand_code.strip()
    subcategory_hint = _normalize_optional_text(args.subcategory_hint)
    dimension_code = _normalize_optional_text(args.final_tags_dimension) or "scene"
    llm_model = _normalize_optional_text(args.llm_model)
    llm_max_tags = args.llm_max_tags if args.llm_max_tags and args.llm_max_tags > 0 else None
    batch_tags = _normalize_batch_tags(args)

    prepared_uploads: list[PreparedUpload] = []
    for index, original_path in enumerate(file_paths):
        upload_path_str, cleanup_path_str = await asyncio.to_thread(
            EmbeddingService.prepare_image_path_for_limit,
            str(original_path),
            max_bytes=IMAGE_MAX_BYTES,
            target_bytes=IMAGE_TARGET_BYTES,
            purpose="geo materials create upload",
        )
        upload_path = Path(upload_path_str)
        cleanup_upload_path = bool(cleanup_path_str)

        _print_auto_image_progress(index=index, total=len(file_paths), original_path=original_path)
        try:
            semantic_info = await describe_image(
                str(upload_path),
                category=category_hint,
                subcategory=subcategory_hint,
                source_name=original_path.name,
                model=llm_model,
                max_tags=llm_max_tags,
                settings=settings,
            )
        except Exception as exc:
            _print_auto_image_failure(
                index=index,
                total=len(file_paths),
                original_path=original_path,
                error=exc,
            )
            raise

        summary = str(semantic_info.get("summary") or "").strip()
        raw_tags = semantic_info.get("tags", [])
        tags: list[str] = []
        if isinstance(raw_tags, list):
            for item in raw_tags:
                tag = str(item or "").strip()
                if tag and tag not in tags:
                    tags.append(tag)

        if not summary:
            raise ValueError(f"LLM 没有生成图片描述: {original_path.name}")
        if not tags:
            raise ValueError(f"LLM 没有生成图片标签: {original_path.name}")

        field_name = f"file_{index}"
        upload_filename = _resolve_upload_filename(original_path, upload_path)
        mime_type = _resolve_image_content_type(upload_path, original_path.name)
        item = {
            "asset_type": "image",
            "title": original_path.name,
            "description": summary,
            "note": summary,
            "final_tags": _build_final_tags(
                [*tags, *(tag for tag in batch_tags if tag not in tags)],
                dimension_code=dimension_code,
            ),
            "file_field": field_name,
        }
        prepared_uploads.append(
            PreparedUpload(
                original_path=original_path,
                upload_path=upload_path,
                upload_filename=upload_filename,
                mime_type=mime_type,
                field_name=field_name,
                item=item,
                cleanup_upload_path=cleanup_upload_path,
            )
        )
    return prepared_uploads


def _cleanup_prepared_uploads(prepared_uploads: list[PreparedUpload]) -> None:
    for prepared in prepared_uploads:
        if prepared.cleanup_upload_path and prepared.upload_path.exists():
            prepared.upload_path.unlink(missing_ok=True)


def _build_preview_from_prepared(prepared_uploads: list[PreparedUpload]) -> dict[str, Any]:
    return {
        "items": [prepared.item for prepared in prepared_uploads],
        "files": [
            {
                "field_name": prepared.field_name,
                "original_path": str(prepared.original_path),
                "upload_path": str(prepared.upload_path),
                "upload_filename": prepared.upload_filename,
                "mime_type": prepared.mime_type,
                "compressed": prepared.upload_path != prepared.original_path,
            }
            for prepared in prepared_uploads
        ],
    }


def _build_manual_upload_data(item: dict[str, Any]) -> dict[str, str]:
    data: dict[str, str] = {
        "asset_type": str(item.get("asset_type") or "").strip(),
    }
    title = _normalize_optional_text(item.get("title"))
    description = _normalize_optional_text(item.get("description"))
    note = _normalize_optional_text(item.get("note")) or _normalize_optional_text(item.get("operator_note"))
    source_asset_id = _normalize_optional_text(item.get("source_asset_id"))
    llm_prompt_template_id = _normalize_optional_text(item.get("llm_prompt_template_id"))
    keywords = item.get("keywords")
    final_tags = item.get("final_tags")

    if title is not None:
        data["title"] = title
    if description is not None:
        data["description"] = description
    if note is not None:
        data["note"] = note
    if source_asset_id is not None:
        data["source_asset_id"] = source_asset_id
    if llm_prompt_template_id is not None:
        data["llm_prompt_template_id"] = llm_prompt_template_id
    if isinstance(keywords, list):
        normalized_keywords = [str(item).strip() for item in keywords if str(item).strip()]
        if normalized_keywords:
            data["keywords"] = ",".join(normalized_keywords)
    elif _normalize_optional_text(keywords) is not None:
        data["keywords"] = _normalize_optional_text(keywords) or ""
    if final_tags is not None:
        data["final_tags"] = json.dumps(final_tags, ensure_ascii=False)
    return data


def _build_preview_from_manual(
    *,
    file_paths: list[Path],
    file_field_names: list[str],
    items_json: str,
) -> dict[str, Any]:
    return {
        "items": json.loads(items_json),
        "files": [
            {
                "field_name": file_field_names[index],
                "path": str(path),
                "filename": path.name,
                "mime_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            }
            for index, path in enumerate(file_paths)
        ],
    }


def _default_result_json_path() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return PROJECT_ROOT / "logs" / f"geo_materials_create_result_{timestamp}.json"


def _write_result_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _chunk_file_paths(file_paths: list[Path], *, batch_size: int) -> list[list[Path]]:
    if batch_size <= 0 or batch_size > MAX_UPLOAD_FILES:
        raise ValueError(f"batch_size 必须在 1 到 {MAX_UPLOAD_FILES} 之间")
    return [file_paths[index : index + batch_size] for index in range(0, len(file_paths), batch_size)]


def _print_request_preview(
    *,
    endpoint: str,
    headers: dict[str, str],
    data: dict[str, str],
    preview: dict[str, Any],
    batch_index: int | None = None,
    batch_count: int | None = None,
) -> None:
    title = "将要发送的请求:"
    if batch_index is not None and batch_count is not None:
        title = f"将要发送的请求（第 {batch_index}/{batch_count} 批）:"
    print(title)
    print(
        json.dumps(
            {
                "endpoint": endpoint,
                "headers": _sanitize_headers_for_preview(headers),
                "data": data,
                "preview": preview,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _print_response(*, response: Any, batch_index: int | None = None, batch_count: int | None = None) -> Any:
    if batch_index is not None and batch_count is not None:
        print(f"status（第 {batch_index}/{batch_count} 批）:", response.status_code)
    else:
        print("status:", response.status_code)
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            parsed = response.json()
            print(json.dumps(parsed, ensure_ascii=False, indent=2))
            return parsed
        except Exception:
            print(response.text)
            return response.text
    print(response.text)
    return response.text


def _execute_request(
    *,
    requests_module: Any,
    endpoint: str,
    headers: dict[str, str],
    data: dict[str, str],
    files_payload: list[tuple[str, Path, str, str]],
    timeout_seconds: float,
) -> Any:
    with ExitStack() as stack:
        files: list[tuple[str, tuple[str, Any, str]]] = []
        for field_name, path, upload_filename, mime_type in files_payload:
            file_obj = stack.enter_context(path.open("rb"))
            files.append((field_name, (upload_filename, file_obj, mime_type)))
        return requests_module.post(
            endpoint,
            headers=headers,
            data=data,
            files=files,
            timeout=float(timeout_seconds),
        )


def _extract_manual_upload_outcome(
    *,
    response: Any,
    response_body: Any,
    index: int,
    original_path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if isinstance(response_body, dict):
        payload = {
            "index": index,
            "filename": original_path.name,
            "success": bool(response.ok),
            "status_code": int(response.status_code),
            "asset_id": response_body.get("asset_id"),
            "status": response_body.get("status"),
            "processing_status": response_body.get("processing_status"),
            "governance_status": response_body.get("governance_status"),
            "availability_status": response_body.get("availability_status"),
            "message": response_body.get("detail") if not response.ok else None,
        }
    else:
        payload = {
            "index": index,
            "filename": original_path.name,
            "success": bool(response.ok),
            "status_code": int(response.status_code),
            "asset_id": None,
            "status": None,
            "processing_status": None,
            "governance_status": None,
            "availability_status": None,
            "message": str(response_body),
        }

    if payload["success"]:
        return [payload], []
    return [], [payload]


def _delete_successful_original_files(*, file_paths: list[Path]) -> list[str]:
    deleted_files: list[str] = []
    for original_path in file_paths:
        if not original_path.exists():
            continue
        original_path.unlink(missing_ok=True)
        deleted_files.append(str(original_path))
    return deleted_files


def _run_auto_batches(
    *,
    args: argparse.Namespace,
    requests_module: Any,
    headers: dict[str, str],
    file_paths: list[Path],
) -> tuple[int, list[BatchExecutionResult]]:
    from knowledge_base.infrastructure.settings import get_settings

    settings = get_settings()
    batch_file_groups = [[path] for path in file_paths]
    batch_count = len(batch_file_groups)
    results: list[BatchExecutionResult] = []

    for batch_index, batch_files in enumerate(batch_file_groups, start=1):
        prepared_uploads: list[PreparedUpload] = []
        try:
            prepared_uploads = asyncio.run(
                _prepare_auto_uploads(
                    args,
                    file_paths=batch_files,
                    settings=settings,
                )
            )
            prepared = prepared_uploads[0]
            data = _build_manual_upload_data(prepared.item)
            preview = _build_preview_from_prepared(prepared_uploads)
            _print_request_preview(
                endpoint=args.endpoint,
                headers=headers,
                data=data,
                preview=preview,
                batch_index=batch_index,
                batch_count=batch_count,
            )

            if args.dry_run:
                results.append(
                    BatchExecutionResult(
                        batch_index=batch_index,
                        batch_count=batch_count,
                        file_count=len(batch_files),
                        ok=True,
                        status_code=None,
                        response_body="dry_run",
                        success_files=[
                            {
                                "index": 0,
                                "filename": batch_files[0].name,
                                "success": True,
                                "status_code": None,
                                "asset_id": None,
                                "status": "dry_run",
                                "processing_status": None,
                                "governance_status": None,
                                "availability_status": None,
                                "message": "dry_run",
                            }
                        ],
                        failed_files=[],
                        deleted_files=[],
                    )
                )
                continue

            files_payload = [
                (
                    "file",
                    prepared.upload_path,
                    prepared.upload_filename,
                    prepared.mime_type,
                )
            ]
            response = _execute_request(
                requests_module=requests_module,
                endpoint=args.endpoint,
                headers=headers,
                data=data,
                files_payload=files_payload,
                timeout_seconds=float(args.timeout_seconds),
            )
            response_body = _print_response(
                response=response,
                batch_index=batch_index,
                batch_count=batch_count,
            )
            success_files, failed_files = _extract_manual_upload_outcome(
                response=response,
                response_body=response_body,
                index=0,
                original_path=prepared.original_path,
            )
            deleted_files: list[str] = []
            if args.delete_success_files and success_files:
                deleted_files = _delete_successful_original_files(file_paths=[prepared.original_path])
                if deleted_files:
                    print(
                        f"第 {batch_index}/{batch_count} 张上传成功，已删除原始文件 {len(deleted_files)} 个"
                    )
            results.append(
                BatchExecutionResult(
                    batch_index=batch_index,
                    batch_count=batch_count,
                    file_count=len(batch_files),
                    ok=bool(response.ok),
                    status_code=int(response.status_code),
                    response_body=response_body,
                    success_files=success_files,
                    failed_files=failed_files,
                    deleted_files=deleted_files,
                )
            )
            if not response.ok:
                return 1, results
        except Exception as exc:
            _print_auto_image_skipped(
                index=batch_index,
                total=batch_count,
                original_path=batch_files[0],
                error=exc,
            )
            results.append(
                _build_auto_preprocess_failed_result(
                    batch_index=batch_index,
                    batch_count=batch_count,
                    batch_files=batch_files,
                    error=exc,
                )
            )
            continue
        finally:
            _cleanup_prepared_uploads(prepared_uploads)

        has_next_batch = batch_index < batch_count
        interval_seconds = random.randint(3, 9)
        if has_next_batch and not args.dry_run:
            next_batch_index = batch_index + 1
            print(
                f"第 {batch_index}/{batch_count} 张完成，等待 {interval_seconds} 秒后开始第 {next_batch_index}/{batch_count} 张..."
            )
            time.sleep(interval_seconds)

    _print_auto_skipped_summary(results)
    if any(result.failed_files for result in results):
        return 2, results
    return 0, results


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        import requests
    except ModuleNotFoundError as exc:
        missing_name = getattr(exc, "name", "") or str(exc)
        print(
            "缺少 requests 依赖，无法运行该测试脚本。"
            "请在项目环境中执行，例如 `uv run python scripts/test_geo_materials_create.py ...`，"
            f"当前缺少模块: {missing_name}",
            file=sys.stderr,
        )
        return 2

    try:
        file_paths = _resolve_input_files(args)
        headers = _build_headers(args)
        if args.dir is not None and int(args.batch_interval_seconds) < 0:
            raise ValueError("--batch-interval-seconds 不能小于 0")
    except ValueError as exc:
        print(f"参数准备失败: {exc}", file=sys.stderr)
        return 2

    if args.dir is not None:
        exit_code, batch_results = _run_auto_batches(
            args=args,
            requests_module=requests,
            headers=headers,
            file_paths=file_paths,
        )
        result_payload = {
            "mode": "directory_auto_batch",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "total_files": len(file_paths),
            "batch_size": 1,
            "batch_interval_seconds": int(args.batch_interval_seconds),
            "batch_count": len(batch_results),
            "all_ok": all(result.ok for result in batch_results),
            "results": [
                {
                    "batch_index": result.batch_index,
                    "batch_count": result.batch_count,
                    "file_count": result.file_count,
                    "ok": result.ok,
                    "status_code": result.status_code,
                    "success_files": result.success_files,
                    "failed_files": result.failed_files,
                    "deleted_files": result.deleted_files,
                    "response_body": result.response_body,
                }
                for result in batch_results
            ],
        }
        print(json.dumps(result_payload, ensure_ascii=False, indent=2))
        result_json_path = args.result_json or _default_result_json_path()
        _write_result_json(result_json_path, result_payload)
        print(f"批处理结果已写入: {result_json_path}")
        return exit_code

    try:
        items_json = _build_manual_items_json(args, file_paths=file_paths)
        file_field_names = _extract_file_field_names(
            items_json,
            file_count=len(file_paths),
            default_single_file_field=args.file_field,
        )
    except ValueError as exc:
        print(f"参数准备失败: {exc}", file=sys.stderr)
        return 2

    items = json.loads(items_json)
    preview_data = _build_manual_upload_data(items[0]) if items else {}
    preview = _build_preview_from_manual(
        file_paths=file_paths,
        file_field_names=file_field_names,
        items_json=items_json,
    )
    _print_request_preview(
        endpoint=args.endpoint,
        headers=headers,
        data=preview_data,
        preview=preview,
    )

    if args.dry_run:
        return 0

    results: list[dict[str, Any]] = []
    all_ok = True
    for index, path in enumerate(file_paths):
        item = items[index]
        data = _build_manual_upload_data(item)
        response = _execute_request(
            requests_module=requests,
            endpoint=args.endpoint,
            headers=headers,
            data=data,
            files_payload=[
                (
                    "file",
                    path,
                    path.name,
                    mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                )
            ],
            timeout_seconds=float(args.timeout_seconds),
        )
        response_body = _print_response(response=response)
        success_files, failed_files = _extract_manual_upload_outcome(
            response=response,
            response_body=response_body,
            index=index,
            original_path=path,
        )
        deleted_files: list[str] = []
        if args.delete_success_files and success_files:
            deleted_files = _delete_successful_original_files(file_paths=[path])
        all_ok = all_ok and bool(response.ok)
        results.append(
            {
                "index": index,
                "filename": path.name,
                "ok": bool(response.ok),
                "status_code": int(response.status_code),
                "success_files": success_files,
                "failed_files": failed_files,
                "deleted_files": deleted_files,
                "response_body": response_body,
            }
        )
        if not response.ok:
            break

    result_payload = {
        "mode": "manual",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "file_count": len(file_paths),
        "all_ok": all_ok,
        "results": results,
    }
    result_json_path = args.result_json or _default_result_json_path()
    _write_result_json(result_json_path, result_payload)
    print(f"执行结果已写入: {result_json_path}")

    if all_ok:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
