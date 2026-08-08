from __future__ import annotations

from collections import defaultdict
from io import BytesIO
import math
import re
from typing import Any
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
        pages: list[tuple[int, str]] = []
        for page_number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            if not text.strip() and _page_has_non_text_content(page):
                raise KnowledgeParseError("PDF_TEXT_LAYER_MISSING")
            pages.append((page_number, text))
    except KnowledgeParseError:
        raise
    except (PdfReadError, OSError, ValueError) as exc:
        raise KnowledgeParseError("FILE_DECODE_FAILED") from exc
    except Exception as exc:
        raise KnowledgeParseError("FILE_DECODE_FAILED") from exc

    if not any(text.strip() for _, text in pages):
        raise KnowledgeParseError("PDF_TEXT_LAYER_MISSING")
    return pages


def _page_has_non_text_content(page: Any) -> bool:
    contents = page.get_contents()
    if contents is not None and contents.get_data().strip():
        return True

    resources = page.get("/Resources")
    if resources is None:
        return False
    resources = resources.get_object() if hasattr(resources, "get_object") else resources
    xobjects = resources.get("/XObject") if hasattr(resources, "get") else None
    if xobjects is None:
        return False
    xobjects = xobjects.get_object() if hasattr(xobjects, "get_object") else xobjects
    for candidate in xobjects.values() if hasattr(xobjects, "values") else ():
        candidate = candidate.get_object() if hasattr(candidate, "get_object") else candidate
        if hasattr(candidate, "get") and str(candidate.get("/Subtype")) == "/Image":
            return True
    return False


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
        lines = text.splitlines()
        page_lines.append((page_number, lines))
        for margin, _, line in _margin_line_indexes(lines):
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
        removable_indexes = {
            index
            for margin, index, line in _margin_line_indexes(lines)
            if (margin, _normalized_margin_line(line)) in repeated
        }
        kept_lines = [line for index, line in enumerate(lines) if index not in removable_indexes]
        cleaned.append((page_number, "\n".join(kept_lines)))
    return cleaned


def _margin_line_indexes(lines: list[str]) -> list[tuple[str, int, str]]:
    margins: list[tuple[str, int, str]] = []
    top_indexes = [index for index, line in enumerate(lines) if line.strip()][:2]
    for index in top_indexes:
        line = lines[index]
        margins.append(("top", index, line))
    bottom_indexes = [index for index in range(len(lines) - 1, -1, -1) if lines[index].strip()][:2]
    for index in bottom_indexes:
        margins.append(("bottom", index, lines[index]))
    return margins


def _normalized_margin_line(line: str) -> str | None:
    normalized = _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", line)).strip().casefold()
    if not normalized or len(normalized) > _MAX_MARGIN_LINE_LENGTH:
        return None
    return _DIGITS.sub("#", normalized)
