from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ..providers.llm_client import get_llm_client
from ..tools import AgentToolRegistry
from .context import AgentContext
from .router import AgentRouter
from .skill_registry import AgentSkillRegistry
from .state import AgentTaskType
from .workflows import ConsultationWorkflow, FormalReviewWorkflow


class ConsultationRuntime(Protocol):
    def handle(
        self,
        payload: dict[str, Any],
        trace_recorder: Any | None = None,
    ) -> dict[str, Any]: ...


class FormalReviewRuntime(Protocol):
    def start(
        self,
        payload: dict[str, Any],
        trace_recorder: Any | None = None,
    ) -> dict[str, Any]: ...

    def resume(
        self,
        review_id: str,
        resume_signal: dict[str, Any],
        trace_recorder: Any | None = None,
    ) -> dict[str, Any]: ...


@dataclass
class AfterSalesAgent:
    """唯一自主售后 Agent；事件类型明确时直接调度对应 Skill。"""

    tools: Any = field(default_factory=AgentToolRegistry)
    llm: Any = field(default_factory=get_llm_client)
    skill_registry: AgentSkillRegistry = field(default_factory=AgentSkillRegistry)
    router: AgentRouter = field(default_factory=AgentRouter)
    checkpointer: Any | None = None
    consultation_workflow: ConsultationRuntime | None = None
    formal_review_workflow: FormalReviewRuntime | None = None

    def __post_init__(self) -> None:
        if self.consultation_workflow is None:
            self.consultation_workflow = ConsultationWorkflow(
                tools=self.tools,
                llm=self.llm,
                skills=self.skill_registry,
            )

    def handle_chat(
        self,
        payload: dict[str, Any],
        trace_recorder: Any | None = None,
    ) -> dict[str, Any]:
        if self.consultation_workflow is None:
            raise RuntimeError("consultation workflow is not configured")
        return self.consultation_workflow.handle(payload, trace_recorder)

    def start_formal_review(
        self,
        payload: dict[str, Any],
        trace_recorder: Any | None = None,
    ) -> dict[str, Any]:
        if self.formal_review_workflow is None:
            self.formal_review_workflow = FormalReviewWorkflow(
                tools=self.tools,
                llm=self.llm,
                skills=self.skill_registry,
                checkpointer=self.checkpointer,
            )
        return self.formal_review_workflow.start(payload, trace_recorder)

    def resume_formal_review(
        self,
        review_id: str,
        resume_signal: dict[str, Any],
        trace_recorder: Any | None = None,
    ) -> dict[str, Any]:
        if self.formal_review_workflow is None:
            self.formal_review_workflow = FormalReviewWorkflow(
                tools=self.tools,
                llm=self.llm,
                skills=self.skill_registry,
                checkpointer=self.checkpointer,
            )
        return self.formal_review_workflow.resume(
            review_id,
            resume_signal,
            trace_recorder,
        )

    def handle(
        self,
        payload: dict[str, Any],
        trace_recorder: Any | None = None,
    ) -> dict[str, Any]:
        context = AgentContext.from_payload(payload, trace_recorder)
        state = self.router.route(payload, context)
        if state.task_type is AgentTaskType.FORMAL_REVIEW:
            return self.start_formal_review(state.payload, trace_recorder)
        return self.handle_chat(state.payload, trace_recorder)
