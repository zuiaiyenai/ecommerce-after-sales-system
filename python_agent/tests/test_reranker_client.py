from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import math
import threading
import time

import httpx
import pytest

from after_sales_agent.providers.reranker_client import (
    ManagedHTTPRerankTransport,
    RerankCircuitBreaker,
    RerankError,
    RerankerClient,
    RerankerConfig,
)


def _config(**overrides: object) -> RerankerConfig:
    values = {
        "provider": "dashscope",
        "base_url": "https://example.invalid/rerank",
        "api_key": "test",
        "model": "text-rerank-v2",
        "timeout_seconds": 0.05,
        "max_retries": 1,
        "max_candidates": 20,
        "max_concurrency": 1,
        "circuit_failure_threshold": 5,
        "circuit_recovery_seconds": 30.0,
    }
    values.update(overrides)
    return RerankerConfig(**values)


def _candidates(count: int = 2) -> list[dict[str, object]]:
    return [
        {"chunk_id": chr(ord("A") + index), "chunk_text": f"document-{index}", "rrf_score": 0.03 - index / 1000}
        for index in range(count)
    ]


class SequenceTransport:
    def __init__(self, *outcomes: object) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0
        self.timeouts: list[float] = []

    def post_json(self, _payload: dict[str, object], *, timeout: float) -> dict[str, object]:
        self.calls += 1
        self.timeouts.append(timeout)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome  # type: ignore[return-value]


def test_timeout_degrades_to_original_rrf_order_without_policy_trust() -> None:
    candidates = _candidates()
    transport = SequenceTransport(RerankError("TIMEOUT"), RerankError("TIMEOUT"))

    result = RerankerClient(transport=transport, config=_config()).rerank("refund", candidates, top_n=2)

    assert result.mode == "hybrid_rrf_degraded"
    assert result.degraded is True
    assert result.failure_reason == "TIMEOUT"
    assert result.items == candidates
    assert not any(item.get("trusted_policy_eligible") is True for item in result.items)
    assert transport.calls == 2


@pytest.mark.parametrize("code", ["TIMEOUT", "HTTP_429", "HTTP_500", "HTTP_503"])
def test_only_timeout_rate_limit_and_5xx_retry_once(code: str) -> None:
    transport = SequenceTransport(
        RerankError(code),
        {"results": [{"index": 0, "relevance_score": 0.9}]},
    )

    result = RerankerClient(transport=transport, config=_config(max_retries=9)).rerank(
        "query", _candidates(1), top_n=1
    )

    assert result.degraded is False
    assert transport.calls == 2


@pytest.mark.parametrize("code", ["HTTP_400", "HTTP_401", "HTTP_403"])
def test_client_errors_do_not_retry(code: str) -> None:
    transport = SequenceTransport(RerankError(code))

    result = RerankerClient(transport=transport, config=_config()).rerank("query", _candidates(1), top_n=1)

    assert result.degraded is True
    assert result.failure_reason == code
    assert transport.calls == 1


def test_semaphore_queue_wait_is_bounded_by_timeout() -> None:
    entered = threading.Event()
    release = threading.Event()

    class BlockingTransport:
        def post_json(self, _payload: dict[str, object], *, timeout: float) -> dict[str, object]:
            entered.set()
            release.wait(timeout=1)
            return {"results": [{"index": 0, "relevance_score": 0.8}]}

    client = RerankerClient(transport=BlockingTransport(), config=_config(timeout_seconds=0.02))
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(client.rerank, "first", _candidates(1), 1)
        assert entered.wait(timeout=1)
        started = time.monotonic()
        queued = client.rerank("queued", _candidates(1), 1)
        elapsed = time.monotonic() - started
        release.set()
        assert first.result(timeout=1).degraded is False

    assert queued.degraded is True
    assert queued.failure_reason == "QUEUE_TIMEOUT"
    assert elapsed < 0.25


@pytest.mark.parametrize(
    "results",
    [
        [{"index": 99, "relevance_score": 0.9}],
        [{"index": 0, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.8}],
        [{"index": 0, "relevance_score": float("nan")}],
        [{"index": 0, "relevance_score": float("inf")}],
        [{"index": 0, "relevance_score": -0.01}],
        [{"index": 0, "relevance_score": 1.01}],
    ],
)
def test_invalid_indexes_and_scores_fail_closed(results: list[dict[str, object]]) -> None:
    candidates = _candidates()
    transport = SequenceTransport({"results": results})

    result = RerankerClient(transport=transport, config=_config()).rerank("query", candidates, top_n=2)

    assert result.degraded is True
    assert result.failure_reason == "INVALID_RESPONSE"
    assert result.items == candidates


def test_provider_indexes_align_to_original_candidates_in_provider_order() -> None:
    candidates = _candidates(3)
    transport = SequenceTransport(
        {"results": [{"index": 2, "relevance_score": 0.95}, {"index": 0, "relevance_score": "0.75"}]}
    )

    result = RerankerClient(transport=transport, config=_config()).rerank("query", candidates, top_n=2)

    assert result.degraded is False
    assert [item["chunk_id"] for item in result.items] == ["C", "A"]
    assert [item["provider_index"] for item in result.items] == [2, 0]
    assert [item["rerank_score"] for item in result.items] == [0.95, 0.75]
    assert candidates[2].get("rerank_score") is None
    assert math.isfinite(result.latency_ms)


def test_unconfigured_provider_degrades_without_transport_call() -> None:
    transport = SequenceTransport({"results": [{"index": 0, "relevance_score": 0.9}]})
    config = _config(provider="", api_key="")

    result = RerankerClient(transport=transport, config=config).rerank("query", _candidates(1), top_n=1)

    assert result.mode == "hybrid_rrf_degraded"
    assert result.failure_reason == "NOT_CONFIGURED"
    assert transport.calls == 0


def test_circuit_breaker_allows_only_one_recovery_probe_across_threads() -> None:
    now = [100.0]
    breaker = RerankCircuitBreaker(threshold=1, recovery_seconds=30, clock=lambda: now[0])
    assert breaker.before_call() is True
    breaker.record_failure()
    assert breaker.before_call() is False
    now[0] += 31

    barrier = threading.Barrier(8)

    def attempt() -> bool:
        barrier.wait(timeout=1)
        return breaker.before_call()

    with ThreadPoolExecutor(max_workers=8) as pool:
        allowed = list(pool.map(lambda _index: attempt(), range(8)))

    assert allowed.count(True) == 1
    breaker.record_success()
    assert breaker.before_call() is True


def test_circuit_opens_at_threshold_and_recovers_after_successful_probe() -> None:
    now = [10.0]
    breaker = RerankCircuitBreaker(threshold=2, recovery_seconds=5, clock=lambda: now[0])
    breaker.record_failure()
    assert breaker.before_call() is True
    breaker.record_failure()
    assert breaker.before_call() is False
    now[0] += 6
    assert breaker.before_call() is True
    breaker.record_success()
    assert breaker.before_call() is True


def test_terminal_non_retryable_provider_failures_also_release_and_open_breaker() -> None:
    transport = SequenceTransport(RerankError("HTTP_401"))
    client = RerankerClient(
        transport=transport,
        config=_config(circuit_failure_threshold=1),
    )

    rejected = client.rerank("query", _candidates(1), top_n=1)
    blocked = client.rerank("query", _candidates(1), top_n=1)

    assert rejected.failure_reason == "HTTP_401"
    assert blocked.failure_reason == "CIRCUIT_OPEN"
    assert transport.calls == 1


def test_retrieval_package_exports_rerank_threshold_contract() -> None:
    from after_sales_agent.retrieval import RERANK_THRESHOLDS

    assert RERANK_THRESHOLDS["after_sales_policy"] == 0.75
    assert RERANK_THRESHOLDS["evidence_requirement"] == 0.65
    assert RERANK_THRESHOLDS["faq"] == 0.60


@pytest.mark.parametrize(
    ("status", "expected_code"),
    [(400, "HTTP_400"), (401, "HTTP_401"), (403, "HTTP_403"), (429, "HTTP_429"), (503, "HTTP_503")],
)
def test_managed_http_transport_classifies_status(status: int, expected_code: str) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"message": "failure"})

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    transport = ManagedHTTPRerankTransport(
        base_url="https://example.invalid/rerank",
        api_key="secret",
        client=http_client,
    )

    with pytest.raises(RerankError) as captured:
        transport.post_json({"query": "q"}, timeout=0.1)

    assert captured.value.code == expected_code


def test_managed_http_transport_classifies_httpx_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    transport = ManagedHTTPRerankTransport(
        base_url="https://example.invalid/rerank",
        api_key="secret",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(RerankError) as captured:
        transport.post_json({"query": "q"}, timeout=0.1)

    assert captured.value.code == "TIMEOUT"
