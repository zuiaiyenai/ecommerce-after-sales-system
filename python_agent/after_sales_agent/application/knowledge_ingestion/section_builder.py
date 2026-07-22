from __future__ import annotations

import re


_CHINESE_NUMBER = "0-9零〇一二三四五六七八九十百千万两"
_CHAPTER_OR_SECTION = re.compile(
    rf"^\s*第[{_CHINESE_NUMBER}]+(?P<kind>章|节)\s*(?P<title>\S.*?)\s*$"
)
_CHINESE_ENUMERATION = re.compile(
    rf"^\s*[{_CHINESE_NUMBER}]+、\s*(?P<title>\S.*?)\s*$"
)
_DECIMAL_NUMBERING = re.compile(
    r"^\s*(?P<number>\d+(?:\.\d+)+)\s+(?P<title>\S.*?)\s*$"
)


class HeadingStack:
    def __init__(self) -> None:
        self._items: list[tuple[int, str]] = []

    def enter(self, level: int, title: str) -> tuple[str, ...]:
        clean = title.strip()
        self._items = [item for item in self._items if item[0] < level]
        self._items.append((level, clean))
        return self.path

    @property
    def path(self) -> tuple[str, ...]:
        return tuple(value for _, value in self._items)


def numbered_heading(line: str) -> tuple[int, str] | None:
    """Return an explicit numbered heading without guessing from short lines."""
    match = _CHAPTER_OR_SECTION.match(line)
    if match:
        level = 1 if match.group("kind") == "章" else 2
        return level, match.group("title").strip()

    match = _CHINESE_ENUMERATION.match(line)
    if match:
        return 1, match.group("title").strip()

    match = _DECIMAL_NUMBERING.match(line)
    if match:
        return len(match.group("number").split(".")), match.group("title").strip()

    return None
