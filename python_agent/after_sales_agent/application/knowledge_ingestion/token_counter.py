from __future__ import annotations

import unicodedata


def estimate_tokens(text: str) -> int:
    """Count CJK characters, words, and punctuation after NFKC normalization."""
    normalized = unicodedata.normalize("NFKC", text)
    tokens = 0
    in_word = False

    for character in normalized:
        if character.isspace():
            in_word = False
        elif _is_cjk(character):
            tokens += 1
            in_word = False
        elif character.isalnum() or character == "_":
            if not in_word:
                tokens += 1
                in_word = True
        else:
            tokens += 1
            in_word = False

    return tokens


def split_by_estimated_tokens(
    text: str,
    hard_max_tokens: int,
    hard_max_chars: int = 6400,
) -> list[str]:
    """Split source text without changing its characters or their order."""
    if hard_max_tokens <= 0:
        raise ValueError("hard_max_tokens must be positive")
    if hard_max_chars <= 0:
        raise ValueError("hard_max_chars must be positive")
    if not text:
        return []

    parts: list[str] = []
    current: list[str] = []
    current_tokens = 0
    current_chars = 0

    def flush() -> None:
        nonlocal current, current_tokens, current_chars
        if current:
            parts.append("".join(current))
            current = []
            current_tokens = 0
            current_chars = 0

    for unit, unit_tokens in _source_units(text):
        if len(unit) > hard_max_chars:
            flush()
            for start in range(0, len(unit), hard_max_chars):
                parts.append(unit[start : start + hard_max_chars])
            continue

        exceeds_tokens = current and current_tokens + unit_tokens > hard_max_tokens
        exceeds_chars = current and current_chars + len(unit) > hard_max_chars
        if exceeds_tokens or exceeds_chars:
            flush()

        current.append(unit)
        current_tokens += unit_tokens
        current_chars += len(unit)

    flush()
    return parts


def _source_units(text: str) -> list[tuple[str, int]]:
    """Create source-preserving lexical units with normalized token costs."""
    units: list[tuple[str, int]] = []
    pending = ""
    pending_kind: str | None = None

    def emit_pending() -> None:
        nonlocal pending, pending_kind
        if pending:
            units.append((pending, estimate_tokens(pending)))
            pending = ""
            pending_kind = None

    for character in text:
        kind = _source_character_kind(character)
        if kind in {"word", "whitespace"} and kind == pending_kind:
            pending += character
        else:
            emit_pending()
            if kind in {"word", "whitespace"}:
                pending = character
                pending_kind = kind
            else:
                units.append((character, estimate_tokens(character)))
    emit_pending()
    return units


def _source_character_kind(character: str) -> str:
    normalized = unicodedata.normalize("NFKC", character)
    if normalized and all(item.isspace() for item in normalized):
        return "whitespace"
    if normalized and all(
        (item.isalnum() or item == "_") and not _is_cjk(item) for item in normalized
    ):
        return "word"
    return "other"


def _is_cjk(character: str) -> bool:
    codepoint = ord(character)
    return (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
        or 0x20000 <= codepoint <= 0x2EBEF
        or 0x30000 <= codepoint <= 0x323AF
    )
