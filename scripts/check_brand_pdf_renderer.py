from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="检查品牌知识库 Markdown -> HTML -> PDF 的 Playwright 渲染链路是否可用。"
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="可选：把渲染出的测试 PDF 输出到指定路径，便于人工确认。",
    )
    return parser


async def _run(output_path: Path | None) -> int:
    from knowledge_base.brand.full_markdown import (
        _collect_pdf_renderer_diagnostics,
        render_brand_full_knowledge_pdf_bytes,
    )
    from knowledge_base.infrastructure.settings import get_settings

    diagnostics = _collect_pdf_renderer_diagnostics()
    print("PDF renderer diagnostics:")
    print(json.dumps(diagnostics, ensure_ascii=False, indent=2))

    sample_markdown = """# 品牌知识库 PDF 自检

## 基本信息

- 品牌名称：示例品牌
- 官方网站：[https://example.com](https://example.com)

## 表格

| 字段 | 内容 |
| --- | --- |
| 版本 | V1 |
| 年份 | 2026 |
"""

    try:
        pdf_bytes = await render_brand_full_knowledge_pdf_bytes(
            sample_markdown,
            title="品牌知识库 PDF 自检",
            settings=get_settings(),
        )
    except Exception as exc:  # noqa: BLE001
        print("PDF render check failed:")
        print(str(exc))
        return 1

    print(f"PDF render check passed, bytes={len(pdf_bytes)}")
    print(f"PDF header={pdf_bytes[:8]!r}")

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(pdf_bytes)
        print(f"PDF written to {output_path}")

    return 0


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    return asyncio.run(_run(args.output))


if __name__ == "__main__":
    raise SystemExit(main())
