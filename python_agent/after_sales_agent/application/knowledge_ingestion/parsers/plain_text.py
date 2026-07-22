from __future__ import annotations

from after_sales_agent.application.knowledge_ingestion.models import DocumentBlock
from after_sales_agent.application.knowledge_ingestion.section_builder import (
    HeadingStack,
    numbered_heading,
)


def parse_plain_text(text: str) -> list[DocumentBlock]:
    headings = HeadingStack()
    blocks: list[DocumentBlock] = []
    paragraph_lines: list[str] = []

    def flush() -> None:
        nonlocal paragraph_lines
        if paragraph_lines:
            blocks.append(DocumentBlock("paragraph", "\n".join(paragraph_lines), headings.path))
        paragraph_lines = []

    for line in text.splitlines():
        heading = numbered_heading(line)
        if heading:
            flush()
            headings.enter(*heading)
        elif line.strip():
            paragraph_lines.append(line)
        else:
            flush()

    flush()
    return blocks
