"""Parsers that preserve the structural context of knowledge documents."""

from after_sales_agent.application.knowledge_ingestion.parsers.markdown import parse_markdown
from after_sales_agent.application.knowledge_ingestion.parsers.plain_text import (
    parse_plain_text,
)

__all__ = ["parse_markdown", "parse_plain_text"]
