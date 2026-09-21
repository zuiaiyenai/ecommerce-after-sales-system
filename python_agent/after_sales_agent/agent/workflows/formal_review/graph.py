from __future__ import annotations

from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from dataclasses import dataclass, field
import hashlib
import os
from typing import Any, Literal, Optional, Protocol, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command, interrupt

from .contracts import (
    EvidenceAssessment,
    EvidenceTask,
    PolicyAssessment,
    PolicyTask,
    ReviewProposal,
    ReviewWorkflowPlan,
    TrustedCaseContext,
)
from .evaluators import is_core_evidence_requirement
from .workflows import (
    EvidenceWorkflow,
    EvidenceWorkflowRuntime,
    PolicyWorkflow,
    PolicyWorkflowRuntime,
)
from .tool_ports import (
    RegistryEvidenceReviewPort,
    RegistryPolicyRetrievalPort,
)
from .synthesis import ComplexReviewSynthesizer
from .confidence import apply_deterministic_confidence
from .sop import (
    ESCALATED_REVIEW_MODE,
    SOP_REVIEW_MODE,
    FormalReviewSop,
)
from ....tools import AgentToolRegistry, ToolResult
from ...skill_registry import AgentSkill, AgentSkillRegistry
from ....application.rag_query_rewrite import RagQueryRewriteService
from ....infrastructure.agent_metrics import AGENT_RUNTIME_METRICS
from ....infrastructure.request_tracing import TraceRecorder, bind_trace_id, current_trace_id
from ....providers.llm_client import get_llm_client


class ReviewTools(Protocol):
    def call(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        ...


class ReviewLlm(Protocol):
    def generate_structured(self, *, system_prompt: str, user_prompt: str, schema: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        ...


class FormalReviewState(TypedDict, total=False):
    payload: dict[str, Any]
    trace_id: str
    trusted_context: TrustedCaseContext
    ticket_data: dict[str, Any]
    issue: str
    workflow_plan: ReviewWorkflowPlan
    policy_assessment: PolicyAssessment
    evidence_assessment: EvidenceAssessment
    review_proposal: ReviewProposal
    gate_action: str
    gate_reasons: list[str]
    evidence_needed: list[str]
    tool_trace: list[dict[str, Any]]
    review_result: Optional[dict[str, Any]]
    evidence_request_applied: bool
    evidence_request_outcome: str
    final_reply: str
    need_human: bool
    failure_reason: Optional[str]
    resume_signal: dict[str, Any]
    submission_outcome: str
    review_mode: str
    escalation_reasons: list[str]
    skill_versions: dict[str, str]


_ACTIVE_REVIEW_TRACE: ContextVar[TraceRecorder | None] = ContextVar(
    "active_formal_review_trace",
    default=None,
)


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _env_score(name: str, default: float) -> float:
    try:
        return max(0.0, min(float(os.getenv(name, str(default))), 1.0))
    except (TypeError, ValueError):
        return default


@dataclass
class FormalReviewWorkflow:
    tools: ReviewTools = field(default_factory=AgentToolRegistry)
    llm: ReviewLlm = field(default_factory=get_llm_client)
    policy_workflow: PolicyWorkflowRuntime | None = None
    evidence_workflow: EvidenceWorkflowRuntime | None = None
    skills: AgentSkillRegistry = field(default_factory=AgentSkillRegistry)
    checkpointer: BaseCheckpointSaver[Any] | None = None
    auto_approve_enabled: bool = field(
        default_factory=lambda: _env_bool(
            "FORMAL_REVIEW_AUTO_APPROVE_ENABLED",
            True,
        )
    )
    minimum_review_confidence: float = field(
        default_factory=lambda: _env_score(
            "FORMAL_REVIEW_MIN_CONFIDENCE",
            0.75,
        )
    )

    def __post_init__(self) -> None:
        self._formal_review_skill_definition = self._require_skill(
            "formal_review"
        )
        if self.policy_workflow is None:
            self.policy_workflow = PolicyWorkflow(
                RegistryPolicyRetrievalPort(self.tools),
                rewrite_service=RagQueryRewriteService(self.llm),
            )
        if self.evidence_workflow is None:
            self.evidence_workflow = EvidenceWorkflow(
                RegistryEvidenceReviewPort(self.tools)
            )
        graph = StateGraph(FormalReviewState)
        graph.add_node("load_trusted_context", self.load_trusted_context)
        graph.add_node("validate_review_inputs", self.validate_review_inputs)
        graph.add_node("sop_plan", self.sop_plan)
        graph.add_node("policy_workflow", self.policy_workflow_node)
        graph.add_node("evidence_workflow", self.evidence_workflow_node)
        graph.add_node("review_synthesis", self.review_synthesis)
        graph.add_node("deterministic_gate", self.deterministic_gate)
        graph.add_node("submit_review", self.submit_review)
        graph.add_node("request_missing_evidence", self.request_missing_evidence)
        graph.add_node("await_evidence", self.await_evidence)
        graph.add_node("await_newer_evidence", self.await_newer_evidence)
        graph.add_node("prepare_resumed_attempt", self.prepare_resumed_attempt)
        graph.add_node("submit_manual_review", self.submit_manual_review)

        graph.set_entry_point("load_trusted_context")
        graph.add_conditional_edges(
            "load_trusted_context",
            self.route_after_context,
            {
                "validate_review_inputs": "validate_review_inputs",
                "submit_manual_review": "submit_manual_review",
            },
        )
        graph.add_conditional_edges(
            "validate_review_inputs",
            self.route_after_input_validation,
            {
                "sop_plan": "sop_plan",
                "request_missing_evidence": "request_missing_evidence",
            },
        )
        graph.add_edge("sop_plan", "policy_workflow")
        graph.add_edge("sop_plan", "evidence_workflow")
        graph.add_edge("policy_workflow", "review_synthesis")
        graph.add_edge("evidence_workflow", "review_synthesis")
        graph.add_edge("review_synthesis", "deterministic_gate")
        graph.add_conditional_edges(
            "deterministic_gate",
            self.route_after_gate,
            {
                "submit_review": "submit_review",
                "request_missing_evidence": "request_missing_evidence",
                "submit_manual_review": "submit_manual_review",
            },
        )
        graph.add_conditional_edges(
            "request_missing_evidence",
            self.route_after_evidence_request,
            {
                "await_evidence": "await_evidence",
                "prepare_resumed_attempt": "prepare_resumed_attempt",
                "submit_manual_review": "submit_manual_review",
            },
        )
        graph.add_edge("await_evidence", "prepare_resumed_attempt")
        graph.add_edge("await_newer_evidence", "prepare_resumed_attempt")
        graph.add_edge("prepare_resumed_attempt", "load_trusted_context")
        graph.add_conditional_edges(
            "submit_review",
            self.route_after_submission,
            {"await_newer_evidence": "await_newer_evidence", "end": END},
        )
        graph.add_conditional_edges(
            "submit_manual_review",
            self.route_after_submission,
            {"await_newer_evidence": "await_newer_evidence", "end": END},
        )
        self.graph = graph.compile(checkpointer=self.checkpointer)

    def handle(
        self,
        payload: dict[str, Any],
        trace_recorder: Any | None = None,
    ) -> dict[str, Any]:
        return self.start(payload, trace_recorder)

    def start(
        self,
        payload: dict[str, Any],
        trace_recorder: Any | None = None,
    ) -> dict[str, Any]:
        review_id = str(payload.get("review_request_id") or "").strip()
        if not review_id:
            raise ValueError("review_request_id is required")
        trace = trace_recorder if isinstance(trace_recorder, TraceRecorder) else None
        state: FormalReviewState = {
            "payload": dict(payload),
            "trace_id": trace.trace_id if trace else "",
            "issue": str(payload.get("message") or "").strip(),
            "tool_trace": [],
            "review_result": None,
            "evidence_request_applied": False,
            "evidence_request_outcome": "",
            "evidence_needed": [],
            "need_human": False,
            "failure_reason": None,
            "review_mode": SOP_REVIEW_MODE,
            "escalation_reasons": [],
            "skill_versions": self._formal_skill_versions(),
        }
        final = self._invoke(
            state,
            review_id=review_id,
            trace=trace,
            operation="start",
        )
        return self._format_result(final)

    def resume(
        self,
        review_id: str,
        resume_signal: dict[str, Any],
        trace_recorder: Any | None = None,
    ) -> dict[str, Any]:
        normalized_review_id = str(review_id or "").strip()
        if not normalized_review_id:
            raise ValueError("review_id is required")
        if self.checkpointer is None:
            raise RuntimeError("durable checkpointer is required to resume a review")
        trace = trace_recorder if isinstance(trace_recorder, TraceRecorder) else None
        final = self._invoke(
            Command(resume=dict(resume_signal)),
            review_id=normalized_review_id,
            trace=trace,
            operation="resume",
        )
        return self._format_result(final)

    def _invoke(
        self,
        graph_input: FormalReviewState | Command,
        *,
        review_id: str,
        trace: TraceRecorder | None,
        operation: str,
    ) -> dict[str, Any]:
        bind_llm = getattr(self.llm, "bind_trace", None)
        if callable(bind_llm):
            bind_llm(trace)
        trace_token = _ACTIVE_REVIEW_TRACE.set(trace)
        try:
            with bind_trace_id(trace.trace_id if trace else None):
                with self._trace_step(
                    trace,
                    "formal_review_skill",
                    review_request_id=review_id,
                    operation=operation,
                ) as trace_step:
                    graph_config = {
                        "configurable": {"thread_id": review_id}
                    }
                    final = self.graph.invoke(graph_input, config=graph_config)
                    if self.checkpointer is not None:
                        snapshot = self.graph.get_state(graph_config)
                        interrupts = tuple(
                            interrupt_value
                            for task in snapshot.tasks
                            for interrupt_value in task.interrupts
                        )
                        if interrupts:
                            final = {**final, "__interrupt__": interrupts}
                    trace_step.details.update(
                        {
                            "gate_action": final.get("gate_action"),
                            "need_human": bool(final.get("need_human")),
                            "failure_reason": final.get("failure_reason"),
                        }
                    )
        finally:
            _ACTIVE_REVIEW_TRACE.reset(trace_token)
            if callable(bind_llm):
                bind_llm(None)

        return final

    def _format_result(self, final: dict[str, Any]) -> dict[str, Any]:
        context = final.get("trusted_context")
        ticket = final.get("review_result") or final.get("ticket_data") or {}
        payload = final.get("payload") or {}
        paused = bool(final.get("__interrupt__"))
        return {
            "assistant_reply": final.get("final_reply") or "",
            "session_mode": "AI",
            "tool_trace": final.get("tool_trace") or [],
            "ticket": self._ticket_payload(ticket),
            "review_result": final.get("review_result"),
            "need_human": bool(final.get("need_human")),
            "evidence_needed": list(
                final.get("evidence_needed")
                or (
                    final.get("evidence_assessment")
                    or EvidenceAssessment(
                        context_version="",
                        success=False,
                        visual_verifiable=False,
                        evidence_consistent=None,
                        visual_confidence=0.0,
                    )
                ).missing_evidence
            ),
            "persistence": {
                "session_id": context.session_id if context else payload.get("session_id"),
                "ticket_no": ticket.get("ticket_no") if isinstance(ticket, dict) else None,
            },
            "raw": {
                "runtime": "formal_review_skill",
                "review_mode": final.get("review_mode") or SOP_REVIEW_MODE,
                "escalation_reasons": final.get("escalation_reasons") or [],
                "skill_versions": final.get("skill_versions")
                or self._formal_skill_versions(),
                "context_version": context.context_version if context else None,
                "evidence_revision": context.evidence_revision if context else None,
                "paused": paused,
                "gate_action": final.get("gate_action"),
                "gate_reasons": final.get("gate_reasons") or [],
                "evidence_request_applied": bool(
                    final.get("evidence_request_applied")
                ),
                "failure_reason": final.get("failure_reason"),
                "workflow_plan": self._as_dict(final.get("workflow_plan")),
                "policy_assessment": self._as_dict(
                    final.get("policy_assessment")
                ),
                "evidence_assessment": self._as_dict(
                    final.get("evidence_assessment")
                ),
                "review_proposal": self._as_dict(final.get("review_proposal")),
            },
        }

    def load_trusted_context(
        self,
        state: FormalReviewState,
    ) -> FormalReviewState:
        payload = state["payload"]
        arguments = {
            "user_id": str(payload.get("user_id") or ""),
            "ticket_id": str(payload.get("ticket_id") or ""),
            "order_id": payload.get("order_id"),
        }
        with self._node_trace(
            state,
            "review_load_trusted_context",
        ) as trace_step:
            result = self.tools.call("get_after_sales_ticket", arguments)
            trace_step.details.update(
                {
                    "ok": result.ok,
                    "error_category": result.error_category,
                }
            )
        trace = [self._trace_entry(result, arguments)]
        if not result.ok or not isinstance(result.data, dict):
            return {
                "tool_trace": trace,
                "failure_reason": result.error_category or "ticket_lookup_failed",
                "gate_action": "MANUAL_REVIEW",
                "gate_reasons": ["trusted_context_unavailable"],
                "need_human": True,
            }
        context = TrustedCaseContext.from_ticket(payload, result.data)
        # The ticket stored by Java is the business source of truth. Kafka's
        # message is often only a generic event description and must not dilute
        # the policy retrieval query.
        issue = context.issue_description
        trace_step.details["ticket_status"] = context.ticket_status
        if context.ticket_status not in {"PENDING", "PENDING_REVIEW"}:
            return {
                "tool_trace": trace,
                "ticket_data": dict(result.data),
                "trusted_context": context,
                "failure_reason": "ticket_status_changed",
                "gate_action": "MANUAL_REVIEW",
                "gate_reasons": ["ticket_status_changed"],
                "need_human": True,
            }
        return {
            "tool_trace": trace,
            "ticket_data": dict(result.data),
            "trusted_context": context,
            "issue": issue,
        }

    def validate_review_inputs(
        self,
        state: FormalReviewState,
    ) -> FormalReviewState:
        context = state["trusted_context"]
        ticket = state.get("ticket_data") or {}
        has_issue_description = any(
            str(ticket.get(field) or "").strip()
            for field in ("reason_detail", "description")
        )
        missing: list[str] = []
        if not has_issue_description:
            missing.append("问题描述")
        if not context.attachments:
            missing.append("商品问题图片")
        with self._node_trace(
            state,
            "review_validate_inputs",
        ) as trace_step:
            trace_step.details.update(
                {
                    "has_issue_description": has_issue_description,
                    "has_image_evidence": bool(context.attachments),
                    "missing_input_count": len(missing),
                }
            )
        if missing:
            return {
                "gate_action": "REQUEST_EVIDENCE",
                "gate_reasons": ["evidence_missing"],
                "evidence_needed": missing,
                "need_human": False,
            }
        return {"evidence_needed": []}

    def sop_plan(self, state: FormalReviewState) -> FormalReviewState:
        context = state["trusted_context"]
        with self._node_trace(
            state,
            "review_sop_plan",
        ) as trace_step:
            plan = FormalReviewSop.plan(context, state.get("issue") or "")
            trace_step.details.update(
                {
                    "requires_policy": bool(plan.policy_query),
                    "specialist_count": len(plan.specialists),
                    "plan_action": plan.action,
                }
            )
        return {"workflow_plan": plan}

    def _policy_task(self, state: FormalReviewState) -> PolicyTask:
        context = state["trusted_context"]
        payload = state["payload"]
        review_request_id = str(payload.get("review_request_id") or "")
        return PolicyTask(
            task_id=self._workflow_task_id(
                review_request_id,
                "POLICY",
                context.context_version,
            ),
            trace_id=self._state_trace_id(state),
            review_request_id=review_request_id,
            ticket_id=context.ticket_id,
            context_version=context.context_version,
            user_id=context.user_id,
            issue=state.get("issue") or "",
            query=state["workflow_plan"].policy_query,
            merchant_code=context.merchant_code,
            product_name=context.product_name,
            product_category=context.product_category,
            after_sales_type=context.after_sales_type,
            policy_version=context.policy_version,
            business_time=context.business_time,
            skill_name=self._formal_review_skill_definition.name,
            skill_version=self._formal_review_skill_definition.version,
            skill_instructions=self._formal_skill_instructions(
                "policy-workflow.md"
            ),
        )

    def _evidence_task(self, state: FormalReviewState) -> EvidenceTask:
        context = state["trusted_context"]
        payload = state["payload"]
        review_request_id = str(payload.get("review_request_id") or "")
        return EvidenceTask(
            task_id=self._workflow_task_id(
                review_request_id,
                "EVIDENCE",
                context.context_version,
            ),
            trace_id=self._state_trace_id(state),
            review_request_id=review_request_id,
            ticket_id=context.ticket_id,
            context_version=context.context_version,
            user_id=context.user_id,
            order_id=context.order_id,
            issue=state.get("issue") or "",
            product_name=context.product_name,
            product_category=context.product_category,
            after_sales_type=context.after_sales_type,
            attachments=tuple(dict(item) for item in context.attachments),
            skill_name=self._formal_review_skill_definition.name,
            skill_version=self._formal_review_skill_definition.version,
            skill_instructions=self._formal_skill_instructions(
                "evidence-workflow.md"
            ),
        )

    @staticmethod
    def _workflow_task_id(
        review_request_id: str,
        specialist: str,
        context_version: str,
    ) -> str:
        raw = f"{review_request_id}:{specialist}:{context_version}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _state_trace_id(state: FormalReviewState) -> str | None:
        return str(state.get("trace_id") or current_trace_id() or "") or None

    def policy_workflow_node(self, state: FormalReviewState) -> FormalReviewState:
        task = self._policy_task(state)
        with self._node_trace(
            state,
            "review_policy_workflow",
        ) as trace_step:
            if self.policy_workflow is None:
                raise RuntimeError("policy workflow is not configured")
            assessment = self.policy_workflow.handle(task)
            trace_step.details.update(
                {
                    "skill_task_id": task.task_id,
                    "skill_type": "POLICY",
                    "skill_name": task.skill_name,
                    "skill_version": task.skill_version,
                    "input_context_version": task.context_version,
                    "output_context_version": assessment.context_version,
                    "success": assessment.success,
                    "retrieval_mode": assessment.retrieval_mode,
                    "trusted_policy_eligible": assessment.trusted_policy_eligible,
                    "policy_version_matched": assessment.policy_version_matched,
                    "citation_count": len(assessment.citations),
                }
            )
        return {"policy_assessment": assessment}

    def evidence_workflow_node(self, state: FormalReviewState) -> FormalReviewState:
        task = self._evidence_task(state)
        with self._node_trace(
            state,
            "review_evidence_workflow",
        ) as trace_step:
            if self.evidence_workflow is None:
                raise RuntimeError("evidence workflow is not configured")
            assessment = self.evidence_workflow.handle(task)
            trace_step.details.update(
                {
                    "skill_task_id": task.task_id,
                    "skill_type": "EVIDENCE",
                    "skill_name": task.skill_name,
                    "skill_version": task.skill_version,
                    "input_context_version": task.context_version,
                    "output_context_version": assessment.context_version,
                    "success": assessment.success,
                    "visual_verifiable": assessment.visual_verifiable,
                    "evidence_consistent": assessment.evidence_consistent,
                    "missing_evidence_count": len(assessment.missing_evidence),
                    "risk_signal_count": len(assessment.risk_signals),
                }
            )
        return {"evidence_assessment": assessment}

    def review_synthesis(self, state: FormalReviewState) -> FormalReviewState:
        with self._node_trace(
            state,
            "review_synthesis",
        ) as trace_step:
            policy = state["policy_assessment"]
            evidence = state["evidence_assessment"]
            expected_context_version = state["trusted_context"].context_version
            specialist_versions = {
                policy.context_version,
                evidence.context_version,
            }
            if specialist_versions != {expected_context_version}:
                trace_step.details.update(
                    {
                        "synthesis_skipped": True,
                        "failure_category": (
                            "specialist_context_version_mismatch"
                        ),
                        "expected_context_version": expected_context_version,
                        "policy_context_version": policy.context_version,
                        "evidence_context_version": evidence.context_version,
                    }
                )
                return {
                    "failure_reason": (
                        "specialist_context_version_mismatch"
                    ),
                    "gate_action": "MANUAL_REVIEW",
                    "gate_reasons": [
                        "specialist_context_version_mismatch"
                    ],
                    "need_human": True,
                }
            if policy.required_evidence:
                unresolved = tuple(
                    item
                    for item in policy.required_evidence
                    if is_core_evidence_requirement(item)
                    and item not in evidence.satisfied_evidence
                    and item not in evidence.missing_evidence
                    and not (
                        evidence.visual_verifiable
                        and any(token in item for token in ("图片", "照片", "截图"))
                    )
                )
                if unresolved:
                    evidence = EvidenceAssessment(
                        **{
                            **evidence.to_dict(),
                            "missing_evidence": tuple(
                                dict.fromkeys(
                                    [*evidence.missing_evidence, *unresolved]
                                )
                            ),
                        }
                    )
            escalation = FormalReviewSop.assess_escalation(
                policy,
                evidence,
                minimum_review_confidence=self.minimum_review_confidence,
            )
            if escalation.required:
                review_mode = ESCALATED_REVIEW_MODE
                proposal = ComplexReviewSynthesizer(self.llm).synthesize(
                    state["trusted_context"],
                    state.get("issue") or "",
                    policy,
                    evidence,
                )
            else:
                review_mode = SOP_REVIEW_MODE
                proposal = FormalReviewSop.build_routine_proposal(policy, evidence)
            proposal = apply_deterministic_confidence(
                proposal,
                policy,
                evidence,
            )
            trace_step.details.update(
                {
                    "proposed_verdict": proposal.proposed_verdict,
                    "confidence": proposal.confidence,
                    "model_confidence": proposal.model_confidence,
                    "confidence_model_version": (
                        proposal.confidence_model_version
                    ),
                    "confidence_breakdown": proposal.confidence_breakdown,
                    "missing_evidence_count": len(evidence.missing_evidence),
                    "risk_reason_count": len(proposal.risk_reasons),
                    "review_mode": review_mode,
                    "escalation_reasons": list(escalation.reasons),
                }
            )
        return {
            "evidence_assessment": evidence,
            "review_proposal": proposal,
            "review_mode": review_mode,
            "escalation_reasons": list(escalation.reasons),
        }

    def deterministic_gate(
        self,
        state: FormalReviewState,
    ) -> FormalReviewState:
        if (
            state.get("failure_reason")
            == "specialist_context_version_mismatch"
        ):
            return {
                "failure_reason": (
                    "specialist_context_version_mismatch"
                ),
                "gate_action": "MANUAL_REVIEW",
                "gate_reasons": [
                    "specialist_context_version_mismatch"
                ],
                "need_human": True,
            }
        with self._node_trace(
            state,
            "review_deterministic_gate",
        ) as trace_step:
            policy = state["policy_assessment"]
            evidence = state["evidence_assessment"]
            proposal = state["review_proposal"]
            policy_reasons: list[str] = []
            evidence_failure_reasons: list[str] = []
            if not policy.success or not policy.trusted_policy_eligible:
                policy_reasons.append("policy_not_trusted")
            if not policy.policy_version_matched:
                policy_reasons.append("policy_version_not_matched")
            if evidence.risk_signals:
                evidence_failure_reasons.append("evidence_risk_detected")
            if not evidence.success:
                evidence_failure_reasons.append("evidence_service_failed")

            if evidence_failure_reasons:
                action = "MANUAL_REVIEW"
                reasons = evidence_failure_reasons
            elif not state["trusted_context"].attachments:
                action = "REQUEST_EVIDENCE"
                reasons = ["evidence_missing"]
            elif not evidence.visual_verifiable:
                action = "MANUAL_REVIEW"
                reasons = ["visual_evidence_not_verifiable"]
            elif evidence.visual_confidence < self.minimum_review_confidence:
                action = "MANUAL_REVIEW"
                reasons = ["visual_confidence_below_threshold"]
            elif policy_reasons:
                action = "MANUAL_REVIEW"
                reasons = policy_reasons
            elif proposal.confidence < self.minimum_review_confidence:
                action = "MANUAL_REVIEW"
                reasons = ["review_confidence_below_threshold"]
            elif (
                self.auto_approve_enabled
                and proposal.proposed_verdict == "APPROVE"
                and evidence.visual_verifiable
                and evidence.evidence_consistent is True
            ):
                action = "SUBMIT_REVIEW"
                reasons = []
            else:
                action = "MANUAL_REVIEW"
                reasons = [
                    "auto_approve_disabled"
                    if not self.auto_approve_enabled
                    else "approval_conditions_not_met"
                ]
            trace_step.details.update(
                {
                    "gate_action": action,
                    "gate_reasons": list(reasons),
                    "auto_approve_enabled": self.auto_approve_enabled,
                    "review_confidence": proposal.confidence,
                    "minimum_review_confidence": self.minimum_review_confidence,
                }
            )
        return {
            "gate_action": action,
            "gate_reasons": reasons,
            "need_human": action == "MANUAL_REVIEW",
        }

    def submit_review(self, state: FormalReviewState) -> FormalReviewState:
        return self._submit_verdict(state, "APPROVE")

    def submit_manual_review(
        self,
        state: FormalReviewState,
    ) -> FormalReviewState:
        return self._submit_verdict(state, "MANUAL_REVIEW_REQUIRED")

    def request_missing_evidence(
        self,
        state: FormalReviewState,
    ) -> FormalReviewState:
        evidence_request_skill = self._require_skill("evidence_collection")
        skill_versions = dict(state.get("skill_versions") or {})
        skill_versions[evidence_request_skill.name] = evidence_request_skill.version
        payload = state["payload"]
        context = state.get("trusted_context")
        evidence = state.get("evidence_assessment")
        missing = list(state.get("evidence_needed") or [])
        if not missing and evidence:
            missing = list(evidence.missing_evidence)
        reply = (
            f"为便于继续审核，请补充：{'、'.join(missing)}。"
            if missing
            else "为便于继续审核，请补充相关问题凭证。"
        )
        arguments = {
            "user_id": context.user_id if context else payload.get("user_id"),
            "session_id": context.session_id if context else payload.get("session_id"),
            "ticket_id": context.ticket_id if context else payload.get("ticket_id"),
            "order_id": context.order_id if context else payload.get("order_id"),
            "review_request_id": str(payload.get("review_request_id") or ""),
            "evidence_revision": context.evidence_revision if context else 0,
            "assistant_reply": reply,
            "evidence_needed": missing,
        }
        with self._node_trace(
            state,
            "java_request_missing_evidence",
            missing_evidence_count=len(missing),
        ) as trace_step:
            result = self.tools.call("request_missing_evidence", arguments)
            trace_step.details.update(
                {
                    "ok": result.ok,
                    "error_category": result.error_category,
                }
            )
        AGENT_RUNTIME_METRICS.record_formal_review(
            action="request_evidence",
            success=result.ok,
        )
        trace = list(state.get("tool_trace") or [])
        trace.append(self._trace_entry(result, arguments))
        data = result.data if result.ok and isinstance(result.data, dict) else {}
        reject_reason = str(
            data.get("review_reject_reason")
            or data.get("reviewRejectReason")
            or ""
        ).upper()
        stale_evidence = reject_reason == "STALE_EVIDENCE"
        applied = bool(result.ok and not stale_evidence)
        return {
            "tool_trace": trace,
            "evidence_request_applied": applied,
            "evidence_request_outcome": reject_reason,
            "evidence_needed": missing,
            "skill_versions": skill_versions,
            "final_reply": (
                reply
                if applied
                else ""
                if stale_evidence
                else "补充凭证请求暂时无法确认，售后申请将转由人工继续核对。"
            ),
            "need_human": not result.ok and not stale_evidence,
            "failure_reason": (
                None
                if applied or stale_evidence
                else result.error_category or "evidence_request_failed"
            ),
            "gate_action": (
                "REQUEST_EVIDENCE"
                if applied
                else "STALE_EVIDENCE"
                if stale_evidence
                else "MANUAL_REVIEW"
            ),
        }

    def await_evidence(self, state: FormalReviewState) -> FormalReviewState:
        context = state.get("trusted_context")
        signal = interrupt(
            {
                "reason": "evidence_required",
                "review_id": str(state["payload"].get("review_request_id") or ""),
                "ticket_id": context.ticket_id if context else None,
                "evidence_revision": context.evidence_revision if context else 0,
                "evidence_needed": list(state.get("evidence_needed") or []),
            }
        )
        return {"resume_signal": dict(signal) if isinstance(signal, dict) else {}}

    def await_newer_evidence(self, state: FormalReviewState) -> FormalReviewState:
        context = state.get("trusted_context")
        signal = interrupt(
            {
                "reason": "stale_evidence",
                "review_id": str(state["payload"].get("review_request_id") or ""),
                "ticket_id": context.ticket_id if context else None,
                "evidence_revision": context.evidence_revision if context else 0,
            }
        )
        return {"resume_signal": dict(signal) if isinstance(signal, dict) else {}}

    def prepare_resumed_attempt(self, state: FormalReviewState) -> FormalReviewState:
        return {
            "trace_id": current_trace_id() or str(state.get("trace_id") or ""),
            "trusted_context": None,
            "ticket_data": {},
            "workflow_plan": None,
            "policy_assessment": None,
            "evidence_assessment": None,
            "review_proposal": None,
            "review_result": None,
            "submission_outcome": "",
            "gate_action": "",
            "gate_reasons": [],
            "evidence_needed": [],
            "evidence_request_applied": False,
            "evidence_request_outcome": "",
            "need_human": False,
            "failure_reason": None,
            "final_reply": "",
            "tool_trace": [],
            "review_mode": SOP_REVIEW_MODE,
            "escalation_reasons": [],
            "skill_versions": self._formal_skill_versions(),
        }

    def _submit_verdict(
        self,
        state: FormalReviewState,
        verdict: str,
    ) -> FormalReviewState:
        payload = state["payload"]
        context = state.get("trusted_context")
        policy = state.get("policy_assessment")
        evidence = state.get("evidence_assessment")
        proposal = state.get("review_proposal")
        arguments = {
            "user_id": context.user_id if context else payload.get("user_id"),
            "session_id": context.session_id if context else payload.get("session_id"),
            "ticket_id": context.ticket_id if context else payload.get("ticket_id"),
            "order_id": context.order_id if context else payload.get("order_id"),
            "review_request_id": str(payload.get("review_request_id") or ""),
            "expected_evidence_revision": (
                context.evidence_revision if context else 0
            ),
            "agent_architecture": "single_agent_skills_tools_retrieval",
            "skill_versions": state.get("skill_versions")
            or self._formal_skill_versions(),
            "context_version": context.context_version if context else None,
            "verdict": verdict,
            "ai_review_confidence": proposal.confidence if proposal else 0.0,
            "model_confidence": (
                proposal.model_confidence if proposal else 0.0
            ),
            "confidence_model_version": (
                proposal.confidence_model_version if proposal else None
            ),
            "confidence_breakdown": (
                proposal.confidence_breakdown if proposal else {}
            ),
            "reason": (
                proposal.reason
                if proposal
                else "智能审核无法形成可靠结论，转人工审核。"
            ),
            "evidence_needed": list(evidence.missing_evidence) if evidence else [],
            "visual_uncertain": not bool(evidence and evidence.visual_verifiable),
            "policy_uncertain": not bool(
                policy and policy.trusted_policy_eligible
            ),
            "evidence_consistent": (
                evidence.evidence_consistent if evidence else None
            ),
            "visual_confidence": (
                evidence.visual_confidence if evidence else 0.0
            ),
            "risk_review_reasons": list(
                dict.fromkeys(
                    [
                        *(state.get("gate_reasons") or []),
                        *(state.get("escalation_reasons") or []),
                        *(proposal.risk_reasons if proposal else ()),
                        *(policy.uncertainty_reasons if policy else ()),
                        *(evidence.uncertainty_reasons if evidence else ()),
                    ]
                )
            ),
            "knowledge_retrieval_mode": (
                policy.retrieval_mode if policy else None
            ),
            "filter_level": policy.filter_level if policy else None,
            "reranker_succeeded": (
                policy.reranker_succeeded if policy else False
            ),
            "trusted_policy_eligible": (
                policy.trusted_policy_eligible if policy else False
            ),
            "policy_version": context.policy_version if context else None,
            "policy_match_score": policy.policy_match_score if policy else 0.0,
            "policy_citations": (
                [dict(item) for item in policy.citations] if policy else []
            ),
            "image_review": evidence.image_review if evidence else None,
            "specialist_assessments": {
                "policy": policy.to_dict() if policy else None,
                "evidence": evidence.to_dict() if evidence else None,
            },
        }
        step_name = (
            "java_submit_review"
            if verdict == "APPROVE"
            else "java_submit_manual_review"
        )
        with self._node_trace(
            state,
            step_name,
            verdict=verdict,
        ) as trace_step:
            result = self.tools.call("submit_ai_review", arguments)
            data = result.data if result.ok and isinstance(result.data, dict) else None
            trace_step.details.update(
                {
                    "ok": result.ok,
                    "error_category": result.error_category,
                    "review_applied": bool(data and data.get("review_applied") is True),
                    "review_reject_reason": (
                        (data or {}).get("review_reject_reason")
                        if isinstance(data, dict)
                        else None
                    ),
                }
            )
        AGENT_RUNTIME_METRICS.record_formal_review(
            action=(
                "submit_review"
                if verdict == "APPROVE"
                else "manual_review"
            ),
            success=result.ok,
        )
        trace = list(state.get("tool_trace") or [])
        trace.append(self._trace_entry(result, arguments))
        data = result.data if result.ok and isinstance(result.data, dict) else None
        applied = bool(data and data.get("review_applied") is True)
        reject_reason = str((data or {}).get("review_reject_reason") or "").upper()
        if not applied and reject_reason == "STALE_EVIDENCE":
            return {
                "tool_trace": trace,
                "review_result": data,
                "submission_outcome": "STALE_EVIDENCE",
                "final_reply": "",
                "need_human": False,
                "failure_reason": None,
            }
        actual = str(
            (data or {}).get("verdict")
            or (data or {}).get("ai_review_result")
            or verdict
        ).upper()
        if applied and actual == "APPROVE":
            reply = "您的售后申请已完成智能初审，当前已进入处理中。"
            need_human = False
        elif applied:
            reply = "您的售后申请需要人工进一步复核。"
            need_human = True
        else:
            reply = "智能初审结果暂时无法确认，将由人工继续核对。"
            need_human = True
        return {
            "tool_trace": trace,
            "review_result": data,
            "final_reply": reply,
            "need_human": need_human,
            "submission_outcome": "APPLIED" if applied else "NOT_APPLIED",
            "failure_reason": (
                state.get("failure_reason")
                or (
                    None
                    if applied
                    else result.error_category or "review_not_applied"
                )
            ),
        }

    @staticmethod
    def route_after_context(
        state: FormalReviewState,
    ) -> Literal["validate_review_inputs", "submit_manual_review"]:
        return (
            "validate_review_inputs"
            if state.get("trusted_context")
            and not state.get("failure_reason")
            else "submit_manual_review"
        )

    @staticmethod
    def route_after_input_validation(
        state: FormalReviewState,
    ) -> Literal["sop_plan", "request_missing_evidence"]:
        return (
            "request_missing_evidence"
            if state.get("evidence_needed")
            else "sop_plan"
        )

    @staticmethod
    def route_after_gate(
        state: FormalReviewState,
    ) -> Literal[
        "submit_review",
        "request_missing_evidence",
        "submit_manual_review",
    ]:
        return {
            "SUBMIT_REVIEW": "submit_review",
            "REQUEST_EVIDENCE": "request_missing_evidence",
        }.get(str(state.get("gate_action")), "submit_manual_review")

    @staticmethod
    def route_after_evidence_request(
        state: FormalReviewState,
    ) -> Literal["await_evidence", "prepare_resumed_attempt", "submit_manual_review"]:
        if state.get("evidence_request_applied"):
            return "await_evidence"
        if state.get("evidence_request_outcome") == "STALE_EVIDENCE":
            return "prepare_resumed_attempt"
        return "submit_manual_review"

    @staticmethod
    def route_after_submission(
        state: FormalReviewState,
    ) -> Literal["await_newer_evidence", "end"]:
        return (
            "await_newer_evidence"
            if state.get("submission_outcome") == "STALE_EVIDENCE"
            else "end"
        )

    @staticmethod
    def _trace_entry(
        result: ToolResult,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "tool": result.name,
            "arguments": arguments,
            "ok": result.ok,
            "data": result.data,
            "error": result.error,
            "error_code": result.error_code,
            "error_category": result.error_category,
            "retryable": result.retryable,
            "function_call_mode": "deterministic",
            "provider_tool_call_shape": "none",
        }

    @staticmethod
    def _trace_step(
        trace_recorder: TraceRecorder | None,
        name: str,
        **details: Any,
    ):
        return (
            trace_recorder.step(name, **details)
            if trace_recorder is not None
            else nullcontext(type("TraceDetails", (), {"details": {}})())
        )

    @contextmanager
    def _node_trace(
        self,
        state: FormalReviewState,
        name: str,
        **details: Any,
    ):
        trace = _ACTIVE_REVIEW_TRACE.get()
        with bind_trace_id(trace.trace_id if trace else None):
            with self._trace_step(trace, name, **details) as trace_step:
                yield trace_step

    @staticmethod
    def _ticket_payload(ticket: dict[str, Any]) -> dict[str, Any] | None:
        if not ticket:
            return None
        return {
            "ticket_id": str(ticket.get("ticket_id") or "") or None,
            "ticket_no": str(ticket.get("ticket_no") or "") or None,
            "status": str(ticket.get("status") or "").lower(),
            "order_id": str(ticket.get("order_id") or "") or None,
            "existing": bool(ticket.get("existing")),
        }

    @staticmethod
    def _as_dict(value: Any) -> dict[str, Any] | None:
        if value is None:
            return None
        to_dict = getattr(value, "to_dict", None)
        return to_dict() if callable(to_dict) else None

    def _require_skill(self, stage: str) -> AgentSkill:
        skill = self.skills.select(stage)
        if skill is None:
            raise RuntimeError(f"required formal review skill is missing: {stage}")
        return skill

    def _formal_skill_versions(self) -> dict[str, str]:
        return {
            self._formal_review_skill_definition.name: (
                self._formal_review_skill_definition.version
            ),
        }

    def _formal_skill_instructions(self, reference: str) -> str:
        reference_instructions = self.skills.load_reference(
            self._formal_review_skill_definition.name,
            reference,
        )
        return (
            f"按需加载的工作流参考（{reference}）：\n"
            f"{reference_instructions}"
        )


# 兼容旧导入；正式运行时统一使用 FormalReviewWorkflow。
FormalReviewGraph = FormalReviewWorkflow
