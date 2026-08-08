from __future__ import annotations

from after_sales_agent.application.formal_review.contracts import TrustedCaseContext


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
