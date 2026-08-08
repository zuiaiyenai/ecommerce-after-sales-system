# Structured Document Chunking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace fixed character-window knowledge splitting with deterministic, structure-aware PDF/Markdown/TXT chunking that preserves source context and supplies contextualized embedding input without changing citation text.

**Architecture:** Python parses each supported format into a shared `DocumentBlock` model and runs one recursive structured chunker before metadata classification. Java remains responsible for draft revision state, persists structural metadata through review, builds the final context prefix from authoritative document data, embeds contextualized text, and publishes the original chunk text for citations.

**Tech Stack:** Python 3.11+, `pypdf`, `pytest`; Java 21, Spring Boot, `JdbcTemplate`, JUnit 5, Mockito; PostgreSQL 16 with pgvector and JSONB.

## Global Constraints

- Support one uploaded file at a time in `.pdf`, `.md`, or `.txt` format; do not add batch upload.
- Continue using `pypdf`; do not add PDF layout libraries or OCR.
- Defaults are `target_tokens=500`, `hard_max_tokens=800`, `min_merge_tokens=150`, `hard_max_chars=6400`, and `chunking_strategy="structured_recursive_v1"`.
- Token counts are deterministic local estimates named `estimated_tokens`; chunking must not call an LLM, network tokenizer, or runtime download.
- Keep `/api/knowledge/parse`, `KnowledgeIngestionService`, `heading_path`, and `page_number` backward compatible.
- `page_number` is the PDF start page; Markdown/TXT page fields are `null`; `page_end` is stored in JSON metadata.
- Existing `source_type` remains the knowledge business type; `source_format` is the file format (`pdf`, `markdown`, or `text`).
- `chunk_text` remains source text. Context prefixes are used for embeddings and `search_text`, never displayed as citation text.
- Java document metadata and revision are authoritative; Python structural metadata cannot overwrite business-owned fields.
- Parsing or embedding failure must not replace the currently published revision.
- Do not automatically reindex existing published knowledge or rebuild the PostgreSQL volume.
- Any Java `Long` identifier that reaches JavaScript must remain JSON string serialized.

---

## File Map

**Create:**

- `python_agent/after_sales_agent/application/knowledge_ingestion/__init__.py`: package exports.
- `python_agent/after_sales_agent/application/knowledge_ingestion/models.py`: immutable parser and chunk models plus configuration.
- `python_agent/after_sales_agent/application/knowledge_ingestion/token_counter.py`: deterministic token estimation and hard splitting.
- `python_agent/after_sales_agent/application/knowledge_ingestion/section_builder.py`: heading recognition and heading-stack state.
- `python_agent/after_sales_agent/application/knowledge_ingestion/parsers/__init__.py`: parser exports.
- `python_agent/after_sales_agent/application/knowledge_ingestion/parsers/markdown.py`: Markdown block parser.
- `python_agent/after_sales_agent/application/knowledge_ingestion/parsers/plain_text.py`: TXT block parser.
- `python_agent/after_sales_agent/application/knowledge_ingestion/parsers/pdf.py`: `pypdf` page extraction, repeated margin removal, and conservative PDF structure parsing.
- `python_agent/after_sales_agent/application/knowledge_ingestion/structured_chunker.py`: block grouping, recursive splitting, and small-chunk merging.
- `python_agent/after_sales_agent/application/knowledge_ingestion/service.py`: parsing facade and final metadata classification.
- `python_agent/tests/test_knowledge_ingestion_models.py`: model and token-estimator tests.
- `python_agent/tests/test_structured_document_parsers.py`: Markdown/TXT/PDF parser tests.
- `python_agent/tests/test_structured_chunker.py`: recursive chunking invariants.
- `sql/migrations/20260722_add_knowledge_chunk_draft_metadata.sql`: durable draft metadata migration.

**Modify:**

- `python_agent/after_sales_agent/application/knowledge_ingestion_service.py`: compatibility re-export only.
- `python_agent/tests/test_knowledge_ingestion_service.py`: service/API regression and metadata tests.
- `sql/pgvector_schema.sql`: fresh-install draft metadata column.
- `src/main/java/com/ecommerce/aftersales/service/KnowledgeDraftService.java`: persist parser structural metadata.
- `src/main/java/com/ecommerce/aftersales/service/KnowledgePublishService.java`: select, merge, and publish metadata; create contextualized search text.
- `src/main/java/com/ecommerce/aftersales/service/KnowledgeIngestionAsyncService.java`: unify text/file parsing and contextualized embedding input; remove fixed windows.
- `src/test/java/com/ecommerce/aftersales/service/KnowledgeDraftServiceTest.java`: draft metadata SQL contract.
- `src/test/java/com/ecommerce/aftersales/service/KnowledgePublishServiceTest.java`: metadata precedence and citation contract.
- `src/test/java/com/ecommerce/aftersales/service/KnowledgeIngestionAsyncServiceTest.java`: text parsing and embedding-input contract.

---

### Task 1: Shared Models And Deterministic Token Estimation

**Files:**

- Create: `python_agent/after_sales_agent/application/knowledge_ingestion/__init__.py`
- Create: `python_agent/after_sales_agent/application/knowledge_ingestion/models.py`
- Create: `python_agent/after_sales_agent/application/knowledge_ingestion/token_counter.py`
- Create: `python_agent/tests/test_knowledge_ingestion_models.py`

**Interfaces:**

- Produces: `KnowledgeParseError`, `ChunkingConfig`, `DocumentBlock`, `StructuredChunk`, `estimate_tokens(text: str) -> int`, and `split_by_estimated_tokens(text: str, hard_max_tokens: int, hard_max_chars: int = 6400) -> list[str]`.
- `DocumentBlock.heading_path` and `StructuredChunk.heading_path` are tuples internally; the service serializes them as JSON lists.

- [ ] **Step 1: Write failing model and token tests**

```python
import pytest

from after_sales_agent.application.knowledge_ingestion.models import ChunkingConfig, DocumentBlock
from after_sales_agent.application.knowledge_ingestion.token_counter import estimate_tokens, split_by_estimated_tokens


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
    parts = split_by_estimated_tokens("质量问题" * 900, hard_max_tokens=80)
    assert parts
    assert all(part.strip() and estimate_tokens(part) <= 80 for part in parts)
    assert "".join(parts) == "质量问题" * 900


def test_hard_split_caps_a_single_pathological_word_by_characters() -> None:
    parts = split_by_estimated_tokens("x" * 15000, hard_max_tokens=800, hard_max_chars=6400)
    assert "".join(parts) == "x" * 15000
    assert all(len(part) <= 6400 for part in parts)
```

- [ ] **Step 2: Run the tests and confirm import failure**

Run: `Set-Location python_agent; python -m pytest tests/test_knowledge_ingestion_models.py -v`

Expected: FAIL during collection because `after_sales_agent.application.knowledge_ingestion` does not exist.

- [ ] **Step 3: Implement immutable models and validation**

```python
@dataclass(frozen=True)
class ChunkingConfig:
    target_tokens: int = 500
    hard_max_tokens: int = 800
    min_merge_tokens: int = 150
    hard_max_chars: int = 6400
    chunking_strategy: str = "structured_recursive_v1"

    def __post_init__(self) -> None:
        if not 0 < self.min_merge_tokens <= self.target_tokens <= self.hard_max_tokens:
            raise ValueError("chunk token limits must satisfy min <= target <= hard max")


class KnowledgeParseError(ValueError):
    """Stable parse error code propagated across the Python/Java boundary."""


@dataclass(frozen=True)
class DocumentBlock:
    block_type: str
    text: str
    heading_path: tuple[str, ...] = ()
    page_start: int | None = None
    page_end: int | None = None
    splittable: bool = True

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("document block text must not be blank")
        if (self.page_start is None) != (self.page_end is None):
            raise ValueError("page range must be entirely present or absent")
        if self.page_start is not None and (self.page_start < 1 or self.page_end < self.page_start):
            raise ValueError("invalid page range")


@dataclass(frozen=True)
class StructuredChunk:
    text: str
    heading_path: tuple[str, ...]
    page_start: int | None
    page_end: int | None
    content_types: tuple[str, ...]
    estimated_tokens: int
```

Implement `estimate_tokens` by scanning NFKC-normalized text and counting each CJK character, each contiguous alphanumeric/underscore word, and each non-whitespace punctuation symbol. Implement hard splitting by accumulating lexical units until the next unit would exceed `hard_max_tokens` or `hard_max_chars`; preserve whitespace as zero-cost source units and preserve every source character in order. Split an individual lexical unit by characters only when it exceeds `hard_max_chars`.

- [ ] **Step 4: Run the focused tests**

Run: `Set-Location python_agent; python -m pytest tests/test_knowledge_ingestion_models.py -v`

Expected: 5 tests PASS.

- [ ] **Step 5: Commit the shared primitives**

```powershell
git add python_agent/after_sales_agent/application/knowledge_ingestion python_agent/tests/test_knowledge_ingestion_models.py
git commit -m "feat: add structured chunking primitives"
```

---

### Task 2: Markdown And Plain-Text Structure Parsers

**Files:**

- Create: `python_agent/after_sales_agent/application/knowledge_ingestion/section_builder.py`
- Create: `python_agent/after_sales_agent/application/knowledge_ingestion/parsers/__init__.py`
- Create: `python_agent/after_sales_agent/application/knowledge_ingestion/parsers/markdown.py`
- Create: `python_agent/after_sales_agent/application/knowledge_ingestion/parsers/plain_text.py`
- Create: `python_agent/tests/test_structured_document_parsers.py`

**Interfaces:**

- Consumes: `DocumentBlock` from Task 1.
- Produces: `parse_markdown(text: str) -> list[DocumentBlock]`, `parse_plain_text(text: str) -> list[DocumentBlock]`, `HeadingStack.enter(level: int, title: str) -> tuple[str, ...]`, and `numbered_heading(line: str) -> tuple[int, str] | None`.

- [ ] **Step 1: Write failing Markdown and TXT parser tests**

```python
def test_markdown_preserves_heading_paths_and_atomic_block_types() -> None:
    blocks = parse_markdown("""# 退款规则

## 举证要求

- 图片凭证
- 检测报告

| 类型 | 要求 |
| --- | --- |
| 图片 | 清晰 |

```text
# not a heading
```
""")
    assert [block.block_type for block in blocks] == ["list", "table", "code"]
    assert all(block.heading_path == ("退款规则", "举证要求") for block in blocks)
    assert all(block.page_start is None and block.page_end is None for block in blocks)


def test_markdown_supports_setext_headings() -> None:
    blocks = parse_markdown("退款规则\n====\n\n正文")
    assert blocks[0].heading_path == ("退款规则",)
    assert blocks[0].text == "正文"


def test_plain_text_uses_only_conservative_numbered_headings() -> None:
    blocks = parse_plain_text("第一章 退款规则\n\n正文。\n\n普通短句\n\n继续说明。")
    assert blocks[0].heading_path == ("第一章 退款规则",)
    assert "普通短句" in [block.text for block in blocks]
```

- [ ] **Step 2: Run the parser tests and confirm missing imports**

Run: `Set-Location python_agent; python -m pytest tests/test_structured_document_parsers.py -k "markdown or plain" -v`

Expected: FAIL because parser modules are absent.

- [ ] **Step 3: Implement heading state and Markdown block recognition**

Implement `HeadingStack` so entering level N removes headings at level N or deeper, then returns the complete path. In `parse_markdown`, process fenced code before headings; recognize ATX and Setext headings; group consecutive list, table, quote, and paragraph lines; flush the current block on blank lines, block-type changes, or headings. Do not include heading text in body blocks.

```python
class HeadingStack:
    def __init__(self) -> None:
        self._items: list[tuple[int, str]] = []

    def enter(self, level: int, title: str) -> tuple[str, ...]:
        clean = title.strip()
        self._items = [item for item in self._items if item[0] < level]
        self._items.append((level, clean))
        return tuple(value for _, value in self._items)

    @property
    def path(self) -> tuple[str, ...]:
        return tuple(value for _, value in self._items)
```

Implement `numbered_heading` for explicit forms only: Chinese chapter/section prefixes, Chinese enumeration followed by `、`, and decimal numbering such as `1.2 标题`. A generic short line without such a marker remains a paragraph.

- [ ] **Step 4: Run focused parser tests**

Run: `Set-Location python_agent; python -m pytest tests/test_structured_document_parsers.py -k "markdown or plain" -v`

Expected: all selected tests PASS.

- [ ] **Step 5: Commit text parsers**

```powershell
git add python_agent/after_sales_agent/application/knowledge_ingestion python_agent/tests/test_structured_document_parsers.py
git commit -m "feat: parse markdown and text structure"
```

---

### Task 3: Conservative PDF Structure Parsing

**Files:**

- Create: `python_agent/after_sales_agent/application/knowledge_ingestion/parsers/pdf.py`
- Modify: `python_agent/tests/test_structured_document_parsers.py`
- Modify: `python_agent/tests/test_knowledge_ingestion_service.py`

**Interfaces:**

- Consumes: `DocumentBlock`, `HeadingStack`, and `numbered_heading` from Tasks 1-2.
- Produces: `extract_pdf_pages(content: bytes) -> list[tuple[int, str]]` and `parse_pdf(content: bytes) -> tuple[list[tuple[int, str]], list[DocumentBlock]]`.
- Raises the existing `KnowledgeParseError` codes through the service facade.

- [ ] **Step 1: Add failing PDF page-range and repeated-margin tests**

Extend the PDF fixture helper so each generated page can contain several positioned lines. Add tests asserting:

```python
def test_pdf_keeps_heading_across_pages_and_removes_stable_margins() -> None:
    pages, blocks = parse_pdf(_pdf_bytes(
        "售后政策\n第一章 退款规则\n第一页正文\n第 1 页",
        "售后政策\n第二页正文\n第 2 页",
        "售后政策\n第三页正文\n第 3 页",
    ))
    assert len(pages) == 3
    assert all("售后政策" not in block.text for block in blocks)
    assert [block.page_start for block in blocks] == [1, 2, 3]
    assert all(block.heading_path == ("第一章 退款规则",) for block in blocks)


def test_pdf_does_not_remove_margin_lines_from_short_documents() -> None:
    _, blocks = parse_pdf(_pdf_bytes("重要提示\n正文", "重要提示\n正文二"))
    assert any("重要提示" in block.text for block in blocks)
```

Keep existing encrypted and text-layer-missing tests unchanged.

- [ ] **Step 2: Run PDF tests and verify failure**

Run: `Set-Location python_agent; python -m pytest tests/test_structured_document_parsers.py tests/test_knowledge_ingestion_service.py -k pdf -v`

Expected: new tests FAIL because `parse_pdf` is missing.

- [ ] **Step 3: Implement PDF extraction and conservative cleanup**

Use `PdfReader(io.BytesIO(content))`, preserving existing `PDF_ENCRYPTED`, `PDF_TEXT_LAYER_MISSING`, and `FILE_DECODE_FAILED` behavior. For documents with at least three pages, inspect the first and last two nonblank lines of each page. Remove a normalized short line only when it appears in the same margin on at least `max(3, ceil(page_count * 0.6))` pages. Never remove repeated interior lines.

Parse each page with the shared numbered-heading rules. Emit page-local blocks carrying `(page_number, page_number)`; retain the heading stack between pages so the chunker can later combine a section across pages.

- [ ] **Step 4: Run all parser and legacy PDF tests**

Run: `Set-Location python_agent; python -m pytest tests/test_structured_document_parsers.py tests/test_knowledge_ingestion_service.py -k "pdf or scanned" -v`

Expected: all selected tests PASS.

- [ ] **Step 5: Commit PDF parsing**

```powershell
git add python_agent/after_sales_agent/application/knowledge_ingestion/parsers/pdf.py python_agent/tests/test_structured_document_parsers.py python_agent/tests/test_knowledge_ingestion_service.py
git commit -m "feat: preserve pdf structure and pages"
```

---

### Task 4: Recursive Structured Chunker

**Files:**

- Create: `python_agent/after_sales_agent/application/knowledge_ingestion/structured_chunker.py`
- Create: `python_agent/tests/test_structured_chunker.py`

**Interfaces:**

- Consumes: `ChunkingConfig`, `DocumentBlock`, `StructuredChunk`, `estimate_tokens`, and `split_by_estimated_tokens`.
- Produces: `StructuredChunker(config: ChunkingConfig).chunk(blocks: Sequence[DocumentBlock]) -> list[StructuredChunk]`.

- [ ] **Step 1: Write failing chunking-invariant tests**

```python
def test_combines_paragraphs_without_crossing_headings() -> None:
    config = ChunkingConfig(target_tokens=20, hard_max_tokens=30, min_merge_tokens=5)
    blocks = [
        DocumentBlock("paragraph", "退款条件。", ("退款",), None, None),
        DocumentBlock("paragraph", "需要凭证。", ("退款",), None, None),
        DocumentBlock("paragraph", "换货条件。", ("换货",), None, None),
    ]
    chunks = StructuredChunker(config).chunk(blocks)
    assert chunks[0].heading_path == ("退款",)
    assert chunks[-1].heading_path == ("换货",)
    assert "换货条件" not in chunks[0].text


def test_recurses_from_sentence_to_token_and_enforces_hard_max() -> None:
    config = ChunkingConfig(target_tokens=20, hard_max_tokens=30, min_merge_tokens=5)
    block = DocumentBlock("paragraph", "正常句子。" + "异常" * 80, ("规则",), 2, 2)
    chunks = StructuredChunker(config).chunk([block])
    assert all(0 < chunk.estimated_tokens <= 30 for chunk in chunks)
    assert "".join(chunk.text for chunk in chunks).replace("\n\n", "") == block.text


def test_merges_small_adjacent_chunks_only_with_compatible_context() -> None:
    config = ChunkingConfig(target_tokens=8, hard_max_tokens=12, min_merge_tokens=4)
    blocks = [
        DocumentBlock("paragraph", "甲。", ("同章",), 1, 1),
        DocumentBlock("paragraph", "乙。", ("同章",), 2, 2),
        DocumentBlock("paragraph", "丙。", ("异章",), 2, 2),
    ]
    chunks = StructuredChunker(config).chunk(blocks)
    assert "甲" in chunks[0].text and "乙" in chunks[0].text
    assert chunks[-1].heading_path == ("异章",)


def test_table_splits_by_rows_and_repeats_header() -> None:
    block = DocumentBlock("table", "|类型|要求|\n|---|---|\n" + "\n".join(f"|类型{i}|说明{i}|" for i in range(30)), ("表格",))
    chunks = StructuredChunker(ChunkingConfig(target_tokens=30, hard_max_tokens=40, min_merge_tokens=5)).chunk([block])
    assert len(chunks) > 1
    assert all(chunk.text.startswith("|类型|要求|\n|---|---|") for chunk in chunks)
```

- [ ] **Step 2: Run tests and verify missing chunker failure**

Run: `Set-Location python_agent; python -m pytest tests/test_structured_chunker.py -v`

Expected: FAIL during import because `structured_chunker.py` is absent.

- [ ] **Step 3: Implement block-specific recursive splitting and grouping**

Implement these private operations in order:

```python
class StructuredChunker:
    def __init__(self, config: ChunkingConfig | None = None) -> None:
        self.config = config or ChunkingConfig()

    def chunk(self, blocks: Sequence[DocumentBlock]) -> list[StructuredChunk]:
        atomic = [piece for block in blocks for piece in self._split_oversized(block)]
        grouped = self._combine_adjacent(atomic)
        merged = self._merge_small(grouped)
        self._validate(merged)
        return merged
```

`_split_oversized` splits paragraph/quote on complete Chinese and Western sentence terminators, list on items, table on rows with repeated header, and code on lines; it calls `split_by_estimated_tokens` only for an oversized smallest unit. `_combine_adjacent` requires equal heading paths and adjacent page ranges. `_merge_small` tests both neighbors and selects the compatible result closest to `target_tokens` without exceeding `hard_max_tokens` or `hard_max_chars`. `_validate` rejects blank output and any chunk beyond either hard limit.

- [ ] **Step 4: Run chunker tests**

Run: `Set-Location python_agent; python -m pytest tests/test_structured_chunker.py -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit the chunker**

```powershell
git add python_agent/after_sales_agent/application/knowledge_ingestion/structured_chunker.py python_agent/tests/test_structured_chunker.py
git commit -m "feat: add recursive structured chunker"
```

---

### Task 5: Integrate The Python Parsing Facade And Metadata Classification

**Files:**

- Create: `python_agent/after_sales_agent/application/knowledge_ingestion/service.py`
- Modify: `python_agent/after_sales_agent/application/knowledge_ingestion/__init__.py`
- Modify: `python_agent/after_sales_agent/application/knowledge_ingestion_service.py`
- Modify: `python_agent/tests/test_knowledge_ingestion_service.py`

**Interfaces:**

- Consumes: all Python components from Tasks 1-4 and the existing `MetadataClassifier` protocol.
- Produces: the existing `KnowledgeParseError`, `DraftChunk`, `ParseResult`, and `KnowledgeIngestionService.parse(...)` public API.
- Adds `DraftChunk.metadata: dict[str, object]` with `page_start`, `page_end`, `content_types`, `estimated_tokens`, and `chunking_strategy`.

- [ ] **Step 1: Replace overlap expectations with structural metadata tests**

Replace `test_chunks_keep_sentence_boundary_overlap_and_top_level_sections_separate` with assertions that no fixed overlap is introduced, top-level sections remain separate, and every chunk carries the versioned structural metadata:

```python
def test_parse_uses_structured_chunks_without_fixed_overlap() -> None:
    result = KnowledgeIngestionService(classifier=FakeClassifier({})).parse(
        file_name="policy.md",
        content=("# 退款\n\n" + "完整段落。" * 300 + "\n\n# 换货\n\n换货正文。").encode(),
        knowledge_type="faq",
        allowed_metadata={"product_categories": [], "scenes": [], "intents": []},
    )
    assert len(result.chunks) > 1
    assert result.chunks[-1].heading_path == ["换货"]
    assert all(chunk.metadata["chunking_strategy"] == "structured_recursive_v1" for chunk in result.chunks)
    assert all(chunk.metadata["estimated_tokens"] <= 800 for chunk in result.chunks)


def test_markdown_and_txt_do_not_fake_page_one() -> None:
    for name in ("policy.md", "policy.txt"):
        result = KnowledgeIngestionService().parse(
            file_name=name,
            content=b"# Title\n\nBody" if name.endswith(".md") else b"1. Title\n\nBody",
            knowledge_type="faq",
            allowed_metadata={"product_categories": [], "scenes": [], "intents": []},
        )
        assert result.chunks[0].page_number is None
        assert result.chunks[0].metadata["page_end"] is None
```

- [ ] **Step 2: Run service tests and observe failures**

Run: `Set-Location python_agent; python -m pytest tests/test_knowledge_ingestion_service.py -v`

Expected: FAIL because `DraftChunk` has no `metadata` and old overlap behavior remains.

- [ ] **Step 3: Implement the facade and compatibility re-export**

Move service behavior into the package facade. Select a parser strictly by suffix, call `StructuredChunker`, and then classify final chunks using existing allowed-value intersection and review-required behavior. Map each `StructuredChunk` to:

```python
DraftChunk(
    chunk_index=index,
    heading_path=list(chunk.heading_path),
    page_number=chunk.page_start,
    text=chunk.text,
    product_categories=values["product_categories"],
    scenes=values["scenes"],
    intents=values["intents"],
    classification_source=source,
    classification_confidence=confidence,
    classification_reason=reason,
    review_required=review_required,
    metadata={
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "content_types": list(chunk.content_types),
        "estimated_tokens": chunk.estimated_tokens,
        "chunking_strategy": self._chunker.config.chunking_strategy,
    },
)
```

Keep `python_agent/after_sales_agent/application/knowledge_ingestion_service.py` as imports from `.knowledge_ingestion.service` so existing HTTP and tests do not change import paths.

After successful chunking, log one structured summary containing `source_format`, chunk count, maximum and average estimated tokens, distinct heading-path count, cross-page chunk count, and strategy version. Do not log chunk text or parsed document content.

- [ ] **Step 4: Run the complete Python ingestion suite**

Run: `Set-Location python_agent; python -m pytest tests/test_knowledge_ingestion_models.py tests/test_structured_document_parsers.py tests/test_structured_chunker.py tests/test_knowledge_ingestion_service.py -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit facade integration**

```powershell
git add python_agent/after_sales_agent/application/knowledge_ingestion python_agent/after_sales_agent/application/knowledge_ingestion_service.py python_agent/tests
git commit -m "feat: integrate structured knowledge parsing"
```

---

### Task 6: Persist Draft Structural Metadata

**Files:**

- Create: `sql/migrations/20260722_add_knowledge_chunk_draft_metadata.sql`
- Modify: `sql/pgvector_schema.sql`
- Modify: `src/main/java/com/ecommerce/aftersales/service/KnowledgeDraftService.java:127-143`
- Modify: `src/test/java/com/ecommerce/aftersales/service/KnowledgeDraftServiceTest.java`

**Interfaces:**

- Consumes: parser response field `chunks[].metadata` from Task 5.
- Produces: `knowledge_chunk_draft.metadata JSONB NOT NULL DEFAULT '{}'::jsonb` and Java insertion of a sanitized JSON object.

- [ ] **Step 1: Write the failing Java persistence test**

Add `metadata` to `parsedDraft()` and capture the insert SQL and arguments:

```java
import java.util.Arrays;
import java.util.stream.IntStream;

import static org.mockito.Mockito.atLeastOnce;

@Test
void parsedStructuralMetadataIsPersistedAsJsonb() {
    JdbcTemplate jdbc = mock(JdbcTemplate.class);
    when(jdbc.queryForList(anyString(), any(Object[].class))).thenReturn(List.of(Map.of("id", 42L)));
    when(jdbc.update(anyString(), any(Object[].class))).thenReturn(1);
    KnowledgeDraftService service = new KnowledgeDraftService(jdbc);

    service.replaceParsedDraft(42L, 7L, parsedDraft());

    ArgumentCaptor<String> sql = ArgumentCaptor.forClass(String.class);
    ArgumentCaptor<Object[]> args = ArgumentCaptor.forClass(Object[].class);
    verify(jdbc, atLeastOnce()).update(sql.capture(), args.capture());
    int insert = IntStream.range(0, sql.getAllValues().size())
            .filter(i -> sql.getAllValues().get(i).contains("INSERT INTO knowledge_chunk_draft"))
            .findFirst().orElseThrow();
    assertThat(sql.getAllValues().get(insert)).contains("metadata").contains("?::jsonb");
    assertThat(Arrays.stream(args.getAllValues().get(insert)).map(String::valueOf))
            .anyMatch(value -> value.contains("structured_recursive_v1") && value.contains("page_end"));
}
```

- [ ] **Step 2: Run the test and verify SQL-contract failure**

Run: `.\mvnw.cmd -Dtest=KnowledgeDraftServiceTest test`

Expected: FAIL because draft insert SQL has no metadata column.

- [ ] **Step 3: Add the formal migration and persist metadata**

Migration content:

```sql
ALTER TABLE knowledge_chunk_draft
    ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;
```

Add the same column to `sql/pgvector_schema.sql`. In `replaceParsedDraft`, accept only map-shaped parser metadata, serialize it with the existing object mapper helper, and insert it as `?::jsonb`. Non-map metadata becomes `{}`; parser-controlled top-level values are not copied into document metadata.

- [ ] **Step 4: Run draft-service tests**

Run: `.\mvnw.cmd -Dtest=KnowledgeDraftServiceTest test`

Expected: all `KnowledgeDraftServiceTest` tests PASS.

- [ ] **Step 5: Commit migration and persistence**

```powershell
git add sql/migrations/20260722_add_knowledge_chunk_draft_metadata.sql sql/pgvector_schema.sql src/main/java/com/ecommerce/aftersales/service/KnowledgeDraftService.java src/test/java/com/ecommerce/aftersales/service/KnowledgeDraftServiceTest.java
git commit -m "feat: persist chunk structure metadata"
```

---

### Task 7: Contextualized Embeddings, Metadata Precedence, And Unified Text Parsing

**Files:**

- Modify: `src/main/java/com/ecommerce/aftersales/service/KnowledgePublishService.java:66-188`
- Modify: `src/main/java/com/ecommerce/aftersales/service/KnowledgeIngestionAsyncService.java:92-458`
- Modify: `src/test/java/com/ecommerce/aftersales/service/KnowledgePublishServiceTest.java`
- Modify: `src/test/java/com/ecommerce/aftersales/service/KnowledgeIngestionAsyncServiceTest.java`

**Interfaces:**

- Consumes: draft `metadata`, authoritative document fields, and original `chunk_text`.
- Produces: `KnowledgePublishService.contextualizedText(Map<String,Object>)`, merged published metadata, original citations, and one Python parse path for text/file inputs.
- Embedding request `chunks` contains contextualized text; `commitPublishedRevision` still inserts original `chunk_text`.

- [ ] **Step 1: Write failing contextual embedding and citation tests**

In `KnowledgeIngestionAsyncServiceTest`, capture the `/embeddings` request from `publish` and assert its only chunk contains document title, heading path, page range, source file, and original body. In `KnowledgePublishServiceTest`, capture the `knowledge_chunk` insert and assert `chunk_text` remains exactly `body`, while `search_text` contains the context and JSON metadata contains `page_end` plus citation data.

```java
assertThat(embeddingChunks.getFirst())
        .contains("文档：平台售后退款规则")
        .contains("章节：退款政策 > 举证要求")
        .contains("位置：第 3-4 页")
        .contains("来源：policy.pdf / POLICY-2026")
        .endsWith("body");
assertThat(publishedChunkText).isEqualTo("body");
assertThat(publishedMetadata).contains("\"page_end\":4").contains("\"pageNumber\":3");
```

Add a text-import test verifying `processTextImport` posts a Base64 `.txt` payload to `/knowledge/parse`, calls `replaceParsedDraft`, and never executes `DELETE FROM knowledge_chunk`.

- [ ] **Step 2: Run focused Java tests and confirm failures**

Run: `.\mvnw.cmd -Dtest=KnowledgeIngestionAsyncServiceTest,KnowledgePublishServiceTest test`

Expected: FAIL because publish embeds raw `chunk_text`, draft metadata is not selected/merged, and text import still uses `splitContent`.

- [ ] **Step 3: Build authoritative deterministic context in Java**

Extend `targetDraft` to select `d.metadata chunk_metadata` and `kd.metadata document_metadata`. Implement helpers that parse map/JSON/PGobject safely and construct:

```text
文档：{title}
章节：{heading_path joined by " > "}
位置：第 {page_start[-page_end]} 页
来源：{file_name} / {source_code}
内容类型：{content_types joined by "、"}

{chunk_text}
```

Omit lines whose values are absent. In `publish`, pass `draft.stream().map(KnowledgePublishService::contextualizedText).toList()` to `generateEmbeddings`; preserve the original rows for `commitPublishedRevision`.

In `metadata(row)`, start with sanitized structural draft metadata, then overwrite authoritative document and revision fields, set `source_format` from the stored file name or text-ingestion mode, copy the human-confirmed `product_categories`, `scenes`, and `intents`, then write `citation.headingPath`, `citation.pageNumber`, `citation.pageStart`, and `citation.pageEnd`. Build `searchText(row)` from the same context plus confirmed classification labels. Never replace the existing business meaning of `source_type` with a file suffix.

- [ ] **Step 4: Remove the Java character-window write path**

Make `processTextImport` and text-document reprocessing call `processParsedFile(documentId, content.getBytes(UTF_8), "knowledge-" + documentId + ".txt", targetRevision)`. Preserve the claimed target revision and route failures through `markParseFailed`. Delete `processDocument`, `splitContent`, the direct `DELETE FROM knowledge_chunk` path, and the legacy `generateEmbeddings(documentId, document, chunks)` method used only by that path.

Do not add a fallback to fixed windows when Python parsing fails.

- [ ] **Step 5: Run focused Java tests**

Run: `.\mvnw.cmd -Dtest=KnowledgeIngestionAsyncServiceTest,KnowledgePublishServiceTest,KnowledgeDraftServiceTest test`

Expected: all selected tests PASS.

- [ ] **Step 6: Commit Java integration**

```powershell
git add src/main/java/com/ecommerce/aftersales/service/KnowledgePublishService.java src/main/java/com/ecommerce/aftersales/service/KnowledgeIngestionAsyncService.java src/test/java/com/ecommerce/aftersales/service/KnowledgePublishServiceTest.java src/test/java/com/ecommerce/aftersales/service/KnowledgeIngestionAsyncServiceTest.java
git commit -m "feat: contextualize knowledge embeddings"
```

---

### Task 8: Full Regression, Observability, And Contract Verification

**Files:**

- Modify: `python_agent/tests/test_knowledge_ingestion_service.py`
- Modify: `src/test/java/com/ecommerce/aftersales/service/KnowledgeIngestionAsyncServiceTest.java`
- Modify: `src/test/java/com/ecommerce/aftersales/service/KnowledgePublishServiceTest.java`

**Interfaces:**

- Verifies: stable parse error codes, chunk metrics without content logging, deterministic repeat output, revision safety, embedding count/dimension checks, and existing API compatibility.

- [ ] **Step 1: Add deterministic and metrics regression tests**

Parse the same Markdown, PDF, and TXT fixtures twice and compare `ParseResult.to_dict()` exactly. Capture Python logs and assert they contain format, chunk count, maximum estimated tokens, heading count, cross-page chunk count, and strategy version, but not the fixture body. Preserve existing tests for invalid Base64, internal-token authentication, encrypted PDF, missing text layer, stale draft target, and embedding dimension/count.

- [ ] **Step 2: Run Python regression suite**

Run: `Set-Location python_agent; python -m pytest tests/test_knowledge_ingestion_models.py tests/test_structured_document_parsers.py tests/test_structured_chunker.py tests/test_knowledge_ingestion_service.py -v`

Expected: all tests PASS with no network or real LLM calls.

- [ ] **Step 3: Run Java knowledge regression suite**

Run: `.\mvnw.cmd -Dtest=KnowledgePublishServiceTest,KnowledgePublishIntegrationTest,KnowledgeIngestionAsyncServiceTest,KnowledgeDraftServiceTest,KnowledgeManagementControllerTest,KnowledgeServiceTest test`

Expected: all selected tests PASS; API IDs remain textual where exposed.

- [ ] **Step 4: Run static and diff checks**

Run: `Set-Location python_agent; python -m compileall -q after_sales_agent`

Expected: exit code 0.

Run: `Set-Location ..; git diff --check`

Expected: exit code 0 and no whitespace errors.

- [ ] **Step 5: Confirm no obsolete fixed splitter remains**

Run: `rg -n "splitContent|overlapSize|maxChunkSize|buffer\[-overlap_chars" src/main/java python_agent/after_sales_agent`

Expected: no matches in production ingestion code.

- [ ] **Step 6: Commit final regression coverage**

```powershell
git add python_agent/tests/test_knowledge_ingestion_service.py src/test/java/com/ecommerce/aftersales/service/KnowledgeIngestionAsyncServiceTest.java src/test/java/com/ecommerce/aftersales/service/KnowledgePublishServiceTest.java
git commit -m "test: cover structured knowledge ingestion"
```

## Manual Post-Implementation Check

Do not automatically apply the migration to the current database or reindex published data. After code review, explicitly apply `sql/migrations/20260722_add_knowledge_chunk_draft_metadata.sql` to database `after_sales_rag`, verify the column with `information_schema.columns`, then import one disposable Markdown, TXT, and text-layer PDF through the admin flow. Confirm the draft UI shows stable original text, PostgreSQL draft metadata contains source structure, embedding logs report the strategy without document content, and the active published revision remains unchanged until explicit publish.
