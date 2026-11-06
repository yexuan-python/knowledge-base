from __future__ import annotations

import argparse
import sys
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET


NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
}


@dataclass(frozen=True)
class SlideText:
    slide_name: str
    slide_number: int
    text_blocks: list[str]
    notes_blocks: list[str]
    chart_blocks: list[str]

    @property
    def combined_text(self) -> str:
        parts: list[str] = []
        if self.text_blocks:
            parts.extend(self.text_blocks)
        if self.chart_blocks:
            parts.extend(self.chart_blocks)
        if self.notes_blocks:
            parts.append("Speaker Notes:")
            parts.extend(self.notes_blocks)
        return "\n".join(part for part in parts if part.strip()).strip()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract text locally from a .pptx file without using DocMind."
    )
    parser.add_argument("file", help="Path to the .pptx file.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Directory to write output files into. Defaults to the source file directory.",
    )
    parser.add_argument(
        "--prefix",
        help="Output filename prefix. Defaults to the source filename stem.",
    )
    parser.add_argument(
        "--include-notes",
        action="store_true",
        help="Include speaker notes in the extracted output when present.",
    )
    parser.add_argument(
        "--print-text",
        action="store_true",
        help="Print extracted text to stdout after success.",
    )
    return parser


def _resolve_file(path_value: str) -> Path:
    path = Path(path_value).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"file not found: {path}")
    if not path.is_file():
        raise FileNotFoundError(f"not a file: {path}")
    if path.suffix.lower() != ".pptx":
        raise ValueError(f"expected a .pptx file, got: {path.name}")
    return path


def _slide_sort_key(name: str) -> tuple[int, str]:
    stem = Path(name).stem
    digits = "".join(ch for ch in stem if ch.isdigit())
    if digits:
        return int(digits), name
    return sys.maxsize, name


def _iter_slide_files(names: Iterable[str]) -> list[str]:
    slide_names = [
        name
        for name in names
        if name.startswith("ppt/slides/slide") and name.endswith(".xml")
    ]
    return sorted(slide_names, key=_slide_sort_key)


def _find_text_blocks(xml_bytes: bytes) -> list[str]:
    root = ET.fromstring(xml_bytes)
    blocks: list[str] = []
    seen: set[str] = set()

    for paragraph in root.findall(".//a:p", NS):
        runs: list[str] = []
        for text_node in paragraph.findall(".//a:t", NS):
            if text_node.text:
                runs.append(text_node.text)
        paragraph_text = "".join(runs).strip()
        if paragraph_text and paragraph_text not in seen:
            seen.add(paragraph_text)
            blocks.append(paragraph_text)

    return blocks


def _notes_path_for_slide(slide_name: str) -> str:
    slide_file = Path(slide_name).name
    digits = "".join(ch for ch in Path(slide_file).stem if ch.isdigit())
    return f"ppt/notesSlides/notesSlide{digits}.xml"


def _rels_path_for_slide(slide_name: str) -> str:
    slide_file = Path(slide_name).name
    return f"ppt/slides/_rels/{slide_file}.rels"


def _resolve_target(base_path: str, target: str) -> str:
    base_parts = Path(base_path).parent.parts
    target_parts = Path(target).parts
    stack = list(base_parts)
    for part in target_parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if stack:
                stack.pop()
            continue
        stack.append(part)
    return "/".join(stack)


def _extract_related_chart_text(
    archive: zipfile.ZipFile,
    names: set[str],
    slide_name: str,
) -> list[str]:
    rels_path = _rels_path_for_slide(slide_name)
    if rels_path not in names:
        return []

    rels_root = ET.fromstring(archive.read(rels_path))
    chart_targets: list[str] = []
    for rel in rels_root.findall(".//{*}Relationship"):
        rel_type = str(rel.attrib.get("Type") or "")
        target = str(rel.attrib.get("Target") or "")
        if not target:
            continue
        if rel_type.endswith("/chart") or "/chart" in rel_type:
            chart_targets.append(_resolve_target(rels_path, target))

    chart_blocks: list[str] = []
    seen: set[str] = set()
    for chart_path in chart_targets:
        if chart_path not in names:
            continue
        for block in _find_text_blocks(archive.read(chart_path)):
            if block not in seen:
                seen.add(block)
                chart_blocks.append(block)
    return chart_blocks


def _extract_pptx(path: Path, *, include_notes: bool) -> tuple[list[SlideText], dict[str, int]]:
    slides: list[SlideText] = []

    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        name_set = set(names)
        slide_names = _iter_slide_files(names)
        media_count = sum(1 for name in names if name.startswith("ppt/media/"))
        notes_count = sum(
            1
            for name in names
            if name.startswith("ppt/notesSlides/notesSlide") and name.endswith(".xml")
        )

        for slide_number, slide_name in enumerate(slide_names, start=1):
            slide_xml = archive.read(slide_name)
            text_blocks = _find_text_blocks(slide_xml)
            chart_blocks = _extract_related_chart_text(archive, name_set, slide_name)

            notes_blocks: list[str] = []
            if include_notes:
                notes_name = _notes_path_for_slide(slide_name)
                if notes_name in name_set:
                    notes_xml = archive.read(notes_name)
                    notes_blocks = _find_text_blocks(notes_xml)

            slides.append(
                SlideText(
                    slide_name=slide_name,
                    slide_number=slide_number,
                    text_blocks=text_blocks,
                    notes_blocks=notes_blocks,
                    chart_blocks=chart_blocks,
                )
            )

    stats = {
        "slide_count": len(slides),
        "notes_slide_count": notes_count,
        "media_count": media_count,
    }
    return slides, stats


def _build_markdown(slides: list[SlideText]) -> str:
    sections: list[str] = []
    for slide in slides:
        body = slide.combined_text
        if not body:
            continue
        sections.append(f"## Slide {slide.slide_number}\n\n{body}")
    return "\n\n".join(sections).strip()


def _write_outputs(
    *,
    output_dir: Path,
    prefix: str,
    markdown_text: str,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    markdown_path = output_dir / f"{prefix}.local_pptx.md"
    markdown_path.write_text(markdown_text, encoding="utf-8")
    print(f"markdown: {markdown_path}")


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        source_path = _resolve_file(args.file)
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        slides, stats = _extract_pptx(source_path, include_notes=args.include_notes)
    except zipfile.BadZipFile:
        print(f"invalid pptx or corrupted zip archive: {source_path}", file=sys.stderr)
        return 1
    except ET.ParseError as exc:
        print(f"failed to parse pptx xml: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"failed to extract pptx text: {exc}", file=sys.stderr)
        return 1

    markdown_text = _build_markdown(slides)

    slides_with_text = sum(1 for slide in slides if slide.text_blocks or slide.chart_blocks)
    slides_with_notes = sum(1 for slide in slides if slide.notes_blocks)
    character_count = len(markdown_text)

    output_dir = args.output_dir.expanduser().resolve() if args.output_dir else source_path.parent
    prefix = args.prefix or source_path.stem

    _write_outputs(
        output_dir=output_dir,
        prefix=prefix,
        markdown_text=markdown_text,
    )

    print(f"slide_count: {stats['slide_count']}")
    print(f"media_count: {stats['media_count']}")
    print(f"slides_with_text: {slides_with_text}")
    print(f"character_count: {character_count}")
    print(f"has_extractable_text: {str(bool(markdown_text.strip())).lower()}")

    if args.print_text and markdown_text:
        print("\n--- text ---\n")
        print(markdown_text)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
