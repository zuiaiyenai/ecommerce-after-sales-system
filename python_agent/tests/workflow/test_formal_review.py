from __future__ import annotations

from dataclasses import fields

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from after_sales_agent.agent.skill_registry import AgentSkillRegistry
from after_sales_agent.agent.workflows.formal_review import (
    EvidenceAssessment,
    EvidenceTask,
    EvidenceWorkflow,
    FormalReviewWorkflow,
    PolicyAssessment,
    PolicyTask,
    PolicyWorkflow,
)
from after_sales_agent.agent.workflows.formal_review.contracts import TrustedCaseContext
from after_sales_agent.application.rag_query_rewrite import (
    RagQueryCandidate,
    RagRewriteDecision,
    RagRewriteModelError,
)
from after_sales_agent.infrastructure.request_tracing import TraceRecorder, current_trace_id
from after_sales_agent.tools import ToolResult


class PolicyPort:
    def __init__(self) -> None:
        self.tasks: list[PolicyTask] = []

    def retrieve(self, task: PolicyTask) -> ToolResult:
        self.tasks.append(task)
        return ToolResult(
            ok=True,
            name="retrieve_knowledge",
            data={
                "mode": "hybrid_reranked",
                "filter_level": "strict",
                "reranker_succeeded": True,
                "trusted_policy_eligible": True,
                "threshold": 0.55,
                "hits": [
                    {
                        "source_type": "after_sales_policy",
                        "merchant_code": task.merchant_code,
                        "policy_version": task.policy_version,
                        "trusted_policy_eligible": True,
                        "relaxation_level": "strict",
                        "rerank_score": 0.9,
                        "valid_from": "2026-01-01T00:00:00+08:00",
                        "valid_to": "2027-01-01T00:00:00+08:00",
                        "metadata": {"default_evidence": ["商品问题图片"]},
                        "citations": [
                            {
                                "source_code": "POLICY-001",
                                "chunk_id": "chunk-001",
                            }
                        ],
                    }
                ],
            },
        )

    def retrieve_multi(
        self,
        task: PolicyTask,
        queries: tuple[str, ...],
    ) -> ToolResult:
        raise AssertionError("trusted first-pass retrieval must skip query rewriting")


class EvidencePort:
    def __init__(self) -> None:
        self.tasks: list[EvidenceTask] = []

    def review(self, task: EvidenceTask) -> ToolResult:
        self.tasks.append(task)
        return ToolResult(
            ok=True,
            name="review_images",
            data={
                "success": True,
                "has_damage_area": True,
                "missing_visual_evidence": [],
                "confidence": 0.93,
                "items": [{"confidence": 0.93}],
            },
        )


def policy_task(context_version: str = "ctx-1") -> PolicyTask:
    return PolicyTask(
        task_id=f"policy-{context_version}",
        trace_id="1234567890abcdef1234567890abcdef",
        review_request_id="event-1",
        ticket_id="9001",
        context_version=context_version,
        user_id="7",
        issue="耳机外壳破裂",
        query="耳机质量问题退货政策",
        merchant_code="MERCHANT_DEMO",
        product_name="蓝牙耳机",
        product_category="headphone",
        after_sales_type="RETURN_REFUND",
        policy_version="v2",
        business_time="2026-07-01T10:00:00+08:00",
        skill_name="formal-review",
        skill_version="policy-version-1",
        skill_instructions="只评估权威政策证据。",
    )


def evidence_task(
    context_version: str = "ctx-1",
    *,
    with_attachments: bool = True,
) -> EvidenceTask:
    return EvidenceTask(
        task_id=f"evidence-{context_version}",
        trace_id="1234567890abcdef1234567890abcdef",
        review_request_id="event-1",
        ticket_id="9001",
        context_version=context_version,
        user_id="7",
        order_id="8001",
        issue="耳机外壳破裂",
        product_name="蓝牙耳机",
        product_category="headphone",
        after_sales_type="RETURN_REFUND",
        attachments=(
            ({"kind": "image", "source": "https://example.invalid/a.jpg"},)
            if with_attachments
            else ()
        ),
        skill_name="formal-review",
        skill_version="evidence-version-1",
        skill_instructions="只评估直接可见的凭证。",
    )


def test_workflow_tasks_expose_only_domain_specific_context() -> None:
    policy_fields = {item.name for item in fields(PolicyTask)}
    evidence_fields = {item.name for item in fields(EvidenceTask)}

    assert "attachments" not in policy_fields
    assert "policy_assessment" not in evidence_fields
    assert "policy_version" not in evidence_fields
    assert "review_proposal" not in policy_fields | evidence_fields
    assert "gate_action" not in policy_fields | evidence_fields


def test_policy_workflow_runs_with_private_task_and_policy_only_port() -> None:
    port = PolicyPort()
    workflow = PolicyWorkflow(port=port)
    first = workflow.handle(policy_task("ctx-1"))
    second = workflow.handle(policy_task("ctx-2"))

    assert not hasattr(port, "call")
    assert [task.context_version for task in port.tasks] == ["ctx-1", "ctx-2"]
    assert first.context_version == "ctx-1"
    assert second.context_version == "ctx-2"
    assert first.trusted_policy_eligible is True


class ControlledPolicyPort:
    def __init__(
        self,
        initial: ToolResult,
        rewritten: ToolResult,
    ) -> None:
        self.initial = initial
        self.rewritten = rewritten
        self.calls: list[tuple[str, object]] = []

    def retrieve(self, task: PolicyTask) -> ToolResult:
        self.calls.append(("retrieve", task))
        return self.initial

    def retrieve_multi(
        self,
        task: PolicyTask,
        queries: tuple[str, ...],
    ) -> ToolResult:
        self.calls.append(("retrieve_multi", queries))
        return self.rewritten


class RewriteService:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict[str, object]] = []

    def evaluate(self, **kwargs: object) -> RagRewriteDecision:
        self.calls.append(dict(kwargs))
        if self.fail:
            raise RagRewriteModelError("rewrite unavailable")
        return RagRewriteDecision(
            sufficient=False,
            confidence=0.8,
            covered_aspects=(),
            missing_aspects=("special return conditions",),
            queries=(
                RagQueryCandidate(
                    query="headphone quality return special conditions",
                    focus="special conditions",
                ),
            ),
        )


def _untrusted_policy_result(
    *,
    mode: str = "hybrid_reranked",
    failure_reason: str | None = None,
) -> ToolResult:
    return ToolResult(
        ok=True,
        name="retrieve_knowledge",
        data={
            "mode": mode,
            "filter_level": "strict",
            "reranker_succeeded": mode == "hybrid_reranked",
            "trusted_policy_eligible": False,
            "failure_reason": failure_reason,
            "hits": [],
        },
    )


def _trusted_multi_policy_result(task: PolicyTask) -> ToolResult:
    return ToolResult(
        ok=True,
        name="retrieve_knowledge_multi",
        data={
            "mode": "multi_query_reranked",
            "filter_level": "strict",
            "reranker_succeeded": True,
            "trusted_policy_eligible": True,
            "threshold": 0.55,
            "hits": [
                {
                    "source_type": "after_sales_policy",
                    "merchant_code": task.merchant_code,
                    "policy_version": task.policy_version,
                    "trusted_policy_eligible": True,
                    "relaxation_level": "strict",
                    "rerank_score": 0.91,
                    "valid_from": "2026-01-01T00:00:00+08:00",
                    "valid_to": "2027-01-01T00:00:00+08:00",
                    "citations": [
                        {
                            "source_code": "POLICY-002",
                            "chunk_id": "chunk-002",
                        }
                    ],
                }
            ],
        },
    )


def test_policy_workflow_rewrites_once_and_accepts_trusted_second_pass() -> None:
    task = policy_task()
    port = ControlledPolicyPort(
        _untrusted_policy_result(),
        _trusted_multi_policy_result(task),
    )
    rewrite = RewriteService()

    assessment = PolicyWorkflow(
        port=port,
        rewrite_service=rewrite,
    ).handle(task)

    assert [name for name, _ in port.calls] == ["retrieve", "retrieve_multi"]
    assert len(rewrite.calls) == 1
    assert "formal-review@policy-version-1" in str(
        rewrite.calls[0]["task"]
    )
    assert "只评估权威政策证据。" in str(
        rewrite.calls[0]["task"]
    )
    assert port.calls[1][1] == (
        "headphone quality return special conditions",
    )
    assert assessment.trusted_policy_eligible is True
    assert assessment.retrieval_mode == "multi_query_reranked"


def test_policy_workflow_second_pass_is_terminal_even_when_still_untrusted() -> None:
    port = ControlledPolicyPort(
        _untrusted_policy_result(),
        _untrusted_policy_result(),
    )
    rewrite = RewriteService()

    assessment = PolicyWorkflow(
        port=port,
        rewrite_service=rewrite,
    ).handle(policy_task())

    assert [name for name, _ in port.calls] == ["retrieve", "retrieve_multi"]
    assert len(rewrite.calls) == 1
    assert assessment.trusted_policy_eligible is False


def test_policy_workflow_does_not_rewrite_infrastructure_failure() -> None:
    port = ControlledPolicyPort(
        _untrusted_policy_result(
            mode="hybrid_rrf_degraded",
            failure_reason="EMBEDDING_ERROR",
        ),
        _untrusted_policy_result(),
    )
    rewrite = RewriteService()

    assessment = PolicyWorkflow(
        port=port,
        rewrite_service=rewrite,
    ).handle(policy_task())

    assert [name for name, _ in port.calls] == ["retrieve"]
    assert rewrite.calls == []
    assert assessment.trusted_policy_eligible is False


def test_policy_workflow_rewrite_failure_fails_closed_without_second_call() -> None:
    port = ControlledPolicyPort(
        _untrusted_policy_result(),
        _untrusted_policy_result(),
    )
    rewrite = RewriteService(fail=True)

    assessment = PolicyWorkflow(
        port=port,
        rewrite_service=rewrite,
    ).handle(policy_task())

    assert [name for name, _ in port.calls] == ["retrieve"]
    assert len(rewrite.calls) == 1
    assert assessment.trusted_policy_eligible is False


def test_evidence_workflow_without_attachments_does_not_call_vision_port() -> None:
    port = EvidencePort()
    workflow = EvidenceWorkflow(port=port)

    assessment = workflow.handle(evidence_task(with_attachments=False))

    assert not hasattr(port, "call")
    assert port.tasks == []
    assert assessment.context_version == "ctx-1"
    assert assessment.visual_verifiable is False
    assert assessment.missing_evidence


def test_evidence_workflow_uses_only_evidence_task_for_visual_review() -> None:
    port = EvidencePort()
    workflow = EvidenceWorkflow(port=port)

    assessment = workflow.handle(evidence_task())

    assert port.tasks == [evidence_task()]
    assert assessment.context_version == "ctx-1"
    assert assessment.visual_verifiable is True


class FunctionalEvidencePort:
    def __init__(self, *, contradictory: bool = False) -> None:
        self.contradictory = contradictory

    def review(self, task: EvidenceTask) -> ToolResult:
        return ToolResult(
            ok=True,
            name="review_images",
            data={
                "success": True,
                "has_damage_area": False,
                "has_visible_issue": True,
                "evidence_relevant": True,
                "evidence_consistent": not self.contradictory,
                "tampering_suspected": False,
                "evidence_categories": ["functional_issue"],
                "observed_issue_types": ["screen_error"],
                "verification_limitations": [],
                "missing_visual_evidence": [],
                "items": [
                    {
                        "confidence": 0.91,
                        "issue_visible": True,
                        "evidence_relevance": 0.93,
                        "evidence_consistency": (
                            "contradictory"
                            if self.contradictory
                            else "consistent"
                        ),
                    }
                ],
            },
        )


def test_evidence_workflow_accepts_visible_functional_issue_without_damage() -> None:
    assessment = EvidenceWorkflow(
        port=FunctionalEvidencePort()
    ).handle(evidence_task())

    assert assessment.visual_verifiable is True
    assert assessment.evidence_consistent is True
    assert assessment.evidence_categories == ("functional_issue",)
    assert assessment.observed_issue_types == ("screen_error",)
    assert "商品问题图片" in assessment.satisfied_evidence


def test_evidence_workflow_marks_contradictory_visual_evidence_as_risk() -> None:
    assessment = EvidenceWorkflow(
        port=FunctionalEvidencePort(contradictory=True)
    ).handle(evidence_task())

    assert assessment.visual_verifiable is False
    assert assessment.evidence_consistent is False
    assert "visual_evidence_contradictory" in assessment.risk_signals
    assert "visual_evidence_inconsistent" in assessment.uncertainty_reasons


class PlanningOnlyLlm:
    def __init__(self) -> None:
        self.calls = 0

    def chat_json(self, **kwargs):
        self.calls += 1
        if self.calls > 1:
            raise AssertionError("context mismatch must skip supervisor synthesis")
        return {
            "specialists": ["POLICY", "EVIDENCE"],
            "policy_query": "商品质量问题退货政策",
            "reason_codes": ["FORMAL_REVIEW"],
        }

    def generate_structured(self, *, system_prompt, user_prompt, schema, **kwargs):
        self.calls += 1
        if self.calls > 1:
            raise AssertionError("context mismatch must skip supervisor synthesis")
        return {
            "specialists": ["POLICY", "EVIDENCE"],
            "policy_query": "商品质量问题退货政策",
            "reason_codes": ["FORMAL_REVIEW"],
        }


class ParentTools:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def call(self, name: str, arguments: dict[str, object]) -> ToolResult:
        self.calls.append((name, dict(arguments)))
        if name == "get_after_sales_ticket":
            return ToolResult(
                ok=True,
                name=name,
                data={
                    "ticket_id": "9001",
                    "order_id": "8001",
                    "status": "PENDING_REVIEW",
                    "merchant_code": "MERCHANT_DEMO",
                    "policy_version": "v2",
                    "product_name": "蓝牙耳机",
                    "category": "headphone",
                    "after_sales_type": "RETURN_REFUND",
                    "description": "耳机外壳破裂",
                    "after_sales_applied_at": "2026-07-01T10:00:00+08:00",
                    "context_version": "ctx-current",
                    "evidence_urls": ["https://example.invalid/a.jpg"],
                },
            )
        if name == "submit_ai_review":
            return ToolResult(
                ok=True,
                name=name,
                data={
                    "review_applied": True,
                    "verdict": arguments["verdict"],
                    "status": "PENDING_REVIEW",
                },
            )
        raise AssertionError(f"unexpected parent tool: {name}")


class StalePolicyWorkflow:
    def handle(self, task: PolicyTask) -> PolicyAssessment:
        return PolicyAssessment(
            context_version="ctx-stale",
            success=True,
            trusted_policy_eligible=True,
            policy_version_matched=True,
            filter_level="strict",
            reranker_succeeded=True,
            retrieval_mode="hybrid_reranked",
            policy_match_score=0.9,
        )


class CurrentEvidenceWorkflow:
    def handle(self, task: EvidenceTask) -> EvidenceAssessment:
        return EvidenceAssessment(
            context_version=task.context_version,
            success=True,
            visual_verifiable=True,
            evidence_consistent=True,
            visual_confidence=0.9,
        )


def test_specialist_context_version_mismatch_fails_closed_without_synthesis() -> None:
    tools = ParentTools()
    llm = PlanningOnlyLlm()
    graph = FormalReviewWorkflow(
        tools=tools,
        llm=llm,
        policy_workflow=StalePolicyWorkflow(),
        evidence_workflow=CurrentEvidenceWorkflow(),
    )

    result = graph.handle(
        {
            "user_id": "7",
            "session_id": "12",
            "ticket_id": "9001",
            "review_request_id": "event-1",
            "order_id": "8001",
            "message": "请进行AI初审",
            "client_context": {"source": "kafka"},
        }
    )

    assert llm.calls == 0
    assert result["raw"]["gate_action"] == "MANUAL_REVIEW"
    assert result["raw"]["gate_reasons"] == [
        "specialist_context_version_mismatch"
    ]
    assert result["raw"]["failure_reason"] == (
        "specialist_context_version_mismatch"
    )
    assert tools.calls[-1][0] == "submit_ai_review"
    assert tools.calls[-1][1]["verdict"] == "MANUAL_REVIEW_REQUIRED"


class ReviewLlm:
    def __init__(self) -> None:
        self.calls = 0
        self.synthesis_calls = 0
        self.user_prompts: list[str] = []

    def chat_json(self, **kwargs):
        self.calls += 1
        self.user_prompts.append(str(kwargs.get("user_prompt") or ""))
        if self.calls == 1:
            return {
                "specialists": ["POLICY", "EVIDENCE"],
                "policy_query": "耳机质量问题退货政策及凭证要求",
                "reason_codes": ["FORMAL_REVIEW"],
            }
        return {
            "proposed_verdict": "APPROVE",
            "reason": "政策和证据均满足审核条件。",
            "confidence": 0.94,
            "risk_reasons": [],
            "assistant_reply": "智能初审已完成。",
        }

    def generate_structured(self, *, system_prompt, user_prompt, schema, **kwargs):
        self.calls += 1
        self.user_prompts.append(str(user_prompt or ""))
        if "proposed_verdict" in (schema.get("properties") or {}):
            self.synthesis_calls += 1
        return {
            "proposed_verdict": "APPROVE",
            "reason": "政策和证据均满足审核条件。",
            "confidence": 0.94,
            "risk_reasons": [],
            "assistant_reply": "智能初审已完成。",
        }


class ReviewTools:
    def __init__(
        self,
        *,
        trusted: bool = True,
        has_evidence: bool = True,
        has_description: bool = True,
        optional_missing_evidence: bool = False,
        policy_score: float = 0.91,
        policy_threshold: float = 0.55,
        visual_score: float = 0.96,
        vision_failure: bool = False,
        evidence_revision: int = 0,
        stale_evidence_request_once: bool = False,
    ) -> None:
        self.trusted = trusted
        self.has_evidence = has_evidence
        self.has_description = has_description
        self.optional_missing_evidence = optional_missing_evidence
        self.policy_score = policy_score
        self.policy_threshold = policy_threshold
        self.visual_score = visual_score
        self.vision_failure = vision_failure
        self.evidence_revision = evidence_revision
        self.stale_evidence_request_once = stale_evidence_request_once
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.trace_ids: list[str | None] = []

    def call(self, name: str, arguments: dict[str, object]) -> ToolResult:
        self.trace_ids.append(current_trace_id())
        self.calls.append((name, dict(arguments)))
        if name == "get_after_sales_ticket":
            return ToolResult(
                ok=True,
                name=name,
                data={
                    "ticket_id": "90071992547409931",
                    "ticket_no": "AS-001",
                    "order_id": "90071992547409932",
                    "status": "PENDING_REVIEW",
                    "merchant_code": "MERCHANT_DEMO",
                    "policy_version": "v2",
                    "product_name": "蓝牙耳机",
                    "category": "headphone",
                    "after_sales_type": "RETURN_REFUND",
                    "reason": "QUALITY",
                    "description": (
                        "刚拆封使用就发现耳机外壳破裂，希望退款。"
                        if self.has_description
                        else ""
                    ),
                    "after_sales_applied_at": "2026-07-01T10:00:00+08:00",
                    "context_version": "ctx-java-1",
                    "evidence_revision": self.evidence_revision,
                    "evidence_urls": (
                        ["https://example.invalid/evidence.jpg"]
                        if self.has_evidence
                        else []
                    ),
                },
            )
        if name == "retrieve_knowledge":
            return ToolResult(
                ok=True,
                name=name,
                data={
                    "mode": "hybrid_reranked",
                    "filter_level": "strict",
                    "reranker_succeeded": True,
                    "trusted_policy_eligible": self.trusted,
                    "threshold": self.policy_threshold,
                    "hits": (
                        [
                            {
                                "source_type": "after_sales_policy",
                                "merchant_code": "MERCHANT_DEMO",
                                "policy_version": "v2",
                                "trusted_policy_eligible": True,
                                "relaxation_level": "strict",
                                "rerank_score": self.policy_score,
                                "threshold": self.policy_threshold,
                                "valid_from": "2026-01-01T00:00:00+08:00",
                                "valid_to": "2027-01-01T00:00:00+08:00",
                                "metadata": {
                                    "source_type": "after_sales_policy",
                                    "merchant_code": "MERCHANT_DEMO",
                                    "policy_version": "v2",
                                    "default_evidence": ["商品问题图片"],
                                },
                                "citations": [
                                    {
                                        "source_code": "POLICY-001",
                                        "chunk_id": "chunk-001",
                                    }
                                ],
                            }
                        ]
                        if self.trusted
                        else []
                    ),
                },
            )
        if name == "review_images":
            if self.vision_failure:
                return ToolResult(
                    ok=False,
                    name=name,
                    error="upstream vision provider timeout",
                    error_category="service_unavailable",
                    retryable=True,
                )
            return ToolResult(
                ok=True,
                name=name,
                data={
                    "success": True,
                    "has_damage_area": self.has_evidence,
                    "missing_visual_evidence": (
                        ["外包装照片", "物流面单照片"]
                        if self.has_evidence and self.optional_missing_evidence
                        else ([] if self.has_evidence else ["商品问题图片"])
                    ),
                    "confidence": self.visual_score if self.has_evidence else 0.2,
                    "items": [{"confidence": self.visual_score}],
                },
            )
        if name == "submit_ai_review":
            return ToolResult(
                ok=True,
                name=name,
                data={
                    "review_applied": True,
                    "verdict": arguments["verdict"],
                    "status": (
                        "PROCESSING"
                        if arguments["verdict"] == "APPROVE"
                        else "PENDING_REVIEW"
                    ),
                },
            )
        if name == "request_missing_evidence":
            if self.stale_evidence_request_once:
                self.stale_evidence_request_once = False
                self.evidence_revision += 1
                return ToolResult(
                    ok=True,
                    name=name,
                    data={
                        "review_reject_reason": "STALE_EVIDENCE",
                        "current_evidence_revision": self.evidence_revision,
                    },
                )
            return ToolResult(
                ok=True,
                name=name,
                data={"message_id": "100", "session_id": "12"},
            )
        raise AssertionError(f"unexpected tool: {name}")


def payload() -> dict[str, object]:
    return {
        "user_id": "7",
        "session_id": "12",
        "ticket_id": "90071992547409931",
        "review_request_id": "event-1",
        "order_id": "90071992547409932",
        "message": "售后申请已提交，请进行AI初审。",
        "client_context": {"source": "kafka"},
    }


def test_formal_review_skill_runs_workflows_and_submits_approved_proposal() -> None:
    tools = ReviewTools()
    graph = FormalReviewWorkflow(tools=tools, llm=ReviewLlm(), auto_approve_enabled=True)
    trace = TraceRecorder(
        request_type="kafka_review",
        trace_id="1234567890abcdef1234567890abcdef",
    )

    result = graph.handle(payload(), trace)

    assert result["raw"]["runtime"] == "formal_review_skill"
    assert result["raw"]["review_mode"] == "SOP_AUTOMATED"
    assert result["raw"]["escalation_reasons"] == []
    assert set(result["raw"]["skill_versions"]) == {
        "formal-review",
    }
    assert graph.llm.calls == 0
    assert graph.llm.synthesis_calls == 0
    assert result["raw"]["gate_action"] == "SUBMIT_REVIEW"
    called = [name for name, _ in tools.calls]
    assert called[0] == "get_after_sales_ticket"
    assert set(called[1:3]) == {"retrieve_knowledge", "review_images"}
    assert called[-1] == "submit_ai_review"
    assert tools.calls[-1][1]["verdict"] == "APPROVE"
    assert tools.calls[-1][1]["ai_review_confidence"] == 0.9565
    assert tools.calls[-1][1]["model_confidence"] == 0.0
    assert tools.calls[-1][1]["confidence_model_version"] == "deterministic-v1"
    assert tools.calls[-1][1]["confidence_breakdown"]["kind"] == (
        "deterministic_decision_support"
    )
    assert tools.calls[-1][1]["skill_versions"] == result["raw"][
        "skill_versions"
    ]
    assert result["review_result"]["review_applied"] is True
    assert set(tools.trace_ids) == {trace.trace_id}
    serialized = trace.to_dict()
    names = [step["name"] for step in serialized["steps"]]
    assert names[0] == "formal_review_skill"
    assert {
        "review_load_trusted_context",
        "review_sop_plan",
        "review_policy_workflow",
        "review_evidence_workflow",
        "review_synthesis",
        "review_deterministic_gate",
        "java_submit_review",
    }.issubset(names)
    synthesize_step = next(
        step
        for step in serialized["steps"]
        if step["name"] == "review_synthesis"
    )
    assert synthesize_step["details"]["confidence"] == 0.9565
    assert synthesize_step["details"]["model_confidence"] == 0.0
    assert synthesize_step["details"]["confidence_breakdown"]["signals"] == {
        "policy_relevance": 0.91,
        "policy_threshold": 0.55,
        "visual_confidence": 0.96,
        "policy_integrity": 1.0,
        "evidence_integrity": 1.0,
    }
    assert all(step["status"] == "SUCCESS" for step in serialized["steps"])
    policy_step = next(
        step for step in serialized["steps"]
        if step["name"] == "review_policy_workflow"
    )
    evidence_step = next(
        step for step in serialized["steps"]
        if step["name"] == "review_evidence_workflow"
    )
    assert policy_step["details"]["skill_name"] == (
        "formal-review"
    )
    assert evidence_step["details"]["skill_name"] == (
        "formal-review"
    )
    vision_arguments = next(
        arguments for name, arguments in tools.calls
        if name == "review_images"
    )
    assert vision_arguments["skill_name"] == "formal-review"
    assert vision_arguments["skill_version"] == result["raw"][
        "skill_versions"
    ]["formal-review"]
    assert "不得绕过确定性 Gate" in vision_arguments["skill_instructions"]
    assert "# 凭证审核工作流" in vision_arguments["skill_instructions"]
    assert graph.skills.cache_state() == {
        "skills": ("formal-review",),
        "references": (
            "formal-review/evidence-workflow.md",
            "formal-review/policy-workflow.md",
        ),
    }


def test_formal_review_fails_fast_when_required_skills_are_missing(
    tmp_path,
) -> None:
    with pytest.raises(
        RuntimeError,
        match="required formal review skill is missing",
    ):
        FormalReviewWorkflow(
            tools=ReviewTools(),
            llm=ReviewLlm(),
            skills=AgentSkillRegistry(root=tmp_path),
        )


def test_policy_score_above_configured_threshold_can_pass_formal_review() -> None:
    tools = ReviewTools(policy_score=0.57, policy_threshold=0.55)
    graph = FormalReviewWorkflow(tools=tools, llm=ReviewLlm(), auto_approve_enabled=True)

    result = graph.handle(payload())

    assert result["raw"]["gate_action"] == "SUBMIT_REVIEW"
    assert tools.calls[-1][1]["verdict"] == "APPROVE"
    assert tools.calls[-1][1]["policy_match_score"] == 0.57


def test_low_deterministic_confidence_forces_manual_review() -> None:
    tools = ReviewTools(policy_score=0.55, visual_score=0.2)
    graph = FormalReviewWorkflow(tools=tools, llm=ReviewLlm())

    result = graph.handle(payload())

    assert result["raw"]["gate_action"] == "MANUAL_REVIEW"
    assert result["raw"]["gate_reasons"] == ["visual_confidence_below_threshold"]
    assert tools.calls[-1][1]["verdict"] == "MANUAL_REVIEW_REQUIRED"
    assert tools.calls[-1][1]["ai_review_confidence"] == 0.6025
    assert tools.calls[-1][1]["model_confidence"] == 0.94
    assert graph.llm.synthesis_calls == 1
    assert result["raw"]["review_mode"] == "COMPLEX_SKILL_REVIEW"
    assert result["raw"]["escalation_reasons"] == [
        "visual_evidence_uncertain"
    ]


def test_vision_service_failure_is_persisted_as_manual_review_with_safe_user_reply() -> None:
    tools = ReviewTools(vision_failure=True)
    graph = FormalReviewWorkflow(tools=tools, llm=ReviewLlm())

    result = graph.handle(payload())

    assert result["raw"]["gate_action"] == "MANUAL_REVIEW"
    assert result["raw"]["gate_reasons"] == ["evidence_service_failed"]
    assert tools.calls[-1][0] == "submit_ai_review"
    assert tools.calls[-1][1]["verdict"] == "MANUAL_REVIEW_REQUIRED"
    assert result["need_human"] is True
    assert "timeout" not in result["assistant_reply"].lower()
    assert "service_unavailable" not in result["assistant_reply"].lower()


def test_policy_query_is_built_from_trusted_ticket_facts() -> None:
    tools = ReviewTools()
    graph = FormalReviewWorkflow(tools=tools, llm=ReviewLlm())

    graph.handle(payload())

    retrieval = next(arguments for name, arguments in tools.calls if name == "retrieve_knowledge")
    assert "刚拆封使用就发现耳机外壳破裂，希望退款。" in retrieval["query"]
    assert "蓝牙耳机" in retrieval["query"]
    # Structured taxonomy remains a hard retrieval filter/context field. Mixing
    # it into the natural-language rerank query depresses otherwise relevant
    # policy scores.
    assert "headphone" not in retrieval["query"]
    assert "RETURN_REFUND" not in retrieval["query"]


def test_graph_requests_evidence_without_submitting_a_review() -> None:
    tools = ReviewTools(has_evidence=False)
    llm = ReviewLlm()
    graph = FormalReviewWorkflow(tools=tools, llm=llm, checkpointer=InMemorySaver())

    result = graph.handle(payload())

    assert result["raw"]["gate_action"] == "REQUEST_EVIDENCE"
    assert [name for name, _ in tools.calls] == [
        "get_after_sales_ticket",
        "request_missing_evidence",
    ]
    assert llm.calls == 0
    assert result["evidence_needed"] == ["商品问题图片"]
    assert result["raw"]["evidence_request_applied"] is True
    assert set(result["raw"]["skill_versions"]) == {
        "formal-review",
        "evidence-request",
    }
    assert graph.skills.cache_state()["skills"] == (
        "evidence-request",
        "formal-review",
    )


def test_stale_evidence_request_refreshes_same_review_without_manual_handoff() -> None:
    tools = ReviewTools(has_evidence=False, stale_evidence_request_once=True)
    graph = FormalReviewWorkflow(
        tools=tools,
        llm=ReviewLlm(),
        checkpointer=InMemorySaver(),
        auto_approve_enabled=True,
    )

    result = graph.handle(payload())

    names = [name for name, _ in tools.calls]
    assert names.count("get_after_sales_ticket") == 2
    assert names.count("request_missing_evidence") == 2
    assert "submit_ai_review" not in names
    assert result["raw"]["paused"] is True
    assert result["raw"]["evidence_request_applied"] is True
    assert result["raw"]["paused"] is True


def test_graph_requests_problem_description_before_running_workflows() -> None:
    tools = ReviewTools(has_description=False)
    llm = ReviewLlm()
    graph = FormalReviewWorkflow(tools=tools, llm=llm, checkpointer=InMemorySaver())

    result = graph.handle(payload())

    assert result["raw"]["gate_action"] == "REQUEST_EVIDENCE"
    assert [name for name, _ in tools.calls] == [
        "get_after_sales_ticket",
        "request_missing_evidence",
    ]
    assert llm.calls == 0
    assert result["evidence_needed"] == ["问题描述"]


def test_graph_requests_evidence_before_policy_uncertainty_handoff() -> None:
    tools = ReviewTools(trusted=False, has_evidence=False)
    graph = FormalReviewWorkflow(
        tools=tools,
        llm=ReviewLlm(),
        checkpointer=InMemorySaver(),
        auto_approve_enabled=True,
    )

    result = graph.handle(payload())

    assert result["raw"]["gate_action"] == "REQUEST_EVIDENCE"
    assert result["raw"]["gate_reasons"] == ["evidence_missing"]
    assert tools.calls[-1][0] == "request_missing_evidence"
    assert "submit_ai_review" not in [name for name, _ in tools.calls]


def test_resume_same_review_refreshes_evidence_and_low_confidence_goes_manual() -> None:
    tools = ReviewTools(has_evidence=False, visual_score=0.2)
    graph = FormalReviewWorkflow(
        tools=tools,
        llm=ReviewLlm(),
        checkpointer=InMemorySaver(),
        auto_approve_enabled=True,
    )

    waiting = graph.start(payload())
    assert waiting["raw"]["paused"] is True
    assert [name for name, _ in tools.calls].count("request_missing_evidence") == 1

    tools.has_evidence = True
    tools.evidence_revision = 1
    resumed = graph.resume(
        "event-1",
        {"event_id": "resume-1", "evidence_revision": 1},
    )

    assert resumed["raw"]["paused"] is False
    assert resumed["raw"]["gate_action"] == "MANUAL_REVIEW"
    assert resumed["raw"]["gate_reasons"] == ["visual_confidence_below_threshold"]
    assert [name for name, _ in tools.calls].count("request_missing_evidence") == 1
    assert tools.calls[-1][0] == "submit_ai_review"
    assert tools.calls[-1][1]["review_request_id"] == "event-1"
    assert tools.calls[-1][1]["expected_evidence_revision"] == 1


def test_deterministic_gate_overrides_approve_when_policy_is_untrusted() -> None:
    tools = ReviewTools(trusted=False)
    graph = FormalReviewWorkflow(tools=tools, llm=ReviewLlm())

    result = graph.handle(payload())

    assert result["raw"]["gate_action"] == "MANUAL_REVIEW"
    assert tools.calls[-1][0] == "submit_ai_review"
    assert tools.calls[-1][1]["verdict"] == "MANUAL_REVIEW_REQUIRED"
    assert "policy_not_trusted" in result["raw"]["gate_reasons"]
    assert graph.llm.synthesis_calls == 1
    assert result["raw"]["review_mode"] == "COMPLEX_SKILL_REVIEW"
    assert "policy_not_authoritative" in result["raw"]["escalation_reasons"]


def test_optional_package_and_waybill_do_not_block_formal_review() -> None:
    tools = ReviewTools(optional_missing_evidence=True)
    graph = FormalReviewWorkflow(tools=tools, llm=ReviewLlm(), auto_approve_enabled=True)

    result = graph.handle({**payload(), "message": ""})

    assert result["raw"]["gate_action"] == "SUBMIT_REVIEW"
    assert tools.calls[-1][0] == "submit_ai_review"
    assert graph.llm.calls == 0
    retrieval = next(
        arguments
        for name, arguments in tools.calls
        if name == "retrieve_knowledge"
    )
    assert "刚拆封使用就发现耳机外壳破裂，希望退款。" in retrieval["query"]


def test_java_relative_upload_url_is_resolved_for_formal_vision_review(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "AFTERSALES_JAVA_TOOL_BASE_URL",
        "http://java:8080/api/internal/agent-tools",
    )

    context = TrustedCaseContext.from_ticket(
        {
            "user_id": "7",
            "session_id": "12",
            "ticket_id": "21",
            "order_id": "31",
            "client_context": {"source": "kafka"},
        },
        {
            "ticket_id": "21",
            "order_id": "31",
            "status": "PENDING_REVIEW",
            "evidence_urls": ["/uploads/2026/07/30/damage.png"],
        },
    )

    assert context.attachments[0]["source"] == (
        "http://java:8080/api/uploads/2026/07/30/damage.png"
    )
