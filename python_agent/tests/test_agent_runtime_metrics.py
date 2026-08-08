from __future__ import annotations

from prometheus_client import CollectorRegistry

from after_sales_agent.infra.agent_metrics import AgentRuntimeMetrics


def test_runtime_metrics_use_fixed_labels_and_expose_latency_summary() -> None:
    metrics = AgentRuntimeMetrics()
    metrics.record_trace("/api/chat", {
        "total_duration_ms": 120,
        "steps": [
            {"name": "agentic_rag_chat", "duration_ms": 100},
            {"name": "user-controlled-step", "duration_ms": 999},
        ],
    })
    metrics.record_tool("search_user_orders", True)
    metrics.record_tool("user-controlled-tool", False, "something-dynamic")
    metrics.record_rag_mode("lexical_fallback_after_embedding_error")
    metrics.record_review("MANUAL_REVIEW_REQUIRED")
    metrics.record_handoff()
    metrics.record_formal_review(action="manual_review", success=True)

    snapshot = metrics.snapshot()

    assert snapshot["agent_request_total"] == {"/api/chat": 1}
    assert snapshot["agent_request_latency_ms"]["/api/chat"]["p95_recent"] == 120
    assert snapshot["agent_request_latency_ms"]["/api/chat"]["sample_window"] == 1
    assert snapshot["agent_step_latency_ms"]["agentic_rag_chat"]["max"] == 100
    assert "user-controlled-step" not in snapshot["agent_step_latency_ms"]
    assert snapshot["agent_tool_call_total"]["unknown"]["failure"] == 1
    assert snapshot["agent_tool_error_total"]["unknown"] == 1
    assert snapshot["agent_rag_mode_total"]["lexical_fallback"] == 1
    assert snapshot["agent_review_verdict_total"]["manual_required"] == 1
    assert snapshot["agent_handoff_total"] == 1
    assert snapshot["agent_formal_review_run_total"] == {
        "manual_review:success": 1
    }


def test_runtime_metrics_expose_prometheus_histograms_and_fixed_labels() -> None:
    metrics = AgentRuntimeMetrics(CollectorRegistry())
    metrics.record_trace("/api/chat", {
        "total_duration_ms": 250,
        "steps": [{"name": "agentic_rag_chat", "duration_ms": 200}],
    })
    metrics.record_tool("user-controlled-tool", False, "dynamic-error")
    metrics.record_rag_mode("pgvector")
    metrics.record_review("APPROVE")
    metrics.record_handoff()
    metrics.record_formal_review(action="submit_review", success=True)

    payload, content_type = metrics.prometheus_payload()
    body = payload.decode("utf-8")

    assert content_type.startswith("text/plain")
    assert 'agent_requests_total{route="/api/chat"} 1.0' in body
    assert 'agent_request_duration_seconds_count{route="/api/chat"} 1.0' in body
    assert 'agent_step_duration_seconds_count{step="agentic_rag_chat"} 1.0' in body
    assert 'agent_tool_calls_total{outcome="failure",tool="unknown"} 1.0' in body
    assert 'agent_tool_errors_total{category="unknown"} 1.0' in body
    assert 'agent_rag_retrievals_total{mode="pgvector"} 1.0' in body
    assert 'agent_review_verdicts_total{verdict="approve"} 1.0' in body
    assert "agent_handoffs_total 1.0" in body
    assert 'agent_formal_review_runs_total{action="submit_review",outcome="success"} 1.0' in body


def test_runtime_metrics_recognize_layered_retrieval_modes() -> None:
    metrics = AgentRuntimeMetrics()
    for mode in (
        "dense",
        "keyword",
        "rrf",
        "hybrid_reranked",
        "hybrid_rrf_degraded",
        "lexical_compatibility",
    ):
        metrics.record_rag_mode(mode)

    assert metrics.snapshot()["agent_rag_mode_total"] == {
        "compatibility": 1,
        "dense": 1,
        "keyword": 1,
        "rerank": 1,
        "rrf": 2,
    }


def test_runtime_metrics_record_kafka_review_node_steps() -> None:
    metrics = AgentRuntimeMetrics()
    metrics.record_trace(
        "/kafka/review",
        {
            "total_duration_ms": 420,
            "steps": [
                {"name": "kafka_idempotency_claim", "duration_ms": 2},
                {"name": "review_policy_agent", "duration_ms": 120},
                {"name": "review_evidence_agent", "duration_ms": 140},
                {"name": "review_deterministic_gate", "duration_ms": 1},
                {"name": "java_submit_review", "duration_ms": 30},
                {"name": "kafka_commit_offset", "duration_ms": 3},
            ],
        },
    )

    snapshot = metrics.snapshot()

    assert snapshot["agent_request_total"] == {"/kafka/review": 1}
    assert snapshot["agent_step_latency_ms"]["review_policy_agent"]["max"] == 120
    assert snapshot["agent_step_latency_ms"]["java_submit_review"]["max"] == 30
