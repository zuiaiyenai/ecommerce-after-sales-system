from __future__ import annotations

from collections import defaultdict
from io import BytesIO
import math
import re
import unicodedata

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from after_sales_agent.application.knowledge_ingestion.models import (
    DocumentBlock,
    KnowledgeParseError,
)
from after_sales_agent.application.knowledge_ingestion.section_builder import (
    HeadingStack,
    numbered_heading,
)


_DIGITS = re.compile(r"\d+")
_WHITESPACE = re.compile(r"\s+")
_MAX_MARGIN_LINE_LENGTH = 120


def extract_pdf_pages(content: bytes) -> list[tuple[int, str]]:
    """Extract text-layer content while preserving the stable parsing error codes."""
    try:
        reader = PdfReader(BytesIO(content))
        if reader.is_encrypted:
            raise KnowledgeParseError("PDF_ENCRYPTED")
        pages = [
            (page_number, (page.extract_text() or "").strip())
            for page_number, page in enumerate(reader.pages, start=1)
        ]
    except KnowledgeParseError:
        raise
    except (PdfReadError, OSError, ValueError) as exc:
        raise KnowledgeParseError("FILE_DECODE_FAILED") from exc
    except Exception as exc:
        raise KnowledgeParseError("FILE_DECODE_FAILED") from exc

    if not any(text for _, text in pages):
        raise KnowledgeParseError("PDF_TEXT_LAYER_MISSING")
    return pages


def parse_pdf(content: bytes) -> tuple[list[tuple[int, str]], list[DocumentBlock]]:
    """Parse text PDFs into page-local blocks with inherited numbered headings."""
    pages = _remove_stable_margins(extract_pdf_pages(content))
    headings = HeadingStack()
    blocks: list[DocumentBlock] = []

    for page_number, text in pages:
        paragraph_lines: list[str] = []

        def flush() -> None:
            nonlocal paragraph_lines
            if paragraph_lines:
                blocks.append(
                    DocumentBlock(
                        "paragraph",
                        "\n".join(paragraph_lines),
                        headings.path,
                        page_number,
                        page_number,
                    )
                )
            paragraph_lines = []

        for line in text.splitlines():
            heading = numbered_heading(line)
            if heading is not None:
                flush()
                headings.enter(*heading)
            elif line.strip():
                paragraph_lines.append(line.strip())
            else:
                flush()
        flush()

    return pages, blocks


def _remove_stable_margins(pages: list[tuple[int, str]]) -> list[tuple[int, str]]:
    if len(pages) < 3:
        return pages

    threshold = max(3, math.ceil(len(pages) * 0.6))
    candidates: dict[tuple[str, str], set[int]] = defaultdict(set)
    page_lines: list[tuple[int, list[str]]] = []

    for page_number, text in pages:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        page_lines.append((page_number, lines))
        for margin, line in _margin_lines(lines):
            normalized = _normalized_margin_line(line)
            if normalized:
                candidates[(margin, normalized)].add(page_number)

    repeated = {
        candidate
        for candidate, page_numbers in candidates.items()
        if len(page_numbers) >= threshold
    }
    if not repeated:
        return pages

    cleaned: list[tuple[int, str]] = []
    for page_number, lines in page_lines:
        margin_indexes = {
            (margin, index)
            for margin, index, _ in _margin_line_indexes(lines)
        }
        kept_lines = [
            line
            for index, line in enumerate(lines)
            if not any(
                (margin, _normalized_margin_line(line)) in repeated
                for margin, candidate_index in margin_indexes
                if candidate_index == index
            )
        ]
        cleaned.append((page_number, "\n".join(kept_lines)))
    return cleaned


def _margin_lines(lines: list[str]) -> list[tuple[str, str]]:
    return [(margin, line) for margin, _, line in _margin_line_indexes(lines)]


def _margin_line_indexes(lines: list[str]) -> list[tuple[str, int, str]]:
    margins: list[tuple[str, int, str]] = []
    for index, line in enumerate(lines[:2]):
        margins.append(("top", index, line))
    for offset, line in enumerate(reversed(lines[-2:])):
        margins.append(("bottom", len(lines) - offset - 1, line))
    return margins


def _normalized_margin_line(line: str) -> str | None:
    normalized = _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", line)).strip().casefold()
    if not normalized or len(normalized) > _MAX_MARGIN_LINE_LENGTH:
        return None
    return _DIGITS.sub("#", normalized)
