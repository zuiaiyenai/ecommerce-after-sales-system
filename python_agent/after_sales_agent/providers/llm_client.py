from __future__ import annotations

import base64
from contextvars import ContextVar
from dataclasses import dataclass
import json
import os
import threading
from typing import Any, Iterator

from ..infra.request_tracing import TraceRecorder
from .resilient_llm_runtime import (
    FallbackLLMClient,
    LLMClient,
    LLMError,
    LLMResponseParseError,
    OllamaHTTPClient,
    OpenAICompatibleHTTPClient,
    ProviderConfig,
)


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class LLMRequestContext:
    request_id: str
    session_id: str | None = None
    user_id: str | None = None


@dataclass(frozen=True)
class OpenAICompatibleConfig:
    base_url: str
    api_key: str
    model: str
    timeout_seconds: int = 60
    ollama_keep_alive: str = "30m"
    provider: str = "remote"

    @classmethod
    def from_env(cls) -> "OpenAICompatibleConfig":
        provider = os.getenv("LLM_PROVIDER", "remote").strip().lower()
        if provider == "ollama":
            return cls(
                provider="ollama",
                base_url=os.getenv("OLLAMA_BASE_URL", os.getenv("QWEN_BASE_URL", "http://127.0.0.1:11434")),
                api_key="",
                model=os.getenv("OLLAMA_MODEL", os.getenv("QWEN_MODEL", "qwen2.5:7b")),
                timeout_seconds=int(os.getenv("LLM_TOTAL_TIMEOUT_SECONDS", os.getenv("QWEN_TIMEOUT_SECONDS", "90"))),
                ollama_keep_alive=os.getenv("OLLAMA_KEEP_ALIVE", "30m"),
            )
        return cls(
            provider="remote",
            base_url=os.getenv("LLM_BASE_URL", os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode")),
            api_key=os.getenv("LLM_API_KEY", os.getenv("QWEN_API_KEY", "")),
            model=os.getenv("LLM_MODEL", os.getenv("QWEN_MODEL", "qwen-plus")),
            timeout_seconds=int(os.getenv("LLM_TOTAL_TIMEOUT_SECONDS", os.getenv("QWEN_TIMEOUT_SECONDS", "90"))),
            ollama_keep_alive=os.getenv("OLLAMA_KEEP_ALIVE", "30m"),
        )


def _provider_config(config: OpenAICompatibleConfig, provider: str) -> ProviderConfig:
    prefix = "OLLAMA" if provider == "ollama" else "LLM"
    return ProviderConfig(
        provider=provider,
        base_url=config.base_url,
        api_key=config.api_key,
        model=config.model,
        connect_timeout=float(os.getenv(f"{prefix}_CONNECT_TIMEOUT_SECONDS", os.getenv("LLM_CONNECT_TIMEOUT_SECONDS", "5"))),
        read_timeout=float(os.getenv(f"{prefix}_READ_TIMEOUT_SECONDS", os.getenv("LLM_READ_TIMEOUT_SECONDS", "60"))),
        write_timeout=float(os.getenv(f"{prefix}_WRITE_TIMEOUT_SECONDS", os.getenv("LLM_WRITE_TIMEOUT_SECONDS", "30"))),
        pool_timeout=float(os.getenv(f"{prefix}_POOL_TIMEOUT_SECONDS", os.getenv("LLM_POOL_TIMEOUT_SECONDS", "5"))),
        total_timeout=float(os.getenv(f"{prefix}_TOTAL_TIMEOUT_SECONDS", str(config.timeout_seconds))),
        max_concurrent=int(os.getenv(f"{prefix}_MAX_CONCURRENT_REQUESTS", "2" if provider == "ollama" else os.getenv("LLM_MAX_CONCURRENT_REQUESTS", "20"))),
        max_queue_wait=float(os.getenv(f"{prefix}_MAX_QUEUE_WAIT_SECONDS", os.getenv("LLM_MAX_QUEUE_WAIT_SECONDS", "10"))),
        max_connections=int(os.getenv(f"{prefix}_MAX_CONNECTIONS", os.getenv("LLM_MAX_CONNECTIONS", "50"))),
        max_keepalive_connections=int(os.getenv(f"{prefix}_MAX_KEEPALIVE_CONNECTIONS", os.getenv("LLM_MAX_KEEPALIVE_CONNECTIONS", "20"))),
        keepalive_expiry=float(os.getenv(f"{prefix}_KEEPALIVE_EXPIRY_SECONDS", os.getenv("LLM_KEEPALIVE_EXPIRY_SECONDS", "30"))),
        max_retries=int(os.getenv(f"{prefix}_MAX_RETRIES", os.getenv("LLM_MAX_RETRIES", "2"))),
        retry_base_delay=float(os.getenv("LLM_RETRY_BASE_DELAY_SECONDS", "1")),
        retry_max_delay=float(os.getenv("LLM_RETRY_MAX_DELAY_SECONDS", "8")),
        circuit_failure_threshold=int(os.getenv(f"{prefix}_CIRCUIT_FAILURE_THRESHOLD", os.getenv("LLM_CIRCUIT_FAILURE_THRESHOLD", "5"))),
        circuit_recovery_seconds=float(os.getenv(f"{prefix}_CIRCUIT_RECOVERY_SECONDS", os.getenv("LLM_CIRCUIT_RECOVERY_SECONDS", "30"))),
        ollama_keep_alive=config.ollama_keep_alive,
    )


class OpenAICompatibleClient:
    """Backward-compatible facade used by the existing Agent services."""

    def __init__(self, config: OpenAICompatibleConfig) -> None:
        self.config = config
        self._trace_recorder: ContextVar[TraceRecorder | None] = ContextVar("llm_trace_recorder", default=None)
        effective_provider = "ollama" if config.provider == "ollama" or config.base_url.rstrip("/").endswith(":11434") else "remote"
        primary: LLMClient
        if effective_provider == "ollama":
            primary = OllamaHTTPClient(_provider_config(config, "ollama"))
        else:
            primary = OpenAICompatibleHTTPClient(_provider_config(config, "remote"))
        fallback: LLMClient | None = None
        if effective_provider == "remote" and _env_bool("LLM_FALLBACK_ENABLED", True) and os.getenv("LLM_FALLBACK_PROVIDER", "ollama").lower() == "ollama":
            fallback_config = OpenAICompatibleConfig(
                provider="ollama",
                base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
                api_key="",
                model=os.getenv("OLLAMA_MODEL", os.getenv("QWEN_MODEL", "qwen2.5:7b")),
                timeout_seconds=int(os.getenv("OLLAMA_TOTAL_TIMEOUT_SECONDS", "90")),
                ollama_keep_alive=os.getenv("OLLAMA_KEEP_ALIVE", "30m"),
            )
            fallback = OllamaHTTPClient(_provider_config(fallback_config, "ollama"))
        self._client = FallbackLLMClient(primary, fallback)

    def bind_trace(self, trace_recorder: TraceRecorder | None) -> None:
        self._trace_recorder.set(trace_recorder)

    @property
    def trace_recorder(self) -> TraceRecorder | None:
        return self._trace_recorder.get()

    def close(self) -> None:
        self._client.close()

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, **kwargs: Any) -> dict[str, Any]:
        kwargs.pop("context", None)
        self._apply_provider_defaults(kwargs)
        return self._client.chat(messages, tools, **kwargs)

    def stream_chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, **kwargs: Any) -> Iterator[dict[str, Any]]:
        kwargs.pop("context", None)
        self._apply_provider_defaults(kwargs)
        return self._client.stream_chat(messages, tools, **kwargs)

    def _apply_provider_defaults(self, kwargs: dict[str, Any]) -> None:
        if self._client.primary.provider == "remote" and self.config.model.startswith("deepseek-"):
            thinking_enabled = _env_bool("LLM_THINKING_ENABLED", False)
            kwargs.setdefault("thinking", {"type": "enabled" if thinking_enabled else "disabled"})

    def chat_json(self, *, system_prompt: str, user_prompt: str, temperature: float = 0.2, max_tokens: int = 600) -> dict[str, Any]:
        provider = self._client.primary.provider
        recorder = self.trace_recorder
        if recorder is not None:
            with recorder.step("text_model_call", model=self.config.model, mode="text", provider=provider, max_tokens=max_tokens):
                return self._chat_json(system_prompt, user_prompt, temperature, max_tokens)
        return self._chat_json(system_prompt, user_prompt, temperature, max_tokens)

    def _chat_json(self, system_prompt: str, user_prompt: str, temperature: float, max_tokens: int) -> dict[str, Any]:
        response = self.chat(
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        try:
            if "choices" in response:
                content = response["choices"][0]["message"]["content"]
            else:
                content = response["message"]["content"]
            if isinstance(content, dict):
                return content
            return json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise LLMResponseParseError("Model response content cannot be parsed as JSON") from exc

    def chat_multimodal_json(self, *, system_prompt: str, user_text: str, image_urls: list[str], temperature: float = 0.1, max_tokens: int = 180) -> dict[str, Any]:
        if self._client.primary.provider == "ollama":
            content: Any = user_text
            images = [self._extract_base64_image(value) for value in image_urls]
            messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": content, "images": images}]
        else:
            content = [{"type": "text", "text": user_text}]
            content.extend({"type": "image_url", "image_url": {"url": value}} for value in image_urls)
            messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": content}]
        response = self.chat(messages, temperature=temperature, max_tokens=max_tokens)
        try:
            raw = response["choices"][0]["message"]["content"] if "choices" in response else response["message"]["content"]
            return raw if isinstance(raw, dict) else json.loads(raw)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise LLMResponseParseError("Vision model response cannot be parsed as JSON") from exc

    @staticmethod
    def _extract_base64_image(image_url: str) -> str:
        if image_url.startswith("data:"):
            parts = image_url.split(",", 1)
            if len(parts) != 2 or not parts[1]:
                raise LLMError("Invalid image data URL")
            return parts[1]
        return base64.b64encode(image_url.encode("utf-8")).decode("utf-8")


class LLMClientManager:
    """Single owner for pooled model clients and their shutdown lifecycle."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._clients: dict[OpenAICompatibleConfig, OpenAICompatibleClient] = {}

    def get(self, config: OpenAICompatibleConfig | None = None) -> OpenAICompatibleClient:
        resolved = config or OpenAICompatibleConfig.from_env()
        with self._lock:
            client = self._clients.get(resolved)
            if client is None:
                client = OpenAICompatibleClient(resolved)
                self._clients[resolved] = client
            return client

    def close(self) -> None:
        with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
        for client in clients:
            client.close()


LLM_CLIENTS = LLMClientManager()


def get_llm_client(config: OpenAICompatibleConfig | None = None) -> OpenAICompatibleClient:
    return LLM_CLIENTS.get(config)
