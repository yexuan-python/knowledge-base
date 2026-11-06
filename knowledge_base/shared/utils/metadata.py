from __future__ import annotations

import json
import logging
from typing import Any
from uuid import uuid4


logger = logging.getLogger(__name__)


def normalize_upload_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    prepared = dict(metadata)

    raw_brand_name = prepared.get("brand_name")
    if isinstance(raw_brand_name, str):
        brand_name = raw_brand_name.strip()
        if brand_name:
            prepared["brand_name"] = brand_name
        else:
            prepared.pop("brand_name", None)

    raw_category = prepared.get("category")
    if isinstance(raw_category, str):
        category = raw_category.strip()
        if category:
            prepared["category"] = category
        else:
            prepared.pop("category", None)

    raw_subcategory = prepared.get("subcategory")
    if isinstance(raw_subcategory, str):
        subcategory = raw_subcategory.strip()
        if subcategory:
            prepared["subcategory"] = subcategory
        else:
            prepared.pop("subcategory", None)

    brand_name = prepared.get("brand_name")
    category = prepared.get("category")
    if isinstance(brand_name, str) and brand_name and not category:
        prepared["category"] = brand_name
    elif isinstance(category, str) and category and not brand_name:
        prepared["brand_name"] = category

    return prepared


def build_registry_reservation(*, filename: str, file_size: int | None, file_hash: str) -> dict[str, Any]:
    return {
        "reservation_id": str(uuid4()),
        "original_filename": filename,
        "file_size": file_size,
        "file_hash": file_hash,
    }


def resolve_registry_category(category: str | None) -> str:
    candidate = (category or "").strip()
    return candidate or "uncategorized"


def parse_metadata_json(raw_metadata: Any) -> dict[str, Any]:
    if isinstance(raw_metadata, dict):
        return raw_metadata
    if isinstance(raw_metadata, str) and raw_metadata:
        try:
            parsed = json.loads(raw_metadata)
        except json.JSONDecodeError:
            logger.warning("Invalid metadata_json encountered")
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}
