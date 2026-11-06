from __future__ import annotations

from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter


@dataclass(frozen=True)
class TextChunk:
    chunk_id: str
    chunk_index: int
    text: str


def split_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")
    if not text or not text.strip():
        return []

    separators = ["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""]
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=separators,
        keep_separator=False,
        strip_whitespace=True,
    )
    return splitter.split_text(text)


def build_chunks(text: str, document_id: str, chunk_size: int, chunk_overlap: int) -> list[TextChunk]:
    chunk_texts = split_text(text, chunk_size, chunk_overlap)
    return [
        TextChunk(chunk_id=f"{document_id}:{index}", chunk_index=index, text=chunk_text)
        for index, chunk_text in enumerate(chunk_texts)
    ]
