from __future__ import annotations

import os
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def load_agent_env(*, override: bool | None = None) -> Path | None:
    """Load local Agent settings without overriding deployment environment variables."""
    should_override = _env_bool("AGENT_ENV_OVERRIDE", True) if override is None else override
    candidates = (
        Path(__file__).resolve().parent / ".env",
        Path.cwd() / "python_agent" / ".env",
        Path.cwd() / ".env",
        Path(__file__).resolve().parents[2] / ".env",
    )
    for path in candidates:
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            name = name.strip()
            value = value.strip().strip('"').strip("'")
            if name:
                if should_override:
                    os.environ[name] = value
                else:
                    os.environ.setdefault(name, value)
        return path
    return None
