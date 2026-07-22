from __future__ import annotations

from after_sales_agent.application.knowledge_ingestion.models import DocumentBlock
from after_sales_agent.application.knowledge_ingestion.section_builder import (
    HeadingStack,
    numbered_heading,
)


def parse_plain_text(text: str) -> list[DocumentBlock]:
    headings = HeadingStack()
    blocks: list[DocumentBlock] = []

    for line in text.splitlines():
        heading = numbered_heading(line)
        if heading:
            headings.enter(*heading)
        elif line.strip():
            blocks.append(DocumentBlock("paragraph", line.strip(), headings.path))

    return blocks
