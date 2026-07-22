"""Backward-compatible imports for the structured knowledge ingestion facade."""

from after_sales_agent.application.knowledge_ingestion.service import (
    DraftChunk,
    KnowledgeIngestionService,
    KnowledgeParseError,
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
