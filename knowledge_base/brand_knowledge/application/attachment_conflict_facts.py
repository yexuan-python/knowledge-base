from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import unicodedata
from typing import Any


logger = logging.getLogger(__name__)


class AttachmentConflictFactsMixin:
    @staticmethod
    def _normalize_fact_text(value: str) -> str:
        normalized = unicodedata.normalize("NFKC", str(value or ""))
        normalized = " ".join(normalized.replace("\r\n", "\n").replace("\r", "\n").split())
        return normalized.casefold().strip()

    async def _build_attachment_temp_fact_rows(
        self,
        *,
        brand_code: str,
        brand_name: str,
        source_task_id: str,
        source_documents: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if (
            self._deps.embeddings is None
            or self._deps.store is None
            or self._deps.brand_knowledge_facts is None
        ):
            return []

        from knowledge_base.document.ai.facts import extract_facts_from_text, parse_facts_json_response

        source_documents_to_process = [
            source_document
            for source_document in source_documents
            if self._normalize_markdown_text(source_document.get("markdown_text"))
        ]
        total_documents = len(source_documents_to_process)
        if total_documents == 0:
            return []

        deduplicated_rows: list[dict[str, Any]] = []
        seen_hashes: set[str] = set()
        failed_documents: list[dict[str, Any]] = []
        initial_success_count = 0
        initial_failure_count = 0

        for source_document in source_documents_to_process:
            rows, row_hashes, failed = await self._build_attachment_temp_fact_rows_for_source_document(
                brand_code=brand_code,
                brand_name=brand_name,
                source_task_id=source_task_id,
                source_document=source_document,
                seen_hashes=seen_hashes,
                extract_facts_from_text=extract_facts_from_text,
                parse_facts_json_response=parse_facts_json_response,
                retry_round=0,
            )
            if failed:
                initial_failure_count += 1
                failed_documents.append(source_document)
                continue
            initial_success_count += 1
            deduplicated_rows.extend(rows)
            seen_hashes.update(row_hashes)

        retry_success_count = 0
        retry_failure_count = 0
        retried_documents_count = 0
        if initial_failure_count > 0 and initial_failure_count * 3 >= total_documents:
            retried_documents_count = len(failed_documents)
            retry_targets = failed_documents
            failed_documents = []
            logger.info(
                "Attachment temp fact extraction retry triggered brand_code=%s brand_name=%s source_task_id=%s total_documents=%s failed_documents=%s threshold=1/3",
                brand_code,
                brand_name,
                source_task_id,
                total_documents,
                retried_documents_count,
            )
            for source_document in retry_targets:
                rows, row_hashes, failed = await self._build_attachment_temp_fact_rows_for_source_document(
                    brand_code=brand_code,
                    brand_name=brand_name,
                    source_task_id=source_task_id,
                    source_document=source_document,
                    seen_hashes=seen_hashes,
                    extract_facts_from_text=extract_facts_from_text,
                    parse_facts_json_response=parse_facts_json_response,
                    retry_round=1,
                )
                if failed:
                    retry_failure_count += 1
                    failed_documents.append(source_document)
                    continue
                retry_success_count += 1
                deduplicated_rows.extend(rows)
                seen_hashes.update(row_hashes)

        final_success_count = initial_success_count + retry_success_count
        final_failure_count = len(failed_documents)
        logger.info(
            "Attachment temp fact extraction completed brand_code=%s brand_name=%s source_task_id=%s total_documents=%s success_count=%s failure_count=%s initial_success_count=%s initial_failure_count=%s retried_documents_count=%s retry_success_count=%s retry_failure_count=%s deduplicated_fact_rows=%s",
            brand_code,
            brand_name,
            source_task_id,
            total_documents,
            final_success_count,
            final_failure_count,
            initial_success_count,
            initial_failure_count,
            retried_documents_count,
            retry_success_count,
            retry_failure_count,
            len(deduplicated_rows),
        )
        if final_failure_count > 0:
            failed_source_names = [
                str(source_document.get("original_filename") or source_document.get("document_id") or "").strip()
                for source_document in failed_documents
            ]
            logger.warning(
                "Attachment temp fact extraction finished with failures brand_code=%s brand_name=%s source_task_id=%s failed_count=%s failed_source_names=%s",
                brand_code,
                brand_name,
                source_task_id,
                final_failure_count,
                failed_source_names,
            )
        return deduplicated_rows

    async def _build_attachment_temp_fact_rows_for_source_document(
        self,
        *,
        brand_code: str,
        brand_name: str,
        source_task_id: str,
        source_document: dict[str, Any],
        seen_hashes: set[str],
        extract_facts_from_text: Any,
        parse_facts_json_response: Any,
        retry_round: int,
    ) -> tuple[list[dict[str, Any]], set[str], bool]:
        markdown_text = self._normalize_markdown_text(source_document.get("markdown_text"))
        if not markdown_text:
            return [], set(), False

        source_name = str(source_document.get("original_filename") or source_document.get("document_id") or "").strip()
        subcategory = str(source_document.get("subcategory") or "").strip() or None
        try:
            facts_json_str = await extract_facts_from_text(
                markdown_text,
                category=brand_name,
                subcategory=subcategory,
                source_name=source_name,
                settings=self._deps.settings,
            )
            facts_payload = await parse_facts_json_response(
                facts_json_str,
                source_name=source_name,
                settings=self._deps.settings,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Attachment temp fact extraction failed, skipping source document brand_code=%s source_name=%s retry_round=%s error_type=%s error=%s",
                brand_code,
                source_name,
                retry_round,
                exc.__class__.__name__,
                exc,
                exc_info=True,
            )
            return [], set(), True

        local_rows: list[dict[str, Any]] = []
        local_seen_hashes: set[str] = set()
        for item in facts_payload if isinstance(facts_payload, list) else []:
            if not isinstance(item, dict):
                continue
            for value in item.values():
                if isinstance(value, list):
                    raw_values = [str(entry or "").strip() for entry in value if str(entry or "").strip()]
                else:
                    normalized = str(value or "").strip()
                    raw_values = [normalized] if normalized else []
                for fact_text in raw_values:
                    normalized_fact_text = self._normalize_fact_text(fact_text)
                    if not normalized_fact_text:
                        continue
                    fact_hash = hashlib.sha256(f"{brand_code}{normalized_fact_text}".encode("utf-8")).hexdigest()
                    if fact_hash in seen_hashes or fact_hash in local_seen_hashes:
                        continue
                    local_seen_hashes.add(fact_hash)
                    local_rows.append(
                        {
                            "brand_code": brand_code,
                            "brand_name": brand_name,
                            "fact_scope": "attachment_temp",
                            "fact_id": fact_hash,
                            "fact_text": fact_text,
                            "normalized_fact_hash": fact_hash,
                            "source_document_id": str(source_document.get("document_id") or "").strip(),
                            "source_task_id": source_task_id,
                            "source_asset_id": int(source_document.get("asset_id") or 0) or None,
                            "full_knowledge_file_id": None,
                            "version_no": None,
                            "knowledge_date": None,
                            "section_path": None,
                        }
                    )
        return local_rows, local_seen_hashes, False

    async def _sync_attachment_temp_facts(
        self,
        *,
        brand_code: str,
        brand_name: str,
        source_task_id: str,
        source_documents: list[dict[str, Any]],
    ) -> int:
        fact_rows = await self._build_attachment_temp_fact_rows(
            brand_code=brand_code,
            brand_name=brand_name,
            source_task_id=source_task_id,
            source_documents=source_documents,
        )
        if not fact_rows:
            return 0

        vectors = await asyncio.to_thread(
            self._deps.embeddings.embed_documents,
            [row["fact_text"] for row in fact_rows],
        )
        milvus_rows: list[dict[str, Any]] = []
        for row, vector in zip(fact_rows, vectors, strict=True):
            self._deps.brand_knowledge_facts.upsert_fact(**row)
            milvus_rows.append(
                {
                    "fact_id": row["fact_id"],
                    "fact_text": row["fact_text"],
                    "brand_code": row["brand_code"],
                    "brand_name": row["brand_name"],
                    "category": row["brand_name"],
                    "source_document_id": row["source_document_id"],
                    "document_ids": json.dumps([row["source_document_id"]], ensure_ascii=False),
                    "vector": vector,
                }
            )
        self._deps.store.upsert_facts(milvus_rows)
        return len(fact_rows)

    def _cleanup_attachment_temp_facts(
        self,
        *,
        source_task_id: str,
    ) -> int:
        if self._deps.brand_knowledge_facts is None:
            return 0
        temp_rows = self._deps.brand_knowledge_facts.list_by_source_task_id_and_scope(
            source_task_id=source_task_id,
            fact_scope="attachment_temp",
        )
        temp_fact_ids = [
            str(row.get("fact_id") or "").strip()
            for row in temp_rows
            if str(row.get("fact_id") or "").strip()
        ]
        deleted_count = self._deps.brand_knowledge_facts.delete_by_source_task_id_and_scope(
            source_task_id=source_task_id,
            fact_scope="attachment_temp",
        )
        if temp_fact_ids and self._deps.store is not None:
            self._deps.store.delete_facts_by_ids(temp_fact_ids)
        return deleted_count
