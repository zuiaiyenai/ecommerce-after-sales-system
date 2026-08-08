from __future__ import annotations

from dataclasses import dataclass


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
        object.__setattr__(self, "heading_path", tuple(self.heading_path))
        if not self.text.strip():
            raise ValueError("document block text must not be blank")
        if (self.page_start is None) != (self.page_end is None):
            raise ValueError("page range must be entirely present or absent")
        if self.page_start is not None and (
            self.page_start < 1 or self.page_end < self.page_start
        ):
            raise ValueError("invalid page range")


@dataclass(frozen=True)
class StructuredChunk:
    text: str
    heading_path: tuple[str, ...]
    page_start: int | None
    page_end: int | None
    content_types: tuple[str, ...]
    estimated_tokens: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "heading_path", tuple(self.heading_path))
        object.__setattr__(self, "content_types", tuple(self.content_types))
