from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from knowledge_base.shared.utils import parse_metadata_json


logger = logging.getLogger(__name__)


class AttachmentDraftRuntimeMixin:
    def _draft_root(self) -> Path:
        return Path(self._deps.settings.upload_staging_dir) / "attachment_parse_drafts"

    def _draft_dir(self, draft_id: str) -> Path:
        return self._draft_root() / draft_id

    def _download_dir(self, draft_id: str) -> Path:
        return self._draft_dir(draft_id) / "downloads"

    def _review_dir(self, draft_id: str) -> Path:
        return self._draft_dir(draft_id) / "reviews"

    def _draft_manifest_path(self, draft_id: str) -> Path:
        return self._draft_dir(draft_id) / "draft.json"

    def _review_result_path(self, draft_id: str, review_id: str) -> Path:
        return self._review_dir(draft_id) / f"{review_id}.json"

    def _confirmed_markdown_dir(self, draft_id: str) -> Path:
        return self._draft_dir(draft_id) / "confirmed_markdowns"

    def _attachment_draft_ttl_seconds(self) -> int:
        raw_value = getattr(
            self._deps.settings,
            "attachment_draft_ttl_seconds",
            self.ATTACHMENT_DRAFT_TTL_SECONDS,
        )
        try:
            ttl_seconds = int(raw_value)
        except (TypeError, ValueError):
            ttl_seconds = self.ATTACHMENT_DRAFT_TTL_SECONDS
        return max(60, ttl_seconds)

    @staticmethod
    def _parse_manifest_datetime(value: Any) -> datetime | None:
        normalized = str(value or "").strip()
        if not normalized:
            return None
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            return None

    @staticmethod
    def _serialize_manifest_datetime(value: datetime) -> str:
        return value.isoformat(timespec="seconds")

    def _draft_last_active_at(
        self,
        *,
        manifest_path: Path,
        manifest: dict[str, Any],
    ) -> datetime:
        last_active_at = self._parse_manifest_datetime(manifest.get("updated_at"))
        if last_active_at is None:
            last_active_at = self._parse_manifest_datetime(manifest.get("created_at"))
        if last_active_at is None:
            last_active_at = datetime.fromtimestamp(manifest_path.stat().st_mtime)
        return last_active_at

    def _draft_is_expired(
        self,
        *,
        manifest_path: Path,
        manifest: dict[str, Any],
        now: datetime | None = None,
    ) -> bool:
        draft_status = str(manifest.get("draft_status") or "").strip()
        if draft_status not in self._DRAFT_ACTIVE_STATUSES:
            return False
        current_time = now or datetime.now()
        last_active_at = self._draft_last_active_at(manifest_path=manifest_path, manifest=manifest)
        return current_time >= last_active_at + timedelta(seconds=self._attachment_draft_ttl_seconds())

    def _delete_draft_dir(self, draft_id: str, *, reason: str) -> None:
        draft_dir = self._draft_dir(draft_id)
        if not draft_dir.exists():
            return
        logger.info("Attachment draft cleanup draft_id=%s reason=%s", draft_id, reason)
        shutil.rmtree(draft_dir, ignore_errors=True)

    def _persist_draft_manifest(
        self,
        *,
        draft_id: str,
        manifest: dict[str, Any],
    ) -> dict[str, Any]:
        normalized_manifest = dict(manifest)
        now = datetime.now()
        if not self._parse_manifest_datetime(normalized_manifest.get("created_at")):
            normalized_manifest["created_at"] = self._serialize_manifest_datetime(now)
        normalized_manifest["updated_at"] = self._serialize_manifest_datetime(now)
        normalized_manifest["draft_status"] = (
            str(normalized_manifest.get("draft_status") or "").strip() or "pending_review"
        )
        normalized_manifest["draft_ttl_seconds"] = self._attachment_draft_ttl_seconds()
        self._draft_manifest_path(draft_id).write_text(
            json.dumps(normalized_manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return normalized_manifest

    def _update_draft_manifest(
        self,
        *,
        draft_id: str,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        manifest = self._load_draft_manifest(draft_id)
        manifest.update(updates)
        return self._persist_draft_manifest(draft_id=draft_id, manifest=manifest)

    def cleanup_expired_drafts(self) -> int:
        draft_root = self._draft_root()
        if not draft_root.exists():
            return 0
        deleted_count = 0
        now = datetime.now()
        ttl_seconds = self._attachment_draft_ttl_seconds()
        for child in draft_root.iterdir():
            if not child.is_dir():
                continue
            manifest_path = child / "draft.json"
            if manifest_path.exists():
                manifest = parse_metadata_json(manifest_path.read_text(encoding="utf-8"))
                if isinstance(manifest, dict) and self._draft_is_expired(
                    manifest_path=manifest_path,
                    manifest=manifest,
                    now=now,
                ):
                    self._delete_draft_dir(child.name, reason="ttl_expired")
                    deleted_count += 1
                continue
            last_modified_at = datetime.fromtimestamp(child.stat().st_mtime)
            if now >= last_modified_at + timedelta(seconds=ttl_seconds):
                self._delete_draft_dir(child.name, reason="orphan_dir_ttl_expired")
                deleted_count += 1
        return deleted_count

    @staticmethod
    def _should_cleanup_draft_after_confirm_failure(job: dict[str, Any] | None) -> bool:
        if job is None:
            return True
        retry_count = int(job.get("retry_count") or 0) + 1
        max_retries = int(job.get("max_retries") or 0)
        return retry_count > max_retries

    def _preview_parse_max_concurrency(self, attachment_count: int) -> int:
        raw_value = getattr(
            self._deps.settings,
            "attachment_preview_parse_max_concurrency",
            self.PREVIEW_PARSE_MAX_CONCURRENCY,
        )
        try:
            concurrency = int(raw_value)
        except (TypeError, ValueError):
            concurrency = self.PREVIEW_PARSE_MAX_CONCURRENCY
        concurrency = max(1, min(concurrency, self.PREVIEW_PARSE_MAX_CONCURRENCY_CAP))
        if attachment_count > 0:
            concurrency = min(concurrency, attachment_count)
        return concurrency

    def _load_draft_manifest(self, draft_id: str) -> dict[str, Any]:
        manifest_path = self._draft_manifest_path(draft_id)
        if not manifest_path.exists():
            raise ValueError("draft_id 不存在或已过期")
        manifest = parse_metadata_json(manifest_path.read_text(encoding="utf-8"))
        if not manifest:
            raise ValueError("draft 信息损坏")
        if self._draft_is_expired(manifest_path=manifest_path, manifest=manifest):
            self._delete_draft_dir(draft_id, reason="ttl_expired_on_access")
            raise ValueError("draft_id 不存在或已过期")
        return manifest
