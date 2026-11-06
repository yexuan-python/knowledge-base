from .docmind_client import DocMindClient, DocMindError, DocMindParseResult
from .document_parser import (
    DocumentParser,
    NoTextExtractedError,
    ParsedDocument,
    UnsupportedFileTypeError,
    WatermarkedDocumentError,
)
from .pdf_watermark import (
    PdfWatermarkCandidate,
    PdfWatermarkReport,
    WatermarkResidueReport,
    _is_single_page_repeated_watermark,
    analyze_pdf_watermark_phrases,
    detect_markdown_watermark_residue,
    detect_pdf_watermark_suspect,
    remove_markdown_watermark_residue,
)

try:
    from .chunking import TextChunk, build_chunks, split_text
except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency guard
    _chunking_import_error = exc

    def _raise_chunking_import_error(*_args, **_kwargs):
        raise ModuleNotFoundError(
            "knowledge_base.ingest.infrastructure.chunking requires 'langchain_text_splitters'"
        ) from _chunking_import_error

    TextChunk = None  # type: ignore[assignment]
    build_chunks = _raise_chunking_import_error  # type: ignore[assignment]
    split_text = _raise_chunking_import_error  # type: ignore[assignment]

__all__ = [
    "_is_single_page_repeated_watermark",
    "analyze_pdf_watermark_phrases",
    "build_chunks",
    "detect_markdown_watermark_residue",
    "detect_pdf_watermark_suspect",
    "remove_markdown_watermark_residue",
    "DocMindClient",
    "DocMindError",
    "DocMindParseResult",
    "DocumentParser",
    "NoTextExtractedError",
    "ParsedDocument",
    "PdfWatermarkCandidate",
    "PdfWatermarkReport",
    "split_text",
    "TextChunk",
    "UnsupportedFileTypeError",
    "WatermarkResidueReport",
    "WatermarkedDocumentError",
]
