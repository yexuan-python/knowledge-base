from __future__ import annotations

import importlib.util
import types
import unittest

FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None

if FASTAPI_AVAILABLE:
    from fastapi.testclient import TestClient

    from knowledge_base.api_app.app import create_app
    from knowledge_base.api_app.routers import knowledge as knowledge_router_module


class StubKnowledgeBaseService:
    def __init__(self, *, update_result: dict | None = None, update_error: Exception | None = None) -> None:
        self.update_result = update_result
        self.update_error = update_error
        self.update_calls: list[object] = []
        self.start_calls = 0
        self.stop_calls = 0

    async def start(self) -> None:
        self.start_calls += 1

    async def stop(self) -> None:
        self.stop_calls += 1

    async def update_knowledge(self, request) -> dict | None:
        self.update_calls.append(request)
        if self.update_error is not None:
            raise self.update_error
        return self.update_result


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed")
class KnowledgeRouteTests(unittest.TestCase):
    def _build_client(self, service: StubKnowledgeBaseService) -> TestClient:
        settings = types.SimpleNamespace(dashscope_api_key="test-key")
        app = create_app(settings=settings, service=service)
        app.dependency_overrides[knowledge_router_module.get_service] = lambda: service
        return TestClient(app)

    def test_update_knowledge_respects_skip_full_ai_knowledge_sync(self) -> None:
        service = StubKnowledgeBaseService(update_result={"status": "success"})

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/knowledge/update",
                json={
                    "basic_info": {
                        "brand_code": "100060",
                        "brand_name": "北京嘉禾妇儿医院",
                    },
                    "products": [],
                    "company_profile": None,
                    "management_team": [],
                    "competitors": [],
                    "authority_honors": [],
                    "customers_cases": [],
                    "official_media_matrix": [],
                    "official_malls": [],
                    "sensitive_topics": {
                        "sensitive_contents": [],
                        "controversial_events": [],
                        "forbidden_words": [],
                        "negative_clarifications": [],
                        "other_info": [],
                    },
                    "attachments": [],
                    "other_info": [],
                    "skip_full_ai_knowledge_sync": False,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "success"})
        self.assertEqual(service.start_calls, 1)
        self.assertEqual(service.stop_calls, 1)
        self.assertEqual(len(service.update_calls), 1)
        update_request = service.update_calls[0]
        self.assertFalse(update_request.skip_full_ai_knowledge_sync)

    def test_update_knowledge_defaults_to_full_ai_knowledge_sync(self) -> None:
        service = StubKnowledgeBaseService(update_result={"status": "success"})

        with self._build_client(service) as client:
            response = client.post(
                "/api/v1/knowledge/update",
                json={
                    "basic_info": {
                        "brand_code": "100060",
                        "brand_name": "北京嘉禾妇儿医院",
                    },
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "success"})
        update_request = service.update_calls[0]
        self.assertFalse(update_request.skip_full_ai_knowledge_sync)

    def test_update_knowledge_omitted_products_and_empty_products_are_explicit_empty_snapshots(self) -> None:
        for product_fields in ({}, {"products": []}):
            with self.subTest(product_fields=product_fields):
                service = StubKnowledgeBaseService(update_result={"status": "success"})
                with self._build_client(service) as client:
                    response = client.post("/api/v1/knowledge/update", json={
                        "basic_info": {"brand_code": "100060", "brand_name": "北京嘉禾妇儿医院"},
                        **product_fields,
                    })
                self.assertEqual(response.status_code, 200)
                request = service.update_calls[0]
                self.assertEqual(request.products, [])
                self.assertIn("products", request.model_fields_set)
                self.assertNotIn("attachments", request.model_fields_set)
                self.assertNotIn("competitors", request.model_fields_set)

    def test_update_knowledge_does_not_log_full_request_body(self) -> None:
        service = StubKnowledgeBaseService(update_result={"status": "success"})

        with self._build_client(service) as client:
            with self.assertLogs("knowledge_base.api_app.routers.knowledge", level="INFO") as captured_logs:
                response = client.post(
                    "/api/v1/knowledge/update",
                    json={
                        "basic_info": {
                            "brand_code": "100060",
                            "brand_name": "北京嘉禾妇儿医院",
                            "intro": "SHOULD_NOT_APPEAR_IN_INFO_LOGS",
                        },
                        "products": [{"name": "产品A"}],
                        "company_profile": None,
                        "management_team": [],
                        "competitors": [],
                        "authority_honors": [],
                        "customers_cases": [],
                        "official_media_matrix": [],
                        "official_malls": [],
                        "sensitive_topics": {
                            "sensitive_contents": [],
                            "controversial_events": [],
                            "forbidden_words": [],
                            "negative_clarifications": [],
                            "other_info": [],
                        },
                        "attachments": [],
                        "other_info": [],
                    },
                )

        self.assertEqual(response.status_code, 200)
        log_text = "\n".join(captured_logs.output)
        self.assertIn("brand_code=100060", log_text)
        self.assertIn("products_count=1", log_text)
        self.assertNotIn("request_json=", log_text)
        self.assertNotIn("SHOULD_NOT_APPEAR_IN_INFO_LOGS", log_text)
