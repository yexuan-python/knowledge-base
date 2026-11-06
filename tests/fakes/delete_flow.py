from __future__ import annotations


class FakeDeleteOSSClient:
    enabled = True

    def __init__(self, object_keys: list[str]) -> None:
        self.object_keys = list(object_keys)
        self.deleted_keys: list[str] = []

    def list_object_keys(self, prefix: str, *, suffix: str | None = None, max_keys: int = 1000):
        return [
            key for key in self.object_keys
            if key.startswith(prefix) and (not suffix or key.endswith(suffix))
        ]

    def delete_object(self, object_key: str) -> bool:
        self.deleted_keys.append(object_key)
        return True


class FakeAiKnowledgeOSSClient(FakeDeleteOSSClient):
    def build_object_url(self, object_key: str) -> str:
        return f"https://oss.example.com/{object_key}"


class FakeDeleteDocumentSummaries:
    def get_summaries_by_category(self, category: str):
        return [{"document_id": "doc-1"}]


class FakeDeleteFactRelations:
    def count_document_fact_relations(self, document_ids: list[str]) -> int:
        return len(document_ids)


class FakeDeleteVectorStore:
    def __init__(self) -> None:
        self.deleted_brand_fact_codes: list[str] = []

    def get_documents_info_by_ids(self, document_ids: list[str]):
        return [{"document_id": document_id, "metadata_json": {}} for document_id in document_ids]

    def delete_facts_by_brand_code(self, brand_code: str) -> None:
        self.deleted_brand_fact_codes.append(brand_code)


class FakeDeleteDocumentApp:
    def collect_document_object_keys(self, *, document_id: str, doc_info, registry_entry):
        keys = {"fulltext/doc-1.txt"}
        original_file_key = str((registry_entry or {}).get("original_file_key") or "").strip()
        if original_file_key:
            keys.add(original_file_key)
        return keys


class FakeDeleteBrandKnowledgeSessions:
    def __init__(self, *, session_count: int = 2, round_count: int = 3) -> None:
        self.session_count = session_count
        self.round_count = round_count
        self.deleted_calls: list[dict[str, object]] = []

    def count_by_brand_identifier(self, *, brand_code: str | None, brand_name: str | None) -> dict[str, int]:
        if brand_code == "BRAND-001" or brand_name == "示例品牌":
            return {
                "brand_knowledge_sessions": self.session_count,
                "brand_knowledge_session_rounds": self.round_count,
            }
        return {
            "brand_knowledge_sessions": 0,
            "brand_knowledge_session_rounds": 0,
        }

    def delete_by_brand_identifier(self, *, brand_code: str | None, brand_name: str | None) -> dict[str, int]:
        self.deleted_calls.append(
            {
                "brand_code": brand_code,
                "brand_name": brand_name,
            }
        )
        return self.count_by_brand_identifier(brand_code=brand_code, brand_name=brand_name)


class FakeDeleteAttachmentAssets:
    def __init__(self) -> None:
        self.rows = [
            {
                "oss_key": "test/BRAND-001/attachments/doc.pdf/abc123.pdf",
                "fulltext_key": "test/BRAND-001/attachments/doc.pdf/V1.md",
            }
        ]
        self.deleted_brand_codes: list[str] = []

    def list_by_brand_code(self, *, brand_code: str, limit: int = 100):
        if brand_code != "BRAND-001":
            return []
        return list(self.rows[:limit])

    def delete_by_brand_code(self, *, brand_code: str) -> int:
        self.deleted_brand_codes.append(brand_code)
        deleted_count = len(self.rows) if brand_code == "BRAND-001" else 0
        self.rows = []
        return deleted_count


class FakeDeleteBrandFactsStore:
    def __init__(self) -> None:
        self.deleted_brand_codes: list[str] = []

    def count_by_brand_code(self, *, brand_code: str) -> int:
        return 2 if brand_code == "BRAND-001" else 0

    def delete_by_brand_code(self, *, brand_code: str) -> int:
        self.deleted_brand_codes.append(brand_code)
        return 2 if brand_code == "BRAND-001" else 0


class FakeDeleteBrandKnowledgeIngestionJobs:
    def __init__(self, *, count: int = 2) -> None:
        self.count = count
        self.deleted_brand_codes: list[str] = []

    def count_by_brand_code(self, *, brand_code: str) -> int:
        return self.count if brand_code == "BRAND-001" else 0

    def delete_by_brand_code(self, *, brand_code: str) -> int:
        self.deleted_brand_codes.append(brand_code)
        return self.count if brand_code == "BRAND-001" else 0


class FakeDeleteBackgroundJobs:
    def __init__(self, *, count: int = 3) -> None:
        self.count = count
        self.deleted_calls: list[dict[str, object]] = []

    def count_by_brand_identifier(
        self,
        *,
        brand_code: str | None,
        brand_name: str | None,
        source_ids: list[str] | None = None,
    ) -> int:
        if brand_code == "BRAND-001" or brand_name == "示例品牌":
            return self.count
        return 0

    def delete_by_brand_identifier(
        self,
        *,
        brand_code: str | None,
        brand_name: str | None,
        source_ids: list[str] | None = None,
    ) -> int:
        self.deleted_calls.append(
            {
                "brand_code": brand_code,
                "brand_name": brand_name,
                "source_ids": list(source_ids or []),
            }
        )
        return self.count_by_brand_identifier(
            brand_code=brand_code,
            brand_name=brand_name,
            source_ids=source_ids,
        )
