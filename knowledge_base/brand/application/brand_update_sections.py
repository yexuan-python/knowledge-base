from __future__ import annotations

from typing import Any

from knowledge_base.brand.competitor_schema import normalize_competitors_for_storage


class BrandKnowledgeUpdateSectionsMixin:
    @classmethod
    def _competitors_content_for_revision_compare(cls, value: Any) -> list[dict[str, Any]]:
        comparable: list[dict[str, Any]] = []
        for item in normalize_competitors_for_storage(value):
            comparable.append(
                {
                    key: item_value
                    for key, item_value in item.items()
                    if key != "aliases"
                }
            )
        return comparable

    def _knowledge_payloads_for_update(
        self,
        *,
        normalized_company_profile: Any,
        request: Any,
        other_info_content: Any,
    ) -> tuple[tuple[str, Any], ...]:
        return (
            ("company_profile", normalized_company_profile),
            ("management_team", request.management_team),
            ("competitors", request.competitors),
            ("authority_honors", request.authority_honors),
            ("customers_cases", request.customers_cases),
            ("official_media_matrix", request.official_media_matrix),
            ("official_malls", request.official_malls),
            ("other_info", other_info_content),
        )

    def _apply_structured_knowledge_updates(
        self,
        *,
        request: Any,
        resolved_brand_id: int,
        knowledge_map: dict[str, Any],
        normalized_company_profile: Any,
        other_info_content: Any,
        updated_sections: list[str],
        deleted_sections: list[str],
        structured_update_entries: list[dict[str, Any]],
        structured_change_details: list[dict[str, Any]],
    ) -> bool:
        revision_should_bump = False
        explicit_empty_updatable_types = {
            "company_profile",
            "management_team",
            "competitors",
            "authority_honors",
            "customers_cases",
            "official_media_matrix",
            "official_malls",
            "other_info",
        }
        for knowledge_type, content in self._knowledge_payloads_for_update(
            normalized_company_profile=normalized_company_profile,
            request=request,
            other_info_content=other_info_content,
        ):
            existing_section_content = knowledge_map.get(knowledge_type)
            should_apply, resolved_content, has_change, has_deletion = self._resolve_section_update_action(
                request=request,
                knowledge_type=knowledge_type,
                content=content,
                existing_content=existing_section_content,
                clearable_types=explicit_empty_updatable_types,
            )
            if not should_apply:
                continue
            if knowledge_type == "competitors":
                resolved_content = normalize_competitors_for_storage(resolved_content)
                existing_for_revision = self._competitors_content_for_revision_compare(existing_section_content)
                next_for_revision = self._competitors_content_for_revision_compare(resolved_content)
                has_change = self._has_material_change(existing_for_revision, next_for_revision)
                has_deletion = (
                    self._has_meaningful_payload(existing_for_revision)
                    and self._has_removal_delta(existing_for_revision, next_for_revision)
                )
            if has_change:
                revision_should_bump = True
                self._append_structured_change_detail(
                    structured_change_details,
                    section=knowledge_type,
                    title=knowledge_type,
                    action="delete" if has_deletion else "update",
                    before=existing_section_content,
                    after=resolved_content,
                )
                structured_update_entries.append(
                    {
                        "section": knowledge_type,
                        "title": knowledge_type,
                        "action": "delete" if has_deletion else "update",
                        "content": resolved_content,
                    }
                )
            if self._has_meaningful_payload(resolved_content):
                self._deps.brand_knowledge.upsert_brand_knowledge_json(
                    brand_id=resolved_brand_id,
                    knowledge_type=knowledge_type,
                    content_json=resolved_content,
                    source_task_id=None,
                )
            else:
                self._deps.brand_knowledge.delete_brand_knowledge_type(
                    brand_id=resolved_brand_id,
                    knowledge_type=knowledge_type,
                )
            if has_change:
                updated_sections.append(knowledge_type)
            if has_deletion and knowledge_type not in deleted_sections:
                deleted_sections.append(knowledge_type)
        return revision_should_bump

    def _apply_attachment_products_update(
        self,
        *,
        resolved_brand_id: int,
        existing_attachment_products: list[dict[str, Any]],
        attachment_products_override_provided: bool,
        attachment_products_content: list[dict[str, Any]],
        updated_sections: list[str],
        deleted_sections: list[str],
        structured_update_entries: list[dict[str, Any]],
        structured_change_details: list[dict[str, Any]],
    ) -> bool:
        if not attachment_products_override_provided:
            return False

        attachment_products_has_change = self._has_material_change(
            existing_attachment_products,
            attachment_products_content,
        )
        if attachment_products_has_change:
            self._append_structured_change_detail(
                structured_change_details,
                section=self.ATTACHMENT_PRODUCTS_KNOWLEDGE_TYPE,
                title=self.ATTACHMENT_PRODUCTS_KNOWLEDGE_TYPE,
                action="delete" if not self._has_meaningful_payload(attachment_products_content) else "update",
                before=existing_attachment_products,
                after=attachment_products_content,
            )
            structured_update_entries.append(
                {
                    "section": self.ATTACHMENT_PRODUCTS_KNOWLEDGE_TYPE,
                    "title": self.ATTACHMENT_PRODUCTS_KNOWLEDGE_TYPE,
                    "action": "update",
                    "content": attachment_products_content,
                }
            )
        if self._has_meaningful_payload(attachment_products_content):
            self._deps.brand_knowledge.upsert_brand_knowledge_json(
                brand_id=resolved_brand_id,
                knowledge_type=self.ATTACHMENT_PRODUCTS_KNOWLEDGE_TYPE,
                content_json=attachment_products_content,
                source_task_id=None,
            )
        else:
            self._deps.brand_knowledge.delete_brand_knowledge_type(
                brand_id=resolved_brand_id,
                knowledge_type=self.ATTACHMENT_PRODUCTS_KNOWLEDGE_TYPE,
            )
        if attachment_products_has_change and self.ATTACHMENT_PRODUCTS_KNOWLEDGE_TYPE not in updated_sections:
            updated_sections.append(self.ATTACHMENT_PRODUCTS_KNOWLEDGE_TYPE)
        if (
            not self._has_meaningful_payload(attachment_products_content)
            and self.ATTACHMENT_PRODUCTS_KNOWLEDGE_TYPE not in deleted_sections
        ):
            deleted_sections.append(self.ATTACHMENT_PRODUCTS_KNOWLEDGE_TYPE)
        return attachment_products_has_change

    def _apply_sensitive_topics_update(
        self,
        *,
        request: Any,
        sensitive_topics_was_provided: bool,
        knowledge_map: dict[str, Any],
        resolved_brand_id: int,
        updated_sections: list[str],
        structured_update_entries: list[dict[str, Any]],
        structured_change_details: list[dict[str, Any]],
    ) -> bool:
        normalized_sensitive_topics = self._serialize_sensitive_topics_payload(request.sensitive_topics)
        if not sensitive_topics_was_provided and not self._has_sensitive_topics_content(normalized_sensitive_topics):
            return False

        sensitive_topics_has_change = self._has_positive_change(
            knowledge_map.get("sensitive_topics"),
            normalized_sensitive_topics,
        )
        if sensitive_topics_has_change:
            self._append_structured_change_detail(
                structured_change_details,
                section="sensitive_topics",
                title="敏感话题",
                action="update",
                before=knowledge_map.get("sensitive_topics"),
                after=normalized_sensitive_topics,
            )
            structured_update_entries.append(
                {
                    "section": "sensitive_topics",
                    "title": "敏感话题",
                    "action": "update",
                    "content": normalized_sensitive_topics,
                }
            )
        self._deps.brand_knowledge.upsert_brand_knowledge_json(
            brand_id=resolved_brand_id,
            knowledge_type="sensitive_topics",
            content_json=normalized_sensitive_topics,
            source_task_id=None,
        )
        if sensitive_topics_has_change:
            updated_sections.append("sensitive_topics")
        return sensitive_topics_has_change

    def _apply_attachments_update(
        self,
        *,
        resolved_brand_id: int,
        existing_attachments: Any,
        next_attachments: Any,
        updated_sections: list[str],
        structured_update_entries: list[dict[str, Any]],
        structured_change_details: list[dict[str, Any]],
    ) -> bool:
        normalized_attachments = self._normalize_attachment_entries(next_attachments)
        attachments_has_change = self._attachments_have_positive_change(existing_attachments, next_attachments)
        if attachments_has_change:
            self._append_structured_change_detail(
                structured_change_details,
                section="attachments",
                title="附件资料",
                action="update",
                before=existing_attachments,
                after=normalized_attachments,
            )
            structured_update_entries.append(
                {
                    "section": "attachments",
                    "title": "附件资料",
                    "action": "update",
                    "content": normalized_attachments,
                }
            )
        self._deps.brand_knowledge.upsert_brand_knowledge_json(
            brand_id=resolved_brand_id,
            knowledge_type="attachments",
            content_json=normalized_attachments,
            source_task_id=None,
        )
        if attachments_has_change:
            updated_sections.append("attachments")
        return attachments_has_change
