from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable


logger = logging.getLogger(__name__)

JOB_TYPE_BRAND_FULL_KNOWLEDGE_REFRESH = "brand_full_knowledge_refresh"


@dataclass(frozen=True)
class BrandFullKnowledgeRefreshJobHandler:
    deps: Any
    normalize_optional_str: Callable[[Any], str | None]
    build_callback_payload: Callable[..., dict[str, Any]]
    post_callback_if_configured: Callable[..., Awaitable[dict[str, Any]]]

    async def handle(
        self,
        job: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        audit_store = getattr(self.deps, "brand_knowledge_update_audits", None)
        if audit_store is None or not hasattr(audit_store, "list_unconsumed_for_full_knowledge"):
            raise RuntimeError("brand knowledge update audit store is not initialized")
        if not callable(self.deps.build_full_knowledge_from_update):
            raise RuntimeError("brand full knowledge generator is not initialized")

        brand_code = self.normalize_optional_str(payload.get("brand_code"))
        brand_name = self.normalize_optional_str(payload.get("brand_name"))
        if not brand_code:
            raise ValueError("brand_full_knowledge_refresh 缺少 brand_code")
        if not brand_name:
            raise ValueError("brand_full_knowledge_refresh 缺少 brand_name")
        source_types = [
            str(item or "").strip()
            for item in (payload.get("source_types") or ["knowledge_update", "attachment_confirm"])
            if str(item or "").strip()
        ]
        if not source_types:
            source_types = ["knowledge_update", "attachment_confirm"]

        audits = audit_store.list_unconsumed_for_full_knowledge(
            brand_code=brand_code,
            source_types=source_types,
        )
        if not audits:
            return {
                "brand_code": brand_code,
                "brand_name": brand_name,
                "status": "skipped",
                "reason": "no_unconsumed_audits",
                "consumed_audit_count": 0,
            }

        audit_ids = [int(item["id"]) for item in audits if item.get("id") is not None]
        job_id = str(job.get("job_id") or "").strip()
        if hasattr(audit_store, "claim_for_full_knowledge"):
            audit_store.claim_for_full_knowledge(
                audit_ids=audit_ids,
                full_knowledge_job_id=job_id,
            )
        try:
            knowledge_revision = self.normalize_optional_str(payload.get("knowledge_revision"))
            generated_source_task_id = self.build_source_task_id(
                job_id=job_id,
                knowledge_revision=knowledge_revision,
                audits=audits,
            )
            structured_knowledge_markdown = self.build_structured_markdown(
                brand_name=brand_name,
                audits=audits,
                attachment_markdowns=self.load_attachment_confirm_markdowns(audits),
            )
            change_origin = self.resolve_change_origin(audits)
            ai_knowledge_payload = await self.deps.build_full_knowledge_from_update(
                brand_name=brand_name,
                update_reason="brand_full_knowledge_refresh",
                source_task_id=generated_source_task_id,
                change_origin=change_origin,
                knowledge_revision=knowledge_revision,
                deleted_sections=self.deleted_sections_from_audits(audits),
                structured_knowledge_markdown=structured_knowledge_markdown,
            )
            if hasattr(audit_store, "mark_full_knowledge_consumed"):
                audit_store.mark_full_knowledge_consumed(
                    audit_ids=audit_ids,
                    full_knowledge_job_id=job_id,
                )
            pending_after = 0
            if hasattr(audit_store, "count_unconsumed_for_full_knowledge"):
                pending_after = int(
                    audit_store.count_unconsumed_for_full_knowledge(
                        brand_code=brand_code,
                        source_types=source_types,
                    )
                    or 0
                )
            callback_payload = self.build_callback_payload(
                brand_code=brand_code,
                knowledge_revision=knowledge_revision,
                ai_knowledge_payload=ai_knowledge_payload,
            )
            callback_result = await self.post_callback_if_configured(
                job=job,
                payload=payload,
                callback_payload=callback_payload,
            )
            return {
                "brand_code": brand_code,
                "brand_name": brand_name,
                "source_types": source_types,
                "change_origin": change_origin,
                "generated_source_task_id": generated_source_task_id,
                "consumed_audit_count": len(audit_ids),
                "pending_audit_count_after": pending_after,
                "ai_knowledge_payload": ai_knowledge_payload,
                "callback_payload": callback_payload,
                "callback_result": callback_result,
            }
        except Exception as exc:
            logger.warning(
                "Brand full knowledge refresh failed; releasing audit claim job_id=%s audit_count=%s error=%s",
                job_id,
                len(audit_ids),
                exc,
                exc_info=True,
            )
            if hasattr(audit_store, "release_full_knowledge_claim"):
                try:
                    audit_store.release_full_knowledge_claim(full_knowledge_job_id=job_id)
                except Exception as release_exc:  # noqa: BLE001
                    logger.warning(
                        "Failed to release brand full knowledge audit claim job_id=%s error=%s",
                        job_id,
                        release_exc,
                        exc_info=True,
                    )
            raise

    @classmethod
    def build_source_task_id(
        cls,
        *,
        job_id: str,
        knowledge_revision: str | None,
        audits: list[dict[str, Any]],
    ) -> str:
        batch_hash = cls.build_batch_hash(audits)
        normalized_job_id = str(job_id or "").strip() or JOB_TYPE_BRAND_FULL_KNOWLEDGE_REFRESH
        normalized_revision = str(knowledge_revision or "").strip() or "unknown"
        suffix = f":{batch_hash}"
        prefix = f"{normalized_job_id}:"
        max_length = 128
        max_revision_length = max_length - len(prefix) - len(suffix)
        if max_revision_length <= 0:
            return f"{normalized_job_id}:{batch_hash}"[:max_length]
        if len(normalized_revision) > max_revision_length:
            revision_hash = hashlib.sha256(normalized_revision.encode("utf-8")).hexdigest()[:8]
            if max_revision_length > len(revision_hash) + 1:
                normalized_revision = f"{normalized_revision[:max_revision_length - len(revision_hash) - 1]}-{revision_hash}"
            else:
                normalized_revision = revision_hash[:max_revision_length]
        return f"{prefix}{normalized_revision}{suffix}"

    @staticmethod
    def resolve_change_origin(audits: list[dict[str, Any]]) -> str:
        source_types = {
            str(audit.get("source_type") or "").strip()
            for audit in audits
            if str(audit.get("source_type") or "").strip()
        }
        if "knowledge_update" in source_types:
            return "frontend"
        if "attachment_confirm" in source_types:
            return "api"
        return "frontend"

    @staticmethod
    def build_batch_hash(audits: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for audit in audits:
            lines.append(
                "|".join(
                    [
                        str(audit.get("id") or "").strip(),
                        str(audit.get("source_type") or "").strip(),
                        str(audit.get("source_task_id") or "").strip(),
                        str(audit.get("section") or "").strip(),
                        str(audit.get("change_action") or "").strip(),
                    ]
                )
            )
        return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def deleted_sections_from_audits(audits: list[dict[str, Any]]) -> list[str]:
        deleted_sections: list[str] = []
        for audit in audits:
            if str(audit.get("change_action") or "").strip() != "delete":
                continue
            if not BrandFullKnowledgeRefreshJobHandler.is_empty_audit_value(audit.get("after_json")):
                continue
            section = str(audit.get("section") or "").strip()
            if section and section not in deleted_sections:
                deleted_sections.append(section)
        return deleted_sections

    @staticmethod
    def is_empty_audit_value(value: Any) -> bool:
        parsed_value = BrandFullKnowledgeRefreshJobHandler.parse_audit_json(value)
        if parsed_value is None:
            return True
        if isinstance(parsed_value, (list, dict, tuple, set)):
            return len(parsed_value) == 0
        if isinstance(parsed_value, str):
            return not parsed_value.strip()
        return False

    def load_attachment_confirm_markdowns(self, audits: list[dict[str, Any]]) -> list[dict[str, str]]:
        oss_client = getattr(self.deps, "oss_client", None)
        if oss_client is None or not getattr(oss_client, "enabled", False) or not hasattr(oss_client, "get_object_text"):
            return []
        seen_keys: set[str] = set()
        sources: list[dict[str, str]] = []
        for audit in audits:
            if str(audit.get("source_type") or "").strip() != "attachment_confirm":
                continue
            oss_key = str(audit.get("source_oss_key") or "").strip()
            if not oss_key or oss_key in seen_keys:
                continue
            seen_keys.add(oss_key)
            markdown_text = oss_client.get_object_text(oss_key)
            if not markdown_text:
                logger.warning("Attachment confirmed markdown missing for refresh source_oss_key=%s", oss_key)
                continue
            sources.append(
                {
                    "source_name": str(audit.get("source_name") or oss_key.rsplit("/", 1)[-1]),
                    "source_oss_key": oss_key,
                    "markdown_text": str(markdown_text),
                }
            )
        return sources

    @staticmethod
    def build_structured_markdown(
        *,
        brand_name: str,
        audits: list[dict[str, Any]],
        attachment_markdowns: list[dict[str, str]],
    ) -> str:
        lines: list[str] = [
            f"# {brand_name} 本轮品牌知识变更摘要",
            "",
            "本文件包含本轮合并后的 knowledge_update / attachment_confirm 变更；未列出的 section 请沿用上一版品牌 AI 知识库。",
            "",
            "## 变更来源",
        ]
        source_counts: dict[str, int] = {}
        for audit in audits:
            source_type = str(audit.get("source_type") or "knowledge_update").strip() or "knowledge_update"
            source_counts[source_type] = source_counts.get(source_type, 0) + 1
        for source_type, count in sorted(source_counts.items()):
            lines.append(f"- {source_type}: {count} 条")
        lines.extend(["", "## 结构化变更"])
        for audit in audits:
            section = str(audit.get("section") or "").strip()
            section_title = str(audit.get("section_title") or audit.get("section") or "").strip()
            action = str(audit.get("change_action") or "update").strip()
            lines.append("")
            lines.append(f"## {section_title}")
            lines.append("")
            lines.append(f"- section：`{section}`")
            lines.append(f"- source_type：`{str(audit.get('source_type') or '').strip()}`")
            source_task_id = str(audit.get("source_task_id") or "").strip()
            if source_task_id:
                lines.append(f"- source_task_id：`{source_task_id}`")
            lines.append(f"- change_type：`{action}`")
            before_json = BrandFullKnowledgeRefreshJobHandler.parse_audit_json(audit.get("before_json"))
            after_json = BrandFullKnowledgeRefreshJobHandler.parse_audit_json(audit.get("after_json"))
            lines.append("")
            lines.append("变更前内容：")
            lines.append("```json")
            lines.append(json.dumps(before_json, ensure_ascii=False, indent=2, default=str))
            lines.append("```")
            lines.append("")
            lines.append("本次更新后的内容：")
            lines.append("```json")
            lines.append(json.dumps(after_json, ensure_ascii=False, indent=2, default=str))
            lines.append("```")
        if attachment_markdowns:
            lines.extend(["", "## 附件确认 Markdown"])
            for source in attachment_markdowns:
                lines.append("")
                lines.append(f"### {source['source_name']}")
                lines.append(str(source.get("markdown_text") or "").strip())
        return "\n".join(lines).strip()

    @staticmethod
    def parse_audit_json(value: Any) -> Any:
        if isinstance(value, (dict, list)):
            return value
        if isinstance(value, str) and value.strip():
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return None
