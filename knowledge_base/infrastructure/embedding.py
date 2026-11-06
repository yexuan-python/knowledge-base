import io
import logging
import os
import tempfile
import threading
import shutil
import subprocess
from pathlib import Path
from time import monotonic, perf_counter

from dashscope import MultiModalEmbedding
from PIL import Image, UnidentifiedImageError

from knowledge_base.infrastructure.dashscope_runtime import configure_dashscope
from knowledge_base.infrastructure.settings import Settings

logger = logging.getLogger(__name__)


class EmbeddingRateLimitedError(RuntimeError):
    def __init__(self, retry_after_seconds: float, message: str) -> None:
        self.retry_after_seconds = max(0.0, float(retry_after_seconds))
        super().__init__(message)


class EmbeddingService:
    """DashScope multi-modal embedding wrapper for text and image retrieval."""

    IMAGE_EMBED_MAX_BYTES = 5 * 1024 * 1024
    IMAGE_EMBED_TARGET_BYTES = int(4.5 * 1024 * 1024)

    def __init__(self, settings: Settings, api_key: str | None = None):
        self._settings = settings
        configure_dashscope(self._settings)
        self.api_key = api_key or self._settings.dashscope_api_key
        if not self.api_key:
            raise ValueError("DASHSCOPE_API_KEY environment variable not set")
        self.model_name = self._settings.embedding_model
        self._dimension = 1024
        configured_concurrency = getattr(self._settings, "embedding_max_concurrency", None)
        if configured_concurrency is None:
            configured_concurrency = 10
        self._max_concurrency = max(1, int(configured_concurrency))
        self._call_semaphore = threading.BoundedSemaphore(self._max_concurrency)
        configured_cooldown_seconds = getattr(self._settings, "embedding_rate_limit_cooldown_seconds", None)
        if configured_cooldown_seconds is None:
            configured_cooldown_seconds = 60
        self._rate_limit_cooldown_seconds = max(0.0, float(configured_cooldown_seconds))
        self._state_lock = threading.Lock()
        self._cooldown_until_monotonic = 0.0

    @property
    def dimension(self) -> int:
        return self._dimension

    @staticmethod
    def _is_rate_limit_message(message: str | None) -> bool:
        normalized = str(message or "").strip().lower()
        return "rate limit" in normalized or "too many requests" in normalized

    def _cooldown_remaining_seconds(self) -> float:
        with self._state_lock:
            return max(0.0, self._cooldown_until_monotonic - monotonic())

    def _raise_rate_limited_error(self, *, message: str | None) -> None:
        with self._state_lock:
            self._cooldown_until_monotonic = max(
                self._cooldown_until_monotonic,
                monotonic() + self._rate_limit_cooldown_seconds,
            )
            retry_after_seconds = max(0.0, self._cooldown_until_monotonic - monotonic())
        logger.warning(
            "Embedding provider rate limited; cooldown_seconds=%.2f retry_after_seconds=%.2f message=%s",
            self._rate_limit_cooldown_seconds,
            retry_after_seconds,
            message,
        )
        raise EmbeddingRateLimitedError(
            retry_after_seconds,
            f"Embedding API rate limited: {message or 'unknown error'}",
        )

    def _call_embedding_api(self, payload: list[dict[str, str]]) -> object:
        remaining = self._cooldown_remaining_seconds()
        if remaining > 0:
            raise EmbeddingRateLimitedError(remaining, "Embedding API cooling down")

        with self._call_semaphore:
            remaining = self._cooldown_remaining_seconds()
            if remaining > 0:
                raise EmbeddingRateLimitedError(remaining, "Embedding API cooling down")
            try:
                response = MultiModalEmbedding.call(
                    model=self.model_name,
                    input=payload,
                    api_key=self.api_key,
                    dimension=self._dimension,
                )
            except Exception as exc:
                if self._is_rate_limit_message(str(exc)):
                    self._raise_rate_limited_error(message=str(exc))
                raise

            if self._is_rate_limit_message(getattr(response, "message", None)):
                self._raise_rate_limited_error(message=getattr(response, "message", None))
            return response

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """批量处理文本"""
        batch_size = 20
        all_embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i+batch_size]
            inputs = [{"text": t} for t in batch]

            try:
                resp = self._call_embedding_api(inputs)
                if resp.status_code != 200:
                    raise Exception(f"Embedding API error: {resp.message}")
                
                embeddings = [item["embedding"] for item in resp.output["embeddings"]]

                all_embeddings.extend(embeddings)
                
            except Exception:
                logger.exception("Embedding text batch failed batch_size=%s", len(texts))
                raise

        return all_embeddings

    def embed_query(self, text: str) -> list[float]:
        """查询文本向量化"""
        return self.embed_documents([text])[0]
    
    @staticmethod
    def _compress_image(image_path: str, max_bytes: int) -> bytes:
        """压缩图片至指定字节大小，返回图片字节数据"""
        with Image.open(image_path) as img:
            # 转换为 RGB（去除透明通道）
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')

            current = img.copy()
            last_output = None

            while True:
                for quality in (85, 75, 65, 55, 45, 35, 25):
                    output = io.BytesIO()
                    current.save(output, format='JPEG', quality=quality, optimize=True)
                    data = output.getvalue()
                    if len(data) <= max_bytes:
                        return data
                    last_output = data

                # 质量压缩仍不够时，继续缩小尺寸并重试
                if current.width <= 512 or current.height <= 512:
                    return last_output or b""

                new_size = (
                    max(int(current.width * 0.85), 512),
                    max(int(current.height * 0.85), 512),
                )
                current = current.resize(new_size, Image.Resampling.LANCZOS)

    @staticmethod
    def _detect_mime_type(image_path: str) -> str | None:
        """Use the local `file` command to sniff the real image type."""
        file_cmd = shutil.which("file")
        if not file_cmd:
            return None

        try:
            result = subprocess.run(
                [file_cmd, "--mime-type", "-b", image_path],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return None

        if result.returncode != 0:
            return None
        return str(result.stdout or "").strip().lower() or None

    @classmethod
    def _normalize_image_path(
        cls,
        image_path: str,
        *,
        purpose: str,
    ) -> tuple[str, str | None]:
        """Convert HEIC/HEIF images to a temporary JPEG when needed."""
        path = Path(image_path)
        detected_mime_type = cls._detect_mime_type(image_path)
        suffix = path.suffix.lower()
        is_heic_like = detected_mime_type in {"image/heic", "image/heif"} or suffix in {".heic", ".heif"}
        if not is_heic_like:
            try:
                with Image.open(image_path):
                    return image_path, None
            except (UnidentifiedImageError, OSError):
                raise ValueError(
                    f"图片无法被当前环境读取: {path.name}。"
                    "如果这是 HEIC/HEIF，请先转换成 JPG/PNG，或确保系统支持该格式。"
                )

        sips_cmd = shutil.which("sips")
        if not sips_cmd:
            raise ValueError(
                f"图片 {path.name} 是 HEIC/HEIF 格式，但当前环境没有 `sips`，"
                f"无法自动转换用于 {purpose}"
            )

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            result = subprocess.run(
                [sips_cmd, "-s", "format", "jpeg", image_path, "--out", tmp_path],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                stderr = str(result.stderr or "").strip()
                stdout = str(result.stdout or "").strip()
                details = stderr or stdout or "unknown error"
                raise ValueError(
                    f"HEIC/HEIF 转换失败，无法继续 {purpose}: {path.name}，原因: {details}"
                )
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

        return tmp_path, tmp_path

    @classmethod
    def prepare_image_path_for_limit(
        cls,
        image_path: str,
        *,
        max_bytes: int,
        target_bytes: int,
        purpose: str,
    ) -> tuple[str, str | None]:
        """Prepare a local image path that satisfies the given size limit."""
        normalized_path, cleanup_path = cls._normalize_image_path(image_path, purpose=purpose)

        file_size = os.path.getsize(image_path)
        if normalized_path != image_path:
            file_size = os.path.getsize(normalized_path)

        if file_size <= max_bytes:
            return normalized_path, cleanup_path

        img_bytes = cls._compress_image(
            normalized_path,
            max_bytes=target_bytes,
        )
        if not img_bytes:
            if cleanup_path and os.path.exists(normalized_path):
                os.unlink(normalized_path)
            raise ValueError(f"Image compression produced empty output for {purpose}")

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp.write(img_bytes)
            tmp_path = tmp.name

        final_size = os.path.getsize(tmp_path)
        if final_size > max_bytes:
            os.unlink(tmp_path)
            if cleanup_path and os.path.exists(normalized_path):
                os.unlink(normalized_path)
            raise ValueError(
                f"Compressed image is still too large for {purpose}: {final_size} bytes > {max_bytes} bytes"
            )

        if cleanup_path and os.path.exists(normalized_path):
            os.unlink(normalized_path)

        logger.info(
            "Compressed image for %s original=%s original_size=%s compressed_size=%s",
            purpose,
            Path(image_path).name,
            file_size,
            final_size,
        )
        return tmp_path, tmp_path

    def _prepare_image_input(self, image_path: str) -> tuple[str, str | None]:
        """Prepare a local image path that satisfies the embedding model size limit."""
        return self.prepare_image_path_for_limit(
            image_path,
            max_bytes=self.IMAGE_EMBED_MAX_BYTES,
            target_bytes=self.IMAGE_EMBED_TARGET_BYTES,
            purpose="image embedding",
        )

    def embed_image(self, image_path: str) -> list[float]:
        """
        将图片编码为向量
        image_path: 本地图片路径或网络URL
        """
        
        tmp_path = None
        started_at = perf_counter()

        try:
            input_path, tmp_path = self._prepare_image_input(image_path)

            resp = self._call_embedding_api([{"image": input_path}])

            if resp.status_code == 200:
                return resp.output["embeddings"][0]["embedding"]

            duration_ms = (perf_counter() - started_at) * 1000
            logger.error(
                "Embedding image returned error image_path=%s status_code=%s duration_ms=%.2f message=%s",
                image_path,
                resp.status_code,
                duration_ms,
                resp.message,
            )
            raise Exception(f"Image Embedding Error: {resp.message}")
        except Exception:
            logger.exception("Embedding image failed image_path=%s", image_path)
            raise
        finally:
            # 4. 清理临时文件
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
   
    def embed_image_with_text(self, image_path: str, text: str) -> list[float]:
        """
        将图片和文本联合编码为向量
        :param image_path: 本地图片路径或 URL
        :param text: 图片的描述文本（如“红苹果”）
        """
        started_at = perf_counter()
        tmp_path = None
        try:
            input_path, tmp_path = self._prepare_image_input(image_path)
            resp = self._call_embedding_api([{"image": input_path, "text": text}])
        except Exception:
            logger.exception("Embedding image+text failed image_path=%s", image_path)
            raise
        try:
            if resp.status_code == 200:
                return resp.output["embeddings"][0]["embedding"]
            duration_ms = (perf_counter() - started_at) * 1000
            logger.error(
                "Embedding image+text returned error image_path=%s status_code=%s duration_ms=%.2f message=%s",
                image_path,
                resp.status_code,
                duration_ms,
                resp.message,
            )
            raise Exception(f"Image+Text Embedding Error: {resp.message}")
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
