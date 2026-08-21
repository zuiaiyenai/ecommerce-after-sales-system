from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    name: str
    data: Any = None
    error: str | None = None
    error_code: str | None = None
    error_category: str | None = None
    retryable: bool = False

