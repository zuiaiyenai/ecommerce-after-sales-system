"""Shared resilience mechanisms — CircuitBreaker, RetryPolicy, Semaphore.

Extracted from providers/resilient_llm_runtime.py and providers/reranker_client.py.

Each provider (LLM, Embedding, Reranker) keeps its own strategy:
  - retry conditions (which errors are retriable)
  - retry count and backoff strategy
  - circuit-breaker threshold and recovery time
  - degradation logic

Only the *mechanism* (CircuitBreaker / RetryPolicy / Semaphore) is shared.
"""
from __future__ import annotations

import logging
import random
import threading
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Thread-safe circuit breaker.

    Two modes:
      - *raising* (default): before_call() raises on open circuit.
      - *passive*: before_call(*raise_on_open=False*) returns False on open.
    """

    def __init__(
        self,
        threshold: int,
        recovery_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.threshold = max(1, int(threshold))
        self.recovery_seconds = max(0.0, float(recovery_seconds))
        self._clock = clock
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_at: float | None = None
        self._probe_running = False

    def before_call(self, *, raise_on_open: bool = True) -> bool:
        with self._lock:
            if self._opened_at is None:
                return True
            if self._clock() - self._opened_at < self.recovery_seconds or self._probe_running:
                if raise_on_open:
                    raise CircuitOpenError("circuit is open")
                return False
            self._probe_running = True
            return True

    def success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None
            self._probe_running = False

    def failure(self) -> None:
        with self._lock:
            self._probe_running = False
            self._failures += 1
            if self._failures >= self.threshold:
                self._opened_at = self._clock()


class CircuitOpenError(RuntimeError):
    """Raised when a CircuitBreaker is in the open state."""


class RetryPolicy:
    """Generic retry with exponential backoff + jitter.

    Usage::

        policy = RetryPolicy(max_attempts=3, base_delay=1.0, max_delay=30.0)
        for attempt in policy:
            try:
                result = do_work()
                policy.mark_success()
                break
            except RetryableError as exc:
                policy.mark_failure(exc)
                if attempt == policy.last_attempt:
                    raise
                continue
    """

    def __init__(
        self,
        *,
        max_attempts: int,
        base_delay: float,
        max_delay: float,
    ) -> None:
        self.max_attempts = max(1, int(max_attempts))
        self.base_delay = max(0.0, float(base_delay))
        self.max_delay = max(0.0, float(max_delay))
        self.attempt = 0
        self.last_attempt = False
        self.current_delay = 0.0
        self._error: Exception | None = None

    def mark_failure(self, exc: Exception) -> None:
        self._error = exc
        self.last_attempt = self.attempt + 1 >= self.max_attempts
        if self.last_attempt:
            return
        self.current_delay = min(
            self.max_delay,
            self.base_delay * (2 ** self.attempt),
        )
        self.current_delay *= random.uniform(0.5, 1.5)

    def mark_success(self) -> None:
        self._error = None
        self.last_attempt = False

    def sleep(self) -> None:
        if self.current_delay > 0:
            time.sleep(self.current_delay)

    def __iter__(self) -> Any:
        self.attempt = 0
        self.last_attempt = False
        while self.attempt < self.max_attempts:
            self.last_attempt = self.attempt + 1 >= self.max_attempts
            yield self.attempt
            self.attempt += 1


class Semaphore:
    """Wrapper around threading.BoundedSemaphore with timed acquire."""

    def __init__(self, value: int = 1) -> None:
        self._sem = threading.BoundedSemaphore(max(1, int(value)))

    def acquire(self, *, timeout: float) -> bool:
        return self._sem.acquire(timeout=max(0.0, float(timeout)))

    def release(self) -> None:
        self._sem.release()


class TimingSemaphore:
    """Semaphore that records how long acquisition took (in ms)."""

    def __init__(self, value: int = 1) -> None:
        self._sem = threading.BoundedSemaphore(max(1, int(value)))
        self.last_queue_ms = 0.0

    def acquire(self, *, timeout: float) -> bool:
        started = time.monotonic()
        result = self._sem.acquire(timeout=max(0.0, float(timeout)))
        self.last_queue_ms = (time.monotonic() - started) * 1000
        return result

    def release(self) -> None:
        self._sem.release()
