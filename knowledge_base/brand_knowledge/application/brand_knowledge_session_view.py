from __future__ import annotations

import json
import unicodedata
from datetime import datetime
from typing import Any

from knowledge_base.brand.full_markdown import build_brand_full_knowledge_filename


class BrandKnowledgeSessionViewMixin:
    @staticmethod
    def _parse_json_value(raw: Any, default: Any) -> Any:
        if raw is None:
            return default
        if isinstance(raw, (dict, list)):
            return raw
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return default
            return parsed
        return default

    @staticmethod
    def _build_assistant_message(
        *,
        status: str,
        round_no: int,
        conflicts: list[dict[str, Any]],
        conflict_markdown: str | None,
        final_markdown: str | None,
    ) -> str:
        if status == "completed":
            return "所有冲突已处理完毕，已生成最终《品牌知识库》。"
        if conflict_markdown:
            return f"我已经完成第 {round_no} 轮整理，并识别到以下待确认内容：\n\n{conflict_markdown}"
        if conflicts:
            lines = [f"我已经完成第 {round_no} 轮整理，并识别到以下待确认内容："]
            for index, conflict in enumerate(conflicts, start=1):
                topic = str(conflict.get("topic") or f"冲突 {index}")
                description = str(conflict.get("description") or "").strip()
                lines.append(f"\n冲突 {index}｜{topic}")
                if description:
                    lines.append(description)
            lines.append("\n请直接回复你的决定，例如：冲突1 选A，冲突2 以第二份资料为准。")
            return "\n".join(lines)
        if final_markdown:
            return "已生成最终《品牌知识库》。"
        return f"第 {round_no} 轮已完成，请继续输入。"

    @staticmethod
    def _build_conflict_markdown(conflicts: list[dict[str, Any]]) -> str | None:
        if not conflicts:
            return None

        lines = ["# 待确认冲突清单"]
        for index, conflict in enumerate(conflicts, start=1):
            topic = str(conflict.get("topic") or "未命名冲突").strip()
            description = str(conflict.get("description") or "").strip()

            lines.append(f"\n## 冲突 {index}：{topic}")
            if description:
                lines.append(description)

            options = conflict.get("options")
            if isinstance(options, list) and options:
                for option in options:
                    if not isinstance(option, dict):
                        continue
                    option_id = str(option.get("option_id") or "").strip() or "?"
                    content = str(option.get("content") or "").strip() or "未提供"
                    source_files = option.get("source_files")
                    normalized_sources = "、".join(
                        str(item).strip()
                        for item in source_files
                        if str(item).strip()
                    ) if isinstance(source_files, list) else "未提供"
                    lines.append(f"\n- 选项 {option_id}：{content} —— 来源：{normalized_sources}")

        return "\n".join(lines)

    @staticmethod
    def _build_final_knowledge_filename(brand_name: str, *, version_no: int = 1) -> str:
        return build_brand_full_knowledge_filename(
            brand_name=str(brand_name or "").strip(),
            version_no=version_no,
            now=datetime.now(),
        )

    @staticmethod
    def _normalize_auto_merged(raw_auto_merged: Any) -> list[dict[str, Any]]:
        if not isinstance(raw_auto_merged, list):
            return []
        normalized_items: list[dict[str, Any]] = []
        for item in raw_auto_merged:
            if not isinstance(item, dict):
                continue
            topic = str(item.get("topic") or "").strip()
            category = str(item.get("category") or "").strip()
            resolution = str(item.get("resolution") or "").strip()
            if not topic or not category or not resolution:
                continue
            source_files = item.get("source_files")
            normalized_items.append(
                {
                    "topic": topic,
                    "category": category,
                    "resolution": resolution,
                    "source_files": [
                        str(source_file).strip()
                        for source_file in source_files
                        if str(source_file).strip()
                    ] if isinstance(source_files, list) else [],
                }
            )
        return normalized_items

    @staticmethod
    def _normalize_conflicts(raw_conflicts: Any) -> list[dict[str, Any]]:
        if not isinstance(raw_conflicts, list):
            return []

        normalized_conflicts: list[dict[str, Any]] = []
        for index, item in enumerate(raw_conflicts, start=1):
            if not isinstance(item, dict):
                continue
            conflict_id = str(item.get("conflict_id") or "").strip() or str(index)
            topic = str(item.get("topic") or "").strip()
            if not topic:
                continue
            severity = str(item.get("severity") or "").strip() or None

            raw_options = item.get("options")
            normalized_options: list[dict[str, Any]] = []
            if isinstance(raw_options, list):
                for option_index, option in enumerate(raw_options, start=1):
                    if not isinstance(option, dict):
                        continue
                    option_id = str(option.get("option_id") or chr(64 + option_index)).strip() or chr(64 + option_index)
                    content = str(option.get("content") or "").strip()
                    if not content:
                        continue
                    source_files = option.get("source_files")
                    normalized_options.append(
                        {
                            "option_id": option_id,
                            "content": content,
                            "source_files": [
                                str(source_file).strip()
                                for source_file in source_files
                                if str(source_file).strip()
                            ] if isinstance(source_files, list) else [],
                        }
                    )

            if not normalized_options:
                continue

            normalized_conflicts.append(
                {
                    "conflict_id": conflict_id,
                    "topic": topic,
                    "severity": severity,
                    "description": str(item.get("description") or "").strip() or None,
                    "options": normalized_options,
                }
            )

        return normalized_conflicts

    @staticmethod
    def _normalize_markdown_text(value: Any) -> str:
        text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
        text = unicodedata.normalize("NFKC", text)
        lines = [line.rstrip() for line in text.split("\n")]
        return "\n".join(lines).strip()

    @staticmethod
    def _seconds_until(next_retry_at: Any) -> float:
        if not isinstance(next_retry_at, datetime):
            return 0.0
        return max(0.0, (next_retry_at - datetime.now()).total_seconds())

    @staticmethod
    def _attachment_conflict_resolution_job_id(session_id: str) -> str:
        normalized_session_id = str(session_id or "").strip()
        return f"bg:attachment_conflict_resolution:{normalized_session_id}"[:128]

    @staticmethod
    def _session_type_from_kind(session_kind: Any) -> str | None:
        normalized_session_kind = str(session_kind or "").strip()
        if normalized_session_kind == "attachment_conflict" or normalized_session_kind.startswith("attachment_conflict:"):
            return "initial_generation"
        if normalized_session_kind == "knowledge_iteration" or normalized_session_kind.startswith("knowledge_iteration:"):
            return "knowledge_iteration"
        return normalized_session_kind or None

    @staticmethod
    def _iteration_mode_from_kind(session_kind: Any) -> str | None:
        normalized_session_kind = str(session_kind or "").strip()
        prefix = "knowledge_iteration:"
        if normalized_session_kind.startswith(prefix):
            return normalized_session_kind.removeprefix(prefix).strip() or None
        return None

    @classmethod
    def _normalize_session_payload(
        cls,
        payload: dict[str, Any],
        *,
        allow_completed: bool,
        fallback_summary: str | None = None,
    ) -> dict[str, Any]:
        normalized_conflicts = cls._normalize_conflicts(payload.get("conflicts"))
        normalized_auto_merged = cls._normalize_auto_merged(payload.get("auto_merged"))
        final_markdown = str(payload.get("final_markdown") or "").strip() or None
        working_summary = str(
            payload.get("working_summary")
            or payload.get("draft_markdown")
            or fallback_summary
            or ""
        ).strip() or None
        scan_summary = str(payload.get("scan_summary") or "").strip() or working_summary

        requested_status = str(payload.get("status") or "").strip()
        if normalized_conflicts:
            status = "waiting_user_input"
            final_markdown = None
        elif allow_completed and final_markdown:
            status = "completed"
        elif requested_status == "completed" and allow_completed and final_markdown:
            status = "completed"
        elif requested_status == "no_conflicts":
            status = "no_conflicts"
        else:
            status = "running"

        return {
            "status": status,
            "working_summary": working_summary,
            "scan_summary": scan_summary,
            "auto_merged": normalized_auto_merged,
            "conflicts": normalized_conflicts,
            "conflict_markdown": cls._build_conflict_markdown(normalized_conflicts),
            "final_markdown": final_markdown if status == "completed" else None,
        }

    def get_latest_attachment_conflict_session(
        self,
        *,
        brand_code: str,
        brand_name: str | None = None,
    ) -> dict[str, Any] | None:
        normalized_brand_code = str(brand_code or "").strip()
        if not normalized_brand_code:
            raise ValueError("brand_code 不能为空")

        brand = self._deps.brands.get_brand_by_code(normalized_brand_code)
        if not brand:
            raise ValueError("品牌不存在，请先建品牌")

        candidate_sessions = [
            session
            for session_kind in ("attachment_conflict", "attachment_conflict:draft_only")
            for session in [
                self._deps.brand_knowledge_sessions.get_latest_by_brand_code(
                    brand_code=normalized_brand_code,
                    session_kind=session_kind,
                    preferred_statuses=["waiting_user_input", "running", "no_conflicts", "failed", "completed"],
                )
            ]
            if session
        ]
        session = max(candidate_sessions, key=self._session_recency_sort_key) if candidate_sessions else None
        if not session:
            return None

        session_id = str(session.get("session_id") or "").strip()
        if not session_id:
            return None
        return self.get_knowledge_session(session_id=session_id)

    @staticmethod
    def _session_recency_sort_key(session: dict[str, Any]) -> tuple[datetime, int]:
        timestamp = session.get("updated_at") or session.get("created_at")
        if isinstance(timestamp, datetime):
            parsed_timestamp = timestamp
        else:
            parsed_timestamp = datetime.min
            if timestamp is not None:
                try:
                    parsed_timestamp = datetime.fromisoformat(str(timestamp))
                except ValueError:
                    parsed_timestamp = datetime.min
        try:
            row_id = int(session.get("id") or 0)
        except (TypeError, ValueError):
            row_id = 0
        return parsed_timestamp, row_id

    def get_knowledge_session(self, *, session_id: str) -> dict[str, Any] | None:
        session = self._deps.brand_knowledge_sessions.get_session(session_id)
        if not session:
            return None
        source_documents = self._parse_json_value(session.get("source_documents_json"), [])
        conflicts = self._parse_json_value(session.get("latest_conflicts_json"), [])
        auto_merged = self._normalize_auto_merged(
            self._parse_json_value(session.get("latest_auto_merged_json"), [])
        )
        if not isinstance(source_documents, list):
            source_documents = []
        if not isinstance(conflicts, list):
            conflicts = []
        final_full_knowledge_file_id = session.get("final_full_knowledge_file_id")
        final_document_id = str(session.get("final_document_id") or "").strip() or None
        final_knowledge_row = None
        normalized_file_id = None
        if final_full_knowledge_file_id not in {None, ""}:
            try:
                normalized_file_id = int(final_full_knowledge_file_id)
            except (TypeError, ValueError):
                normalized_file_id = None
        if normalized_file_id is not None:
            final_knowledge_row = self._deps.brand_full_knowledge.get_by_ids(file_ids=[normalized_file_id]).get(
                normalized_file_id
            )
        final_filename = None
        knowledge_oss_url_md = None
        knowledge_oss_url_pdf = None
        final_oss_key = session.get("final_oss_key")
        if isinstance(final_knowledge_row, dict):
            final_filename = final_knowledge_row.get("file_name")
            knowledge_oss_url_md = final_knowledge_row.get("oss_url")
            knowledge_oss_url_pdf = final_knowledge_row.get("pdf_oss_url")
            final_oss_key = final_knowledge_row.get("oss_key") or final_oss_key
            final_document_id = str(final_knowledge_row.get("document_id") or "").strip() or final_document_id
        elif session.get("final_markdown"):
            final_filename = self._build_final_knowledge_filename(str(session.get("brand_name") or ""))
        return {
            "session_id": str(session.get("session_id") or ""),
            "brand_code": str(session.get("brand_code") or "").strip() or None,
            "brand_name": str(session.get("brand_name") or ""),
            "status": str(session.get("status") or ""),
            "knowledge_markdown_status": str(session.get("status") or ""),
            "round_no": int(session.get("current_round") or 0),
            "session_type": self._session_type_from_kind(session.get("session_kind")),
            "iteration_mode": self._iteration_mode_from_kind(session.get("session_kind")),
            "session_kind": str(session.get("session_kind") or "").strip() or None,
            "source_task_id": str(session.get("source_task_id") or "").strip() or None,
            "assistant_message": str(session.get("latest_assistant_message") or "") or self._build_assistant_message(
                status=str(session.get("status") or ""),
                round_no=int(session.get("current_round") or 0),
                conflicts=conflicts,
                conflict_markdown=session.get("latest_conflict_markdown"),
                final_markdown=session.get("final_markdown"),
            ),
            "source_documents": source_documents,
            "conflicts": conflicts,
            "conflict_markdown": session.get("latest_conflict_markdown"),
            "scan_summary": str(session.get("latest_scan_summary") or "").strip() or None,
            "auto_merged": auto_merged,
            "final_markdown": session.get("final_markdown"),
            "final_oss_key": final_oss_key,
            "final_filename": final_filename,
            "final_full_knowledge_file_id": normalized_file_id,
            "final_document_id": final_document_id,
            "knowledge_oss_url_md": knowledge_oss_url_md,
            "knowledge_oss_url_pdf": knowledge_oss_url_pdf,
        }
