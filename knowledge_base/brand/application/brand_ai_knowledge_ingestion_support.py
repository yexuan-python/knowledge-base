from __future__ import annotations

import asyncio
import hashlib
import json
import unicodedata
from pathlib import Path
from typing import Any

from knowledge_base.ingest.application.remote_download import download_remote_content_to_temp_file
from knowledge_base.shared.utils import (
    build_brand_ai_knowledge_markdown_object_key,
    build_brand_ai_knowledge_pdf_object_key,
)


class BrandAiKnowledgeIngestionSupportMixin:
    @staticmethod
    def _compute_sha256_for_path(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as file_obj:
            for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
                if not chunk:
                    continue
                digest.update(chunk)
        return digest.hexdigest()

    async def _prepare_source_file(
        self,
        *,
        filename: str,
        staged_path: Path | None,
        source_url: str | None,
        content_type: str | None,
        brand_code: str,
    ) -> tuple[Path, str, int, bool]:
        if staged_path is not None and staged_path.exists():
            return (
                staged_path,
                self._normalize_content_type(filename=filename, content_type=content_type),
                staged_path.stat().st_size,
                False,
            )
        if not source_url:
            raise ValueError("正式知识库文件缺少 source_url")
        temp_path, downloaded_content_type, downloaded_size = await download_remote_content_to_temp_file(
            url=source_url,
            name=filename,
            log_context=f"brand_ai_knowledge:{brand_code}",
        )
        return (
            temp_path,
            self._normalize_content_type(filename=filename, content_type=content_type or downloaded_content_type),
            downloaded_size,
            True,
        )

    @staticmethod
    def _normalize_content_type(*, filename: str, content_type: str | None) -> str:
        normalized = str(content_type or "").strip()
        if normalized:
            return normalized
        suffix = Path(filename).suffix.lower()
        if suffix == ".md":
            return "text/markdown"
        if suffix == ".pdf":
            return "application/pdf"
        return "application/octet-stream"

    @staticmethod
    def _is_reusable_same_content_row(row: dict[str, Any]) -> bool:
        status = str(row.get("ingest_status") or "").strip().lower()
        if status and status != "success":
            return False
        return bool(row.get("document_id") or row.get("oss_key") or row.get("oss_url"))

    @staticmethod
    def _normalize_markdown_text(value: Any) -> str:
        text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
        text = unicodedata.normalize("NFKC", text)
        lines = [line.rstrip() for line in text.split("\n")]
        return "\n".join(lines).strip()

    @staticmethod
    def _normalize_uploaded_markdown_text(value: Any) -> str:
        text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
        lines = [line.rstrip() for line in text.split("\n")]
        return "\n".join(lines).strip()

    @staticmethod
    def _build_job_id(*, task_id: str, upload_task_file_id: int) -> str:
        return f"brand-ai-kb:{task_id}:{upload_task_file_id}"[:128]

    @staticmethod
    def _build_document_id(*, brand_code: str, version_no: int, knowledge_date: str, revision_no: int) -> str:
        return f"brandkb:{brand_code}:V{version_no}:{knowledge_date}:R{revision_no}"[:128]

    @staticmethod
    def _build_markdown_file_name(*, brand_name: str, version_no: int, knowledge_date: str) -> str:
        return f"【{brand_name}】品牌AI知识库_V{version_no}_{knowledge_date}.md"

    @staticmethod
    def _build_pdf_file_name(markdown_file_name: str) -> str:
        if markdown_file_name.lower().endswith(".md"):
            return f"{markdown_file_name[:-3]}.pdf"
        return f"{markdown_file_name}.pdf"

    async def _upload_markdown_file(
        self,
        *,
        brand_name: str,
        filename: str,
        markdown_text: str,
    ) -> tuple[str, str]:
        markdown_oss_key = build_brand_ai_knowledge_markdown_object_key(brand_name=brand_name, filename=filename)
        uploaded_key = await asyncio.to_thread(
            self._deps.oss_client.upload_bytes,
            markdown_text.encode("utf-8"),
            markdown_oss_key,
            "text/markdown; charset=utf-8",
        )
        if not uploaded_key:
            raise ValueError(f"正式知识库 Markdown 上传 OSS 失败: {filename}")
        markdown_oss_url = self._deps.oss_client.build_object_url(uploaded_key)
        return uploaded_key, str(markdown_oss_url or "")

    async def _render_pdf(self, *, markdown_text: str, title: str) -> bytes:
        from knowledge_base.brand.full_markdown import render_brand_full_knowledge_pdf_bytes

        return await render_brand_full_knowledge_pdf_bytes(
            markdown_text,
            title=title,
            settings=self._deps.settings,
        )

    async def _upload_pdf_file(
        self,
        *,
        brand_name: str,
        filename: str,
        pdf_bytes: bytes,
    ) -> tuple[str, str]:
        pdf_oss_key = build_brand_ai_knowledge_pdf_object_key(brand_name=brand_name, filename=filename)
        uploaded_key = await asyncio.to_thread(
            self._deps.oss_client.upload_bytes,
            pdf_bytes,
            pdf_oss_key,
            "application/pdf",
        )
        if not uploaded_key:
            raise ValueError(f"正式知识库 PDF 上传 OSS 失败: {filename}")
        pdf_oss_url = self._deps.oss_client.build_object_url(uploaded_key)
        return uploaded_key, str(pdf_oss_url or "")

    async def _write_document_chunks(
        self,
        *,
        document_id: str,
        brand_code: str,
        brand_name: str,
        source_name: str,
        source_url: str,
        markdown_text: str,
        version_no: int,
        knowledge_date: str,
        revision_no: int,
        full_knowledge_file_id: int,
        content_hash: str,
    ) -> None:
        from knowledge_base.ingest.infrastructure.chunking import build_chunks

        chunk_size = int(getattr(self._deps.settings, "chunk_size", 1200) or 1200)
        chunk_overlap = int(getattr(self._deps.settings, "chunk_overlap", 100) or 100)
        chunks = build_chunks(markdown_text, document_id=document_id, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        if not chunks:
            raise ValueError("正式知识库 Markdown 切块结果为空")
        vectors = await asyncio.to_thread(self._deps.embeddings.embed_documents, [chunk.text for chunk in chunks])
        metadata = {
            "brand_code": brand_code,
            "brand_name": brand_name,
            "category": brand_name,
            "source_url": source_url,
            "kb_version": f"V{version_no}",
            "version_no": version_no,
            "knowledge_date": knowledge_date,
            "revision_no": revision_no,
            "full_knowledge_file_id": full_knowledge_file_id,
            "content_hash": content_hash,
            "source_type": "brand_ai_knowledge",
        }
        rows = [
            {
                "id": chunk.chunk_id,
                "document_id": document_id,
                "source_name": source_name,
                "source_type": "brand_ai_knowledge",
                "brand_code": brand_code,
                "brand_name": brand_name,
                "product_code": None,
                "product_name": None,
                "chunk_index": chunk.chunk_index,
                "text": chunk.text,
                "metadata_json": json.dumps(metadata, ensure_ascii=False),
                "vector": vector,
            }
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        self._deps.store.insert_chunks(
            document_id=document_id,
            source_name=source_name,
            source_type="brand_ai_knowledge",
            chunk_payloads=rows,
        )

    async def _build_fact_rows(
        self,
        *,
        brand_code: str,
        brand_name: str,
        source_document_id: str,
        full_knowledge_file_id: int,
        version_no: int,
        knowledge_date: str,
        source_name: str,
        markdown_text: str,
    ) -> list[dict[str, Any]]:
        from knowledge_base.document.ai.facts import extract_facts_from_text, parse_facts_json_response

        facts_json_str = await extract_facts_from_text(
            markdown_text,
            category=brand_name,
            source_name=source_name,
            settings=self._deps.settings,
        )
        facts_payload = await parse_facts_json_response(
            facts_json_str,
            source_name=source_name,
            settings=self._deps.settings,
        )
        raw_fact_texts: list[str] = []
        for item in facts_payload if isinstance(facts_payload, list) else []:
            if not isinstance(item, dict):
                continue
            for value in item.values():
                if isinstance(value, list):
                    raw_fact_texts.extend(str(entry or "").strip() for entry in value if str(entry or "").strip())
                else:
                    normalized = str(value or "").strip()
                    if normalized:
                        raw_fact_texts.append(normalized)

        deduplicated_rows: list[dict[str, Any]] = []
        seen_hashes: set[str] = set()
        for fact_text in raw_fact_texts:
            normalized_fact_text = self._normalize_fact_text(fact_text)
            if not normalized_fact_text:
                continue
            fact_hash = hashlib.sha256(f"{brand_code}{normalized_fact_text}".encode("utf-8")).hexdigest()
            if fact_hash in seen_hashes:
                continue
            seen_hashes.add(fact_hash)
            deduplicated_rows.append(
                {
                    "brand_code": brand_code,
                    "brand_name": brand_name,
                    "fact_scope": "official_kb",
                    "fact_id": fact_hash,
                    "fact_text": fact_text,
                    "normalized_fact_hash": fact_hash,
                    "source_document_id": source_document_id,
                    "source_task_id": None,
                    "source_asset_id": None,
                    "full_knowledge_file_id": full_knowledge_file_id,
                    "version_no": version_no,
                    "knowledge_date": knowledge_date,
                    "section_path": None,
                }
            )
        return deduplicated_rows

    @staticmethod
    def _normalize_fact_text(value: str) -> str:
        normalized = unicodedata.normalize("NFKC", str(value or ""))
        normalized = " ".join(normalized.replace("\r\n", "\n").replace("\r", "\n").split())
        return normalized.casefold().strip()

    async def _upsert_facts(self, fact_rows: list[dict[str, Any]]) -> None:
        if not fact_rows:
            return
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
                    "product_code": row.get("product_code"),
                    "product_name": row.get("product_name"),
                    "category": row["brand_name"],
                    "source_document_id": row["source_document_id"],
                    "document_ids": json.dumps([row["source_document_id"]], ensure_ascii=False),
                    "vector": vector,
                }
            )
        self._deps.store.upsert_facts(milvus_rows)

    def _cleanup_old_versions(self, *, brand_code: str, keep_document_id: str) -> dict[str, Any]:
        old_document_ids = self._deps.brand_full_knowledge.list_old_document_ids(
            brand_code=brand_code,
            keep_document_id=keep_document_id,
        )
        if old_document_ids:
            self._deps.store.delete_documents_by_ids(old_document_ids)

        stale_fact_rows = self._deps.brand_knowledge_facts.list_by_brand_code(brand_code=brand_code)
        stale_fact_ids = [
            str(row.get("fact_id") or "").strip()
            for row in stale_fact_rows
            if str(row.get("source_document_id") or "").strip() != keep_document_id and str(row.get("fact_id") or "").strip()
        ]
        deleted_fact_count = self._deps.brand_knowledge_facts.delete_by_brand_code_excluding_document(
            brand_code=brand_code,
            keep_document_id=keep_document_id,
        )
        if stale_fact_ids:
            self._deps.store.delete_facts_by_ids(stale_fact_ids)
        return {
            "deleted_document_count": len(old_document_ids),
            "deleted_fact_count": deleted_fact_count,
        }

    def _cleanup_old_facts(self, *, brand_code: str, keep_document_id: str) -> dict[str, Any]:
        stale_fact_rows = self._deps.brand_knowledge_facts.list_by_brand_code(brand_code=brand_code)
        stale_fact_ids = [
            str(row.get("fact_id") or "").strip()
            for row in stale_fact_rows
            if str(row.get("source_document_id") or "").strip() != keep_document_id and str(row.get("fact_id") or "").strip()
        ]
        deleted_fact_count = self._deps.brand_knowledge_facts.delete_by_brand_code_excluding_document(
            brand_code=brand_code,
            keep_document_id=keep_document_id,
        )
        if stale_fact_ids:
            self._deps.store.delete_facts_by_ids(stale_fact_ids)
        return {
            "deleted_fact_count": deleted_fact_count,
        }

    @staticmethod
    def _build_facts_only_document_id(*, brand_code: str, content_hash: str) -> str:
        return f"brandfacts:{brand_code}:{content_hash[:32]}"[:128]
