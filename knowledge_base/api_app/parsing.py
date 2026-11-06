from __future__ import annotations

import json
import logging

from fastapi import HTTPException, UploadFile


logger = logging.getLogger(__name__)


def parse_metadata(metadata: str | None) -> dict[str, object]:
    if metadata is None:
        return {}
    try:
        value = json.loads(metadata)
    except json.JSONDecodeError as exc:
        logger.warning("Metadata parsing failed reason=invalid_json")
        raise HTTPException(status_code=400, detail="metadata must be a valid JSON object") from exc
    if not isinstance(value, dict):
        logger.warning("Metadata parsing failed reason=not_object actual_type=%s", type(value).__name__)
        raise HTTPException(status_code=400, detail="metadata must be a JSON object")
    return value


async def check_file_size_streaming(file: UploadFile, max_size: int) -> bool:
    """Stream a file upload to confirm it does not exceed the configured limit."""
    total = 0
    chunk_size = 8192
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_size:
            return False
    await file.seek(0)
    return True
