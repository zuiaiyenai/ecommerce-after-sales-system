from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import hashlib
import json
import logging
import re
import secrets
import threading
from time import perf_counter
from typing import Any


TRACE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_CURRENT_TRACE_ID: ContextVar[str | None] = ContextVar("agent_trace_id", default=None)
logger = logging.getLogger("after_sales_agent.trace")


def new_trace_id() -> str:
    return secrets.token_hex(16)


def normalize_trace_id(value: str | None) -> str:
    candidate = str(value or "").strip().lower()
    return candidate if TRACE_ID_PATTERN.fullmatch(candidate) else new_trace_id()


def trace_id_from_seed(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:32]


def current_trace_id() -> str | None:
    return _CURRENT_TRACE_ID.get()


class TraceIdLoggingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = current_trace_id() or "-"
        return True


def install_trace_logging_filter() -> None:
    for handler in logging.getLogger().handlers:
        if not any(isinstance(item, TraceIdLoggingFilter) for item in handler.filters):
            handler.addFilter(TraceIdLoggingFilter())


@contextmanager
def bind_trace_id(trace_id: str | None):
    token = _CURRENT_TRACE_ID.set(trace_id)
    try:
        yield
    finally:
        _CURRENT_TRACE_ID.reset(token)


@dataclass
class TraceStep:
    name: str
    started_at: float
    sequence: int = 0
    finished_at: float | None = None
    duration_ms: int | None = None
    details: dict[str, Any] = field(default_factory=dict)
    status: str = "RUNNING"
    error_type: str | None = None


@dataclass
class TraceRecorder:
    request_type: str
    trace_id: str = field(default_factory=new_trace_id)
    steps: list[TraceStep] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    _lock: threading.RLock = field(
        default_factory=threading.RLock,
        init=False,
        repr=False,
    )
    _sequence: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        self.trace_id = normalize_trace_id(self.trace_id)

    @contextmanager
    def step(self, name: str, **details: Any):
        with self._lock:
            self._sequence += 1
            entry = TraceStep(
                name=name,
                started_at=perf_counter(),
                sequence=self._sequence,
                details=dict(details),
            )
            self.steps.append(entry)
        logger.info(
            "trace_step_start request_type=%s step=%s sequence=%s details=%s",
            self.request_type,
            name,
            entry.sequence,
            json.dumps(details, ensure_ascii=False, separators=(",", ":"), default=str),
        )
        try:
            yield entry
        except Exception as exc:
            with self._lock:
                entry.status = "ERROR"
                entry.error_type = exc.__class__.__name__
            logger.exception(
                "trace_step_error request_type=%s step=%s sequence=%s error_type=%s",
                self.request_type,
                name,
                entry.sequence,
                entry.error_type,
            )
            raise
        finally:
            with self._lock:
                entry.finished_at = perf_counter()
                entry.duration_ms = int(
                    (entry.finished_at - entry.started_at) * 1000
                )
                if entry.status == "RUNNING":
                    entry.status = "SUCCESS"
                duration_ms = entry.duration_ms
                status = entry.status
                error_type = entry.error_type
                final_details = dict(entry.details)
            logger.info(
                "trace_step_end request_type=%s step=%s sequence=%s status=%s duration_ms=%s error_type=%s details=%s",
                self.request_type,
                name,
                entry.sequence,
                status,
                duration_ms,
                error_type or "none",
                json.dumps(
                    final_details,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    default=str,
                ),
            )

    def set_meta(self, **values: Any) -> None:
        with self._lock:
            self.meta.update(values)

    def to_dict(self) -> dict[str, Any]:
        # Steps may be nested (for example LangGraph contains model/tool calls),
        # so summing them would double-count elapsed time.
        with self._lock:
            steps = list(self.steps)
            meta = dict(self.meta)
        completed = [step for step in steps if step.finished_at is not None]
        total_ms = 0 if not completed else int(
            (max(step.finished_at for step in completed) - min(step.started_at for step in completed)) * 1000
        )
        return {
            "trace_id": self.trace_id,
            "request_type": self.request_type,
            "total_duration_ms": total_ms,
            "meta": meta,
            "steps": [
                {
                    "name": step.name,
                    "sequence": step.sequence,
                    "duration_ms": step.duration_ms,
                    "status": step.status,
                    "error_type": step.error_type,
                    "details": dict(step.details),
                }
                for step in steps
            ],
        }
