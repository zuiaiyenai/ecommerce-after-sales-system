from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any


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
    steps: list[TraceStep] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

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
        total_ms = sum(step.duration_ms or 0 for step in self.steps)
        return {
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

