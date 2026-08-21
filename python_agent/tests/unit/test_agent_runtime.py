from __future__ import annotations

from typing import Any

from after_sales_agent.agent import AfterSalesAgent


class FakeConsultationWorkflow:
    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], Any]] = []

    def handle(
        self,
        payload: dict[str, Any],
        trace_recorder: Any | None = None,
    ) -> dict[str, Any]:
        self.calls.append((payload, trace_recorder))
        return {"route": "chat"}


class FakeFormalReviewWorkflow:
    def __init__(self) -> None:
        self.start_calls: list[tuple[dict[str, Any], Any]] = []
        self.resume_calls: list[tuple[str, dict[str, Any], Any]] = []

    def start(
        self,
        payload: dict[str, Any],
        trace_recorder: Any | None = None,
    ) -> dict[str, Any]:
        self.start_calls.append((payload, trace_recorder))
        return {"route": "formal_review_start"}

    def resume(
        self,
        review_id: str,
        resume_signal: dict[str, Any],
        trace_recorder: Any | None = None,
    ) -> dict[str, Any]:
        self.resume_calls.append((review_id, resume_signal, trace_recorder))
        return {"route": "formal_review_resume"}


def build_agent() -> tuple[
    AfterSalesAgent,
    FakeConsultationWorkflow,
    FakeFormalReviewWorkflow,
]:
    chat = FakeConsultationWorkflow()
    formal_review = FakeFormalReviewWorkflow()
    agent = AfterSalesAgent(
        tools=object(),
        llm=object(),
        consultation_workflow=chat,
        formal_review_workflow=formal_review,
    )
    return agent, chat, formal_review


def test_handle_chat_delegates_to_consultation_workflow() -> None:
    agent, chat, formal_review = build_agent()
    payload = {"message": "查询退货政策"}
    trace = object()

    assert agent.handle_chat(payload, trace) == {"route": "chat"}
    assert chat.calls == [(payload, trace)]
    assert formal_review.start_calls == []


def test_formal_review_event_bypasses_consultation_workflow() -> None:
    agent, chat, formal_review = build_agent()
    payload = {"review_request_id": "review-1", "ticket_id": "ticket-1"}
    trace = object()

    assert agent.start_formal_review(payload, trace) == {
        "route": "formal_review_start"
    }
    assert formal_review.start_calls == [(payload, trace)]
    assert chat.calls == []


def test_resume_formal_review_delegates_to_same_workflow() -> None:
    agent, chat, formal_review = build_agent()
    signal = {"type": "EVIDENCE_UPDATED"}
    trace = object()

    assert agent.resume_formal_review("review-1", signal, trace) == {
        "route": "formal_review_resume"
    }
    assert formal_review.resume_calls == [("review-1", signal, trace)]
    assert chat.calls == []


def test_generic_http_handle_routes_to_consultation_workflow() -> None:
    agent, chat, formal_review = build_agent()
    payload = {"message": "查询物流进度"}

    assert agent.handle(payload) == {"route": "chat"}
    assert chat.calls == [(payload, None)]
    assert formal_review.start_calls == []


def test_generic_kafka_handle_routes_to_formal_review_workflow() -> None:
    agent, chat, formal_review = build_agent()
    payload = {
        "review_request_id": "review-1",
        "client_context": {"source": "kafka"},
    }

    assert agent.handle(payload) == {"route": "formal_review_start"}
    assert formal_review.start_calls == [(payload, None)]
    assert chat.calls == []
