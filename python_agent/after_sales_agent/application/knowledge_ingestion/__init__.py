"""Structured knowledge-document ingestion primitives."""

from after_sales_agent.application.knowledge_ingestion.models import KnowledgeParseError
from after_sales_agent.application.knowledge_ingestion.service import (
    DraftChunk,
    KnowledgeIngestionService,
    MetadataClassifier,
    ParseResult,
)

__all__ = [
    "DraftChunk",
    "KnowledgeIngestionService",
    "KnowledgeParseError",
    "MetadataClassifier",
    "ParseResult",
]
