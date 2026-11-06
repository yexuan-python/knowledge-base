from __future__ import annotations

import unittest

from knowledge_base.brand_knowledge.schemas.requests import (
    BrandAttachmentConflictResolutionSubmitRequest,
    BrandKnowledgeSessionCreateRequest,
)
from knowledge_base.brand_knowledge.application.publish_mode import (
    attachment_conflict_session_kind_for_publish_mode,
    is_attachment_conflict_session_kind,
    is_draft_only_publish_mode,
    normalize_publish_mode,
    publish_mode_from_attachment_conflict_session_kind,
    should_ingest_full_knowledge,
)


class BrandKnowledgeRequestDefaultTests(unittest.TestCase):
    def test_session_create_request_defaults_to_draft_only(self) -> None:
        request = BrandKnowledgeSessionCreateRequest(
            session_type="initial_generation",
            task_id="task-1",
        )

        self.assertEqual(request.publish_mode, "draft_only")

    def test_attachment_resolution_submit_request_defaults_to_draft_only(self) -> None:
        request = BrandAttachmentConflictResolutionSubmitRequest(
            session_id="bks_123",
            round_no=1,
        )

        self.assertEqual(request.publish_mode, "draft_only")

    def test_publish_mode_helper_defaults_and_maps_session_kind(self) -> None:
        self.assertEqual(normalize_publish_mode(None), "draft_only")
        self.assertEqual(normalize_publish_mode(None, default="full_ingest"), "full_ingest")
        self.assertTrue(is_draft_only_publish_mode(" draft_only "))
        self.assertFalse(should_ingest_full_knowledge("draft_only"))
        self.assertTrue(should_ingest_full_knowledge("full_ingest"))
        self.assertEqual(
            attachment_conflict_session_kind_for_publish_mode("draft_only"),
            "attachment_conflict:draft_only",
        )
        self.assertEqual(
            attachment_conflict_session_kind_for_publish_mode("full_ingest"),
            "attachment_conflict",
        )
        self.assertTrue(is_attachment_conflict_session_kind("attachment_conflict:draft_only"))
        self.assertEqual(
            publish_mode_from_attachment_conflict_session_kind("attachment_conflict:draft_only"),
            "draft_only",
        )
        self.assertEqual(
            publish_mode_from_attachment_conflict_session_kind("attachment_conflict"),
            "full_ingest",
        )

    def test_publish_mode_helper_rejects_unknown_mode(self) -> None:
        with self.assertRaisesRegex(ValueError, "不支持的知识库发布模式"):
            normalize_publish_mode("preview_only")
