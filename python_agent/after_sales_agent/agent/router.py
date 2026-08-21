from __future__ import annotations

from .context import AgentContext
from .state import AgentState, AgentTaskType


class AgentRouter:
    """Deterministically routes known transport events; no LLM call occurs here."""

    _FORMAL_REVIEW_SOURCES = {"kafka", "review-consumer"}

    def route(
        self,
        payload: dict[str, object],
        context: AgentContext,
    ) -> AgentState:
        explicit_type = str(payload.get("task_type") or "").strip().lower()
        is_formal_review = (
            explicit_type == AgentTaskType.FORMAL_REVIEW.value
            or context.source in self._FORMAL_REVIEW_SOURCES
        )
        return AgentState(
            task_type=(
                AgentTaskType.FORMAL_REVIEW
                if is_formal_review
                else AgentTaskType.CONSULTATION
            ),
            payload=dict(payload),
        )

