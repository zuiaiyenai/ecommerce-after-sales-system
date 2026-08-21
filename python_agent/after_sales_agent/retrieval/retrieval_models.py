"""Shared data structures for the retrieval pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RetrievalResult:
    """Structured retrieval result."""
    mode: str
    hits: list[dict[str, Any]] = field(default_factory=list)
    filter_level: str = "strict"
    reranker_succeeded: bool = False
    threshold: float = 0.6
    no_answer: bool = True
    trusted_policy_eligible: bool = False
    failure_reason: str | None = None
    trace: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = {
            "mode": self.mode,
            "hits": self.hits,
            "filter_level": self.filter_level,
            "reranker_succeeded": self.reranker_succeeded,
            "threshold": self.threshold,
            "no_answer": self.no_answer,
            "trusted_policy_eligible": self.trusted_policy_eligible,
            "failure_reason": self.failure_reason,
            "trace": self.trace,
        }
        return d
