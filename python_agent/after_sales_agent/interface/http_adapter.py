from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class ChatAgent(Protocol):
    def handle_chat(
        self,
        payload: dict[str, Any],
        trace_recorder: Any | None = None,
    ) -> dict[str, Any]: ...


@dataclass
class AfterSalesHttpAdapter:
    """Maps HTTP use cases to the single Agent without owning business logic."""

    agent: ChatAgent

    def handle_chat(
        self,
        payload: dict[str, Any],
        trace_recorder: Any | None = None,
    ) -> dict[str, Any]:
        return self.agent.handle_chat(payload, trace_recorder)

