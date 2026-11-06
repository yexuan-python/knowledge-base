from __future__ import annotations

import logging
from time import monotonic
from typing import Any


logger = logging.getLogger(__name__)


class BrandPathCachingMixin:
    def _clear_brand_path_caches(self) -> None:
        with self._brand_paths_load_cache_lock:
            self._brand_paths_load_cache.clear()
            self._brand_paths_load_cache_last_cleanup_at = monotonic()
            self._brand_paths_load_cache_last_stats_log_at = monotonic()
        with self._path_index_summary_cache_lock:
            self._path_index_summary_cache.clear()
            self._path_index_summary_cache_last_cleanup_at = monotonic()

    def _brand_path_asset_cache_key(
        self,
        *,
        brand_code: str,
        knowledge_revision: str,
        path: str,
    ) -> tuple[str, str, str]:
        return (
            str(brand_code or "").strip(),
            str(knowledge_revision or "").strip(),
            str(path or "").strip(),
        )

    @staticmethod
    def _copy_cached_brand_path_asset(asset: dict[str, Any]) -> dict[str, Any]:
        return dict(asset)

    def _get_cached_brand_path_asset(
        self,
        *,
        brand_code: str,
        knowledge_revision: str,
        path: str,
    ) -> dict[str, Any] | None:
        if self._brand_paths_load_cache_ttl_seconds <= 0 or self._brand_paths_load_cache_max_entries <= 0:
            return None
        cache_key = self._brand_path_asset_cache_key(
            brand_code=brand_code,
            knowledge_revision=knowledge_revision,
            path=path,
        )
        now = monotonic()
        with self._brand_paths_load_cache_lock:
            self._cleanup_expired_brand_path_assets_locked(now)
            self._maybe_log_brand_path_cache_stats_locked(now)
            cached = self._brand_paths_load_cache.get(cache_key)
            if cached is None:
                logger.debug(
                    "Brand paths-load cache miss brand_code=%s knowledge_revision=%s path=%s",
                    brand_code,
                    knowledge_revision,
                    path,
                )
                return None
            expires_at, _last_access_at, asset = cached
            if expires_at <= now:
                self._brand_paths_load_cache.pop(cache_key, None)
                logger.debug(
                    "Brand paths-load cache expired brand_code=%s knowledge_revision=%s path=%s",
                    brand_code,
                    knowledge_revision,
                    path,
                )
                return None
            logger.debug(
                "Brand paths-load cache hit brand_code=%s knowledge_revision=%s path=%s",
                brand_code,
                knowledge_revision,
                path,
            )
            self._brand_paths_load_cache[cache_key] = (expires_at, now, asset)
            return self._copy_cached_brand_path_asset(asset)

    def _cache_brand_path_asset(
        self,
        *,
        brand_code: str,
        knowledge_revision: str,
        path: str,
        asset: dict[str, Any],
    ) -> None:
        if self._brand_paths_load_cache_ttl_seconds <= 0 or self._brand_paths_load_cache_max_entries <= 0:
            return
        normalized_cache_key = self._brand_path_asset_cache_key(
            brand_code=brand_code,
            knowledge_revision=knowledge_revision,
            path=path,
        )
        now = monotonic()
        expires_at = now + self._brand_paths_load_cache_ttl_seconds
        with self._brand_paths_load_cache_lock:
            self._cleanup_expired_brand_path_assets_locked(now)
            self._brand_paths_load_cache[normalized_cache_key] = (
                expires_at,
                now,
                self._copy_cached_brand_path_asset(asset),
            )
            self._evict_brand_path_assets_if_needed_locked()
            self._maybe_log_brand_path_cache_stats_locked(now)
        logger.debug(
            "Brand paths-load cache store brand_code=%s knowledge_revision=%s path=%s ttl_seconds=%.1f",
            brand_code,
            knowledge_revision,
            path,
            self._brand_paths_load_cache_ttl_seconds,
        )

    def _cleanup_expired_brand_path_assets_locked(self, now: float) -> None:
        if self._brand_paths_load_cache_cleanup_interval_seconds <= 0:
            return
        if now - self._brand_paths_load_cache_last_cleanup_at < self._brand_paths_load_cache_cleanup_interval_seconds:
            return
        expired_keys = [
            cache_key
            for cache_key, (expires_at, _last_access_at, _asset) in self._brand_paths_load_cache.items()
            if expires_at <= now
        ]
        for cache_key in expired_keys:
            self._brand_paths_load_cache.pop(cache_key, None)
        self._brand_paths_load_cache_last_cleanup_at = now
        if expired_keys:
            logger.debug(
                "Brand paths-load cache cleanup removed=%s remaining=%s",
                len(expired_keys),
                len(self._brand_paths_load_cache),
            )

    def _evict_brand_path_assets_if_needed_locked(self) -> None:
        overflow = len(self._brand_paths_load_cache) - self._brand_paths_load_cache_max_entries
        if overflow <= 0:
            return
        eviction_keys = sorted(
            self._brand_paths_load_cache.items(),
            key=lambda item: item[1][1],
        )[:overflow]
        for cache_key, _value in eviction_keys:
            self._brand_paths_load_cache.pop(cache_key, None)
        logger.debug(
            "Brand paths-load cache eviction removed=%s remaining=%s max_entries=%s",
            overflow,
            len(self._brand_paths_load_cache),
            self._brand_paths_load_cache_max_entries,
        )

    def _maybe_log_brand_path_cache_stats_locked(self, now: float) -> None:
        if self._brand_paths_load_cache_stats_log_interval_seconds <= 0:
            return
        if now - self._brand_paths_load_cache_last_stats_log_at < self._brand_paths_load_cache_stats_log_interval_seconds:
            return
        self._brand_paths_load_cache_last_stats_log_at = now
        logger.debug(
            "Brand paths-load cache stats entries=%s max_entries=%s ttl_seconds=%.1f cleanup_interval_seconds=%.1f",
            len(self._brand_paths_load_cache),
            self._brand_paths_load_cache_max_entries,
            self._brand_paths_load_cache_ttl_seconds,
            self._brand_paths_load_cache_cleanup_interval_seconds,
        )

    def _path_index_summary_cache_key(
        self,
        *,
        brand_code: str,
        knowledge_revision: str,
        path: str,
    ) -> tuple[str, str, str]:
        return (
            str(brand_code or "").strip(),
            str(knowledge_revision or "").strip(),
            str(path or "").strip(),
        )

    def _get_cached_path_index_summary(
        self,
        *,
        brand_code: str,
        knowledge_revision: str,
        path: str,
    ) -> str | None:
        if self._path_index_summary_cache_ttl_seconds <= 0 or self._path_index_summary_cache_max_entries <= 0:
            return None
        cache_key = self._path_index_summary_cache_key(
            brand_code=brand_code,
            knowledge_revision=knowledge_revision,
            path=path,
        )
        now = monotonic()
        with self._path_index_summary_cache_lock:
            self._cleanup_expired_path_index_summaries_locked(now)
            cached = self._path_index_summary_cache.get(cache_key)
            if cached is None:
                return None
            expires_at, _last_access_at, summary = cached
            if expires_at <= now:
                self._path_index_summary_cache.pop(cache_key, None)
                return None
            self._path_index_summary_cache[cache_key] = (expires_at, now, summary)
            return str(summary or "").strip() or None

    def _cache_path_index_summary(
        self,
        *,
        brand_code: str,
        knowledge_revision: str,
        path: str,
        summary: str,
    ) -> None:
        if self._path_index_summary_cache_ttl_seconds <= 0 or self._path_index_summary_cache_max_entries <= 0:
            return
        normalized_summary = str(summary or "").strip()
        if not normalized_summary:
            return
        cache_key = self._path_index_summary_cache_key(
            brand_code=brand_code,
            knowledge_revision=knowledge_revision,
            path=path,
        )
        now = monotonic()
        expires_at = now + self._path_index_summary_cache_ttl_seconds
        with self._path_index_summary_cache_lock:
            self._cleanup_expired_path_index_summaries_locked(now)
            self._path_index_summary_cache[cache_key] = (expires_at, now, normalized_summary)
            self._evict_path_index_summaries_if_needed_locked()

    def _cleanup_expired_path_index_summaries_locked(self, now: float) -> None:
        if self._path_index_summary_cache_cleanup_interval_seconds <= 0:
            return
        if now - self._path_index_summary_cache_last_cleanup_at < self._path_index_summary_cache_cleanup_interval_seconds:
            return
        expired_keys = [
            cache_key
            for cache_key, (expires_at, _last_access_at, _summary) in self._path_index_summary_cache.items()
            if expires_at <= now
        ]
        for cache_key in expired_keys:
            self._path_index_summary_cache.pop(cache_key, None)
        self._path_index_summary_cache_last_cleanup_at = now

    def _evict_path_index_summaries_if_needed_locked(self) -> None:
        overflow = len(self._path_index_summary_cache) - self._path_index_summary_cache_max_entries
        if overflow <= 0:
            return
        eviction_keys = sorted(
            self._path_index_summary_cache.items(),
            key=lambda item: item[1][1],
        )[:overflow]
        for cache_key, _value in eviction_keys:
            self._path_index_summary_cache.pop(cache_key, None)

    @classmethod
    def _prepare_path_index_summary_content(cls, content: str) -> str:
        normalized_content = str(content or "").strip()
        if not normalized_content:
            return ""
        return normalized_content[: cls.PATH_INDEX_SUMMARY_MAX_CONTENT_CHARS]
