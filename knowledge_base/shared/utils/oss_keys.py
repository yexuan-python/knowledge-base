from __future__ import annotations

import os
from pathlib import Path


def sanitize_oss_segment(value: str | None, *, default: str) -> str:
    candidate = (value or "").strip()
    candidate = candidate.strip("/\\")
    candidate = candidate.replace("/", "_").replace("\\", "_")
    return candidate or default


def apply_oss_test_prefix(object_key: str) -> str:
    prefix = os.getenv("OSS_OBJECT_KEY_PREFIX", "").strip().strip("/\\")
    if not prefix:
        return object_key
    return f"{prefix}/{object_key.lstrip('/\\')}"


_KNOWN_OSS_OBJECT_KEY_PREFIXES = frozenset({"dev", "local", "pre", "prod", "staging", "test"})


def object_key_matches_current_oss_prefix(object_key: str | None) -> bool:
    key = (object_key or "").strip().lstrip("/\\")
    if not key:
        return False

    prefix = os.getenv("OSS_OBJECT_KEY_PREFIX", "").strip().strip("/\\")
    if prefix:
        return key == prefix or key.startswith(f"{prefix}/")

    first_segment = key.split("/", 1)[0]
    return first_segment not in _KNOWN_OSS_OBJECT_KEY_PREFIXES


def versioned_original_filename(version: int, filename: str, document_id: str) -> str:
    suffix = Path(filename).suffix
    if suffix:
        return f"V{version}{suffix}"
    return f"V{version}-{document_id}"


def build_original_object_key(
    *,
    category: str | None,
    subcategory: str | None,
    filename: str,
    document_id: str,
    converted_version: int,
) -> str:
    category_part = sanitize_oss_segment(category, default="uncategorized")
    subcategory_part = sanitize_oss_segment(subcategory, default="")
    safe_name = sanitize_oss_segment(Path(filename).name, default=document_id)
    versioned_name = sanitize_oss_segment(
        versioned_original_filename(converted_version, filename, document_id),
        default=f"V{converted_version}-{document_id}",
    )
    path_parts = [category_part, "original"]
    if subcategory_part:
        path_parts.append(subcategory_part)
    path_parts.extend([safe_name, versioned_name])
    return apply_oss_test_prefix("/".join(path_parts))


def build_fulltext_object_key(
    *,
    category: str | None,
    subcategory: str | None,
    filename: str,
    document_id: str,
    converted_version: int,
) -> str:
    category_part = sanitize_oss_segment(category, default="uncategorized")
    subcategory_part = sanitize_oss_segment(subcategory, default="")
    safe_name = sanitize_oss_segment(Path(filename).name, default=document_id)
    path_parts = [category_part, "converted"]
    if subcategory_part:
        path_parts.append(subcategory_part)
    path_parts.extend([safe_name, f"V{converted_version}.md"])
    return apply_oss_test_prefix("/".join(path_parts))


def build_image_object_key(
    *,
    category: str | None,
    subcategory: str | None,
    filename: str,
    document_id: str,
    converted_version: int,
) -> str:
    return build_original_object_key(
        category=category,
        subcategory=subcategory,
        filename=filename,
        document_id=document_id,
        converted_version=converted_version,
    )


def legacy_fulltext_object_key(document_id: str) -> str:
    return f"fulltext/{document_id}.txt"


def build_brand_attachment_object_key(
    *,
    brand_code: str | None,
    filename: str,
    file_hash: str,
) -> str:
    brand_code_part = sanitize_oss_segment(brand_code, default="unknown-brand")
    safe_name = sanitize_oss_segment(Path(filename).name, default=file_hash[:16] or "file")
    suffix = Path(filename).suffix.lower()
    hash_prefix = sanitize_oss_segment(file_hash[:16], default="hash")
    object_name = f"{hash_prefix}{suffix}" if suffix else hash_prefix
    return apply_oss_test_prefix(f"{brand_code_part}/attachments/{safe_name}/{object_name}")


def build_brand_ai_knowledge_markdown_object_key(
    *,
    brand_name: str | None,
    filename: str,
) -> str:
    brand_name_part = sanitize_oss_segment(brand_name, default="unknown-brand")
    safe_name = sanitize_oss_segment(Path(filename).name, default="knowledge.md")
    return apply_oss_test_prefix(f"{brand_name_part}/ai_knowledge/{safe_name}")


def build_brand_ai_knowledge_pdf_object_key(
    *,
    brand_name: str | None,
    filename: str,
) -> str:
    brand_name_part = sanitize_oss_segment(brand_name, default="unknown-brand")
    safe_name = sanitize_oss_segment(Path(filename).name, default="knowledge.pdf")
    return apply_oss_test_prefix(f"{brand_name_part}/ai_knowledge/{safe_name}")
