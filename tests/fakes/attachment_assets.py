from __future__ import annotations

import tempfile
import types
from pathlib import Path


class FakeBrandAttachmentAssetStore:
    def __init__(self) -> None:
        self.rows = [
            {
                "id": 1,
                "brand_code": "BRAND-001",
                "brand_name": "示例品牌",
                "original_filename": "保留附件.docx",
                "source_url": "https://example.com/keep.docx",
                "oss_key": "示例品牌/original/保留附件.docx/V1.docx",
                "fulltext_key": "示例品牌/converted/保留附件.docx/V1.md",
                "file_hash": "keep-hash",
                "converted_version": 1,
            },
            {
                "id": 2,
                "brand_code": "BRAND-001",
                "brand_name": "示例品牌",
                "original_filename": "删除附件.docx",
                "source_url": "https://example.com/remove.docx",
                "oss_key": "示例品牌/original/删除附件.docx/V1.docx",
                "fulltext_key": "示例品牌/converted/删除附件.docx/V1.md",
                "file_hash": "remove-hash",
                "converted_version": 1,
            },
        ]
        self.created_assets: list[dict[str, object]] = []
        self.deleted_ids: list[int] = []

    def get_by_brand_code_and_file_hash(self, *, brand_code: str, file_hash: str):
        for row in self.rows:
            if row.get("brand_code") == brand_code and row.get("file_hash") == file_hash:
                return dict(row)
        return None

    def get_next_converted_version(self, *, brand_code: str, original_filename: str) -> int:
        versions = [
            int(row.get("converted_version") or 0)
            for row in self.rows
            if row.get("brand_code") == brand_code and row.get("original_filename") == original_filename
        ]
        return (max(versions) if versions else 0) + 1

    def create_asset(self, **kwargs):
        self.created_assets.append(dict(kwargs))
        new_id = len(self.rows) + 1
        row = {"id": new_id, **kwargs}
        self.rows.append(row)
        return new_id

    def get_by_brand_code_and_attachment(self, *, brand_code: str, original_filename: str, source_url: str | None = None):
        for row in reversed(self.rows):
            if row.get("brand_code") != brand_code:
                continue
            if row.get("original_filename") != original_filename:
                continue
            if source_url is not None and row.get("source_url") != source_url:
                continue
            return dict(row)
        return None

    def delete_by_id(self, *, asset_id: int) -> int:
        self.deleted_ids.append(asset_id)
        before = len(self.rows)
        self.rows = [row for row in self.rows if int(row.get("id") or 0) != asset_id]
        return before - len(self.rows)


class FakeAttachmentOSSClient:
    enabled = True

    def __init__(self) -> None:
        self.uploaded_objects: list[tuple[str, bytes, str]] = []
        self.deleted_keys: list[str] = []

    def upload_bytes(self, data: bytes, object_key: str, content_type: str):
        self.uploaded_objects.append((object_key, data, content_type))
        return object_key

    def upload_file(self, file_path: str, object_key: str, content_type: str = "application/octet-stream"):
        self.uploaded_objects.append((object_key, Path(file_path).read_bytes(), content_type))
        return object_key

    def build_object_url(self, object_key: str) -> str:
        return f"https://oss.example.com/{object_key}"

    def delete_object(self, object_key: str) -> bool:
        self.deleted_keys.append(object_key)
        return True


class FakeAttachmentParser:
    def parse_path(self, path, source_name=None, *, source_url=None):
        return types.SimpleNamespace(
            markdown_text=f"# {source_name}\n来源：{source_url}",
            text=f"# {source_name}\n来源：{source_url}",
            source_type=Path(str(source_name or "")).suffix.lstrip(".") or "text",
        )


async def fake_temp_file_download(*, payloads):
    created_paths: list[Path] = []

    async def _download(*, url: str, name: str, log_context: str):
        del url, log_context
        data, content_type = payloads.pop(0)
        suffix = Path(name).suffix or ".tmp"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(data)
            temp_path = Path(tmp.name)
        created_paths.append(temp_path)
        return temp_path, content_type, len(data)

    return _download, created_paths
