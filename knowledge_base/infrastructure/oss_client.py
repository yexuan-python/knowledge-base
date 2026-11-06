import logging
import tempfile
import time
from typing import Any, Callable, Optional
from urllib.parse import quote
from pathlib import Path

import oss2

from knowledge_base.infrastructure.settings import Settings

logger = logging.getLogger(__name__)


class OSSClient:
    _UPLOAD_RETRY_DELAYS_SECONDS = (1, 2, 4)

    def __init__(self, settings: Settings):
        self._settings = settings
        self.bucket_name = self._settings.oss_bucket_name
        self.endpoint = self._settings.oss_endpoint
        self.region = self._settings.oss_region
        self.access_key_id = self._settings.oss_access_key_id
        self.access_key_secret = self._settings.oss_access_key_secret

        # 如果缺少必要配置，禁用 OSS 并记录警告
        if not self.bucket_name or not self.access_key_id or not self.access_key_secret:
            logger.warning("OSS credentials missing, OSS functionality disabled")
            self.enabled = False
            return
        
        # 初始化bucket对象
        self.bucket = oss2.Bucket(oss2.Auth(self.access_key_id, self.access_key_secret), self.endpoint, self.bucket_name)
        self.enabled = True

    def _upload_with_retry(
        self,
        *,
        operation_name: str,
        object_key: str,
        attempt_upload: Callable[[], None],
        success_log_message: str,
        success_log_args: tuple[Any, ...],
    ) -> Optional[str]:
        last_error: Exception | None = None
        total_attempts = len(self._UPLOAD_RETRY_DELAYS_SECONDS)
        for attempt_no, delay_seconds in enumerate(self._UPLOAD_RETRY_DELAYS_SECONDS, start=1):
            try:
                attempt_upload()
                logger.info(success_log_message, *success_log_args)
                return object_key
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning(
                    "OSS %s failed object_key=%s attempt=%s/%s error_type=%s error=%s",
                    operation_name,
                    object_key,
                    attempt_no,
                    total_attempts,
                    type(exc).__name__,
                    exc,
                    exc_info=True,
                )
                if attempt_no >= total_attempts:
                    break
                logger.info(
                    "Retrying OSS %s object_key=%s in %ss (attempt %s/%s)",
                    operation_name,
                    object_key,
                    delay_seconds,
                    attempt_no + 1,
                    total_attempts,
                )
                time.sleep(delay_seconds)
        logger.error(
            "OSS %s failed after %s attempts object_key=%s error=%s",
            operation_name,
            total_attempts,
            object_key,
            last_error,
        )
        return None

    def build_object_url(self, object_key: str) -> Optional[str]:
        """根据 object_key 构造可访问的 OSS 下载 URL"""
        if not self.enabled or not object_key:
            return None
        expires_seconds = max(1, int(getattr(self._settings, "oss_download_url_expires_seconds", 604800) or 604800))
        try:
            return self.bucket.sign_url("GET", object_key, expires_seconds, slash_safe=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "OSS sign_url failed object_key=%s expires_seconds=%s error_type=%s error=%s",
                object_key,
                expires_seconds,
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            encoded_key = quote(object_key, safe="/-_.~")
            return f"https://{self.bucket_name}.{self.endpoint}/{encoded_key}"
       
    def upload_bytes(self, data: bytes, object_key: str, content_type: str = "application/octet-stream") -> Optional[str]:
        """上传字节数据到OSS"""
        if not self.enabled:
            return None

        headers = {'Content-Type': content_type}
        return self._upload_with_retry(
            operation_name="upload_bytes",
            object_key=object_key,
            attempt_upload=lambda: self.bucket.put_object(object_key, data, headers=headers),
            success_log_message="Bytes uploaded to OSS: %s, size=%d",
            success_log_args=(object_key, len(data)),
        )

    def upload_file(
        self,
        file_path: str,
        object_key: str,
        content_type: str = "application/octet-stream",
    ) -> Optional[str]:
        """上传本地文件到OSS"""
        if not self.enabled:
            return None
        headers = {'Content-Type': content_type}
        return self._upload_with_retry(
            operation_name="upload_file",
            object_key=object_key,
            attempt_upload=lambda: self.bucket.put_object_from_file(object_key, file_path, headers=headers),
            success_log_message="Uploaded to OSS: %s -> %s",
            success_log_args=(file_path, object_key),
        )

    def get_object(self, object_key: str) -> Optional[bytes]:
        """从OSS获取对象内容（字节）"""
        if not self.enabled:
            return None
        try:
            # oss2的get_object返回一个类文件对象
            result = self.bucket.get_object(object_key)
            # 通过.read()方法读取内容
            return result.read()
        except oss2.exceptions.NoSuchKey:
            logger.warning("Object not found in OSS: %s", object_key)
            return None
        except Exception as e:
            logger.error("Failed to get object from OSS: %s", e)
            return None

    def download_object_to_temp_file(
        self,
        object_key: str,
        *,
        suffix: str = ".tmp",
    ) -> Optional[Path]:
        """将 OSS 对象分块下载到本地临时文件，避免一次性读入内存。"""
        if not self.enabled:
            return None

        temp_path: Path | None = None
        result = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix or ".tmp") as tmp:
                temp_path = Path(tmp.name)
            result = self.bucket.get_object(object_key)
            with temp_path.open("wb") as output_file:
                while True:
                    chunk = result.read(1024 * 1024)
                    if not chunk:
                        break
                    output_file.write(chunk)
            return temp_path
        except oss2.exceptions.NoSuchKey:
            logger.warning("Object not found in OSS: %s", object_key)
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            return None
        except Exception as e:
            logger.error("Failed to download object from OSS to temp file: %s", e)
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            return None
        finally:
            close = getattr(result, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

    def get_object_text(self, object_key: str, encoding: str = "utf-8") -> Optional[str]:
        """从OSS获取文本对象内容"""
        data = self.get_object(object_key)
        if data is None:
            return None
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            logger.warning("Failed to decode OSS object with encoding=%s object_key=%s", encoding, object_key)
            return None

    def list_object_keys(self, prefix: str, *, suffix: str | None = None, max_keys: int = 1000) -> list[str]:
        """列出指定前缀下的对象 key"""
        if not self.enabled:
            return []
        normalized_prefix = str(prefix or "").strip()
        if not normalized_prefix:
            return []

        object_keys: list[str] = []
        marker = ""
        try:
            while True:
                result = self.bucket.list_objects(prefix=normalized_prefix, marker=marker, max_keys=max_keys)
                object_list = getattr(result, "object_list", None) or []
                for item in object_list:
                    object_key = str(getattr(item, "key", "") or "").strip()
                    if not object_key:
                        continue
                    if suffix and not object_key.endswith(suffix):
                        continue
                    object_keys.append(object_key)
                if not getattr(result, "is_truncated", False):
                    break
                next_marker = str(getattr(result, "next_marker", "") or "").strip()
                if not next_marker or next_marker == marker:
                    break
                marker = next_marker
        except Exception as e:
            logger.error("Failed to list OSS objects for prefix %s: %s", normalized_prefix, e)
            return []
        return object_keys

    def prefix_exists(self, prefix: str) -> bool:
        """判断给定前缀下是否已有对象"""
        if not self.enabled:
            return False
        try:
            result = self.bucket.list_objects(prefix=prefix, max_keys=1)
            return bool(getattr(result, "object_list", None))
        except Exception as e:
            logger.error("Failed to list OSS objects for prefix %s: %s", prefix, e)
            return False

    def delete_object(self, object_key: str) -> bool:
        """从OSS删除对象"""
        if not self.enabled:
            return False
        try:
            self.bucket.delete_object(object_key)
            logger.info("Deleted from OSS: %s", object_key)
            return True
        except Exception as e:
            logger.error("Failed to delete from OSS: %s", e)
            return False
