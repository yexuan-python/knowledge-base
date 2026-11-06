from __future__ import annotations

from tests.fakes.attachment_preview_flow import *


class AttachmentPreviewConfirmPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_confirm_save_uses_confirmed_text_and_manifest_brand_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            uploaded_bytes_calls: list[dict[str, str]] = []
            uploaded_file_calls: list[dict[str, str]] = []
            ingest_text_document = AsyncMock(return_value=types.SimpleNamespace(document_id="confirmed_doc_1"))

            def _upload_bytes(data: bytes, object_key: str, content_type: str) -> str:
                uploaded_bytes_calls.append(
                    {
                        "text": data.decode("utf-8"),
                        "object_key": object_key,
                        "content_type": content_type,
                    }
                )
                return object_key

            def _upload_file(file_path: str, object_key: str) -> str:
                uploaded_file_calls.append(
                    {
                        "file_path": file_path,
                        "object_key": object_key,
                    }
                )
                return object_key

            service = AttachmentDraftService(
                AttachmentDraftDependencies(
                    settings=types.SimpleNamespace(upload_staging_dir=temp_dir),
                    parser=_FakeParser(),
                    oss_client=types.SimpleNamespace(
                        enabled=True,
                        upload_bytes=_upload_bytes,
                        upload_file=_upload_file,
                        build_object_url=lambda object_key: f"https://oss.example.com/{object_key}",
                        delete_object=lambda _object_key: None,
                    ),
                    brands=None,
                    brand_products=None,
                    brand_knowledge=None,
                    update_knowledge=AsyncMock(),
                    ingest_text_document=ingest_text_document,
                )
            )

            draft_id = "bad_confirm"
            draft_dir = Path(temp_dir) / "attachment_parse_drafts" / draft_id
            download_dir = draft_dir / "downloads"
            download_dir.mkdir(parents=True, exist_ok=True)
            local_attachment = download_dir / "001-品牌手册.pdf"
            local_attachment.write_bytes(b"demo attachment")
            (draft_dir / "draft.json").write_text(
                json.dumps(
                    {
                        "draft_id": draft_id,
                        "brand_name": "示例品牌",
                        "attachments": [
                            {
                                "name": "品牌手册.pdf",
                                "url": "https://example.com/brand-book.pdf",
                                "local_path": str(local_attachment),
                            }
                        ],
                        "combined_markdown_text": "# 示例品牌 附件预解析草稿",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            request = types.SimpleNamespace(
                brand_name=None,
                review_id=None,
                confirmed_text="品牌概述：这里是确认后的内容\n品牌优势：这里是补充优势",
                knowledge_revision=None,
            )

            with self.assertRaisesRegex(ValueError, "旧链路已禁用"):
                await service.confirm_save(
                    request=request,
                    draft_id=draft_id,
                )

        self.assertEqual([], uploaded_bytes_calls)
        self.assertEqual([], uploaded_file_calls)
        ingest_text_document.assert_not_awaited()

    async def test_confirm_save_with_review_id_enqueues_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            draft_id = "bad_confirm_enqueue"
            review_id = "bar_confirm_enqueue"
            draft_dir = Path(temp_dir) / "attachment_parse_drafts" / draft_id
            review_dir = draft_dir / "reviews"
            review_dir.mkdir(parents=True, exist_ok=True)
            (draft_dir / "draft.json").write_text(
                json.dumps(
                    {
                        "draft_id": draft_id,
                        "brand_name": "示例品牌",
                        "brand_code": "BRAND-001",
                        "attachments": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (review_dir / f"{review_id}.json").write_text(
                json.dumps(
                    {
                        "review_id": review_id,
                        "draft_id": draft_id,
                        "brand_code": "BRAND-001",
                        "brand_name": "示例品牌",
                        "knowledge_revision": "LXKG-SLPP-V1.0.0-20260630010101",
                        "update_request_payload": {
                            "basic_info": {
                                "brand_name": "示例品牌",
                                "brand_code": "BRAND-001",
                            },
                            "attachments": [],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            enqueue_pipeline = AsyncMock(
                return_value={
                    "job_id": f"bg:attachment_confirm_pipeline:confirm:{draft_id}:{review_id}",
                    "status": "waiting",
                }
            )
            service = AttachmentDraftService(
                AttachmentDraftDependencies(
                    settings=types.SimpleNamespace(upload_staging_dir=temp_dir),
                    parser=_FakeParser(),
                    oss_client=types.SimpleNamespace(enabled=False),
                    brands=_FakeBrandStore(),
                    brand_products=_FakeBrandProductStore(),
                    brand_knowledge=_FakeBrandKnowledgeStore(),
                    update_knowledge=AsyncMock(),
                    enqueue_attachment_confirm_pipeline_job=enqueue_pipeline,
                )
            )

            result = await service.confirm_save(
                request=types.SimpleNamespace(
                    review_id=review_id,
                    confirmed_text=None,
                    brand_name=None,
                    knowledge_revision="LXKG-SLPP-V1.0.0-20260630010101",
                ),
                draft_id=draft_id,
            )

        self.assertEqual("waiting", result["status"])
        self.assertEqual("waiting", result["background_job_status"])
        self.assertEqual(f"bg:attachment_confirm_pipeline:confirm:{draft_id}:{review_id}", result["background_job_id"])
        enqueue_pipeline.assert_awaited_once()
        self.assertEqual(draft_id, enqueue_pipeline.await_args.kwargs["draft_id"])
        self.assertEqual(review_id, enqueue_pipeline.await_args.kwargs["review_id"])

    async def test_confirm_pipeline_uses_unique_confirmed_markdown_and_enqueues_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            draft_id = "bad_confirm_source"
            review_id = "bar_confirm_source"
            draft_dir = Path(temp_dir) / "attachment_parse_drafts" / draft_id
            review_dir = draft_dir / "reviews"
            review_dir.mkdir(parents=True, exist_ok=True)
            (draft_dir / "draft.json").write_text(
                json.dumps(
                    {
                        "draft_id": draft_id,
                        "brand_name": "示例品牌",
                        "brand_code": "BRAND-001",
                        "attachments": [
                            {
                                "name": "品牌手册.pdf",
                                "url": "https://example.com/brand-book.pdf",
                            }
                        ],
                        "combined_markdown_text": "# 示例品牌 附件预解析草稿",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (review_dir / f"{review_id}.json").write_text(
                json.dumps(
                    {
                        "review_id": review_id,
                        "draft_id": draft_id,
                        "brand_code": "BRAND-001",
                        "brand_name": "示例品牌",
                        "knowledge_revision": "LXKG-SLPP-V1.0.0-20260630010101",
                        "update_request_payload": {
                            "basic_info": {
                                "brand_name": "示例品牌",
                                "brand_code": "BRAND-001",
                                "intro": "附件确认后的简介",
                            },
                            "attachments": [
                                {
                                    "name": "品牌手册.pdf",
                                    "url": "https://example.com/brand-book.pdf",
                                }
                            ],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            update_knowledge = AsyncMock(
                return_value={
                    "brand_id": 1,
                    "updated_sections": ["basic_info", "attachments"],
                    "knowledge_revision": "LXKG-SLPP-V1.0.1-20260630020202",
                }
            )
            enqueue_refresh = AsyncMock(
                return_value={
                    "job_id": "bg:brand_full_knowledge_refresh:BRAND-001",
                    "status": "waiting",
                }
            )
            oss_client = _FakeOSSClient()
            service = AttachmentDraftService(
                AttachmentDraftDependencies(
                    settings=types.SimpleNamespace(upload_staging_dir=temp_dir, dashscope_api_key="test-key", text_llm_model="qwen-plus"),
                    parser=_FakeParser(),
                    oss_client=oss_client,
                    brands=_FakeBrandStore(),
                    brand_products=_FakeBrandProductStore(),
                    brand_knowledge=_FakeBrandKnowledgeStore(),
                    update_knowledge=update_knowledge,
                    enqueue_brand_full_knowledge_refresh_job=enqueue_refresh,
                )
            )

            result = await service._process_confirm_pipeline(
                request=types.SimpleNamespace(
                    review_id=review_id,
                    confirmed_text=None,
                    brand_name=None,
                    knowledge_revision="LXKG-SLPP-V1.0.0-20260630010101",
                ),
                draft_id=draft_id,
                job={
                    "job_id": f"bg:attachment_confirm_pipeline:confirm:{draft_id}:{review_id}",
                    "retry_count": 0,
                    "max_retries": 3,
                },
            )

        uploaded_key = oss_client.uploaded[0]["object_key"]
        self.assertIn(f"示例品牌-{draft_id}-{review_id}-confirmed-knowledge.md", uploaded_key)
        update_request = update_knowledge.await_args.args[0]
        self.assertEqual("attachment_confirm", update_request.source_type)
        self.assertEqual(f"confirm:{draft_id}:{review_id}", update_request.source_task_id)
        self.assertEqual(f"bg:attachment_confirm_pipeline:confirm:{draft_id}:{review_id}", update_request.source_job_id)
        self.assertEqual(uploaded_key, update_request.source_oss_key)
        self.assertEqual(f"示例品牌-{draft_id}-{review_id}-confirmed-knowledge.md", update_request.source_name)
        enqueue_refresh.assert_awaited_once()
        self.assertEqual("BRAND-001", enqueue_refresh.await_args.kwargs["brand_code"])
        self.assertEqual("示例品牌", enqueue_refresh.await_args.kwargs["brand_name"])
        self.assertEqual("attachment_confirm", enqueue_refresh.await_args.kwargs["trigger_source_type"])
        self.assertEqual(f"confirm:{draft_id}:{review_id}", enqueue_refresh.await_args.kwargs["trigger_source_task_id"])
        self.assertEqual(300, enqueue_refresh.await_args.kwargs["delay_seconds"])
        self.assertEqual("bg:brand_full_knowledge_refresh:BRAND-001", result["full_knowledge_refresh_job_id"])

    async def test_review_changes_rejects_expired_draft_and_cleans_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            expired_at = datetime.now() - timedelta(hours=2)
            service = AttachmentDraftService(
                AttachmentDraftDependencies(
                    settings=types.SimpleNamespace(
                        upload_staging_dir=temp_dir,
                        attachment_draft_ttl_seconds=60,
                        dashscope_api_key="test-key",
                        text_llm_model="qwen-plus",
                    ),
                    parser=_FakeParser(),
                    oss_client=types.SimpleNamespace(enabled=False),
                    brands=_FakeBrandStore(),
                    brand_products=_FakeBrandProductStore(),
                    brand_knowledge=_FakeBrandKnowledgeStore(),
                    update_knowledge=AsyncMock(),
                    ingest_text_document=AsyncMock(),
                )
            )

            draft_id = "bad_expired_review"
            draft_dir = Path(temp_dir) / "attachment_parse_drafts" / draft_id
            draft_dir.mkdir(parents=True, exist_ok=True)
            (draft_dir / "draft.json").write_text(
                json.dumps(
                    {
                        "draft_id": draft_id,
                        "brand_name": "示例品牌",
                        "brand_code": "BRAND-001",
                        "draft_status": "pending_review",
                        "created_at": expired_at.isoformat(timespec="seconds"),
                        "updated_at": expired_at.isoformat(timespec="seconds"),
                        "attachments": [],
                        "combined_markdown_text": "# 示例品牌 附件预解析草稿",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            request = types.SimpleNamespace(
                brand_name=None,
                brand_code=None,
                candidate_snapshot={"basic_info": {"advantages": "新优势"}},
                knowledge_revision=None,
            )

            with self.assertRaisesRegex(ValueError, "draft_id 不存在或已过期"):
                await service.review_changes(
                    request=request,
                    draft_id=draft_id,
                )

        self.assertFalse(draft_dir.exists())

    async def test_review_changes_returns_summary_and_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = AttachmentDraftService(
                AttachmentDraftDependencies(
                    settings=types.SimpleNamespace(upload_staging_dir=temp_dir, dashscope_api_key="test-key", text_llm_model="qwen-plus"),
                    parser=_FakeParser(),
                    oss_client=types.SimpleNamespace(enabled=False),
                    brands=_FakeBrandStore(),
                    brand_products=_FakeBrandProductStore(),
                    brand_knowledge=_FakeBrandKnowledgeStore(),
                    update_knowledge=AsyncMock(),
                    ingest_text_document=AsyncMock(),
                )
            )

            draft_id = "bad_review"
            draft_dir = Path(temp_dir) / "attachment_parse_drafts" / draft_id
            draft_dir.mkdir(parents=True, exist_ok=True)
            (draft_dir / "draft.json").write_text(
                json.dumps(
                    {
                        "draft_id": draft_id,
                        "brand_name": "示例品牌",
                        "brand_code": "BRAND-001",
                        "attachments": [
                            {
                                "name": "品牌手册.pdf",
                                "url": "https://example.com/brand-book.pdf",
                                "local_path": str(draft_dir / "downloads" / "001-品牌手册.pdf"),
                            }
                        ],
                        "combined_markdown_text": "# 示例品牌 附件预解析草稿",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            request = types.SimpleNamespace(
                brand_name=None,
                brand_code=None,
                candidate_snapshot={},
                knowledge_revision="LXKG-SLPP-V1.0.0-20260630010101",
            )

            candidate_snapshot = {
                "basic_info": {
                    "brand_name": "示例品牌",
                    "website": ["https://new.example.com"],
                    "extra_info": {
                        "brand_english_name": "Sample Brand",
                        "brand_advantage": ["新优势"],
                        "target_region": ["中国", "日本"],
                    },
                },
                "products": [
                    {
                        "base_info": {
                            "name": "经典产品",
                            "product_description": "新品介绍",
                        }
                    }
                ],
                "company_profile": {
                    "subject_info": "示例企业主体",
                    "company_intro": "新公司简介",
                },
                "management_team": {
                    "members": [
                        {
                            "name": "张三",
                            "title": "CEO",
                            "bio": "创始人兼 CEO",
                        }
                    ]
                },
                "competitors": {
                    "competitors": [
                        {
                            "name": "竞品A",
                            "introduction": "新竞品介绍",
                        }
                    ]
                },
                "sensitive_topics": {
                    "sensitive_contents": ["价格敏感"],
                    "controversial_events": ["需要谨慎表述"],
                    "forbidden_words": ["保本"],
                    "negative_clarifications": ["已有统一口径"],
                    "other_info": [],
                },
                "other_info": [
                    {
                        "title": "停车场信息",
                        "content": "有停车场",
                    }
                ],
            }
            request.candidate_snapshot = candidate_snapshot

            result = await service.review_changes(
                request=request,
                draft_id=draft_id,
            )

        self.assertEqual(draft_id, result["draft_id"])
        self.assertEqual("示例品牌", result["brand_name"])
        self.assertEqual("BRAND-001", result["brand_code"])
        self.assertEqual("LXKG-SLPP-V1.0.0-20260630010101", result["knowledge_revision"])
        self.assertTrue(result["review_id"].startswith("bar_"))
        self.assertGreaterEqual(result["summary"]["added_field_count"], 1)
        self.assertGreaterEqual(result["summary"]["modified_field_count"], 1)
        self.assertEqual(0, result["summary"]["deleted_field_count"])
        self.assertTrue(result["can_confirm"])
        self.assertGreaterEqual(len(result["warnings"]), 1)
        self.assertTrue(any(item["field_path"] == "basic_info.extra_info.brand_advantage" for item in result["changes"]))
        self.assertTrue(any(item["field_path"] == "basic_info.extra_info.brand_english_name" for item in result["changes"]))
        self.assertTrue(any(item["field_path"] == "products[经典产品].base_info.product_description" for item in result["changes"]))
        self.assertTrue(any(item["field_path"] == "competitors.competitors[竞品A].introduction" for item in result["changes"]))
        self.assertTrue(any(item["field_path"] == "other_info[停车场信息].content" for item in result["changes"]))

    async def test_confirm_save_with_review_id_updates_knowledge_without_ingesting_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            update_knowledge = AsyncMock(
                return_value={
                    "brand_id": 1,
                    "updated_sections": ["basic_info", "products", "attachments"],
                    "knowledge_revision": "LXKG-SLPP-V1.1.0-20260630020202",
                }
            )
            ingest_text_document = AsyncMock(return_value=types.SimpleNamespace(document_id="confirmed_doc_2"))
            service = AttachmentDraftService(
                AttachmentDraftDependencies(
                    settings=types.SimpleNamespace(upload_staging_dir=temp_dir, dashscope_api_key="test-key", text_llm_model="qwen-plus"),
                    parser=_FakeParser(),
                    oss_client=types.SimpleNamespace(enabled=False),
                    brands=_FakeBrandStore(),
                    brand_products=_FakeBrandProductStore(),
                    brand_knowledge=_FakeBrandKnowledgeStore(),
                    update_knowledge=update_knowledge,
                    ingest_text_document=ingest_text_document,
                )
            )

            draft_id = "bad_confirm_review"
            draft_dir = Path(temp_dir) / "attachment_parse_drafts" / draft_id
            download_dir = draft_dir / "downloads"
            download_dir.mkdir(parents=True, exist_ok=True)
            local_attachment = download_dir / "001-品牌手册.pdf"
            local_attachment.write_bytes(b"demo attachment")
            (draft_dir / "draft.json").write_text(
                json.dumps(
                    {
                        "draft_id": draft_id,
                        "brand_name": "示例品牌",
                        "brand_code": "BRAND-001",
                        "attachments": [
                            {
                                "name": "品牌手册.pdf",
                                "url": "https://example.com/brand-book.pdf",
                                "local_path": str(local_attachment),
                            }
                        ],
                        "combined_markdown_text": "# 示例品牌 附件预解析草稿",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            candidate_snapshot = {
                "basic_info": {
                    "brand_name": "示例品牌",
                    "brand_code": "BRAND-001",
                    "website": ["https://new.example.com"],
                    "advantages": "新优势",
                },
                "products": [
                    {
                        "name": "经典产品",
                        "product_description": "新品介绍",
                    }
                ],
                "company_profile": {},
                "management_team": [],
                "competitors": [
                    {
                        "name": "竞品A",
                        "competitors_description": "新竞品介绍",
                    }
                ],
                "authority_honors": [],
                "customers_cases": [],
                "sensitive_topics": {},
                "other_info": [
                    {
                        "title": "停车场信息",
                        "content": "有地下停车场",
                    }
                ],
            }

            review_request = types.SimpleNamespace(
                brand_name=None,
                brand_code=None,
                candidate_snapshot=candidate_snapshot,
                knowledge_revision="LXKG-SLPP-V1.0.0-20260630010101",
            )

            review_result = await service.review_changes(
                request=review_request,
                draft_id=draft_id,
            )

            confirm_request = types.SimpleNamespace(
                review_id=review_result["review_id"],
                confirmed_text=None,
                brand_name=None,
                knowledge_revision=review_result["knowledge_revision"],
            )

            result = await service._process_confirm_pipeline(
                request=confirm_request,
                draft_id=draft_id,
            )

        self.assertEqual("示例品牌", result["brand_name"])
        self.assertEqual(1, result["brand_id"])
        self.assertEqual(["basic_info", "products", "attachments"], result["updated_sections"])
        self.assertEqual("LXKG-SLPP-V1.1.0-20260630020202", result["knowledge_revision"])
        self.assertIsNone(result["final_document_id"])
        self.assertEqual([], result["original_attachments"])
        self.assertEqual([], result["attachment_documents"])
        update_knowledge.assert_awaited_once()
        update_request = update_knowledge.await_args.args[0]
        self.assertEqual("示例品牌", _value_from_object_or_dict(update_request.basic_info, "brand_name"))
        self.assertEqual("BRAND-001", _value_from_object_or_dict(update_request.basic_info, "brand_code"))
        self.assertEqual("经典产品", _value_from_object_or_dict(update_request.products[0], "name"))
        self.assertEqual("竞品A", update_request.competitors[0]["name"])
        update_other_info = {
            item["title"]: item["content"]
            for item in update_request.other_info
        }
        self.assertEqual("有地下停车场", update_other_info["停车场信息"])
        self.assertEqual("每晚开放", update_other_info["夜游说明"])
        ingest_text_document.assert_not_awaited()

    async def test_confirm_pipeline_terminal_failure_cleans_draft_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            update_knowledge = AsyncMock(side_effect=RuntimeError("update failed"))
            service = AttachmentDraftService(
                AttachmentDraftDependencies(
                    settings=types.SimpleNamespace(upload_staging_dir=temp_dir, dashscope_api_key="test-key", text_llm_model="qwen-plus"),
                    parser=_FakeParser(),
                    oss_client=types.SimpleNamespace(enabled=False),
                    brands=_FakeBrandStore(),
                    brand_products=_FakeBrandProductStore(),
                    brand_knowledge=_FakeBrandKnowledgeStore(),
                    update_knowledge=update_knowledge,
                    ingest_text_document=AsyncMock(),
                )
            )

            draft_id = "bad_confirm_terminal_failure"
            draft_dir = Path(temp_dir) / "attachment_parse_drafts" / draft_id
            review_dir = draft_dir / "reviews"
            review_dir.mkdir(parents=True, exist_ok=True)
            now_text = datetime.now().isoformat(timespec="seconds")
            (draft_dir / "draft.json").write_text(
                json.dumps(
                    {
                        "draft_id": draft_id,
                        "brand_name": "示例品牌",
                        "brand_code": "BRAND-001",
                        "draft_status": "confirming",
                        "created_at": now_text,
                        "updated_at": now_text,
                        "attachments": [],
                        "combined_markdown_text": "# 示例品牌 附件预解析草稿",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (review_dir / "bar_terminal_failure.json").write_text(
                json.dumps(
                    {
                        "review_id": "bar_terminal_failure",
                        "draft_id": draft_id,
                        "brand_code": "BRAND-001",
                        "brand_name": "示例品牌",
                        "knowledge_revision": "LXKG-SLPP-V1.0.0-20260630010101",
                        "update_request_payload": {
                            "basic_info": {
                                "brand_name": "示例品牌",
                                "brand_code": "BRAND-001",
                            },
                            "attachments": [],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "update failed"):
                await service._process_confirm_pipeline(
                    request=types.SimpleNamespace(
                        review_id="bar_terminal_failure",
                        confirmed_text=None,
                        brand_name=None,
                        knowledge_revision="LXKG-SLPP-V1.0.0-20260630010101",
                    ),
                    draft_id=draft_id,
                    job={"retry_count": 0, "max_retries": 0},
                )

        self.assertFalse(draft_dir.exists())

    async def test_confirm_save_writes_new_attachment_products_to_brand_knowledge_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            update_knowledge = AsyncMock(
                return_value={
                    "brand_id": 1,
                    "updated_sections": ["basic_info", "products", "attachments"],
                    "knowledge_revision": "LXKG-SLPP-V1.1.0-20260630020202",
                }
            )
            ingest_text_document = AsyncMock(return_value=types.SimpleNamespace(document_id="confirmed_doc_3"))
            brand_knowledge = _FakeBrandKnowledgeStore()
            service = AttachmentDraftService(
                AttachmentDraftDependencies(
                    settings=types.SimpleNamespace(upload_staging_dir=temp_dir, dashscope_api_key="test-key", text_llm_model="qwen-plus"),
                    parser=_FakeParser(),
                    oss_client=types.SimpleNamespace(enabled=False),
                    brands=_FakeBrandStore(),
                    brand_products=_FakeBrandProductStore(),
                    brand_knowledge=brand_knowledge,
                    update_knowledge=update_knowledge,
                    ingest_text_document=ingest_text_document,
                )
            )

            draft_id = "bad_confirm_new_attachment_product"
            draft_dir = Path(temp_dir) / "attachment_parse_drafts" / draft_id
            download_dir = draft_dir / "downloads"
            download_dir.mkdir(parents=True, exist_ok=True)
            local_attachment = download_dir / "001-品牌手册.pdf"
            local_attachment.write_bytes(b"demo attachment")
            (draft_dir / "draft.json").write_text(
                json.dumps(
                    {
                        "draft_id": draft_id,
                        "brand_name": "示例品牌",
                        "brand_code": "BRAND-001",
                        "attachments": [
                            {
                                "name": "品牌手册.pdf",
                                "url": "https://example.com/brand-book.pdf",
                                "local_path": str(local_attachment),
                            }
                        ],
                        "combined_markdown_text": "# 示例品牌 附件预解析草稿",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            review_result = await service.review_changes(
                request=types.SimpleNamespace(
                    brand_name=None,
                    brand_code=None,
                    candidate_snapshot={
                        "basic_info": {
                            "brand_name": "示例品牌",
                            "brand_code": "BRAND-001",
                        },
                        "products": [
                            {
                                "name": "经典产品",
                                "product_description": "经典产品附件补充介绍",
                            }
                        ],
                        "other_info": [
                            {
                                "title": "附件解析新增产品",
                                "content": [
                                    {
                                        "name": "附件新品",
                                        "product_description": "附件解析出来的新产品",
                                        "product_website": "https://example.com/new-product",
                                    }
                                ],
                            }
                        ],
                        "company_profile": {},
                        "management_team": [],
                        "competitors": [],
                        "authority_honors": [],
                        "customers_cases": [],
                        "sensitive_topics": {},
                    },
                    knowledge_revision="LXKG-SLPP-V1.0.0-20260630010101",
                ),
                draft_id=draft_id,
            )

            result = await service._process_confirm_pipeline(
                request=types.SimpleNamespace(
                    review_id=review_result["review_id"],
                    confirmed_text=None,
                    brand_name=None,
                    knowledge_revision=review_result["knowledge_revision"],
                ),
                draft_id=draft_id,
            )

        self.assertIn("attachment_products", result["updated_sections"])
        update_request = update_knowledge.await_args.args[0]
        self.assertEqual(["经典产品"], [_value_from_object_or_dict(product, "name") for product in update_request.products])
        attachment_products_upsert = next(
            item for item in brand_knowledge.last_knowledge_upserts
            if item["knowledge_type"] == "attachment_products"
        )
        self.assertEqual(
            [
                {
                    "name": "附件新品",
                    "product_alias": None,
                    "product_description": "附件解析出来的新产品",
                    "product_website": "https://example.com/new-product",
                    "product_images": [],
                    "price_info": None,
                    "coverage_regions": [],
                    "product_advantages": None,
                    "target_scenarios": None,
                    "service_standard": None,
                    "service_process": None,
                    "cases_and_reputation": None,
                    "certification_info": None,
                    "core_technology": None,
                    "other_info": None,
                }
            ],
            attachment_products_upsert["content_json"],
        )
