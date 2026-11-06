from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


AI_KNOWLEDGE_FILENAME_RE = re.compile(
    r"^[【「](?P<brand_name>.+?)[】」]品牌AI知识库_V(?P<version_no>\d+)_(?P<knowledge_date>\d{8})\.(?P<ext>[^.]+)$"
)


@dataclass(frozen=True)
class ParsedAiKnowledgeFilename:
    brand_name: str
    version_no: int
    knowledge_date: str
    extension: str
    original_filename: str

    @property
    def normalized_extension(self) -> str:
        return self.extension.lower()

    @property
    def suffix(self) -> str:
        return f".{self.extension}"


def parse_ai_knowledge_filename(filename: str) -> ParsedAiKnowledgeFilename | None:
    normalized_filename = Path(str(filename or "").strip()).name
    if not normalized_filename:
        return None

    match = AI_KNOWLEDGE_FILENAME_RE.match(normalized_filename)
    if match is None:
        return None

    return ParsedAiKnowledgeFilename(
        brand_name=match.group("brand_name").strip(),
        version_no=int(match.group("version_no")),
        knowledge_date=match.group("knowledge_date"),
        extension=match.group("ext").strip(),
        original_filename=normalized_filename,
    )


def is_ai_knowledge_filename(filename: str) -> bool:
    return parse_ai_knowledge_filename(filename) is not None
