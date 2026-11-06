from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


_SAFE_FILENAME_PATTERN = re.compile(r"[^\w.\-]+", re.UNICODE)
_EXTRACT_CACHE_VERSION = "brand-backfill-extract-v1"
_DEFAULT_EXTRACT_CONCURRENCY = 2
_DEFAULT_EXTRACT_RETRIES = 3
_EXTRACT_RETRY_DELAYS_SECONDS = (2.0, 5.0, 10.0)
_BACKFILL_CALLBACK_TYPE = "brand_backfill_completed"
_WRITABLE_SECTIONS = (
    "basic_info",
    "products",
    "attachment_products",
    "company_profile",
    "management_team",
    "competitors",
    "authority_honors",
    "customers_cases",
    "sensitive_topics",
    "attachments",
    "official_malls",
    "official_media_matrix",
    "other_info",
)
_ATTACHMENT_PRODUCTS_KNOWLEDGE_TYPE = "attachment_products"
_PRODUCT_TEXT_FIELDS = (
    "product_alias",
    "product_description",
    "product_website",
    "price_info",
    "product_advantages",
    "target_scenarios",
    "service_standard",
    "service_process",
    "cases_and_reputation",
    "certification_info",
    "core_technology",
    "other_info",
)
_PRODUCT_LIST_FIELDS = ("product_images", "coverage_regions")


_RUNTIME: dict[str, Any] | None = None


def _load_runtime() -> dict[str, Any]:
    global _RUNTIME
    if _RUNTIME is not None:
        return _RUNTIME

    try:
        from knowledge_base.brand.application.service import BrandApplicationService
        from knowledge_base.brand.callback_mapper import format_brand_callback_knowledge_from_snapshot
        from knowledge_base.brand.enrichment import enrich_brand_from_tianyancha
        from knowledge_base.brand.knowledge_extraction import (
            _KNOWLEDGE_TYPES,
            _apply_extracted_basic_info_to_brand,
            _apply_extracted_products_to_brand_products,
            _build_basic_info_from_brand,
            _build_brand_product_payloads,
            _build_empty_knowledge,
            _load_content_json,
            _merge_brand_knowledge,
            _normalize_extraction_result,
            _normalize_optional_str,
            _sanitize_final_payload,
        )
        from knowledge_base.brand_knowledge.ai import extract_brand_knowledge_from_markdown
        from knowledge_base.composition import build_mysql_stores
        from knowledge_base.infrastructure import OSSClient, TianyanchaClient, get_settings, setup_logging
    except ModuleNotFoundError as exc:
        missing_name = getattr(exc, "name", "") or str(exc)
        raise RuntimeError(
            "项目依赖未安装，无法执行品牌回补脚本。"
            "请在项目环境中运行，例如 `uv run python scripts/backfill_brand_from_markdown.py ...`，"
            f"当前缺少模块: {missing_name}"
        ) from exc

    def configure_logging() -> Any:
        settings = get_settings()
        log_file = Path(settings.log_dir) / "app.log"
        setup_logging(level=settings.log_level, log_file=str(log_file))
        return settings

    def build_service() -> Any:
        settings = get_settings()
        stores = build_mysql_stores(settings)

        class LightweightBackfillService:
            def __init__(self) -> None:
                self._settings = settings
                self._brands = stores.brands
                self._brand_full_knowledge = stores.brand_full_knowledge
                self._brand_products = stores.brand_products
                self._brand_knowledge = stores.brand_knowledge
                self._upload_tasks = stores.upload_tasks
                self._tianyancha_client = TianyanchaClient(settings)
                self.oss_client = OSSClient(settings)

        return LightweightBackfillService()

    _RUNTIME = {
        "BrandApplicationService": BrandApplicationService,
        "build_service": build_service,
        "configure_logging": configure_logging,
        "enrich_brand_from_tianyancha": enrich_brand_from_tianyancha,
        "format_brand_callback_knowledge_from_snapshot": format_brand_callback_knowledge_from_snapshot,
        "extract_brand_knowledge_from_markdown": extract_brand_knowledge_from_markdown,
        "_KNOWLEDGE_TYPES": _KNOWLEDGE_TYPES,
        "_apply_extracted_basic_info_to_brand": _apply_extracted_basic_info_to_brand,
        "_apply_extracted_products_to_brand_products": _apply_extracted_products_to_brand_products,
        "_build_basic_info_from_brand": _build_basic_info_from_brand,
        "_build_brand_product_payloads": _build_brand_product_payloads,
        "_build_empty_knowledge": _build_empty_knowledge,
        "_load_content_json": _load_content_json,
        "_merge_brand_knowledge": _merge_brand_knowledge,
        "_normalize_extraction_result": _normalize_extraction_result,
        "_normalize_optional_str": _normalize_optional_str,
        "_sanitize_final_payload": _sanitize_final_payload,
    }
    return _RUNTIME


@dataclass(frozen=True)
class MarkdownSource:
    kind: str
    name: str
    identifier: str
    subcategory: str | None = None
    path: Path | None = None
    oss_key: str | None = None


@dataclass(frozen=True)
class BrandJob:
    brand_name: str
    brand_root: Path | None
    markdown_sources: list[MarkdownSource]


@dataclass(frozen=True)
class ExtractedMarkdownResult:
    source: MarkdownSource
    source_name: str
    subcategory: str | None
    markdown_text_length: int
    extracted_raw: dict[str, Any]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "读取本地 Markdown，复用现有品牌知识抽取/天眼查补全逻辑，"
            "将结果回补到品牌库中；默认不触发现有 upload/callback 链路，"
            "可通过 --callback 或 --callback-url 在写库成功后回调上游。"
        )
    )
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--brands-root",
        type=Path,
        help="批量模式：根目录下每个一级子目录视为一个品牌目录，递归读取其中的 .md 文件。",
    )
    mode_group.add_argument(
        "--brand-name",
        help="单品牌模式：指定品牌名，再通过 --md-dir / --md-file 提供 Markdown 来源。",
    )
    parser.add_argument(
        "--from-oss-converted",
        action="store_true",
        help="单品牌模式：直接从 OSS 的 `品牌名/converted/` 读取 Markdown。",
    )
    parser.add_argument(
        "--oss-prefix",
        help="单品牌模式：自定义 OSS prefix；传这个时会优先用该 prefix，而不是自动拼 `品牌名/converted/`。",
    )
    parser.add_argument(
        "--md-dir",
        type=Path,
        help="单品牌模式：Markdown 所在目录，会递归扫描。",
    )
    parser.add_argument(
        "--md-file",
        type=Path,
        action="append",
        default=[],
        help="单品牌模式：可重复传多个 Markdown 文件。",
    )
    parser.add_argument(
        "--glob",
        default="*.md",
        help="扫描 Markdown 时使用的 glob，默认 *.md。",
    )
    parser.add_argument(
        "--skip-tianyancha",
        action="store_true",
        help="跳过天眼查和网页补空，只做 Markdown 抽取与回补。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只抽取和 merge，不写数据库。建议先跑一次核对结果。",
    )
    parser.add_argument(
        "--write-sections",
        nargs="+",
        choices=_WRITABLE_SECTIONS,
        help=(
            "只回填指定 section。可选值："
            + ", ".join(_WRITABLE_SECTIONS)
            + "。不传时默认按现有逻辑全量回填。"
        ),
    )
    parser.add_argument(
        "--fill-empty-only",
        action="store_true",
        help="只补已有品牌知识中的空字段；列表型 section 只更新已有条目，不新增产品、竞品等条目。",
    )
    parser.add_argument(
        "--extract-concurrency",
        type=int,
        default=_DEFAULT_EXTRACT_CONCURRENCY,
        help=f"Markdown LLM 抽取并发数，默认 {_DEFAULT_EXTRACT_CONCURRENCY}。建议 2-3，避免触发限流。",
    )
    parser.add_argument(
        "--extract-retries",
        type=int,
        default=_DEFAULT_EXTRACT_RETRIES,
        help=f"单个 Markdown 抽取失败后的重试次数，默认 {_DEFAULT_EXTRACT_RETRIES}。",
    )
    parser.add_argument(
        "--extract-cache-dir",
        type=Path,
        help=(
            "Markdown 抽取结果缓存目录。默认优先使用 --output-dir/.extract_cache；"
            "未传 --output-dir 时使用项目 .cache/backfill_extract。"
        ),
    )
    parser.add_argument(
        "--no-extract-cache",
        action="store_true",
        help="禁用 Markdown 抽取结果缓存，每次都重新调用 LLM。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="把每个品牌最终 merge 后的 JSON 输出到本地目录，便于核对。",
    )
    parser.add_argument(
        "--callback",
        action="store_true",
        help="写库成功后使用 BRAND_COMPLETION_CALLBACK_URL 回调上游。",
    )
    parser.add_argument(
        "--callback-url",
        help="写库成功后回调上游的 URL；传入后会自动启用回调，并覆盖 BRAND_COMPLETION_CALLBACK_URL。",
    )
    parser.add_argument(
        "--callback-timeout-seconds",
        type=float,
        help="回调请求超时时间；默认使用 BRAND_COMPLETION_CALLBACK_TIMEOUT_SECONDS。",
    )
    parser.add_argument(
        "--callback-task-prefix",
        default="manual_brand_backfill",
        help="写入 upload_task_callbacks 时使用的 task_id 前缀。",
    )
    parser.add_argument(
        "--callback-on-dry-run",
        action="store_true",
        help="dry-run 时也发送回调；仅建议联调上游回调接收逻辑时使用。",
    )
    parser.add_argument(
        "--callback-on-failure",
        action="store_true",
        help="品牌处理失败时也发送失败回调；默认只对成功处理的品牌回调。",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="任一品牌处理失败时立即退出；默认继续处理后续品牌。",
    )
    return parser


def _safe_output_name(brand_name: str) -> str:
    normalized = _SAFE_FILENAME_PATTERN.sub("_", brand_name.strip()).strip("._")
    return normalized or "brand"


def _callback_task_id(*, prefix: str, brand_name: str, brand_id: int | None = None) -> str:
    safe_prefix = _safe_output_name(prefix)[:48] or "manual_brand_backfill"
    safe_brand = _safe_output_name(brand_name)[:48] or "brand"
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    brand_part = str(brand_id) if brand_id is not None else safe_brand
    return f"{safe_prefix}:{brand_part}:{timestamp}"


def _resolve_callback_url(args: argparse.Namespace, settings: Any) -> str | None:
    explicit_url = str(args.callback_url or "").strip()
    if explicit_url:
        return explicit_url
    if not args.callback:
        return None
    configured_url = str(getattr(settings, "brand_completion_callback_url", "") or "").strip()
    if not configured_url:
        raise ValueError("已启用 --callback，但 BRAND_COMPLETION_CALLBACK_URL 未配置")
    return configured_url


def _resolve_callback_timeout(args: argparse.Namespace, settings: Any) -> float:
    if args.callback_timeout_seconds is not None:
        return float(args.callback_timeout_seconds)
    return float(getattr(settings, "brand_completion_callback_timeout_seconds", 5.0))


def _current_backfill_knowledge_mete(service: Any, *, brand: dict[str, Any]) -> dict[str, str]:
    version = str(brand.get("knowledge_revision") or "").strip()
    latest = None
    brand_id = brand.get("id")
    if brand_id is not None and hasattr(service, "_brand_full_knowledge"):
        latest = service._brand_full_knowledge.get_latest_by_brand_id(brand_id=int(brand_id))
    return {
        "version": version,
        "oss_url_md": str((latest or {}).get("oss_url") or "").strip(),
        "oss_url_pdf": str((latest or {}).get("pdf_oss_url") or "").strip(),
    }


def _build_backfill_callback_payload(
    service: Any,
    *,
    result: dict[str, Any],
    status: str,
    error_message: str | None = None,
) -> dict[str, Any]:
    runtime = _load_runtime()
    brand_name = str(result.get("brand_name") or "").strip()
    brand = service._brands.get_brand_by_name(brand_name) if brand_name else None
    if not isinstance(brand, dict):
        brand = {}
    knowledge_snapshot = result.get("knowledge") if isinstance(result.get("knowledge"), dict) else {}
    brand_code = str(brand.get("brand_code") or "").strip()
    if not brand_code and isinstance(knowledge_snapshot, dict):
        basic_info = knowledge_snapshot.get("basic_info")
        if isinstance(basic_info, dict):
            brand_code = str(basic_info.get("brand_code") or "").strip()

    is_success = status == "success"
    payload: dict[str, Any] = {
        "brand_code": brand_code,
        "overall_status": "completed" if is_success else "failed",
        "completed_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
        "knowledge_extraction_status": "success" if is_success else "failed",
        "knowledge_markdown_status": "success" if is_success else "failed",
        "knowledge_mete": _current_backfill_knowledge_mete(service, brand=brand),
    }
    if is_success:
        payload["knowledge"] = runtime["format_brand_callback_knowledge_from_snapshot"](
            brand=brand,
            knowledge_snapshot=knowledge_snapshot,
        )
    elif error_message:
        payload["error_message"] = error_message
    return payload


def _record_backfill_callback_pending(
    service: Any,
    *,
    task_id: str,
    callback_url: str,
    payload: dict[str, Any],
) -> int:
    upload_tasks = getattr(service, "_upload_tasks", None)
    if upload_tasks is None:
        return 0
    upload_tasks.upsert_upload_task_callback(
        task_id=task_id,
        callback_type=_BACKFILL_CALLBACK_TYPE,
        callback_url=callback_url,
        request_payload_json=payload,
        status="pending",
    )
    callback = upload_tasks.get_upload_task_callback(
        task_id=task_id,
        callback_type=_BACKFILL_CALLBACK_TYPE,
    )
    return int((callback or {}).get("retry_count") or 0)


def _record_backfill_callback_result(
    service: Any,
    *,
    task_id: str,
    payload: dict[str, Any],
    status: str,
    retry_count: int,
    response_code: int | None,
    response_body: str | None,
    error_message: str | None,
) -> None:
    upload_tasks = getattr(service, "_upload_tasks", None)
    if upload_tasks is None:
        return
    upload_tasks.update_upload_task_callback_result(
        task_id=task_id,
        callback_type=_BACKFILL_CALLBACK_TYPE,
        request_payload_json=payload,
        status=status,
        retry_count=retry_count,
        next_retry_at=None,
        last_response_code=response_code,
        last_response_body=response_body,
        last_error_message=error_message,
        sent_at=datetime.now() if status == "success" else None,
    )


def _post_backfill_callback(
    *,
    callback_url: str,
    payload: dict[str, Any],
    timeout_seconds: float,
) -> tuple[int | None, str | None, str | None]:
    try:
        import requests

        response = requests.post(callback_url, json=payload, timeout=timeout_seconds)
    except Exception as exc:  # noqa: BLE001
        return None, None, str(exc)
    return response.status_code, response.text, None


async def _send_backfill_callback(
    service: Any,
    *,
    result: dict[str, Any],
    status: str,
    error_message: str | None,
    callback_url: str,
    timeout_seconds: float,
    callback_task_prefix: str,
) -> dict[str, Any]:
    payload = _build_backfill_callback_payload(
        service,
        result=result,
        status=status,
        error_message=error_message,
    )
    task_id = _callback_task_id(
        prefix=callback_task_prefix,
        brand_name=str(result.get("brand_name") or ""),
        brand_id=result.get("brand_id") if isinstance(result.get("brand_id"), int) else None,
    )
    retry_count = _record_backfill_callback_pending(
        service,
        task_id=task_id,
        callback_url=callback_url,
        payload=payload,
    )
    response_code, response_body, post_error = await asyncio.to_thread(
        _post_backfill_callback,
        callback_url=callback_url,
        payload=payload,
        timeout_seconds=timeout_seconds,
    )
    callback_status = "success" if response_code is not None and 200 <= response_code < 300 else "failed"
    _record_backfill_callback_result(
        service,
        task_id=task_id,
        payload=payload,
        status=callback_status,
        retry_count=retry_count,
        response_code=response_code,
        response_body=response_body,
        error_message=post_error,
    )
    return {
        "task_id": task_id,
        "callback_type": _BACKFILL_CALLBACK_TYPE,
        "status": callback_status,
        "response_code": response_code,
        "response_body": response_body,
        "error": post_error,
    }


def _read_markdown_text(path: Path) -> str:
    encodings = ("utf-8", "utf-8-sig", "gb18030")
    last_error: Exception | None = None
    for encoding in encodings:
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    return path.read_text(encoding="utf-8")


def _collect_markdown_files(root: Path, pattern: str) -> list[Path]:
    resolved_root = root.expanduser().resolve()
    if not resolved_root.exists():
        raise FileNotFoundError(f"目录不存在: {resolved_root}")
    if not resolved_root.is_dir():
        raise NotADirectoryError(f"不是目录: {resolved_root}")
    files = sorted(path for path in resolved_root.rglob(pattern) if path.is_file())
    return files


def _build_local_markdown_sources(files: list[Path], *, brand_root: Path | None) -> list[MarkdownSource]:
    sources: list[MarkdownSource] = []
    for path in files:
        source_name = _infer_source_name(path, brand_root)
        subcategory = _infer_subcategory(path, brand_root)
        sources.append(
            MarkdownSource(
                kind="local",
                name=source_name,
                identifier=str(path),
                subcategory=subcategory,
                path=path,
            )
        )
    return sources


def _build_jobs(args: argparse.Namespace) -> list[BrandJob]:
    if args.brands_root is not None:
        brands_root = args.brands_root.expanduser().resolve()
        if not brands_root.exists():
            raise FileNotFoundError(f"brands root 不存在: {brands_root}")
        if not brands_root.is_dir():
            raise NotADirectoryError(f"brands root 不是目录: {brands_root}")

        jobs: list[BrandJob] = []
        for child in sorted(path for path in brands_root.iterdir() if path.is_dir()):
            markdown_files = _collect_markdown_files(child, args.glob)
            if not markdown_files:
                continue
            jobs.append(
                BrandJob(
                    brand_name=child.name.strip(),
                    brand_root=child,
                    markdown_sources=_build_local_markdown_sources(markdown_files, brand_root=child),
                )
            )
        return jobs

    brand_name = str(args.brand_name or "").strip()
    if not brand_name:
        raise ValueError("brand_name 不能为空")

    if args.from_oss_converted and (args.md_dir is not None or args.md_file):
        raise ValueError("--from-oss-converted 与 --md-dir/--md-file 不能同时使用")
    if args.oss_prefix and not args.from_oss_converted:
        raise ValueError("--oss-prefix 需要和 --from-oss-converted 一起使用")
    if args.from_oss_converted:
        return [
            BrandJob(
                brand_name=brand_name,
                brand_root=None,
                markdown_sources=[],
            )
        ]

    markdown_files: list[Path] = []
    brand_root: Path | None = None
    if args.md_dir is not None:
        brand_root = args.md_dir.expanduser().resolve()
        markdown_files.extend(_collect_markdown_files(brand_root, args.glob))
    for path in args.md_file or []:
        resolved = path.expanduser().resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"Markdown 文件不存在: {resolved}")
        if not resolved.is_file():
            raise FileNotFoundError(f"不是文件: {resolved}")
        markdown_files.append(resolved)

    deduped_files: list[Path] = []
    seen_paths: set[Path] = set()
    for path in sorted(markdown_files):
        if path in seen_paths:
            continue
        seen_paths.add(path)
        deduped_files.append(path)

    if not deduped_files:
        raise ValueError("未找到任何 Markdown 文件，请传 --md-dir 或 --md-file")

    return [
        BrandJob(
            brand_name=brand_name,
            brand_root=brand_root,
            markdown_sources=_build_local_markdown_sources(deduped_files, brand_root=brand_root),
        )
    ]


def _infer_source_name(path: Path, brand_root: Path | None) -> str:
    if brand_root is None:
        return path.name
    try:
        return path.resolve().relative_to(brand_root.resolve()).as_posix()
    except ValueError:
        return path.name


def _infer_subcategory(path: Path, brand_root: Path | None) -> str | None:
    if brand_root is None:
        return None
    try:
        relative = path.resolve().relative_to(brand_root.resolve())
    except ValueError:
        return None
    if len(relative.parts) <= 1:
        return None
    first_part = relative.parts[0].strip()
    return first_part or None


def _copy_jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _resolve_write_sections(args: argparse.Namespace) -> set[str]:
    raw_sections = list(args.write_sections or [])
    if not raw_sections:
        return set(_WRITABLE_SECTIONS)
    return {str(item).strip() for item in raw_sections if str(item).strip()}


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(_has_value(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_has_value(item) for item in value)
    return True


def _fill_missing_dict(existing_value: Any, incoming_value: Any) -> dict[str, Any]:
    existing = dict(existing_value) if isinstance(existing_value, dict) else {}
    incoming = dict(incoming_value) if isinstance(incoming_value, dict) else {}
    merged = dict(existing)
    for key, value in incoming.items():
        if not _has_value(merged.get(key)) and _has_value(value):
            merged[key] = value
        elif key not in merged:
            merged[key] = value
    return merged


def _item_key(item: dict[str, Any], fields: tuple[str, ...]) -> str:
    return "|".join(str(item.get(field) or "").strip().lower() for field in fields)


def _merge_existing_list_items_only(
    existing_value: Any,
    incoming_value: Any,
    *,
    key_fields: tuple[str, ...],
) -> list[Any]:
    if not isinstance(existing_value, list) or not existing_value:
        return []
    incoming_items = incoming_value if isinstance(incoming_value, list) else []
    incoming_by_key = {
        _item_key(item, key_fields): item
        for item in incoming_items
        if isinstance(item, dict) and _item_key(item, key_fields).strip("|")
    }
    merged_items: list[Any] = []
    for item in existing_value:
        if not isinstance(item, dict):
            merged_items.append(item)
            continue
        key = _item_key(item, key_fields)
        incoming_item = incoming_by_key.get(key)
        merged_items.append(_fill_missing_dict(item, incoming_item or {}))
    return merged_items


def _merge_sensitive_topics_fill_empty(existing_value: Any, incoming_value: Any) -> dict[str, list[str]]:
    runtime = _load_runtime()
    brand_application_service = runtime["BrandApplicationService"]
    existing_normalized = brand_application_service._serialize_sensitive_topics_payload(existing_value)
    incoming_normalized = brand_application_service._serialize_sensitive_topics_payload(incoming_value)
    merged: dict[str, list[str]] = {}
    for key in (
        "sensitive_contents",
        "controversial_events",
        "forbidden_words",
        "negative_clarifications",
        "other_info",
    ):
        existing_items = list(existing_normalized.get(key, []))
        incoming_items = list(incoming_normalized.get(key, []))
        if existing_items:
            merged[key] = existing_items
        elif incoming_items:
            merged[key] = _dedupe_text_list(incoming_items)
    return {key: value for key, value in merged.items() if value}


def _merge_other_info_entries(existing_value: Any, incoming_value: Any) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in list(existing_value or []) + list(incoming_value or []):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("key") or item.get("name") or "").strip()
        content = item.get("content") if "content" in item else item.get("value")
        if not title or content in (None, "", [], {}):
            continue
        entry = {
            "title": title,
            "content": content,
        }
        identity = json.dumps(entry, ensure_ascii=False, sort_keys=True)
        if identity in seen:
            continue
        seen.add(identity)
        merged.append(entry)
    return merged


def _apply_fill_empty_only_policy(
    *,
    final_payload: dict[str, Any],
    existing_snapshot: dict[str, Any],
    existing_sensitive_topics: Any,
    incoming_sensitive_topics: Any,
) -> dict[str, Any]:
    filtered = _copy_jsonable(final_payload)
    filtered["basic_info"] = _fill_missing_dict(
        existing_snapshot.get("basic_info"),
        final_payload.get("basic_info"),
    )
    filtered["company_profile"] = _fill_missing_dict(
        existing_snapshot.get("company_profile"),
        final_payload.get("company_profile"),
    )
    filtered["products"] = _merge_existing_list_items_only(
        existing_snapshot.get("products"),
        final_payload.get("products"),
        key_fields=("name",),
    )
    filtered["management_team"] = _merge_existing_list_items_only(
        existing_snapshot.get("management_team"),
        final_payload.get("management_team"),
        key_fields=("member_name",),
    )
    # In fill-empty-only mode, keep competitor data unchanged.
    filtered["competitors"] = _copy_jsonable(existing_snapshot.get("competitors") or [])
    filtered["authority_honors"] = _merge_existing_list_items_only(
        existing_snapshot.get("authority_honors"),
        final_payload.get("authority_honors"),
        key_fields=("title", "year"),
    )
    filtered["customers_cases"] = _merge_existing_list_items_only(
        existing_snapshot.get("customers_cases"),
        final_payload.get("customers_cases"),
        key_fields=("case_name", "customer_name"),
    )
    filtered["attachments"] = _merge_existing_list_items_only(
        existing_snapshot.get("attachments"),
        final_payload.get("attachments"),
        key_fields=("name", "url"),
    )
    filtered["official_malls"] = _merge_existing_list_items_only(
        existing_snapshot.get("official_malls"),
        final_payload.get("official_malls"),
        key_fields=("store_name", "platform"),
    )
    filtered["official_media_matrix"] = _merge_existing_list_items_only(
        existing_snapshot.get("official_media_matrix"),
        final_payload.get("official_media_matrix"),
        key_fields=("media_platform", "account_name", "account_id"),
    )
    filtered["other_info"] = _merge_other_info_entries(
        existing_snapshot.get("other_info"),
        final_payload.get("other_info"),
    )
    filtered["sensitive_topics"] = _merge_sensitive_topics_fill_empty(
        existing_sensitive_topics,
        incoming_sensitive_topics,
    )
    return filtered


def _normalize_oss_prefix(prefix: str) -> str:
    normalized = str(prefix or "").strip().strip("/")
    return f"{normalized}/" if normalized else ""


def _candidate_oss_prefixes(brand_name: str, explicit_prefix: str | None) -> list[str]:
    if explicit_prefix:
        normalized = _normalize_oss_prefix(explicit_prefix)
        return [normalized] if normalized else []
    normalized_brand = brand_name.strip().strip("/")
    prefixes = [
        _normalize_oss_prefix(f"{normalized_brand}/converted"),
        _normalize_oss_prefix(f"test/{normalized_brand}/converted"),
    ]
    deduped: list[str] = []
    for item in prefixes:
        if item and item not in deduped:
            deduped.append(item)
    return deduped


def _infer_oss_subcategory(prefix: str, object_key: str) -> str | None:
    normalized_prefix = _normalize_oss_prefix(prefix)
    normalized_key = str(object_key or "").strip().strip("/")
    if not normalized_prefix or not normalized_key.startswith(normalized_prefix):
        return None
    relative = normalized_key[len(normalized_prefix):].strip("/")
    if not relative:
        return None
    parts = relative.split("/")
    if len(parts) <= 2:
        return None
    return parts[0].strip() or None


def _load_oss_markdown_sources(service: Any, *, brand_name: str, explicit_prefix: str | None) -> list[MarkdownSource]:
    oss_client = service.oss_client
    if not getattr(oss_client, "enabled", False):
        raise RuntimeError("OSS 未启用，请先配置 OSS 环境变量")

    matched_sources: list[MarkdownSource] = []
    attempted_prefixes = _candidate_oss_prefixes(brand_name, explicit_prefix)
    for prefix in attempted_prefixes:
        object_keys = sorted(oss_client.list_object_keys(prefix, suffix=".md"))
        if not object_keys:
            continue
        for object_key in object_keys:
            matched_sources.append(
                MarkdownSource(
                    kind="oss",
                    name=object_key[len(prefix):] if object_key.startswith(prefix) else object_key,
                    identifier=object_key,
                    subcategory=_infer_oss_subcategory(prefix, object_key),
                    oss_key=object_key,
                )
            )
        if matched_sources:
            return matched_sources

    attempted_display = ", ".join(attempted_prefixes) or "<empty>"
    raise FileNotFoundError(f"OSS 未找到任何 Markdown，对应 prefix: {attempted_display}")


def _load_markdown_text_from_source(service: Any, source: MarkdownSource) -> str:
    if source.kind == "local":
        if source.path is None:
            raise ValueError(f"本地 Markdown source 缺少 path: {source}")
        return _read_markdown_text(source.path)
    if source.kind == "oss":
        if not source.oss_key:
            raise ValueError(f"OSS Markdown source 缺少 oss_key: {source}")
        text = service.oss_client.get_object_text(source.oss_key, encoding="utf-8")
        if text is None:
            raw_bytes = service.oss_client.get_object(source.oss_key)
            if raw_bytes is None:
                raise FileNotFoundError(f"OSS 对象不存在或读取失败: {source.oss_key}")
            try:
                return raw_bytes.decode("utf-8-sig")
            except UnicodeDecodeError:
                return raw_bytes.decode("gb18030")
        return text
    raise ValueError(f"不支持的 Markdown source kind: {source.kind}")


def _resolve_extract_cache_dir(args: argparse.Namespace) -> Path | None:
    if args.no_extract_cache:
        return None
    if args.extract_cache_dir is not None:
        return args.extract_cache_dir.expanduser().resolve()
    if args.output_dir is not None:
        return (args.output_dir.expanduser().resolve() / ".extract_cache")
    return PROJECT_ROOT / ".cache" / "backfill_extract"


def _extract_cache_key(
    *,
    brand_name: str,
    source: MarkdownSource,
    markdown_text: str,
    model_name: str,
) -> str:
    payload = {
        "version": _EXTRACT_CACHE_VERSION,
        "brand_name": brand_name,
        "source_kind": source.kind,
        "source_name": source.name,
        "source_identifier": source.identifier,
        "subcategory": source.subcategory,
        "model_name": model_name,
        "markdown_sha256": hashlib.sha256(markdown_text.encode("utf-8")).hexdigest(),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _read_extract_cache(cache_dir: Path | None, cache_key: str) -> dict[str, Any] | None:
    if cache_dir is None:
        return None
    cache_path = cache_dir / f"{cache_key}.json"
    if not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[EXTRACT_CACHE_INVALID] path={cache_path} error={exc}", file=sys.stderr)
        return None
    extracted = payload.get("extracted_raw") if isinstance(payload, dict) else None
    return extracted if isinstance(extracted, dict) else None


def _write_extract_cache(
    cache_dir: Path | None,
    cache_key: str,
    *,
    brand_name: str,
    source: MarkdownSource,
    extracted_raw: dict[str, Any],
) -> None:
    if cache_dir is None:
        return
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{cache_key}.json"
    payload = {
        "version": _EXTRACT_CACHE_VERSION,
        "brand_name": brand_name,
        "source": {
            "kind": source.kind,
            "name": source.name,
            "identifier": source.identifier,
            "subcategory": source.subcategory,
        },
        "extracted_raw": extracted_raw,
        "cached_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    temp_path = cache_path.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(cache_path)


async def _extract_markdown_source(
    service: Any,
    *,
    runtime: dict[str, Any],
    brand_name: str,
    source: MarkdownSource,
    index: int,
    total: int,
    semaphore: asyncio.Semaphore,
    cache_dir: Path | None,
    max_retries: int,
) -> ExtractedMarkdownResult:
    async with semaphore:
        markdown_text = _load_markdown_text_from_source(service, source)
        source_name = source.name
        model_name = str(getattr(service._settings, "text_llm_model", "") or "")
        cache_key = _extract_cache_key(
            brand_name=brand_name,
            source=source,
            markdown_text=markdown_text,
            model_name=model_name,
        )
        cached = _read_extract_cache(cache_dir, cache_key)
        if cached is not None:
            print(f"[EXTRACT_CACHE_HIT] {index}/{total} {source_name}")
            return ExtractedMarkdownResult(
                source=source,
                source_name=source_name,
                subcategory=source.subcategory,
                markdown_text_length=len(markdown_text),
                extracted_raw=cached,
            )

        print(f"[EXTRACT] {index}/{total} {source_name}")
        started_at = time.monotonic()
        attempts = max(1, max_retries + 1)
        for attempt in range(1, attempts + 1):
            try:
                extracted_raw = await runtime["extract_brand_knowledge_from_markdown"](
                    markdown_text,
                    brand_name=brand_name,
                    source_name=source_name,
                    subcategory=source.subcategory,
                    settings=service._settings,
                )
                _write_extract_cache(
                    cache_dir,
                    cache_key,
                    brand_name=brand_name,
                    source=source,
                    extracted_raw=extracted_raw,
                )
                elapsed = time.monotonic() - started_at
                print(f"[EXTRACT_OK] {index}/{total} {source_name} elapsed={elapsed:.1f}s")
                return ExtractedMarkdownResult(
                    source=source,
                    source_name=source_name,
                    subcategory=source.subcategory,
                    markdown_text_length=len(markdown_text),
                    extracted_raw=extracted_raw,
                )
            except Exception as exc:
                if attempt >= attempts:
                    elapsed = time.monotonic() - started_at
                    print(
                        f"[EXTRACT_FAIL] {index}/{total} {source_name} "
                        f"attempt={attempt}/{attempts} elapsed={elapsed:.1f}s error={exc}",
                        file=sys.stderr,
                    )
                    raise
                delay = _EXTRACT_RETRY_DELAYS_SECONDS[
                    min(attempt - 1, len(_EXTRACT_RETRY_DELAYS_SECONDS) - 1)
                ]
                print(
                    f"[EXTRACT_RETRY] {index}/{total} {source_name} "
                    f"attempt={attempt}/{attempts} wait={delay:.1f}s error={exc}",
                    file=sys.stderr,
                )
                await asyncio.sleep(delay)

    raise RuntimeError(f"Markdown 抽取异常结束: {source.name}")


def _build_existing_aggregated(
    service: Any,
    *,
    brand: dict[str, Any],
    existing_products: list[dict[str, Any]],
    knowledge_map: dict[str, Any],
) -> dict[str, Any]:
    runtime = _load_runtime()
    aggregated = runtime["_build_empty_knowledge"]()
    aggregated["basic_info"] = runtime["_build_basic_info_from_brand"](
        service,
        brand,
        aggregated["basic_info"],
    )
    aggregated["products"] = runtime["_build_brand_product_payloads"](service, existing_products)

    company_profile = knowledge_map.get("company_profile") or knowledge_map.get("company_info") or {}
    if isinstance(company_profile, dict):
        existing_company_profile = dict(company_profile)
        existing_company_profile.setdefault("source_files", [])
        aggregated["company_profile"].update(existing_company_profile)

    for section_name in (
        "management_team",
        "competitors",
        "authority_honors",
        "customers_cases",
        "official_malls",
        "official_media_matrix",
        "other_info",
    ):
        value = knowledge_map.get(section_name)
        if isinstance(value, list):
            aggregated[section_name] = [
                dict(item) if isinstance(item, dict) else item
                for item in value
            ]
    attachments = knowledge_map.get("attachments")
    if isinstance(attachments, list):
        aggregated["attachments"] = [
            dict(item) if isinstance(item, dict) else item
            for item in attachments
        ]

    return aggregated


def _merge_attachment_entries(existing_value: Any, incoming_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def _normalize_item(item: Any) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        name = str(item.get("name") or "").strip()
        url = str(
            item.get("url")
            or item.get("source_url")
            or item.get("local_path")
            or ""
        ).strip()
        if not name:
            return None
        normalized = dict(item)
        if url and "url" not in normalized:
            normalized["url"] = url
        return normalized

    for item in list(existing_value or []) + incoming_entries:
        normalized = _normalize_item(item)
        if normalized is None:
            continue
        name = str(normalized.get("name") or "").strip()
        url = str(
            normalized.get("url")
            or normalized.get("source_url")
            or normalized.get("local_path")
            or ""
        ).strip()
        identity = (name, url)
        if identity in seen:
            continue
        seen.add(identity)
        merged.append(normalized)
    return merged


def _dedupe_text_list(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _merge_sensitive_topics(existing_value: Any, incoming_value: Any) -> dict[str, list[str]]:
    runtime = _load_runtime()
    brand_application_service = runtime["BrandApplicationService"]
    existing_normalized = brand_application_service._serialize_sensitive_topics_payload(existing_value)
    incoming_normalized = brand_application_service._serialize_sensitive_topics_payload(incoming_value)
    merged = {
        key: _dedupe_text_list(
            list(existing_normalized.get(key, [])) + list(incoming_normalized.get(key, []))
        )
        for key in (
            "sensitive_contents",
            "controversial_events",
            "forbidden_words",
            "negative_clarifications",
            "other_info",
        )
    }
    return {
        key: value
        for key, value in merged.items()
        if value
    }


def _normalize_product_name(product: Any) -> str:
    if not isinstance(product, dict):
        return ""
    return str(product.get("name") or product.get("product_name") or "").strip()


def _product_name_keys(products: Any) -> set[str]:
    if not isinstance(products, list):
        return set()
    return {
        name.casefold()
        for item in products
        if (name := _normalize_product_name(item))
    }


def _normalize_string_list(value: Any) -> list[str]:
    runtime = _load_runtime()
    brand_application_service = runtime["BrandApplicationService"]
    return [
        str(item).strip()
        for item in brand_application_service.normalize_sequence_value(value)
        if str(item).strip()
    ]


def _normalize_attachment_product_payload(product: dict[str, Any]) -> dict[str, Any] | None:
    name = _normalize_product_name(product)
    if not name:
        return None
    payload: dict[str, Any] = {"name": name}
    for field in _PRODUCT_TEXT_FIELDS:
        value = product.get(field)
        if field == "product_website" and not value:
            value = product.get("product_link")
        if field == "product_advantages" and not value:
            value = product.get("advantages")
        if field == "target_scenarios" and not value:
            value = product.get("scenarios")
        payload[field] = str(value).strip() if value is not None and str(value).strip() else None
    for field in _PRODUCT_LIST_FIELDS:
        source_value = product.get(field)
        if field == "product_images" and source_value is None:
            source_value = product.get("product_images_json")
        if field == "coverage_regions" and source_value is None:
            source_value = product.get("coverage_regions_json")
        payload[field] = _normalize_string_list(source_value)
    return payload


def _split_products_for_storage(
    *,
    existing_products: list[dict[str, Any]],
    existing_attachment_products: list[dict[str, Any]],
    extracted_products: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    formal_product_names = _product_name_keys(existing_products)
    attachment_product_names = _product_name_keys(existing_attachment_products)
    known_product_names = formal_product_names | attachment_product_names
    formal_updates: list[dict[str, Any]] = []
    new_attachment_products: list[dict[str, Any]] = []
    seen_formal: set[str] = set()
    seen_attachment: set[str] = set()

    for item in extracted_products if isinstance(extracted_products, list) else []:
        if not isinstance(item, dict):
            continue
        name = _normalize_product_name(item)
        if not name:
            continue
        key = name.casefold()
        if key in formal_product_names:
            if key not in seen_formal:
                formal_updates.append(dict(item, name=name))
                seen_formal.add(key)
            continue
        if key in known_product_names or key in seen_attachment:
            continue
        normalized = _normalize_attachment_product_payload(dict(item, name=name))
        if normalized is None:
            continue
        new_attachment_products.append(normalized)
        seen_attachment.add(key)
    return formal_updates, new_attachment_products


def _merge_attachment_products(
    existing_attachment_products: list[dict[str, Any]],
    new_attachment_products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    index_by_name: dict[str, int] = {}

    def add_or_merge(product: dict[str, Any]) -> None:
        normalized = _normalize_attachment_product_payload(product)
        if normalized is None:
            return
        key = normalized["name"].casefold()
        if key not in index_by_name:
            index_by_name[key] = len(merged)
            merged.append(normalized)
            return

        existing = merged[index_by_name[key]]
        for field in _PRODUCT_TEXT_FIELDS:
            if not existing.get(field) and normalized.get(field):
                existing[field] = normalized[field]
        for field in _PRODUCT_LIST_FIELDS:
            current_values = list(existing.get(field) or [])
            seen_values = {str(item).strip() for item in current_values if str(item).strip()}
            for item in normalized.get(field) or []:
                item_text = str(item).strip()
                if item_text and item_text not in seen_values:
                    current_values.append(item_text)
                    seen_values.add(item_text)
            existing[field] = current_values

    for product in existing_attachment_products:
        if isinstance(product, dict):
            add_or_merge(product)
    for product in new_attachment_products:
        if isinstance(product, dict):
            add_or_merge(product)
    return merged


async def _process_brand(
    service: Any,
    *,
    job: BrandJob,
    write_db: bool,
    write_sections: set[str],
    fill_empty_only: bool,
    use_tianyancha: bool,
    output_dir: Path | None,
    extract_concurrency: int,
    extract_cache_dir: Path | None,
    extract_retries: int,
) -> dict[str, Any]:
    runtime = _load_runtime()
    brand_name = job.brand_name
    brand = service._brands.get_brand_by_name(brand_name)
    if not brand or brand.get("id") is None:
        raise ValueError(f"品牌不存在 brand_name={brand_name}")

    brand_id = int(brand["id"])
    existing_products = service._brand_products.get_brand_products(brand_id=brand_id)
    existing_rows = service._brand_knowledge.get_all_brand_knowledge_json(brand_id=brand_id)
    knowledge_map = {
        str(row.get("knowledge_type") or "").strip(): runtime["_load_content_json"](row.get("content_json"))
        for row in existing_rows
        if str(row.get("knowledge_type") or "").strip()
    }

    aggregated = _build_existing_aggregated(
        service,
        brand=brand,
        existing_products=existing_products,
        knowledge_map=knowledge_map,
    )
    existing_snapshot = _copy_jsonable(aggregated)
    existing_sensitive_topics = knowledge_map.get("sensitive_topics") or {}
    existing_attachment_products = (
        knowledge_map.get(_ATTACHMENT_PRODUCTS_KNOWLEDGE_TYPE)
        if isinstance(knowledge_map.get(_ATTACHMENT_PRODUCTS_KNOWLEDGE_TYPE), list)
        else []
    )
    extracted_sensitive_topics: list[dict[str, Any]] = []
    local_attachments: list[dict[str, Any]] = []

    semaphore = asyncio.Semaphore(max(1, extract_concurrency))
    extracted_results = await asyncio.gather(
        *[
            _extract_markdown_source(
                service,
                runtime=runtime,
                brand_name=brand_name,
                source=markdown_source,
                index=index,
                total=len(job.markdown_sources),
                semaphore=semaphore,
                cache_dir=extract_cache_dir,
                max_retries=max(0, extract_retries),
            )
            for index, markdown_source in enumerate(job.markdown_sources, start=1)
        ]
    )

    for result in extracted_results:
        markdown_source = result.source
        source_name = result.source_name
        subcategory = result.subcategory
        extracted = runtime["_normalize_extraction_result"](
            result.extracted_raw,
            source_file=source_name,
        )
        extracted["source_file"] = source_name
        extracted_sensitive_topics.extend(
            dict(item) for item in extracted.get("sensitive_topics", []) if isinstance(item, dict)
        )
        extracted["sensitive_topics"] = []
        aggregated = runtime["_merge_brand_knowledge"](base=aggregated, extracted=extracted)
        if markdown_source.kind == "local":
            assert markdown_source.path is not None
            local_attachments.append(
                {
                    "name": markdown_source.path.name,
                    "url": markdown_source.path.resolve().as_uri(),
                    "source_url": str(markdown_source.path.resolve()),
                    "source_type": "local_markdown",
                    "subcategory": subcategory,
                    "fulltext_length": result.markdown_text_length,
                }
            )
        else:
            local_attachments.append(
                {
                    "name": source_name.split("/")[-1] or source_name,
                    "url": service.oss_client.build_object_url(markdown_source.oss_key or "") or "",
                    "source_url": markdown_source.oss_key,
                    "source_type": "oss_markdown",
                    "subcategory": subcategory,
                    "fulltext_length": result.markdown_text_length,
                }
            )

    final_payload = runtime["_sanitize_final_payload"](aggregated)
    final_payload["attachments"] = _merge_attachment_entries(
        knowledge_map.get("attachments") or [],
        local_attachments,
    )
    final_payload["sensitive_topics"] = _merge_sensitive_topics(
        existing_sensitive_topics,
        extracted_sensitive_topics,
    )

    if use_tianyancha:
        (
            enriched_basic_info,
            enriched_company_profile,
            enriched_management_team,
            enriched_competitors,
        ) = await runtime["enrich_brand_from_tianyancha"](
            service,
            brand=brand,
            extracted_basic_info=final_payload["basic_info"],
            company_profile=final_payload["company_profile"],
            management_team=final_payload["management_team"],
            competitors=final_payload["competitors"],
        )
        final_payload["basic_info"] = enriched_basic_info
        final_payload["company_profile"] = enriched_company_profile
        final_payload["management_team"] = enriched_management_team
        final_payload["competitors"] = enriched_competitors

    if fill_empty_only:
        final_payload = _apply_fill_empty_only_policy(
            final_payload=final_payload,
            existing_snapshot=existing_snapshot,
            existing_sensitive_topics=existing_sensitive_topics,
            incoming_sensitive_topics=extracted_sensitive_topics,
        )

    formal_product_updates, new_attachment_products = _split_products_for_storage(
        existing_products=existing_products,
        existing_attachment_products=existing_attachment_products,
        extracted_products=final_payload.get("products"),
    )
    merged_attachment_products = _merge_attachment_products(
        existing_attachment_products,
        new_attachment_products,
    )
    final_payload["attachment_products"] = _copy_jsonable(merged_attachment_products)
    final_payload["new_attachment_products"] = _copy_jsonable(new_attachment_products)
    final_payload["formal_product_updates"] = _copy_jsonable(formal_product_updates)

    if write_db:
        if "basic_info" in write_sections:
            runtime["_apply_extracted_basic_info_to_brand"](
                service,
                brand=brand,
                extracted_basic_info=final_payload["basic_info"],
                company_profile=final_payload["company_profile"] if "company_profile" in write_sections else {},
                knowledge_revision=None,
            )
        if "products" in write_sections:
            if formal_product_updates:
                runtime["_apply_extracted_products_to_brand_products"](
                    service,
                    brand_id=brand_id,
                    brand_name=brand_name,
                    existing_products=existing_products,
                    extracted_products=formal_product_updates,
                )
            if new_attachment_products:
                service._brand_knowledge.upsert_brand_knowledge_json(
                    brand_id=brand_id,
                    knowledge_type=_ATTACHMENT_PRODUCTS_KNOWLEDGE_TYPE,
                    content_json=merged_attachment_products,
                    source_task_id=None,
                )
        elif "attachment_products" in write_sections and new_attachment_products:
            service._brand_knowledge.upsert_brand_knowledge_json(
                brand_id=brand_id,
                knowledge_type=_ATTACHMENT_PRODUCTS_KNOWLEDGE_TYPE,
                content_json=merged_attachment_products,
                source_task_id=None,
            )
        for knowledge_type in runtime["_KNOWLEDGE_TYPES"]:
            if knowledge_type not in write_sections:
                continue
            service._brand_knowledge.upsert_brand_knowledge_json(
                brand_id=brand_id,
                knowledge_type=knowledge_type,
                content_json=final_payload[knowledge_type],
                source_task_id=None,
            )

        refreshed_brand = service._brands.get_brand_by_name(brand_name) or brand
        refreshed_products = service._brand_products.get_brand_products(brand_id=brand_id)
        refreshed_rows = service._brand_knowledge.get_all_brand_knowledge_json(brand_id=brand_id)
        refreshed_knowledge_map = {
            str(row.get("knowledge_type") or "").strip(): runtime["_load_content_json"](row.get("content_json"))
            for row in refreshed_rows
            if str(row.get("knowledge_type") or "").strip()
        }
        if "basic_info" in write_sections:
            final_payload["basic_info"] = runtime["_build_basic_info_from_brand"](
                service,
                refreshed_brand,
                final_payload["basic_info"],
            )
        if "products" in write_sections:
            final_payload["products"] = runtime["_build_brand_product_payloads"](service, refreshed_products)
        if "products" in write_sections or "attachment_products" in write_sections:
            final_payload["attachment_products"] = (
                refreshed_knowledge_map.get(_ATTACHMENT_PRODUCTS_KNOWLEDGE_TYPE)
                if isinstance(refreshed_knowledge_map.get(_ATTACHMENT_PRODUCTS_KNOWLEDGE_TYPE), list)
                else []
            )

    if output_dir is not None:
        resolved_output_dir = output_dir.expanduser().resolve()
        resolved_output_dir.mkdir(parents=True, exist_ok=True)
        output_path = resolved_output_dir / f"{_safe_output_name(brand_name)}.json"
        output_path.write_text(
            json.dumps(
                {
                    "brand_name": brand_name,
                    "brand_id": brand_id,
                    "markdown_files": [source.identifier for source in job.markdown_sources],
                    "written_to_db": write_db,
                    "write_sections": sorted(write_sections),
                    "fill_empty_only": fill_empty_only,
                    "extract_concurrency": extract_concurrency,
                    "extract_retries": extract_retries,
                    "extract_cache_dir": str(extract_cache_dir) if extract_cache_dir is not None else None,
                    "knowledge": final_payload,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    return {
        "brand_name": brand_name,
        "brand_id": brand_id,
        "markdown_file_count": len(job.markdown_sources),
        "written_to_db": write_db,
        "write_sections": sorted(write_sections),
        "fill_empty_only": fill_empty_only,
        "used_tianyancha": use_tianyancha,
        "extract_concurrency": extract_concurrency,
        "extract_retries": extract_retries,
        "extract_cache_dir": str(extract_cache_dir) if extract_cache_dir is not None else None,
        "knowledge": _copy_jsonable(final_payload),
    }


async def _async_main(args: argparse.Namespace) -> int:
    jobs = _build_jobs(args)
    if not jobs:
        print("没有找到可处理的品牌目录或 Markdown 文件")
        return 0
    write_sections = _resolve_write_sections(args)
    extract_concurrency = max(1, int(args.extract_concurrency or 1))
    extract_retries = max(0, int(args.extract_retries or 0))
    extract_cache_dir = _resolve_extract_cache_dir(args)

    runtime = _load_runtime()
    settings = runtime["configure_logging"]()
    service = runtime["build_service"]()
    callback_url = _resolve_callback_url(args, settings)
    callback_timeout_seconds = _resolve_callback_timeout(args, settings)
    should_send_success_callback = bool(callback_url) and (not args.dry_run or args.callback_on_dry_run)
    if callback_url and args.dry_run and not args.callback_on_dry_run:
        print("[CALLBACK] dry-run 模式默认不发送回调；如需联调回调接收，请加 --callback-on-dry-run")
    jobs = [
        BrandJob(
            brand_name=job.brand_name,
            brand_root=job.brand_root,
            markdown_sources=(
                _load_oss_markdown_sources(
                    service,
                    brand_name=job.brand_name,
                    explicit_prefix=args.oss_prefix,
                )
                if args.from_oss_converted
                else job.markdown_sources
            ),
        )
        for job in jobs
    ]

    success_results: list[dict[str, Any]] = []
    failed_results: list[dict[str, Any]] = []
    callback_results: list[dict[str, Any]] = []

    for job in jobs:
        print(
            f"[START] brand={job.brand_name} markdown_count={len(job.markdown_sources)} "
            f"extract_concurrency={extract_concurrency} extract_retries={extract_retries} "
            f"extract_cache={'disabled' if extract_cache_dir is None else extract_cache_dir}"
        )
        try:
            result = await _process_brand(
                service,
                job=job,
                write_db=not args.dry_run,
                write_sections=write_sections,
                fill_empty_only=bool(args.fill_empty_only),
                use_tianyancha=not args.skip_tianyancha,
                output_dir=args.output_dir,
                extract_concurrency=extract_concurrency,
                extract_cache_dir=extract_cache_dir,
                extract_retries=extract_retries,
            )
            success_results.append(result)
            print(
                f"[OK] brand={job.brand_name} markdown_count={len(job.markdown_sources)} "
                f"written_to_db={not args.dry_run}"
            )
            if should_send_success_callback and callback_url:
                callback_result = await _send_backfill_callback(
                    service,
                    result=result,
                    status="success",
                    error_message=None,
                    callback_url=callback_url,
                    timeout_seconds=callback_timeout_seconds,
                    callback_task_prefix=args.callback_task_prefix,
                )
                callback_result["brand_name"] = job.brand_name
                callback_results.append(callback_result)
                print(
                    f"[CALLBACK] brand={job.brand_name} status={callback_result['status']} "
                    f"response_code={callback_result['response_code']} task_id={callback_result['task_id']}"
                )
                if callback_result["status"] != "success":
                    failed_results.append(
                        {
                            "brand_name": job.brand_name,
                            "error": f"callback failed: {callback_result.get('error') or callback_result.get('response_body')}",
                        }
                    )
                    if args.fail_fast:
                        break
        except Exception as exc:
            failed_item = {
                "brand_name": job.brand_name,
                "error": str(exc),
            }
            failed_results.append(failed_item)
            print(f"[FAIL] brand={job.brand_name} error={exc}", file=sys.stderr)
            if args.callback_on_failure and callback_url and (not args.dry_run or args.callback_on_dry_run):
                callback_result = await _send_backfill_callback(
                    service,
                    result={"brand_name": job.brand_name, "knowledge": {}},
                    status="failed",
                    error_message=str(exc),
                    callback_url=callback_url,
                    timeout_seconds=callback_timeout_seconds,
                    callback_task_prefix=args.callback_task_prefix,
                )
                callback_result["brand_name"] = job.brand_name
                callback_results.append(callback_result)
                print(
                    f"[CALLBACK] brand={job.brand_name} status={callback_result['status']} "
                    f"response_code={callback_result['response_code']} task_id={callback_result['task_id']}"
                )
                if callback_result["status"] != "success":
                    failed_results.append(
                        {
                            "brand_name": job.brand_name,
                            "error": f"failure callback failed: {callback_result.get('error') or callback_result.get('response_body')}",
                        }
                    )
            if args.fail_fast:
                break

    summary = {
        "success_count": len(success_results),
        "failed_count": len(failed_results),
        "dry_run": bool(args.dry_run),
        "results": [
            {
                "brand_name": item["brand_name"],
                "brand_id": item["brand_id"],
                "markdown_file_count": item["markdown_file_count"],
                "written_to_db": item["written_to_db"],
                "write_sections": item["write_sections"],
                "fill_empty_only": item["fill_empty_only"],
                "used_tianyancha": item["used_tianyancha"],
                "extract_concurrency": item["extract_concurrency"],
                "extract_retries": item["extract_retries"],
                "extract_cache_dir": item["extract_cache_dir"],
            }
            for item in success_results
        ],
        "errors": failed_results,
        "callbacks": callback_results,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if failed_results else 0


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
