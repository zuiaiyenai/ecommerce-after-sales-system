from __future__ import annotations

import base64
import io
import json

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject

from after_sales_agent.interface import http_server
from after_sales_agent.application.knowledge_ingestion import (
    KnowledgeIngestionService,
    KnowledgeParseError,
)
from after_sales_agent.application.knowledge_admin_service import KnowledgeAdminService
from after_sales_agent.application.knowledge_ingestion.models import (
    ChunkingConfig,
    DocumentBlock,
    StructuredChunk,
)
from after_sales_agent.application.knowledge_ingestion.token_counter import (
    estimate_tokens,
    split_by_estimated_tokens,
)
from after_sales_agent.application.knowledge_ingestion.structured_chunker import (
    StructuredChunker,
)
from after_sales_agent.application.knowledge_ingestion.parsers.markdown import parse_markdown
from after_sales_agent.application.knowledge_ingestion.parsers.plain_text import (
    parse_plain_text,
)
from after_sales_agent.application.knowledge_ingestion.parsers import pdf as pdf_parser
from after_sales_agent.application.knowledge_ingestion.parsers.pdf import parse_pdf
from after_sales_agent.application.knowledge_ingestion.section_builder import (
    HeadingStack,
    numbered_heading,
)


# ---------------------------------------------------------------------------
# Helpers from test_knowledge_ingestion_service.py
# ---------------------------------------------------------------------------

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


def _invoke_post_route(
    monkeypatch: pytest.MonkeyPatch,
    *,
    path: str,
    body: bytes,
    general_limit: int,
    knowledge_parse_limit: int,
) -> list[tuple[dict[str, object], int]]:
    handler = object.__new__(http_server.AgentApiHandler)
    handler.path = path
    handler.headers = {
        "Content-Length": str(len(body)),
        "X-Agent-Internal-Token": "knowledge-token",
    }
    handler.rfile = io.BytesIO(body)
    sent: list[tuple[dict[str, object], int]] = []
    handler._send_json = lambda value, *, status=200: sent.append((value, status))
    monkeypatch.setattr(http_server, "AGENT_INTERNAL_TOKEN", "knowledge-token")
    monkeypatch.setattr(http_server, "AGENT_MAX_REQUEST_BYTES", general_limit)
    monkeypatch.setattr(http_server, "KNOWLEDGE_PARSE_MAX_REQUEST_BYTES", knowledge_parse_limit)
    handler.do_POST()
    return sent


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


# ---------------------------------------------------------------------------
# Helpers from test_structured_document_parsers.py
# ---------------------------------------------------------------------------

def _pdf_bytes_for_parsers(*pages: tuple[str, ...]) -> bytes:
    writer = PdfWriter()
    for lines in pages:
        _add_text_page(writer, lines)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _add_text_page(writer: PdfWriter, lines: tuple[str, ...]) -> None:
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
        commands.append(f"72 {250 - index * 30} Td ({line}) Tj")
    commands.append("ET")
    stream = DecodedStreamObject()
    stream.set_data("\n".join(commands).encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)


def _mixed_pdf_bytes(*, middle: str) -> bytes:
    writer = PdfWriter()
    _add_text_page(writer, ("First text page",))
    page = writer.add_blank_page(width=300, height=300)
    if middle == "image":
        image = DecodedStreamObject()
        image.set_data(b"\x00")
        image.update(
            {
                NameObject("/Type"): NameObject("/XObject"),
                NameObject("/Subtype"): NameObject("/Image"),
                NameObject("/Width"): NumberObject(1),
                NameObject("/Height"): NumberObject(1),
                NameObject("/ColorSpace"): NameObject("/DeviceGray"),
                NameObject("/BitsPerComponent"): NumberObject(8),
            }
        )
        image_ref = writer._add_object(image)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/XObject"): DictionaryObject({NameObject("/Im0"): image_ref})}
        )
        stream = DecodedStreamObject()
        stream.set_data(b"q 100 0 0 100 10 10 cm /Im0 Do Q")
        page[NameObject("/Contents")] = writer._add_object(stream)
    _add_text_page(writer, ("Third text page",))
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


# ===========================================================================
# Tests from test_knowledge_ingestion_service.py
# ===========================================================================

def test_knowledge_parse_default_request_limit_covers_java_max_file_and_json_envelope() -> None:
    max_file_bytes = 10 * 1024 * 1024
    encoded_bytes = 4 * ((max_file_bytes + 2) // 3)

    assert http_server.KNOWLEDGE_PARSE_JSON_ENVELOPE_BYTES == 1024 * 1024
    assert http_server.DEFAULT_KNOWLEDGE_PARSE_MAX_REQUEST_BYTES == (
        encoded_bytes + http_server.KNOWLEDGE_PARSE_JSON_ENVELOPE_BYTES
    )


def test_knowledge_parse_route_uses_dedicated_request_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    body = json.dumps(_parse_payload(file_name="policy.txt", content=b"refund policy")).encode("utf-8")
    assert len(body) > 64

    sent = _invoke_post_route(
        monkeypatch,
        path="/api/knowledge/parse",
        body=body,
        general_limit=64,
        knowledge_parse_limit=len(body),
    )

    assert sent[0][1] == 200
    assert sent[0][0]["content"] == "refund policy"


def test_knowledge_parse_route_returns_stable_file_too_large_error(monkeypatch: pytest.MonkeyPatch) -> None:
    body = json.dumps(_parse_payload(file_name="policy.txt", content=b"refund policy")).encode("utf-8")
    limit = len(body) - 1

    sent = _invoke_post_route(
        monkeypatch,
        path="/api/knowledge/parse",
        body=body,
        general_limit=64,
        knowledge_parse_limit=limit,
    )

    assert sent == [({"error": "FILE_TOO_LARGE", "max_bytes": limit}, 413)]


def test_non_parse_route_keeps_general_request_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    body = json.dumps({"query": "refund policy"}).encode("utf-8")
    limit = len(body) - 1

    sent = _invoke_post_route(
        monkeypatch,
        path="/api/knowledge/retrieve",
        body=body,
        general_limit=limit,
        knowledge_parse_limit=len(body) + 100,
    )

    assert sent == [({"error": "request_too_large", "max_bytes": limit}, 413)]


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


@pytest.mark.parametrize(
    ("file_name", "content", "source_format"),
    [
        ("policy.md", b"# Refund\n\nfixture-body-must-not-be-logged", "md"),
        ("policy.txt", b"fixture-body-must-not-be-logged", "txt"),
        ("policy.pdf", _pdf_bytes("fixture-body-must-not-be-logged"), "pdf"),
    ],
)
def test_parse_is_deterministic_and_logs_only_aggregate_chunk_metrics(
    caplog: pytest.LogCaptureFixture,
    file_name: str,
    content: bytes,
    source_format: str,
) -> None:
    service = KnowledgeIngestionService()

    with caplog.at_level("INFO", logger="after_sales_agent.application.knowledge_ingestion.service"):
        first = service.parse(
            file_name=file_name,
            content=content,
            knowledge_type="faq",
            allowed_metadata={},
        )
        second = service.parse(
            file_name=file_name,
            content=content,
            knowledge_type="faq",
            allowed_metadata={},
        )

    assert first.to_dict() == second.to_dict()
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert f"source_format={source_format}" in messages
    assert "chunk_count=" in messages
    assert "max_estimated_tokens=" in messages
    assert "distinct_heading_paths=" in messages
    assert "cross_page_chunk_count=" in messages
    assert "strategy_version=" in messages
    assert "fixture-body-must-not-be-logged" not in messages


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


# ===========================================================================
# Tests from test_knowledge_ingestion_models.py
# ===========================================================================

def test_chunking_defaults_are_versioned_and_ordered() -> None:
    config = ChunkingConfig()

    assert (config.min_merge_tokens, config.target_tokens, config.hard_max_tokens) == (150, 500, 800)
    assert config.chunking_strategy == "structured_recursive_v1"


def test_document_block_rejects_blank_text_and_invalid_pages() -> None:
    with pytest.raises(ValueError, match="text"):
        DocumentBlock("paragraph", "", (), None, None)
    with pytest.raises(ValueError, match="page"):
        DocumentBlock("paragraph", "body", (), 4, 3)


def test_token_estimate_counts_cjk_words_punctuation_and_whitespace() -> None:
    assert estimate_tokens("退款 policy_2026，生效。") == 7


def test_token_estimate_treats_nfkc_equivalent_words_identically() -> None:
    assert estimate_tokens("ABC_123，退款") == 4
    assert estimate_tokens("ＡＢＣ＿１２３，退款") == 4


def test_hard_split_rejects_indivisible_atomic_unit_over_token_limit() -> None:
    with pytest.raises(ValueError, match="indivisible atomic unit.*token limit"):
        split_by_estimated_tokens("\u2025", hard_max_tokens=1)


def test_hard_split_preserves_nfkc_source_text_with_default_limit() -> None:
    text = "\uff21\uff22\uff23\uff3f\uff11\uff12\uff13"

    assert split_by_estimated_tokens(text, hard_max_tokens=800) == [text]


def test_models_normalize_heading_paths_and_content_types_to_tuples() -> None:
    block = DocumentBlock("paragraph", "body", ["Returns"])
    chunk = StructuredChunk(
        text="body",
        heading_path=["Returns", "Eligibility"],
        page_start=1,
        page_end=1,
        content_types=["paragraph", "policy"],
        estimated_tokens=1,
    )

    assert block.heading_path == ("Returns",)
    assert chunk.heading_path == ("Returns", "Eligibility")
    assert chunk.content_types == ("paragraph", "policy")


def test_hard_split_never_returns_blank_or_oversized_units() -> None:
    text = "质量问题" * 900
    parts = split_by_estimated_tokens(text, hard_max_tokens=80)

    assert parts
    assert all(part.strip() and estimate_tokens(part) <= 80 for part in parts)
    assert "".join(parts) == text


def test_hard_split_keeps_words_punctuation_boundaries_and_whitespace() -> None:
    text = "alpha_2026， beta_2"

    parts = split_by_estimated_tokens(text, hard_max_tokens=1)

    assert parts == ["alpha_2026", "， ", "beta_2"]
    assert "".join(parts) == text
    assert [estimate_tokens(part) for part in parts] == [1, 1, 1]


def test_hard_split_caps_a_single_pathological_word_by_characters() -> None:
    text = "x" * 15000
    parts = split_by_estimated_tokens(text, hard_max_tokens=800, hard_max_chars=6400)

    assert "".join(parts) == text
    assert all(len(part) <= 6400 for part in parts)


# ===========================================================================
# Tests from test_structured_chunker.py
# ===========================================================================

def test_combines_paragraphs_without_crossing_headings() -> None:
    config = ChunkingConfig(target_tokens=20, hard_max_tokens=30, min_merge_tokens=5)
    blocks = [
        DocumentBlock("paragraph", "Return eligibility.", ("Returns",), None, None),
        DocumentBlock("paragraph", "Proof is required.", ("Returns",), None, None),
        DocumentBlock("paragraph", "Exchange eligibility.", ("Exchanges",), None, None),
    ]

    chunks = StructuredChunker(config).chunk(blocks)

    assert chunks[0].heading_path == ("Returns",)
    assert chunks[-1].heading_path == ("Exchanges",)
    assert "Exchange eligibility." not in chunks[0].text


def test_recurses_from_sentences_to_token_fallback_and_enforces_hard_max() -> None:
    config = ChunkingConfig(target_tokens=20, hard_max_tokens=30, min_merge_tokens=5)
    text = "Normal sentence. " + "oversized " * 80
    block = DocumentBlock("paragraph", text, ("Rules",), 2, 2)

    chunks = StructuredChunker(config).chunk([block])

    assert all(0 < chunk.estimated_tokens <= 30 for chunk in chunks)
    assert "".join(chunk.text for chunk in chunks).replace("\n\n", "") == text


def test_merges_small_adjacent_chunks_only_with_compatible_context() -> None:
    config = ChunkingConfig(target_tokens=8, hard_max_tokens=12, min_merge_tokens=4)
    blocks = [
        DocumentBlock("paragraph", "A.", ("Same",), 1, 1),
        DocumentBlock("paragraph", "B.", ("Same",), 2, 2),
        DocumentBlock("paragraph", "C.", ("Different",), 2, 2),
    ]

    chunks = StructuredChunker(config).chunk(blocks)

    assert "A." in chunks[0].text and "B." in chunks[0].text
    assert chunks[-1].heading_path == ("Different",)


def test_does_not_merge_reverse_page_ranges() -> None:
    config = ChunkingConfig(target_tokens=20, hard_max_tokens=30, min_merge_tokens=5)
    blocks = [
        DocumentBlock("paragraph", "Later pages.", ("Same",), 5, 10),
        DocumentBlock("paragraph", "Earlier pages.", ("Same",), 1, 2),
    ]

    chunks = StructuredChunker(config).chunk(blocks)

    assert len(chunks) == 2
    assert all(chunk.page_start is not None and chunk.page_start <= chunk.page_end for chunk in chunks)


def test_small_chunk_can_merge_up_to_hard_limit_when_it_exceeds_target() -> None:
    config = ChunkingConfig(target_tokens=8, hard_max_tokens=12, min_merge_tokens=4)
    blocks = [
        DocumentBlock("paragraph", "A.", ("Same",)),
        DocumentBlock("paragraph", "one two three four five six.", ("Same",)),
    ]

    chunks = StructuredChunker(config).chunk(blocks)

    assert len(chunks) == 1
    assert chunks[0].estimated_tokens > config.target_tokens
    assert chunks[0].estimated_tokens <= config.hard_max_tokens


def test_table_splits_by_rows_and_repeats_header() -> None:
    header = "|Type|Requirement|\n|---|---|"
    rows = "\n".join(f"|Type{i}|Description{i}|" for i in range(30))
    block = DocumentBlock("table", f"{header}\n{rows}", ("Table",))

    chunks = StructuredChunker(
        ChunkingConfig(target_tokens=30, hard_max_tokens=40, min_merge_tokens=5)
    ).chunk([block])

    assert len(chunks) > 1
    assert all(chunk.text.startswith(header) for chunk in chunks)
    assert all(chunk.content_types == ("table",) for chunk in chunks)


def test_table_reserves_header_budget_when_splitting_an_oversized_row() -> None:
    header = "|" + "h " * 26 + "|\n|---|"
    row = "|" + "v " * 20 + "|"
    block = DocumentBlock("table", f"{header}\n{row}", ("Table",))
    config = ChunkingConfig(
        target_tokens=35,
        hard_max_tokens=40,
        hard_max_chars=80,
        min_merge_tokens=5,
    )

    chunks = StructuredChunker(config).chunk([block])

    assert len(chunks) > 1
    assert all(chunk.text.startswith(f"{header}\n") for chunk in chunks)
    assert all(chunk.estimated_tokens <= config.hard_max_tokens for chunk in chunks)
    assert all(len(chunk.text) <= config.hard_max_chars for chunk in chunks)
    assert "".join(chunk.text[len(header) + 1 :] for chunk in chunks) == row


def test_table_rejects_a_header_that_leaves_no_data_budget() -> None:
    header = "|" + "h " * 35 + "|\n|---|"
    block = DocumentBlock("table", f"{header}\n|value|", ("Table",))
    config = ChunkingConfig(target_tokens=35, hard_max_tokens=40, min_merge_tokens=5)

    with pytest.raises(ValueError, match="table header leaves no room for data"):
        StructuredChunker(config).chunk([block])


def test_list_and_code_blocks_split_on_items_and_lines() -> None:
    config = ChunkingConfig(target_tokens=6, hard_max_tokens=8, min_merge_tokens=2)
    list_block = DocumentBlock("list", "- alpha beta\n- gamma delta\n- epsilon zeta", ("List",))
    code_block = DocumentBlock("code", "first line\nsecond line\nthird line", ("Code",))

    list_chunks = StructuredChunker(config).chunk([list_block])
    code_chunks = StructuredChunker(config).chunk([code_block])

    assert all(chunk.estimated_tokens <= 8 for chunk in list_chunks + code_chunks)
    assert "".join(chunk.text for chunk in list_chunks).replace("\n\n", "") == list_block.text
    assert "".join(chunk.text for chunk in code_chunks).replace("\n\n", "") == code_block.text


def test_oversized_code_split_preserves_blank_and_indented_lines() -> None:
    config = ChunkingConfig(target_tokens=6, hard_max_tokens=8, min_merge_tokens=2)
    text = "first one two three\n\n  second one two three\nthird one two three\n"
    block = DocumentBlock("code", text, ("Code",))

    chunks = StructuredChunker(config).chunk([block])

    assert len(chunks) > 1
    assert "".join(chunk.text for chunk in chunks) == text
    assert all(chunk.text.endswith("\n") for chunk in chunks)
    assert all(chunk.estimated_tokens <= config.hard_max_tokens for chunk in chunks)


@pytest.mark.parametrize("block_type", ["code", "list"])
def test_rejects_unattachable_oversized_whitespace_runs(block_type: str) -> None:
    config = ChunkingConfig(
        target_tokens=4,
        hard_max_tokens=8,
        hard_max_chars=10,
        min_merge_tokens=2,
    )
    whitespace_run = " " * (config.hard_max_chars + 1)
    text = f"first\n{whitespace_run}\nsecond\n"
    block = DocumentBlock(block_type, text, ("Whitespace",))

    with pytest.raises(ValueError, match="whitespace run.*character limit"):
        StructuredChunker(config).chunk([block])


# ===========================================================================
# Tests from test_structured_document_parsers.py
# ===========================================================================

def test_pdf_rejects_mixed_text_and_image_only_pages() -> None:
    with pytest.raises(pdf_parser.KnowledgeParseError, match="PDF_TEXT_LAYER_MISSING"):
        parse_pdf(_mixed_pdf_bytes(middle="image"))


def test_pdf_allows_genuinely_blank_page_between_text_pages() -> None:
    pages, blocks = parse_pdf(_mixed_pdf_bytes(middle="blank"))

    assert [page_number for page_number, _ in pages] == [1, 2, 3]
    assert [block.page_start for block in blocks] == [1, 3]


def test_pdf_page_text_extraction_exception_is_not_silently_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TextPage:
        def extract_text(self) -> str:
            return "body"

    class BrokenPage:
        def extract_text(self) -> str:
            raise RuntimeError("extract failed")

    class Reader:
        is_encrypted = False
        pages = [TextPage(), BrokenPage()]

    monkeypatch.setattr(pdf_parser, "PdfReader", lambda _content: Reader())

    with pytest.raises(pdf_parser.KnowledgeParseError, match="FILE_DECODE_FAILED"):
        pdf_parser.extract_pdf_pages(b"pdf")


def test_pdf_margin_cleanup_removes_only_edge_occurrence_when_text_repeats_in_body() -> None:
    _, blocks = parse_pdf(
        _pdf_bytes_for_parsers(
            ("Return policy", "Lead one", "Return policy", "Body one", "Tail one", "Page 1"),
            ("Return policy", "Lead two", "Return policy", "Body two", "Tail two", "Page 2"),
            ("Return policy", "Lead three", "Return policy", "Body three", "Tail three", "Page 3"),
        )
    )

    texts = "\n".join(block.text for block in blocks)
    assert texts.count("Return policy") == 3


def test_pdf_keeps_heading_across_pages_and_removes_stable_margins() -> None:
    pages, blocks = parse_pdf(
        _pdf_bytes_for_parsers(
            ("Return policy", "1.1 Refund rules", "First page body", "Page 1"),
            ("Return policy", "Second page body", "Page 2"),
            ("Return policy", "Third page body", "Page 3"),
        )
    )

    assert len(pages) == 3
    assert all("Return policy" not in block.text for block in blocks)
    assert [block.page_start for block in blocks] == [1, 2, 3]
    assert all(block.heading_path == ("Refund rules",) for block in blocks)


def test_pdf_does_not_remove_margin_lines_from_short_documents() -> None:
    _, blocks = parse_pdf(
        _pdf_bytes_for_parsers(
            ("Important notice", "First body"),
            ("Important notice", "Second body"),
        )
    )

    assert any("Important notice" in block.text for block in blocks)


def test_pdf_margin_cleanup_preserves_blank_lines_between_body_paragraphs() -> None:
    _, blocks = parse_pdf(
        _pdf_bytes_for_parsers(
            ("Return policy", "Page one first paragraph", " ", "Page one second paragraph", "Page 1"),
            ("Return policy", "Page two first paragraph", " ", "Page two second paragraph", "Page 2"),
            ("Return policy", "Page three first paragraph", " ", "Page three second paragraph", "Page 3"),
        )
    )

    assert [block.text for block in blocks] == [
        "Page one first paragraph",
        "Page one second paragraph",
        "Page two first paragraph",
        "Page two second paragraph",
        "Page three first paragraph",
        "Page three second paragraph",
    ]


def test_heading_stack_replaces_same_or_deeper_heading_levels() -> None:
    headings = HeadingStack()

    assert headings.enter(1, "退款规则") == ("退款规则",)
    assert headings.enter(2, "凭证要求") == ("退款规则", "凭证要求")
    assert headings.enter(2, "退款时效") == ("退款规则", "退款时效")
    assert headings.path == ("退款规则", "退款时效")


def test_markdown_preserves_heading_paths_and_atomic_block_types() -> None:
    blocks = parse_markdown(
        """# 退款规则
## 凭证要求

- 图片凭证
- 检测报告

| 类型 | 要求 |
| --- | --- |
| 图片 | 清晰 |

```text
# not a heading
```
"""
    )

    assert [block.block_type for block in blocks] == ["list", "table", "code"]
    assert all(block.heading_path == ("退款规则", "凭证要求") for block in blocks)
    assert all(block.page_start is None and block.page_end is None for block in blocks)


def test_markdown_supports_setext_headings() -> None:
    blocks = parse_markdown("退款规则\n====\n\n正文")

    assert blocks[0].heading_path == ("退款规则",)
    assert blocks[0].text == "正文"


def test_plain_text_uses_only_conservative_numbered_headings() -> None:
    blocks = parse_plain_text("第一章 退款规则\n\n正文。\n\n普通短句\n继续说明。")

    assert blocks[0].heading_path == ("退款规则",)
    assert [block.text for block in blocks] == ["正文。", "普通短句\n继续说明。"]


def test_numbered_heading_requires_an_explicit_numbering_marker() -> None:
    assert numbered_heading("第一章 退款规则") == (1, "退款规则")
    assert numbered_heading("二、凭证要求") == (1, "凭证要求")
    assert numbered_heading("1.2 图片要求") == (2, "图片要求")
    assert numbered_heading("普通短句") is None


def test_markdown_groups_quotes_and_consecutive_paragraph_lines() -> None:
    blocks = parse_markdown("> 第一行\n> 第二行\n\n正文第一行\n正文第二行")

    assert [block.block_type for block in blocks] == ["quote", "paragraph"]
    assert [block.text for block in blocks] == [
        "> 第一行\n> 第二行",
        "正文第一行\n正文第二行",
    ]


def test_markdown_recognizes_tables_without_outer_pipes() -> None:
    blocks = parse_markdown("类型 | 要求\n--- | ---\n图片 | 清晰")

    assert [block.block_type for block in blocks] == ["table"]


def test_markdown_keeps_invalid_closing_fence_inside_code_block() -> None:
    blocks = parse_markdown(
        """````text
# not a heading
````not-a-close
- still code
````
# 后续标题
正文
"""
    )

    assert [block.block_type for block in blocks] == ["code", "paragraph"]
    assert "````not-a-close\n- still code" in blocks[0].text
    assert blocks[1].heading_path == ("后续标题",)


def test_parsers_package_exports_public_parse_functions() -> None:
    from after_sales_agent.application.knowledge_ingestion.parsers import (
        parse_markdown as exported_markdown,
    )
    from after_sales_agent.application.knowledge_ingestion.parsers import (
        parse_plain_text as exported_plain_text,
    )

    assert exported_markdown is parse_markdown
    assert exported_plain_text is parse_plain_text


def test_plain_text_keeps_markdown_like_lines_in_a_paragraph() -> None:
    blocks = parse_plain_text("普通说明\n- 不是列表\n> 不是引用\n| 不是表格 |\n\n后续说明")

    assert [block.block_type for block in blocks] == ["paragraph", "paragraph"]
    assert [block.text for block in blocks] == [
        "普通说明\n- 不是列表\n> 不是引用\n| 不是表格 |",
        "后续说明",
    ]
