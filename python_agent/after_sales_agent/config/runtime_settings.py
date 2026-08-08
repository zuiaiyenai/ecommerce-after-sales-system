"""Shared local-only configuration helpers for the Python Agent."""
from __future__ import annotations

import os
from pathlib import Path


def resolve_agent_internal_token() -> str:
    """Resolve one shared Java/Python secret without duplicating shell exports."""
    return (
        os.getenv("AFTERSALES_AGENT_INTERNAL_TOKEN")
        or os.getenv("AGENT_INTERNAL_TOKEN")
        or _read_property("app.agent.internal-token")
        or ""
    )


def _read_property(key: str) -> str:
    candidates = (
        Path.cwd() / "agent.local.properties",
        Path(__file__).resolve().parents[3] / "agent.local.properties",
    )
    for path in candidates:
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            if name.strip() == key:
                return value.strip()
    return ""
