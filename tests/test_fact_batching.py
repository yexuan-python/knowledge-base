from __future__ import annotations

import json
import hashlib
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

from tests._stub_utils import ensure_stub_module


def _install_test_stubs() -> None:
    dotenv_stub = ensure_stub_module("dotenv")
    if dotenv_stub is not None:
        dotenv_stub.load_dotenv = lambda *args, **kwargs: None
        sys.modules.setdefault("dotenv", dotenv_stub)

    requests_stub = ensure_stub_module("requests")
    if requests_stub is not None:
        requests_stub.post = lambda *args, **kwargs: None
        requests_stub.get = lambda *args, **kwargs: None
        sys.modules.setdefault("requests", requests_stub)

    dashscope_stub = ensure_stub_module("dashscope")
    if dashscope_stub is not None:
        dashscope_stub.Generation = type("Generation", (), {})
        dashscope_stub.TextEmbedding = type("TextEmbedding", (), {})
        dashscope_stub.MultiModalEmbedding = type("MultiModalEmbedding", (), {})
        dashscope_stub.MultiModalConversation = type("MultiModalConversation", (), {})
        sys.modules.setdefault("dashscope", dashscope_stub)

    pil_stub = ensure_stub_module("PIL", is_package=True)
    if pil_stub is not None:
        pil_image = types.SimpleNamespace(
            Resampling=types.SimpleNamespace(LANCZOS="LANCZOS"),
            open=lambda *args, **kwargs: None,
        )
        pil_stub.Image = pil_image
        sys.modules.setdefault("PIL", pil_stub)


_install_test_stubs()

from knowledge_base.document.application.service import (
    DocumentApplicationDependencies,
    DocumentApplicationService,
)
from knowledge_base.document.application import service as document_application_service


class FakeDocumentRegistryStore:
    def __init__(self) -> None:
        self.ai_status_updates: list[dict[str, str]] = []

    def update_document_ai_status(self, **kwargs) -> None:
        self.ai_status_updates.append(kwargs)

    def get_document_registry_record(self, *, category: str, file_hash: str):
        return {
            "document_id": "doc-stub",
            "upload_task_id": None,
            "facts_status": "success",
        }


class FakeDocumentCategoryStore:
    def document_exists(self, document_id: str) -> bool:
        return True

    def get_latest_document_ids_by_category(self, category: str) -> list[str]:
        return ["legacy-doc"]


class FakeStore:
    def __init__(self, existing_map: dict[str, dict] | None = None) -> None:
        self.existing_map = existing_map or {}
        self.get_facts_by_ids_calls: list[list[str]] = []
        self.upsert_facts_calls: list[dict[str, object]] = []
        self.search_facts_calls: list[dict[str, object]] = []

    def get_facts_by_ids(self, fact_ids: list[str]) -> dict[str, dict]:
        self.get_facts_by_ids_calls.append(list(fact_ids))
        return {
            fact_id: self.existing_map[fact_id]
            for fact_id in fact_ids
            if fact_id in self.existing_map
        }

    def upsert_facts(self, facts_data: list[dict], *, partial_update: bool = False) -> None:
        self.upsert_facts_calls.append(
            {
                "facts_data": facts_data,
                "partial_update": partial_update,
            }
        )

    def search_facts(
        self,
        query_vector: list[float],
        category: str,
        top_k: int,
        *,
        source_document_id: str | None = None,
        brand_code: str | None = None,
        product_code: str | None = None,
    ) -> list[dict]:
        self.search_facts_calls.append(
            {
                "query_vector": query_vector,
                "category": category,
                "top_k": top_k,
                "source_document_id": source_document_id,
                "brand_code": brand_code,
                "product_code": product_code,
            }
        )
        return [
            {
                "entity": {
                    "fact_text": "品牌提供企业法律顾问服务",
                    "brand_code": brand_code or "",
                    "brand_name": category,
                    "product_code": product_code or "",
                    "product_name": "产品A" if product_code else "",
                    "document_ids": json.dumps(["kb-latest", "old-doc"], ensure_ascii=False),
                },
                "distance": 0.91,
            }
        ]


class FakeEmbeddingService:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[float(index + 1)] for index, _ in enumerate(texts)]

    def embed_query(self, text: str) -> list[float]:
        return [float(len(text))]


class FakeOSSClient:
    enabled = False


class FakeBrandStore:
    def get_brand_by_name(self, brand_name: str) -> dict | None:
        if brand_name != "示例品牌":
            return None
        return {"id": 100, "brand_code": "DEMO", "brand_name": "示例品牌"}

    def get_brand_by_id(self, brand_id: int) -> dict | None:
        if brand_id != 100:
            return None
        return {"id": 100, "brand_code": "DEMO", "brand_name": "示例品牌"}

    def get_brand_by_code(self, brand_code: str) -> dict | None:
        if brand_code != "DEMO":
            return None
        return {"id": 100, "brand_code": "DEMO", "brand_name": "示例品牌"}


class FakeBrandProductStore:
    def get_by_product_code(self, *, product_code: str) -> dict | None:
        if product_code != "PROD-001":
            return None
        return {
            "brand_id": 100,
            "brand_code": "DEMO",
            "brand_name": "示例品牌",
            "product_code": "PROD-001",
            "product_name": "产品A",
        }


class FakeBrandFullKnowledgeStore:
    def __init__(self, document_id: str | None = "kb-latest") -> None:
        self.document_id = document_id

    def get_latest_by_brand_code(self, *, brand_code: str) -> dict | None:
        if brand_code != "DEMO" or not self.document_id:
            return None
        return {"document_id": self.document_id}


def build_document_application(
    *,
    existing_map: dict[str, dict] | None = None,
    brand_full_knowledge: FakeBrandFullKnowledgeStore | None = None,
) -> DocumentApplicationService:
    return DocumentApplicationService(
        DocumentApplicationDependencies(
            settings=None,
            store=FakeStore(existing_map=existing_map),
            embeddings=FakeEmbeddingService(),
            document_categories=FakeDocumentCategoryStore(),
            document_registry=FakeDocumentRegistryStore(),
            fact_relations=types.SimpleNamespace(
                replace_document_fact_relations=lambda *args, **kwargs: None,
            ),
            oss_client=FakeOSSClient(),
            get_document_info=lambda _document_id: {"source_name": "测试文档"},
            get_full_text=lambda _document_id: None,
            notify_ai_failure_if_ready=_noop_async,
            finalize_task_callback_from_document=_noop_async,
            brands=FakeBrandStore(),
            brand_products=FakeBrandProductStore(),
            brand_full_knowledge=brand_full_knowledge or FakeBrandFullKnowledgeStore(),
        )
    )


async def _noop_async(*args, **kwargs) -> None:
    return None


class FactBatchingTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_facts_are_embedded_in_one_batch(self) -> None:
        application = build_document_application()

        facts_json = json.dumps(
            [
                {"facts": ["事实A", "事实B", "事实A"]},
                {"facts": ["事实C"]},
            ],
            ensure_ascii=False,
        )

        with patch.object(
            document_application_service,
            "extract_facts_from_text",
            AsyncMock(return_value=facts_json),
        ):
            await application.generate_and_save_facts(
                document_id="doc-1",
                category="品牌A",
                file_hash="hash-1",
                text="正文",
            )

        self.assertEqual(application._deps.embeddings.calls, [["事实A", "事实B", "事实C"]])
        self.assertEqual(len(application._deps.store.get_facts_by_ids_calls), 1)
        self.assertEqual(len(application._deps.store.upsert_facts_calls), 1)
        first_call = application._deps.store.upsert_facts_calls[0]
        self.assertFalse(first_call["partial_update"])
        self.assertEqual(len(first_call["facts_data"]), 3)

    async def test_fenced_json_with_trailing_commas_is_recovered(self) -> None:
        application = build_document_application()
        facts_json = """```json
[
  {"facts": ["事实A", "事实B",]},
  {"facts": "事实C",},
]
```"""

        with patch.object(
            document_application_service,
            "extract_facts_from_text",
            AsyncMock(return_value=facts_json),
        ):
            await application.generate_and_save_facts(
                document_id="doc-1",
                category="品牌A",
                file_hash="hash-1",
                text="正文",
            )

        self.assertEqual(application._deps.embeddings.calls, [["事实A", "事实B", "事实C"]])
        self.assertEqual(len(application._deps.store.upsert_facts_calls), 1)

    async def test_json_wrapped_by_explanation_text_is_recovered(self) -> None:
        application = build_document_application()
        facts_json = """以下是提取结果：
[
  {"facts": ["事实A"]},
  {"facts": ["事实B"]}
]
请查收。"""

        with patch.object(
            document_application_service,
            "extract_facts_from_text",
            AsyncMock(return_value=facts_json),
        ):
            await application.generate_and_save_facts(
                document_id="doc-1",
                category="品牌A",
                file_hash="hash-1",
                text="正文",
            )

        self.assertEqual(application._deps.embeddings.calls, [["事实A", "事实B"]])
        self.assertEqual(len(application._deps.store.upsert_facts_calls), 1)

    async def test_existing_facts_update_document_ids_without_reembedding(self) -> None:
        fact_id = hashlib.sha256("事实A".encode("utf-8")).hexdigest()
        existing_map = {
            fact_id: {
                "fact_id": fact_id,
                "fact_text": "事实A",
                "category": "品牌A",
                "document_ids": json.dumps(["doc-old"], ensure_ascii=False),
                "vector": [0.1, 0.2],
            }
        }
        application = build_document_application(existing_map=existing_map)

        facts_json = json.dumps([{"facts": ["事实A"]}], ensure_ascii=False)

        with patch.object(
            document_application_service,
            "extract_facts_from_text",
            AsyncMock(return_value=facts_json),
        ):
            await application.generate_and_save_facts(
                document_id="doc-2",
                category="品牌A",
                file_hash="hash-2",
                text="正文",
            )

        self.assertEqual(application._deps.embeddings.calls, [])
        self.assertEqual(len(application._deps.store.upsert_facts_calls), 1)
        first_call = application._deps.store.upsert_facts_calls[0]
        self.assertTrue(first_call["partial_update"])
        updated = first_call["facts_data"][0]
        self.assertEqual(json.loads(updated["document_ids"]), ["doc-old", "doc-2"])
        self.assertEqual(updated["vector"], [0.1, 0.2])

    async def test_search_facts_by_category_queries_brand_facts_without_latest_document_filter(self) -> None:
        application = build_document_application()

        result = await application.search_facts_by_category("示例品牌", "法律顾问", 5)

        self.assertEqual(len(result), 1)
        self.assertIsNone(application._deps.store.search_facts_calls[0]["source_document_id"])
        self.assertEqual(
            application._deps.store.search_facts_calls[0]["brand_code"],
            "DEMO",
        )
        self.assertEqual(result[0]["document_count"], 2)

    async def test_search_facts_by_category_without_latest_brand_knowledge_keeps_brand_code_filter(self) -> None:
        application = build_document_application(brand_full_knowledge=FakeBrandFullKnowledgeStore(document_id=None))

        result = await application.search_facts_by_category("示例品牌", "法律顾问", 5)

        self.assertEqual(len(result), 1)
        self.assertEqual(
            application._deps.store.search_facts_calls[0],
            {
                "query_vector": [4.0],
                "category": "示例品牌",
                "top_k": 5,
                "source_document_id": None,
                "brand_code": "DEMO",
                "product_code": None,
            },
        )
        self.assertEqual(result[0]["document_count"], 2)

    async def test_search_facts_with_product_code_resolves_brand_without_product_filter(self) -> None:
        application = build_document_application()

        result = await application.search_facts(
            product_code="PROD-001",
            query="法律顾问",
            top_k=5,
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(
            application._deps.store.search_facts_calls[0],
            {
                "query_vector": [4.0],
                "category": "示例品牌",
                "top_k": 5,
                "source_document_id": None,
                "brand_code": "DEMO",
                "product_code": None,
            },
        )
        self.assertEqual(
            result[0]["metadata"],
            {
                "brand_code": "DEMO",
                "brand_name": "示例品牌",
                "product_code": None,
                "product_name": None,
            },
        )

    async def test_search_facts_by_category_matched_without_latest_brand_knowledge_returns_temp_document_ids(self) -> None:
        application = build_document_application(brand_full_knowledge=FakeBrandFullKnowledgeStore(document_id=None))

        result = await application.search_facts_by_category_matched("示例品牌", "法律顾问", 5)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["document_ids"], ["kb-latest", "old-doc"])


if __name__ == "__main__":
    unittest.main()
