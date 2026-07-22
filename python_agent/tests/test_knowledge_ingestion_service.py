from __future__ import annotations

import base64
import io
import json

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from after_sales_agent.api import http_server
from after_sales_agent.application.knowledge_ingestion_service import (
    KnowledgeIngestionService,
    KnowledgeParseError,
)
from after_sales_agent.application.knowledge_admin_service import KnowledgeAdminService


class FakeClassifier:
    def __init__(self, response: object) -> None:
        self.response = response

    def classify(self, **_kwargs: object) -> object:
        return self.response


class RaisingClassifier:
    def classify(self, **_kwargs: object) -> dict[str, object]:
        raise RuntimeError("classifier unavailable")


def _pdf_bytes(*texts: str | tuple[str, ...], encrypted: bool = False) -> bytes:
    writer = PdfWriter()
    for text in texts:
        lines = (text,) if isinstance(text, str) else text
        page = writer.add_blank_page(width=300, height=300)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        font_ref = writer._add_object(font)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
        )
        commands = ["BT /F1 12 Tf"]
        for index, line in enumerate(lines):
            commands.append(f"72 {180 - index * 24} Td ({line}) Tj")
        commands.append("ET")
        stream = DecodedStreamObject()
        stream.set_data("\n".join(commands).encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted:
        writer.encrypt("secret")
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _parse_payload(*, file_name: str, content: bytes) -> dict[str, object]:
    return {
        "file_name": file_name,
        "content_base64": base64.b64encode(content).decode("ascii"),
        "knowledge_type": "faq",
        "allowed_metadata": {
            "product_categories": ["product"],
            "scenes": ["scene"],
            "intents": ["intent"],
        },
    }


def _oversized_table_content() -> bytes:
    return ("# Limits\n\n|" + ("header " * 800) + "|\n|---|\n|value|").encode("utf-8")


def _invoke_parse_route(monkeypatch: pytest.MonkeyPatch, payload: dict[str, object], token: str | None) -> list[tuple[dict[str, object], int]]:
    body = json.dumps(payload).encode("utf-8")
    handler = object.__new__(http_server.AgentApiHandler)
    handler.path = "/api/knowledge/parse"
    handler.headers = {"Content-Length": str(len(body))}
    if token is not None:
        handler.headers["X-Agent-Internal-Token"] = token
    handler.rfile = io.BytesIO(body)
    sent: list[tuple[dict[str, object], int]] = []
    handler._send_json = lambda value, *, status=200: sent.append((value, status))
    monkeypatch.setattr(http_server, "AGENT_INTERNAL_TOKEN", "knowledge-token")
    handler.do_POST()
    return sent


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


def test_rule_matching_requires_english_token_boundaries_and_keeps_chinese_phrase_matching() -> None:
    result = KnowledgeIngestionService(classifier=FakeClassifier({})).parse(
        file_name="policy.txt",
        content="undamaged\n质量问题".encode("utf-8"),
        knowledge_type="faq",
        allowed_metadata={
            "product_categories": ["damaged"],
            "scenes": ["damaged", "质量问题"],
            "intents": ["damaged"],
        },
    )

    chunk = result.chunks[0]
    assert chunk.product_categories is None
    assert chunk.scenes == ["质量问题"]
    assert chunk.intents is None
    assert chunk.review_required is True
    assert KnowledgeIngestionService._contains_term("The return policy applies", "return_policy") is True
    assert KnowledgeIngestionService._contains_term("return_policy_extended", "return_policy") is False


def test_cjk_rule_matching_rejects_negated_substrings_and_requires_review() -> None:
    result = KnowledgeIngestionService(classifier=FakeClassifier({})).parse(
        file_name="policy.txt",
        content="不退款；非质量问题".encode("utf-8"),
        knowledge_type="faq",
        allowed_metadata={
            "product_categories": ["退款"],
            "scenes": ["质量问题"],
            "intents": ["退款"],
        },
    )

    chunk = result.chunks[0]
    assert chunk.product_categories is None
    assert chunk.scenes is None
    assert chunk.intents is None
    assert chunk.review_required is True
    assert KnowledgeIngestionService._contains_term("质量问题", "质量问题") is True
    assert KnowledgeIngestionService._contains_term("标题：质量问题", "质量问题") is True


@pytest.mark.parametrize("response", [{}, None, []])
def test_empty_or_non_dict_model_response_is_not_marked_as_available(response: object) -> None:
    result = KnowledgeIngestionService(classifier=FakeClassifier(response)).parse(
        file_name="policy.txt",
        content=b"unclassified text",
        knowledge_type="faq",
        allowed_metadata={
            "product_categories": ["headphone"],
            "scenes": ["quality_issue"],
            "intents": ["refund"],
        },
    )

    assert result.chunks[0].classification_source == "unclassified"
    assert result.chunks[0].review_required is True


@pytest.mark.parametrize(
    ("file_name", "content", "error"),
    [
        ("policy.docx", b"not supported", "UNSUPPORTED_FILE_TYPE"),
        ("broken.pdf", b"not a PDF", "FILE_DECODE_FAILED"),
        ("encrypted.pdf", _pdf_bytes("protected", encrypted=True), "PDF_ENCRYPTED"),
        ("empty.md", b"", "DOCUMENT_CONTENT_EMPTY"),
        ("empty.txt", b"", "DOCUMENT_CONTENT_EMPTY"),
    ],
)
def test_parse_rejects_unsupported_and_unreadable_documents(file_name: str, content: bytes, error: str) -> None:
    with pytest.raises(KnowledgeParseError, match=error):
        KnowledgeIngestionService().parse(
            file_name=file_name,
            content=content,
            knowledge_type="faq",
            allowed_metadata={},
        )


def test_parse_wraps_expected_chunker_errors_with_stable_code() -> None:
    with pytest.raises(KnowledgeParseError, match="DOCUMENT_CHUNKING_FAILED"):
        KnowledgeIngestionService().parse(
            file_name="limits.md",
            content=_oversized_table_content(),
            knowledge_type="faq",
            allowed_metadata={},
        )


def test_parse_rejects_invalid_utf8_txt() -> None:
    with pytest.raises(KnowledgeParseError, match="FILE_DECODE_FAILED"):
        KnowledgeIngestionService().parse(
            file_name="policy.txt",
            content=b"\xff\xfe",
            knowledge_type="faq",
            allowed_metadata={},
        )


def test_text_pdf_chunks_keep_structured_source_page_range() -> None:
    result = KnowledgeIngestionService(classifier=FakeClassifier({})).parse(
        file_name="policy.pdf",
        content=_pdf_bytes("first page", "second page"),
        knowledge_type="faq",
        allowed_metadata={},
    )

    assert [chunk.page_number for chunk in result.chunks] == [1]
    assert [chunk.metadata["page_end"] for chunk in result.chunks] == [2]
    assert [chunk.text for chunk in result.chunks] == ["first page\n\nsecond page"]


def test_parse_uses_structured_chunks_without_fixed_overlap() -> None:
    returns_body = "".join(f"Sentence {index}. " for index in range(600))
    content = "# Returns\n\n" + returns_body + "\n\n# Exchanges\n\nExchange body."
    result = KnowledgeIngestionService(classifier=FakeClassifier({})).parse(
        file_name="policy.md",
        content=content.encode("utf-8"),
        knowledge_type="faq",
        allowed_metadata={},
    )

    return_chunks = [chunk for chunk in result.chunks if chunk.heading_path == ["Returns"]]
    assert len(return_chunks) > 1
    assert "".join(chunk.text for chunk in return_chunks) == returns_body
    assert result.chunks[-1].heading_path == ["Exchanges"]
    for chunk in result.chunks:
        assert chunk.metadata["page_start"] is None
        assert chunk.metadata["page_end"] is None
        assert chunk.metadata["content_types"] == ["paragraph"]
        assert isinstance(chunk.metadata["estimated_tokens"], int)
        assert 0 < chunk.metadata["estimated_tokens"] <= 800
        assert chunk.metadata["chunking_strategy"] == "structured_recursive_v1"


def test_markdown_and_txt_do_not_fake_page_one() -> None:
    for name in ("policy.md", "policy.txt"):
        result = KnowledgeIngestionService().parse(
            file_name=name,
            content=b"# Title\n\nBody" if name.endswith(".md") else b"1. Title\n\nBody",
            knowledge_type="faq",
            allowed_metadata={},
        )

        assert result.chunks[0].page_number is None
        assert result.chunks[0].metadata["page_end"] is None


def test_model_failure_keeps_rule_metadata_and_requires_review_for_unknown_fields() -> None:
    result = KnowledgeIngestionService(classifier=RaisingClassifier()).parse(
        file_name="policy.txt",
        content=b"headphone refund",
        knowledge_type="faq",
        allowed_metadata={
            "product_categories": ["headphone"],
            "scenes": ["quality_issue"],
            "intents": ["refund"],
        },
    )

    chunk = result.chunks[0]
    assert chunk.product_categories == ["headphone"]
    assert chunk.intents == ["refund"]
    assert chunk.scenes is None
    assert chunk.classification_source == "rule"
    assert chunk.review_required is True


def test_mixed_model_metadata_keeps_only_allowed_values_and_requires_review() -> None:
    result = KnowledgeIngestionService(
        classifier=FakeClassifier({"intents": ["refund", "not_allowed"]})
    ).parse(
        file_name="policy.txt",
        content=b"headphone quality_issue",
        knowledge_type="faq",
        allowed_metadata={
            "product_categories": ["headphone"],
            "scenes": ["quality_issue"],
            "intents": ["refund"],
        },
    )

    assert result.chunks[0].intents == ["refund"]
    assert result.chunks[0].review_required is True


def test_knowledge_parse_route_rejects_invalid_internal_token(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = _invoke_parse_route(
        monkeypatch,
        _parse_payload(file_name="policy.txt", content=b"product scene intent"),
        token="wrong-token",
    )

    assert sent == [({"error": "unauthorized"}, 401)]


def test_knowledge_parse_route_accepts_real_internal_token(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = _invoke_parse_route(
        monkeypatch,
        _parse_payload(file_name="policy.txt", content=b"product scene intent"),
        token="knowledge-token",
    )

    assert sent[0][1] == 200
    assert sent[0][0]["content"] == "product scene intent"


@pytest.mark.parametrize(
    ("file_name", "content", "error", "status"),
    [
        ("policy.docx", b"not supported", "UNSUPPORTED_FILE_TYPE", 415),
        ("broken.pdf", b"not a PDF", "FILE_DECODE_FAILED", 422),
        ("encrypted.pdf", _pdf_bytes("protected", encrypted=True), "PDF_ENCRYPTED", 422),
        ("scan.pdf", _pdf_bytes(""), "PDF_TEXT_LAYER_MISSING", 422),
        ("empty.md", b"", "DOCUMENT_CONTENT_EMPTY", 422),
        ("empty.txt", b"", "DOCUMENT_CONTENT_EMPTY", 422),
        ("limits.md", _oversized_table_content(), "DOCUMENT_CHUNKING_FAILED", 422),
    ],
)
def test_knowledge_parse_route_maps_parse_errors_without_internal_details(
    monkeypatch: pytest.MonkeyPatch,
    file_name: str,
    content: bytes,
    error: str,
    status: int,
) -> None:
    sent = _invoke_parse_route(monkeypatch, _parse_payload(file_name=file_name, content=content), "knowledge-token")

    assert sent == [({"error": error}, status)]
