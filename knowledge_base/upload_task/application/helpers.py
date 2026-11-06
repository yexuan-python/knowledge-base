from __future__ import annotations

import hashlib
import json
import mimetypes
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from knowledge_base.brand.ai_knowledge_filename import parse_ai_knowledge_filename
from knowledge_base.shared.utils import normalize_http_url_sequence


def is_duplicate_upload_error(exc: Exception) -> bool:
    message = str(exc)
    return "发现相同文件已存在" in message or "当前批次存在重复文件" in message


async def stage_upload_file(
    upload: UploadFile,
    staged_path: Path,
    *,
    chunk_size: int = 1024 * 1024,
) -> tuple[int, str]:
    hasher = hashlib.sha256()
    total_size = 0

    await upload.seek(0)
    with staged_path.open("wb") as staged_file:
        while True:
            chunk = await upload.read(chunk_size)
            if not chunk:
                break
            staged_file.write(chunk)
            hasher.update(chunk)
            total_size += len(chunk)

    await upload.seek(0)
    return total_size, hasher.hexdigest()


def normalize_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    normalized = str(value).strip()
    if not normalized:
        return None
    try:
        return int(normalized)
    except ValueError:
        return None


def normalize_websites(value: Any) -> list[str]:
    return normalize_http_url_sequence(value)


def serialize_brand_competitors(value: Any) -> list[dict[str, str | None]]:
    if not isinstance(value, list):
        return []
    competitors: list[dict[str, str | None]] = []
    for item in value:
        name = str(getattr(item, "name", "") or "").strip()
        if not name:
            continue
        website = str(getattr(item, "website", "") or "").strip() or None
        competitors.append({"name": name, "website": website})
    return competitors


def resolve_metadata_brand_name(metadata: dict[str, Any]) -> str | None:
    return str(metadata.get("brand_name") or metadata.get("category") or "").strip() or None


def compute_sha256_for_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            if not chunk:
                continue
            digest.update(chunk)
    return digest.hexdigest()


def validate_documents_upload_metadata(metadata: dict[str, Any]) -> None:
    brand_code = str(metadata.get("brand_code") or "").strip()
    brand_name = str(metadata.get("brand_name") or "").strip()
    category = str(metadata.get("category") or "").strip()
    if not brand_code or not brand_name or not category:
        raise ValueError(
            "/api/v1/documents/upload 仅支持品牌附件和正式品牌 AI 知识库文件；metadata 必须包含 category、brand_code、brand_name"
        )
    resolved_brand_name = resolve_metadata_brand_name(metadata) or ""
    if resolved_brand_name != category:
        raise ValueError("metadata.category 必须与 brand_name 一致")


def resolve_brand_ai_knowledge_job_id(*, task_id: str, file_id: int) -> str:
    return f"brand-ai-kb:{task_id}:{file_id}"[:128]


def serialize_websites(value: Any) -> str | None:
    websites = normalize_websites(value)
    if not websites:
        return None
    return json.dumps(websites, ensure_ascii=False)


def resolve_file_role(filename: str, metadata: dict[str, Any]) -> str:
    if bool(metadata.get("force_attachment")):
        return "attachment"
    parsed_filename = parse_ai_knowledge_filename(filename)
    if parsed_filename is not None and parsed_filename.normalized_extension == "md":
        return "brand_ai_knowledge"
    return "attachment"


def detect_content_type(*, filename: str, content_type: str | None) -> str:
    normalized = str(content_type or "").strip()
    if normalized:
        return normalized
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"
