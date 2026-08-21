from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AgentContext:
    source: str = "http"
    trace_recorder: Any | None = None

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        trace_recorder: Any | None = None,
    ) -> "AgentContext":
        client_context = payload.get("client_context")
        source = (
            str(client_context.get("source") or "http")
            if isinstance(client_context, dict)
            else "http"
        )
        return cls(source=source.strip().lower(), trace_recorder=trace_recorder)

