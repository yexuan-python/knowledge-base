from __future__ import annotations

from typing import Any

from knowledge_base.shared.utils import apply_oss_test_prefix, object_key_matches_current_oss_prefix
from knowledge_base.shared.utils.oss_keys import sanitize_oss_segment


class BrandDeleteWorkflowMixin:
    async def delete_brand(
        self,
        *,
        brand_name: str,
        dry_run: bool,
    ) -> dict[str, Any]:
        normalized_brand_name = (brand_name or "").strip()
        if not normalized_brand_name:
            raise ValueError("brand_name 不能为空")

        brand = self._deps.brands.get_brand_by_name(normalized_brand_name)
        if not brand or brand.get("id") is None:
            raise ValueError("brand_name 对应的品牌不存在")

        resolved_brand_id = int(brand["id"])
        resolved_brand_code = str(self._brand_code_from_row(brand) or "").strip()
        resolved_brand_name = str(self._brand_name_from_row(brand, normalized_brand_name) or normalized_brand_name)
        registry_entries = self._deps.document_registry.get_document_registry_entries_by_category(resolved_brand_name)
        category_document_ids = self._deps.document_categories.get_document_ids_by_category(resolved_brand_name)
        attachment_asset_rows: list[dict[str, Any]] = []
        if (
            resolved_brand_code
            and self._deps.brand_attachment_assets is not None
            and hasattr(self._deps.brand_attachment_assets, "list_by_brand_code")
        ):
            attachment_asset_rows = list(
                self._deps.brand_attachment_assets.list_by_brand_code(
                    brand_code=resolved_brand_code,
                    limit=10000,
                ) or []
            )
        document_ids = sorted(
            {
                str(entry["document_id"])
                for entry in registry_entries
                if entry.get("document_id")
            }
            | {str(document_id) for document_id in category_document_ids if document_id}
        )
        doc_info_map = {
            str(item["document_id"]): item
            for item in self._deps.store.get_documents_info_by_ids(document_ids)
        }
        registry_map = {
            str(entry["document_id"]): entry
            for entry in registry_entries
            if entry.get("document_id")
        }
        oss_keys: set[str] = set()
        for document_id in document_ids:
            oss_keys.update(
                self._deps.document_app.collect_document_object_keys(
                    document_id=document_id,
                    doc_info=doc_info_map.get(document_id),
                    registry_entry=registry_map.get(document_id),
                )
            )

        full_knowledge_rows = self._list_brand_full_knowledge_rows(
            brand_code=str(brand.get("brand_code") or "").strip(),
        )
        full_knowledge_document_ids = {
            str(row.get("document_id") or "").strip()
            for row in full_knowledge_rows
            if str(row.get("document_id") or "").strip()
        }
        document_ids = sorted({*document_ids, *full_knowledge_document_ids})
        full_knowledge_oss_keys = self._collect_brand_full_knowledge_object_keys(full_knowledge_rows)
        attachment_asset_oss_keys = self._collect_brand_attachment_asset_object_keys(attachment_asset_rows)
        ai_knowledge_oss_keys = set(full_knowledge_oss_keys)
        confirmed_knowledge_oss_keys: set[str] = set()
        if self._deps.oss_client is not None:
            ai_knowledge_oss_keys.update(
                self._list_brand_artifact_object_keys(
                    brand_name=resolved_brand_name,
                    artifact_dir="ai_knowledge",
                )
            )
            confirmed_knowledge_oss_keys.update(
                self._list_brand_artifact_object_keys(
                    brand_name=resolved_brand_name,
                    artifact_dir="confirmed_knowledge",
                )
            )
        oss_keys = self._filter_oss_keys_for_current_prefix(oss_keys)
        full_knowledge_oss_keys = self._filter_oss_keys_for_current_prefix(full_knowledge_oss_keys)
        attachment_asset_oss_keys = self._filter_oss_keys_for_current_prefix(attachment_asset_oss_keys)
        ai_knowledge_oss_keys = self._filter_oss_keys_for_current_prefix(ai_knowledge_oss_keys)
        confirmed_knowledge_oss_keys = self._filter_oss_keys_for_current_prefix(confirmed_knowledge_oss_keys)
        brand_artifact_oss_keys = ai_knowledge_oss_keys | confirmed_knowledge_oss_keys
        extra_oss_keys = brand_artifact_oss_keys | attachment_asset_oss_keys
        all_oss_keys = oss_keys | extra_oss_keys

        session_counts = {
            "brand_knowledge_sessions": 0,
            "brand_knowledge_session_rounds": 0,
        }
        if self._deps.brand_knowledge_sessions is not None and hasattr(
            self._deps.brand_knowledge_sessions,
            "count_by_brand_identifier",
        ):
            session_counts = self._deps.brand_knowledge_sessions.count_by_brand_identifier(
                brand_code=resolved_brand_code or None,
                brand_name=resolved_brand_name,
            )

        upload_task_counts = {
            "upload_tasks": 0,
            "upload_task_files": 0,
            "upload_task_callbacks": 0,
        }
        upload_task_ids: list[str] = []
        if self._deps.upload_tasks is not None and hasattr(self._deps.upload_tasks, "count_by_brand_identifier"):
            upload_task_counts = self._deps.upload_tasks.count_by_brand_identifier(
                brand_code=resolved_brand_code or None,
                brand_name=resolved_brand_name,
            )
        if self._deps.upload_tasks is not None and hasattr(self._deps.upload_tasks, "list_task_ids_by_brand_identifier"):
            upload_task_ids = self._deps.upload_tasks.list_task_ids_by_brand_identifier(
                brand_code=resolved_brand_code or None,
                brand_name=resolved_brand_name,
            )

        ingestion_job_count = 0
        if (
            resolved_brand_code
            and self._deps.brand_knowledge_ingestion_jobs is not None
            and hasattr(self._deps.brand_knowledge_ingestion_jobs, "count_by_brand_code")
        ):
            ingestion_job_count = int(
                self._deps.brand_knowledge_ingestion_jobs.count_by_brand_code(
                    brand_code=resolved_brand_code,
                )
                or 0
            )

        background_job_count = 0
        if self._deps.background_jobs is not None and hasattr(
            self._deps.background_jobs,
            "count_by_brand_identifier",
        ):
            background_job_count = int(
                self._deps.background_jobs.count_by_brand_identifier(
                    brand_code=resolved_brand_code or None,
                    brand_name=resolved_brand_name,
                    source_ids=upload_task_ids,
                )
                or 0
            )

        brand_fact_count = 0
        if (
            resolved_brand_code
            and self._deps.brand_knowledge_facts is not None
            and hasattr(self._deps.brand_knowledge_facts, "count_by_brand_code")
        ):
            brand_fact_count = int(
                self._deps.brand_knowledge_facts.count_by_brand_code(
                    brand_code=resolved_brand_code,
                ) or 0
            )

        counts = {
            "brands": 1,
            "brand_products": self._deps.brand_products.count_brand_products_for_delete(
                brand_id=resolved_brand_id,
                brand_name=resolved_brand_name,
            ),
            "brand_knowledge_json": self._deps.brand_knowledge.count_brand_knowledge_json(
                brand_id=resolved_brand_id,
            ),
            "brand_attachment_assets": len(attachment_asset_rows),
            **session_counts,
            "brand_knowledge_facts": brand_fact_count,
            "documents": len(document_ids),
            "document_registry": len(registry_entries),
            "document_categories": len(category_document_ids),
            "document_fact_relations": self._deps.fact_relations.count_document_fact_relations(document_ids),
            "brand_full_knowledge_files": len(full_knowledge_rows),
            "brand_knowledge_ingestion_jobs": ingestion_job_count,
            "background_jobs": background_job_count,
            **upload_task_counts,
            "ai_knowledge_oss_objects": len(ai_knowledge_oss_keys),
            "confirmed_knowledge_oss_objects": len(confirmed_knowledge_oss_keys),
            "oss_objects": len(all_oss_keys),
        }

        execute_delete = bool(dry_run)
        if not execute_delete:
            return {
                "brand_id": resolved_brand_id,
                "brand_code": resolved_brand_code or None,
                "brand_name": resolved_brand_name,
                "dry_run": False,
                "executed": False,
                "message": "品牌删除预览完成，未执行真实删除。",
                "counts": counts,
            }

        for document_id in document_ids:
            await self._delete_document_with_current_oss_prefix_filter(document_id)

        if self._deps.oss_client is not None:
            for object_key in sorted(extra_oss_keys - oss_keys):
                self._deps.oss_client.delete_object(object_key)
        if (
            self._deps.brand_knowledge_sessions is not None
            and hasattr(self._deps.brand_knowledge_sessions, "delete_by_brand_identifier")
        ):
            self._deps.brand_knowledge_sessions.delete_by_brand_identifier(
                brand_code=resolved_brand_code or None,
                brand_name=resolved_brand_name,
            )
        if (
            resolved_brand_code
            and self._deps.brand_attachment_assets is not None
            and hasattr(self._deps.brand_attachment_assets, "delete_by_brand_code")
        ):
            self._deps.brand_attachment_assets.delete_by_brand_code(brand_code=resolved_brand_code)
        if (
            resolved_brand_code
            and self._deps.brand_knowledge_ingestion_jobs is not None
            and hasattr(self._deps.brand_knowledge_ingestion_jobs, "delete_by_brand_code")
        ):
            self._deps.brand_knowledge_ingestion_jobs.delete_by_brand_code(brand_code=resolved_brand_code)
        if self._deps.background_jobs is not None and hasattr(
            self._deps.background_jobs,
            "delete_by_brand_identifier",
        ):
            self._deps.background_jobs.delete_by_brand_identifier(
                brand_code=resolved_brand_code or None,
                brand_name=resolved_brand_name,
                source_ids=upload_task_ids,
            )
        if self._deps.upload_tasks is not None and hasattr(self._deps.upload_tasks, "delete_by_brand_identifier"):
            self._deps.upload_tasks.delete_by_brand_identifier(
                brand_code=resolved_brand_code or None,
                brand_name=resolved_brand_name,
            )
        if (
            resolved_brand_code
            and self._deps.brand_knowledge_facts is not None
            and hasattr(self._deps.brand_knowledge_facts, "delete_by_brand_code")
        ):
            self._deps.brand_knowledge_facts.delete_by_brand_code(brand_code=resolved_brand_code)
        if resolved_brand_code and hasattr(self._deps.store, "delete_facts_by_brand_code"):
            self._deps.store.delete_facts_by_brand_code(resolved_brand_code)
        if (
            resolved_brand_code
            and self._deps.brand_full_knowledge is not None
            and hasattr(self._deps.brand_full_knowledge, "delete_by_brand_code")
        ):
            self._deps.brand_full_knowledge.delete_by_brand_code(brand_code=resolved_brand_code)
        elif self._deps.brand_full_knowledge is not None and hasattr(self._deps.brand_full_knowledge, "delete_by_brand_id"):
            self._deps.brand_full_knowledge.delete_by_brand_id(brand_id=resolved_brand_id)
        self._deps.brand_knowledge.delete_brand_knowledge_json(brand_id=resolved_brand_id)
        self._deps.brand_products.delete_brand_products(
            brand_id=resolved_brand_id,
            brand_name=resolved_brand_name,
        )
        self._deps.brands.delete_brand(brand_id=resolved_brand_id)
        self._deps.document_categories.invalidate_latest_document_ids_cache(resolved_brand_name)

        return {
            "brand_id": resolved_brand_id,
            "brand_code": resolved_brand_code or None,
            "brand_name": resolved_brand_name,
            "dry_run": True,
            "executed": True,
            "message": "品牌及其关联知识数据已删除。",
            "counts": counts,
        }

    def _list_brand_full_knowledge_rows(self, *, brand_code: str) -> list[dict[str, Any]]:
        store = self._deps.brand_full_knowledge
        if not brand_code or store is None:
            return []
        if hasattr(store, "list_by_brand_code"):
            return list(store.list_by_brand_code(brand_code=brand_code) or [])
        brand = self._deps.brands.get_brand_by_code(brand_code)
        brand_id = (brand or {}).get("id")
        if brand_id is not None and hasattr(store, "list_by_brand_id"):
            return list(store.list_by_brand_id(brand_id=int(brand_id)) or [])
        return []

    @staticmethod
    def _collect_brand_full_knowledge_object_keys(rows: list[dict[str, Any]]) -> set[str]:
        object_keys: set[str] = set()
        for row in rows:
            for field_name in ("oss_key", "pdf_oss_key"):
                object_key = str(row.get(field_name) or "").strip()
                if object_key:
                    object_keys.add(object_key)
        return object_keys

    @staticmethod
    def _collect_brand_attachment_asset_object_keys(rows: list[dict[str, Any]]) -> set[str]:
        object_keys: set[str] = set()
        for row in rows:
            for field_name in ("oss_key", "fulltext_key"):
                object_key = str(row.get(field_name) or "").strip()
                if object_key:
                    object_keys.add(object_key)
        return object_keys

    @staticmethod
    def _filter_oss_keys_for_current_prefix(object_keys: set[str]) -> set[str]:
        return {
            object_key
            for object_key in object_keys
            if object_key_matches_current_oss_prefix(object_key)
        }

    async def _delete_document_with_current_oss_prefix_filter(self, document_id: str) -> None:
        await self._deps.delete_document(
            document_id,
            oss_object_key_filter=object_key_matches_current_oss_prefix,
        )

    def _list_brand_artifact_object_keys(self, *, brand_name: str, artifact_dir: str) -> set[str]:
        oss_client = self._deps.oss_client
        if oss_client is None or not getattr(oss_client, "enabled", False):
            return set()
        if not hasattr(oss_client, "list_object_keys"):
            return set()
        safe_brand_name = sanitize_oss_segment(brand_name, default="uncategorized")
        prefixes = (apply_oss_test_prefix(f"{safe_brand_name}/{artifact_dir}/"),)
        object_keys: set[str] = set()
        for prefix in prefixes:
            object_keys.update(str(key) for key in oss_client.list_object_keys(prefix) if str(key).strip())
        return object_keys
