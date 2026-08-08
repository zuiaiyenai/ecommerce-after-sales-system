import pytest

from after_sales_agent.application.knowledge_ingestion.models import (
    ChunkingConfig,
    DocumentBlock,
    StructuredChunk,
)
from after_sales_agent.application.knowledge_ingestion.token_counter import (
    estimate_tokens,
    split_by_estimated_tokens,
)


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
