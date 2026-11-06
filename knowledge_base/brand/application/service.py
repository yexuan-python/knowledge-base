from __future__ import annotations

import asyncio
import logging
import re
import threading
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from time import monotonic, sleep
from typing import Any

from knowledge_base.brand.application.brand_update_workflow import (
    BrandKnowledgeUpdateWorkflowMixin,
)
from knowledge_base.brand.application.brand_delete_workflow import (
    BrandDeleteWorkflowMixin,
)
from knowledge_base.brand.application.brand_asset_rendering import (
    BrandAssetRenderingMixin,
)
from knowledge_base.brand.application.brand_path_caching import (
    BrandPathCachingMixin,
)
from knowledge_base.brand.application.brand_service_normalization import (
    BrandServiceNormalizationMixin,
)
from knowledge_base.brand.application.brand_service_support import (
    BrandServiceSupportMixin,
)
from knowledge_base.brand.application.brand_update_context import (
    BrandKnowledgeUpdateContextMixin,
)
from knowledge_base.brand.application.brand_update_sections import (
    BrandKnowledgeUpdateSectionsMixin,
)
from knowledge_base.brand.application.brand_update_followup import (
    BrandKnowledgeUpdateFollowupMixin,
)
from knowledge_base.brand.application.brand_read_workflow import (
    BrandReadWorkflowMixin,
)
from knowledge_base.brand.application.brand_path_rendering import (
    BrandPathRenderingMixin,
)
from knowledge_base.brand.application.brand_structured_search import (
    BrandStructuredSearchMixin,
)
from knowledge_base.brand_knowledge.application.service import (
    BrandKnowledgeApplicationDependencies,
    BrandKnowledgeApplicationService,
)
from knowledge_base.document.ai import summarize_text
from knowledge_base.ingest.application.remote_download import (
    download_remote_content_to_temp_file,
)
from knowledge_base.shared.utils import parse_metadata_json
from knowledge_base.shared.utils.oss_keys import sanitize_oss_segment


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BrandApplicationDependencies:
    settings: Any
    brands: Any
    brand_products: Any
    brand_knowledge: Any
    industries: Any
    brand_knowledge_sessions: Any
    document_registry: Any
    document_categories: Any
    fact_relations: Any
    store: Any
    document_app: Any
    upload_tasks: Any = None
    brand_attachment_assets: Any = None
    brand_knowledge_facts: Any = None
    delete_document: Any = None
    get_full_text: Any = None
    ingest_staged_file: Any = None
    ingest_from_url: Any = None
    delete_document_by_attachment_name: Any = None
    brand_full_knowledge: Any = None
    brand_knowledge_ingestion_jobs: Any = None
    oss_client: Any = None
    parser: Any = None
    background_jobs: Any = None
    enqueue_brand_knowledge_update_job: Any = None
    enqueue_brand_full_knowledge_refresh_job: Any = None
    build_next_brand_full_knowledge: Any = None
    brand_knowledge_update_audits: Any = None

class BrandApplicationService(
    BrandPathCachingMixin,
    BrandServiceNormalizationMixin,
    BrandServiceSupportMixin,
    BrandKnowledgeUpdateContextMixin,
    BrandKnowledgeUpdateSectionsMixin,
    BrandKnowledgeUpdateFollowupMixin,
    BrandPathRenderingMixin,
    BrandAssetRenderingMixin,
    BrandReadWorkflowMixin,
    BrandKnowledgeUpdateWorkflowMixin,
    BrandStructuredSearchMixin,
    BrandDeleteWorkflowMixin,
):
    PATH_INDEX_SUMMARY_MAX_CONCURRENCY = 4
    PATH_INDEX_SUMMARY_MAX_CONTENT_CHARS = 5000
    _AI_KNOWLEDGE_FILENAME_PATTERN = re.compile(r"_V(?P<version>\d+)_(?P<date>\d{8})\.md$")
    _MYSQL_RENAME_RETRY_DELAYS_SECONDS = (0.2, 0.5)
    _MARKDOWN_HEADING_RE = re.compile(r"^(?P<level>#{1,6})\s+(?P<title>.+?)\s*$")
    _MARKDOWN_BOLD_BULLET_TITLE_RE = re.compile(r"^\s*-\s+\*\*(?P<title>.+?)\*\*\s*$")
    _MARKDOWN_BOLD_BULLET_FIELD_RE = re.compile(r"^\s*-\s+\*\*(?P<label>.+?)\*\*\s*[：:]\s*(?P<value>.*)$")
    _MARKDOWN_TITLE_PREFIX_RE = re.compile(
        r"^(?:第?[一二三四五六七八九十百千万零〇\d]+(?:\.\d+)*[、.．:\s]*)+"
    )
    ATTACHMENT_PRODUCTS_KNOWLEDGE_TYPE = "attachment_products"
    ATTACHMENT_PRODUCTS_OTHER_INFO_TITLE = "附件解析新增产品"
    _ATTACHMENT_PRODUCT_TEXT_FIELDS = (
        "product_alias",
        "product_description",
        "product_website",
        "price_info",
        "product_advantages",
        "target_scenarios",
        "service_standard",
        "service_process",
        "cases_and_reputation",
        "certification_info",
        "core_technology",
        "other_info",
    )
    _ATTACHMENT_PRODUCT_LIST_FIELDS = (
        "product_images",
        "coverage_regions",
    )
    BRAND_OVERVIEW_PATH = "品牌基础信息/品牌介绍"
    COMPANY_PROFILE_PATH = "品牌基础信息/公司档案"
    MANAGEMENT_TEAM_PATH = "品牌基础信息/管理团队"
    HONORS_PATH = "品牌基础信息/权威荣誉"
    CASES_PATH = "品牌基础信息/客户案例"
    SENSITIVE_TOPICS_PATH = "品牌基础信息/敏感话题"
    ATTACHMENTS_PATH = "品牌基础信息/附件资料"
    OFFICIAL_MALLS_PATH = "品牌基础信息/官方商城"
    OFFICIAL_MEDIA_MATRIX_PATH = "品牌基础信息/官方媒体与矩阵"
    def __init__(self, dependencies: BrandApplicationDependencies) -> None:
        self._deps = dependencies
        self._brand_paths_load_cache_ttl_seconds = max(
            0.0,
            float(getattr(self._deps.settings, "brand_paths_load_cache_ttl_seconds", 600.0) or 0.0),
        )
        self._brand_paths_load_cache_max_entries = max(
            0,
            int(getattr(self._deps.settings, "brand_paths_load_cache_max_entries", 100) or 0),
        )
        self._brand_paths_load_cache_cleanup_interval_seconds = min(
            self._brand_paths_load_cache_ttl_seconds or 60.0,
            60.0,
        )
        self._brand_paths_load_cache_stats_log_interval_seconds = min(
            self._brand_paths_load_cache_ttl_seconds or 300.0,
            300.0,
        )
        self._brand_paths_load_cache: dict[tuple[str, str, str], tuple[float, float, dict[str, Any]]] = {}
        self._brand_paths_load_cache_lock = threading.Lock()
        self._brand_paths_load_cache_last_cleanup_at = monotonic()
        self._brand_paths_load_cache_last_stats_log_at = monotonic()
        self._path_index_summary_cache_ttl_seconds = self._brand_paths_load_cache_ttl_seconds
        self._path_index_summary_cache_max_entries = max(
            0,
            int(getattr(self._deps.settings, "path_index_summary_cache_max_entries", 800) or 0),
        )
        self._path_index_summary_cache_cleanup_interval_seconds = min(
            self._path_index_summary_cache_ttl_seconds or 60.0,
            60.0,
        )
        self._path_index_summary_cache: dict[tuple[str, str, str], tuple[float, float, str]] = {}
        self._path_index_summary_cache_lock = threading.Lock()
        self._path_index_summary_cache_last_cleanup_at = monotonic()

    @staticmethod
    def _normalize_session_payload(
        payload: dict[str, Any],
        *,
        allow_completed: bool,
        fallback_summary: str | None = None,
    ) -> dict[str, Any]:
        return BrandKnowledgeApplicationService._normalize_session_payload(
            payload,
            allow_completed=allow_completed,
            fallback_summary=fallback_summary,
        )

    def _brand_knowledge_application(self) -> BrandKnowledgeApplicationService:
        return BrandKnowledgeApplicationService(
            BrandKnowledgeApplicationDependencies(
                settings=self._deps.settings,
                brands=self._deps.brands,
                brand_knowledge_sessions=self._deps.brand_knowledge_sessions,
                document_registry=self._deps.document_registry,
                store=self._deps.store,
                get_full_text=self._deps.get_full_text,
            )
        )

    async def _summarize_text(
        self,
        text: str,
        *,
        model: str | None = None,
        settings: Any | None = None,
    ) -> str:
        return await summarize_text(text, model=model, settings=settings)

    @staticmethod
    def _brand_id_from_row(brand: dict[str, Any] | None) -> int | None:
        if not isinstance(brand, dict):
            return None
        brand_id = brand.get("id")
        if brand_id is None:
            return None
        try:
            return int(brand_id)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _brand_code_from_row(brand: dict[str, Any] | None, fallback: str | None = None) -> str | None:
        if isinstance(brand, dict):
            brand_code = str(brand.get("brand_code") or "").strip()
            if brand_code:
                return brand_code
        normalized_fallback = str(fallback or "").strip()
        return normalized_fallback or None

    @staticmethod
    def _brand_name_from_row(brand: dict[str, Any] | None, fallback: str | None = None) -> str | None:
        if isinstance(brand, dict):
            brand_name = str(brand.get("brand_name") or "").strip()
            if brand_name:
                return brand_name
        normalized_fallback = str(fallback or "").strip()
        return normalized_fallback or None

    def list_brands(self, *, keyword: str | None = None) -> list[dict[str, Any]]:
        items = self._deps.brands.list_brands(keyword=keyword)
        normalized_items: list[dict[str, Any]] = []
        for item in items:
            normalized_item = dict(item)
            normalized_item["website"] = self._normalize_websites(item.get("website"))
            normalized_items.append(normalized_item)
        return normalized_items

    def rename_brand(self, *, brand_code: str, new_brand_name: str) -> dict[str, Any] | None:
        normalized_brand_code = str(brand_code or "").strip()
        normalized_new_brand_name = str(new_brand_name or "").strip()
        if not normalized_brand_code:
            raise ValueError("brand_code 不能为空")
        if not normalized_new_brand_name:
            raise ValueError("new_brand_name 不能为空")

        result: dict[str, Any] | None = None
        for attempt in range(1, 4):
            try:
                result = self._deps.brands.rename_brand(
                    brand_code=normalized_brand_code,
                    new_brand_name=normalized_new_brand_name,
                )
                break
            except Exception as exc:  # noqa: BLE001
                if not self._should_retry_mysql_brand_rename(exc) or attempt >= 3:
                    raise
                sleep(
                    self._MYSQL_RENAME_RETRY_DELAYS_SECONDS[
                        min(attempt - 1, len(self._MYSQL_RENAME_RETRY_DELAYS_SECONDS) - 1)
                    ]
                )
        if result is None:
            return None
        updated_tables = list(result.get("updated_tables") or [])
        if updated_tables:
            if self._deps.document_categories is not None and hasattr(
                self._deps.document_categories,
                "invalidate_latest_document_ids_cache",
            ):
                self._deps.document_categories.invalidate_latest_document_ids_cache()
            self._clear_brand_path_caches()
        background_job = result.get("background_job")
        if isinstance(background_job, dict):
            result["background_job_id"] = str(background_job.get("job_id") or "").strip() or None
            result["background_job_status"] = str(background_job.get("status") or "").strip() or None
        return result

    @staticmethod
    def _should_retry_mysql_brand_rename(exc: Exception) -> bool:
        if isinstance(exc, (ValueError, TypeError, LookupError, AssertionError)):
            return False
        exc_name = exc.__class__.__name__
        if exc_name not in {"OperationalError", "InterfaceError"}:
            return False
        error_code = BrandApplicationService._mysql_error_code(exc)
        return error_code in {1205, 1213, 2006, 2013, 2014, 2016, 2055}

    @staticmethod
    def _mysql_error_code(exc: Exception) -> int | None:
        if not getattr(exc, "args", None):
            return None
        code = exc.args[0]
        try:
            return int(code)
        except (TypeError, ValueError):
            return None

    def get_latest_ai_knowledge(self, *, brand_code: str) -> dict[str, Any] | None:
        normalized_brand_code = (brand_code or "").strip()
        if not normalized_brand_code:
            raise ValueError("brand_code 不能为空")

        brand = self._deps.brands.get_brand_by_code(normalized_brand_code)
        if not brand:
            return None
        brand_id = self._brand_id_from_row(brand)
        if brand_id is None:
            return None
        brand_code = str(self._brand_code_from_row(brand, normalized_brand_code) or "").strip()
        brand_name = str(self._brand_name_from_row(brand) or "").strip()
        if not brand_name:
            raise ValueError("无法确定品牌名称")

        latest_row = None
        store = self._deps.brand_full_knowledge
        if store is not None:
            if hasattr(store, "get_latest_by_brand_code") and brand_code:
                latest_row = store.get_latest_by_brand_code(brand_code=brand_code)
            elif hasattr(store, "get_latest_by_brand_id"):
                latest_row = store.get_latest_by_brand_id(brand_id=brand_id)
        if latest_row:
            oss_key = str(latest_row.get("oss_key") or "").strip()
            file_name = str(latest_row.get("file_name") or "").strip()
            if oss_key and file_name:
                oss_url = self._build_oss_download_url(oss_key)
                if oss_url:
                    return {
                        "brand_id": brand_id,
                        "brand_code": brand_code,
                        "brand_name": brand_name,
                        "file_name": file_name,
                        "oss_key": oss_key,
                        "oss_url": oss_url,
                        "version_no": self._normalize_int(latest_row.get("version_no")),
                        "created_at": latest_row.get("created_at"),
                        "source": "brand_full_knowledge_files",
                    }

        latest_oss_key = self._find_latest_ai_knowledge_markdown_oss_key(brand_name=brand_name)
        if not latest_oss_key:
            return {
                "brand_id": brand_id,
                "brand_code": brand_code,
                "brand_name": brand_name,
                "file_name": "",
                "oss_key": "",
                "oss_url": "",
                "version_no": None,
                "created_at": None,
                "source": "oss",
            }
        oss_url = self._build_oss_download_url(latest_oss_key)
        if not oss_url:
            raise RuntimeError("OSS 下载链接生成失败")
        return {
            "brand_id": brand_id,
            "brand_code": brand_code,
            "brand_name": brand_name,
            "file_name": latest_oss_key.rsplit("/", 1)[-1],
            "oss_key": latest_oss_key,
            "oss_url": oss_url,
            "version_no": self._parse_ai_knowledge_file_sort_key(latest_oss_key)[0] or None,
            "created_at": None,
            "source": "oss",
        }

    def _build_oss_download_url(self, oss_key: str) -> str:
        oss_client = self._deps.oss_client
        if oss_client is None or not getattr(oss_client, "enabled", False):
            return ""
        if not hasattr(oss_client, "build_object_url"):
            return ""
        return str(oss_client.build_object_url(oss_key) or "").strip()

    @classmethod
    def _parse_ai_knowledge_file_sort_key(cls, object_key: str) -> tuple[int, str, str]:
        file_name = str(object_key or "").rsplit("/", 1)[-1]
        match = cls._AI_KNOWLEDGE_FILENAME_PATTERN.search(file_name)
        if not match:
            return (0, "", file_name)
        return (int(match.group("version")), match.group("date"), file_name)

    def _find_latest_ai_knowledge_markdown_oss_key(self, *, brand_name: str) -> str | None:
        oss_client = self._deps.oss_client
        if oss_client is None or not getattr(oss_client, "enabled", False):
            return None
        if not hasattr(oss_client, "list_object_keys"):
            return None
        safe_brand_name = sanitize_oss_segment(brand_name, default="uncategorized")
        prefixes = (
            f"{safe_brand_name}/ai_knowledge/",
            f"test/{safe_brand_name}/ai_knowledge/",
        )
        object_keys: list[str] = []
        for prefix in prefixes:
            object_keys.extend(
                str(key)
                for key in oss_client.list_object_keys(prefix, suffix=".md")
                if str(key).strip()
            )
        if not object_keys:
            return None
        object_keys.sort(key=self._parse_ai_knowledge_file_sort_key, reverse=True)
        return object_keys[0]

    def get_knowledge_session(self, *, session_id: str) -> dict[str, Any] | None:
        return self._brand_knowledge_application().get_knowledge_session(session_id=session_id)
