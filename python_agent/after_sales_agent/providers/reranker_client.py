from __future__ import annotations

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

    @classmethod
    def from_env(cls) -> "RerankerConfig":
        return cls(
            provider=os.getenv("RERANK_PROVIDER", "").strip(),
            base_url=os.getenv("RERANK_BASE_URL", "").strip(),
            api_key=os.getenv("RERANK_API_KEY", "").strip(),
            model=os.getenv("RERANK_MODEL", "text-rerank-v2").strip(),
            timeout_seconds=float(os.getenv("RERANK_TIMEOUT_SECONDS", "3")),
            max_retries=int(os.getenv("RERANK_MAX_RETRIES", "1")),
            max_candidates=int(os.getenv("RERANK_MAX_CANDIDATES", "20")),
            max_concurrency=int(os.getenv("RERANK_MAX_CONCURRENCY", "4")),
            circuit_failure_threshold=int(os.getenv("RERANK_CIRCUIT_FAILURE_THRESHOLD", "5")),
            circuit_recovery_seconds=float(os.getenv("RERANK_CIRCUIT_RECOVERY_SECONDS", "30")),
        )

    @property
    def configured(self) -> bool:
        return bool(self.provider and self.base_url and self.api_key and self.model)


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
    ) -> None:
        self.config = config or RerankerConfig.from_env()
        self.transport = transport or ManagedHTTPRerankTransport(
            base_url=self.config.base_url,
            api_key=self.config.api_key,
        )
        self._semaphore = threading.BoundedSemaphore(max(1, int(self.config.max_concurrency)))
        self.breaker = RerankCircuitBreaker(
            threshold=self.config.circuit_failure_threshold,
            recovery_seconds=self.config.circuit_recovery_seconds,
        )

    def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        top_n: int,
    ) -> RerankResult:
        started = time.monotonic()
        candidate_limit = max(1, min(int(self.config.max_candidates), 20))
        bounded_candidates = list(candidates[:candidate_limit])
        bounded_top_n = max(1, min(int(top_n), len(bounded_candidates))) if bounded_candidates else 0
        fallback = list(bounded_candidates[:bounded_top_n])
        if not bounded_candidates:
            return RerankResult([], "hybrid_reranked", False, None, self._latency_ms(started))
        if not self.config.configured:
            return self._degraded(fallback, "NOT_CONFIGURED", started)
        acquired = self._semaphore.acquire(timeout=max(0.0, float(self.config.timeout_seconds)))
        if not acquired:
            return self._degraded(fallback, "QUEUE_TIMEOUT", started)
        try:
            if not self.breaker.before_call():
                return self._degraded(fallback, "CIRCUIT_OPEN", started)
            payload = {
                "model": self.config.model,
                "query": str(query or ""),
                "documents": [self._candidate_text(item) for item in bounded_candidates],
                "top_n": bounded_top_n,
            }
            attempts = min(max(0, int(self.config.max_retries)), 1) + 1
            for attempt in range(attempts):
                try:
                    data = self.transport.post_json(payload, timeout=float(self.config.timeout_seconds))
                    items = self._validated_items(data, bounded_candidates, bounded_top_n)
                    self.breaker.record_success()
                    return RerankResult(items, "hybrid_reranked", False, None, self._latency_ms(started))
                except RerankError as exc:
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

    @staticmethod
    def _latency_ms(started: float) -> float:
        return round(max(0.0, (time.monotonic() - started) * 1000), 3)

    @classmethod
    def _degraded(
        cls,
        items: list[dict[str, Any]],
        reason: str,
        started: float,
    ) -> RerankResult:
        return RerankResult(list(items), "hybrid_rrf_degraded", True, reason, cls._latency_ms(started))
