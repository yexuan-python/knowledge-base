from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
BASE_DIR = Path(__file__).resolve().parent.parent


def _parse_csv_env(name: str, default: str = "") -> tuple[str, ...]:
    raw_value = os.getenv(name, default)
    return tuple(item.strip() for item in raw_value.split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    vector_store_backend: str = os.getenv("KB_VECTOR_STORE", "milvus").strip().lower()
    milvus_uri: str = os.getenv("KB_MILVUS_URI", str(BASE_DIR / "data" / "milvus.db"))
    collection_name: str = os.getenv("KB_COLLECTION_NAME", "documents")
    qdrant_url: str = os.getenv("KB_QDRANT_URL", "http://127.0.0.1:6333").strip()
    qdrant_api_key: str = os.getenv("KB_QDRANT_API_KEY", "").strip()
    qdrant_collection_name: str = os.getenv("KB_QDRANT_COLLECTION_NAME", collection_name).strip()
    qdrant_facts_collection_name: str = os.getenv(
        "KB_QDRANT_FACTS_COLLECTION_NAME",
        f"{qdrant_collection_name}_facts",
    ).strip()
    qdrant_on_disk_vectors: bool = os.getenv("KB_QDRANT_ON_DISK_VECTORS", "true").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    qdrant_timeout_seconds: float = float(os.getenv("KB_QDRANT_TIMEOUT_SECONDS", "10"))

    chunk_size: int = int(os.getenv("KB_CHUNK_SIZE", "1200"))
    chunk_overlap: int = int(os.getenv("KB_CHUNK_OVERLAP", "150"))
    default_top_k: int = int(os.getenv("KB_DEFAULT_TOP_K", "5"))
    milvus_filter_batch_size: int = int(os.getenv("KB_MILVUS_FILTER_BATCH_SIZE", "200"))
    milvus_iterator_batch_size: int = int(os.getenv("KB_MILVUS_ITERATOR_BATCH_SIZE", "100"))
    milvus_write_batch_size: int = int(os.getenv("KB_MILVUS_WRITE_BATCH_SIZE", "100"))
    vector_search_max_concurrency: int = int(
        os.getenv("KB_VECTOR_SEARCH_MAX_CONCURRENCY", os.getenv("KB_MILVUS_SEARCH_MAX_CONCURRENCY", "1"))
    )
    milvus_search_max_concurrency: int = int(os.getenv("KB_MILVUS_SEARCH_MAX_CONCURRENCY", "1"))

    log_level: str = os.getenv("KB_LOG_LEVEL", "INFO")

    log_dir: str = os.getenv("KB_LOG_DIR", str(BASE_DIR / "logs"))  
    upload_staging_dir: str = os.getenv("KB_UPLOAD_STAGING_DIR", str(BASE_DIR / "data" / "upload_staging"))
    attachment_preview_parse_max_concurrency: int = int(
        os.getenv("KB_ATTACHMENT_PREVIEW_PARSE_MAX_CONCURRENCY", "3")
    )
    embedding_max_concurrency: int = int(os.getenv("KB_EMBEDDING_MAX_CONCURRENCY", "10"))
    embedding_rate_limit_cooldown_seconds: float = float(
        os.getenv("KB_EMBEDDING_RATE_LIMIT_COOLDOWN_SECONDS", "60")
    )
    attachment_draft_ttl_seconds: int = int(
        os.getenv("KB_ATTACHMENT_DRAFT_TTL_SECONDS", str(24 * 60 * 60))
    )
    background_job_lock_timeout_seconds: int = int(
        os.getenv("KB_BACKGROUND_JOB_LOCK_TIMEOUT_SECONDS", "1800")
    )
    brand_full_knowledge_refresh_delay_seconds: int = int(
        os.getenv("KB_BRAND_FULL_KNOWLEDGE_REFRESH_DELAY_SECONDS", "300")
    )

    # DashScope 配置（API Key 必须通过环境变量提供）
    dashscope_api_key: str = os.getenv("DASHSCOPE_API_KEY", "")
    dashscope_base_http_api_url: str = (
        os.getenv("DASHSCOPE_BASE_HTTP_API_URL") or os.getenv("DASHSCOPE_HTTP_BASE_URL") or ""
    ).strip()
    text_llm_model: str = os.getenv("KB_TEXT_LLM_MODEL", "qwen-plus").strip()
    embedding_model: str = os.getenv("KB_EMBEDDING_MODEL", "qwen3-vl-embedding").strip()

    # OSS 配置
    oss_endpoint: str = os.getenv("OSS_ENDPOINT", "oss-cn-beijing.aliyuncs.com")
    oss_bucket_name: str = os.getenv("OSS_BUCKET_NAME", "")
    oss_region: str = os.getenv("OSS_REGION", "cn-beijing")
    oss_access_key_id: str = os.getenv("OSS_ACCESS_KEY_ID", "")
    oss_access_key_secret: str = os.getenv("OSS_ACCESS_KEY_SECRET", "")
    oss_download_url_expires_seconds: int = int(os.getenv("OSS_DOWNLOAD_URL_EXPIRES_SECONDS", "7776000"))

    # DocMind 配置
    docmind_enabled: bool = os.getenv("KB_DOCMIND_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
    docmind_endpoint: str = os.getenv("KB_DOCMIND_ENDPOINT", "docmind-api.cn-hangzhou.aliyuncs.com")
    docmind_access_key_id: str = (
        os.getenv("DOCMIND_ACCESS_KEY_ID")
        or os.getenv("ALIBABA_CLOUD_ACCESS_KEY_ID")
        or os.getenv("OSS_ACCESS_KEY_ID")
        or ""
    )
    docmind_access_key_secret: str = (
        os.getenv("DOCMIND_ACCESS_KEY_SECRET")
        or os.getenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET")
        or os.getenv("OSS_ACCESS_KEY_SECRET")
        or ""
    )
    docmind_timeout_seconds: int = int(os.getenv("KB_DOCMIND_TIMEOUT_SECONDS", "300"))
    docmind_poll_interval_seconds: float = float(os.getenv("KB_DOCMIND_POLL_INTERVAL_SECONDS", "3"))
    docmind_download_timeout_seconds: int = int(os.getenv("KB_DOCMIND_DOWNLOAD_TIMEOUT_SECONDS", "60"))
    docmind_llm_enhancement: bool = (
        os.getenv("KB_DOCMIND_LLM_ENHANCEMENT", "true").lower() in {"1", "true", "yes", "on"}
    )
    docmind_enhancement_mode: str = os.getenv("KB_DOCMIND_ENHANCEMENT_MODE", "VLM")
    docmind_strip_markdown_images: bool = (
        os.getenv("KB_DOCMIND_STRIP_MARKDOWN_IMAGES", "true").lower() in {"1", "true", "yes", "on"}
    )
    image_tagging_enabled: bool = os.getenv("KB_IMAGE_TAGGING_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
    image_tagging_model: str = os.getenv("KB_IMAGE_TAGGING_MODEL", "qwen-vl-max-latest")
    image_tagging_max_tags: int = int(os.getenv("KB_IMAGE_TAGGING_MAX_TAGS", "8"))

    mysql_host: str = os.getenv("MYSQL_HOST", "")
    mysql_port: int = int(os.getenv("MYSQL_PORT", 3306))
    mysql_user: str = os.getenv("MYSQL_USER", "")
    mysql_password: str = os.getenv("MYSQL_PASSWORD", "")
    mysql_database: str = os.getenv("MYSQL_DATABASE", "")
    mysql_pool_size: int = int(os.getenv("MYSQL_POOL_SIZE", "8"))
    category_latest_cache_ttl_seconds: float = float(
        os.getenv("KB_CATEGORY_LATEST_CACHE_TTL_SECONDS", "480")
    )
    brand_paths_load_cache_ttl_seconds: float = float(
        os.getenv("KB_BRAND_PATHS_LOAD_CACHE_TTL_SECONDS", "600")
    )
    brand_paths_load_cache_max_entries: int = int(
        os.getenv("KB_BRAND_PATHS_LOAD_CACHE_MAX_ENTRIES", "100")
    )
    path_index_summary_cache_max_entries: int = int(
        os.getenv("KB_PATH_INDEX_SUMMARY_CACHE_MAX_ENTRIES", "800")
    )

    # 告警配置
    business_alerts_enabled: bool = os.getenv("BUSINESS_ALERTS_ENABLED", "false").strip().lower() == "true"
    business_alert_notify_url: str = os.getenv("BUSINESS_ALERT_NOTIFY_URL", "").strip()
    business_alert_notify_key: str = os.getenv("BUSINESS_ALERT_NOTIFY_KEY", "").strip()
    business_alert_notify_secret: str = os.getenv("BUSINESS_ALERT_NOTIFY_SECRET", "").strip()
    business_alert_timeout_seconds: float = float(os.getenv("BUSINESS_ALERT_TIMEOUT_SECONDS", "5"))
    brand_completion_callback_url: str = os.getenv("BRAND_COMPLETION_CALLBACK_URL", "").strip()
    brand_completion_callback_timeout_seconds: float = float(
        os.getenv("BRAND_COMPLETION_CALLBACK_TIMEOUT_SECONDS", "5")
    )
    pdf_render_timeout_seconds: int = int(os.getenv("KB_PDF_RENDER_TIMEOUT_SECONDS", "120"))

    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "").strip()
    anthropic_base_url: str = os.getenv("ANTHROPIC_BASE_URL", "https://4sapi.org/v1/messages").strip()
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-8").strip()
    brand_patch_llm_provider: str = os.getenv("KB_BRAND_PATCH_LLM_PROVIDER", "anthropic").strip().lower()
    local_llm_base_url: str = os.getenv(
        "KB_LOCAL_LLM_BASE_URL",
        "http://192.168.1.68:9111/v1/chat/completions",
    ).strip()
    local_llm_model: str = os.getenv("KB_LOCAL_LLM_MODEL", "expert").strip()
    local_llm_api_key: str = os.getenv("KB_LOCAL_LLM_API_KEY", "").strip()
    anthropic_stream_enabled: bool = os.getenv("ANTHROPIC_STREAM_ENABLED", "true").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    anthropic_connect_timeout_seconds: float = float(os.getenv("ANTHROPIC_CONNECT_TIMEOUT_SECONDS", "10"))
    anthropic_read_timeout_seconds: float = float(os.getenv("ANTHROPIC_READ_TIMEOUT_SECONDS", "600"))
    anthropic_max_attempts: int = int(os.getenv("ANTHROPIC_MAX_ATTEMPTS", "3"))
    anthropic_retry_backoff_seconds: float = float(os.getenv("ANTHROPIC_RETRY_BACKOFF_SECONDS", "2"))
    anthropic_max_tokens: int = int(os.getenv("ANTHROPIC_MAX_TOKENS", "65536"))
    anthropic_thinking_budget_tokens: int = int(os.getenv("ANTHROPIC_THINKING_BUDGET_TOKENS", "10000"))
    brand_knowledge_min_files: int = int(os.getenv("KB_BRAND_KNOWLEDGE_MIN_FILES", "3"))
    brand_knowledge_output_prefix: str = os.getenv(
        "KB_BRAND_KNOWLEDGE_OUTPUT_PREFIX",
        "knowledge_base_outputs",
    ).strip()
    tianyancha_api_key: str = os.getenv("KB_TIANYANCHA_API_KEY", "").strip()
    tianyancha_enabled: bool = os.getenv("KB_TIANYANCHA_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
    tianyancha_mcp_url: str = os.getenv("KB_TIANYANCHA_MCP_URL", "https://mcp.tianyancha.com/v1").strip()
    tianyancha_timeout_seconds: float = float(os.getenv("KB_TIANYANCHA_TIMEOUT_SECONDS", "15"))
    cors_allow_origins: tuple[str, ...] = _parse_csv_env(
        "KB_CORS_ALLOW_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173",
    )
    cors_allow_credentials: bool = os.getenv("KB_CORS_ALLOW_CREDENTIALS", "true").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    # 上传限制
    max_upload_size_mb: int = 50
    max_merged_text_chars: int = 500_000   # 合并事实提取的最大字符数

    def ensure_directories(self) -> None:
        if "://" in self.milvus_uri:
            return
        milvus_path = Path(self.milvus_uri).expanduser()
        milvus_path.parent.mkdir(parents=True, exist_ok=True)

        Path(self.log_dir).mkdir(parents=True, exist_ok=True)
        Path(self.upload_staging_dir).mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
