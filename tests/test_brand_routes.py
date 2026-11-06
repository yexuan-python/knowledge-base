from __future__ import annotations

import types
import unittest
from dataclasses import asdict

from fastapi.testclient import TestClient

from knowledge_base.api_app.app import create_app
from knowledge_base.api_app.routers import brands as brands_router_module
from knowledge_base.upload_task.schemas import UploadTaskCreateResponse


class StubKnowledgeBaseService:
    def __init__(
        self,
        *,
        brand_list_result: list[dict] | None = None,
        latest_ai_knowledge_result: dict | None = None,
        latest_ai_knowledge_error: Exception | None = None,
        official_malls_result: dict | None = None,
        official_malls_error: Exception | None = None,
        meta_result: dict | None = None,
        meta_error: Exception | None = None,
        paths_result: dict | None = None,
        paths_error: Exception | None = None,
        rename_result: dict | None = None,
        rename_error: Exception | None = None,
        upload_result: UploadTaskCreateResponse | None = None,
        upload_error: Exception | None = None,
    ) -> None:
        self.brand_list_result = brand_list_result or []
        self.latest_ai_knowledge_result = latest_ai_knowledge_result
        self.latest_ai_knowledge_error = latest_ai_knowledge_error
        self.official_malls_result = official_malls_result
        self.official_malls_error = official_malls_error
        self.meta_result = meta_result
        self.meta_error = meta_error
        self.paths_result = paths_result
        self.paths_error = paths_error
        self.rename_result = rename_result
        self.rename_error = rename_error
        self.upload_result = upload_result
        self.upload_error = upload_error
        self.brand_list_calls: list[dict] = []
        self.latest_ai_knowledge_calls: list[dict] = []
        self.official_malls_calls: list[dict] = []
        self.meta_calls: list[dict] = []
        self.paths_calls: list[dict] = []
        self.rename_calls: list[dict] = []
        self.upload_calls: list[dict] = []
        self.start_calls = 0
        self.stop_calls = 0
        self._alert_app = None

    async def start(self) -> None:
        self.start_calls += 1

    async def stop(self) -> None:
        self.stop_calls += 1

    async def list_brands(self, *, keyword: str | None = None) -> list[dict]:
        self.brand_list_calls.append({"keyword": keyword})
        return list(self.brand_list_result)

    async def get_latest_ai_knowledge(self, *, brand_code: str) -> dict | None:
        self.latest_ai_knowledge_calls.append({"brand_code": brand_code})
        if self.latest_ai_knowledge_error is not None:
            raise self.latest_ai_knowledge_error
        return self.latest_ai_knowledge_result

    async def get_brand_official_malls(self, *, brand_code: str) -> dict | None:
        self.official_malls_calls.append({"brand_code": brand_code})
        if self.official_malls_error is not None:
            raise self.official_malls_error
        return self.official_malls_result

    async def get_brand_meta(
        self,
        *,
        brand_code: str,
        include_path_index: bool = True,
    ) -> dict | None:
        self.meta_calls.append(
            {
                "brand_code": brand_code,
                "include_path_index": include_path_index,
            }
        )
        if self.meta_error is not None:
            raise self.meta_error
        return self.meta_result

    def load_brand_paths(
        self,
        *,
        brand_code: str,
        paths: list[str],
        knowledge_revision: str | None = None,
    ) -> dict | None:
        self.paths_calls.append(
            {
                "brand_code": brand_code,
                "paths": paths,
                "knowledge_revision": knowledge_revision,
            }
        )
        if self.paths_error is not None:
            raise self.paths_error
        return self.paths_result

    async def rename_brand(self, request) -> dict | None:
        payload = asdict(request) if hasattr(request, "__dataclass_fields__") else request.model_dump()
        self.rename_calls.append(payload)
        if self.rename_error is not None:
            raise self.rename_error
        return self.rename_result

    async def enqueue_brand_upload_task(self, request) -> UploadTaskCreateResponse:
        payload = asdict(request) if hasattr(request, "__dataclass_fields__") else request.model_dump()
        self.upload_calls.append(payload)
        if self.upload_error is not None:
            raise self.upload_error
        return self.upload_result or UploadTaskCreateResponse(
            task_id="task-brand-upload-empty",
            status="completed",
            file_count=0,
            message="品牌资料已保存，无附件需要处理",
        )


class BrandRouteTests(unittest.TestCase):
    def _build_client(self, service: StubKnowledgeBaseService) -> TestClient:
        settings = types.SimpleNamespace(dashscope_api_key="test-key")
        app = create_app(settings=settings, service=service)
        app.dependency_overrides[brands_router_module.get_service] = lambda: service
        return TestClient(app)

    def test_brand_upload_without_attachments_returns_completed_task(self) -> None:
        service = StubKnowledgeBaseService(
            upload_result=UploadTaskCreateResponse(
                task_id="task-brand-upload-empty",
                status="completed",
                file_count=0,
                message="品牌资料已保存，无附件需要处理",
            )
        )

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/brands/upload",
                json={
                    "brand_code": "BRAND-001",
                    "brand_name": "示例品牌",
                    "intro": "示例品牌介绍",
                    "attachments": [],
                },
            )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(
            response.json(),
            {
                "task_id": "task-brand-upload-empty",
                "status": "completed",
                "file_count": 0,
                "message": "品牌资料已保存，无附件需要处理",
            },
        )
        self.assertEqual(len(service.upload_calls), 1)
        self.assertEqual("BRAND-001", service.upload_calls[0]["brand_code"])
        self.assertEqual("示例品牌", service.upload_calls[0]["brand_name"])
        self.assertEqual([], service.upload_calls[0]["attachments"])

    def test_upload_validation_failure_sends_alert_with_original_attachments(self) -> None:
        class FakeAlertApp:
            def __init__(self) -> None:
                self.calls: list[dict] = []

            async def notify_request_validation_failure(self, **kwargs):
                self.calls.append(kwargs)

        service = StubKnowledgeBaseService()
        alert_app = FakeAlertApp()
        service._alert_app = alert_app

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/brands/upload",
                json={
                    "attachments": [
                        {
                            "name": "品牌手册.pdf",
                            "url": "https://example.com/brand-book.pdf",
                        }
                    ],
                    "products": [
                        {
                            "name": "示例产品",
                            "attachments": [
                                {
                                    "name": "产品手册.pdf",
                                    "url": "https://example.com/product-book.pdf",
                                }
                            ],
                        }
                    ],
                },
            )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(1, len(alert_app.calls))
        call = alert_app.calls[0]
        self.assertEqual("POST", call["method"])
        self.assertEqual("/api/v1/brands/upload", call["path"])
        self.assertEqual(
            [
                {
                    "name": "品牌手册.pdf",
                    "url": "https://example.com/brand-book.pdf",
                }
            ],
            call["request_body"]["attachments"],
        )
        self.assertEqual(
            [
                {
                    "name": "产品手册.pdf",
                    "url": "https://example.com/product-book.pdf",
                }
            ],
            call["request_body"]["products"][0]["attachments"],
        )
        self.assertTrue(all("input" not in error for error in call["errors"]))

    def test_upload_validation_failure_with_bytes_body_returns_json_422(self) -> None:
        class FakeAlertApp:
            def __init__(self) -> None:
                self.calls: list[dict] = []

            async def notify_request_validation_failure(self, **kwargs):
                self.calls.append(kwargs)

        service = StubKnowledgeBaseService()
        alert_app = FakeAlertApp()
        service._alert_app = alert_app

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/brands/upload",
                content=b"\x80\x81not-json",
                headers={"content-type": "application/octet-stream"},
            )

        self.assertEqual(response.status_code, 422)
        self.assertIsInstance(response.json(), dict)
        self.assertIn("detail", response.json())
        self.assertEqual(1, len(alert_app.calls))
        self.assertTrue(all("input" not in error for error in response.json()["detail"]))
        self.assertTrue(all("input" not in error for error in alert_app.calls[0]["errors"]))

    def test_non_upload_validation_failure_does_not_send_alert(self) -> None:
        class FakeAlertApp:
            def __init__(self) -> None:
                self.calls: list[dict] = []

            async def notify_request_validation_failure(self, **kwargs):
                self.calls.append(kwargs)

        service = StubKnowledgeBaseService()
        alert_app = FakeAlertApp()
        service._alert_app = alert_app

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/brands/attachments/preview-parse",
                json={},
            )

        self.assertEqual(response.status_code, 422)
        self.assertEqual([], alert_app.calls)

    def test_get_brand_meta_returns_wrapped_response(self) -> None:
        service = StubKnowledgeBaseService(
            meta_result={
                "meta": {
                    "brand_code": "BRAND-001",
                    "brand_name": "示例品牌",
                    "brand_aliases": ["示例别名"],
                    "brand_english_name": "Demo Brand",
                    "industry": "消费品",
                    "official_websites": ["https://example.com"],
                    "knowledge_revision": "brand-001-20260623154510",
                    "company_subject_name": "示例企业主体",
                    "company_profile": {
                        "brand_subject_name": "示例企业主体",
                        "company_intro": "示例企业简介",
                    },
                    "products": [
                        {
                            "name": "明星产品",
                            "aliases": ["爆款"],
                            "path": "产品信息/明星产品",
                            "intro": "核心产品介绍",
                        }
                    ],
                    "competitors": [
                        {
                            "name": "竞品A",
                            "aliases": [],
                            "path": "竞品信息/竞品A",
                            "intro": "主要竞对",
                        }
                    ],
                },
                "path_index": [
                    {
                        "path": "品牌基础信息/品牌介绍",
                        "title": "品牌介绍",
                        "summary": "品牌基础介绍",
                    }
                ],
            }
        )

        with self._build_client(service) as client:
            response = client.get("/api/v1/brands/BRAND-001/meta")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "code": 0,
                "message": "ok",
                "data": {
                    "meta": {
                        "brand_code": "BRAND-001",
                        "brand_name": "示例品牌",
                        "brand_aliases": ["示例别名"],
                        "brand_english_name": "Demo Brand",
                        "industry": "消费品",
                        "official_websites": ["https://example.com"],
                        "knowledge_revision": "brand-001-20260623154510",
                        "company_subject_name": "示例企业主体",
                        "company_profile": {
                            "brand_subject_name": "示例企业主体",
                            "company_intro": "示例企业简介",
                        },
                        "products": [
                            {
                                "name": "明星产品",
                                "aliases": ["爆款"],
                                "path": "产品信息/明星产品",
                                "intro": "核心产品介绍",
                            }
                        ],
                        "competitors": [
                            {
                                "name": "竞品A",
                                "aliases": [],
                                "path": "竞品信息/竞品A",
                                "intro": "主要竞对",
                            }
                        ],
                    },
                    "path_index": [
                        {
                            "path": "品牌基础信息/品牌介绍",
                            "title": "品牌介绍",
                            "summary": "品牌基础介绍",
                        }
                    ],
                },
            },
        )
        self.assertEqual(
            service.meta_calls,
            [
                {
                    "brand_code": "BRAND-001",
                    "include_path_index": True,
                }
            ],
        )
        self.assertEqual(service.start_calls, 1)
        self.assertEqual(service.stop_calls, 1)

    def test_list_brands_returns_wrapped_response(self) -> None:
        service = StubKnowledgeBaseService(
            brand_list_result=[
                {
                    "id": 1,
                    "brand_code": "BRAND-001",
                    "brand_name": "示例品牌",
                    "brand_alias": "示例别名",
                    "website": ["https://example.com"],
                    "intro": "品牌简介",
                    "updated_at": None,
                }
            ]
        )

        with self._build_client(service) as client:
            response = client.get("/api/v1/brands?keyword=%E7%A4%BA%E4%BE%8B")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "keyword": "示例",
                "brands": [
                    {
                        "id": 1,
                        "brand_code": "BRAND-001",
                        "brand_name": "示例品牌",
                        "brand_alias": "示例别名",
                        "website": ["https://example.com"],
                        "intro": "品牌简介",
                        "updated_at": None,
                    }
                ],
            },
        )
        self.assertEqual(service.brand_list_calls, [{"keyword": "示例"}])

    def test_get_latest_ai_knowledge_returns_wrapped_response(self) -> None:
        service = StubKnowledgeBaseService(
            latest_ai_knowledge_result={
                "brand_code": "BRAND-001",
                "brand_name": "示例品牌",
                "brand_id": 1,
                "file_name": "【示例品牌】品牌AI知识库_V3_20260821.md",
                "oss_key": "knowledge/brand-001/v3.md",
                "oss_url": "https://oss.example.com/knowledge/brand-001/v3.md",
                "version_no": 3,
                "created_at": None,
                "source": "brand_full_knowledge_files",
            }
        )

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/brands/ai-knowledge/latest",
                json={"brand_code": "BRAND-001"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "code": 0,
                "message": "ok",
                "data": {
                    "brand_code": "BRAND-001",
                    "brand_name": "示例品牌",
                    "brand_id": 1,
                    "file_name": "【示例品牌】品牌AI知识库_V3_20260821.md",
                    "oss_key": "knowledge/brand-001/v3.md",
                    "oss_url": "https://oss.example.com/knowledge/brand-001/v3.md",
                    "version_no": 3,
                    "created_at": None,
                    "source": "brand_full_knowledge_files",
                },
            },
        )
        self.assertEqual(service.latest_ai_knowledge_calls, [{"brand_code": "BRAND-001"}])

    def test_get_brand_official_malls_returns_wrapped_response(self) -> None:
        service = StubKnowledgeBaseService(
            official_malls_result={
                "brand_code": "BRAND-001",
                "brand_name": "示例品牌",
                "knowledge_revision": "brand-001-20260623154510",
                "official_malls": [
                    {
                        "store_name": "品牌旗舰店",
                        "platform": "天猫",
                        "homepage_urls": ["https://mall.example.com"],
                        "store_ids": ["TM-001"],
                        "main_categories": ["智能汽车"],
                        "advantages": ["官方正品"],
                        "related_products": ["1001"],
                        "other_info": ["支持售后咨询"],
                    }
                ],
            }
        )

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/brands/official-malls",
                json={"brand_code": "BRAND-001"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "code": 0,
                "message": "ok",
                "data": {
                    "brand_code": "BRAND-001",
                    "brand_name": "示例品牌",
                    "knowledge_revision": "brand-001-20260623154510",
                    "official_malls": [
                        {
                            "store_name": "品牌旗舰店",
                            "platform": "天猫",
                            "homepage_urls": ["https://mall.example.com"],
                            "store_ids": ["TM-001"],
                            "main_categories": ["智能汽车"],
                            "advantages": ["官方正品"],
                            "related_products": ["1001"],
                            "other_info": ["支持售后咨询"],
                        }
                    ],
                },
            },
        )
        self.assertEqual(service.official_malls_calls, [{"brand_code": "BRAND-001"}])

    def test_get_brand_official_malls_returns_404_when_brand_missing(self) -> None:
        service = StubKnowledgeBaseService(official_malls_result=None)

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/brands/official-malls",
                json={"brand_code": "NOT-FOUND"},
            )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(),
            {
                "code": 40401,
                "message": "brand_code 不存在",
                "data": None,
            },
        )

    def test_get_brand_official_malls_returns_400_wrapped_error(self) -> None:
        service = StubKnowledgeBaseService(
            official_malls_error=ValueError("brand_code 不能为空")
        )

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/brands/official-malls",
                json={"brand_code": " "},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {
                "code": 40001,
                "message": "brand_code 不能为空",
                "data": None,
            },
        )

    def test_get_brand_meta_omits_path_index_when_disabled(self) -> None:
        service = StubKnowledgeBaseService(
            meta_result={
                "meta": {
                    "brand_code": "BRAND-001",
                    "brand_name": "示例品牌",
                    "brand_aliases": [],
                    "brand_english_name": "",
                    "industry": "",
                    "official_websites": [],
                    "knowledge_revision": "brand-001-20260623154510",
                    "company_subject_name": "",
                    "company_profile": {},
                    "products": [],
                    "competitors": [],
                },
                "path_index": [
                    {
                        "path": "品牌基础信息/品牌介绍",
                        "title": "品牌介绍",
                        "summary": "品牌基础介绍",
                    }
                ],
            }
        )

        with self._build_client(service) as client:
            response = client.get("/api/v1/brands/BRAND-001/meta?include_path_index=false")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "code": 0,
                "message": "ok",
                "data": {
                    "meta": {
                        "brand_code": "BRAND-001",
                        "brand_name": "示例品牌",
                        "brand_aliases": [],
                        "brand_english_name": "",
                        "industry": "",
                        "official_websites": [],
                        "knowledge_revision": "brand-001-20260623154510",
                        "company_subject_name": "",
                        "company_profile": {},
                        "products": [],
                        "competitors": [],
                    }
                },
            },
        )
        self.assertEqual(service.meta_calls[0]["include_path_index"], False)

    def test_get_brand_meta_returns_404_when_brand_missing(self) -> None:
        service = StubKnowledgeBaseService(meta_result=None)

        with self._build_client(service) as client:
            response = client.get("/api/v1/brands/NOT-FOUND/meta")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(),
            {
                "code": 40401,
                "message": "brand_code 不存在",
                "data": None,
            },
        )

    def test_get_brand_meta_returns_400_wrapped_error(self) -> None:
        service = StubKnowledgeBaseService(meta_error=ValueError("brand_code 不能为空"))

        with self._build_client(service) as client:
            response = client.get("/api/v1/brands/%20/meta")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {
                "code": 40001,
                "message": "brand_code 不能为空",
                "data": None,
            },
        )

    def test_load_brand_paths_returns_wrapped_response(self) -> None:
        service = StubKnowledgeBaseService(
            paths_result={
                "assets": [
                    {
                        "title": "品牌介绍",
                        "path": "品牌基础信息/品牌介绍",
                        "content": "# 品牌介绍\n示例内容",
                        "knowledge_revision": "brand-001-20260623154510",
                        "updated_at": None,
                    }
                ],
                "missing_paths": [
                    {
                        "path": "品牌基础信息/不存在节点",
                        "reason": "not_found",
                    }
                ],
            }
        )

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/brands/BRAND-001/paths-load",
                json={
                    "knowledge_revision": "brand-001-20260623154510",
                    "paths": ["品牌基础信息/品牌介绍", "品牌基础信息/不存在节点"],
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "code": 0,
                "message": "ok",
                "data": {
                    "assets": [
                        {
                            "title": "品牌介绍",
                            "path": "品牌基础信息/品牌介绍",
                            "content": "# 品牌介绍\n示例内容",
                            "knowledge_revision": "brand-001-20260623154510",
                            "updated_at": None,
                        }
                    ],
                    "missing_paths": [
                        {
                            "path": "品牌基础信息/不存在节点",
                            "reason": "not_found",
                        }
                    ],
                },
            },
        )
        self.assertEqual(
            service.paths_calls,
            [
                {
                    "brand_code": "BRAND-001",
                    "paths": ["品牌基础信息/品牌介绍", "品牌基础信息/不存在节点"],
                    "knowledge_revision": "brand-001-20260623154510",
                }
            ],
        )

    def test_load_brand_paths_returns_404_when_brand_missing(self) -> None:
        service = StubKnowledgeBaseService(paths_result=None)

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/brands/NOT-FOUND/paths-load",
                json={
                    "knowledge_revision": "brand-001-20260623154510",
                    "paths": ["品牌基础信息/品牌介绍"],
                },
            )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(),
            {
                "code": 40401,
                "message": "brand_code 不存在",
                "data": None,
            },
        )

    def test_load_brand_paths_returns_409_when_revision_mismatched(self) -> None:
        service = StubKnowledgeBaseService(
            paths_error=RuntimeError("knowledge_revision 已过期，请重新获取 meta")
        )

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/brands/BRAND-001/paths-load",
                json={
                    "knowledge_revision": "stale-revision",
                    "paths": ["品牌基础信息/品牌介绍"],
                },
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json(),
            {
                "code": 40901,
                "message": "knowledge_revision 已过期，请重新获取 meta",
                "data": None,
            },
        )

    def test_load_brand_paths_returns_400_wrapped_error(self) -> None:
        service = StubKnowledgeBaseService(paths_error=ValueError("paths 不能为空"))

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/brands/BRAND-001/paths-load",
                json={"knowledge_revision": "brand-001-20260623154510", "paths": []},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {
                "code": 40001,
                "message": "paths 不能为空",
                "data": None,
            },
        )

    def test_rename_brand_returns_success_response(self) -> None:
        service = StubKnowledgeBaseService(
            rename_result={
                "brand_code": "100204",
                "brand_id": 7,
                "old_brand_name": "御温泉渡假村",
                "brand_name": "珠海御温泉渡假村",
                "counts": {
                    "brands": 1,
                    "brand_products": 2,
                    "brand_full_knowledge_files": 1,
                    "brand_knowledge_facts": 3,
                    "brand_attachment_assets": 1,
                    "brand_knowledge_ingestion_jobs": 1,
                    "brand_knowledge_sessions": 1,
                    "document_registry": 2,
                    "document_categories": 2,
                    "background_jobs": 1,
                    "upload_tasks": 1,
                },
                "updated_tables": [
                    "brands",
                    "brand_products",
                    "document_registry",
                    "document_categories",
                ],
            }
        )

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/brands/rename",
                json={
                    "brand_code": "100204",
                    "new_brand_name": "珠海御温泉渡假村",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "brand_code": "100204",
                "brand_id": 7,
                "old_brand_name": "御温泉渡假村",
                "brand_name": "珠海御温泉渡假村",
                "executed": True,
                "message": "品牌名称更新完成。",
                "counts": {
                    "brands": 1,
                    "brand_products": 2,
                    "brand_full_knowledge_files": 1,
                    "brand_knowledge_facts": 3,
                    "brand_attachment_assets": 1,
                    "brand_knowledge_ingestion_jobs": 1,
                    "brand_knowledge_sessions": 1,
                    "document_registry": 2,
                    "document_categories": 2,
                    "background_jobs": 1,
                    "upload_tasks": 1,
                },
                "updated_tables": [
                    "brands",
                    "brand_products",
                    "document_registry",
                    "document_categories",
                ],
            },
        )
        self.assertEqual(
            service.rename_calls,
            [
                {
                    "brand_code": "100204",
                    "new_brand_name": "珠海御温泉渡假村",
                }
            ],
        )

    def test_rename_brand_returns_404_when_brand_missing(self) -> None:
        service = StubKnowledgeBaseService(rename_result=None)

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/brands/rename",
                json={
                    "brand_code": "NOT-FOUND",
                    "new_brand_name": "珠海御温泉渡假村",
                },
            )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "brand_code 对应的品牌不存在"})

    def test_rename_brand_returns_409_when_new_name_conflicts(self) -> None:
        service = StubKnowledgeBaseService(rename_error=ValueError("new_brand_name 对应的品牌已存在"))

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/brands/rename",
                json={
                    "brand_code": "100204",
                    "new_brand_name": "珠海御温泉渡假村",
                },
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"detail": "new_brand_name 对应的品牌已存在"})
