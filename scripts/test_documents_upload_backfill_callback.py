#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "测试辅助脚本：复用 `/api/v1/documents/upload` 正式知识库回填规则与 completed callback 口径，"
            "但不走 upload task / Milvus / facts / OSS 正式入库。默认 dry-run，只预览回填后的快照和回调 JSON。"
        )
    )
    parser.add_argument(
        "--markdown-file",
        type=Path,
        required=True,
        help="要测试的正式知识库 Markdown 文件。",
    )
    parser.add_argument(
        "--brand-name",
        help="可选；不传时优先从文件名 `【品牌名】品牌AI知识库_Vx_YYYYMMDD.md` 解析。",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="真的执行回填写库。默认只做 dry-run 预览，不写数据库。",
    )
    parser.add_argument(
        "--skip-callback-payload",
        action="store_true",
        help="只跑回填，不构造 completed callback JSON。",
    )
    parser.add_argument(
        "--callback",
        action="store_true",
        help="发送 callback 到环境变量里的 BRAND_COMPLETION_CALLBACK_URL。",
    )
    parser.add_argument(
        "--callback-url",
        help="显式指定 callback URL；传这个时优先于 --callback。",
    )
    parser.add_argument(
        "--callback-timeout-seconds",
        type=float,
        help="callback 超时时间；默认走配置里的 BRAND_COMPLETION_CALLBACK_TIMEOUT_SECONDS。",
    )
    parser.add_argument(
        "--source-task-id",
        help="写回 brand_knowledge_json 时记录的 source_task_id。默认自动生成。",
    )
    parser.add_argument(
        "--knowledge-version",
        help="可选；覆盖 callback payload 里的 knowledge_mete.version。",
    )
    parser.add_argument(
        "--knowledge-oss-url-md",
        help="可选；覆盖 callback payload 里的 knowledge_mete.oss_url_md。",
    )
    parser.add_argument(
        "--knowledge-oss-url-pdf",
        help="可选；覆盖 callback payload 里的 knowledge_mete.oss_url_pdf。",
    )
    parser.add_argument(
        "--output-callback-json",
        type=Path,
        help="把 callback payload 落到本地 JSON 文件。",
    )
    parser.add_argument(
        "--output-snapshot-json",
        type=Path,
        help="把最终知识快照落到本地 JSON 文件。",
    )
    return parser


def _load_runtime() -> dict[str, Any]:
    try:
        import requests

        from knowledge_base.brand.ai_knowledge_filename import parse_ai_knowledge_filename
        from knowledge_base.brand.application.ai_knowledge_ingestion import (
            BrandAiKnowledgeIngestionDependencies,
            BrandAiKnowledgeIngestionService,
        )
        from knowledge_base.brand.application.callbacks import (
            _build_callback_payload_with_knowledge,
            maybe_finalize_task_callback,
        )
        from knowledge_base.brand.callback_mapper import format_brand_callback_knowledge_from_snapshot
        from knowledge_base.brand.knowledge_extraction import (
            _filter_other_info_entries,
            _merge_other_info_with_attachment_products,
            extract_brand_knowledge_snapshot_from_markdown,
        )
        from knowledge_base.composition import KnowledgeBaseRuntimeState, build_mysql_stores
        from knowledge_base.infrastructure import OSSClient, TianyanchaClient, get_settings, setup_logging
    except ModuleNotFoundError as exc:
        missing_name = getattr(exc, "name", "") or str(exc)
        raise RuntimeError(
            "项目依赖未安装，无法执行测试脚本。"
            "请在项目虚拟环境中运行，例如 `uv run python scripts/test_documents_upload_backfill_callback.py ...`，"
            f"当前缺少模块: {missing_name}"
        ) from exc

    return {
        "requests": requests,
        "parse_ai_knowledge_filename": parse_ai_knowledge_filename,
        "BrandAiKnowledgeIngestionDependencies": BrandAiKnowledgeIngestionDependencies,
        "BrandAiKnowledgeIngestionService": BrandAiKnowledgeIngestionService,
        "KnowledgeBaseRuntimeState": KnowledgeBaseRuntimeState,
        "build_mysql_stores": build_mysql_stores,
        "get_settings": get_settings,
        "setup_logging": setup_logging,
        "OSSClient": OSSClient,
        "TianyanchaClient": TianyanchaClient,
        "format_brand_callback_knowledge_from_snapshot": format_brand_callback_knowledge_from_snapshot,
        "extract_brand_knowledge_snapshot_from_markdown": extract_brand_knowledge_snapshot_from_markdown,
        "_merge_other_info_with_attachment_products": _merge_other_info_with_attachment_products,
        "_filter_other_info_entries": _filter_other_info_entries,
        "_build_callback_payload_with_knowledge": _build_callback_payload_with_knowledge,
        "maybe_finalize_task_callback": maybe_finalize_task_callback,
    }


def _resolve_brand_name(*, args: argparse.Namespace, runtime: dict[str, Any], markdown_path: Path) -> str:
    explicit_brand_name = str(args.brand_name or "").strip()
    if explicit_brand_name:
        return explicit_brand_name
    parsed = runtime["parse_ai_knowledge_filename"](markdown_path.name)
    if parsed is not None:
        return str(parsed.brand_name or "").strip()
    raise ValueError("未传 --brand-name，且无法从文件名解析品牌名")


def _resolve_callback_url(*, args: argparse.Namespace, settings: Any) -> str | None:
    explicit_url = str(args.callback_url or "").strip()
    if explicit_url:
        return explicit_url
    if not args.callback:
        return None
    configured_url = str(getattr(settings, "brand_completion_callback_url", "") or "").strip()
    if not configured_url:
        raise ValueError("已启用 --callback，但 BRAND_COMPLETION_CALLBACK_URL 未配置")
    return configured_url


def _resolve_callback_timeout(*, args: argparse.Namespace, settings: Any) -> float:
    if args.callback_timeout_seconds is not None:
        return float(args.callback_timeout_seconds)
    return float(getattr(settings, "brand_completion_callback_timeout_seconds", 5.0))


def _build_source_task_id(*, args: argparse.Namespace, brand_name: str) -> str:
    explicit = str(args.source_task_id or "").strip()
    if explicit:
        return explicit
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"manual_documents_upload_backfill:{brand_name}:{timestamp}"


def _write_json_file(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class _LightweightCallbackBackfillService:
    def __init__(self, *, settings: Any, stores: Any, runtime: Any, oss_client: Any, tianyancha_client: Any) -> None:
        self._settings = settings
        self._brands = stores.brands
        self._brand_products = stores.brand_products
        self._brand_knowledge = stores.brand_knowledge
        self._brand_full_knowledge = stores.brand_full_knowledge
        self._brand_knowledge_facts = stores.brand_knowledge_facts
        self._brand_knowledge_ingestion_jobs = stores.brand_knowledge_ingestion_jobs
        self._brand_knowledge_sessions = stores.brand_knowledge_sessions
        self._upload_tasks = stores.upload_tasks
        self._document_registry = stores.document_registry
        self._runtime = runtime
        self.oss_client = oss_client
        self._tianyancha_client = tianyancha_client
        self._preview_snapshots_by_brand_code: dict[str, dict[str, Any]] = {}
        self._knowledge_mete_override_by_brand_code: dict[str, dict[str, str]] = {}

    @staticmethod
    def _spawn_background_task(coro: Any) -> asyncio.Task[Any]:
        return asyncio.create_task(coro)

    @staticmethod
    def _parse_json_value(raw: Any, default: Any) -> Any:
        if raw is None:
            return default
        if isinstance(raw, (dict, list)):
            return raw
        if isinstance(raw, str) and raw.strip():
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return default
        return default

    @staticmethod
    def _normalize_attachment_entries(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        normalized: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for item in value:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("attachment_name") or "").strip()
            url = str(item.get("url") or item.get("source_url") or "").strip()
            if not name:
                continue
            dedupe_key = (name.casefold(), url)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            entry: dict[str, Any] = {"name": name}
            if url:
                entry["url"] = url
            for key in ("type", "description"):
                text = str(item.get(key) or "").strip()
                if text:
                    entry[key] = text
            normalized.append(entry)
        return normalized

    def _load_brand_knowledge_snapshot(self, *, brand: dict[str, Any]) -> dict[str, Any]:
        brand_code = str((brand or {}).get("brand_code") or "").strip()
        if brand_code and brand_code in self._preview_snapshots_by_brand_code:
            return json.loads(json.dumps(self._preview_snapshots_by_brand_code[brand_code], ensure_ascii=False))

        brand_id = brand.get("id")
        if brand_id is None:
            return {"basic_info": {}, "attachments": []}
        knowledge_rows = self._brand_knowledge.get_all_brand_knowledge_json(brand_id=int(brand_id))
        knowledge_map = {
            str(row.get("knowledge_type") or "").strip(): self._parse_json_value(row.get("content_json"), None)
            for row in knowledge_rows
            if str(row.get("knowledge_type") or "").strip()
        }
        products: list[dict[str, Any]] = []
        for product in self._brand_products.get_brand_products(brand_id=int(brand_id)):
            if not isinstance(product, dict):
                continue
            products.append(
                {
                    "name": str(product.get("product_name") or product.get("name") or "").strip(),
                    "product_description": product.get("product_description"),
                    "product_website": product.get("product_website"),
                    "product_images": self._parse_json_value(
                        product.get("product_images_json"),
                        product.get("product_images") or [],
                    ),
                    "coverage_regions": self._parse_json_value(
                        product.get("coverage_regions_json"),
                        product.get("coverage_regions") or [],
                    ),
                    "price_info": product.get("price_info"),
                    "product_advantages": product.get("product_advantages"),
                    "target_scenarios": product.get("target_scenarios"),
                    "service_standard": product.get("service_standard"),
                    "service_process": product.get("service_process"),
                    "cases_and_reputation": product.get("cases_and_reputation"),
                    "certification_info": product.get("certification_info"),
                    "core_technology": product.get("core_technology"),
                    "other_info": product.get("other_info"),
                }
            )
        return {
            "basic_info": {
                "brand_code": brand.get("brand_code"),
                "brand_name": brand.get("brand_name"),
                "brand_alias": brand.get("brand_alias"),
                "brand_logo": brand.get("brand_logo"),
                "website": brand.get("website"),
                "customer_service_hotline": brand.get("customer_service_hotline"),
                "intro": brand.get("intro"),
                "email": brand.get("email"),
                "brand_enterprise_entity": brand.get("brand_enterprise_entity"),
                "business_license_image_path": brand.get("business_license_image_path"),
                "english_name": brand.get("english_name"),
                "official_wechat_account": brand.get("official_wechat_account"),
                "positioning": brand.get("positioning"),
                "advantages": brand.get("advantages"),
                "mission": brand.get("mission"),
                "vision": brand.get("vision"),
                "target_regions": brand.get("target_regions_json"),
                "other_info": brand.get("other_info"),
            },
            "company_profile": knowledge_map.get("company_profile") or knowledge_map.get("company_info") or {},
            "management_team": knowledge_map.get("management_team") or [],
            "competitors": knowledge_map.get("competitors") or [],
            "authority_honors": knowledge_map.get("authority_honors") or knowledge_map.get("honors") or [],
            "customers_cases": knowledge_map.get("customers_cases") or knowledge_map.get("cases") or [],
            "products": products,
            "attachment_products": knowledge_map.get("attachment_products") or [],
            "sensitive_topics": knowledge_map.get("sensitive_topics") or {},
            "attachments": self._normalize_attachment_entries(knowledge_map.get("attachments")),
            "official_malls": knowledge_map.get("official_malls") or [],
            "official_media_matrix": knowledge_map.get("official_media_matrix") or [],
            "other_info": knowledge_map.get("other_info") or [],
        }

    def _current_brand_knowledge_mete(self, *, brand: dict[str, Any]) -> tuple[str, dict[str, str]]:
        brand_code = str((brand or {}).get("brand_code") or "").strip()
        version = str((brand or {}).get("knowledge_revision") or "").strip()
        latest = None
        brand_id = brand.get("id")
        if brand_id is not None:
            latest = self._brand_full_knowledge.get_latest_by_brand_id(brand_id=int(brand_id))
        knowledge_mete = {
            "version": version,
            "oss_url_md": str((latest or {}).get("oss_url") or "").strip(),
            "oss_url_pdf": str((latest or {}).get("pdf_oss_url") or "").strip(),
        }
        override = self._knowledge_mete_override_by_brand_code.get(brand_code)
        if isinstance(override, dict):
            knowledge_mete = {
                "version": str(override.get("version") or knowledge_mete.get("version") or "").strip(),
                "oss_url_md": str(override.get("oss_url_md") or knowledge_mete.get("oss_url_md") or "").strip(),
                "oss_url_pdf": str(override.get("oss_url_pdf") or knowledge_mete.get("oss_url_pdf") or "").strip(),
            }
        return ("success" if latest else "skipped", knowledge_mete)


async def _build_preview_snapshot(
    *,
    service: Any,
    ingestion_service: Any,
    runtime: dict[str, Any],
    brand: dict[str, Any],
    brand_name: str,
    markdown_text: str,
    source_name: str,
) -> dict[str, Any]:
    brand_id = int(brand["id"])
    existing_snapshot = ingestion_service._load_existing_brand_knowledge_snapshot(brand_id=brand_id)
    incoming_snapshot = await runtime["extract_brand_knowledge_snapshot_from_markdown"](
        brand_name=brand_name,
        markdown_text=markdown_text,
        source_name=source_name,
        settings=service._settings,
    )
    merged_snapshot = ingestion_service._merge_full_markdown_backfill_snapshot(
        existing_snapshot=existing_snapshot,
        incoming_snapshot=incoming_snapshot,
    )
    merged_attachment_products = ingestion_service._build_attachment_products_from_full_markdown(
        brand_id=brand_id,
        incoming_snapshot=incoming_snapshot,
    )
    merged_snapshot["other_info"] = runtime["_merge_other_info_with_attachment_products"](
        merged_snapshot.get("other_info"),
        merged_attachment_products,
    )
    merged_snapshot["attachment_products"] = merged_attachment_products
    merged_snapshot["other_info"] = runtime["_filter_other_info_entries"](
        merged_snapshot.get("other_info"),
        snapshot=merged_snapshot,
    )
    return merged_snapshot


def _build_runtime_state(runtime_cls: Any) -> Any:
    return runtime_cls(
        upload_queue=asyncio.Queue(),
        queued_task_ids=set(),
        queue_lock=asyncio.Lock(),
        background_job_queue=asyncio.Queue(),
        queued_background_job_ids=set(),
        background_job_queue_lock=asyncio.Lock(),
        inflight_brand_callbacks=set(),
        scheduled_brand_callback_retries=set(),
        scheduled_brand_completion_checks=set(),
        scheduled_attachment_conflict_callback_retries=set(),
        scheduled_attachment_confirm_callback_retries=set(),
        scheduled_attachment_delete_callback_retries=set(),
    )


def _build_lightweight_service(runtime: dict[str, Any]) -> Any:
    settings = runtime["get_settings"]()
    log_file = Path(settings.log_dir) / "app.log"
    runtime["setup_logging"](level=settings.log_level, log_file=str(log_file))
    stores = runtime["build_mysql_stores"](settings)
    runtime_state = _build_runtime_state(runtime["KnowledgeBaseRuntimeState"])
    oss_client = runtime["OSSClient"](settings)
    tianyancha_client = runtime["TianyanchaClient"](settings)
    return _LightweightCallbackBackfillService(
        settings=settings,
        stores=stores,
        runtime=runtime_state,
        oss_client=oss_client,
        tianyancha_client=tianyancha_client,
    )


def _build_upload_file_record(*, markdown_path: Path, source_name: str, markdown_text: str) -> dict[str, Any]:
    return {
        "file_index": 0,
        "original_filename": source_name,
        "file_role": "brand_ai_knowledge",
        "stored_path": str(markdown_path),
        "file_size": len(markdown_text.encode("utf-8")),
        "file_hash": hashlib.sha256(markdown_text.encode("utf-8")).hexdigest(),
        "converted_version": None,
        "content_type": "text/markdown",
        "status": "success",
        "error_message": None,
    }


def _create_synthetic_upload_task(
    *,
    service: Any,
    task_id: str,
    brand: dict[str, Any],
    brand_name: str,
    upload_file: dict[str, Any],
) -> None:
    metadata = {
        "brand_code": str(brand.get("brand_code") or "").strip(),
        "brand_name": brand_name,
        "category": brand_name,
        "brand_callback_enabled": True,
    }
    service._upload_tasks.create_upload_task(
        task_id=task_id,
        task_type="document_upload",
        metadata=metadata,
        chunk_size=None,
        chunk_overlap=None,
        files=[upload_file],
    )
    files = service._upload_tasks.get_upload_task_files(task_id)
    if not files:
        raise RuntimeError("synthetic upload task file 创建失败")
    file_id = int(files[0]["id"])
    service._upload_tasks.update_upload_task_file_status(
        file_id,
        "success",
        content_type="text/markdown",
        file_size=upload_file["file_size"],
        file_hash=upload_file["file_hash"],
    )
    service._upload_tasks.refresh_upload_task_counts(task_id)
    service._upload_tasks.update_upload_task_status(task_id, "completed")


def _delete_synthetic_upload_task(*, service: Any, task_id: str) -> None:
    upload_tasks = service._upload_tasks
    with upload_tasks._get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM upload_task_callbacks WHERE task_id = %s", (task_id,))
            cursor.execute("DELETE FROM upload_task_files WHERE task_id = %s", (task_id,))
            cursor.execute("DELETE FROM upload_tasks WHERE task_id = %s", (task_id,))


async def _run(args: argparse.Namespace) -> int:
    runtime = _load_runtime()
    service = _build_lightweight_service(runtime)
    settings = service._settings
    markdown_path = args.markdown_file.expanduser().resolve()
    if not markdown_path.is_file():
        raise FileNotFoundError(f"Markdown 文件不存在: {markdown_path}")

    brand_name = _resolve_brand_name(args=args, runtime=runtime, markdown_path=markdown_path)
    brand = service._brands.get_brand_by_name(brand_name)
    if not isinstance(brand, dict) or brand.get("id") is None:
        raise ValueError(f"品牌不存在 brand_name={brand_name}")

    markdown_text = markdown_path.read_text(encoding="utf-8-sig")
    source_name = markdown_path.name
    source_task_id = _build_source_task_id(args=args, brand_name=brand_name)
    synthetic_task_id = f"{source_task_id}:callback"

    ingestion_service = runtime["BrandAiKnowledgeIngestionService"](
        runtime["BrandAiKnowledgeIngestionDependencies"](
            settings=service._settings,
            brands=service._brands,
            parser=None,
            embeddings=None,
            store=None,
            oss_client=service.oss_client,
            brand_full_knowledge=service._brand_full_knowledge,
            brand_knowledge_facts=getattr(service, "_brand_knowledge_facts", None),
            brand_knowledge_ingestion_jobs=getattr(service, "_brand_knowledge_ingestion_jobs", None),
            brand_knowledge=getattr(service, "_brand_knowledge", None),
            brand_products=getattr(service, "_brand_products", None),
        )
    )

    if args.write:
        await ingestion_service._backfill_brand_knowledge_json_from_full_markdown(
            brand=brand,
            brand_name=brand_name,
            markdown_text=markdown_text,
            source_name=source_name,
            source_task_id=source_task_id,
        )
        brand = service._brands.get_brand_by_name(brand_name) or brand
        knowledge_snapshot = service._load_brand_knowledge_snapshot(brand=brand)
    else:
        knowledge_snapshot = await _build_preview_snapshot(
            service=service,
            ingestion_service=ingestion_service,
            runtime=runtime,
            brand=brand,
            brand_name=brand_name,
            markdown_text=markdown_text,
            source_name=source_name,
        )

    knowledge_mete_override = {
        "version": str(args.knowledge_version or "").strip(),
        "oss_url_md": str(args.knowledge_oss_url_md or "").strip(),
        "oss_url_pdf": str(args.knowledge_oss_url_pdf or "").strip(),
    }
    if not any(knowledge_mete_override.values()):
        knowledge_mete_override = None
    brand_code = str(brand.get("brand_code") or "").strip()
    if brand_code and knowledge_mete_override is not None:
        service._knowledge_mete_override_by_brand_code[brand_code] = knowledge_mete_override
    if not args.write and brand_code:
        service._preview_snapshots_by_brand_code[brand_code] = knowledge_snapshot

    upload_file = _build_upload_file_record(
        markdown_path=markdown_path,
        source_name=source_name,
        markdown_text=markdown_text,
    )
    _create_synthetic_upload_task(
        service=service,
        task_id=synthetic_task_id,
        brand=brand,
        brand_name=brand_name,
        upload_file=upload_file,
    )

    callback_payload: dict[str, Any] | None = None
    callback_url = _resolve_callback_url(args=args, settings=settings)
    callback_result: dict[str, Any] | None = None
    callback_row: dict[str, Any] | None = None
    try:
        if callback_url:
            setattr(settings, "brand_completion_callback_url", callback_url)
            setattr(settings, "brand_completion_callback_timeout_seconds", _resolve_callback_timeout(args=args, settings=settings))
            await runtime["maybe_finalize_task_callback"](service, synthetic_task_id)
            callback_row = service._upload_tasks.get_upload_task_callback(
                task_id=synthetic_task_id,
                callback_type="brand_knowledge_completed",
            )
            callback_payload = (
                json.loads(callback_row["request_payload_json"])
                if isinstance((callback_row or {}).get("request_payload_json"), str) and str(callback_row.get("request_payload_json") or "").strip()
                else (callback_row or {}).get("request_payload_json")
            )
            callback_result = {
                "callback_url": callback_url,
                "status_code": (callback_row or {}).get("last_response_code"),
                "response_text": (callback_row or {}).get("last_response_body"),
                "status": (callback_row or {}).get("status"),
            }
        elif not args.skip_callback_payload:
            callback_payload = await runtime["_build_callback_payload_with_knowledge"](service, synthetic_task_id)
    finally:
        _delete_synthetic_upload_task(service=service, task_id=synthetic_task_id)

    result = {
        "mode": "write" if args.write else "dry_run",
        "brand_name": brand_name,
        "source_name": source_name,
        "source_task_id": source_task_id,
        "synthetic_task_id": synthetic_task_id,
        "knowledge_snapshot": knowledge_snapshot,
        "callback_payload": callback_payload,
        "callback_row": callback_row,
        "callback_result": callback_result,
    }

    if args.output_snapshot_json is not None:
        _write_json_file(args.output_snapshot_json.expanduser().resolve(), knowledge_snapshot)
    if args.output_callback_json is not None and callback_payload is not None:
        _write_json_file(args.output_callback_json.expanduser().resolve(), callback_payload)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    args = _build_parser().parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
