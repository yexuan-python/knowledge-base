from __future__ import annotations

import io
import importlib.util
import types
import unittest

FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None

if FASTAPI_AVAILABLE:
    from fastapi.testclient import TestClient

    from knowledge_base.api_app.app import create_app
    from knowledge_base.api_app.routers import documents as documents_router_module
    from knowledge_base.infrastructure.embedding import EmbeddingRateLimitedError
    from knowledge_base.upload_task.schemas import UploadTaskCreateResponse


class StubKnowledgeBaseService:
    def __init__(
        self,
        *,
        search_result: list[dict] | None = None,
        brand_facts_ingest_result: dict | None = None,
        brand_facts_ingest_error: Exception | None = None,
        brand_facts_error: Exception | None = None,
        search_error: Exception | None = None,
        image_search_error: Exception | None = None,
        upload_result: UploadTaskCreateResponse | None = None,
        upload_error: Exception | None = None,
    ) -> None:
        self.search_result = search_result or []
        self.search_error = search_error
        self.search_calls: list[dict] = []
        self.image_search_result: list[dict] = []
        self.image_search_error = image_search_error
        self.image_search_calls: list[dict] = []
        self.brand_facts_result: list[dict] = []
        self.brand_facts_calls: list[dict] = []
        self.brand_facts_ingest_result = brand_facts_ingest_result or {}
        self.brand_facts_ingest_error = brand_facts_ingest_error
        self.brand_facts_error = brand_facts_error
        self.upload_result = upload_result
        self.upload_error = upload_error
        self.brand_facts_ingest_calls: list[dict] = []
        self.upload_calls: list[dict] = []
        self.start_calls = 0
        self.stop_calls = 0

    async def start(self) -> None:
        self.start_calls += 1

    async def stop(self) -> None:
        self.stop_calls += 1

    async def search(self, request) -> list[dict]:
        self.search_calls.append(request.model_dump())
        if self.search_error is not None:
            raise self.search_error
        return list(self.search_result)

    async def search_images(self, request) -> list[dict]:
        self.image_search_calls.append(request.model_dump())
        if self.image_search_error is not None:
            raise self.image_search_error
        return list(self.image_search_result)

    async def search_facts(
        self,
        *,
        brand_code: str | None = None,
        brand_name: str | None = None,
        category: str | None = None,
        product_code: str | None = None,
        query: str | None,
        top_k: int,
    ) -> list[dict]:
        self.brand_facts_calls.append(
            {
                "brand_code": brand_code,
                "brand_name": brand_name,
                "category": category,
                "product_code": product_code,
                "query": query,
                "top_k": top_k,
            }
        )
        if self.brand_facts_error is not None:
            raise self.brand_facts_error
        return list(self.brand_facts_result)

    async def ingest_brand_facts_only(
        self,
        *,
        files,
        metadata: dict,
    ) -> dict:
        self.brand_facts_ingest_calls.append(
            {
                "file_names": [getattr(file, "filename", None) for file in files],
                "metadata": metadata,
            }
        )
        if self.brand_facts_ingest_error is not None:
            raise self.brand_facts_ingest_error
        return dict(self.brand_facts_ingest_result)

    async def enqueue_upload_task(
        self,
        *,
        files,
        metadata: dict,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
    ) -> UploadTaskCreateResponse:
        self.upload_calls.append(
            {
                "file_names": [getattr(file, "filename", None) for file in files],
                "metadata": metadata,
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
            }
        )
        if self.upload_error is not None:
            raise self.upload_error
        return self.upload_result or UploadTaskCreateResponse(
            task_id="task-document-upload",
            status="queued",
            file_count=len(files),
            message="文件已上传成功，后台任务正在排队处理",
        )


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is required for route tests")
class SearchRouteTests(unittest.TestCase):
    def _build_client(self, service: StubKnowledgeBaseService) -> TestClient:
        settings = types.SimpleNamespace(dashscope_api_key="test-key")
        app = create_app(settings=settings, service=service)
        app.dependency_overrides[documents_router_module.get_service] = lambda: service
        return TestClient(app)

    def test_search_returns_wrapped_results(self) -> None:
        service = StubKnowledgeBaseService(
            search_result=[
                {
                    "chunk_id": "100003_20260629_041_001",
                    "content": "炜衡密云分所提供企业常年法律顾问服务。",
                    "score": 0.88,
                    "category": "炜衡密云分所",
                    "metadata": {
                        "brand_id": 100003,
                        "brand_name": "炜衡密云分所",
                        "kb_version": "2026-06-29-001",
                        "section_title": "4.1 企业法律顾问服务",
                        "source_url": "https://example.com/brand-kb/100003/20260629.md",
                        "content_hash": "sha256:demo",
                    },
                }
            ]
        )

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/search",
                json={
                    "query": "炜衡密云分所 北京 密云 企业法律顾问 本地服务 服务能力",
                    "top_k": 5,
                    "category": "炜衡密云分所",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "code": 0,
                "message": "ok",
                "data": [
                    {
                        "chunk_id": "100003_20260629_041_001",
                        "content": "炜衡密云分所提供企业常年法律顾问服务。",
                        "score": 0.88,
                        "brand_name": "炜衡密云分所",
                        "category": "炜衡密云分所",
                        "metadata": {
                            "brand_id": 100003,
                            "brand_name": "炜衡密云分所",
                            "kb_version": "2026-06-29-001",
                            "section_title": "4.1 企业法律顾问服务",
                            "source_url": "https://example.com/brand-kb/100003/20260629.md",
                            "content_hash": "sha256:demo",
                        },
                    }
                ],
            },
        )
        self.assertEqual(
            service.search_calls,
            [
                {
                    "query": "炜衡密云分所 北京 密云 企业法律顾问 本地服务 服务能力",
                    "top_k": 5,
                    "document_ids": None,
                    "source_types": None,
                    "brand_code": None,
                    "brand_name": None,
                    "category": "炜衡密云分所",
                    "product_code": None,
                    "subcategory": None,
                }
            ],
        )
        self.assertEqual(service.start_calls, 1)
        self.assertEqual(service.stop_calls, 1)

    def test_documents_upload_maps_missing_brand_metadata_to_400(self) -> None:
        service = StubKnowledgeBaseService(
            upload_error=ValueError(
                "/api/v1/documents/upload 仅支持品牌附件和正式品牌 AI 知识库文件；metadata 必须包含 category、brand_code、brand_name"
            )
        )

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/documents/upload",
                data={"metadata": '{"category":"示例品牌"}'},
                files={"files": ("brand-book.pdf", io.BytesIO(b"pdf-bytes"), "application/pdf")},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {
                "detail": "/api/v1/documents/upload 仅支持品牌附件和正式品牌 AI 知识库文件；metadata 必须包含 category、brand_code、brand_name"
            },
        )
        self.assertEqual(
            service.upload_calls,
            [
                {
                    "file_names": ["brand-book.pdf"],
                    "metadata": {"category": "示例品牌"},
                    "chunk_size": None,
                    "chunk_overlap": None,
                }
            ],
        )

    def test_image_search_returns_asset_friendly_results(self) -> None:
        service = StubKnowledgeBaseService()
        service.image_search_result = [
            {
                "asset_id": 21,
                "document_id": "asset_21",
                "score": 0.93,
                "brand_code": "BRAND-001",
                "brand_name": "示例品牌",
                "subcategory": "橱柜",
                "original_filename": "厨房场景图.png",
                "oss_url": "https://oss.example.com/brand/image.png",
                "source_url": "https://example.com/kitchen.png",
                "content_type": "image/png",
                "file_size": 12345,
                "image_summary": "现代厨房橱柜场景图",
                "image_tags": ["厨房", "橱柜"],
            }
        ]

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/images/search",
                json={
                    "query": "厨房橱柜",
                    "top_k": 10,
                    "brand_name": "示例品牌",
                    "subcategory": "橱柜",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "code": 0,
                "message": "ok",
                "data": [
                    {
                        "asset_id": 21,
                        "document_id": "asset_21",
                        "score": 0.93,
                        "brand_code": "BRAND-001",
                        "brand_name": "示例品牌",
                        "subcategory": "橱柜",
                        "original_filename": "厨房场景图.png",
                        "oss_url": "https://oss.example.com/brand/image.png",
                        "source_url": "https://example.com/kitchen.png",
                        "content_type": "image/png",
                        "file_size": 12345,
                        "image_summary": "现代厨房橱柜场景图",
                        "image_tags": ["厨房", "橱柜"],
                    }
                ],
            },
        )
        self.assertEqual(
            service.image_search_calls,
            [
                {
                    "query": "厨房橱柜",
                    "top_k": 10,
                    "document_ids": None,
                    "brand_code": None,
                    "brand_name": "示例品牌",
                    "category": None,
                    "product_code": None,
                    "subcategory": "橱柜",
                }
            ],
        )

    def test_search_accepts_brand_code_and_product_code(self) -> None:
        service = StubKnowledgeBaseService(search_result=[])

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/search",
                json={
                    "query": "售后服务标准",
                    "top_k": 5,
                    "brand_code": "BRAND-001",
                    "product_code": "PROD-001",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            service.search_calls,
            [
                {
                    "query": "售后服务标准",
                    "top_k": 5,
                    "document_ids": None,
                    "source_types": None,
                    "brand_code": "BRAND-001",
                    "brand_name": None,
                    "category": None,
                    "product_code": "PROD-001",
                    "subcategory": None,
                }
            ],
        )

    def test_search_returns_400_when_product_code_mismatches_brand_code(self) -> None:
        service = StubKnowledgeBaseService(search_error=ValueError("product_code 不属于指定 brand_code"))

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/search",
                json={
                    "query": "售后服务标准",
                    "brand_code": "BRAND-001",
                    "product_code": "PROD-OTHER",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "product_code 不属于指定 brand_code"})

    def test_image_search_returns_400_when_product_code_mismatches_brand_code(self) -> None:
        service = StubKnowledgeBaseService(image_search_error=ValueError("product_code 不属于指定 brand_code"))

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/images/search",
                json={
                    "query": "厨房橱柜",
                    "brand_code": "BRAND-001",
                    "product_code": "PROD-OTHER",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "product_code 不属于指定 brand_code"})

    def test_brand_facts_route_supports_primary_path(self) -> None:
        service = StubKnowledgeBaseService()
        service.brand_facts_result = [
            {
                "fact_id": "fact-1",
                "fact": "炜衡密云分所提供企业常年法律顾问服务。",
            }
        ]

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/brands/facts",
                json={
                    "brand_code": "WHMY",
                    "brand_name": "炜衡密云分所",
                    "query": "企业法律顾问",
                    "top_k": 3,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "brand_code": "WHMY",
                "brand_name": "炜衡密云分所",
                "category": "炜衡密云分所",
                "query": "企业法律顾问",
                "facts": [
                    {
                        "fact_id": "fact-1",
                        "fact": "炜衡密云分所提供企业常年法律顾问服务。",
                    }
                ],
            },
        )
        self.assertEqual(
            service.brand_facts_calls,
            [
                {
                    "brand_code": "WHMY",
                    "brand_name": "炜衡密云分所",
                    "category": None,
                    "product_code": None,
                    "query": "企业法律顾问",
                    "top_k": 3,
                }
            ],
        )

    def test_brand_facts_route_supports_product_code_without_brand_name(self) -> None:
        service = StubKnowledgeBaseService()
        service.brand_facts_result = [
            {
                "fact": "产品A支持全国售后服务。",
                "metadata": {
                    "brand_code": "BRAND-001",
                    "brand_name": "示例品牌",
                    "product_code": "PROD-001",
                    "product_name": "产品A",
                },
            }
        ]

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/brands/facts",
                json={
                    "product_code": "PROD-001",
                    "query": "售后服务",
                    "top_k": 3,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "brand_code": "BRAND-001",
                "brand_name": "示例品牌",
                "category": "示例品牌",
                "product_code": "PROD-001",
                "query": "售后服务",
                "facts": [
                    {
                        "fact": "产品A支持全国售后服务。",
                    }
                ],
            },
        )
        self.assertEqual(
            service.brand_facts_calls,
            [
                {
                    "brand_code": None,
                    "brand_name": None,
                    "category": None,
                    "product_code": "PROD-001",
                    "query": "售后服务",
                    "top_k": 3,
                }
            ],
        )

    def test_brand_facts_route_requires_query(self) -> None:
        service = StubKnowledgeBaseService()

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/brands/facts",
                json={
                    "brand_code": "WHMY",
                },
            )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(service.brand_facts_calls, [])

    def test_brand_facts_route_requires_brand_scope(self) -> None:
        service = StubKnowledgeBaseService()

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/brands/facts",
                json={
                    "query": "营业时间",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"detail": "brand_code、brand_name、category、product_code 至少传一个"},
        )
        self.assertEqual(service.brand_facts_calls, [])

    def test_brand_facts_route_returns_503_when_embedding_is_rate_limited(self) -> None:
        service = StubKnowledgeBaseService(
            brand_facts_error=EmbeddingRateLimitedError(60, "Embedding API cooling down")
        )

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/categories/facts",
                json={
                    "category": "炜衡密云分所",
                    "query": "企业法律顾问",
                    "top_k": 3,
                },
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {
                "code": "embedding_rate_limited",
                "message": "embedding 服务限流，请稍后重试",
                "data": None,
            },
        )
        self.assertEqual(response.headers.get("retry-after"), "60")
        self.assertEqual(
            service.brand_facts_calls,
            [
                {
                    "brand_code": None,
                    "brand_name": "炜衡密云分所",
                    "category": "炜衡密云分所",
                    "product_code": None,
                    "query": "企业法律顾问",
                    "top_k": 3,
                }
            ],
        )

    def test_category_facts_route_supports_legacy_category_field(self) -> None:
        service = StubKnowledgeBaseService()
        service.brand_facts_result = [
            {
                "fact_id": "fact-2",
                "fact": "天津华厦眼科可提供眼科相关诊疗服务。",
                "metadata": {
                    "brand_code": "BRAND-002",
                    "brand_name": "天津华厦眼科",
                    "product_code": None,
                    "product_name": None,
                },
            }
        ]

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/categories/facts",
                json={
                    "category": "天津华厦眼科",
                    "query": "眼睛",
                    "top_k": 5,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "brand_code": "BRAND-002",
                "brand_name": "天津华厦眼科",
                "category": "天津华厦眼科",
                "query": "眼睛",
                "facts": [
                    {
                        "fact_id": "fact-2",
                        "fact": "天津华厦眼科可提供眼科相关诊疗服务。",
                    }
                ],
            },
        )
        self.assertEqual(
            service.brand_facts_calls,
            [
                {
                    "brand_code": None,
                    "brand_name": "天津华厦眼科",
                    "category": "天津华厦眼科",
                    "product_code": None,
                    "query": "眼睛",
                    "top_k": 5,
                }
            ],
        )

    def test_preflight_request_allows_configured_frontend_origin(self) -> None:
        service = StubKnowledgeBaseService()
        settings = types.SimpleNamespace(
            dashscope_api_key="test-key",
            cors_allow_origins=("http://localhost:3000",),
            cors_allow_credentials=True,
        )
        app = create_app(settings=settings, service=service)

        with TestClient(app) as client:
            response = client.options(
                "/api/v1/search",
                headers={
                    "Origin": "http://localhost:3000",
                    "Access-Control-Request-Method": "POST",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("access-control-allow-origin"), "http://localhost:3000")
        self.assertEqual(response.headers.get("access-control-allow-credentials"), "true")
        self.assertEqual(service.start_calls, 1)
        self.assertEqual(service.stop_calls, 1)

    def test_brand_facts_upload_route_returns_sync_ingest_result(self) -> None:
        service = StubKnowledgeBaseService(
            brand_facts_ingest_result={
                "status": "success",
                "brand_code": "BRAND-001",
                "brand_name": "示例品牌",
                "document_id": "brandfacts:BRAND-001:abc123",
                "fact_count": 12,
                "deleted_fact_count": 9,
                "content_hash": "abc123",
                "content_type": "text/markdown",
                "file_hash": "filehash-1",
                "file_size": 321,
                "file_name": "facts.md",
            }
        )

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/brands/facts/upload",
                data={
                    "metadata": '{"category":"示例品牌","brand_code":"BRAND-001","brand_name":"示例品牌"}',
                },
                files={
                    "files": ("facts.md", io.BytesIO(b"# facts"), "text/markdown"),
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "status": "success",
                "brand_code": "BRAND-001",
                "brand_name": "示例品牌",
                "document_id": "brandfacts:BRAND-001:abc123",
                "fact_count": 12,
                "deleted_fact_count": 9,
                "content_hash": "abc123",
                "content_type": "text/markdown",
                "file_hash": "filehash-1",
                "file_size": 321,
                "file_name": "facts.md",
            },
        )
        self.assertEqual(
            service.brand_facts_ingest_calls,
            [
                {
                    "file_names": ["facts.md"],
                    "metadata": {
                        "category": "示例品牌",
                        "brand_code": "BRAND-001",
                        "brand_name": "示例品牌",
                    },
                }
            ],
        )

    def test_brand_facts_upload_route_maps_value_error_to_400(self) -> None:
        service = StubKnowledgeBaseService(
            brand_facts_ingest_error=ValueError("facts-only 上传当前仅支持单文件")
        )

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/brands/facts/upload",
                data={
                    "metadata": '{"category":"示例品牌","brand_code":"BRAND-001","brand_name":"示例品牌"}',
                },
                files=[
                    ("files", ("facts-1.md", io.BytesIO(b"# a"), "text/markdown")),
                    ("files", ("facts-2.md", io.BytesIO(b"# b"), "text/markdown")),
                ],
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "facts-only 上传当前仅支持单文件"})


if __name__ == "__main__":
    unittest.main()
