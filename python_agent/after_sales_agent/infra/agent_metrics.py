from __future__ import annotations

from collections import Counter as CollectionCounter, deque
import threading
from typing import Any

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter as PrometheusCounter,
    Histogram,
    generate_latest,
)


class _PrometheusMetrics:
    """Prometheus instruments with bounded, pre-defined label dimensions."""

    def __init__(self, registry: CollectorRegistry) -> None:
        self.registry = registry
        self.requests = PrometheusCounter(
            "agent_requests", "Agent HTTP requests", ("route",), registry=registry
        )
        self.request_duration = Histogram(
            "agent_request_duration_seconds",
            "Agent HTTP request duration",
            ("route",),
            buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 90),
            registry=registry,
        )
        self.step_duration = Histogram(
            "agent_step_duration_seconds",
            "Agent trace step duration",
            ("step",),
            buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 90),
            registry=registry,
        )
        self.tool_calls = PrometheusCounter(
            "agent_tool_calls", "Agent tool calls", ("tool", "outcome"), registry=registry
        )
        self.tool_errors = PrometheusCounter(
            "agent_tool_errors", "Agent tool errors", ("category",), registry=registry
        )
        self.rag_retrievals = PrometheusCounter(
            "agent_rag_retrievals", "Agent RAG retrieval modes", ("mode",), registry=registry
        )
        self.review_verdicts = PrometheusCounter(
            "agent_review_verdicts", "Agent review verdicts", ("verdict",), registry=registry
        )
        self.handoffs = PrometheusCounter(
            "agent_handoffs", "Agent handoffs to human service", registry=registry
        )

    def payload(self) -> tuple[bytes, str]:
        return generate_latest(self.registry), CONTENT_TYPE_LATEST


class _LatencyStats:
    """All-time aggregate plus a bounded recent window for percentile estimates."""

    def __init__(self, window_size: int = 2048) -> None:
        self.count = 0
        self.total = 0
        self.maximum = 0
        self.samples: deque[int] = deque(maxlen=window_size)

    def observe(self, value: int) -> None:
        self.count += 1
        self.total += value
        self.maximum = max(self.maximum, value)
        self.samples.append(value)

    def snapshot(self) -> dict[str, float | int]:
        ordered = sorted(self.samples)
        p95_index = max(0, int((len(ordered) - 1) * 0.95))
        return {
            "count": self.count,
            "avg": round(self.total / self.count, 2) if self.count else 0.0,
            "p95_recent": ordered[p95_index] if ordered else 0,
            "max": self.maximum,
            "sample_window": len(ordered),
        }


class AgentRuntimeMetrics:
    """Thread-safe in-process metrics with fixed, low-cardinality labels."""

    KNOWN_TOOLS = {
        "search_user_orders", "get_order_detail", "get_existing_after_sales",
        "get_after_sales_ticket", "get_merchant_policy", "retrieve_knowledge",
        "review_images", "submit_ai_review", "handoff_to_human",
        "append_chat_message", "request_missing_evidence",
    }
    ERROR_CATEGORIES = {
        "validation", "permission", "not_found", "timeout",
        "service_unavailable", "guard_limit", "tool_error", "unknown",
    }
    TRACE_STEPS = {
        "read_request_body", "emotion_analyze", "langgraph_agent",
        "agent_tool_call", "text_model_call", "review_images",
    }

    def __init__(self, prometheus_registry: CollectorRegistry | None = None) -> None:
        self._lock = threading.Lock()
        self._request_total: CollectionCounter[str] = CollectionCounter()
        self._request_latency: dict[str, _LatencyStats] = {}
        self._tool_calls: CollectionCounter[tuple[str, str]] = CollectionCounter()
        self._tool_errors: CollectionCounter[str] = CollectionCounter()
        self._rag_modes: CollectionCounter[str] = CollectionCounter()
        self._review_verdicts: CollectionCounter[str] = CollectionCounter()
        self._handoffs = 0
        self._step_latency: dict[str, _LatencyStats] = {}
        self._prometheus = _PrometheusMetrics(prometheus_registry) if prometheus_registry is not None else None

    def record_trace(self, path: str, trace: dict[str, Any]) -> None:
        route = self._route(path)
        duration = self._non_negative_int(trace.get("total_duration_ms"))
        known_steps: list[tuple[str, int]] = []
        for item in trace.get("steps") or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "")
            if name in self.TRACE_STEPS:
                known_steps.append((name, self._non_negative_int(item.get("duration_ms"))))
        with self._lock:
            self._request_total[route] += 1
            self._request_latency.setdefault(route, _LatencyStats()).observe(duration)
            for name, step_duration in known_steps:
                self._step_latency.setdefault(name, _LatencyStats()).observe(step_duration)
        if self._prometheus is not None:
            self._prometheus.requests.labels(route=route).inc()
            self._prometheus.request_duration.labels(route=route).observe(duration / 1000)
            for name, step_duration in known_steps:
                self._prometheus.step_duration.labels(step=name).observe(step_duration / 1000)

    def record_tool(self, name: str, ok: bool, error_category: str | None = None) -> None:
        tool = name if name in self.KNOWN_TOOLS else "unknown"
        outcome = "success" if ok else "failure"
        category = str(error_category or "unknown").strip().lower()
        if category not in self.ERROR_CATEGORIES:
            category = "unknown"
        with self._lock:
            self._tool_calls[(tool, outcome)] += 1
            if not ok:
                self._tool_errors[category] += 1
        if self._prometheus is not None:
            self._prometheus.tool_calls.labels(tool=tool, outcome=outcome).inc()
            if not ok:
                self._prometheus.tool_errors.labels(category=category).inc()

    def record_rag_mode(self, mode: str | None) -> None:
        value = str(mode or "none").strip().lower()
        if "compatibility" in value:
            label = "compatibility"
        elif value == "dense" or value.startswith("dense_"):
            label = "dense"
        elif value == "keyword" or value.startswith("keyword_"):
            label = "keyword"
        elif "rerank" in value and "rrf" not in value:
            label = "rerank"
        elif value == "rrf" or "rrf" in value:
            label = "rrf"
        elif value == "pgvector":
            label = "pgvector"
        elif "relaxed" in value:
            label = "relaxed"
        elif "lexical" in value:
            label = "lexical_fallback"
        elif "local" in value:
            label = "local_fallback"
        elif "error" in value or "missing" in value or "not_configured" in value:
            label = "error"
        else:
            label = "none"
        with self._lock:
            self._rag_modes[label] += 1
        if self._prometheus is not None:
            self._prometheus.rag_retrievals.labels(mode=label).inc()

    def record_review(self, verdict: str) -> None:
        label = "approve" if str(verdict).upper() == "APPROVE" else "manual_required"
        with self._lock:
            self._review_verdicts[label] += 1
        if self._prometheus is not None:
            self._prometheus.review_verdicts.labels(verdict=label).inc()

    def record_handoff(self) -> None:
        with self._lock:
            self._handoffs += 1
        if self._prometheus is not None:
            self._prometheus.handoffs.inc()

    def prometheus_payload(self) -> tuple[bytes, str]:
        if self._prometheus is None:
            return b"", CONTENT_TYPE_LATEST
        return self._prometheus.payload()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "agent_request_total": dict(sorted(self._request_total.items())),
                "agent_request_latency_ms": self._latency_snapshot(self._request_latency),
                "agent_tool_call_total": self._nested_tool_snapshot(),
                "agent_tool_error_total": dict(sorted(self._tool_errors.items())),
                "agent_rag_mode_total": dict(sorted(self._rag_modes.items())),
                "agent_review_verdict_total": dict(sorted(self._review_verdicts.items())),
                "agent_handoff_total": self._handoffs,
                "agent_step_latency_ms": self._latency_snapshot(self._step_latency),
            }

    def _nested_tool_snapshot(self) -> dict[str, dict[str, int]]:
        result: dict[str, dict[str, int]] = {}
        for (tool, outcome), count in sorted(self._tool_calls.items()):
            result.setdefault(tool, {})[outcome] = count
        return result

    @staticmethod
    def _latency_snapshot(values: dict[str, _LatencyStats]) -> dict[str, dict[str, float | int]]:
        return {label: stats.snapshot() for label, stats in sorted(values.items())}

    @staticmethod
    def _route(path: str) -> str:
        return path if path in {"/api/chat", "/api/review-images", "/api/analyze/emotion"} else "other"

    @staticmethod
    def _non_negative_int(value: Any) -> int:
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0


AGENT_PROMETHEUS_REGISTRY = CollectorRegistry(auto_describe=True)
AGENT_RUNTIME_METRICS = AgentRuntimeMetrics(AGENT_PROMETHEUS_REGISTRY)
