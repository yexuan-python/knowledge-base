from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4


logger = logging.getLogger(__name__)


class AttachmentDraftPreviewParseMixin:
    async def preview_parse(
        self,
        *,
        brand_name: str,
        brand_code: str | None,
        attachments: list[dict[str, str]],
    ) -> dict[str, Any]:
        self.cleanup_expired_drafts()
        started_at = perf_counter()
        normalized_brand_name = (brand_name or "").strip()
        if not normalized_brand_name:
            raise ValueError("brand_name 不能为空")
        if not attachments:
            raise ValueError("attachments 不能为空")

        draft_id = f"bad_{uuid4().hex}"
        draft_dir = self._draft_dir(draft_id)
        download_dir = self._download_dir(draft_id)
        download_dir.mkdir(parents=True, exist_ok=True)

        draft_attachment_entries: list[dict[str, Any]] = []
        parse_tasks: list[asyncio.Task[dict[str, Any]]] = []
        semaphore = asyncio.Semaphore(self._preview_parse_max_concurrency(len(attachments)))

        try:
            logger.info(
                "Attachment preview parse started brand_name=%s draft_id=%s attachment_count=%s max_concurrency=%s",
                normalized_brand_name,
                draft_id,
                len(attachments),
                self._preview_parse_max_concurrency(len(attachments)),
            )
            for index, attachment in enumerate(attachments, start=1):
                name = (attachment.get("name") or "").strip()
                url = (attachment.get("url") or "").strip()
                if not name or not url:
                    continue

                destination = download_dir / f"{index:03d}-{Path(name).name}"
                draft_entry = {
                    "name": name,
                    "url": url,
                }
                draft_attachment_entries.append(draft_entry)
                parse_tasks.append(
                    asyncio.create_task(
                        self._parse_attachment(
                            brand_name=normalized_brand_name,
                            name=name,
                            url=url,
                            destination=destination,
                            semaphore=semaphore,
                        )
                    )
                )

            logger.info(
                "Attachment preview parse tasks scheduled brand_name=%s draft_id=%s valid_attachment_count=%s",
                normalized_brand_name,
                draft_id,
                len(parse_tasks),
            )
            parse_started_at = perf_counter()
            parsed_items = await asyncio.gather(*parse_tasks) if parse_tasks else []
            parse_elapsed = perf_counter() - parse_started_at
            success_count = sum(
                1 for item in parsed_items if isinstance(item, dict) and item.get("status") == "success"
            )
            failed_count = sum(
                1 for item in parsed_items if isinstance(item, dict) and item.get("status") == "failed"
            )
            logger.info(
                "Attachment preview parse stage completed brand_name=%s draft_id=%s "
                "success_count=%s failed_count=%s parse_stage_elapsed=%.2fs",
                normalized_brand_name,
                draft_id,
                success_count,
                failed_count,
                parse_elapsed,
            )
            if parsed_items and success_count == 0 and failed_count == len(parsed_items):
                logger.warning(
                    "Attachment preview parse finished with all attachments failed brand_name=%s draft_id=%s failed_count=%s",
                    normalized_brand_name,
                    draft_id,
                    failed_count,
                )
            combine_started_at = perf_counter()
            combined_markdown_text = self._build_combined_markdown(
                brand_name=normalized_brand_name,
                parsed_items=parsed_items,
            )
            combine_elapsed = perf_counter() - combine_started_at
            logger.info(
                "Attachment preview markdown combined brand_name=%s draft_id=%s "
                "markdown_chars=%s combine_elapsed=%.2fs",
                normalized_brand_name,
                draft_id,
                len(combined_markdown_text or ""),
                combine_elapsed,
            )
            for draft_entry, parsed_item in zip(draft_attachment_entries, parsed_items, strict=False):
                if not isinstance(parsed_item, dict):
                    continue
                draft_entry.update(
                    {
                        "status": str(parsed_item.get("status") or "").strip(),
                        "source_type": parsed_item.get("source_type"),
                        "parser_backend": parsed_item.get("parser_backend"),
                        "parsed_text": parsed_item.get("parsed_text"),
                        "markdown_text": parsed_item.get("markdown_text"),
                        "error_message": parsed_item.get("error_message"),
                    }
                )

            snapshot_started_at = perf_counter()
            normalized_brand_code = self._normalize_optional_str(brand_code)
            current_snapshot, current_revision, brand = self._try_build_current_snapshot(
                brand_code=normalized_brand_code,
                brand_name=normalized_brand_name,
            )
            resolved_brand_code = (
                self._normalize_optional_str((brand or {}).get("brand_code")) or normalized_brand_code
            )
            resolved_brand_id = (brand or {}).get("id") if isinstance(brand, dict) else None
            existing_attachment_products = (
                self._load_attachment_products(brand_id=int(resolved_brand_id))
                if resolved_brand_id is not None
                else []
            )
            snapshot_elapsed = perf_counter() - snapshot_started_at
            logger.info(
                "Attachment preview current snapshot loaded brand_name=%s draft_id=%s "
                "brand_id=%s existing_attachment_products=%s snapshot_elapsed=%.2fs",
                normalized_brand_name,
                draft_id,
                (brand or {}).get("id") if isinstance(brand, dict) else None,
                len(existing_attachment_products),
                snapshot_elapsed,
            )
            structured_snapshot, extraction_markdown_text = self._extract_structured_candidate_from_parsed_items(
                parsed_items=parsed_items,
                brand_name=normalized_brand_name,
                brand_code=resolved_brand_code,
            )
            logger.info(
                "Attachment preview spreadsheet enhancement completed brand_name=%s draft_id=%s "
                "structured_fields=%s residual_markdown_chars=%s",
                normalized_brand_name,
                draft_id,
                ",".join(sorted(structured_snapshot.keys()))
                if isinstance(structured_snapshot, dict)
                else type(structured_snapshot).__name__,
                len(extraction_markdown_text or ""),
            )
            extract_elapsed = 0.0
            if extraction_markdown_text:
                extract_started_at = perf_counter()
                logger.info(
                    "Attachment preview extraction started brand_name=%s draft_id=%s markdown_chars=%s",
                    normalized_brand_name,
                    draft_id,
                    len(extraction_markdown_text or ""),
                )
                from knowledge_base.brand_knowledge.application import attachment_flow as attachment_flow_module

                extracted = await attachment_flow_module.extract_brand_knowledge_from_markdown(
                    extraction_markdown_text,
                    brand_name=normalized_brand_name,
                    source_name=f"{normalized_brand_name}-attachment-preview.md",
                    settings=self._deps.settings,
                )
                extract_elapsed = perf_counter() - extract_started_at
                logger.info(
                    "Attachment preview extraction completed brand_name=%s draft_id=%s "
                    "extract_elapsed=%.2fs extracted_sections=%s",
                    normalized_brand_name,
                    draft_id,
                    extract_elapsed,
                    ",".join(sorted(extracted.keys())) if isinstance(extracted, dict) else type(extracted).__name__,
                )
                candidate_snapshot = self._build_update_payload_from_extracted(
                    extracted=extracted,
                    brand_name=normalized_brand_name,
                    brand_code=resolved_brand_code,
                    draft_attachments=draft_attachment_entries,
                    current_snapshot=current_snapshot,
                )
            else:
                candidate_snapshot = {}
            if self._has_meaningful_payload(structured_snapshot):
                candidate_snapshot = self._merge_snapshot(
                    current_snapshot=candidate_snapshot,
                    candidate_snapshot={
                        **structured_snapshot,
                        "attachments": [],
                    },
                )
            candidate_snapshot = self._refine_preview_candidate_snapshot(candidate_snapshot)

            manifest_started_at = perf_counter()
            manifest = {
                "draft_id": draft_id,
                "brand_name": normalized_brand_name,
                "brand_code": resolved_brand_code,
                "draft_status": "pending_review",
                "attachments": draft_attachment_entries,
                "combined_markdown_text": combined_markdown_text,
                "current_snapshot": current_snapshot,
                "candidate_snapshot": candidate_snapshot,
                "knowledge_revision": current_revision,
            }
            self._persist_draft_manifest(draft_id=draft_id, manifest=manifest)
            manifest_elapsed = perf_counter() - manifest_started_at
            logger.info(
                "Attachment preview draft manifest saved brand_name=%s draft_id=%s "
                "attachments=%s manifest_elapsed=%.2fs",
                normalized_brand_name,
                draft_id,
                len(draft_attachment_entries),
                manifest_elapsed,
            )

            response_started_at = perf_counter()
            new_attachment_products = self._build_new_attachment_products(
                current_snapshot=current_snapshot,
                candidate_snapshot=candidate_snapshot,
                existing_attachment_products=existing_attachment_products,
            )
            external_snapshot_source = self._keep_upstream_products_in_products(
                candidate_snapshot=candidate_snapshot,
                current_snapshot=current_snapshot,
            )
            external_candidate_snapshot = self._build_external_candidate_snapshot(external_snapshot_source)
            external_candidate_snapshot = self._append_new_attachment_products_to_other_info(
                candidate_snapshot=external_candidate_snapshot,
                new_attachment_products=new_attachment_products,
            )
            response = {
                "draft_id": draft_id,
                "brand_name": normalized_brand_name,
                "candidate_snapshot": external_candidate_snapshot,
                "field_labels": self._build_preview_field_labels(external_candidate_snapshot),
                "knowledge_revision": current_revision,
            }
            response_elapsed = perf_counter() - response_started_at
            logger.info(
                "Attachment preview parse completed brand_name=%s draft_id=%s attachment_count=%s "
                "success_count=%s failed_count=%s markdown_chars=%s parse_elapsed=%.2fs "
                "combine_elapsed=%.2fs snapshot_elapsed=%.2fs extract_elapsed=%.2fs "
                "manifest_elapsed=%.2fs response_elapsed=%.2fs total_elapsed=%.2fs",
                normalized_brand_name,
                draft_id,
                len(draft_attachment_entries),
                sum(1 for item in parsed_items if isinstance(item, dict) and item.get("status") == "success"),
                sum(1 for item in parsed_items if isinstance(item, dict) and item.get("status") == "failed"),
                len(combined_markdown_text or ""),
                parse_elapsed,
                combine_elapsed,
                snapshot_elapsed,
                extract_elapsed,
                manifest_elapsed,
                response_elapsed,
                perf_counter() - started_at,
            )
            return response
        except ValueError:
            shutil.rmtree(draft_dir, ignore_errors=True)
            raise
        except Exception:
            logger.exception(
                "Attachment preview parse crashed brand_name=%s attachment_count=%s total_elapsed=%.2fs",
                normalized_brand_name,
                len(attachments),
                perf_counter() - started_at,
            )
            shutil.rmtree(draft_dir, ignore_errors=True)
            raise
