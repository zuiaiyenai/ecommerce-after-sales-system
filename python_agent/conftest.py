"""Pytest hooks to work around a broken .pytest_cache directory."""
from __future__ import annotations

import os
import pytest
from pathlib import Path
from typing import Optional


# RERANK env vars loaded by .env that must not leak between tests
_RERANK_ENV_KEYS = frozenset([
    "RERANK_PROVIDER",
    "RERANK_BASE_URL",
    "RERANK_API_KEY",
    "RERANK_MODEL",
    "RERANK_TIMEOUT_SECONDS",
    "RERANK_MAX_RETRIES",
    "RERANK_MAX_CANDIDATES",
    "RERANK_MAX_CONCURRENCY",
    "RERANK_CIRCUIT_FAILURE_THRESHOLD",
    "RERANK_CIRCUIT_RECOVERY_SECONDS",
])


def pytest_ignore_collect(
    collection_path: Path,
    path: Optional[str] = None,
    config: object = None,
) -> bool:
    """Skip the unreadable .pytest_cache directory during collection."""
    try:
        return collection_path.name == ".pytest_cache"
    except Exception:
        return False


def _save_rerank_env() -> dict[str, str | None]:
    return {k: os.environ.pop(k, None) for k in _RERANK_ENV_KEYS}


def _restore_rerank_env(saved: dict[str, str | None]) -> None:
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def pytest_configure(config):
    """Save and neutralise RERANK env vars before the test session starts."""
    _save_rerank_env()
    try:
        from after_sales_agent.providers.reranker_client import RERANKER_CLIENTS
        RERANKER_CLIENTS.reset()
    except Exception:
        pass


def pytest_unconfigure(config):
    """Restore RERANK env vars and reset singleton after the session ends."""
    _restore_rerank_env({})
    try:
        from after_sales_agent.providers.reranker_client import RERANKER_CLIENTS
        RERANKER_CLIENTS.reset()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def reset_reranker_singleton():
    """Reset RERANKER_CLIENTS and RERANK env vars before and after each test
    to prevent singleton state leakage and .env pollution between tests."""
    saved = _save_rerank_env()
    try:
        from after_sales_agent.providers.reranker_client import RERANKER_CLIENTS
        RERANKER_CLIENTS.reset()
    except Exception as e:
        _restore_rerank_env(saved)
        raise
    yield
    _restore_rerank_env(saved)
    try:
        from after_sales_agent.providers.reranker_client import RERANKER_CLIENTS
        RERANKER_CLIENTS.reset()
    except Exception:
        pass
