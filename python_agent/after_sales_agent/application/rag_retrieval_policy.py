from __future__ import annotations

from typing import Any, ClassVar


class RagRetrievalPolicy:
    _INFRASTRUCTURE_FAILURES: ClassVar[frozenset[str]] = frozenset(
        {
            "EMPTY_QUERY",
            "PGVECTOR_NOT_CONFIGURED",
            "PGVECTOR_DEPENDENCY_MISSING",
            "EMBEDDING_ERROR",
            "PGVECTOR_ERROR",
            "LEXICAL_ERROR",
            "LEXICAL_NOT_CONFIGURED",
            "LEXICAL_DEPENDENCY_MISSING",
            "LEXICAL_FALLBACK_ONLY",
            "LOCAL_JSON_MISSING",
            "LOCAL_FALLBACK_ONLY",
            "UNEXPECTED_ERROR",
        }
    )

    def is_infrastructure_failure(self, result: dict[str, Any]) -> bool:
        failure_reason = str(result.get("failure_reason") or "").strip().upper()
        return (
            failure_reason in self._INFRASTRUCTURE_FAILURES
            or self._is_failure_mode(result.get("mode"))
        )

    @staticmethod
    def _is_failure_mode(value: Any) -> bool:
        mode = str(value or "").strip().lower()
        return (
            mode.endswith("_error")
            or mode.endswith("_not_configured")
            or mode.endswith("_dependency_missing")
            or "degraded" in mode
            or mode in {"embedding_error", "skipped"}
        )
