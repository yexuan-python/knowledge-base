from __future__ import annotations

from tests.fakes.attachment_preview_flow import *


class AttachmentPreviewParseCoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_attachment_preview_review_confirm_pipeline_chain_returns_queryable_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            update_knowledge = AsyncMock(
                return_value={
                    "brand_id": 1,
                    "brand_code": "BRAND-001",
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

            async def _enqueue_pipeline(**kwargs):
                return {
                    "job_id": f"bg:attachment_confirm_pipeline:confirm:{kwargs['draft_id']}:{kwargs['review_id']}",
                    "status": "waiting",
                }

            enqueue_pipeline = AsyncMock(side_effect=_enqueue_pipeline)
            oss_client = _FakeOSSClient()
            service = AttachmentDraftService(
                AttachmentDraftDependencies(
                    settings=types.SimpleNamespace(
                        upload_staging_dir=temp_dir,
                        dashscope_api_key="test-key",
                        text_llm_model="qwen-plus",
                    ),
                    parser=_FakeParser(),
                    oss_client=oss_client,
                    brands=_FakeBrandStore(),
                    brand_products=_FakeBrandProductStore(),
                    brand_knowledge=_FakeBrandKnowledgeStore(),
                    update_knowledge=update_knowledge,
                    enqueue_brand_full_knowledge_refresh_job=enqueue_refresh,
                    enqueue_attachment_confirm_pipeline_job=enqueue_pipeline,
                )
            )

            async def _fake_download_attachment(*, url: str, destination: Path) -> None:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(f"downloaded from {url}".encode("utf-8"))

            with (
                patch.object(service, "_download_attachment", new=AsyncMock(side_effect=_fake_download_attachment)),
                patch(
                    "knowledge_base.brand_knowledge.application.attachment_flow.extract_brand_knowledge_from_markdown",
                    new=AsyncMock(
                        return_value={
                            "basic_info": {
                                "email": "new-brand@example.com",
                                "advantages": "附件确认后的新优势",
                            },
                            "other_info": {
                                "停车场信息": "有地下停车场",
                            },
                        }
                    ),
                ),
            ):
                preview_result = await service.preview_parse(
                    brand_name="示例品牌",
                    brand_code="BRAND-001",
                    attachments=[
                        {
                            "name": "品牌手册.pdf",
                            "url": "https://example.com/brand-book.pdf",
                        }
                    ],
                )

            review_result = await service.review_changes(
                request=types.SimpleNamespace(
                    brand_name=None,
                    brand_code=None,
                    candidate_snapshot=preview_result["candidate_snapshot"],
                    knowledge_revision=preview_result["knowledge_revision"],
                ),
                draft_id=preview_result["draft_id"],
            )
            confirm_result = await service.confirm_save(
                request=types.SimpleNamespace(
                    review_id=review_result["review_id"],
                    confirmed_text=None,
                    brand_name=None,
                    knowledge_revision=review_result["knowledge_revision"],
                ),
                draft_id=preview_result["draft_id"],
            )

            pipeline_job_payload = dict(enqueue_pipeline.await_args.kwargs)
            pipeline_result = await service.process_confirm_pipeline_job(
                payload=pipeline_job_payload,
                job={
                    "job_id": confirm_result["background_job_id"],
                    "retry_count": 0,
                    "max_retries": 3,
                },
            )

        self.assertEqual("示例品牌", preview_result["brand_name"])
        self.assertTrue(preview_result["draft_id"].startswith("bad_"))
        self.assertTrue(review_result["review_id"].startswith("bar_"))
        self.assertTrue(review_result["can_confirm"])
        self.assertEqual("waiting", confirm_result["background_job_status"])
        self.assertEqual(
            f"bg:attachment_confirm_pipeline:confirm:{preview_result['draft_id']}:{review_result['review_id']}",
            confirm_result["background_job_id"],
        )
        enqueue_pipeline.assert_awaited_once()
        self.assertEqual(preview_result["draft_id"], pipeline_job_payload["draft_id"])
        self.assertEqual(review_result["review_id"], pipeline_job_payload["review_id"])

        update_request = update_knowledge.await_args.args[0]
        self.assertEqual("attachment_confirm", update_request.source_type)
        self.assertEqual(
            f"confirm:{preview_result['draft_id']}:{review_result['review_id']}",
            update_request.source_task_id,
        )
        self.assertEqual(confirm_result["background_job_id"], update_request.source_job_id)
        self.assertEqual("success", pipeline_result["status"])
        self.assertEqual("BRAND-001", pipeline_result["brand_code"])
        self.assertEqual("示例品牌", pipeline_result["brand_name"])
        self.assertEqual(["basic_info", "attachments"], pipeline_result["updated_sections"])
        self.assertEqual("LXKG-SLPP-V1.0.1-20260630020202", pipeline_result["knowledge_revision"])
        self.assertEqual("bg:brand_full_knowledge_refresh:BRAND-001", pipeline_result["full_knowledge_refresh_job_id"])
        self.assertEqual("waiting", pipeline_result["full_knowledge_refresh_status"])
        self.assertEqual("skipped", pipeline_result["confirm_callback_status"])
        self.assertEqual(1, len(oss_client.uploaded))
        self.assertIn(
            f"示例品牌-{preview_result['draft_id']}-{review_result['review_id']}-confirmed-knowledge.md",
            oss_client.uploaded[0]["object_key"],
        )
        enqueue_refresh.assert_awaited_once()
        self.assertEqual("attachment_confirm", enqueue_refresh.await_args.kwargs["trigger_source_type"])
        self.assertEqual(
            f"confirm:{preview_result['draft_id']}:{review_result['review_id']}",
            enqueue_refresh.await_args.kwargs["trigger_source_task_id"],
        )

        class _FakeBackgroundJobStore:
            def get_job(self, job_id: str) -> dict:
                return {
                    "job_id": job_id,
                    "job_type": "attachment_confirm_pipeline",
                    "source_type": "attachment_confirm",
                    "source_id": f"confirm:{preview_result['draft_id']}:{review_result['review_id']}",
                    "status": "success",
                    "priority": 100,
                    "retry_count": 0,
                    "max_retries": 3,
                    "next_retry_at": None,
                    "locked_by": None,
                    "locked_at": None,
                    "last_error_message": None,
                    "started_at": None,
                    "finished_at": None,
                    "created_at": None,
                    "updated_at": None,
                    "payload_json": json.dumps(pipeline_job_payload, ensure_ascii=False),
                    "result_json": json.dumps(pipeline_result, ensure_ascii=False),
                }

        query_service = KnowledgeBaseService.__new__(KnowledgeBaseService)
        query_service._background_jobs = _FakeBackgroundJobStore()

        query_result = query_service.get_attachment_confirm_result(confirm_result["background_job_id"])

        self.assertEqual(0, query_result["code"])
        self.assertEqual("ok", query_result["message"])
        self.assertEqual("BRAND-001", query_result["data"]["brand_code"])
        self.assertEqual("示例品牌", query_result["data"]["brand_name"])
        self.assertEqual("LXKG-SLPP-V1.0.1-20260630020202", query_result["data"]["knowledge_revision"])
        self.assertEqual("bg:brand_full_knowledge_refresh:BRAND-001", query_result["data"]["full_knowledge_refresh_job_id"])

    async def test_preview_parse_returns_candidate_snapshot_and_keeps_internal_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = AttachmentDraftService(
                AttachmentDraftDependencies(
                    settings=types.SimpleNamespace(upload_staging_dir=temp_dir),
                    parser=_FakeParser(),
                    oss_client=types.SimpleNamespace(),
                    brands=None,
                    brand_products=None,
                    brand_knowledge=None,
                    update_knowledge=AsyncMock(),
                    ingest_text_document=AsyncMock(),
                )
            )

            async def _fake_download_attachment(*, url: str, destination: Path) -> None:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(f"downloaded from {url}".encode("utf-8"))

            with patch.object(service, "_download_attachment", new=AsyncMock(side_effect=_fake_download_attachment)):
                with patch(
                    "knowledge_base.brand_knowledge.application.attachment_flow.extract_brand_knowledge_from_markdown",
                    new=AsyncMock(
                        return_value={
                            "basic_info": {
                                "advantages": "新优势",
                                "customer_service_hotline": "400-100-200",
                                "official_wechat_account": "示例公众号",
                                "english_name": None,
                                "email": "hello@example.com",
                                "website": [],
                            },
                            "company_profile": {
                                "established_time": "2018年",
                                "brand_subject_name": "示例主体公司",
                                "business_license_image_path": "https://example.com/license.png",
                                "registered_capital": "100万元",
                                "company_intro": None,
                            },
                            "products": [
                                {
                                    "name": "示例产品",
                                    "product_website": "https://example.com/product",
                                    "product_advantages": "高效稳定",
                                }
                            ],
                            "other_info": {
                                "所属行业": "企业通用服务",
                                "品牌名称": "示例品牌",
                                "brand_name": "示例品牌",
                                "停车场信息": "有停车场",
                                "English Section": "英文标题内容",
                                "空信息": "",
                            },
                        }
                    ),
                ):
                    result = await service.preview_parse(
                        brand_name="示例品牌",
                        brand_code="BRAND-001",
                        attachments=[
                            {
                                "name": "品牌手册.pdf",
                                "url": "https://example.com/brand-book.pdf",
                            }
                        ],
                    )

            self.assertEqual("示例品牌", result["brand_name"])
            self.assertNotIn("attachments", result)
            self.assertNotIn("current_snapshot", result)
            self.assertNotIn("combined_markdown_text", result)
            self.assertEqual("品牌基础信息", result["field_labels"]["basic_info"])
            self.assertEqual("邮箱", result["field_labels"]["basic_info.email"])
            self.assertEqual("所属行业", result["field_labels"]["basic_info.industry_id"])
            self.assertEqual("品牌优势", result["field_labels"]["basic_info.extra_info.brand_advantage"])
            self.assertEqual("公司信息", result["field_labels"]["company_profile"])
            self.assertEqual("成立时间", result["field_labels"]["company_profile.founded_at"])
            self.assertNotIn("products", result["field_labels"])
            self.assertNotIn("products[].base_info.name", result["field_labels"])
            self.assertNotIn("products[].base_info.product_link", result["field_labels"])
            self.assertNotIn("products[].knowledge.advantages", result["field_labels"])
            self.assertNotIn("basic_info.website", result["field_labels"])
            self.assertNotIn("basic_info.extra_info.brand_english_name", result["field_labels"])
            self.assertNotIn("company_profile.company_intro", result["field_labels"])
            self.assertNotIn("other_info", result["field_labels"])
            self.assertNotIn("other_info[].title", result["field_labels"])
            self.assertNotIn("other_info[].content", result["field_labels"])
            self.assertEqual("产品名称", result["field_labels"]["other_info[].content[].name"])
            self.assertEqual("产品网站", result["field_labels"]["other_info[].content[].product_website"])
            self.assertEqual("产品优势", result["field_labels"]["other_info[].content[].product_advantages"])
            self.assertEqual("hello@example.com", result["candidate_snapshot"]["basic_info"]["email"])
            self.assertEqual("企业通用服务", result["candidate_snapshot"]["basic_info"]["industry_id"])
            self.assertEqual(["新优势"], result["candidate_snapshot"]["basic_info"]["extra_info"]["brand_advantage"])
            self.assertEqual("示例公众号", result["candidate_snapshot"]["basic_info"]["extra_info"]["official_wechat"])
            self.assertNotIn("brand_english_name", result["candidate_snapshot"]["basic_info"]["extra_info"])
            self.assertNotIn("website", result["candidate_snapshot"]["basic_info"])
            self.assertEqual("2018年", result["candidate_snapshot"]["company_profile"]["founded_at"])
            self.assertNotIn("company_intro", result["candidate_snapshot"]["company_profile"])
            self.assertNotIn("products", result["candidate_snapshot"])
            self.assertEqual(
                [
                    {"title": "停车场信息", "content": "有停车场"},
                    {"title": "其他信息", "content": "英文标题内容"},
                    {
                        "title": "附件解析新增产品",
                        "content": [
                            {
                                "name": "示例产品",
                                "product_website": "https://example.com/product",
                                "product_advantages": "高效稳定",
                            }
                        ],
                    },
                ],
                result["candidate_snapshot"]["other_info"],
            )
            draft_manifest = json.loads(
                (Path(temp_dir) / "attachment_parse_drafts" / result["draft_id"] / "draft.json").read_text(encoding="utf-8")
            )
            self.assertEqual(1, len(draft_manifest["attachments"]))
            self.assertEqual("success", draft_manifest["attachments"][0]["status"])
            self.assertEqual("示例产品", draft_manifest["candidate_snapshot"]["products"][0]["name"])
            self.assertEqual("# 品牌手册.pdf\n这里是品牌附件正文", draft_manifest["combined_markdown_text"])

    def test_split_line_text_values_keeps_long_text_punctuation(self) -> None:
        self.assertEqual(
            AttachmentDraftService._split_line_text_values(
                "1. 安全:严格遵循国家校服标准,采用环保安全材质,守护学生健康;\n"
                "2. 舒适:采用先进面料与工艺,保障学生日常校园活动的穿着体验",
            ),
            [
                "1. 安全:严格遵循国家校服标准,采用环保安全材质,守护学生健康;",
                "2. 舒适:采用先进面料与工艺,保障学生日常校园活动的穿着体验",
            ],
        )

    async def test_preview_parse_returns_empty_snapshot_when_all_attachments_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = AttachmentDraftService(
                AttachmentDraftDependencies(
                    settings=types.SimpleNamespace(upload_staging_dir=temp_dir),
                    parser=_FakeParser(),
                    oss_client=types.SimpleNamespace(),
                    brands=None,
                    brand_products=None,
                    brand_knowledge=None,
                    update_knowledge=AsyncMock(),
                    ingest_text_document=AsyncMock(),
                )
            )

            with patch.object(
                service,
                "_parse_attachment",
                new=AsyncMock(
                    return_value={
                        "name": "品牌资料.pdf",
                        "url": "https://example.com/missing.pdf",
                        "status": "failed",
                        "error_message": "404 Not Found",
                    }
                ),
            ):
                result = await service.preview_parse(
                    brand_name="示例品牌",
                    brand_code="BRAND-001",
                    attachments=[
                        {
                            "name": "品牌资料.pdf",
                            "url": "https://example.com/missing.pdf",
                        }
                    ],
                )

            self.assertEqual("示例品牌", result["brand_name"])
            self.assertEqual({}, result["candidate_snapshot"])
            self.assertEqual({}, result["field_labels"])
            self.assertIn("draft_id", result)

    async def test_preview_parse_only_returns_unknown_products_as_attachment_new_products(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            brand_knowledge = _FakeBrandKnowledgeStore()
            brand_knowledge._rows.append(
                {
                    "knowledge_type": "attachment_products",
                    "content_json": json.dumps(
                        [
                            {
                                "name": "已有附件产品",
                                "product_description": "之前已经从附件解析入库",
                            }
                        ],
                        ensure_ascii=False,
                    ),
                }
            )
            service = AttachmentDraftService(
                AttachmentDraftDependencies(
                    settings=types.SimpleNamespace(upload_staging_dir=temp_dir),
                    parser=_FakeParser(),
                    oss_client=types.SimpleNamespace(),
                    brands=_FakeBrandStore(),
                    brand_products=_FakeBrandProductStore(),
                    brand_knowledge=brand_knowledge,
                    update_knowledge=AsyncMock(),
                    ingest_text_document=AsyncMock(),
                )
            )

            async def _fake_download_attachment(*, url: str, destination: Path) -> None:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(f"downloaded from {url}".encode("utf-8"))

            with patch.object(service, "_download_attachment", new=AsyncMock(side_effect=_fake_download_attachment)):
                with patch(
                    "knowledge_base.brand_knowledge.application.attachment_flow.extract_brand_knowledge_from_markdown",
                    new=AsyncMock(
                        return_value={
                            "products": [
                                {
                                    "name": "经典产品",
                                    "product_description": "正式产品的附件补充",
                                },
                                {
                                    "name": "已有附件产品",
                                    "product_description": "重复附件产品不应再次返回",
                                },
                                {
                                    "name": "附件新品",
                                    "product_description": "这才是真正新增的附件产品",
                                },
                            ],
                            "other_info": {
                                "所属行业": "企业通用服务",
                            },
                        }
                    ),
                ):
                    result = await service.preview_parse(
                        brand_name="示例品牌",
                        brand_code="BRAND-001",
                        attachments=[
                            {
                                "name": "品牌手册.pdf",
                                "url": "https://example.com/brand-book.pdf",
                            }
                        ],
                    )

            self.assertEqual("企业通用服务", result["candidate_snapshot"]["basic_info"]["industry_id"])
            self.assertEqual(["经典产品"], [
                item["base_info"]["name"]
                for item in result["candidate_snapshot"].get("products", [])
            ])
            self.assertEqual(
                [
                    {
                        "title": "附件解析新增产品",
                        "content": [
                            {
                                "name": "附件新品",
                                "product_description": "这才是真正新增的附件产品",
                            }
                        ],
                    }
                ],
                result["candidate_snapshot"].get("other_info"),
            )
            self.assertEqual("产品名称", result["field_labels"]["other_info[].content[].name"])
            self.assertEqual("产品介绍", result["field_labels"]["other_info[].content[].product_description"])

    def test_preview_field_labels_fallback_for_unknown_other_info_content_keys(self) -> None:
        service = AttachmentDraftService(
            AttachmentDraftDependencies(
                settings=types.SimpleNamespace(upload_staging_dir="/tmp"),
                parser=_FakeParser(),
                oss_client=types.SimpleNamespace(),
                brands=None,
                brand_products=None,
                brand_knowledge=None,
                update_knowledge=AsyncMock(),
                ingest_text_document=AsyncMock(),
            )
        )

        labels = service._build_preview_field_labels(
            {
                "other_info": [
                    {
                        "title": "附件解析新增产品",
                        "content": [
                            {
                                "name": "附件新品",
                                "usage_method": "开碗即食",
                                "ingredient_highlights": "含唾液酸和低聚果糖",
                                "llm_custom_field": "模型额外字段",
                            }
                        ],
                    }
                ]
            }
        )

        self.assertEqual("产品名称", labels["other_info[].content[].name"])
        self.assertEqual("食用/使用方法", labels["other_info[].content[].usage_method"])
        self.assertEqual("成分亮点", labels["other_info[].content[].ingredient_highlights"])
        self.assertEqual("补充信息", labels["other_info[].content[].llm_custom_field"])

    def test_review_change_field_labels_hide_structural_containers(self) -> None:
        self.assertEqual(
            "产品[灵犀GEO] / 核心技术/专利名称",
            AttachmentDraftService._build_diff_field_label(
                "products[灵犀GEO].knowledge.technologies_patents"
            ),
        )
        self.assertEqual(
            "产品[灵犀GEO] / 适用场景/人群",
            AttachmentDraftService._build_diff_field_label("products[灵犀GEO].knowledge.scenarios"),
        )
        self.assertEqual(
            "产品[灵犀GEO] / 产品网站",
            AttachmentDraftService._build_diff_field_label("products[灵犀GEO].base_info.product_link"),
        )
        self.assertEqual(
            "管理团队 / 名称",
            AttachmentDraftService._build_diff_field_label("management_team.members[王芳].name"),
        )
        self.assertEqual(
            "管理团队 / 成员介绍",
            AttachmentDraftService._build_diff_field_label("management_team.members[李敏].bio"),
        )
        self.assertEqual(
            "竞品信息 / 优势",
            AttachmentDraftService._build_diff_field_label("competitors.competitors[竞品A].strengths"),
        )

    def test_other_info_nested_non_product_content_is_flattened_to_text(self) -> None:
        service = AttachmentDraftService(
            AttachmentDraftDependencies(
                settings=types.SimpleNamespace(upload_staging_dir="/tmp"),
                parser=_FakeParser(),
                oss_client=types.SimpleNamespace(),
                brands=None,
                brand_products=None,
                brand_knowledge=None,
                update_knowledge=AsyncMock(),
                ingest_text_document=AsyncMock(),
            )
        )

        normalized = service._normalize_other_info_for_merge(
            [
                {
                    "title": "术语表",
                    "content": [
                        [
                            [
                                [
                                    {"title": "其他信息", "content": "其他信息"},
                                    {"title": "其他信息二", "content": "其他信息"},
                                ],
                                [
                                    {"title": "其他信息", "content": "其他信息二"},
                                    {"title": "其他信息二", "content": "燕窝酸(唾液酸)"},
                                ],
                            ],
                            [
                                [
                                    {"title": "其他信息", "content": "其他信息"},
                                    {"title": "其他信息二", "content": "其他信息二"},
                                ],
                                [
                                    {"title": "其他信息", "content": "其他信息二"},
                                    {"title": "其他信息二", "content": "燕窝酸,是燕窝独有的核心标志性活性营养。"},
                                ],
                            ],
                        ]
                    ],
                }
            ]
        )

        self.assertEqual(
            [
                {
                    "title": "术语表",
                    "content": "燕窝酸(唾液酸)\n燕窝酸,是燕窝独有的核心标志性活性营养。",
                }
            ],
            normalized,
        )
        self.assertNotIn("其他信息", normalized[0]["content"])
        self.assertIsInstance(normalized[0]["content"], str)

    def test_attachment_new_products_other_info_content_keeps_product_objects(self) -> None:
        service = AttachmentDraftService(
            AttachmentDraftDependencies(
                settings=types.SimpleNamespace(upload_staging_dir="/tmp"),
                parser=_FakeParser(),
                oss_client=types.SimpleNamespace(),
                brands=None,
                brand_products=None,
                brand_knowledge=None,
                update_knowledge=AsyncMock(),
                ingest_text_document=AsyncMock(),
            )
        )

        normalized = service._normalize_other_info_for_merge(
            [
                {
                    "title": "附件解析新增产品",
                    "content": [
                        {
                            "产品名称": "附件新品",
                            "产品介绍": "附件解析出来的新产品",
                            "产品网站": "https://example.com/new-product",
                        }
                    ],
                }
            ]
        )

        self.assertEqual("附件解析新增产品", normalized[0]["title"])
        self.assertIsInstance(normalized[0]["content"], list)
        self.assertIsInstance(normalized[0]["content"][0], dict)
        self.assertEqual("附件新品", normalized[0]["content"][0]["name"])
        self.assertEqual("附件解析出来的新产品", normalized[0]["content"][0]["product_description"])
        self.assertEqual("https://example.com/new-product", normalized[0]["content"][0]["product_website"])
        self.assertEqual([], normalized[0]["content"][0]["product_images"])

    def test_authority_honor_awarded_at_prefers_specific_date_from_description(self) -> None:
        service = AttachmentDraftService(
            AttachmentDraftDependencies(
                settings=types.SimpleNamespace(upload_staging_dir="/tmp"),
                parser=_FakeParser(),
                oss_client=types.SimpleNamespace(),
                brands=None,
                brand_products=None,
                brand_knowledge=None,
                update_knowledge=AsyncMock(),
                ingest_text_document=AsyncMock(),
            )
        )

        internal_snapshot = service._normalize_candidate_snapshot_input(
            {
                "authority_honors": {
                    "honors": [
                        {
                            "title": "中国燕窝行业首家上市公司",
                            "descriptions": [
                                "2023年12月12日,燕之屋(01497.HK)在香港交易所主板上市。"
                            ],
                            "awarded_at": "2023",
                        },
                        {
                            "title": "高端燕窝连续十年全国销售第一",
                            "descriptions": [
                                "中国境内2016~2025年全年终端零售额分别统计;于2026年3月30日完成调研。"
                            ],
                            "awarded_at": "2016-2025",
                        },
                    ]
                }
            }
        )
        external_snapshot = service._build_external_candidate_snapshot(internal_snapshot)

        self.assertEqual(
            "2023年12月12日",
            external_snapshot["authority_honors"]["honors"][0]["awarded_at"],
        )
        self.assertEqual(
            "2016-2025",
            external_snapshot["authority_honors"]["honors"][1]["awarded_at"],
        )

    async def test_preview_parse_preserves_input_order_under_concurrency(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = AttachmentDraftService(
                AttachmentDraftDependencies(
                    settings=types.SimpleNamespace(upload_staging_dir=temp_dir),
                    parser=_FakeParser(),
                    oss_client=types.SimpleNamespace(),
                    brands=None,
                    brand_products=None,
                    brand_knowledge=None,
                    update_knowledge=AsyncMock(),
                    ingest_text_document=AsyncMock(),
                )
            )

            async def _fake_download_attachment(*, url: str, destination: Path) -> None:
                delay = 0.05 if "first" in url else 0.01
                await asyncio.sleep(delay)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(f"downloaded from {url}".encode("utf-8"))

            with patch.object(service, "_download_attachment", new=AsyncMock(side_effect=_fake_download_attachment)):
                with patch(
                    "knowledge_base.brand_knowledge.application.attachment_flow.extract_brand_knowledge_from_markdown",
                    new=AsyncMock(return_value={}),
                ):
                    result = await service.preview_parse(
                        brand_name="示例品牌",
                        brand_code="BRAND-001",
                        attachments=[
                            {
                                "name": "A.pdf",
                                "url": "https://example.com/first.pdf",
                            },
                            {
                                "name": "B.pdf",
                                "url": "https://example.com/second.pdf",
                            },
                        ],
                    )

            self.assertNotIn("attachments", result)
            draft_manifest = json.loads(
                (Path(temp_dir) / "attachment_parse_drafts" / result["draft_id"] / "draft.json").read_text(encoding="utf-8")
            )
            self.assertEqual(["A.pdf", "B.pdf"], [item["name"] for item in draft_manifest["attachments"]])
            self.assertEqual(
                "# A.pdf\n这里是品牌附件正文\n\n# B.pdf\n这里是品牌附件正文",
                draft_manifest["combined_markdown_text"],
            )

    def test_preview_parse_uses_safer_default_max_concurrency(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = AttachmentDraftService(
                AttachmentDraftDependencies(
                    settings=types.SimpleNamespace(upload_staging_dir=temp_dir),
                    parser=_FakeParser(),
                    oss_client=types.SimpleNamespace(),
                    brands=None,
                    brand_products=None,
                    brand_knowledge=None,
                    update_knowledge=AsyncMock(),
                    ingest_text_document=AsyncMock(),
                )
            )

            self.assertEqual(3, service._preview_parse_max_concurrency(10))
            self.assertEqual(2, service._preview_parse_max_concurrency(2))

    async def test_preview_parse_uses_configured_concurrency_for_multiple_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = AttachmentDraftService(
                AttachmentDraftDependencies(
                    settings=types.SimpleNamespace(
                        upload_staging_dir=temp_dir,
                        attachment_preview_parse_max_concurrency=4,
                    ),
                    parser=_FakeParser(),
                    oss_client=types.SimpleNamespace(),
                    brands=None,
                    brand_products=None,
                    brand_knowledge=None,
                    update_knowledge=AsyncMock(),
                    ingest_text_document=AsyncMock(),
                )
            )

            active_downloads = 0
            max_active_downloads = 0

            async def _fake_download_attachment(*, url: str, destination: Path) -> None:
                nonlocal active_downloads, max_active_downloads
                active_downloads += 1
                max_active_downloads = max(max_active_downloads, active_downloads)
                await asyncio.sleep(0.03)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(f"downloaded from {url}".encode("utf-8"))
                active_downloads -= 1

            with patch.object(service, "_download_attachment", new=AsyncMock(side_effect=_fake_download_attachment)):
                with patch(
                    "knowledge_base.brand_knowledge.application.attachment_flow.extract_brand_knowledge_from_markdown",
                    new=AsyncMock(return_value={}),
                ):
                    await service.preview_parse(
                        brand_name="示例品牌",
                        brand_code="BRAND-001",
                        attachments=[
                            {"name": "A.pdf", "url": "https://example.com/a.pdf"},
                            {"name": "B.pdf", "url": "https://example.com/b.pdf"},
                            {"name": "C.pdf", "url": "https://example.com/c.pdf"},
                            {"name": "D.pdf", "url": "https://example.com/d.pdf"},
                        ],
                    )

            self.assertEqual(4, max_active_downloads)
