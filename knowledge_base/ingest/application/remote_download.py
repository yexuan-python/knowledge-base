from __future__ import annotations

import asyncio
import logging
import random
import tempfile
from pathlib import Path

import httpx


logger = logging.getLogger(__name__)

REMOTE_DOWNLOAD_MAX_RETRIES = 3
REMOTE_DOWNLOAD_RETRY_DELAY_SECONDS = 2
REMOTE_DOWNLOAD_RETRYABLE_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.TimeoutException,
    httpx.RemoteProtocolError,
)


async def download_remote_content_to_temp_file(
    *,
    url: str,
    name: str,
    log_context: str,
) -> tuple[Path, str, int]:
    temp_path: Path | None = None
    content_type = ""
    downloaded_size = 0
    suffix = Path(name).suffix or ".tmp"

    for attempt in range(1, REMOTE_DOWNLOAD_MAX_RETRIES + 1):
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                temp_path = Path(tmp.name)
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "")
                    downloaded_size = 0
                    with temp_path.open("wb") as output_file:
                        async for chunk in response.aiter_bytes():
                            if not chunk:
                                continue
                            output_file.write(chunk)
                            downloaded_size += len(chunk)
            if attempt > 1:
                logger.info(
                    "Remote download to temp file succeeded after retry context=%s name=%s attempt=%s url=%s",
                    log_context,
                    name,
                    attempt,
                    url,
                )
            return temp_path, content_type, downloaded_size
        except REMOTE_DOWNLOAD_RETRYABLE_EXCEPTIONS as exc:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
                temp_path = None
            logger.warning(
                "Remote temp-file download failed with retryable error context=%s name=%s attempt=%s/%s url=%s error_type=%s error=%s",
                log_context,
                name,
                attempt,
                REMOTE_DOWNLOAD_MAX_RETRIES,
                url,
                type(exc).__name__,
                exc,
            )
            if attempt >= REMOTE_DOWNLOAD_MAX_RETRIES:
                raise
            delay = REMOTE_DOWNLOAD_RETRY_DELAY_SECONDS * (2 ** (attempt - 1)) + random.uniform(0, 1)
            await asyncio.sleep(delay)
        except Exception:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            raise

    raise ValueError(f"Failed to download remote file to temp path: {name}")


async def download_remote_content_to_path(
    *,
    url: str,
    name: str,
    log_context: str,
    destination: Path,
) -> tuple[str, int]:
    content_type = ""
    downloaded_size = 0

    for attempt in range(1, REMOTE_DOWNLOAD_MAX_RETRIES + 1):
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "")
                    downloaded_size = 0
                    with destination.open("wb") as output_file:
                        async for chunk in response.aiter_bytes():
                            if not chunk:
                                continue
                            output_file.write(chunk)
                            downloaded_size += len(chunk)
            if attempt > 1:
                logger.info(
                    "Remote download to destination succeeded after retry context=%s name=%s attempt=%s url=%s destination=%s",
                    log_context,
                    name,
                    attempt,
                    url,
                    destination,
                )
            return content_type, downloaded_size
        except REMOTE_DOWNLOAD_RETRYABLE_EXCEPTIONS as exc:
            destination.unlink(missing_ok=True)
            logger.warning(
                "Remote destination download failed with retryable error context=%s name=%s attempt=%s/%s url=%s destination=%s error_type=%s error=%s",
                log_context,
                name,
                attempt,
                REMOTE_DOWNLOAD_MAX_RETRIES,
                url,
                destination,
                type(exc).__name__,
                exc,
            )
            if attempt >= REMOTE_DOWNLOAD_MAX_RETRIES:
                raise
            delay = REMOTE_DOWNLOAD_RETRY_DELAY_SECONDS * (2 ** (attempt - 1)) + random.uniform(0, 1)
            await asyncio.sleep(delay)
        except Exception:
            destination.unlink(missing_ok=True)
            raise

    raise ValueError(f"Failed to download remote file to destination: {name}")
