from __future__ import annotations

import json
import logging
import os
from time import perf_counter
import urllib.request


class LocalModelPrewarmService:
    """Preload local Ollama models without mixing that concern into HTTP routes."""

    def __init__(self) -> None:
        self.status: dict[str, object] = {"state": "not_started", "models": {}}

    def prewarm(self) -> None:
        if os.getenv("LLM_PROVIDER", "remote").strip().lower() != "ollama":
            self.status.update({"state": "skipped_remote_provider"})
            return
        if os.getenv("AGENT_PREWARM_MODELS", "true").strip().lower() not in {"1", "true", "yes", "on"}:
            self.status.update({"state": "disabled"})
            return

        base_url = os.getenv(
            "OLLAMA_BASE_URL",
            os.getenv("QWEN_BASE_URL", "http://127.0.0.1:11434"),
        ).rstrip("/")
        keep_alive = os.getenv("OLLAMA_KEEP_ALIVE", "30m")
        text_model = os.getenv(
            "OLLAMA_MODEL",
            os.getenv("QWEN_MODEL", "qwen2.5:7b"),
        )
        models = [
            text_model,
            os.getenv("EMOTION_MODEL", text_model),
        ]
        if os.getenv("AGENT_PREWARM_VISION", "false").strip().lower() in {"1", "true", "yes", "on"}:
            models.append(os.getenv("VISION_MODEL", "qwen2.5vl:7b"))

        self.status.update({"state": "running", "models": {}})
        for model in dict.fromkeys(models):
            self._prewarm_one(base_url=base_url, keep_alive=keep_alive, model=model)
        self.status["state"] = "completed"

    def _prewarm_one(self, *, base_url: str, keep_alive: str, model: str) -> None:
        started = perf_counter()
        try:
            payload = json.dumps(
                {
                    "model": model,
                    "prompt": "warmup",
                    "stream": False,
                    "keep_alive": keep_alive,
                    "options": {"num_predict": 1, "temperature": 0},
                }
            ).encode("utf-8")
            req = urllib.request.Request(
                f"{base_url}/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as response:
                response.read()
            self.status["models"][model] = {"ok": True, "duration_ms": int((perf_counter() - started) * 1000)}
        except Exception as exc:
            self.status["models"][model] = {"ok": False, "error": exc.__class__.__name__}
            logging.getLogger("api_server.prewarm").warning("model prewarm failed model=%s error=%s", model, exc)
