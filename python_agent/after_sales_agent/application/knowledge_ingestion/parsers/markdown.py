from __future__ import annotations

import re

from after_sales_agent.application.knowledge_ingestion.models import DocumentBlock
from after_sales_agent.application.knowledge_ingestion.section_builder import HeadingStack


_ATX_HEADING = re.compile(r"^\s{0,3}(?P<marks>#{1,6})\s+(?P<title>.*?)(?:\s+#+\s*)?$")
_SETEXT_UNDERLINE = re.compile(r"^\s*(?P<mark>=+|-+)\s*$")
_FENCE = re.compile(r"^\s*(?P<fence>`{3,}|~{3,})")
_LIST = re.compile(r"^\s*(?:[-+*]\s+|\d+[.)]\s+)")
_TABLE = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEPARATOR = re.compile(
    r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$"
)
_QUOTE = re.compile(r"^\s*>")


def parse_markdown(text: str) -> list[DocumentBlock]:
    headings = HeadingStack()
    blocks: list[DocumentBlock] = []
    block_type: str | None = None
    block_lines: list[str] = []

    def flush() -> None:
        nonlocal block_type, block_lines
        if block_type is not None and block_lines:
            blocks.append(DocumentBlock(block_type, "\n".join(block_lines), headings.path))
        block_type = None
        block_lines = []

    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        fence_match = _FENCE.match(line)
        if fence_match:
            flush()
            fence = fence_match.group("fence")
            fence_char = fence[0]
            fence_length = len(fence)
            code_lines = [line]
            index += 1
            while index < len(lines):
                code_line = lines[index]
                code_lines.append(code_line)
                index += 1
                if _is_closing_fence(code_line, fence_char, fence_length):
                    break
            blocks.append(DocumentBlock("code", "\n".join(code_lines), headings.path))
            continue

        atx_match = _ATX_HEADING.match(line)
        if atx_match:
            flush()
            headings.enter(len(atx_match.group("marks")), atx_match.group("title").strip())
            index += 1
            continue

        if index + 1 < len(lines) and line.strip():
            setext_match = _SETEXT_UNDERLINE.match(lines[index + 1])
            if setext_match:
                flush()
                headings.enter(1 if setext_match.group("mark")[0] == "=" else 2, line.strip())
                index += 2
                continue

        if not line.strip():
            flush()
            index += 1
            continue

        line_type = _markdown_line_type(line)
        if _is_table_header(lines, index) or (
            block_type == "table" and "|" in line
        ):
            line_type = "table"
        if block_type != line_type:
            flush()
            block_type = line_type
        block_lines.append(line)
        index += 1

    flush()
    return blocks


def _markdown_line_type(line: str) -> str:
    if _LIST.match(line):
        return "list"
    if _TABLE.match(line):
        return "table"
    if _QUOTE.match(line):
        return "quote"
    return "paragraph"


def _is_closing_fence(line: str, fence_char: str, minimum_length: int) -> bool:
    candidate = line.lstrip()
    length = len(candidate) - len(candidate.lstrip(fence_char))
    return (
        length >= minimum_length
        and candidate.startswith(fence_char)
        and not candidate[length:].strip()
    )


def _is_table_header(lines: list[str], index: int) -> bool:
    return index + 1 < len(lines) and "|" in lines[index] and bool(
        _TABLE_SEPARATOR.match(lines[index + 1])
    )
