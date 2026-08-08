from __future__ import annotations

import os
from typing import Any


def build_chat_entry_payload(
    data: dict[str, Any],
    emotion_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected = data.get("selected_order") if isinstance(data.get("selected_order"), dict) else {}
    order_id = data.get("order_id") or selected.get("order_id") or ""
    user_id = data.get("user_id") or selected.get("user_id") or "0"
    raw_client_context = (
        data.get("client_context")
        if isinstance(data.get("client_context"), dict)
        else {}
    )
    client_context = {
        key: value
        for key, value in raw_client_context.items()
        if key not in {"source", "event_id", "trusted_invocation"}
    }
    client_context["source"] = "java_gateway"
    if selected:
        client_context["selected_order_hint"] = {
            "order_id": selected.get("order_id"),
            "product_name": selected.get("product_name"),
            "merchant_code": selected.get("merchant_code"),
            "category": selected.get("category") or selected.get("product_category"),
            "policy_version": selected.get("policy_version"),
            "business_time": selected.get("business_time") or selected.get("create_time"),
            "status": selected.get("status"),
            "after_sales_status": selected.get("after_sales_status"),
            "uploaded_evidence": selected.get("uploaded_evidence") or [],
        }
    if emotion_context:
        client_context["emotion"] = emotion_context
    return {
        "user_id": str(user_id),
        "session_id": data.get("session_id"),
        "ticket_id": data.get("ticket_id"),
        "review_request_id": data.get("review_request_id"),
        "order_id": str(order_id) if order_id else "",
        "message": str(data.get("message") or ""),
        "attachments": list(data.get("attachments") or []),
        "recent_history": build_recent_history_payload(data.get("recent_history")),
        "history_summary": (
            data.get("history_summary")
            if isinstance(data.get("history_summary"), dict)
            else {}
        ),
        "client_context": client_context,
    }


# Compatibility for offline evaluation and callers outside the active runtime.
build_langgraph_entry_payload = build_chat_entry_payload


def build_recent_history_payload(
    payload_history: list[Any] | tuple[Any, ...] | None,
) -> list[dict[str, str]]:
    history: list[dict[str, str]] = []
    for item in payload_history or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        if role == "service":
            role = "assistant"
        if role not in {"user", "assistant"}:
            continue
        content = str(item.get("content") or "").strip()
        if content:
            history.append({"role": role, "content": content})
    limit = max(1, int(os.getenv("AGENT_RECENT_HISTORY_LIMIT", "10")))
    return history[-limit:]
