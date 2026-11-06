from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Coroutine

from fastapi import UploadFile

from knowledge_base.brand.application.facts_only_upload import (
    BrandFactsOnlyUploadDependencies,
    BrandFactsOnlyUploadService,
)
from knowledge_base.brand.schemas import (
    BrandDeleteRequest,
    BrandRenameRequest,
    BrandUploadRequest,
    KnowledgeUpdateRequest,
)
from knowledge_base.brand_knowledge.application.attachment_delete import (
    AttachmentDeleteDependencies,
    AttachmentDeleteWorkflow,
)
from knowledge_base.brand_knowledge.application.status_queries import (
    BrandKnowledgeStatusQueryDependencies,
    BrandKnowledgeStatusQueryService,
)
from knowledge_base.brand_knowledge.application.attachment_preview_entry import (
    AttachmentPreviewEntryDependencies,
    AttachmentPreviewEntryService,
)
from knowledge_base.brand_knowledge.schemas import AttachmentConfirmSaveRequest, AttachmentReviewChangesRequest
from knowledge_base.composition import KnowledgeBaseInfrastructure, build_applications
from knowledge_base.document.domain import IngestedDocument
from knowledge_base.document.schemas import ImageSearchRequest, SearchRequest
from knowledge_base.infrastructure import Settings, TianyanchaClient
from knowledge_base.search.facade import KnowledgeSearchFacade, KnowledgeSearchFacadeDependencies
from knowledge_base.shared.image_preparation import (
    prepare_docmind_image_parsing_path,
    prepare_image_processing_path,
    prepare_image_tagging_path,
    should_route_image_to_document_pipeline,
)
from knowledge_base.upload_task.schemas import UploadTaskCreateResponse


logger = logging.getLogger(__name__)


class _UnavailableDependency:
    def __init__(self, name: str) -> None:
        self._name = name

    def __getattr__(self, attr_name: str) -> Any:
        raise RuntimeError(f"KnowledgeBaseService dependency '{self._name}' is not initialized")

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(f"KnowledgeBaseService dependency '{self._name}' is not initialized")


@dataclass(frozen=True)
class _SearchFallbackSettings:
    milvus_filter_batch_size: int = 200


class KnowledgeBaseService:
    def __init__(self, settings: Settings, infrastructure: KnowledgeBaseInfrastructure) -> None:
        self._settings = settings
        self._parser = infrastructure.parser
        self._embeddings = infrastructure.embeddings
        self._store = infrastructure.vector_store
        self._background_jobs = getattr(infrastructure.mysql_stores, "background_jobs", None)
        self._brand_attachment_assets = getattr(infrastructure.mysql_stores, "brand_attachment_assets", None)
        self._brands = infrastructure.mysql_stores.brands
        self._brand_full_knowledge = infrastructure.mysql_stores.brand_full_knowledge
        self._brand_knowledge_facts = getattr(infrastructure.mysql_stores, "brand_knowledge_facts", None)
        self._brand_knowledge_ingestion_jobs = getattr(infrastructure.mysql_stores, "brand_knowledge_ingestion_jobs", None)
        self._brand_knowledge_update_audits = getattr(infrastructure.mysql_stores, "brand_knowledge_update_audits", None)
        self._brand_products = infrastructure.mysql_stores.brand_products
        self._brand_knowledge = infrastructure.mysql_stores.brand_knowledge
        self._brand_knowledge_sessions = infrastructure.mysql_stores.brand_knowledge_sessions
        self._document_alerts = infrastructure.mysql_stores.document_alerts
        self._document_categories = infrastructure.mysql_stores.document_categories
        self._document_registry = infrastructure.mysql_stores.document_registry
        self._fact_relations = infrastructure.mysql_stores.fact_relations
        self._industries = infrastructure.mysql_stores.industries
        self._upload_tasks = infrastructure.mysql_stores.upload_tasks
        self._runtime = infrastructure.runtime
        self.oss_client = infrastructure.oss_client
        self._tianyancha_client = TianyanchaClient(settings)
        applications = build_applications(self)
        self._brand_callbacks = applications.brand_callbacks
        self._background_jobs_app = applications.background_jobs
        self._brand_app = applications.brand_app
        self._brand_knowledge_attachment_draft_app = applications.brand_knowledge_attachment_draft_app
        self._brand_knowledge_app = applications.brand_knowledge_app
        self._document_app = applications.document_app
        self._ingest_app = applications.ingest_app
        self._search_app = applications.search_app
        self._upload_task_app = applications.upload_task_app
        self._alert_app = applications.alert_app

    def _get_required_component(self, attr_name: str, component_name: str) -> Any:
        component = getattr(self, attr_name, None)
        if component is None:
            raise RuntimeError(f"KnowledgeBaseService {component_name} is not initialized")
        return component

    def _brand_application(self) -> Any:
        app = getattr(self, "_brand_app", None)
        if app is not None:
            return app

        from knowledge_base.brand.application import BrandApplicationDependencies, BrandApplicationService
        from knowledge_base.composition import _build_full_knowledge_from_update_for_service

        missing = _UnavailableDependency("brand_application_support")
        background_jobs_app = getattr(self, "_background_jobs_app", None)
        app = BrandApplicationService(
            BrandApplicationDependencies(
                settings=getattr(self, "_settings", missing),
                brands=self._brands,
                brand_products=self._brand_products,
                brand_knowledge=self._brand_knowledge,
                brand_full_knowledge=getattr(self, "_brand_full_knowledge", missing),
                industries=self._industries,
                brand_knowledge_sessions=self._brand_knowledge_sessions,
                document_registry=self._document_registry,
                document_categories=self._document_categories,
                fact_relations=getattr(self, "_fact_relations", missing),
                store=getattr(self, "_store", missing),
                document_app=getattr(self, "_document_app", missing),
                upload_tasks=getattr(self, "_upload_tasks", None),
                brand_attachment_assets=getattr(self, "_brand_attachment_assets", None),
                brand_knowledge_facts=getattr(self, "_brand_knowledge_facts", None),
                delete_document=self.delete_document,
                get_full_text=self.get_full_text,
                ingest_staged_file=self._ingest_staged_file,
                ingest_from_url=self.ingest_from_url,
                delete_document_by_attachment_name=self.delete_document_by_attachment_name,
                oss_client=getattr(self, "oss_client", missing),
                parser=getattr(self, "_parser", None),
                brand_knowledge_ingestion_jobs=getattr(self, "_brand_knowledge_ingestion_jobs", None),
                brand_knowledge_update_audits=getattr(self, "_brand_knowledge_update_audits", None),
                background_jobs=getattr(self, "_background_jobs", None),
                enqueue_brand_knowledge_update_job=(
                    background_jobs_app.enqueue_brand_knowledge_update
                    if background_jobs_app is not None
                    else None
                ),
                build_next_brand_full_knowledge=lambda **kwargs: _build_full_knowledge_from_update_for_service(
                    self,
                    **kwargs,
                ),
            )
        )
        self._brand_app = app
        return app

    def _document_application(self) -> Any:
        return self._get_required_component("_document_app", "document application")

    def _brand_knowledge_application(self) -> Any:
        return self._get_required_component("_brand_knowledge_app", "brand knowledge application")

    def _brand_knowledge_attachment_draft_application(self) -> Any:
        return self._get_required_component(
            "_brand_knowledge_attachment_draft_app",
            "brand knowledge attachment draft application",
        )

    def _upload_task_application(self) -> Any:
        return self._get_required_component("_upload_task_app", "upload task application")

    def _brand_callback_coordinator(self) -> Any:
        return self._get_required_component("_brand_callbacks", "brand callback coordinator")

    def _search_application(self) -> Any:
        app = getattr(self, "_search_app", None)
        if app is not None:
            return app

        from knowledge_base.search.application import SearchApplicationDependencies, SearchApplicationService

        missing = _UnavailableDependency("search_application_support")
        app = SearchApplicationService(
            SearchApplicationDependencies(
                settings=getattr(self, "_settings", _SearchFallbackSettings()),
                store=getattr(self, "_store", missing),
                embeddings=getattr(self, "_embeddings", missing),
                brands=getattr(self, "_brands", missing),
                brand_app=self._brand_application(),
                document_app=getattr(self, "_document_app", missing),
                document_categories=self._document_categories,
                brand_products=getattr(self, "_brand_products", None),
                brand_full_knowledge=getattr(self, "_brand_full_knowledge", None),
                attachment_assets=getattr(self, "_brand_attachment_assets", None),
            )
        )
        self._search_app = app
        return app

    def _search_facade(self) -> KnowledgeSearchFacade:
        facade = getattr(self, "_knowledge_search_facade", None)
        if facade is not None:
            return facade

        facade = KnowledgeSearchFacade(
            KnowledgeSearchFacadeDependencies(
                search_application=self._search_application,
                document_application=self._document_application,
            )
        )
        self._knowledge_search_facade = facade
        return facade

    def _ingest_application(self) -> Any:
        return self._get_required_component("_ingest_app", "ingest application")

    def _get_document_info(self, document_id: str) -> dict[str, Any] | None:
        docs_info = self._store.get_documents_info_by_ids([document_id])
        if not docs_info:
            return None
        return docs_info[0]

    def _should_route_image_to_document_pipeline(self, suffix: str) -> bool:
        return should_route_image_to_document_pipeline(self._parser, suffix)

    def _prepare_image_processing_path(
        self,
        original_path: Path,
        *,
        max_bytes: int,
        target_bytes: int,
        purpose: str,
    ) -> tuple[Path, bool]:
        return prepare_image_processing_path(
            original_path,
            max_bytes=max_bytes,
            target_bytes=target_bytes,
            purpose=purpose,
        )

    def _prepare_docmind_image_parsing_path(self, original_path: Path, suffix: str) -> tuple[Path, bool]:
        return prepare_docmind_image_parsing_path(self._parser, original_path, suffix)

    def _prepare_image_tagging_path(self, original_path: Path) -> tuple[Path, bool]:
        return prepare_image_tagging_path(original_path)

    @staticmethod
    def _log_background_task_result(task: asyncio.Task[Any]) -> None:
        with suppress(asyncio.CancelledError):
            exc = task.exception()
            if exc is not None:
                logger.error("Background task failed: %s", exc, exc_info=exc)

    def _spawn_background_task(self, coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
        task = asyncio.create_task(coro)
        task.add_done_callback(self._log_background_task_result)
        return task

    @property
    def collection_name(self) -> str:
        return self._store.collection_name

    async def start(self) -> None:
        pending_task_ids = self._upload_tasks.reset_incomplete_upload_tasks()
        if self._background_jobs_app is None and (
            self._runtime.worker_task is None or self._runtime.worker_task.done()
        ):
            self._runtime.worker_task = asyncio.create_task(
                self._upload_task_application().upload_worker(),
                name="upload-task-worker",
            )
        if (
            self._background_jobs is not None
            and self._background_jobs_app is not None
            and (
                getattr(self._runtime, "background_job_worker_task", None) is None
                or self._runtime.background_job_worker_task.done()
            )
        ):
            self._background_jobs_app.reset_processing_jobs()
            self._runtime.background_job_worker_task = asyncio.create_task(
                self._background_jobs_app.worker(),
                name="background-job-worker",
            )
        for task_id in pending_task_ids:
            await self._upload_task_application().schedule_upload_task(task_id)
        if self._background_jobs_app is not None:
            await self._background_jobs_app.schedule_due_jobs()
        self._brand_callback_coordinator().schedule_due_callback_retries()
        self._brand_knowledge_application().schedule_due_attachment_conflict_callback_retries()
        self._brand_knowledge_attachment_draft_application().cleanup_expired_drafts()
        self._brand_knowledge_attachment_draft_application().schedule_due_confirm_callback_retries()
        self.schedule_due_attachment_delete_callback_retries()

    async def stop(self) -> None:
        if self._runtime.worker_task is None:
            upload_worker_task = None
        else:
            upload_worker_task = self._runtime.worker_task
            upload_worker_task.cancel()
        background_job_worker_task = getattr(self._runtime, "background_job_worker_task", None)
        if background_job_worker_task is not None:
            background_job_worker_task.cancel()
        if upload_worker_task is not None:
            with suppress(asyncio.CancelledError):
                await upload_worker_task
            self._runtime.worker_task = None
        if background_job_worker_task is not None:
            with suppress(asyncio.CancelledError):
                await background_job_worker_task
            self._runtime.background_job_worker_task = None

    async def enqueue_upload_task(
        self,
        *,
        files: list[UploadFile],
        metadata: dict[str, Any],
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
    ) -> UploadTaskCreateResponse:
        return await self._upload_task_application().enqueue_upload_task(
            files=files,
            metadata=metadata,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    async def ingest_brand_facts_only(
        self,
        *,
        files: list[UploadFile],
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        return await self._brand_facts_only_upload_service().ingest_brand_facts_only(
            files=files,
            metadata=metadata,
        )

    def _brand_facts_only_upload_service(self) -> BrandFactsOnlyUploadService:
        return BrandFactsOnlyUploadService(
            BrandFactsOnlyUploadDependencies(
                upload_task_application=self._upload_task_application(),
                brand_ai_knowledge_ingestion=self._brand_ai_knowledge_ingestion,
            )
        )

    async def enqueue_brand_upload_task(self, request: BrandUploadRequest) -> UploadTaskCreateResponse:
        return await self._upload_task_application().enqueue_brand_upload_task(request)

    async def list_brands(self, *, keyword: str | None = None) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self._brand_application().list_brands,
            keyword=keyword,
        )

    async def get_brand_meta(
        self,
        *,
        brand_code: str,
        include_path_index: bool = True,
    ) -> dict[str, Any] | None:
        return await self._brand_application().get_brand_meta(
            brand_code=brand_code,
            include_path_index=include_path_index,
        )

    async def get_brand_official_malls(self, *, brand_code: str) -> dict[str, Any] | None:
        return await self._brand_application().get_brand_official_malls(
            brand_code=brand_code,
        )

    def load_brand_paths(
        self,
        *,
        brand_code: str,
        paths: list[str],
        knowledge_revision: str | None = None,
    ) -> dict[str, Any] | None:
        return self._brand_application().load_brand_paths(
            brand_code=brand_code,
            paths=paths,
            knowledge_revision=knowledge_revision,
        )

    async def get_latest_ai_knowledge(self, *, brand_code: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(
            self._brand_application().get_latest_ai_knowledge,
            brand_code=brand_code,
        )

    async def update_knowledge(self, request: KnowledgeUpdateRequest) -> dict[str, Any]:
        return await self._brand_application().update_knowledge(request)

    async def rename_brand(self, request: BrandRenameRequest) -> dict[str, Any] | None:
        return await asyncio.to_thread(
            self._brand_application().rename_brand,
            brand_code=request.brand_code,
            new_brand_name=request.new_brand_name,
        )

    async def generate_and_save_facts(
        self,
        *,
        document_id: str,
        category: str,
        file_hash: str | None,
        text: str,
        subcategory: str | None = None,
        product_code: str | None = None,
        product_name: str | None = None,
    ) -> None:
        await self._document_application().generate_and_save_facts(
            document_id=document_id,
            category=category,
            file_hash=file_hash,
            text=text,
            subcategory=subcategory,
            product_code=product_code,
            product_name=product_name,
        )

    def get_upload_task_status(self, task_id: str) -> dict[str, Any] | None:
        return self._upload_task_application().get_upload_task_status(task_id)

    def _brand_knowledge_status_queries(self) -> BrandKnowledgeStatusQueryService:
        return BrandKnowledgeStatusQueryService(
            BrandKnowledgeStatusQueryDependencies(
                background_jobs=getattr(self, "_background_jobs", None),
                brand_knowledge_update_audits=getattr(self, "_brand_knowledge_update_audits", None),
                get_latest_attachment_conflict_session=(
                    lambda *, brand_code, brand_name=None: self._brand_knowledge_application().get_latest_attachment_conflict_session(
                        brand_code=brand_code,
                        brand_name=brand_name,
                    )
                ),
                upload_tasks=getattr(self, "_upload_tasks", None),
            )
        )

    @staticmethod
    def _format_background_job_datetime(value: Any) -> str | None:
        return BrandKnowledgeStatusQueryService.format_background_job_datetime(value)

    def get_background_job(self, job_id: str) -> dict[str, Any] | None:
        return self._brand_knowledge_status_queries().get_background_job(job_id)

    def list_background_jobs(self, *, limit: int = 20) -> list[dict[str, Any]]:
        return self._brand_knowledge_status_queries().list_background_jobs(limit=limit)

    def query_background_jobs(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        statuses: list[str] | None = None,
        excluded_statuses: list[str] | None = None,
        keyword: str | None = None,
    ) -> dict[str, Any]:
        return self._brand_knowledge_status_queries().query_background_jobs(
            limit=limit,
            offset=offset,
            statuses=statuses,
            excluded_statuses=excluded_statuses,
            keyword=keyword,
        )

    def get_attachment_confirm_result(self, job_id: str) -> dict[str, Any] | None:
        return self._brand_knowledge_status_queries().get_attachment_confirm_result(job_id)

    async def ingest_text_document(
        self,
        *,
        text: str,
        title: str,
        metadata: dict[str, Any],
        chunk_size: int | None,
        chunk_overlap: int | None,
        document_id: str | None = None,
    ) -> IngestedDocument:
        return await self._ingest_application().ingest_text_document(
            text=text,
            title=title,
            metadata=metadata,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            document_id=document_id,
        )

    async def search(self, request: SearchRequest) -> list[dict[str, Any]]:
        return await self._search_facade().search(request)

    async def _search_semantic(self, request: SearchRequest) -> list[dict[str, Any]]:
        return await self._search_facade().search_semantic(request)

    async def search_images(self, request: ImageSearchRequest) -> list[dict[str, Any]]:
        return await self._search_facade().search_images(request)

    @staticmethod
    def _classify_search_query(query: str) -> str:
        return KnowledgeSearchFacade.classify_search_query(query)

    async def _supplement_structured_with_semantic(
        self,
        request: SearchRequest,
        structured_hits: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return await self._search_facade().supplement_structured_with_semantic(request, structured_hits)

    @staticmethod
    def _count_hit_chunks(hits: list[dict[str, Any]]) -> int:
        return KnowledgeSearchFacade.count_hit_chunks(hits)

    def _flatten_grouped_hits_to_results(
        self,
        grouped_hits: list[dict[str, Any]],
        *,
        top_k: int,
        request_category: str | None = None,
    ) -> list[dict[str, Any]]:
        return self._search_facade().flatten_grouped_hits_to_results(
            grouped_hits,
            top_k=top_k,
            request_category=request_category,
        )

    @staticmethod
    def _merge_search_hits(
        structured_hits: list[dict[str, Any]],
        semantic_hits: list[dict[str, Any]],
        *,
        top_k: int,
    ) -> list[dict[str, Any]]:
        return KnowledgeSearchFacade.merge_search_hits(
            structured_hits,
            semantic_hits,
            top_k=top_k,
        )

    async def _search_with_document_filter_batches(
        self,
        *,
        query_vector: list[float],
        top_k: int,
        document_ids: list[str] | None,
        source_types: list[str] | None,
    ) -> list[dict[str, Any]]:
        return await self._search_facade().search_with_document_filter_batches(
            query_vector=query_vector,
            top_k=top_k,
            document_ids=document_ids,
            source_types=source_types,
        )

    async def delete_document(
        self,
        document_id: str,
        *,
        oss_object_key_filter: Callable[[str], bool] | None = None,
    ) -> bool:
        return await self._document_application().delete_document(
            document_id,
            oss_object_key_filter=oss_object_key_filter,
        )

    async def delete_document_by_attachment_name(
        self,
        attachment_name: str,
        *,
        url: str | None = None,
        category: str | None = None,
    ) -> str | None:
        return await self._document_application().delete_document_by_attachment_name(
            attachment_name,
            url=url,
            category=category,
        )

    def _attachment_delete_workflow(self) -> AttachmentDeleteWorkflow:
        return AttachmentDeleteWorkflow(
            AttachmentDeleteDependencies(
                settings=getattr(self, "_settings", object()),
                brands=self._brands,
                brand_knowledge=getattr(self, "_brand_knowledge", None),
                brand_products=getattr(self, "_brand_products", None),
                brand_full_knowledge=getattr(self, "_brand_full_knowledge", None),
                upload_tasks=getattr(self, "_upload_tasks", None),
                runtime=getattr(self, "_runtime", None),
                spawn_background_task=getattr(self, "_spawn_background_task", lambda coro: asyncio.create_task(coro)),
                build_callback_payload=self._build_attachment_delete_callback_payload,
                post_callback=self._post_attachment_delete_callback,
            )
        )

    @staticmethod
    def _parse_json_value(raw: Any, default: Any) -> Any:
        return AttachmentDeleteWorkflow.parse_json_value(raw, default)

    @staticmethod
    def _normalize_attachment_entries(value: Any) -> list[dict[str, Any]]:
        return AttachmentDeleteWorkflow.normalize_attachment_entries(value)

    @staticmethod
    def _attachment_matches_deleted_entry(
        attachment: dict[str, Any],
        deleted_entry: dict[str, Any],
    ) -> bool:
        return AttachmentDeleteWorkflow.attachment_matches_deleted_entry(attachment, deleted_entry)

    def _get_attachment_delete_callback_store(self) -> Any | None:
        return self._attachment_delete_workflow().get_callback_store()

    def _load_brand_knowledge_snapshot(self, *, brand: dict[str, Any]) -> dict[str, Any]:
        return self._attachment_delete_workflow().load_brand_knowledge_snapshot(brand=brand)

    def _sync_remaining_attachments_after_delete(
        self,
        *,
        brand: dict[str, Any],
        deleted_entries: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return self._attachment_delete_workflow().sync_remaining_attachments_after_delete(
            brand=brand,
            deleted_entries=deleted_entries,
        )

    def _current_brand_knowledge_mete(self, *, brand: dict[str, Any]) -> tuple[str, dict[str, str]]:
        return self._attachment_delete_workflow().current_brand_knowledge_mete(brand=brand)

    def _build_attachment_delete_callback_payload(self, *, brand: dict[str, Any]) -> dict[str, Any]:
        coordinator = self._brand_callback_coordinator()
        payload = coordinator.build_attachment_delete_callback_payload(brand=brand)
        if not isinstance(payload, dict):
            raise RuntimeError("brand callback payload builder is not initialized")
        return payload

    @staticmethod
    def _post_attachment_delete_callback(
        callback_url: str,
        payload: dict[str, Any],
        timeout_seconds: float,
    ) -> tuple[int | None, str | None]:
        return AttachmentDeleteWorkflow.post_attachment_delete_callback(
            callback_url,
            payload,
            timeout_seconds,
        )

    async def _send_attachment_delete_callback(
        self,
        *,
        payload: dict[str, Any],
        callback_task_id: str,
    ) -> dict[str, Any]:
        return await self._attachment_delete_workflow().send_callback(
            payload=payload,
            callback_task_id=callback_task_id,
        )

    def _load_attachment_delete_callback_payload(self, callback: dict[str, Any]) -> dict[str, Any]:
        return self._attachment_delete_workflow().load_callback_payload(callback)

    async def _run_persisted_attachment_delete_callback_retries(
        self,
        *,
        callback_task_id: str,
        initial_delay_seconds: float,
    ) -> None:
        await self._attachment_delete_workflow().run_persisted_callback_retries(
            callback_task_id=callback_task_id,
            initial_delay_seconds=initial_delay_seconds,
        )

    def _schedule_attachment_delete_callback_retry_if_needed(self, *, callback_task_id: str) -> bool:
        return self._attachment_delete_workflow().schedule_callback_retry_if_needed(
            callback_task_id=callback_task_id,
        )

    def schedule_due_attachment_delete_callback_retries(self) -> None:
        self._attachment_delete_workflow().schedule_due_callback_retries()

    async def _notify_attachment_delete_success(
        self,
        *,
        brand: dict[str, Any],
        delete_result: dict[str, Any],
    ) -> None:
        await self._attachment_delete_workflow().notify_attachment_delete_success(
            brand=brand,
            delete_result=delete_result,
        )

    async def delete_documents_by_attachments(
        self,
        *,
        brand_code: str,
        attachments: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return await self._attachment_delete_workflow().delete_documents_by_attachments(
            brand_code=brand_code,
            attachments=attachments,
            notify_success=self._notify_attachment_delete_success,
        )

    async def delete_brand(self, request: BrandDeleteRequest) -> dict[str, Any]:
        return await self._brand_application().delete_brand(
            brand_name=request.brand_name,
            dry_run=request.dry_run,
        )

    async def start_brand_attachment_conflict_session(
        self,
        *,
        task_id: str,
        initial_message: str | None = None,
        publish_mode: str | None = "full_ingest",
    ) -> dict[str, Any]:
        # Historical compatibility: this legacy direct entrypoint defaults to
        # formal ingestion. New knowledge-base session APIs pass draft_only
        # explicitly from their request schema when the client omits a mode.
        return await self._brand_knowledge_application().start_attachment_conflict_session(
            task_id=task_id,
            initial_message=initial_message,
            publish_mode=publish_mode,
        )

    async def start_brand_knowledge_session(
        self,
        *,
        session_type: str,
        task_id: str | None = None,
        brand_code: str | None = None,
        brand_name: str | None = None,
        publish_mode: str | None = None,
        iteration_mode: str | None = None,
        initial_message: str | None = None,
        update_instruction: str | None = None,
    ) -> dict[str, Any]:
        normalized_session_type = str(session_type or "").strip()
        if normalized_session_type == "initial_generation":
            normalized_task_id = str(task_id or "").strip()
            if not normalized_task_id:
                raise ValueError("第一次生成会话 task_id 不能为空")
            return await self.start_brand_attachment_conflict_session(
                task_id=normalized_task_id,
                initial_message=initial_message,
                publish_mode=publish_mode,
            )
        if normalized_session_type == "knowledge_iteration":
            return await self._brand_knowledge_application().start_knowledge_iteration_session(
                brand_code=brand_code,
                brand_name=brand_name,
                task_id=task_id,
                publish_mode=publish_mode,
                iteration_mode=iteration_mode,
                initial_message=initial_message,
                update_instruction=update_instruction,
            )
        raise ValueError("不支持的知识会话类型")

    async def submit_brand_attachment_conflict_resolutions(
        self,
        *,
        session_id: str,
        round_no: int,
        resolutions: list[dict[str, Any]],
        force_reingest: bool = False,
        publish_mode: str | None = None,
    ) -> dict[str, Any]:
        return await self._brand_knowledge_application().submit_attachment_conflict_resolutions(
            session_id=session_id,
            round_no=round_no,
            resolutions=resolutions,
            force_reingest=force_reingest,
            publish_mode=publish_mode,
        )

    def get_latest_brand_attachment_conflict_session(
        self,
        *,
        brand_code: str,
        brand_name: str | None = None,
    ) -> dict[str, Any] | None:
        return self._brand_knowledge_status_queries().get_latest_brand_attachment_conflict_session(
            brand_code=brand_code,
            brand_name=brand_name,
        )

    def _resolve_latest_brand_update_markdown_status(
        self,
        *,
        brand_code: str,
        fallback_status: str | None = None,
    ) -> str:
        return self._brand_knowledge_status_queries().resolve_latest_brand_update_markdown_status(
            brand_code=brand_code,
            fallback_status=fallback_status,
        )

    def _count_pending_full_knowledge_audits(self, *, brand_code: str) -> int:
        return self._brand_knowledge_status_queries().count_pending_full_knowledge_audits(brand_code=brand_code)

    def _get_latest_brand_update_job(
        self,
        *,
        brand_code: str,
    ) -> dict[str, Any] | None:
        return self._brand_knowledge_status_queries().get_latest_brand_update_job(brand_code=brand_code)

    @staticmethod
    def _background_job_recency_sort_key(job: dict[str, Any]):
        return BrandKnowledgeStatusQueryService.background_job_recency_sort_key(job)

    @staticmethod
    def _parse_background_job_datetime(value: Any):
        return BrandKnowledgeStatusQueryService.parse_background_job_datetime(value)

    def _resolve_latest_brand_update_brand_name(
        self,
        *,
        brand_code: str,
        fallback_brand_name: str | None = None,
    ) -> str:
        return self._brand_knowledge_status_queries().resolve_latest_brand_update_brand_name(
            brand_code=brand_code,
            fallback_brand_name=fallback_brand_name,
        )

    async def preview_parse_brand_attachments(
        self,
        *,
        brand_name: str,
        brand_code: str | None,
        attachments: list[dict[str, str]],
    ) -> dict[str, Any]:
        return await self._attachment_preview_entry_service().preview_parse_brand_attachments(
            brand_name=brand_name,
            brand_code=brand_code,
            attachments=attachments,
        )

    def _attachment_preview_entry_service(self) -> AttachmentPreviewEntryService:
        return AttachmentPreviewEntryService(
            AttachmentPreviewEntryDependencies(
                brands=getattr(self, "_brands", None),
                upload_task_application=getattr(self, "_upload_task_app", None),
                attachment_draft_application=self._brand_knowledge_attachment_draft_application(),
            )
        )

    @staticmethod
    def _resolve_official_ai_knowledge_preview_attachment(
        attachments: list[dict[str, str]],
    ) -> dict[str, Any] | None:
        return AttachmentPreviewEntryService.resolve_official_ai_knowledge_preview_attachment(attachments)

    async def confirm_save_brand_attachments(
        self,
        *,
        request: AttachmentConfirmSaveRequest,
        draft_id: str,
    ) -> dict[str, Any]:
        return await self._brand_knowledge_attachment_draft_application().confirm_save(
            request=request,
            draft_id=draft_id,
        )

    async def review_brand_attachment_changes(
        self,
        *,
        request: AttachmentReviewChangesRequest,
        draft_id: str,
    ) -> dict[str, Any]:
        return await self._brand_knowledge_attachment_draft_application().review_changes(
            request=request,
            draft_id=draft_id,
        )

    async def ingest_from_url(
        self,
        url: str,
        name: str,
        category: str,
        metadata: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> IngestedDocument:
        return await self._ingest_application().ingest_from_url(
            url=url,
            name=name,
            category=category,
            metadata=metadata,
            task_id=task_id,
        )

    def get_full_text(self, document_id: str) -> str | None:
        return self._ingest_application().get_full_text(document_id)

    async def _ingest_image(
        self,
        *,
        temporary_path: Path,
        filename: str,
        document_id: str,
        metadata: dict[str, Any],
    ) -> IngestedDocument:
        return await self._ingest_application().ingest_image(
            temporary_path=temporary_path,
            filename=filename,
            document_id=document_id,
            metadata=metadata,
        )

    async def _ingest_document(
        self,
        *,
        temporary_path: Path,
        filename: str,
        document_id: str,
        metadata: dict[str, Any],
        chunk_size: int | None,
        chunk_overlap: int | None,
    ) -> IngestedDocument:
        return await self._ingest_application().ingest_document(
            temporary_path=temporary_path,
            filename=filename,
            document_id=document_id,
            metadata=metadata,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    async def _ingest_staged_file(
        self,
        *,
        staged_path: Path,
        filename: str,
        metadata: dict[str, Any],
        chunk_size: int | None,
        chunk_overlap: int | None,
        content_type: str | None = None,
    ) -> IngestedDocument:
        return await self._ingest_application().ingest_staged_file(
            staged_path=staged_path,
            filename=filename,
            metadata=metadata,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            content_type=content_type,
        )

    async def search_facts_by_brand_name(self, brand_name: str, query: str, top_k: int) -> list[dict[str, Any]]:
        return await self._search_facade().search_facts_by_brand_name(brand_name, query, top_k)

    async def search_facts(
        self,
        *,
        brand_code: str | None = None,
        brand_name: str | None = None,
        category: str | None = None,
        product_code: str | None = None,
        query: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        return await self._search_facade().search_facts(
            brand_code=brand_code,
            brand_name=brand_name,
            category=category,
            product_code=product_code,
            query=query,
            top_k=top_k,
        )

    async def search_facts_by_category(self, category: str, query: str, top_k: int) -> list[dict[str, Any]]:
        return await self._search_facade().search_facts_by_category(category, query, top_k)

    async def search_facts_by_brand_name_matched(self, brand_name: str, query: str, top_k: int) -> list[dict[str, Any]]:
        return await self._search_facade().search_facts_by_brand_name_matched(brand_name, query, top_k)

    async def search_facts_by_category_matched(self, category: str, query: str, top_k: int) -> list[dict[str, Any]]:
        return await self._search_facade().search_facts_by_category_matched(category, query, top_k)
