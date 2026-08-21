from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional, Protocol, TypedDict

from langgraph.graph import END, StateGraph

from .evaluators import (
    EvidenceReviewPort,
    EvidenceEvaluator,
    PolicyRetrievalPort,
    PolicyEvaluator,
)
from .contracts import (
    EvidenceAssessment,
    EvidenceTask,
    PolicyAssessment,
    PolicyTask,
)
from ....application.rag_query_rewrite import RagQueryRewriteService, RagRewriteError
from ....application.rag_retrieval_policy import RagRetrievalPolicy
from ....tools import ToolResult


class PolicyWorkflowRuntime(Protocol):
    def handle(self, task: PolicyTask) -> PolicyAssessment:
        ...


class EvidenceWorkflowRuntime(Protocol):
    def handle(self, task: EvidenceTask) -> EvidenceAssessment:
        ...


class PolicyWorkflowState(TypedDict, total=False):
    task: PolicyTask
    retrieval_result: ToolResult
    assessment: PolicyAssessment
    retrieval_observation: dict[str, Any]
    rewrite_queries: tuple[str, ...]
    rewrite_completed: bool
    retrieval_attempts: int
    failure_category: Optional[str]
    steps: int


class EvidenceWorkflowState(TypedDict, total=False):
    task: EvidenceTask
    image_review_result: ToolResult
    assessment: EvidenceAssessment
    failure_category: Optional[str]
    steps: int


@dataclass
class PolicyWorkflow:
    port: PolicyRetrievalPort
    rewrite_service: Optional[RagQueryRewriteService] = None
    _evaluator: PolicyEvaluator = field(init=False, repr=False)
    _retrieval_policy: RagRetrievalPolicy = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._evaluator = PolicyEvaluator(self.port)
        self._retrieval_policy = RagRetrievalPolicy()
        graph = StateGraph(PolicyWorkflowState)
        graph.add_node("receive_task", self.receive_task)
        graph.add_node("retrieve_policy", self.retrieve_policy)
        graph.add_node("observe_policy_result", self.observe_policy_result)
        graph.add_node("rewrite_policy_query", self.rewrite_policy_query)
        graph.add_node("retrieve_policy_multi", self.retrieve_policy_multi)
        graph.add_node(
            "observe_rewritten_policy_result",
            self.observe_policy_result,
        )
        graph.add_node("finalize_policy_assessment", self.assess_policy)
        graph.set_entry_point("receive_task")
        graph.add_conditional_edges(
            "receive_task",
            self.route_after_receive,
            {
                "retrieve_policy": "retrieve_policy",
                "finalize_policy_assessment": "finalize_policy_assessment",
            },
        )
        graph.add_edge("retrieve_policy", "observe_policy_result")
        graph.add_conditional_edges(
            "observe_policy_result",
            self.decide_retrieval_next,
            {
                "rewrite_policy_query": "rewrite_policy_query",
                "finalize_policy_assessment": "finalize_policy_assessment",
            },
        )
        graph.add_conditional_edges(
            "rewrite_policy_query",
            self.route_after_rewrite,
            {
                "retrieve_policy_multi": "retrieve_policy_multi",
                "finalize_policy_assessment": "finalize_policy_assessment",
            },
        )
        graph.add_edge(
            "retrieve_policy_multi",
            "observe_rewritten_policy_result",
        )
        graph.add_edge(
            "observe_rewritten_policy_result",
            "finalize_policy_assessment",
        )
        graph.add_edge("finalize_policy_assessment", END)
        self.graph = graph.compile()

    def handle(self, task: PolicyTask) -> PolicyAssessment:
        final = self.graph.invoke(
            {
                "task": task,
                "failure_category": None,
                "rewrite_queries": (),
                "rewrite_completed": False,
                "retrieval_attempts": 0,
                "steps": 0,
            }
        )
        assessment = final.get("assessment")
        if not isinstance(assessment, PolicyAssessment):
            raise RuntimeError("policy workflow did not produce an assessment")
        return assessment

    @staticmethod
    def receive_task(state: PolicyWorkflowState) -> PolicyWorkflowState:
        task = state["task"]
        missing = [
            name
            for name, value in (
                ("task_id", task.task_id),
                ("review_request_id", task.review_request_id),
                ("ticket_id", task.ticket_id),
                ("context_version", task.context_version),
                ("user_id", task.user_id),
                ("query", task.query),
                ("skill_name", task.skill_name),
                ("skill_version", task.skill_version),
                ("skill_instructions", task.skill_instructions),
            )
            if not str(value or "").strip()
        ]
        return {
            "failure_category": (
                f"invalid_policy_task:{','.join(missing)}" if missing else None
            ),
            "steps": 1,
        }

    def retrieve_policy(
        self,
        state: PolicyWorkflowState,
    ) -> PolicyWorkflowState:
        return {
            "retrieval_result": self._evaluator.retrieve(state["task"]),
            "retrieval_attempts": 1,
            "steps": int(state.get("steps") or 0) + 1,
        }

    def observe_policy_result(
        self,
        state: PolicyWorkflowState,
    ) -> PolicyWorkflowState:
        result = state.get("retrieval_result")
        if result is None:
            result = ToolResult(
                ok=False,
                name="retrieve_knowledge",
                error="policy retrieval result is missing",
                error_code="MISSING_SUBAGENT_RESULT",
                error_category="tool_error",
            )
        assessment = self._evaluator.assess(state["task"], result)
        data = result.data if result.ok and isinstance(result.data, dict) else {}
        infrastructure_failure = (
            not result.ok
            or self._retrieval_policy.is_infrastructure_failure(data)
        )
        return {
            "assessment": assessment,
            "retrieval_observation": {
                "trusted_policy_eligible": assessment.trusted_policy_eligible,
                "retrieval_mode": assessment.retrieval_mode,
                "infrastructure_failure": infrastructure_failure,
                "attempt": int(state.get("retrieval_attempts") or 0),
            },
            "failure_category": (
                result.error_category if not result.ok else None
            ),
            "steps": int(state.get("steps") or 0) + 1,
        }

    def rewrite_policy_query(
        self,
        state: PolicyWorkflowState,
    ) -> PolicyWorkflowState:
        task = state["task"]
        result = state.get("retrieval_result")
        queries: tuple[str, ...] = ()
        failure = state.get("failure_category")
        if (
            self.rewrite_service is not None
            and result is not None
            and result.ok
            and isinstance(result.data, dict)
        ):
            try:
                decision = self.rewrite_service.evaluate(
                    user_question=task.issue,
                    task=(
                        "评估正式售后审核所需的可信政策覆盖，只改写检索问题，"
                        "不作业务决定。\n"
                        f"Active skill ({task.skill_name}@{task.skill_version}):\n"
                        f"{task.skill_instructions}"
                    ),
                    known_facts={
                        "product_name": task.product_name,
                        "product_category": task.product_category,
                        "issue_type": task.issue,
                        "after_sales_type": task.after_sales_type,
                        "scene": "formal_review",
                        "intent": "trusted_policy_retrieval",
                    },
                    original_query=task.query,
                    previous_queries=[],
                    require_trusted_policy=True,
                    retrieval_result=result.data,
                    allow_rewrite=True,
                )
                if not decision.sufficient:
                    queries = tuple(
                        candidate.query for candidate in decision.queries
                        if str(candidate.query or "").strip()
                    )[:3]
            except RagRewriteError:
                failure = "rag_query_rewrite_failed"
        return {
            "rewrite_queries": queries,
            "rewrite_completed": True,
            "failure_category": failure,
            "steps": int(state.get("steps") or 0) + 1,
        }

    def retrieve_policy_multi(
        self,
        state: PolicyWorkflowState,
    ) -> PolicyWorkflowState:
        return {
            "retrieval_result": self._evaluator.retrieve_multi(
                state["task"],
                state.get("rewrite_queries") or (),
            ),
            "retrieval_attempts": int(state.get("retrieval_attempts") or 0) + 1,
            "steps": int(state.get("steps") or 0) + 1,
        }

    def assess_policy(
        self,
        state: PolicyWorkflowState,
    ) -> PolicyWorkflowState:
        assessment = state.get("assessment")
        failure = state.get("failure_category")
        if assessment is None:
            result = ToolResult(
                ok=False,
                name="retrieve_knowledge",
                error=failure or "policy retrieval result is missing",
                error_code=(
                    "INVALID_SUBAGENT_TASK"
                    if failure
                    else "MISSING_SUBAGENT_RESULT"
                ),
                error_category="validation" if failure else "tool_error",
            )
            assessment = self._evaluator.assess(state["task"], result)
        return {
            "assessment": assessment,
            "failure_category": failure,
            "steps": int(state.get("steps") or 0) + 1,
        }

    def decide_retrieval_next(
        self,
        state: PolicyWorkflowState,
    ) -> Literal["rewrite_policy_query", "finalize_policy_assessment"]:
        observation = state.get("retrieval_observation") or {}
        if (
            self.rewrite_service is not None
            and observation.get("trusted_policy_eligible") is not True
            and observation.get("infrastructure_failure") is not True
            and not state.get("rewrite_completed")
            and int(state.get("retrieval_attempts") or 0) < 2
        ):
            return "rewrite_policy_query"
        return "finalize_policy_assessment"

    @staticmethod
    def route_after_rewrite(
        state: PolicyWorkflowState,
    ) -> Literal["retrieve_policy_multi", "finalize_policy_assessment"]:
        return (
            "retrieve_policy_multi"
            if state.get("rewrite_queries")
            else "finalize_policy_assessment"
        )

    @staticmethod
    def route_after_receive(
        state: PolicyWorkflowState,
    ) -> Literal["retrieve_policy", "finalize_policy_assessment"]:
        return (
            "finalize_policy_assessment"
            if state.get("failure_category")
            else "retrieve_policy"
        )


@dataclass
class EvidenceWorkflow:
    port: EvidenceReviewPort
    _evaluator: EvidenceEvaluator = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._evaluator = EvidenceEvaluator(self.port)
        graph = StateGraph(EvidenceWorkflowState)
        graph.add_node("receive_task", self.receive_task)
        graph.add_node("review_evidence", self.review_evidence)
        graph.add_node("assess_evidence", self.assess_evidence)
        graph.set_entry_point("receive_task")
        graph.add_conditional_edges(
            "receive_task",
            self.route_after_receive,
            {
                "review_evidence": "review_evidence",
                "assess_evidence": "assess_evidence",
            },
        )
        graph.add_edge("review_evidence", "assess_evidence")
        graph.add_edge("assess_evidence", END)
        self.graph = graph.compile()

    def handle(self, task: EvidenceTask) -> EvidenceAssessment:
        final = self.graph.invoke(
            {
                "task": task,
                "failure_category": None,
                "steps": 0,
            }
        )
        assessment = final.get("assessment")
        if not isinstance(assessment, EvidenceAssessment):
            raise RuntimeError("evidence workflow did not produce an assessment")
        return assessment

    @staticmethod
    def receive_task(state: EvidenceWorkflowState) -> EvidenceWorkflowState:
        task = state["task"]
        missing = [
            name
            for name, value in (
                ("task_id", task.task_id),
                ("review_request_id", task.review_request_id),
                ("ticket_id", task.ticket_id),
                ("context_version", task.context_version),
                ("user_id", task.user_id),
                ("order_id", task.order_id),
                ("skill_name", task.skill_name),
                ("skill_version", task.skill_version),
                ("skill_instructions", task.skill_instructions),
            )
            if not str(value or "").strip()
        ]
        return {
            "failure_category": (
                f"invalid_evidence_task:{','.join(missing)}" if missing else None
            ),
            "steps": 1,
        }

    def review_evidence(
        self,
        state: EvidenceWorkflowState,
    ) -> EvidenceWorkflowState:
        return {
            "image_review_result": self._evaluator.review(state["task"]),
            "steps": int(state.get("steps") or 0) + 1,
        }

    def assess_evidence(
        self,
        state: EvidenceWorkflowState,
    ) -> EvidenceWorkflowState:
        failure = state.get("failure_category")
        result = state.get("image_review_result")
        if failure:
            result = ToolResult(
                ok=False,
                name="review_images",
                error=failure,
                error_code="INVALID_SUBAGENT_TASK",
                error_category="validation",
            )
        assessment = self._evaluator.assess(state["task"], result)
        return {
            "assessment": assessment,
            "failure_category": (
                failure
                or (
                    result.error_category
                    if result is not None and not result.ok
                    else None
                )
            ),
            "steps": int(state.get("steps") or 0) + 1,
        }

    @staticmethod
    def route_after_receive(
        state: EvidenceWorkflowState,
    ) -> Literal["review_evidence", "assess_evidence"]:
        if state.get("failure_category") or not state["task"].attachments:
            return "assess_evidence"
        return "review_evidence"
