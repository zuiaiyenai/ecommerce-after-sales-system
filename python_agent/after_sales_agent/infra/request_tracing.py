from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import hashlib
import logging
import re
import secrets
from time import perf_counter
from typing import Any


TRACE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_CURRENT_TRACE_ID: ContextVar[str | None] = ContextVar("agent_trace_id", default=None)


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
    finished_at: float | None = None
    duration_ms: int | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class TraceRecorder:
    request_type: str
    trace_id: str = field(default_factory=new_trace_id)
    steps: list[TraceStep] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.trace_id = normalize_trace_id(self.trace_id)

    @contextmanager
    def step(self, name: str, **details: Any):
        entry = TraceStep(name=name, started_at=perf_counter(), details=dict(details))
        self.steps.append(entry)
        try:
            yield entry
        finally:
            entry.finished_at = perf_counter()
            entry.duration_ms = int((entry.finished_at - entry.started_at) * 1000)

    def set_meta(self, **values: Any) -> None:
        self.meta.update(values)

    def to_dict(self) -> dict[str, Any]:
        # Steps may be nested (for example LangGraph contains model/tool calls),
        # so summing them would double-count elapsed time.
        completed = [step for step in self.steps if step.finished_at is not None]
        total_ms = 0 if not completed else int(
            (max(step.finished_at for step in completed) - min(step.started_at for step in completed)) * 1000
        )
        return {
            "trace_id": self.trace_id,
            "request_type": self.request_type,
            "total_duration_ms": total_ms,
            "meta": self.meta,
            "steps": [
                {
                    "name": step.name,
                    "duration_ms": step.duration_ms,
                    "details": step.details,
                }
                for step in self.steps
            ],
        }
