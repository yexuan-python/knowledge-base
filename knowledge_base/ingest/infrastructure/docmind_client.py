from __future__ import annotations

import logging
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from knowledge_base.infrastructure.settings import Settings


logger = logging.getLogger(__name__)


class DocMindError(RuntimeError):
    """Raised when DocMind parsing fails."""


@dataclass(frozen=True)
class DocMindParseResult:
    text: str
    markdown_text: str
    task_id: str


class DocMindClient:
    SUPPORTED_EXTENSIONS = {
        ".bmp",
        ".doc",
        ".docx",
        ".epub",
        ".gif",
        ".htm",
        ".html",
        ".jpeg",
        ".jpg",
        ".mobi",
        ".pdf",
        ".png",
        ".ppt",
        ".pptx",
        ".rtf",
        ".txt",
        ".webp",
        ".xls",
        ".xlsx",
    }

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def enabled(self) -> bool:
        return bool(
            self._settings.docmind_enabled
            and self._settings.docmind_access_key_id
            and self._settings.docmind_access_key_secret
        )

    def supports(self, suffix: str) -> bool:
        return suffix.lower() in self.SUPPORTED_EXTENSIONS

    def parse_file(self, path: Path, *, source_url: str | None = None) -> DocMindParseResult:
        if not self.enabled:
            raise DocMindError("DocMind fallback is not configured")
        if not self.supports(path.suffix):
            raise DocMindError(f"DocMind does not support file type: {path.suffix or '<none>'}")

        client, models, runtime_models = self._create_sdk_client()
        task_id = self._submit_job(
            path,
            client,
            models,
            runtime_models,
            source_url=source_url,
        )
        status_data = self._wait_for_completion(task_id, client, models)

        markdown_text = self._load_markdown_with_fallback(task_id, status_data, client, models)

        markdown_text = markdown_text.strip()
        if self._settings.docmind_strip_markdown_images and markdown_text:
            markdown_text = self._strip_markdown_images(markdown_text).strip()

        text = self._markdown_to_text(markdown_text) if markdown_text else ""
        if not text:
            raise DocMindError(f"DocMind returned no usable text for {path.name}")

        return DocMindParseResult(
            text=text,
            markdown_text=markdown_text,
            task_id=task_id,
        )

    def _create_sdk_client(self):
        try:
            from alibabacloud_docmind_api20220711.client import Client as DocMindSdkClient
            from alibabacloud_docmind_api20220711 import models as docmind_models
            from alibabacloud_tea_openapi import models as open_api_models
            from alibabacloud_tea_util import models as util_models
        except ModuleNotFoundError as exc:
            raise DocMindError(
                "DocMind SDK is not installed. Please install alibabacloud-docmind-api20220711, "
                "alibabacloud-tea-openapi and alibabacloud-tea-util."
            ) from exc

        config = open_api_models.Config(
            access_key_id=self._settings.docmind_access_key_id,
            access_key_secret=self._settings.docmind_access_key_secret,
            endpoint=self._settings.docmind_endpoint,
            type="access_key",
            region_id="cn-hangzhou",
        )
        client = DocMindSdkClient(config)
        return client, docmind_models, util_models

    def _submit_job(
        self,
        path: Path,
        client: Any,
        models: Any,
        runtime_models: Any,
        *,
        source_url: str | None = None,
    ) -> str:
        runtime = runtime_models.RuntimeOptions(
            connect_timeout=int(self._settings.docmind_download_timeout_seconds * 1000),
            read_timeout=int(self._settings.docmind_timeout_seconds * 1000),
        )
        file_size_bytes = self._get_file_size_bytes(path)
        normalized_source_url = self._normalize_source_url(source_url)
        url_submit_error: Exception | None = None
        submit_started_at = time.monotonic()
        logger.info(
            "DocMind submit started file=%s bytes=%s has_source_url=%s source_url=%s",
            path.name,
            file_size_bytes,
            bool(normalized_source_url),
            normalized_source_url or "",
        )
        if normalized_source_url:
            url_submit_started_at = time.monotonic()
            try:
                task_id = self._submit_job_from_url(
                    path,
                    client,
                    models,
                    runtime,
                    source_url=normalized_source_url,
                )
                logger.info(
                    "DocMind parse job submitted via url file=%s bytes=%s task_id=%s "
                    "source_url=%s elapsed=%.2fs total_elapsed=%.2fs",
                    path.name,
                    file_size_bytes,
                    task_id,
                    normalized_source_url,
                    time.monotonic() - url_submit_started_at,
                    time.monotonic() - submit_started_at,
                )
                return task_id
            except Exception as exc:
                url_submit_error = exc
                logger.warning(
                    "DocMind URL submit failed file=%s bytes=%s source_url=%s elapsed=%.2fs error=%s; "
                    "falling back to file upload",
                    path.name,
                    file_size_bytes,
                    normalized_source_url,
                    time.monotonic() - url_submit_started_at,
                    exc,
                )

        file_submit_started_at = time.monotonic()
        try:
            task_id = self._submit_job_from_file(
                path,
                client,
                models,
                runtime,
            )
        except Exception as exc:
            if url_submit_error is not None:
                raise DocMindError(
                    f"DocMind submit failed for {path.name}: "
                    f"url submit error={url_submit_error}; file upload fallback error={exc}"
                ) from exc
            raise

        if url_submit_error is not None:
            logger.info(
                "DocMind parse job submitted via file upload after url fallback file=%s bytes=%s task_id=%s "
                "upload_elapsed=%.2fs total_elapsed=%.2fs",
                path.name,
                file_size_bytes,
                task_id,
                time.monotonic() - file_submit_started_at,
                time.monotonic() - submit_started_at,
            )
        else:
            logger.info(
                "DocMind parse job submitted via file upload file=%s bytes=%s task_id=%s "
                "upload_elapsed=%.2fs total_elapsed=%.2fs",
                path.name,
                file_size_bytes,
                task_id,
                time.monotonic() - file_submit_started_at,
                time.monotonic() - submit_started_at,
            )
        return task_id

    @staticmethod
    def _normalize_source_url(source_url: str | None) -> str | None:
        normalized = str(source_url or "").strip()
        if not normalized:
            return None
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"}:
            return None
        if not parsed.netloc:
            return None
        return normalized

    @staticmethod
    def _get_file_size_bytes(path: Path) -> int | None:
        try:
            return path.stat().st_size
        except OSError:
            return None

    def _submit_job_from_url(
        self,
        path: Path,
        client: Any,
        models: Any,
        runtime: Any,
        *,
        source_url: str,
    ) -> str:
        request_cls = getattr(models, "SubmitDocParserJobRequest", None)
        if request_cls is None:
            raise DocMindError("DocMind SDK does not expose SubmitDocParserJobRequest for URL submit")
        submit_method = getattr(client, "submit_doc_parser_job_with_options", None)
        if submit_method is None:
            submit_method = getattr(client, "submit_doc_parser_job", None)
        if submit_method is None:
            raise DocMindError("DocMind SDK does not expose a URL submit method")

        request = request_cls(
            file_name=path.name,
            file_name_extension=path.suffix.lstrip("."),
            file_url=source_url,
            output_format=["markdown"],
            llm_enhancement=self._settings.docmind_llm_enhancement,
            enhancement_mode=self._settings.docmind_enhancement_mode,
        )
        response = submit_method(request, runtime)
        return self._extract_task_id_from_submit_response(response)

    def _submit_job_from_file(
        self,
        path: Path,
        client: Any,
        models: Any,
        runtime: Any,
    ) -> str:
        with path.open("rb") as file_obj:
            request = models.SubmitDocParserJobAdvanceRequest(
                file_name=path.name,
                file_name_extension=path.suffix.lstrip("."),
                file_url_object=file_obj,
                output_format=["markdown"],
                llm_enhancement=self._settings.docmind_llm_enhancement,
                enhancement_mode=self._settings.docmind_enhancement_mode,
            )
            response = client.submit_doc_parser_job_advance(request, runtime)
        return self._extract_task_id_from_submit_response(response)

    def _extract_task_id_from_submit_response(self, response: Any) -> str:
        body = self._as_dict(getattr(response, "body", response))
        data = self._pick(body, "data") or {}
        task_id = self._pick(data, "id")
        if not task_id:
            raise DocMindError(f"DocMind submit response missing task id: {body}")
        return str(task_id)

    def _wait_for_completion(self, task_id: str, client: Any, models: Any) -> dict[str, Any]:
        deadline = time.monotonic() + self._settings.docmind_timeout_seconds
        last_status = "unknown"

        while time.monotonic() < deadline:
            request = models.QueryDocParserStatusRequest(id=task_id)
            response = client.query_doc_parser_status(request)
            body = self._as_dict(getattr(response, "body", response))
            data = self._pick(body, "data") or {}
            status = str(self._pick(data, "status") or "").lower()
            last_status = status or last_status

            if status == "success":
                logger.info("DocMind parse job completed task_id=%s", task_id)
                return data
            if status in {"failed", "fail", "canceled", "cancelled"}:
                error_message = self._pick(data, "error_message", "message") or body
                raise DocMindError(f"DocMind parse job failed for task {task_id}: {error_message}")

            time.sleep(self._settings.docmind_poll_interval_seconds)

        raise DocMindError(
            f"DocMind parse job timed out after {self._settings.docmind_timeout_seconds}s "
            f"(task_id={task_id}, last_status={last_status})"
        )

    def _load_markdown_with_fallback(
        self,
        task_id: str,
        status_data: dict[str, Any],
        client: Any,
        models: Any,
    ) -> str:
        download_error: Exception | None = None

        try:
            download_started_at = time.monotonic()
            markdown_text = self._download_markdown_from_status(status_data)
        except Exception as exc:
            download_error = exc
            logger.warning(
                "DocMind markdown output download failed task_id=%s elapsed=%.2fs error=%s; "
                "falling back to result API",
                task_id,
                time.monotonic() - download_started_at,
                exc,
            )
            markdown_text = ""

        if markdown_text:
            logger.info(
                "DocMind markdown output download succeeded task_id=%s elapsed=%.2fs markdown_chars=%s",
                task_id,
                time.monotonic() - download_started_at,
                len(markdown_text),
            )
            return markdown_text

        try:
            result_started_at = time.monotonic()
            markdown_text = self._load_markdown_from_result(task_id, client, models)
        except Exception as exc:
            if download_error is not None:
                raise DocMindError(
                    "DocMind markdown retrieval failed for task "
                    f"{task_id}: output download error={download_error}; result api error={exc}"
                ) from exc
            raise

        logger.info(
            "DocMind result API markdown loaded task_id=%s elapsed=%.2fs markdown_chars=%s "
            "after_download_error=%s",
            task_id,
            time.monotonic() - result_started_at,
            len(markdown_text or ""),
            download_error is not None,
        )
        if not markdown_text and download_error is not None:
            logger.warning(
                "DocMind result API returned empty content after markdown download failure task_id=%s",
                task_id,
            )

        return markdown_text

    def _download_markdown_from_status(self, status_data: dict[str, Any]) -> str:
        output_items = self._pick(status_data, "output_format_result") or []
        for item in output_items:
            payload = self._as_dict(item)
            output_type = str(self._pick(payload, "output_type") or "").lower()
            output_url = self._pick(payload, "output_file_url")
            if output_type == "markdown" and output_url:
                return self._download_markdown_output(str(output_url))
        return ""

    def _load_markdown_from_result(self, task_id: str, client: Any, models: Any) -> str:
        parts: list[str] = []
        offset = 0
        step = 200

        while True:
            request = models.GetDocParserResultRequest(
                id=task_id,
                layout_num=offset,
                layout_step_size=step,
            )
            response = client.get_doc_parser_result(request)
            body = self._as_dict(getattr(response, "body", response))
            data = self._pick(body, "data") or {}
            layouts = self._pick(data, "layouts") or []
            if not layouts:
                break

            for layout in layouts:
                payload = self._as_dict(layout)
                markdown_content = self._pick(payload, "markdown_content")
                if markdown_content:
                    parts.append(str(markdown_content))
                    continue
                text = self._pick(payload, "text")
                if text:
                    parts.append(str(text))

            if len(layouts) < step:
                break
            offset += step

        return "\n\n".join(part.strip() for part in parts if str(part).strip())

    def _download_text(self, url: str) -> str:
        temp_path: Path | None = None
        response = requests.get(
            url,
            timeout=self._settings.docmind_download_timeout_seconds,
            stream=True,
        )
        try:
            response.raise_for_status()
            encoding = response.encoding or "utf-8"
            with tempfile.NamedTemporaryFile(delete=False, suffix=".md") as tmp:
                temp_path = Path(tmp.name)
            # This temp file only holds DocMind's downloaded markdown output.
            # The source attachment path used for URL/file-submit fallback is managed by the outer ingest flow.
            with temp_path.open("wb") as output_file:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    output_file.write(chunk)
            return temp_path.read_text(encoding=encoding)
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def _download_markdown_output(self, url: str) -> str:
        last_error: Exception | None = None
        for candidate in self._iter_output_urls(url):
            try:
                return self._download_text(candidate)
            except Exception as exc:
                last_error = exc
                logger.warning("DocMind markdown download attempt failed url=%s error=%s", candidate, exc)

        if last_error is not None:
            raise last_error
        return ""

    @staticmethod
    def _iter_output_urls(url: str) -> list[str]:
        candidates: list[str] = []
        if url.startswith("http://"):
            candidates.append("https://" + url[len("http://"):])
        candidates.append(url)
        deduped: list[str] = []
        for candidate in candidates:
            if candidate not in deduped:
                deduped.append(candidate)
        return deduped

    @staticmethod
    def _as_dict(value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        if hasattr(value, "to_map"):
            mapped = value.to_map()
            if isinstance(mapped, dict):
                return mapped
        if hasattr(value, "__dict__"):
            return {key: val for key, val in vars(value).items() if not key.startswith("_")}
        return {}

    @classmethod
    def _pick(cls, payload: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            candidates = {
                key,
                cls._snake_to_camel(key),
                cls._snake_to_pascal(key),
            }
            for candidate in candidates:
                if candidate in payload:
                    return payload[candidate]
        return None

    @staticmethod
    def _snake_to_camel(value: str) -> str:
        head, *tail = value.split("_")
        return head + "".join(part.capitalize() for part in tail)

    @staticmethod
    def _snake_to_pascal(value: str) -> str:
        return "".join(part.capitalize() for part in value.split("_"))

    @staticmethod
    def _markdown_to_text(markdown_text: str) -> str:
        text = markdown_text
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = text.replace("```markdown", "```")
        text = text.replace("```text", "```")
        text = text.replace("```", "")
        text = text.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
        text = text.replace("&nbsp;", " ")
        text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.MULTILINE)
        text = re.sub(r"^\s*[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def _strip_markdown_images(markdown_text: str) -> str:
        text = markdown_text
        text = re.sub(r"!\[[^\]]*]\([^)]*\)", "", text)
        text = re.sub(r"!\[[^\]]*]\[[^\]]*]", "", text)
        text = re.sub(r"<img\b[^>]*>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^\[[^\]]+]:\s*\S+\s*$", "", text, flags=re.MULTILINE)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text
