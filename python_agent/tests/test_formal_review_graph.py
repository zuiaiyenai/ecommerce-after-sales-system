from __future__ import annotations

from after_sales_agent.application.formal_review import FormalReviewGraph
from after_sales_agent.application.tool_registry import ToolResult
from after_sales_agent.infra.request_tracing import TraceRecorder, current_trace_id


class ReviewLlm:
    def __init__(self) -> None:
        self.calls = 0
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
    ) -> None:
        self.trusted = trusted
        self.has_evidence = has_evidence
        self.has_description = has_description
        self.optional_missing_evidence = optional_missing_evidence
        self.policy_score = policy_score
        self.policy_threshold = policy_threshold
        self.visual_score = visual_score
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


def test_graph_runs_specialist_agents_and_submits_approved_proposal() -> None:
    tools = ReviewTools()
    graph = FormalReviewGraph(tools=tools, llm=ReviewLlm())
    trace = TraceRecorder(
        request_type="kafka_review",
        trace_id="1234567890abcdef1234567890abcdef",
    )

    result = graph.handle(payload(), trace)

    assert result["raw"]["runtime"] == "langgraph_multi_agent_review"
    assert result["raw"]["gate_action"] == "SUBMIT_REVIEW"
    called = [name for name, _ in tools.calls]
    assert called[0] == "get_after_sales_ticket"
    assert set(called[1:3]) == {"retrieve_knowledge", "review_images"}
    assert called[-1] == "submit_ai_review"
    assert tools.calls[-1][1]["verdict"] == "APPROVE"
    assert tools.calls[-1][1]["ai_review_confidence"] == 0.9565
    assert tools.calls[-1][1]["model_confidence"] == 0.94
    assert tools.calls[-1][1]["confidence_model_version"] == "deterministic-v1"
    assert tools.calls[-1][1]["confidence_breakdown"]["kind"] == (
        "deterministic_decision_support"
    )
    assert result["review_result"]["review_applied"] is True
    assert set(tools.trace_ids) == {trace.trace_id}
    serialized = trace.to_dict()
    names = [step["name"] for step in serialized["steps"]]
    assert names[0] == "formal_review_graph"
    assert {
        "review_load_trusted_context",
        "review_supervisor_plan",
        "review_policy_agent",
        "review_evidence_agent",
        "review_supervisor_synthesize",
        "review_deterministic_gate",
        "java_submit_review",
    }.issubset(names)
    synthesize_step = next(
        step
        for step in serialized["steps"]
        if step["name"] == "review_supervisor_synthesize"
    )
    assert synthesize_step["details"]["confidence"] == 0.9565
    assert synthesize_step["details"]["model_confidence"] == 0.94
    assert synthesize_step["details"]["confidence_breakdown"]["signals"] == {
        "policy_relevance": 0.91,
        "policy_threshold": 0.55,
        "visual_confidence": 0.96,
        "policy_integrity": 1.0,
        "evidence_integrity": 1.0,
    }
    assert all(step["status"] == "SUCCESS" for step in serialized["steps"])


def test_policy_score_above_configured_threshold_can_pass_formal_review() -> None:
    tools = ReviewTools(policy_score=0.57, policy_threshold=0.55)
    graph = FormalReviewGraph(tools=tools, llm=ReviewLlm())

    result = graph.handle(payload())

    assert result["raw"]["gate_action"] == "SUBMIT_REVIEW"
    assert tools.calls[-1][1]["verdict"] == "APPROVE"
    assert tools.calls[-1][1]["policy_match_score"] == 0.57


def test_low_deterministic_confidence_forces_manual_review() -> None:
    tools = ReviewTools(policy_score=0.55, visual_score=0.2)
    graph = FormalReviewGraph(tools=tools, llm=ReviewLlm())

    result = graph.handle(payload())

    assert result["raw"]["gate_action"] == "MANUAL_REVIEW"
    assert result["raw"]["gate_reasons"] == ["review_confidence_below_threshold"]
    assert tools.calls[-1][1]["verdict"] == "MANUAL_REVIEW_REQUIRED"
    assert tools.calls[-1][1]["ai_review_confidence"] == 0.6025
    assert tools.calls[-1][1]["model_confidence"] == 0.94


def test_policy_query_is_built_from_trusted_ticket_facts() -> None:
    tools = ReviewTools()
    graph = FormalReviewGraph(tools=tools, llm=ReviewLlm())

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
    graph = FormalReviewGraph(tools=tools, llm=llm)

    result = graph.handle(payload())

    assert result["raw"]["gate_action"] == "REQUEST_EVIDENCE"
    assert [name for name, _ in tools.calls] == [
        "get_after_sales_ticket",
        "request_missing_evidence",
    ]
    assert llm.calls == 0
    assert result["evidence_needed"] == ["商品问题图片"]
    assert result["raw"]["evidence_request_applied"] is True


def test_graph_requests_problem_description_before_running_subagents() -> None:
    tools = ReviewTools(has_description=False)
    llm = ReviewLlm()
    graph = FormalReviewGraph(tools=tools, llm=llm)

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
    graph = FormalReviewGraph(tools=tools, llm=ReviewLlm())

    result = graph.handle(payload())

    assert result["raw"]["gate_action"] == "REQUEST_EVIDENCE"
    assert result["raw"]["gate_reasons"] == ["evidence_missing"]
    assert tools.calls[-1][0] == "request_missing_evidence"
    assert "submit_ai_review" not in [name for name, _ in tools.calls]


def test_deterministic_gate_overrides_approve_when_policy_is_untrusted() -> None:
    tools = ReviewTools(trusted=False)
    graph = FormalReviewGraph(tools=tools, llm=ReviewLlm())

    result = graph.handle(payload())

    assert result["raw"]["gate_action"] == "MANUAL_REVIEW"
    assert tools.calls[-1][0] == "submit_ai_review"
    assert tools.calls[-1][1]["verdict"] == "MANUAL_REVIEW_REQUIRED"
    assert "policy_not_trusted" in result["raw"]["gate_reasons"]


def test_optional_package_and_waybill_do_not_block_formal_review() -> None:
    tools = ReviewTools(optional_missing_evidence=True)
    graph = FormalReviewGraph(tools=tools, llm=ReviewLlm())

    result = graph.handle({**payload(), "message": ""})

    assert result["raw"]["gate_action"] == "SUBMIT_REVIEW"
    assert tools.calls[-1][0] == "submit_ai_review"
    assert "刚拆封使用就发现耳机外壳破裂，希望退款。" in graph.llm.user_prompts[0]
