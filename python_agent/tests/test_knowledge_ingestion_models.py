import pytest

from after_sales_agent.application.knowledge_ingestion.models import ChunkingConfig, DocumentBlock
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


def test_token_estimate_is_deterministic_for_cjk_words_and_punctuation() -> None:
    text = "退款 policy-2026 生效。"

    assert estimate_tokens(text) == estimate_tokens(text)
    assert estimate_tokens(text) > 0


def test_hard_split_never_returns_blank_or_oversized_units() -> None:
    text = "质量问题" * 900
    parts = split_by_estimated_tokens(text, hard_max_tokens=80)

    assert parts
    assert all(part.strip() and estimate_tokens(part) <= 80 for part in parts)
    assert "".join(parts) == text


def test_hard_split_caps_a_single_pathological_word_by_characters() -> None:
    text = "x" * 15000
    parts = split_by_estimated_tokens(text, hard_max_tokens=800, hard_max_chars=6400)

    assert "".join(parts) == text
    assert all(len(part) <= 6400 for part in parts)
