from __future__ import annotations

from dataclasses import fields

from after_sales_agent.application.formal_review import (
    EvidenceAssessment,
    EvidenceSubagentGraph,
    EvidenceTask,
    FormalReviewGraph,
    PolicyAssessment,
    PolicySubagentGraph,
    PolicyTask,
)
from after_sales_agent.application.tool_registry import ToolResult
from after_sales_agent.application.rag_query_rewrite import (
    RagQueryCandidate,
    RagRewriteDecision,
    RagRewriteModelError,
)


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
    )


def test_specialist_tasks_expose_only_domain_specific_context() -> None:
    policy_fields = {item.name for item in fields(PolicyTask)}
    evidence_fields = {item.name for item in fields(EvidenceTask)}

    assert "attachments" not in policy_fields
    assert "policy_assessment" not in evidence_fields
    assert "policy_version" not in evidence_fields
    assert "review_proposal" not in policy_fields | evidence_fields
    assert "gate_action" not in policy_fields | evidence_fields


def test_policy_subagent_runs_with_private_task_and_policy_only_port() -> None:
    port = PolicyPort()
    subagent = PolicySubagentGraph(port=port)
    first = subagent.handle(policy_task("ctx-1"))
    second = subagent.handle(policy_task("ctx-2"))

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


def test_policy_subagent_rewrites_once_and_accepts_trusted_second_pass() -> None:
    task = policy_task()
    port = ControlledPolicyPort(
        _untrusted_policy_result(),
        _trusted_multi_policy_result(task),
    )
    rewrite = RewriteService()

    assessment = PolicySubagentGraph(
        port=port,
        rewrite_service=rewrite,
    ).handle(task)

    assert [name for name, _ in port.calls] == ["retrieve", "retrieve_multi"]
    assert len(rewrite.calls) == 1
    assert port.calls[1][1] == (
        "headphone quality return special conditions",
    )
    assert assessment.trusted_policy_eligible is True
    assert assessment.retrieval_mode == "multi_query_reranked"


def test_policy_subagent_second_pass_is_terminal_even_when_still_untrusted() -> None:
    port = ControlledPolicyPort(
        _untrusted_policy_result(),
        _untrusted_policy_result(),
    )
    rewrite = RewriteService()

    assessment = PolicySubagentGraph(
        port=port,
        rewrite_service=rewrite,
    ).handle(policy_task())

    assert [name for name, _ in port.calls] == ["retrieve", "retrieve_multi"]
    assert len(rewrite.calls) == 1
    assert assessment.trusted_policy_eligible is False


def test_policy_subagent_does_not_rewrite_infrastructure_failure() -> None:
    port = ControlledPolicyPort(
        _untrusted_policy_result(
            mode="hybrid_rrf_degraded",
            failure_reason="EMBEDDING_ERROR",
        ),
        _untrusted_policy_result(),
    )
    rewrite = RewriteService()

    assessment = PolicySubagentGraph(
        port=port,
        rewrite_service=rewrite,
    ).handle(policy_task())

    assert [name for name, _ in port.calls] == ["retrieve"]
    assert rewrite.calls == []
    assert assessment.trusted_policy_eligible is False


def test_policy_subagent_rewrite_failure_fails_closed_without_second_call() -> None:
    port = ControlledPolicyPort(
        _untrusted_policy_result(),
        _untrusted_policy_result(),
    )
    rewrite = RewriteService(fail=True)

    assessment = PolicySubagentGraph(
        port=port,
        rewrite_service=rewrite,
    ).handle(policy_task())

    assert [name for name, _ in port.calls] == ["retrieve"]
    assert len(rewrite.calls) == 1
    assert assessment.trusted_policy_eligible is False


def test_evidence_subagent_without_attachments_does_not_call_vision_port() -> None:
    port = EvidencePort()
    subagent = EvidenceSubagentGraph(port=port)

    assessment = subagent.handle(evidence_task(with_attachments=False))

    assert not hasattr(port, "call")
    assert port.tasks == []
    assert assessment.context_version == "ctx-1"
    assert assessment.visual_verifiable is False
    assert assessment.missing_evidence


def test_evidence_subagent_uses_only_evidence_task_for_visual_review() -> None:
    port = EvidencePort()
    subagent = EvidenceSubagentGraph(port=port)

    assessment = subagent.handle(evidence_task())

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


def test_evidence_subagent_accepts_visible_functional_issue_without_damage() -> None:
    assessment = EvidenceSubagentGraph(
        port=FunctionalEvidencePort()
    ).handle(evidence_task())

    assert assessment.visual_verifiable is True
    assert assessment.evidence_consistent is True
    assert assessment.evidence_categories == ("functional_issue",)
    assert assessment.observed_issue_types == ("screen_error",)
    assert "商品问题图片" in assessment.satisfied_evidence


def test_evidence_subagent_marks_contradictory_visual_evidence_as_risk() -> None:
    assessment = EvidenceSubagentGraph(
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


class StalePolicySubagent:
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


class CurrentEvidenceSubagent:
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
    graph = FormalReviewGraph(
        tools=tools,
        llm=llm,
        policy_subagent=StalePolicySubagent(),
        evidence_subagent=CurrentEvidenceSubagent(),
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

    assert llm.calls == 1
    assert result["raw"]["gate_action"] == "MANUAL_REVIEW"
    assert result["raw"]["gate_reasons"] == [
        "specialist_context_version_mismatch"
    ]
    assert result["raw"]["failure_reason"] == (
        "specialist_context_version_mismatch"
    )
    assert tools.calls[-1][0] == "submit_ai_review"
    assert tools.calls[-1][1]["verdict"] == "MANUAL_REVIEW_REQUIRED"
