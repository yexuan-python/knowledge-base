from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from knowledge_base.infrastructure import get_settings
from knowledge_base.ingest.infrastructure import DocMindClient, DocMindError, DocMindParseResult


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a DocMind parse job independently from the main upload pipeline."
    )
    parser.add_argument(
        "file",
        nargs="?",
        help="Source document path. Required unless --task-id is provided.",
    )
    parser.add_argument(
        "--task-id",
        help="Existing DocMind task id. Use this to resume polling without re-uploading.",
    )
    parser.add_argument(
        "--submit-only",
        action="store_true",
        help="Only submit the file and print the task id.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=0,
        help="Overall wait timeout in seconds. Use 0 to wait indefinitely. Default: 0.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=None,
        help="Polling interval in seconds. Defaults to KB_DOCMIND_POLL_INTERVAL_SECONDS.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Directory to write output files into. Defaults to the source file directory or current directory.",
    )
    parser.add_argument(
        "--prefix",
        help="Output filename prefix. Defaults to the source filename stem or task id.",
    )
    parser.add_argument(
        "--print-markdown",
        action="store_true",
        help="Print extracted markdown to stdout after success.",
    )
    parser.add_argument(
        "--print-text",
        action="store_true",
        help="Print normalized plain text to stdout after success.",
    )
    parser.add_argument(
        "--status-only",
        action="store_true",
        help="Only query and print current task status for --task-id, without waiting for completion.",
    )
    return parser


def _resolve_file(path_value: str) -> Path:
    path = Path(path_value).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"file not found: {path}")
    if not path.is_file():
        raise FileNotFoundError(f"not a file: {path}")
    return path


def _normalize_timeout(timeout_seconds: float | None) -> float | None:
    if timeout_seconds is None or timeout_seconds <= 0:
        return None
    return float(timeout_seconds)


def _resolve_output_dir(source_path: Path | None, configured_output_dir: Path | None) -> Path:
    if configured_output_dir is not None:
        return configured_output_dir.expanduser().resolve()
    if source_path is not None:
        return source_path.parent
    return Path.cwd()


def _resolve_prefix(source_path: Path | None, task_id: str, configured_prefix: str | None) -> str:
    if configured_prefix:
        return configured_prefix
    if source_path is not None:
        return source_path.stem
    return task_id


def _create_sdk_bundle(client: DocMindClient) -> tuple[Any, Any, Any]:
    return client._create_sdk_client()


def _submit_file(
    client: DocMindClient,
    source_path: Path,
) -> str:
    sdk_client, models, runtime_models = _create_sdk_bundle(client)
    return client._submit_job(source_path, sdk_client, models, runtime_models)


def _query_status_payload(
    client: DocMindClient,
    sdk_client: Any,
    models: Any,
    task_id: str,
) -> tuple[str, dict[str, Any]]:
    request = models.QueryDocParserStatusRequest(id=task_id)
    response = sdk_client.query_doc_parser_status(request)
    body = client._as_dict(getattr(response, "body", response))
    data = client._pick(body, "data") or {}
    status = str(client._pick(data, "status") or "").lower() or "unknown"
    return status, data


def _wait_for_completion(
    client: DocMindClient,
    sdk_client: Any,
    models: Any,
    task_id: str,
    *,
    timeout_seconds: float | None,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds if timeout_seconds is not None else None
    last_status = "unknown"

    while deadline is None or time.monotonic() < deadline:
        status, data = _query_status_payload(client, sdk_client, models, task_id)
        last_status = status or last_status

        if status == "success":
            return data
        if status in {"failed", "fail", "canceled", "cancelled"}:
            error_message = client._pick(data, "error_message", "message") or data
            raise DocMindError(f"DocMind parse job failed for task {task_id}: {error_message}")

        print(f"status: {status}")
        time.sleep(poll_interval_seconds)

    raise DocMindError(
        f"DocMind parse job timed out after {timeout_seconds}s "
        f"(task_id={task_id}, last_status={last_status})"
    )


def _load_result(
    client: DocMindClient,
    sdk_client: Any,
    models: Any,
    task_id: str,
    status_data: dict[str, Any],
) -> DocMindParseResult:
    markdown_text = client._load_markdown_with_fallback(task_id, status_data, sdk_client, models)

    markdown_text = markdown_text.strip()
    if client._settings.docmind_strip_markdown_images and markdown_text:
        markdown_text = client._strip_markdown_images(markdown_text).strip()

    text = client._markdown_to_text(markdown_text) if markdown_text else ""
    if not text:
        raise DocMindError(f"DocMind returned no usable text for task {task_id}")

    return DocMindParseResult(
        text=text,
        markdown_text=markdown_text,
        task_id=task_id,
    )


def _write_outputs(
    output_dir: Path,
    prefix: str,
    result: DocMindParseResult,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    markdown_path = output_dir / f"{prefix}.docmind.md"
    text_path = output_dir / f"{prefix}.docmind.txt"
    metadata_path = output_dir / f"{prefix}.docmind.json"

    markdown_path.write_text(result.markdown_text, encoding="utf-8")
    text_path.write_text(result.text, encoding="utf-8")
    metadata_path.write_text(
        json.dumps(
            {
                "task_id": result.task_id,
                "markdown_path": str(markdown_path),
                "text_path": str(text_path),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"markdown: {markdown_path}")
    print(f"text: {text_path}")
    print(f"metadata: {metadata_path}")


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if not args.file and not args.task_id:
        parser.error("either a source file path or --task-id is required")

    settings = get_settings()
    client = DocMindClient(settings)
    if not client.enabled:
        print("DocMind is not configured.", file=sys.stderr)
        return 2

    source_path: Path | None = None
    if args.file:
        try:
            source_path = _resolve_file(args.file)
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            return 2

    if args.submit_only and source_path is None:
        parser.error("--submit-only requires a source file path")

    timeout_seconds = _normalize_timeout(args.timeout)
    poll_interval_seconds = (
        float(args.poll_interval)
        if args.poll_interval is not None and args.poll_interval > 0
        else float(settings.docmind_poll_interval_seconds)
    )

    try:
        task_id = args.task_id
        if task_id is None:
            assert source_path is not None
            task_id = _submit_file(client, source_path)
            print(f"task_id: {task_id}")
            if args.submit_only:
                return 0

        sdk_client, models, _runtime_models = _create_sdk_bundle(client)

        if args.status_only:
            status, data = _query_status_payload(client, sdk_client, models, task_id)
            print(f"task_id: {task_id}")
            print(f"status: {status}")
            if data:
                print(json.dumps(data, ensure_ascii=False, indent=2))
            return 0

        status_data = _wait_for_completion(
            client,
            sdk_client,
            models,
            task_id,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
        result = _load_result(client, sdk_client, models, task_id, status_data)

        output_dir = _resolve_output_dir(source_path, args.output_dir)
        prefix = _resolve_prefix(source_path, task_id, args.prefix)

        print("status: success")
        print(f"task_id: {task_id}")
        print(f"text_length: {len(result.text)}")
        print(f"markdown_length: {len(result.markdown_text)}")

        _write_outputs(output_dir, prefix, result)

        if args.print_markdown:
            print("\n--- markdown ---\n")
            print(result.markdown_text)

        if args.print_text:
            print("\n--- text ---\n")
            print(result.text)

        return 0
    except DocMindError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
