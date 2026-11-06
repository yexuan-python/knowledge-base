from __future__ import annotations

import unittest

from scripts import backfill_brand_from_markdown as backfill


class _FakeBrands:
    def __init__(self, brand: dict[str, object] | None = None) -> None:
        self.brand = brand or {}

    def get_brand_by_name(self, brand_name: str) -> dict[str, object]:
        return dict(self.brand)


class _FakeUploadTasks:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], dict[str, object]] = {}

    def upsert_upload_task_callback(
        self,
        *,
        task_id: str,
        callback_type: str,
        callback_url: str,
        request_payload_json: dict[str, object] | None,
        status: str,
    ) -> None:
        self.rows[(task_id, callback_type)] = {
            "task_id": task_id,
            "callback_type": callback_type,
            "callback_url": callback_url,
            "request_payload_json": request_payload_json,
            "status": status,
            "retry_count": 0,
        }

    def get_upload_task_callback(self, *, task_id: str, callback_type: str):
        return self.rows.get((task_id, callback_type))

    def update_upload_task_callback_result(self, **kwargs) -> None:
        key = (kwargs["task_id"], kwargs["callback_type"])
        self.rows.setdefault(key, {}).update(kwargs)


class _FakeService:
    def __init__(self) -> None:
        self._brands = _FakeBrands(
            {
                "id": 1,
                "brand_code": "BRAND-001",
                "brand_name": "示例品牌",
                "knowledge_revision": "BRAND-001-V1.0.0-20260711120000",
            }
        )
        self._brand_full_knowledge = type(
            "_FakeBrandFullKnowledge",
            (),
            {
                "get_latest_by_brand_id": staticmethod(
                    lambda *, brand_id: {
                        "oss_url": "https://oss.example.com/current.md",
                        "pdf_oss_url": "https://oss.example.com/current.pdf",
                    }
                    if brand_id == 1
                    else None
                )
            },
        )()
        self._upload_tasks = _FakeUploadTasks()


class BackfillCallbackTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.original_runtime = backfill._RUNTIME
        backfill._RUNTIME = {
            "format_brand_callback_knowledge_from_snapshot": lambda *, brand, knowledge_snapshot: {
                "basic_info": {
                    "brand_name": brand.get("brand_name"),
                },
                "attachments": {
                    "files": knowledge_snapshot.get("attachments", []),
                },
            }
        }

    def tearDown(self) -> None:
        backfill._RUNTIME = self.original_runtime

    async def test_builds_success_payload_from_backfill_snapshot(self) -> None:
        service = _FakeService()

        payload = backfill._build_backfill_callback_payload(
            service,
            result={
                "brand_name": "示例品牌",
                "knowledge": {
                    "attachments": [
                        {
                            "name": "品牌手册.md",
                            "url": "file:///tmp/brand.md",
                        }
                    ]
                },
            },
            status="success",
        )

        self.assertEqual(payload["brand_code"], "BRAND-001")
        self.assertEqual(payload["overall_status"], "completed")
        self.assertEqual(payload["knowledge_extraction_status"], "success")
        self.assertEqual(payload["knowledge_markdown_status"], "success")
        self.assertEqual(
            payload["knowledge_mete"],
            {
                "version": "BRAND-001-V1.0.0-20260711120000",
                "oss_url_md": "https://oss.example.com/current.md",
                "oss_url_pdf": "https://oss.example.com/current.pdf",
            },
        )
        self.assertEqual(payload["knowledge"]["basic_info"]["brand_name"], "示例品牌")
        self.assertEqual(payload["knowledge"]["attachments"]["files"][0]["name"], "品牌手册.md")

    async def test_send_callback_records_success_result(self) -> None:
        service = _FakeService()
        original_post = backfill._post_backfill_callback

        def fake_post_backfill_callback(*, callback_url: str, payload: dict[str, object], timeout_seconds: float):
            self.assertEqual(callback_url, "https://callback.example.com")
            self.assertEqual(timeout_seconds, 3.0)
            self.assertEqual(payload["brand_code"], "BRAND-001")
            return 200, "ok", None

        backfill._post_backfill_callback = fake_post_backfill_callback
        try:
            result = await backfill._send_backfill_callback(
                service,
                result={
                    "brand_name": "示例品牌",
                    "brand_id": 1,
                    "knowledge": {},
                },
                status="success",
                error_message=None,
                callback_url="https://callback.example.com",
                timeout_seconds=3.0,
                callback_task_prefix="test_backfill",
            )
        finally:
            backfill._post_backfill_callback = original_post

        self.assertEqual(result["status"], "success")
        row = service._upload_tasks.get_upload_task_callback(
            task_id=result["task_id"],
            callback_type=backfill._BACKFILL_CALLBACK_TYPE,
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "success")
        self.assertEqual(row["last_response_code"], 200)
        self.assertEqual(row["last_response_body"], "ok")
        self.assertIsNotNone(row["sent_at"])


class FillEmptyOnlyPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_runtime = backfill._RUNTIME

        class _FakeBrandApplicationService:
            @staticmethod
            def _serialize_sensitive_topics_payload(value):
                return value if isinstance(value, dict) else {}

        backfill._RUNTIME = {
            "BrandApplicationService": _FakeBrandApplicationService,
        }

    def tearDown(self) -> None:
        backfill._RUNTIME = self.original_runtime

    def test_merges_top_level_other_info(self) -> None:
        result = backfill._apply_fill_empty_only_policy(
            final_payload={
                "basic_info": {},
                "company_profile": {},
                "products": [],
                "management_team": [],
                "competitors": [],
                "authority_honors": [],
                "customers_cases": [],
                "attachments": [],
                "official_malls": [],
                "official_media_matrix": [],
                "other_info": [
                    {
                        "title": "停车信息",
                        "content": "新增内容",
                    },
                    {
                        "title": "高频问答 FAQ",
                        "content": "Q:是否支持补购?\nA:支持。",
                    }
                ],
                "sensitive_topics": {},
            },
            existing_snapshot={
                "basic_info": {},
                "company_profile": {},
                "products": [],
                "management_team": [],
                "competitors": [],
                "authority_honors": [],
                "customers_cases": [],
                "attachments": [],
                "official_malls": [],
                "official_media_matrix": [],
                "other_info": [
                    {
                        "title": "停车信息",
                        "content": "已有内容",
                    }
                ],
            },
            existing_sensitive_topics={},
            incoming_sensitive_topics={},
        )

        self.assertEqual(
            result["other_info"],
            [
                {
                    "title": "停车信息",
                    "content": "已有内容",
                },
                {
                    "title": "停车信息",
                    "content": "新增内容",
                },
                {
                    "title": "高频问答 FAQ",
                    "content": "Q:是否支持补购?\nA:支持。",
                },
            ],
        )

    def test_keeps_competitors_unchanged(self) -> None:
        result = backfill._apply_fill_empty_only_policy(
            final_payload={
                "basic_info": {},
                "company_profile": {},
                "products": [],
                "management_team": [],
                "competitors": [
                    {
                        "name": "欧派家居",
                        "competitors_description": "新增竞品描述",
                    }
                ],
                "authority_honors": [],
                "customers_cases": [],
                "attachments": [],
                "official_malls": [],
                "official_media_matrix": [],
                "other_info": [],
                "sensitive_topics": {},
            },
            existing_snapshot={
                "basic_info": {},
                "company_profile": {},
                "products": [],
                "management_team": [],
                "competitors": [
                    {
                        "name": "欧派家居",
                        "competitors_description": "",
                    }
                ],
                "authority_honors": [],
                "customers_cases": [],
                "attachments": [],
                "official_malls": [],
                "official_media_matrix": [],
                "other_info": [],
            },
            existing_sensitive_topics={},
            incoming_sensitive_topics={},
        )

        self.assertEqual(
            result["competitors"],
            [
                {
                    "name": "欧派家居",
                    "competitors_description": "",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
