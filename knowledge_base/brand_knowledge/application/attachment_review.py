from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from knowledge_base.brand_knowledge.schemas import AttachmentReviewChangesRequest
from knowledge_base.shared.utils import parse_metadata_json


class AttachmentDraftReviewMixin:
    def _build_review_diff(
        self,
        *,
        current_snapshot: dict[str, Any],
        candidate_snapshot: dict[str, Any],
    ) -> tuple[dict[str, int], list[dict[str, Any]]]:
        list_item_keys = {
            "products": "name",
            "management_team": "name",
            "competitors": "name",
            "authority_honors": "title",
            "customers_cases": "case_name",
            "official_malls": "store_name",
            "official_media_matrix": "account_name",
            "other_info": "title",
        }
        current_flat = self._flatten_non_empty_fields(
            current_snapshot,
            prefix="",
            list_item_keys=list_item_keys,
        )
        candidate_flat = self._flatten_non_empty_fields(
            candidate_snapshot,
            prefix="",
            list_item_keys=list_item_keys,
        )

        changes: list[dict[str, Any]] = []
        added_count = 0
        modified_count = 0
        deleted_count = 0
        excluded_prefixes = ("attachments",)
        excluded_paths = {"basic_info.brand_name", "basic_info.brand_code"}

        for field_path, new_value in sorted(candidate_flat.items()):
            if field_path in excluded_paths or field_path.startswith(excluded_prefixes):
                continue
            old_value = current_flat.get(field_path)
            external_field_path = self._build_external_diff_field_path(field_path)
            if old_value is None:
                added_count += 1
                changes.append(
                    {
                        "field_path": external_field_path,
                        "field_label": self._build_diff_field_label(external_field_path),
                        "change_type": "added",
                        "old_value": None,
                        "new_value": new_value,
                    }
                )
                continue
            if old_value != new_value:
                modified_count += 1
                changes.append(
                    {
                        "field_path": external_field_path,
                        "field_label": self._build_diff_field_label(external_field_path),
                        "change_type": "modified",
                        "old_value": old_value,
                        "new_value": new_value,
                    }
                )

        return {
            "added_field_count": added_count,
            "modified_field_count": modified_count,
            "deleted_field_count": deleted_count,
        }, changes

    def _save_review_result(
        self,
        *,
        draft_id: str,
        review_id: str,
        payload: dict[str, Any],
    ) -> None:
        review_dir = self._review_dir(draft_id)
        review_dir.mkdir(parents=True, exist_ok=True)
        self._review_result_path(draft_id, review_id).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_review_result(self, *, draft_id: str, review_id: str) -> dict[str, Any]:
        review_path = self._review_result_path(draft_id, review_id)
        if not review_path.exists():
            raise ValueError("review_id 不存在或已过期")
        payload = parse_metadata_json(review_path.read_text(encoding="utf-8"))
        if not payload:
            raise ValueError("review 结果损坏")
        return payload

    async def review_changes(
        self,
        *,
        request: AttachmentReviewChangesRequest,
        draft_id: str,
    ) -> dict[str, Any]:
        manifest = self._load_draft_manifest(draft_id)
        draft_attachments = manifest.get("attachments") if isinstance(manifest, dict) else None
        if not isinstance(draft_attachments, list):
            raise ValueError("draft 附件信息缺失")

        brand_name = self._normalize_optional_str(request.brand_name) or self._normalize_optional_str(
            manifest.get("brand_name")
        )
        brand_code = self._normalize_optional_str(request.brand_code) or self._normalize_optional_str(
            manifest.get("brand_code")
        )
        if not brand_name:
            raise ValueError("brand_name 不能为空")

        brand = self._resolve_brand_record(brand_code=brand_code, brand_name=brand_name)
        current_snapshot, current_revision = self._build_current_snapshot(brand=brand)
        if request.knowledge_revision and current_revision and request.knowledge_revision.strip() != current_revision:
            raise RuntimeError(f"knowledge_revision 不匹配，当前 revision={current_revision}")

        candidate_payload = self._normalize_candidate_snapshot_input(request.candidate_snapshot)
        if not self._has_meaningful_payload(candidate_payload):
            raise ValueError("candidate_snapshot 不能为空")
        candidate_payload["basic_info"] = {
            **(candidate_payload.get("basic_info") or {}),
            "brand_name": brand_name,
            "brand_code": brand_code or self._normalize_optional_str(brand.get("brand_code")),
        }
        candidate_payload["attachments"] = self._normalize_attachment_entries(
            candidate_payload.get("attachments") or draft_attachments
        )
        summary, changes = self._build_review_diff(
            current_snapshot=current_snapshot,
            candidate_snapshot=candidate_payload,
        )

        review_id = f"bar_{uuid4().hex}"
        review_payload = {
            "review_id": review_id,
            "draft_id": draft_id,
            "brand_code": self._normalize_optional_str(brand.get("brand_code")) or brand_code,
            "brand_name": brand_name,
            "knowledge_revision": current_revision,
            "combined_markdown_text": self._normalize_markdown_text(manifest.get("combined_markdown_text")),
            "update_request_payload": candidate_payload,
            "summary": summary,
            "changes": changes,
        }
        self._save_review_result(
            draft_id=draft_id,
            review_id=review_id,
            payload=review_payload,
        )
        self._update_draft_manifest(
            draft_id=draft_id,
            updates={
                "draft_status": "reviewed",
                "last_review_id": review_id,
            },
        )

        return {
            "review_id": review_id,
            "draft_id": draft_id,
            "brand_code": review_payload["brand_code"],
            "brand_name": brand_name,
            "knowledge_revision": current_revision,
            "summary": summary,
            "changes": changes,
            "warnings": list(self._REVIEW_WARNING_MESSAGES),
            "can_confirm": True,
        }
