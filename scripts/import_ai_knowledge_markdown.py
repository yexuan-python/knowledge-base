#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


AI_KNOWLEDGE_FILENAME_RE = re.compile(
    r"^[【「](?P<brand_name>.+?)[】」]品牌AI知识库_V(?P<version_no>\d+)_(?P<date>\d{8})\.md$"
)


@dataclass(frozen=True)
class ImportItem:
    path: Path
    brand_name: str
    version_no: int
    date_text: str
    file_name: str
    pdf_file_name: str
    content_markdown: str
    oss_key: str
    pdf_oss_key: str


class ImportRuntimeError(RuntimeError):
    pass


class MinimalStores:
    def __init__(self, *, brands: Any, brand_full_knowledge: Any) -> None:
        self.brands = brands
        self.brand_full_knowledge = brand_full_knowledge


def load_runtime() -> tuple[Any, Any, Any, Any, Any]:
    try:
        from knowledge_base.brand.full_markdown import render_brand_full_knowledge_pdf_bytes
        from knowledge_base.infrastructure import OSSClient, get_settings, setup_logging
        from knowledge_base.shared.utils.oss_keys import apply_oss_test_prefix
        from knowledge_base.stores import BrandFullKnowledgeStore, BrandStore
    except ModuleNotFoundError as exc:
        missing_name = getattr(exc, "name", "") or str(exc)
        raise ImportRuntimeError(
            "项目依赖未安装，无法执行导入脚本。"
            "请在项目环境中运行，例如 `uv run python scripts/import_ai_knowledge_markdown.py ...`，"
            f"当前缺少模块: {missing_name}"
        ) from exc

    settings = get_settings()
    setup_logging(level=settings.log_level, log_file=str(Path(settings.log_dir) / "app.log"))
    stores = MinimalStores(
        brands=BrandStore(settings),
        brand_full_knowledge=BrandFullKnowledgeStore(settings),
    )
    stores.brands.ensure_schema_ready()
    stores.brand_full_knowledge.ensure_schema_ready()
    return settings, stores, OSSClient, render_brand_full_knowledge_pdf_bytes, apply_oss_test_prefix


def sanitize_oss_segment(value: str | None, *, default: str) -> str:
    candidate = (value or "").strip()
    candidate = candidate.strip("/\\")
    candidate = candidate.replace("/", "_").replace("\\", "_")
    return candidate or default


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Import 【品牌名】品牌AI知识库_Vx_YYYYMMDD.md files as full AI knowledge baselines. "
            "The script uploads Markdown to OSS ai_knowledge/ and upserts brand_full_knowledge_files."
        )
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path, help="Single Markdown file to import.")
    source.add_argument("--dir", type=Path, help="Directory containing Markdown files to import.")
    parser.add_argument("--recursive", action="store_true", help="Scan --dir recursively.")
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Actually upload to OSS and write MySQL. Without this flag the script only previews actions.",
    )
    parser.add_argument(
        "--skip-oss",
        action="store_true",
        help="Do not upload Markdown/PDF to OSS; only write DB records. Requires --commit for DB writes.",
    )
    parser.add_argument(
        "--skip-pdf",
        action="store_true",
        help="Do not render or upload PDF. By default --commit uploads both Markdown and PDF.",
    )
    parser.add_argument(
        "--create-brand",
        action="store_true",
        help="Create a minimal brands row when brand_name does not exist.",
    )
    parser.add_argument(
        "--source-task-prefix",
        default="manual_ai_knowledge_import",
        help="source_task_id prefix for imported rows.",
    )
    parser.add_argument(
        "--encoding",
        default="utf-8",
        help="Markdown file encoding.",
    )
    return parser.parse_args()


def iter_markdown_files(args: argparse.Namespace) -> list[Path]:
    if args.file is not None:
        return [Path(str(args.file).strip()).expanduser().resolve()]

    root = Path(str(args.dir).strip()).expanduser().resolve()
    pattern = "**/*.md" if args.recursive else "*.md"
    return sorted(path.resolve() for path in root.glob(pattern) if path.is_file())


def build_ai_knowledge_oss_key(*, brand_name: str, file_name: str, apply_prefix: Any | None = None) -> str:
    category_part = sanitize_oss_segment(brand_name, default="uncategorized")
    object_key = f"{category_part}/ai_knowledge/{file_name}"
    if callable(apply_prefix):
        return str(apply_prefix(object_key))
    return object_key


def build_pdf_file_name(markdown_file_name: str) -> str:
    if markdown_file_name.lower().endswith(".md"):
        return f"{markdown_file_name[:-3]}.pdf"
    return f"{markdown_file_name}.pdf"


def parse_import_item(path: Path, *, encoding: str, apply_prefix: Any | None = None) -> ImportItem:
    file_name = path.name.strip()
    match = AI_KNOWLEDGE_FILENAME_RE.match(file_name)
    if not match:
        raise ValueError(
            f"文件名不符合格式: {path.name}，期望："
            "【品牌名】品牌AI知识库_Vx_YYYYMMDD.md 或 「品牌名」品牌AI知识库_Vx_YYYYMMDD.md"
        )

    brand_name = match.group("brand_name").strip()
    version_no = int(match.group("version_no"))
    date_text = match.group("date")
    content_markdown = path.read_text(encoding=encoding).strip()
    if not content_markdown:
        raise ValueError(f"Markdown 内容为空: {path}")

    return ImportItem(
        path=path,
        brand_name=brand_name,
        version_no=version_no,
        date_text=date_text,
        file_name=file_name,
        pdf_file_name=build_pdf_file_name(file_name),
        content_markdown=content_markdown,
        oss_key=build_ai_knowledge_oss_key(brand_name=brand_name, file_name=file_name, apply_prefix=apply_prefix),
        pdf_oss_key=build_ai_knowledge_oss_key(
            brand_name=brand_name,
            file_name=build_pdf_file_name(file_name),
            apply_prefix=apply_prefix,
        ),
    )


def get_or_create_brand_id(stores: Any, *, brand_name: str, create_brand: bool, commit: bool) -> int | None:
    brand = stores.brands.get_brand_by_name(brand_name)
    if brand and brand.get("id") is not None:
        return int(brand["id"])

    if not create_brand:
        return None
    if not commit:
        return 0
    return stores.brands.upsert_brand(brand_name=brand_name)


def upsert_brand_full_knowledge(
    stores: Any,
    *,
    brand_id: int,
    item: ImportItem,
    oss_url: str | None,
    pdf_oss_url: str | None,
    skip_pdf: bool,
    source_task_prefix: str,
) -> None:
    source_task_id = f"{source_task_prefix}:v{item.version_no}:{item.date_text}:{item.brand_name}"
    conflicts_json = json.dumps([], ensure_ascii=False)
    with stores.brand_full_knowledge._get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO brand_full_knowledge_files (
                    brand_id,
                    brand_name,
                    version_no,
                    file_name,
                    pdf_file_name,
                    oss_key,
                    oss_url,
                    pdf_oss_key,
                    pdf_oss_url,
                    content_markdown,
                    conflict_count,
                    conflicts_json,
                    source_task_id
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, %s, %s
                )
                ON DUPLICATE KEY UPDATE
                    brand_name = VALUES(brand_name),
                    file_name = VALUES(file_name),
                    pdf_file_name = VALUES(pdf_file_name),
                    oss_key = VALUES(oss_key),
                    oss_url = VALUES(oss_url),
                    pdf_oss_key = VALUES(pdf_oss_key),
                    pdf_oss_url = VALUES(pdf_oss_url),
                    content_markdown = VALUES(content_markdown),
                    conflict_count = VALUES(conflict_count),
                    conflicts_json = VALUES(conflicts_json),
                    source_task_id = VALUES(source_task_id),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    brand_id,
                    item.brand_name,
                    item.version_no,
                    item.file_name,
                    None if skip_pdf else item.pdf_file_name,
                    item.oss_key,
                    oss_url,
                    None if skip_pdf else item.pdf_oss_key,
                    pdf_oss_url,
                    item.content_markdown,
                    conflicts_json,
                    source_task_id,
                ),
            )


def format_action(
    item: ImportItem,
    *,
    brand_id: int | None,
    oss_url: str | None,
    pdf_oss_url: str | None,
    skip_pdf: bool,
    status: str,
) -> str:
    content_chars = len(item.content_markdown)
    brand_id_text = "missing" if brand_id is None else str(brand_id)
    pdf_lines = ""
    if not skip_pdf:
        pdf_lines = (
            f"\n  pdf_file_name: {item.pdf_file_name}"
            f"\n  pdf_oss_key: {item.pdf_oss_key}"
            f"\n  pdf_oss_url: {pdf_oss_url or ''}"
        )
    return (
        f"[{status}] {item.file_name}\n"
        f"  brand_name: {item.brand_name}\n"
        f"  brand_id: {brand_id_text}\n"
        f"  version_no: {item.version_no}\n"
        f"  oss_key: {item.oss_key}\n"
        f"  oss_url: {oss_url or ''}\n"
        f"{pdf_lines}\n"
        f"  content_chars: {content_chars}"
    )


def main() -> int:
    args = parse_args()

    files = iter_markdown_files(args)
    if not files:
        print("没有找到 Markdown 文件。")
        return 1

    try:
        settings, stores, oss_client_cls, render_pdf, apply_oss_prefix = load_runtime()
    except ImportRuntimeError as exc:
        print(str(exc))
        return 1

    items: list[ImportItem] = []
    errors: list[str] = []
    for path in files:
        try:
            items.append(parse_import_item(path, encoding=args.encoding, apply_prefix=apply_oss_prefix))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{path}: {exc}")

    if errors:
        print("以下文件无法导入：")
        for error in errors:
            print(f"- {error}")
        return 1

    oss_client = oss_client_cls(settings)
    if args.commit and not args.skip_oss and not oss_client.enabled:
        print("OSS 未启用，无法上传。请检查 OSS_* 环境变量，或使用 --skip-oss 仅写 DB。")
        return 1

    imported = 0
    skipped = 0
    for item in items:
        brand_id = get_or_create_brand_id(
            stores,
            brand_name=item.brand_name,
            create_brand=args.create_brand,
            commit=args.commit,
        )
        if brand_id is None:
            skipped += 1
            print(
                format_action(
                    item,
                    brand_id=None,
                    oss_url=None,
                    pdf_oss_url=None,
                    skip_pdf=args.skip_pdf,
                    status="SKIP brand_not_found",
                )
            )
            continue

        oss_url = None
        pdf_oss_url = None
        if args.commit and not args.skip_oss:
            uploaded_key = oss_client.upload_bytes(
                item.content_markdown.encode(args.encoding),
                item.oss_key,
                "text/markdown; charset=utf-8",
            )
            if not uploaded_key:
                raise RuntimeError(f"OSS 上传失败: {item.oss_key}")
            oss_url = oss_client.build_object_url(uploaded_key)
            if not args.skip_pdf:
                pdf_bytes = asyncio.run(
                    render_pdf(
                        item.content_markdown,
                        title=item.file_name,
                        settings=settings,
                    )
                )
                uploaded_pdf_key = oss_client.upload_bytes(
                    pdf_bytes,
                    item.pdf_oss_key,
                    "application/pdf",
                )
                if not uploaded_pdf_key:
                    raise RuntimeError(f"OSS PDF 上传失败: {item.pdf_oss_key}")
                pdf_oss_url = oss_client.build_object_url(uploaded_pdf_key)
        elif not args.skip_oss and oss_client.enabled:
            oss_url = oss_client.build_object_url(item.oss_key)
            if not args.skip_pdf:
                pdf_oss_url = oss_client.build_object_url(item.pdf_oss_key)

        print(
            format_action(
                item,
                brand_id=brand_id,
                oss_url=oss_url,
                pdf_oss_url=pdf_oss_url,
                skip_pdf=args.skip_pdf,
                status="IMPORT" if args.commit else "DRY-RUN",
            )
        )

        if args.commit:
            upsert_brand_full_knowledge(
                stores,
                brand_id=brand_id,
                item=item,
                oss_url=oss_url,
                pdf_oss_url=pdf_oss_url,
                skip_pdf=args.skip_pdf,
                source_task_prefix=args.source_task_prefix,
            )
            imported += 1

    mode = "commit" if args.commit else "dry-run"
    print(f"\n完成：mode={mode}, files={len(items)}, imported={imported}, skipped={skipped}")
    if not args.commit:
        print("当前只是预览。确认无误后加 --commit 正式上传 OSS 并写入 MySQL。")
    return 0 if skipped == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
