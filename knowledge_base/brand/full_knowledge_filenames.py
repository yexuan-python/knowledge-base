from __future__ import annotations

from datetime import datetime

from knowledge_base.shared.utils.oss_keys import apply_oss_test_prefix, sanitize_oss_segment


def build_brand_full_knowledge_filename(*, brand_name: str, version_no: int, now: datetime | None = None) -> str:
    resolved_now = now or datetime.now()
    date_text = resolved_now.strftime("%Y%m%d")
    return f"【{brand_name}】品牌AI知识库_V{version_no}_{date_text}.md"


def build_brand_full_knowledge_oss_key(*, brand_name: str, file_name: str) -> str:
    category_part = sanitize_oss_segment(brand_name, default="uncategorized")
    return apply_oss_test_prefix(f"{category_part}/ai_knowledge/{file_name}")


def build_brand_full_knowledge_pdf_filename(*, markdown_file_name: str) -> str:
    normalized_file_name = str(markdown_file_name or "").strip()
    if normalized_file_name.lower().endswith(".md"):
        return f"{normalized_file_name[:-3]}.pdf"
    return f"{normalized_file_name}.pdf"
