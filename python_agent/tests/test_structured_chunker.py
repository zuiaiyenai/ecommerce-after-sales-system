from __future__ import annotations

from after_sales_agent.application.knowledge_ingestion.models import (
    ChunkingConfig,
    DocumentBlock,
)
from after_sales_agent.application.knowledge_ingestion.structured_chunker import (
    StructuredChunker,
)


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


def test_list_and_code_blocks_split_on_items_and_lines() -> None:
    config = ChunkingConfig(target_tokens=6, hard_max_tokens=8, min_merge_tokens=2)
    list_block = DocumentBlock("list", "- alpha beta\n- gamma delta\n- epsilon zeta", ("List",))
    code_block = DocumentBlock("code", "first line\nsecond line\nthird line", ("Code",))

    list_chunks = StructuredChunker(config).chunk([list_block])
    code_chunks = StructuredChunker(config).chunk([code_block])

    assert all(chunk.estimated_tokens <= 8 for chunk in list_chunks + code_chunks)
    assert "".join(chunk.text for chunk in list_chunks).replace("\n\n", "") == list_block.text
    assert "".join(chunk.text for chunk in code_chunks).replace("\n\n", "") == code_block.text
