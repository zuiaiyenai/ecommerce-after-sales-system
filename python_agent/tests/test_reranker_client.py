from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import math
import threading
import time
from unittest.mock import patch

import httpx
import pytest

from after_sales_agent.providers.reranker_client import (
    ManagedHTTPRerankTransport,
    RerankCircuitBreaker,
    RerankError,
    RerankerClient,
    RerankerClientLifecycle,
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
        inflight = first.result(timeout=1)

    assert queued.degraded is True
    assert queued.failure_reason == "QUEUE_TIMEOUT"
    assert inflight.degraded is True
    assert inflight.failure_reason == "TIMEOUT"
    assert elapsed < 0.25


def test_queue_and_retries_share_one_monotonic_total_deadline() -> None:
    now = [100.0]

    class QueueDelaySemaphore:
        def acquire(self, *, timeout: float) -> bool:
            assert timeout == pytest.approx(1.0)
            now[0] += 0.25
            return True

        def release(self) -> None:
            return None

    class DeadlineTransport:
        def __init__(self) -> None:
            self.timeouts: list[float] = []

        def post_json(self, _payload: dict[str, object], *, timeout: float) -> dict[str, object]:
            self.timeouts.append(timeout)
            if len(self.timeouts) == 1:
                now[0] += 0.5
            else:
                now[0] += timeout
            raise RerankError("TIMEOUT")

    transport = DeadlineTransport()
    client = RerankerClient(
        transport=transport,
        config=_config(timeout_seconds=1.0),
        clock=lambda: now[0],
    )
    client._semaphore = QueueDelaySemaphore()  # type: ignore[assignment]

    result = client.rerank("query", _candidates(1), top_n=1)

    assert result.failure_reason == "TIMEOUT"
    assert transport.timeouts == pytest.approx([0.75, 0.25])
    assert now[0] == pytest.approx(101.0)


def test_valid_response_arriving_after_overall_deadline_fails_closed_without_recording_success() -> None:
    now = [10.0]

    class LateValidTransport:
        def post_json(self, _payload: dict[str, object], *, timeout: float) -> dict[str, object]:
            now[0] += timeout + 0.01
            return {"results": [{"index": 0, "relevance_score": 0.99}]}

    class RecordingBreaker:
        def __init__(self) -> None:
            self.successes = 0
            self.failures = 0

        def before_call(self) -> bool:
            return True

        def record_success(self) -> None:
            self.successes += 1

        def record_failure(self) -> None:
            self.failures += 1

    candidate = {**_candidates(1)[0], "trusted_policy_eligible": False}
    client = RerankerClient(
        transport=LateValidTransport(),
        config=_config(timeout_seconds=1.0, max_retries=0),
        clock=lambda: now[0],
    )
    breaker = RecordingBreaker()
    client.breaker = breaker  # type: ignore[assignment]

    result = client.rerank("query", [candidate], top_n=1)

    assert result.degraded is True
    assert result.failure_reason == "TIMEOUT"
    assert result.items == [candidate]
    assert result.items[0]["trusted_policy_eligible"] is False
    assert breaker.successes == 0
    assert breaker.failures == 1


def test_retry_attempts_recheck_shared_deadline_after_late_valid_response() -> None:
    now = [100.0]

    class RetryThenLateValidTransport:
        def __init__(self) -> None:
            self.timeouts: list[float] = []

        def post_json(self, _payload: dict[str, object], *, timeout: float) -> dict[str, object]:
            self.timeouts.append(timeout)
            if len(self.timeouts) == 1:
                now[0] += 0.6
                raise RerankError("TIMEOUT")
            now[0] += timeout + 0.01
            return {"results": [{"index": 0, "relevance_score": 0.95}]}

    transport = RetryThenLateValidTransport()
    client = RerankerClient(
        transport=transport,
        config=_config(timeout_seconds=1.0, max_retries=1),
        clock=lambda: now[0],
    )

    result = client.rerank("query", _candidates(1), top_n=1)

    assert result.degraded is True
    assert result.failure_reason == "TIMEOUT"
    assert transport.timeouts == pytest.approx([1.0, 0.4])


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


@pytest.mark.parametrize(
    "results",
    [
        [],
        [{"index": 0, "relevance_score": 0.9}],
        [
            {"index": 0, "relevance_score": 0.9},
            {"index": 1, "relevance_score": 0.8},
            {"index": 2, "relevance_score": 0.7},
        ],
    ],
)
def test_provider_result_count_must_exactly_match_requested_cardinality(
    results: list[dict[str, object]],
) -> None:
    candidates = _candidates(3)
    result = RerankerClient(
        transport=SequenceTransport({"results": results}),
        config=_config(),
    ).rerank("query", candidates, top_n=2)

    assert result.degraded is True
    assert result.failure_reason == "INVALID_RESPONSE"
    assert result.items == candidates[:2]


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


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("RERANK_TIMEOUT_SECONDS", "abc"),
        ("RERANK_TIMEOUT_SECONDS", "NaN"),
        ("RERANK_TIMEOUT_SECONDS", "Infinity"),
        ("RERANK_TIMEOUT_SECONDS", "0"),
        ("RERANK_TIMEOUT_SECONDS", "-1"),
        ("RERANK_TIMEOUT_SECONDS", "31"),
        ("RERANK_MAX_RETRIES", "2"),
        ("RERANK_MAX_CANDIDATES", "21"),
        ("RERANK_MAX_CONCURRENCY", "0"),
        ("RERANK_MAX_CONCURRENCY", "65"),
        ("RERANK_CIRCUIT_FAILURE_THRESHOLD", "0"),
        ("RERANK_CIRCUIT_FAILURE_THRESHOLD", "101"),
        ("RERANK_CIRCUIT_RECOVERY_SECONDS", "0"),
        ("RERANK_CIRCUIT_RECOVERY_SECONDS", "3601"),
    ],
)
def test_invalid_numeric_environment_degrades_to_config_error_without_startup_exception(
    monkeypatch,
    name: str,
    value: str,
) -> None:
    for key, valid_value in {
        "RERANK_PROVIDER": "dashscope",
        "RERANK_BASE_URL": "https://example.invalid/rerank",
        "RERANK_API_KEY": "secret-value-must-not-leak",
        "RERANK_MODEL": "text-rerank-v2",
        "RERANK_TIMEOUT_SECONDS": "3",
        "RERANK_MAX_RETRIES": "1",
        "RERANK_MAX_CANDIDATES": "20",
        "RERANK_MAX_CONCURRENCY": "4",
        "RERANK_CIRCUIT_FAILURE_THRESHOLD": "5",
        "RERANK_CIRCUIT_RECOVERY_SECONDS": "30",
    }.items():
        monkeypatch.setenv(key, valid_value)
    monkeypatch.setenv(name, value)

    config = RerankerConfig.from_env()
    with patch("after_sales_agent.providers.reranker_client.ManagedHTTPRerankTransport") as transport_type:
        result = RerankerClient(config=config).rerank("query", _candidates(1), top_n=1)

    assert config.config_error == f"INVALID_RERANK_CONFIG:{name}"
    assert "secret-value-must-not-leak" not in config.config_error
    assert result.failure_reason == "CONFIG_ERROR"
    transport_type.assert_not_called()


def test_partial_provider_configuration_is_config_error_without_transport_creation() -> None:
    config = _config(base_url="")

    with patch("after_sales_agent.providers.reranker_client.ManagedHTTPRerankTransport") as transport_type:
        result = RerankerClient(config=config).rerank("query", _candidates(1), top_n=1)

    assert result.failure_reason == "CONFIG_ERROR"
    transport_type.assert_not_called()


def test_reranker_config_reuses_existing_dashscope_credential(monkeypatch) -> None:
    monkeypatch.setenv("RERANK_PROVIDER", "dashscope")
    monkeypatch.setenv("RERANK_BASE_URL", "https://workspace.example/compatible-api/v1/reranks")
    monkeypatch.delenv("RERANK_API_KEY", raising=False)
    monkeypatch.setenv("VISION_API_KEY", "shared-workspace-key")

    config = RerankerConfig.from_env()

    assert config.api_key == "shared-workspace-key"
    assert config.configured is True


def test_unconfigured_client_does_not_create_managed_transport() -> None:
    config = _config(provider="", base_url="", api_key="", model="")

    with patch("after_sales_agent.providers.reranker_client.ManagedHTTPRerankTransport") as transport_type:
        result = RerankerClient(config=config).rerank("query", _candidates(1), top_n=1)

    assert result.failure_reason == "NOT_CONFIGURED"
    transport_type.assert_not_called()


def test_valid_client_creates_managed_transport_lazily_on_first_call() -> None:
    response_transport = SequenceTransport({"results": [{"index": 0, "relevance_score": 0.8}]})

    with patch(
        "after_sales_agent.providers.reranker_client.ManagedHTTPRerankTransport",
        return_value=response_transport,
    ) as transport_type:
        client = RerankerClient(config=_config())
        transport_type.assert_not_called()
        result = client.rerank("query", _candidates(1), top_n=1)

    assert result.degraded is False
    transport_type.assert_called_once()


def test_reranker_client_close_is_idempotent_and_closes_created_transport_once() -> None:
    class CloseableTransport(SequenceTransport):
        def __init__(self) -> None:
            super().__init__({"results": [{"index": 0, "relevance_score": 0.8}]})
            self.close_calls = 0

        def close(self) -> None:
            self.close_calls += 1

    transport = CloseableTransport()
    client = RerankerClient(config=_config(), transport=transport)
    client.rerank("query", _candidates(1), top_n=1)

    client.close()
    client.close()

    assert transport.close_calls == 1


def test_close_before_first_call_rejects_rerank_without_creating_transport() -> None:
    client = RerankerClient(config=_config())

    with patch("after_sales_agent.providers.reranker_client.ManagedHTTPRerankTransport") as transport_type:
        client.close()
        result = client.rerank("query", _candidates(1), top_n=1)

    assert result.degraded is True
    assert result.failure_reason == "CLIENT_CLOSED"
    assert result.items == _candidates(1)
    transport_type.assert_not_called()


def test_close_waits_for_inflight_rerank_then_closes_transport_once() -> None:
    request_entered = threading.Event()
    release_request = threading.Event()
    close_started = threading.Event()
    close_finished = threading.Event()

    class BlockingCloseableTransport:
        def __init__(self) -> None:
            self.calls = 0
            self.close_calls = 0

        def post_json(self, _payload: dict[str, object], *, timeout: float) -> dict[str, object]:
            self.calls += 1
            request_entered.set()
            assert release_request.wait(timeout=1)
            return {"results": [{"index": 0, "relevance_score": 0.8}]}

        def close(self) -> None:
            self.close_calls += 1

    transport = BlockingCloseableTransport()
    client = RerankerClient(config=_config(timeout_seconds=1.0), transport=transport)

    def close_client() -> None:
        close_started.set()
        client.close()
        close_finished.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        rerank_future = pool.submit(client.rerank, "inflight", _candidates(1), 1)
        assert request_entered.wait(timeout=1)
        close_future = pool.submit(close_client)
        assert close_started.wait(timeout=1)
        assert close_finished.wait(timeout=0.05) is False
        assert transport.close_calls == 0

        rejected = client.rerank("after-close-started", _candidates(1), top_n=1)
        assert rejected.failure_reason == "CLIENT_CLOSED"
        assert transport.calls == 1

        release_request.set()
        assert rerank_future.result(timeout=1).degraded is False
        close_future.result(timeout=1)

    assert close_finished.is_set()
    assert transport.close_calls == 1


def test_close_winning_transport_creation_race_returns_client_closed_without_leak() -> None:
    transport_lookup_started = threading.Event()
    continue_transport_lookup = threading.Event()

    class PausingClient(RerankerClient):
        def _get_transport(self):
            transport_lookup_started.set()
            assert continue_transport_lookup.wait(timeout=1)
            return super()._get_transport()

    client = PausingClient(config=_config(timeout_seconds=1.0))

    with patch("after_sales_agent.providers.reranker_client.ManagedHTTPRerankTransport") as transport_type:
        with ThreadPoolExecutor(max_workers=2) as pool:
            rerank_future = pool.submit(client.rerank, "racing", _candidates(1), 1)
            assert transport_lookup_started.wait(timeout=1)
            close_future = pool.submit(client.close)
            continue_transport_lookup.set()

            result = rerank_future.result(timeout=1)
            close_future.result(timeout=1)

    assert result.failure_reason == "CLIENT_CLOSED"
    transport_type.assert_not_called()


def test_lifecycle_shares_client_and_breaker_across_requests_and_closes_once() -> None:
    transport = SequenceTransport(RerankError("HTTP_500"))
    lifecycle = RerankerClientLifecycle(
        factory=lambda: RerankerClient(
            config=_config(max_retries=0, circuit_failure_threshold=1),
            transport=transport,
        )
    )

    first_client = lifecycle.get()
    first = first_client.rerank("first", _candidates(1), top_n=1)
    second_client = lifecycle.get()
    second = second_client.rerank("second", _candidates(1), top_n=1)

    assert first_client is second_client
    assert first.failure_reason == "HTTP_500"
    assert second.failure_reason == "CIRCUIT_OPEN"
    assert transport.calls == 1

    lifecycle.close()
    lifecycle.close()


def test_lifecycle_close_is_terminal_for_existing_and_future_gets() -> None:
    factory_calls = 0

    def factory() -> RerankerClient:
        nonlocal factory_calls
        factory_calls += 1
        return RerankerClient(
            config=_config(),
            transport=SequenceTransport({"results": [{"index": 0, "relevance_score": 0.8}]}),
        )

    lifecycle = RerankerClientLifecycle(factory=factory)
    client = lifecycle.get()

    lifecycle.close()

    assert client.rerank("query", _candidates(1), top_n=1).failure_reason == "CLIENT_CLOSED"
    with pytest.raises(RerankError) as captured:
        lifecycle.get()
    assert captured.value.code == "CLIENT_CLOSED"
    assert factory_calls == 1


def test_lifecycle_close_before_get_does_not_construct_client() -> None:
    factory_calls = 0

    def factory() -> RerankerClient:
        nonlocal factory_calls
        factory_calls += 1
        return RerankerClient(config=_config())

    lifecycle = RerankerClientLifecycle(factory=factory)
    lifecycle.close()

    with pytest.raises(RerankError) as captured:
        lifecycle.get()

    assert captured.value.code == "CLIENT_CLOSED"
    assert factory_calls == 0


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

    assert RERANK_THRESHOLDS["after_sales_policy"] == 0.55
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
