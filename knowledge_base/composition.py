from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import partial
from typing import Any

from knowledge_base.alerts.application import AlertApplicationDependencies, AlertApplicationService
from knowledge_base.alerts.infrastructure import get_feishu_notifier
from knowledge_base.background_jobs.application import BackgroundJobDependencies, BackgroundJobService
from knowledge_base.brand.application import (
    BrandAiKnowledgeIngestionDependencies,
    BrandAiKnowledgeIngestionService,
    BrandApplicationDependencies,
    BrandApplicationService,
)
from knowledge_base.brand.application.callbacks import (
    BrandCallbackCoordinator,
    bind_brand_callbacks,
    build_current_brand_callback_knowledge_for_service,
)
from knowledge_base.brand.full_markdown import (
    generate_full_brand_knowledge_markdown_from_confirmed_markdown,
    generate_full_brand_knowledge_markdown_from_update,
)
from knowledge_base.brand_knowledge.application import (
    AttachmentDraftDependencies,
    AttachmentDraftService,
    BrandKnowledgeApplicationDependencies,
    BrandKnowledgeApplicationService,
)
from knowledge_base.document.application import (
    DocumentApplicationDependencies,
    DocumentApplicationService,
)
from knowledge_base.ingest.application import IngestApplicationDependencies, IngestApplicationService
from knowledge_base.ingest.infrastructure import DocumentParser
from knowledge_base.infrastructure import EmbeddingService, MilvusVectorStore, OSSClient, QdrantVectorStore, Settings
from knowledge_base.search.application import SearchApplicationDependencies, SearchApplicationService
from knowledge_base.upload_task.application import (
    UploadTaskApplicationDependencies,
    UploadTaskApplicationService,
)
from knowledge_base.stores import (
    BackgroundJobStore,
    BrandAttachmentAssetStore,
    BrandFullKnowledgeStore,
    BrandKnowledgeFactStore,
    BrandKnowledgeIngestionJobStore,
    BrandKnowledgeUpdateAuditStore,
    BrandKnowledgeStore,
    BrandKnowledgeSessionStore,
    BrandProductStore,
    BrandStore,
    DocumentAlertStore,
    DocumentCategoryStore,
    DocumentFactRelationStore,
    DocumentRegistryStore,
    IndustryStore,
    UploadTaskStore,
)
from knowledge_base.stores.mysql_base import ensure_mysql_schema_ready


@dataclass(frozen=True)
class MySQLStores:
    background_jobs: BackgroundJobStore
    brand_attachment_assets: BrandAttachmentAssetStore
    brands: BrandStore
    brand_full_knowledge: BrandFullKnowledgeStore
    brand_knowledge_facts: BrandKnowledgeFactStore
    brand_knowledge_ingestion_jobs: BrandKnowledgeIngestionJobStore
    brand_knowledge_update_audits: BrandKnowledgeUpdateAuditStore
    brand_products: BrandProductStore
    brand_knowledge: BrandKnowledgeStore
    brand_knowledge_sessions: BrandKnowledgeSessionStore
    document_alerts: DocumentAlertStore
    document_categories: DocumentCategoryStore
    document_registry: DocumentRegistryStore
    fact_relations: DocumentFactRelationStore
    industries: IndustryStore
    upload_tasks: UploadTaskStore


@dataclass(frozen=True)
class KnowledgeBaseInfrastructure:
    parser: DocumentParser
    embeddings: EmbeddingService
    vector_store: MilvusVectorStore
    oss_client: OSSClient
    mysql_stores: MySQLStores
    runtime: "KnowledgeBaseRuntimeState"


@dataclass
class KnowledgeBaseRuntimeState:
    upload_queue: asyncio.Queue[str]
    queued_task_ids: set[str]
    queue_lock: asyncio.Lock
    worker_task: asyncio.Task[None] | None = None
    background_job_worker_task: asyncio.Task[None] | None = None
    queued_background_job_ids: set[str] | None = None
    background_job_queue: asyncio.Queue[str] | None = None
    background_job_queue_lock: asyncio.Lock | None = None
    inflight_brand_callbacks: set[str] | None = None
    scheduled_brand_callback_retries: set[str] | None = None
    scheduled_brand_completion_checks: set[str] | None = None
    scheduled_attachment_conflict_callback_retries: set[str] | None = None
    scheduled_attachment_confirm_callback_retries: set[str] | None = None
    scheduled_attachment_delete_callback_retries: set[str] | None = None


@dataclass(frozen=True)
class KnowledgeBaseApplications:
    alert_app: AlertApplicationService
    brand_callbacks: BrandCallbackCoordinator
    background_jobs: BackgroundJobService | None
    brand_app: BrandApplicationService
    brand_knowledge_attachment_draft_app: AttachmentDraftService
    brand_knowledge_app: BrandKnowledgeApplicationService
    document_app: DocumentApplicationService
    ingest_app: IngestApplicationService
    search_app: SearchApplicationService
    upload_task_app: UploadTaskApplicationService


def _ensure_background_job_runtime_ready(runtime: KnowledgeBaseRuntimeState) -> None:
    if runtime.background_job_queue is None:
        runtime.background_job_queue = asyncio.Queue()
    if runtime.queued_background_job_ids is None:
        runtime.queued_background_job_ids = set()
    if runtime.background_job_queue_lock is None:
        runtime.background_job_queue_lock = asyncio.Lock()


def _optional_app_method(app: Any | None, method_name: str) -> Any | None:
    if app is None:
        return None
    return getattr(app, method_name, None)


def _build_full_knowledge_from_update_for_service(
    kb_service: object,
    **kwargs: Any,
) -> Any:
    generated_payload = generate_full_brand_knowledge_markdown_from_update(
        kb_service,
        **kwargs,
    )
    return _ingest_generated_full_knowledge_for_service(
        kb_service,
        generated_payload=generated_payload,
    )


def _build_full_knowledge_from_confirmed_markdown_for_service(
    kb_service: object,
    **kwargs: Any,
) -> Any:
    generated_payload = generate_full_brand_knowledge_markdown_from_confirmed_markdown(
        kb_service,
        **kwargs,
    )
    return _ingest_generated_full_knowledge_for_service(
        kb_service,
        generated_payload=generated_payload,
    )


def _generate_full_knowledge_from_confirmed_markdown_for_service(
    kb_service: object,
    **kwargs: Any,
) -> Any:
    return generate_full_brand_knowledge_markdown_from_confirmed_markdown(
        kb_service,
        **kwargs,
    )


async def _ingest_generated_full_knowledge_for_service(
    kb_service: object,
    *,
    generated_payload: Any,
) -> dict[str, Any]:
    resolved_generated_payload = await generated_payload if asyncio.iscoroutine(generated_payload) else generated_payload
    if not isinstance(resolved_generated_payload, dict):
        raise ValueError("generated_payload 必须是 dict")
    ingestion_service = getattr(kb_service, "_brand_ai_knowledge_ingestion", None)
    if ingestion_service is None:
        raise RuntimeError("brand ai knowledge ingestion service is not initialized")

    brand_code = str(resolved_generated_payload.get("brand_code") or "").strip()
    brand_name = str(resolved_generated_payload.get("brand_name") or "").strip()
    file_name = str(resolved_generated_payload.get("file_name") or "").strip()
    markdown_text = str(resolved_generated_payload.get("knowledge_markdown") or "").strip()
    source_task_id = str(resolved_generated_payload.get("source_task_id") or "").strip() or None
    change_origin = str(resolved_generated_payload.get("change_origin") or "").strip() or None
    if not brand_code or not brand_name or not file_name or not markdown_text:
        raise ValueError("generated_payload 缺少正式入库所需字段")

    task_id = source_task_id or f"brand_ai_knowledge:{brand_code}:{file_name}"
    ingest_result = await ingestion_service.ingest_generated_markdown(
        task_id=task_id,
        upload_task_file_id=0,
        filename=file_name,
        brand_code=brand_code,
        brand_name=brand_name,
        markdown_text=markdown_text,
        force_reingest=False,
        source_task_id=source_task_id,
        change_origin=change_origin or "api",
        job_id=f"brand-ai-kb-generated:{task_id}"[:128],
    )
    return {
        **resolved_generated_payload,
        "status": ingest_result.get("status"),
        "skipped": ingest_result.get("skipped"),
        "document_id": ingest_result.get("document_id"),
        "full_knowledge_file_id": ingest_result.get("full_knowledge_file_id"),
        "knowledge_revision": ingest_result.get("knowledge_revision"),
        "change_origin": ingest_result.get("change_origin") or change_origin,
        "knowledge_oss_key_md": ingest_result.get("markdown_oss_key"),
        "knowledge_oss_url_md": ingest_result.get("markdown_oss_url"),
        "knowledge_oss_key_pdf": ingest_result.get("pdf_oss_key"),
        "knowledge_oss_url_pdf": ingest_result.get("pdf_oss_url"),
        "cleanup": ingest_result.get("cleanup"),
    }


def _process_upload_task_for_service(kb_service: object, task_id: str) -> Any:
    return kb_service._upload_task_application().process_upload_task(task_id)


def _process_attachment_confirm_pipeline_for_service(
    kb_service: object,
    **kwargs: Any,
) -> Any:
    return kb_service._brand_knowledge_attachment_draft_application().process_confirm_pipeline_job(
        **kwargs,
    )


def _process_attachment_conflict_resolution_for_service(
    kb_service: object,
    **kwargs: Any,
) -> Any:
    return kb_service._brand_knowledge_application().process_attachment_conflict_resolution_job(
        **kwargs,
    )


async def _notify_ai_failure_if_ready(
    alert_app: AlertApplicationService,
    *,
    category: str,
    file_hash: str,
) -> None:
    await alert_app.notify_ai_failure_if_ready(
        category=category,
        file_hash=file_hash,
    )


async def _finalize_task_callback_from_document(
    brand_callback_coordinator: BrandCallbackCoordinator,
    *,
    category: str,
    file_hash: str,
) -> None:
    await brand_callback_coordinator.maybe_finalize_task_callback_from_document(
        category=category,
        file_hash=file_hash,
    )


async def _notify_upload_failure(
    alert_app: AlertApplicationService,
    **kwargs: Any,
) -> None:
    await alert_app.notify_upload_failure(**kwargs)


def _schedule_delayed_completion_check(
    brand_callback_coordinator: BrandCallbackCoordinator,
    task_id: str,
    *,
    delay_seconds: int = 600,
) -> None:
    brand_callback_coordinator.schedule_delayed_completion_check(
        task_id,
        delay_seconds=delay_seconds,
    )


def build_mysql_stores(settings: Settings) -> MySQLStores:
    ensure_mysql_schema_ready(
        settings=settings,
        migrations_dir=BrandStore.MIGRATIONS_DIR,
        migrations_table=BrandStore.MIGRATIONS_TABLE,
    )
    return MySQLStores(
        background_jobs=BackgroundJobStore(settings),
        brand_attachment_assets=BrandAttachmentAssetStore(settings),
        brands=BrandStore(settings),
        brand_full_knowledge=BrandFullKnowledgeStore(settings),
        brand_knowledge_facts=BrandKnowledgeFactStore(settings),
        brand_knowledge_ingestion_jobs=BrandKnowledgeIngestionJobStore(settings),
        brand_knowledge_update_audits=BrandKnowledgeUpdateAuditStore(settings),
        brand_products=BrandProductStore(settings),
        brand_knowledge=BrandKnowledgeStore(settings),
        brand_knowledge_sessions=BrandKnowledgeSessionStore(settings),
        document_alerts=DocumentAlertStore(settings),
        document_categories=DocumentCategoryStore(settings),
        document_registry=DocumentRegistryStore(settings),
        fact_relations=DocumentFactRelationStore(settings),
        industries=IndustryStore(settings),
        upload_tasks=UploadTaskStore(settings),
    )


def build_vector_store(settings: Settings, dimension: int) -> Any:
    backend = str(getattr(settings, "vector_store_backend", "milvus") or "milvus").strip().lower()
    if backend == "milvus":
        return MilvusVectorStore(settings, dimension)
    if backend == "qdrant":
        return QdrantVectorStore(settings, dimension)
    raise ValueError(f"Unsupported vector store backend: {backend}")


def build_infrastructure(settings: Settings) -> KnowledgeBaseInfrastructure:
    embeddings = EmbeddingService(settings)
    return KnowledgeBaseInfrastructure(
        parser=DocumentParser(settings),
        embeddings=embeddings,
        vector_store=build_vector_store(settings, embeddings.dimension),
        oss_client=OSSClient(settings),
        mysql_stores=build_mysql_stores(settings),
        runtime=KnowledgeBaseRuntimeState(
            upload_queue=asyncio.Queue(),
            queued_task_ids=set(),
            queue_lock=asyncio.Lock(),
            background_job_queue=asyncio.Queue(),
            queued_background_job_ids=set(),
            background_job_queue_lock=asyncio.Lock(),
            inflight_brand_callbacks=set(),
            scheduled_brand_callback_retries=set(),
            scheduled_brand_completion_checks=set(),
            scheduled_attachment_conflict_callback_retries=set(),
            scheduled_attachment_confirm_callback_retries=set(),
            scheduled_attachment_delete_callback_retries=set(),
        ),
    )


def build_applications(kb_service: object) -> KnowledgeBaseApplications:
    brand_callback_coordinator = bind_brand_callbacks(kb_service)
    _ensure_background_job_runtime_ready(kb_service._runtime)
    background_job_app = (
        BackgroundJobService(
            BackgroundJobDependencies(
                settings=kb_service._settings,
                background_jobs=kb_service._background_jobs,
                store=kb_service._store,
                brands=kb_service._brands,
                upload_tasks=kb_service._upload_tasks,
                build_full_knowledge_from_update=partial(_build_full_knowledge_from_update_for_service, kb_service),
                build_full_knowledge_from_confirmed_markdown=partial(
                    _build_full_knowledge_from_confirmed_markdown_for_service,
                    kb_service,
                ),
                process_upload_task=partial(_process_upload_task_for_service, kb_service),
                process_attachment_confirm_pipeline=partial(
                    _process_attachment_confirm_pipeline_for_service,
                    kb_service,
                ),
                process_attachment_conflict_resolution=partial(
                    _process_attachment_conflict_resolution_for_service,
                    kb_service,
                ),
                build_current_brand_callback_knowledge=partial(
                    build_current_brand_callback_knowledge_for_service,
                    kb_service,
                ),
                brand_knowledge_update_audits=getattr(kb_service, "_brand_knowledge_update_audits", None),
                oss_client=kb_service.oss_client,
                queue=kb_service._runtime.background_job_queue,
                queued_job_ids=kb_service._runtime.queued_background_job_ids,
                queue_lock=kb_service._runtime.background_job_queue_lock,
            )
        )
        if getattr(kb_service, "_background_jobs", None) is not None
        else None
    )
    alert_app = AlertApplicationService(
        AlertApplicationDependencies(
            settings=kb_service._settings,
            document_alerts=kb_service._document_alerts,
            document_registry=kb_service._document_registry,
            notifier=get_feishu_notifier(kb_service._settings),
        )
    )
    document_dependencies = DocumentApplicationDependencies(
        settings=kb_service._settings,
        store=kb_service._store,
        embeddings=kb_service._embeddings,
        document_categories=kb_service._document_categories,
        document_registry=kb_service._document_registry,
        fact_relations=kb_service._fact_relations,
        oss_client=kb_service.oss_client,
        get_document_info=kb_service._get_document_info,
        get_full_text=kb_service.get_full_text,
        notify_ai_failure_if_ready=partial(
            _notify_ai_failure_if_ready,
            alert_app,
        ),
        finalize_task_callback_from_document=partial(
            _finalize_task_callback_from_document,
            brand_callback_coordinator,
        ),
        brands=kb_service._brands,
        brand_products=kb_service._brand_products,
        brand_full_knowledge=kb_service._brand_full_knowledge,
    )
    document_app = DocumentApplicationService(document_dependencies)
    ingest_app = IngestApplicationService(
        IngestApplicationDependencies(kb_service=kb_service)
    )
    brand_ai_knowledge_ingestion_service = BrandAiKnowledgeIngestionService(
        BrandAiKnowledgeIngestionDependencies(
            settings=kb_service._settings,
            brands=kb_service._brands,
            parser=kb_service._parser,
            embeddings=kb_service._embeddings,
            store=kb_service._store,
            oss_client=kb_service.oss_client,
            brand_full_knowledge=kb_service._brand_full_knowledge,
            brand_knowledge_facts=getattr(kb_service, "_brand_knowledge_facts", None),
            brand_knowledge_ingestion_jobs=getattr(kb_service, "_brand_knowledge_ingestion_jobs", None),
            brand_knowledge=getattr(kb_service, "_brand_knowledge", None),
            brand_products=getattr(kb_service, "_brand_products", None),
        )
    )
    kb_service._brand_ai_knowledge_ingestion = brand_ai_knowledge_ingestion_service
    brand_dependencies = BrandApplicationDependencies(
        settings=kb_service._settings,
        brands=kb_service._brands,
        brand_products=kb_service._brand_products,
        brand_knowledge=kb_service._brand_knowledge,
        brand_full_knowledge=kb_service._brand_full_knowledge,
        industries=kb_service._industries,
        brand_knowledge_sessions=kb_service._brand_knowledge_sessions,
        document_registry=kb_service._document_registry,
        document_categories=kb_service._document_categories,
        fact_relations=kb_service._fact_relations,
        store=kb_service._store,
        document_app=document_app,
        upload_tasks=kb_service._upload_tasks,
        brand_attachment_assets=getattr(kb_service, "_brand_attachment_assets", None),
        brand_knowledge_facts=getattr(kb_service, "_brand_knowledge_facts", None),
        delete_document=kb_service.delete_document,
        get_full_text=kb_service.get_full_text,
        ingest_staged_file=ingest_app.ingest_staged_file,
        ingest_from_url=kb_service.ingest_from_url,
        delete_document_by_attachment_name=document_app.delete_document_by_attachment_name,
        oss_client=kb_service.oss_client,
        parser=kb_service._parser,
        brand_knowledge_ingestion_jobs=getattr(kb_service, "_brand_knowledge_ingestion_jobs", None),
        brand_knowledge_update_audits=getattr(kb_service, "_brand_knowledge_update_audits", None),
        background_jobs=kb_service._background_jobs,
        enqueue_brand_knowledge_update_job=_optional_app_method(
            background_job_app,
            "enqueue_brand_knowledge_update",
        ),
        enqueue_brand_full_knowledge_refresh_job=_optional_app_method(
            background_job_app,
            "enqueue_brand_full_knowledge_refresh",
        ),
        build_next_brand_full_knowledge=partial(_build_full_knowledge_from_update_for_service, kb_service),
    )
    brand_app = BrandApplicationService(brand_dependencies)
    brand_knowledge_app = BrandKnowledgeApplicationService(
        BrandKnowledgeApplicationDependencies(
            settings=kb_service._settings,
            brands=kb_service._brands,
            brand_knowledge_sessions=kb_service._brand_knowledge_sessions,
            document_registry=kb_service._document_registry,
            brand_products=kb_service._brand_products,
            brand_knowledge=kb_service._brand_knowledge,
            tianyancha_client=getattr(kb_service, "_tianyancha_client", None),
            upload_tasks=kb_service._upload_tasks,
            attachment_assets=getattr(kb_service, "_brand_attachment_assets", None),
            brand_full_knowledge=kb_service._brand_full_knowledge,
            brand_ai_knowledge_ingestion=brand_ai_knowledge_ingestion_service,
            oss_client=kb_service.oss_client,
            parser=kb_service._parser,
            embeddings=kb_service._embeddings,
            brand_knowledge_facts=getattr(kb_service, "_brand_knowledge_facts", None),
            background_jobs=kb_service._background_jobs,
            store=kb_service._store,
            get_full_text=kb_service.get_full_text,
            runtime=kb_service._runtime,
            spawn_background_task=kb_service._spawn_background_task,
            enqueue_attachment_conflict_resolution_job=_optional_app_method(
                background_job_app,
                "enqueue_attachment_conflict_resolution",
            ),
            build_current_brand_callback_knowledge=partial(
                build_current_brand_callback_knowledge_for_service,
                kb_service,
            ),
            build_next_brand_full_knowledge=partial(
                _build_full_knowledge_from_confirmed_markdown_for_service,
                kb_service,
            ),
            generate_next_brand_full_knowledge=partial(
                _generate_full_knowledge_from_confirmed_markdown_for_service,
                kb_service,
            ),
        )
    )
    brand_knowledge_attachment_draft_app = AttachmentDraftService(
        AttachmentDraftDependencies(
            settings=kb_service._settings,
            parser=kb_service._parser,
            oss_client=kb_service.oss_client,
            brands=kb_service._brands,
            brand_products=kb_service._brand_products,
            brand_knowledge=kb_service._brand_knowledge,
            brand_full_knowledge=kb_service._brand_full_knowledge,
            update_knowledge=kb_service.update_knowledge,
            tianyancha_client=getattr(kb_service, "_tianyancha_client", None),
            ingest_staged_file=ingest_app.ingest_staged_file,
            build_next_brand_full_knowledge=partial(
                _build_full_knowledge_from_confirmed_markdown_for_service,
                kb_service,
            ),
            enqueue_brand_full_knowledge_refresh_job=_optional_app_method(
                background_job_app,
                "enqueue_brand_full_knowledge_refresh",
            ),
            enqueue_attachment_confirm_pipeline_job=_optional_app_method(
                background_job_app,
                "enqueue_attachment_confirm_pipeline",
            ),
            enqueue_attachment_confirm_job=_optional_app_method(
                background_job_app,
                "enqueue_attachment_confirm",
            ),
            runtime=kb_service._runtime,
            spawn_background_task=kb_service._spawn_background_task,
            upload_tasks=kb_service._upload_tasks,
        )
    )
    upload_task_dependencies = UploadTaskApplicationDependencies(
        settings=kb_service._settings,
        brands=kb_service._brands,
        brand_products=kb_service._brand_products,
        industries=kb_service._industries,
        document_registry=kb_service._document_registry,
        document_categories=kb_service._document_categories,
        upload_tasks=kb_service._upload_tasks,
        queue=kb_service._runtime.upload_queue,
        queued_task_ids=kb_service._runtime.queued_task_ids,
        queue_lock=kb_service._runtime.queue_lock,
        ingest_text_document=ingest_app.ingest_text_document,
        ingest_from_url=ingest_app.ingest_from_url,
        ingest_staged_file=ingest_app.ingest_staged_file,
        notify_failed_upload_files=partial(
            upload_tasks_notify_failed_upload_files,
            kb_service,
        ),
        notify_upload_failure=partial(
            _notify_upload_failure,
            alert_app,
        ),
        schedule_delayed_completion_check=partial(
            _schedule_delayed_completion_check,
            brand_callback_coordinator,
        ),
        parser=kb_service._parser,
        brand_ai_knowledge_ingestion=brand_ai_knowledge_ingestion_service,
        brand_full_knowledge=kb_service._brand_full_knowledge,
        brand_knowledge_ingestion_jobs=getattr(kb_service, "_brand_knowledge_ingestion_jobs", None),
        brand_knowledge_sessions=getattr(kb_service, "_brand_knowledge_sessions", None),
        attachment_assets=getattr(kb_service, "_brand_attachment_assets", None),
        oss_client=kb_service.oss_client,
        embeddings=kb_service._embeddings,
        store=kb_service._store,
        enqueue_upload_task_process_job=_optional_app_method(
            background_job_app,
            "enqueue_upload_task_process",
        ),
    )
    search_dependencies = SearchApplicationDependencies(
        settings=kb_service._settings,
        store=kb_service._store,
        embeddings=kb_service._embeddings,
        brands=kb_service._brands,
        brand_products=kb_service._brand_products,
        brand_app=brand_app,
        document_app=document_app,
        document_categories=kb_service._document_categories,
        brand_full_knowledge=kb_service._brand_full_knowledge,
        attachment_assets=getattr(kb_service, "_brand_attachment_assets", None),
    )
    search_app = SearchApplicationService(search_dependencies)
    return KnowledgeBaseApplications(
        alert_app=alert_app,
        brand_callbacks=brand_callback_coordinator,
        background_jobs=background_job_app,
        brand_app=brand_app,
        brand_knowledge_attachment_draft_app=brand_knowledge_attachment_draft_app,
        brand_knowledge_app=brand_knowledge_app,
        document_app=document_app,
        ingest_app=ingest_app,
        search_app=search_app,
        upload_task_app=UploadTaskApplicationService(upload_task_dependencies),
    )


__all__ = [
    "KnowledgeBaseApplications",
    "KnowledgeBaseInfrastructure",
    "KnowledgeBaseRuntimeState",
    "MySQLStores",
    "build_applications",
    "build_infrastructure",
    "build_mysql_stores",
    "build_vector_store",
]


async def upload_tasks_notify_failed_upload_files(kb_service: object, task_id: str) -> None:
    alert_app = AlertApplicationService(
        AlertApplicationDependencies(
            settings=kb_service._settings,
            document_alerts=kb_service._document_alerts,
            document_registry=kb_service._document_registry,
            notifier=get_feishu_notifier(kb_service._settings),
        )
    )
    for item in kb_service._upload_tasks.get_upload_task_files(task_id):
        if item.get("status") != "failed":
            continue
        await alert_app.notify_upload_failure(
            task_id=task_id,
            file_index=int(item["file_index"]),
            original_filename=str(item.get("original_filename") or ""),
            error_message=item.get("error_message"),
            created_at=item.get("created_at"),
        )
