from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from after_sales_agent.application.knowledge_ingestion.models import (
    ChunkingConfig,
    DocumentBlock,
    StructuredChunk,
)
from after_sales_agent.application.knowledge_ingestion.token_counter import (
    estimate_tokens,
    split_by_estimated_tokens,
)


_SENTENCE_TERMINATORS = frozenset(".?!;:。！？；：")


@dataclass(frozen=True)
class _Piece:
    block: DocumentBlock
    leading_separator: str = ""
    combineable: bool = True


@dataclass(frozen=True)
class _Candidate:
    pieces: tuple[_Piece, ...]

    @property
    def heading_path(self) -> tuple[str, ...]:
        return self.pieces[0].block.heading_path

    @property
    def page_start(self) -> int | None:
        return self.pieces[0].block.page_start

    @property
    def page_end(self) -> int | None:
        return self.pieces[-1].block.page_end

    @property
    def text(self) -> str:
        return self.pieces[0].block.text + "".join(
            piece.leading_separator + piece.block.text for piece in self.pieces[1:]
        )

    @property
    def content_types(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(piece.block.block_type for piece in self.pieces))


class StructuredChunker:
    """Split parsed document blocks while retaining their structural context."""

    def __init__(self, config: ChunkingConfig | None = None) -> None:
        self.config = config or ChunkingConfig()

    def chunk(self, blocks: Sequence[DocumentBlock]) -> list[StructuredChunk]:
        atomic: list[_Piece] = []
        for index, block in enumerate(blocks):
            pieces = self._split_oversized(block)
            if index and pieces:
                pieces[0] = _Piece(
                    pieces[0].block,
                    leading_separator="\n\n",
                    combineable=pieces[0].combineable,
                )
            atomic.extend(pieces)

        grouped = self._combine_adjacent(atomic)
        merged = self._merge_small(grouped)
        chunks = [self._to_structured_chunk(candidate) for candidate in merged]
        self._validate(chunks)
        return chunks

    def _split_oversized(self, block: DocumentBlock) -> list[_Piece]:
        if not self._exceeds_hard_limit(block.text):
            return [_Piece(block, combineable=block.block_type != "table")]

        if block.block_type == "table":
            return self._split_table(block)

        units = self._smallest_units(block)
        pieces: list[_Piece] = []
        for unit in units:
            if self._exceeds_hard_limit(unit):
                units_to_emit = split_by_estimated_tokens(
                    unit,
                    self.config.hard_max_tokens,
                    self.config.hard_max_chars,
                )
            else:
                units_to_emit = [unit]
            pieces.extend(
                _Piece(
                    DocumentBlock(
                        block.block_type,
                        emitted,
                        block.heading_path,
                        block.page_start,
                        block.page_end,
                        block.splittable,
                    )
                )
                for emitted in units_to_emit
                if emitted.strip()
            )
        return pieces

    def _smallest_units(self, block: DocumentBlock) -> list[str]:
        if block.block_type in {"paragraph", "quote"}:
            return _split_sentences(block.text)
        if block.block_type in {"list", "code"}:
            return block.text.splitlines(keepends=True) or [block.text]
        return [block.text]

    def _split_table(self, block: DocumentBlock) -> list[_Piece]:
        lines = block.text.splitlines(keepends=True)
        if len(lines) < 3:
            return self._fallback_piece_split(block)

        header = "".join(lines[:2])
        rows = lines[2:]
        if self._exceeds_hard_limit(header):
            return self._fallback_piece_split(block)

        limit = min(self.config.target_tokens, self.config.hard_max_tokens)
        groups: list[str] = []
        current = header
        for row in rows:
            candidate = current + row
            if current != header and self._exceeds_limit(candidate, limit):
                groups.append(current)
                current = header

            if self._exceeds_hard_limit(current + row):
                row_parts = split_by_estimated_tokens(
                    row,
                    self.config.hard_max_tokens,
                    self.config.hard_max_chars,
                )
                for row_part in row_parts:
                    if self._exceeds_hard_limit(header + row_part):
                        return self._fallback_piece_split(block)
                    groups.append(header + row_part)
                current = header
            else:
                current += row

        if current != header:
            groups.append(current)

        return [
            _Piece(
                DocumentBlock(
                    "table",
                    group,
                    block.heading_path,
                    block.page_start,
                    block.page_end,
                    block.splittable,
                ),
                combineable=False,
            )
            for group in groups
        ]

    def _fallback_piece_split(self, block: DocumentBlock) -> list[_Piece]:
        return [
            _Piece(
                DocumentBlock(
                    block.block_type,
                    part,
                    block.heading_path,
                    block.page_start,
                    block.page_end,
                    block.splittable,
                ),
                combineable=False,
            )
            for part in split_by_estimated_tokens(
                block.text,
                self.config.hard_max_tokens,
                self.config.hard_max_chars,
            )
            if part.strip()
        ]

    def _combine_adjacent(self, pieces: Sequence[_Piece]) -> list[_Candidate]:
        candidates: list[_Candidate] = []
        for piece in pieces:
            candidate = _Candidate((piece,))
            if candidates and self._can_combine(candidates[-1], candidate):
                candidates[-1] = _Candidate(candidates[-1].pieces + candidate.pieces)
            else:
                candidates.append(candidate)
        return candidates

    def _merge_small(self, candidates: list[_Candidate]) -> list[_Candidate]:
        merged = list(candidates)
        while True:
            selected: tuple[int, int, _Candidate] | None = None
            for index, candidate in enumerate(merged):
                if estimate_tokens(candidate.text) >= self.config.min_merge_tokens:
                    continue
                options: list[tuple[int, int, _Candidate]] = []
                for neighbor_index in (index - 1, index + 1):
                    if not 0 <= neighbor_index < len(merged):
                        continue
                    left_index, right_index = sorted((index, neighbor_index))
                    combined = _Candidate(
                        merged[left_index].pieces + merged[right_index].pieces
                    )
                    if self._can_merge_small(merged[left_index], merged[right_index]):
                        distance = abs(estimate_tokens(combined.text) - self.config.target_tokens)
                        options.append((distance, left_index, combined))
                if options:
                    selected = min(options, key=lambda option: (option[0], option[1]))
                    break
            if selected is None:
                return merged

            _, left_index, combined = selected
            merged[left_index : left_index + 2] = [combined]

    def _can_combine(self, left: _Candidate, right: _Candidate) -> bool:
        return self._has_compatible_context(left, right) and not self._exceeds_limit(
            _Candidate(left.pieces + right.pieces).text,
            self.config.target_tokens,
        )

    def _can_merge_small(self, left: _Candidate, right: _Candidate) -> bool:
        return self._has_compatible_context(left, right) and not self._exceeds_hard_limit(
            _Candidate(left.pieces + right.pieces).text
        )

    def _has_compatible_context(self, left: _Candidate, right: _Candidate) -> bool:
        if not all(piece.combineable for piece in left.pieces + right.pieces):
            return False
        if left.heading_path != right.heading_path:
            return False
        return _adjacent_page_ranges(left.page_start, left.page_end, right.page_start, right.page_end)

    def _to_structured_chunk(self, candidate: _Candidate) -> StructuredChunk:
        return StructuredChunk(
            text=candidate.text,
            heading_path=candidate.heading_path,
            page_start=candidate.page_start,
            page_end=candidate.page_end,
            content_types=candidate.content_types,
            estimated_tokens=estimate_tokens(candidate.text),
        )

    def _validate(self, chunks: Sequence[StructuredChunk]) -> None:
        for chunk in chunks:
            if not chunk.text.strip():
                raise ValueError("structured chunk text must not be blank")
            if self._exceeds_hard_limit(chunk.text):
                raise ValueError("structured chunk exceeds hard limit")

    def _exceeds_hard_limit(self, text: str) -> bool:
        return self._exceeds_limit(text, self.config.hard_max_tokens)

    def _exceeds_limit(self, text: str, token_limit: int) -> bool:
        return estimate_tokens(text) > token_limit or len(text) > self.config.hard_max_chars


def _split_sentences(text: str) -> list[str]:
    sentences: list[str] = []
    current: list[str] = []
    for character in text:
        current.append(character)
        if character in _SENTENCE_TERMINATORS:
            sentences.append("".join(current))
            current = []
    if current:
        if sentences:
            sentences[-1] += "".join(current)
        else:
            sentences.append("".join(current))
    return sentences


def _adjacent_page_ranges(
    left_start: int | None,
    left_end: int | None,
    right_start: int | None,
    right_end: int | None,
) -> bool:
    if left_start is None or left_end is None:
        return right_start is None and right_end is None
    if right_start is None or right_end is None:
        return False
    return right_start <= left_end + 1
