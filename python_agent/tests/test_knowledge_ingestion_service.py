from __future__ import annotations

import io

import pytest
from pypdf import PdfWriter

from after_sales_agent.application.knowledge_ingestion_service import (
    KnowledgeIngestionService,
    KnowledgeParseError,
)
from after_sales_agent.application.knowledge_admin_service import KnowledgeAdminService


class FakeClassifier:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response

    def classify(self, **_kwargs: object) -> dict[str, object]:
        return self.response


def test_markdown_sections_keep_heading_path_and_unknown_metadata_requires_review() -> None:
    service = KnowledgeIngestionService(classifier=FakeClassifier({"scenes": ["made_up"]}))

    result = service.parse(
        file_name="policy.md",
        content="# 退款\n## 质量问题\n功能异常可申请退款。".encode(),
        knowledge_type="after_sales_policy",
        allowed_metadata={"product_categories": ["headphone"], "scenes": ["quality_issue"], "intents": ["refund"]},
    )

    assert result.chunks[0].heading_path == ["退款", "质量问题"]
    assert result.chunks[0].scenes is None
    assert result.chunks[0].review_required is True


def test_scanned_pdf_is_rejected_without_ocr() -> None:
    buffer = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(buffer)

    with pytest.raises(KnowledgeParseError, match="PDF_TEXT_LAYER_MISSING"):
        KnowledgeIngestionService().parse(
            file_name="scan.pdf",
            content=buffer.getvalue(),
            knowledge_type="faq",
            allowed_metadata={},
        )


class _FakeIngestionService:
    def __init__(self) -> None:
        self.received: dict[str, object] | None = None

    def parse(self, **kwargs: object):  # type: ignore[no-untyped-def]
        self.received = kwargs
        return KnowledgeIngestionService().parse(
            file_name="policy.txt",
            content=b"refund",
            knowledge_type="faq",
            allowed_metadata={},
        )


def test_admin_parse_document_decodes_base64_and_returns_parse_result() -> None:
    ingestion = _FakeIngestionService()
    service = KnowledgeAdminService(ingestion=ingestion)

    result = service.parse_document(
        {
            "file_name": "policy.txt",
            "content_base64": "cmVmdW5k",
            "knowledge_type": "faq",
            "allowed_metadata": {"intents": ["refund"]},
        }
    )

    assert ingestion.received == {
        "file_name": "policy.txt",
        "content": b"refund",
        "knowledge_type": "faq",
        "allowed_metadata": {"intents": ["refund"]},
    }
    assert result["content"] == "refund"
    assert result["chunks"][0]["text"] == "refund"


def test_admin_parse_document_rejects_invalid_base64_with_stable_error() -> None:
    with pytest.raises(KnowledgeParseError, match="FILE_DECODE_FAILED"):
        KnowledgeAdminService().parse_document(
            {
                "file_name": "policy.txt",
                "content_base64": "not valid base64!",
                "knowledge_type": "faq",
            }
        )
