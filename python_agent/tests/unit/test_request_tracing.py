from __future__ import annotations

import re
import logging

from after_sales_agent.infrastructure.request_tracing import (
    TraceRecorder,
    bind_trace_id,
    current_trace_id,
    normalize_trace_id,
    trace_id_from_seed,
)
from after_sales_agent.integrations.java_tool_client import JavaToolClient, JavaToolConfig


def test_trace_recorder_preserves_valid_id_and_serializes_it() -> None:
    trace_id = "0123456789abcdef0123456789abcdef"
    recorder = TraceRecorder("chat", trace_id=trace_id)

    assert recorder.to_dict()["trace_id"] == trace_id


def test_invalid_external_trace_id_is_replaced_and_event_seed_is_stable() -> None:
    generated = normalize_trace_id("../../not-a-trace")

    assert re.fullmatch(r"[0-9a-f]{32}", generated)
    assert trace_id_from_seed("event-1") == trace_id_from_seed("event-1")
    assert trace_id_from_seed("event-1") != trace_id_from_seed("event-2")


def test_java_tool_headers_propagate_bound_trace_context() -> None:
    trace_id = "fedcba9876543210fedcba9876543210"
    client = JavaToolClient(JavaToolConfig("http://localhost", internal_token="secret"))

    with bind_trace_id(trace_id):
        headers = client._headers()
        assert current_trace_id() == trace_id

    assert headers["X-Trace-Id"] == trace_id
    assert headers["X-Agent-Internal-Token"] == "secret"
    assert current_trace_id() is None


def test_trace_step_records_status_sequence_and_structured_logs(caplog) -> None:
    recorder = TraceRecorder(
        "kafka_review",
        trace_id="0123456789abcdef0123456789abcdef",
    )

    with caplog.at_level(logging.INFO, logger="after_sales_agent.trace"):
        with recorder.step("policy_agent", agent="policy") as step:
            step.details["trusted"] = True

    payload = recorder.to_dict()
    recorded = payload["steps"][0]
    assert recorded["sequence"] == 1
    assert recorded["status"] == "SUCCESS"
    assert recorded["error_type"] is None
    assert recorded["details"] == {"agent": "policy", "trusted": True}
    assert "trace_step_start" in caplog.text
    assert "trace_step_end" in caplog.text
    assert "step=policy_agent" in caplog.text


def test_trace_step_records_failure_type_without_swallowing_error() -> None:
    recorder = TraceRecorder("chat")

    try:
        with recorder.step("rag_retrieve_initial"):
            raise TimeoutError("retrieval timed out")
    except TimeoutError:
        pass

    recorded = recorder.to_dict()["steps"][0]
    assert recorded["status"] == "ERROR"
    assert recorded["error_type"] == "TimeoutError"
