from __future__ import annotations

import atexit
from dataclasses import dataclass
import math
import os
import threading
import time
from typing import Any, Callable, Protocol

import httpx


class RerankError(RuntimeError):
    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = str(code or "UNEXPECTED_ERROR").upper()
        super().__init__(message or self.code)

    @property
    def retryable(self) -> bool:
        if self.code in {"TIMEOUT", "HTTP_429"}:
            return True
        if self.code.startswith("HTTP_"):
            try:
                return int(self.code.split("_", 1)[1]) >= 500
            except ValueError:
                return False
        return False


_NUMERIC_CONFIG_SPECS: dict[str, tuple[type[int] | type[float], int | float, int | float, int | float]] = {
    "RERANK_TIMEOUT_SECONDS": (float, 3.0, 0.0, 30.0),
    "RERANK_MAX_RETRIES": (int, 1, 0, 1),
    "RERANK_MAX_CANDIDATES": (int, 20, 1, 20),
    "RERANK_MAX_CONCURRENCY": (int, 4, 1, 64),
    "RERANK_CIRCUIT_FAILURE_THRESHOLD": (int, 5, 1, 100),
    "RERANK_CIRCUIT_RECOVERY_SECONDS": (float, 30.0, 0.0, 3600.0),
}


def _safe_numeric_config(name: str) -> tuple[int | float, str | None]:
    value_type, default, minimum, maximum = _NUMERIC_CONFIG_SPECS[name]
    raw = os.getenv(name, str(default))
    try:
        value = value_type(raw)
    except (TypeError, ValueError, OverflowError):
        return default, f"INVALID_RERANK_CONFIG:{name}"
    if isinstance(value, float) and not math.isfinite(value):
        return default, f"INVALID_RERANK_CONFIG:{name}"
    if value < minimum or value > maximum or (minimum == 0.0 and value == 0.0 and value_type is float):
        return default, f"INVALID_RERANK_CONFIG:{name}"
    return value, None


@dataclass(frozen=True)
class RerankerConfig:
    provider: str
    base_url: str
    api_key: str
    model: str
    timeout_seconds: float = 3.0
    max_retries: int = 1
    max_candidates: int = 20
    max_concurrency: int = 4
    circuit_failure_threshold: int = 5
    circuit_recovery_seconds: float = 30.0
    config_error: str | None = None

    @classmethod
    def from_env(cls) -> "RerankerConfig":
        numeric: dict[str, int | float] = {}
        first_error: str | None = None
        for name in _NUMERIC_CONFIG_SPECS:
            numeric[name], error = _safe_numeric_config(name)
            first_error = first_error or error
        return cls(
            provider=os.getenv("RERANK_PROVIDER", "").strip(),
            base_url=os.getenv("RERANK_BASE_URL", "").strip(),
            api_key=os.getenv("RERANK_API_KEY", "").strip(),
            model=os.getenv("RERANK_MODEL", "text-rerank-v2").strip(),
            timeout_seconds=float(numeric["RERANK_TIMEOUT_SECONDS"]),
            max_retries=int(numeric["RERANK_MAX_RETRIES"]),
            max_candidates=int(numeric["RERANK_MAX_CANDIDATES"]),
            max_concurrency=int(numeric["RERANK_MAX_CONCURRENCY"]),
            circuit_failure_threshold=int(numeric["RERANK_CIRCUIT_FAILURE_THRESHOLD"]),
            circuit_recovery_seconds=float(numeric["RERANK_CIRCUIT_RECOVERY_SECONDS"]),
            config_error=first_error,
        )

    @property
    def validation_error(self) -> str | None:
        if self.config_error:
            return self.config_error
        # Provider and credential are the explicit enablement switch. A stale URL
        # with both unset remains a deliberately disabled configuration.
        if (self.provider or self.api_key) and not (
            self.provider and self.base_url and self.api_key and self.model
        ):
            return "INVALID_RERANK_CONFIG:PROVIDER_FIELDS"
        return None

    @property
    def configured(self) -> bool:
        return self.validation_error is None and bool(
            self.provider and self.base_url and self.api_key and self.model
        )


@dataclass(frozen=True)
class RerankResult:
    items: list[dict[str, Any]]
    mode: str
    degraded: bool
    failure_reason: str | None
    latency_ms: float


class RerankTransport(Protocol):
    def post_json(self, payload: dict[str, Any], *, timeout: float) -> dict[str, Any]: ...


class ManagedHTTPRerankTransport:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self._owns_client = client is None
        self._client = client or httpx.Client()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def post_json(self, payload: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        try:
            response = self._client.post(
                self.base_url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=timeout,
            )
        except httpx.TimeoutException as exc:
            raise RerankError("TIMEOUT", "reranker request timed out") from exc
        except httpx.HTTPError as exc:
            raise RerankError("NETWORK_ERROR", "reranker network request failed") from exc
        if response.status_code >= 400:
            raise RerankError(f"HTTP_{response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise RerankError("INVALID_RESPONSE", "reranker response is not JSON") from exc
        if not isinstance(data, dict):
            raise RerankError("INVALID_RESPONSE", "reranker response must be an object")
        return data


class RerankCircuitBreaker:
    def __init__(
        self,
        *,
        threshold: int,
        recovery_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.threshold = max(1, int(threshold))
        self.recovery_seconds = max(0.0, float(recovery_seconds))
        self._clock = clock
        self._lock = threading.Lock()
        self._failure_count = 0
        self._opened_at: float | None = None
        self._probe_running = False

    def before_call(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return True
            if self._clock() - self._opened_at < self.recovery_seconds:
                return False
            if self._probe_running:
                return False
            self._probe_running = True
            return True

    def record_success(self) -> None:
        with self._lock:
            self._failure_count = 0
            self._opened_at = None
            self._probe_running = False

    def record_failure(self) -> None:
        with self._lock:
            self._probe_running = False
            self._failure_count += 1
            if self._failure_count >= self.threshold:
                self._opened_at = self._clock()


class RerankerClient:
    def __init__(
        self,
        *,
        config: RerankerConfig | None = None,
        transport: RerankTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config or RerankerConfig.from_env()
        self.transport = transport
        self._clock = clock
        self._lifecycle = threading.Condition()
        self._active_calls = 0
        self._closed = False
        self._close_complete = False
        concurrency = self.config.max_concurrency if isinstance(self.config.max_concurrency, int) else 1
        self._semaphore = threading.BoundedSemaphore(max(1, concurrency))
        threshold = (
            self.config.circuit_failure_threshold
            if isinstance(self.config.circuit_failure_threshold, int)
            else 1
        )
        recovery = self.config.circuit_recovery_seconds
        if not isinstance(recovery, (int, float)) or not math.isfinite(float(recovery)):
            recovery = 0.0
        self.breaker = RerankCircuitBreaker(
            threshold=threshold,
            recovery_seconds=recovery,
            clock=clock,
        )

    def _get_transport(self) -> RerankTransport:
        with self._lifecycle:
            if self._closed:
                raise RerankError("CLIENT_CLOSED")
            if self.transport is None:
                self.transport = ManagedHTTPRerankTransport(
                    base_url=self.config.base_url,
                    api_key=self.config.api_key,
                )
            return self.transport

    def close(self) -> None:
        with self._lifecycle:
            if self._close_complete:
                return
            if self._closed:
                while not self._close_complete:
                    self._lifecycle.wait()
                return
            self._closed = True
            while self._active_calls:
                self._lifecycle.wait()
            transport = self.transport
        try:
            close = getattr(transport, "close", None)
            if callable(close):
                close()
        finally:
            with self._lifecycle:
                self._close_complete = True
                self._lifecycle.notify_all()

    def _begin_call(self) -> bool:
        with self._lifecycle:
            if self._closed:
                return False
            self._active_calls += 1
            return True

    def _finish_call(self) -> None:
        with self._lifecycle:
            self._active_calls -= 1
            if self._active_calls == 0:
                self._lifecycle.notify_all()

    def _is_closed(self) -> bool:
        with self._lifecycle:
            return self._closed

    def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        top_n: int,
    ) -> RerankResult:
        started = self._clock()
        timeout_seconds = max(0.0, float(self.config.timeout_seconds))
        deadline = started + timeout_seconds
        candidate_limit = max(1, min(int(self.config.max_candidates), 20))
        bounded_candidates = list(candidates[:candidate_limit])
        bounded_top_n = max(1, min(int(top_n), len(bounded_candidates))) if bounded_candidates else 0
        fallback = list(bounded_candidates[:bounded_top_n])
        if not self._begin_call():
            return self._degraded(fallback, "CLIENT_CLOSED", started)
        try:
            if not bounded_candidates:
                return RerankResult([], "hybrid_reranked", False, None, self._latency_ms(started))
            if self.config.validation_error:
                return self._degraded(fallback, "CONFIG_ERROR", started)
            if not self.config.configured:
                return self._degraded(fallback, "NOT_CONFIGURED", started)
            acquired = self._semaphore.acquire(timeout=max(0.0, deadline - self._clock()))
            if not acquired:
                return self._degraded(fallback, "QUEUE_TIMEOUT", started)
            try:
                if self._is_closed():
                    return self._degraded(fallback, "CLIENT_CLOSED", started)
                if not self.breaker.before_call():
                    return self._degraded(fallback, "CIRCUIT_OPEN", started)
                payload = {
                    "model": self.config.model,
                    "query": str(query or ""),
                    "documents": [self._candidate_text(item) for item in bounded_candidates],
                    "top_n": bounded_top_n,
                }
                attempts = min(max(0, int(self.config.max_retries)), 1) + 1
                try:
                    transport = self._get_transport()
                except RerankError as exc:
                    if exc.code != "CLIENT_CLOSED":
                        self.breaker.record_failure()
                    return self._degraded(fallback, exc.code, started)
                except Exception:
                    self.breaker.record_failure()
                    return self._degraded(fallback, "UNEXPECTED_ERROR", started)
                for attempt in range(attempts):
                    try:
                        remaining = deadline - self._clock()
                        if remaining <= 0.0:
                            raise RerankError("TIMEOUT")
                        data = transport.post_json(payload, timeout=remaining)
                        if self._clock() >= deadline:
                            raise RerankError("TIMEOUT")
                        items = self._validated_items(data, bounded_candidates, bounded_top_n)
                        self.breaker.record_success()
                        return RerankResult(items, "hybrid_reranked", False, None, self._latency_ms(started))
                    except RerankError as exc:
                        if exc.code == "CLIENT_CLOSED":
                            return self._degraded(fallback, exc.code, started)
                        if exc.retryable and attempt + 1 < attempts:
                            continue
                        self.breaker.record_failure()
                        return self._degraded(fallback, exc.code, started)
                    except Exception:
                        self.breaker.record_failure()
                        return self._degraded(fallback, "UNEXPECTED_ERROR", started)
                return self._degraded(fallback, "UNEXPECTED_ERROR", started)
            finally:
                self._semaphore.release()
        finally:
            self._finish_call()

    @staticmethod
    def _candidate_text(candidate: dict[str, Any]) -> str:
        return str(candidate.get("chunk_text") or candidate.get("snippet") or "")

    @staticmethod
    def _validated_items(
        data: dict[str, Any],
        candidates: list[dict[str, Any]],
        top_n: int,
    ) -> list[dict[str, Any]]:
        raw_results = data.get("results")
        if not isinstance(raw_results, list):
            raise RerankError("INVALID_RESPONSE")
        if len(raw_results) != top_n:
            raise RerankError("INVALID_RESPONSE")
        seen: set[int] = set()
        items: list[dict[str, Any]] = []
        for raw in raw_results:
            if not isinstance(raw, dict):
                raise RerankError("INVALID_RESPONSE")
            index = raw.get("index")
            if isinstance(index, bool) or not isinstance(index, int):
                raise RerankError("INVALID_RESPONSE")
            if index < 0 or index >= len(candidates) or index in seen:
                raise RerankError("INVALID_RESPONSE")
            try:
                score = float(raw.get("relevance_score"))
            except (TypeError, ValueError):
                raise RerankError("INVALID_RESPONSE") from None
            if not math.isfinite(score) or score < 0.0 or score > 1.0:
                raise RerankError("INVALID_RESPONSE")
            seen.add(index)
            item = dict(candidates[index])
            item["provider_index"] = index
            item["relevance_score"] = score
            item["rerank_score"] = score
            items.append(item)
        return items[:top_n]

    def _latency_ms(self, started: float) -> float:
        return round(max(0.0, (self._clock() - started) * 1000), 3)

    def _degraded(
        self,
        items: list[dict[str, Any]],
        reason: str,
        started: float,
    ) -> RerankResult:
        return RerankResult(list(items), "hybrid_rrf_degraded", True, reason, self._latency_ms(started))


class RerankerClientLifecycle:
    """Own one process-wide client so breaker and transport state survive requests."""

    def __init__(self, factory: Callable[[], RerankerClient] = RerankerClient) -> None:
        self._factory = factory
        self._client: RerankerClient | None = None
        self._lock = threading.Lock()
        self._closed = False

    def get(self) -> RerankerClient:
        with self._lock:
            if self._closed:
                raise RerankError("CLIENT_CLOSED")
            if self._client is None:
                self._client = self._factory()
            return self._client

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            client = self._client
            if client is not None:
                client.close()


RERANKER_CLIENTS = RerankerClientLifecycle()
atexit.register(RERANKER_CLIENTS.close)
