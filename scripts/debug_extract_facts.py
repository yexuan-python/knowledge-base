#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read a local text/markdown file, call extract_facts_from_text, "
            "and print the raw JSON plus flattened facts for manual verification."
        )
    )
    parser.add_argument("file", help="Path to a local text or markdown file.")
    parser.add_argument(
        "--category",
        default="",
        help="Optional brand/category hint passed to extract_facts_from_text.",
    )
    parser.add_argument(
        "--subcategory",
        default="",
        help="Optional subcategory hint passed to extract_facts_from_text.",
    )
    parser.add_argument(
        "--source-name",
        default="",
        help="Optional source_name override. Defaults to the file name.",
    )
    parser.add_argument(
        "--encoding",
        default="utf-8-sig",
        help="File encoding used when reading the source file. Default: utf-8-sig.",
    )
    parser.add_argument(
        "--raw-only",
        action="store_true",
        help="Only print the raw response returned by extract_facts_from_text.",
    )
    parser.add_argument(
        "--facts-only",
        action="store_true",
        help="Only print the flattened fact list, one fact per line.",
    )
    return parser


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _flatten_facts(payload: Any) -> tuple[list[str], dict[str, int]]:
    fact_texts: list[str] = []
    group_sizes: dict[str, int] = {}
    for item in payload if isinstance(payload, list) else []:
        if not isinstance(item, dict):
            continue
        for key, value in item.items():
            group_name = _normalize_text(key) or "(empty-key)"
            if isinstance(value, list):
                values = [_normalize_text(entry) for entry in value if _normalize_text(entry)]
            else:
                normalized = _normalize_text(value)
                values = [normalized] if normalized else []
            if not values:
                continue
            fact_texts.extend(values)
            group_sizes[group_name] = group_sizes.get(group_name, 0) + len(values)
    return fact_texts, group_sizes


async def _run(args: argparse.Namespace) -> int:
    from knowledge_base.document.ai.facts import extract_facts_from_text
    from knowledge_base.infrastructure import get_settings, setup_logging

    path = Path(str(args.file).strip()).expanduser().resolve()
    if not path.is_file():
        raise SystemExit(f"File not found: {path}")

    if args.raw_only and args.facts_only:
        raise SystemExit("--raw-only and --facts-only cannot be used together")

    text = path.read_text(encoding=args.encoding)
    if not text.strip():
        raise SystemExit(f"Source file is empty: {path}")

    settings = get_settings()
    setup_logging(
        level=settings.log_level,
        log_file=str(Path(settings.log_dir) / "debug_extract_facts.log"),
    )

    raw_result = await extract_facts_from_text(
        text,
        category=_normalize_text(args.category) or None,
        subcategory=_normalize_text(args.subcategory) or None,
        source_name=_normalize_text(args.source_name) or path.name,
        settings=settings,
    )

    if args.raw_only:
        print(raw_result)
        return 0

    try:
        payload = json.loads(raw_result)
    except json.JSONDecodeError as exc:
        print("===== raw response =====")
        print(raw_result)
        raise SystemExit(f"LLM response is not valid JSON: {exc}") from exc

    fact_texts, group_sizes = _flatten_facts(payload)

    if args.facts_only:
        for index, fact_text in enumerate(fact_texts, start=1):
            print(f"{index}. {fact_text}")
        return 0

    print("===== source =====")
    print(
        json.dumps(
            {
                "file": str(path),
                "category": _normalize_text(args.category) or None,
                "subcategory": _normalize_text(args.subcategory) or None,
                "source_name": _normalize_text(args.source_name) or path.name,
                "char_count": len(text),
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    print("\n===== raw json =====")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    print("\n===== summary =====")
    print(
        json.dumps(
            {
                "group_count": len(group_sizes),
                "fact_count": len(fact_texts),
                "groups": group_sizes,
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    print("\n===== flattened facts =====")
    for index, fact_text in enumerate(fact_texts, start=1):
        print(f"{index}. {fact_text}")

    return 0


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
