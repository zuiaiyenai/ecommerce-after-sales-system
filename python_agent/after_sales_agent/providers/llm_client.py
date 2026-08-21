from __future__ import annotations

import base64
from contextvars import ContextVar
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import threading
from typing import Any, Iterator

from jsonschema import validate, ValidationError

from ..infrastructure.request_tracing import TraceRecorder
from .resilient_llm_runtime import (
    FallbackLLMClient,
    LLMClient,
    LLMError,
    LLMResponseParseError,
    OllamaHTTPClient,
    OpenAICompatibleHTTPClient,
    ProviderConfig,
)

logger = logging.getLogger("after_sales_agent.llm_client")


def _read_local_env() -> dict[str, str]:
    """Read local .env file for configuration values."""
    repo_root = Path(__file__).resolve().parents[2]
    candidates = [
        Path.cwd() / "python_agent" / ".env",
        Path.cwd() / ".env",
        repo_root / "python_agent" / ".env",
    ]
    values: dict[str, str] = {}
    for path in candidates:
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
        break
    return values


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
        file_values = _read_local_env()
        provider = (os.getenv("LLM_PROVIDER") or file_values.get("LLM_PROVIDER", "remote")).strip().lower()
        if provider == "ollama":
            return cls(
                provider="ollama",
                base_url=(os.getenv("OLLAMA_BASE_URL") or os.getenv("QWEN_BASE_URL") or file_values.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")),
                api_key="",
                model=(os.getenv("OLLAMA_MODEL") or os.getenv("QWEN_MODEL") or file_values.get("OLLAMA_MODEL", "qwen2.5:7b")),
                timeout_seconds=int(os.getenv("LLM_TOTAL_TIMEOUT_SECONDS") or os.getenv("QWEN_TIMEOUT_SECONDS") or file_values.get("LLM_TOTAL_TIMEOUT_SECONDS", "90")),
                ollama_keep_alive=os.getenv("OLLAMA_KEEP_ALIVE") or file_values.get("OLLAMA_KEEP_ALIVE", "30m"),
            )
        if provider == "dashscope":
            return cls(
                provider="remote",
                base_url=(
                    os.getenv("LLM_BASE_URL")
                    or file_values.get("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode")
                ),
                api_key=(
                    os.getenv("LLM_API_KEY")
                    or file_values.get("LLM_API_KEY")
                    or os.getenv("DASHSCOPE_API_KEY")
                    or file_values.get("DASHSCOPE_API_KEY", "")
                ),
                model=(os.getenv("LLM_MODEL") or file_values.get("LLM_MODEL", "qwen-plus")),
                timeout_seconds=int(
                    os.getenv("LLM_TOTAL_TIMEOUT_SECONDS") or os.getenv("QWEN_TIMEOUT_SECONDS") or file_values.get("LLM_TOTAL_TIMEOUT_SECONDS", "90")
                ),
                ollama_keep_alive=os.getenv("OLLAMA_KEEP_ALIVE") or file_values.get("OLLAMA_KEEP_ALIVE", "30m"),
            )
        return cls(
            provider="remote",
            base_url=(os.getenv("LLM_BASE_URL") or os.getenv("QWEN_BASE_URL") or file_values.get("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode")),
            api_key=(os.getenv("LLM_API_KEY") or os.getenv("QWEN_API_KEY") or file_values.get("LLM_API_KEY", "")),
            model=(os.getenv("LLM_MODEL") or os.getenv("QWEN_MODEL") or file_values.get("LLM_MODEL", "qwen-plus")),
            timeout_seconds=int(os.getenv("LLM_TOTAL_TIMEOUT_SECONDS") or os.getenv("QWEN_TIMEOUT_SECONDS") or file_values.get("LLM_TOTAL_TIMEOUT_SECONDS", "90")),
            ollama_keep_alive=os.getenv("OLLAMA_KEEP_ALIVE") or file_values.get("OLLAMA_KEEP_ALIVE", "30m"),
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

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
        temperature: float = 0.2,
        max_tokens: int = 600,
        retries: int = 2,
    ) -> dict[str, Any]:
        """Structured-output LLM call with bounded, feedback-driven repair.

        The response is parsed locally and validated against ``schema``.  When
        parsing or validation fails, the next attempt receives the previous
        output, a sanitized validation error and the required schema.  Repair is
        capped at two retries.  Exhaustion raises ``LLMResponseParseError`` so
        the application layer can fail closed or hand off; unvalidated JSON is
        never returned as a successful structured response.
        """
        provider = self._client.primary.provider
        recorder = self.trace_recorder

        def _traced_step(name: str, **details: Any) -> Any:
            if recorder is not None:
                return recorder.step(
                    name,
                    model=self.config.model,
                    mode="structured",
                    provider=provider,
                    max_tokens=max_tokens,
                    **details,
                )
            import contextlib
            return contextlib.nullcontext()

        provider = self._client.primary.provider
        # 远程 OpenAI/DashScope 兼容接口使用 json_object；Ollama 接口使用 json。
        kwargs: dict[str, Any] = {
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"} if provider == "remote" else "json",
        }
        last_error: str | None = None
        # 防止调用方误传过大的 retries，保证一次请求最多产生 3 次模型调用。
        repair_retries = max(0, min(int(retries), 2))
        attempts = 1 + repair_retries
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        for attempt in range(attempts):
            with _traced_step(
                "structured_model_call",
                attempt=attempt + 1,
                repair=attempt > 0,
            ):
                response = self.chat(messages, **kwargs)
            content: Any = None
            try:
                if "choices" in response:
                    content = response["choices"][0]["message"]["content"]
                else:
                    content = response["message"]["content"]
                if isinstance(content, dict):
                    parsed = content
                else:
                    parsed = json.loads(content)
                if not isinstance(parsed, dict):
                    raise LLMResponseParseError("structured response is not an object")
                validate(instance=parsed, schema=schema)
                logger.debug("generate_structured succeeded model=%s attempt=%d", self.config.model, attempt + 1)
                return parsed
            except (LLMResponseParseError, ValidationError, json.JSONDecodeError, TypeError, KeyError, IndexError) as exc:
                last_error = self._structured_validation_feedback(exc)
                logger.warning("generate_structured attempt %d failed model=%s error=%s", attempt + 1, self.config.model, last_error)
                if attempt < repair_retries:
                    messages = self._structured_repair_messages(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        previous_content=content,
                        validation_feedback=last_error,
                        schema=schema,
                    )
                    continue
                break

        logger.error(
            "generate_structured exhausted repair attempts model=%s attempts=%d error=%s",
            self.config.model,
            attempts,
            last_error,
        )
        raise LLMResponseParseError(
            f"Structured response failed validation after {attempts} attempts: {last_error or 'unknown_error'}"
        )

    @staticmethod
    def _structured_validation_feedback(exc: Exception) -> str:
        """生成可反馈给模型和日志的有限错误信息，不包含完整业务输入。"""
        if isinstance(exc, ValidationError):
            path = ".".join(str(item) for item in exc.absolute_path) or "$"
            feedback: dict[str, Any] = {
                "kind": "schema_validation_error",
                "path": path,
                "rule": str(exc.validator or "unknown"),
            }
            if exc.validator in {"required", "type", "additionalProperties", "enum"}:
                feedback["expected"] = str(exc.validator_value)[:500]
            return json.dumps(feedback, ensure_ascii=False, default=str)
        if isinstance(exc, json.JSONDecodeError):
            return json.dumps(
                {
                    "kind": "json_decode_error",
                    "line": exc.lineno,
                    "column": exc.colno,
                    "reason": exc.msg,
                },
                ensure_ascii=False,
            )
        if isinstance(exc, (KeyError, IndexError)):
            return json.dumps(
                {"kind": "response_envelope_error", "detail": str(exc)[:200]},
                ensure_ascii=False,
            )
        if isinstance(exc, TypeError):
            return json.dumps({"kind": "invalid_response_type"}, ensure_ascii=False)
        return json.dumps(
            {"kind": "structured_response_error", "reason": str(exc)[:500]},
            ensure_ascii=False,
        )

    @staticmethod
    def _structured_repair_messages(
        *,
        system_prompt: str,
        user_prompt: str,
        previous_content: Any,
        validation_feedback: str,
        schema: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """把上次输出与校验原因反馈给模型，但限制体积以避免重试放大上下文。"""
        if isinstance(previous_content, str):
            previous_text = previous_content
        else:
            previous_text = json.dumps(previous_content, ensure_ascii=False, default=str)
        previous_text = previous_text[:4000]
        schema_text = json.dumps(schema, ensure_ascii=False, separators=(",", ":"), default=str)
        schema_feedback: dict[str, Any]
        if len(schema_text) <= 8000:
            schema_feedback = schema
        else:
            # 极大 schema 只反馈顶层约束，避免一次修复请求把上下文窗口挤满。
            properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
            schema_feedback = {
                "type": schema.get("type"),
                "required": schema.get("required") or [],
                "property_names": list(properties)[:100],
                "additionalProperties": schema.get("additionalProperties"),
                "note": "schema_summary_due_to_size_limit",
            }
        repair_instruction = json.dumps(
            {
                "task": "repair_structured_output",
                "validation_error": json.loads(validation_feedback),
                "required_json_schema": schema_feedback,
                "instructions": [
                    "根据校验错误修复上一次输出",
                    "保持原始任务语义，不添加输入中不存在的事实",
                    "重新输出完整 JSON 对象，不要输出 Markdown 或解释",
                ],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
            {"role": "assistant", "content": previous_text},
            {"role": "user", "content": repair_instruction},
        ]

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
        # Vision models occasionally truncate a large structured answer. Keep one
        # diagnostic retry with a larger budget, and log only a bounded response
        # excerpt so the failure can be diagnosed without dumping the full payload.
        retry_max_tokens = max(max_tokens, 320)
        for attempt, request_max_tokens in enumerate((max_tokens, retry_max_tokens), start=1):
            response = self.chat(messages, temperature=temperature, max_tokens=request_max_tokens)
            raw: Any = None
            try:
                raw = response["choices"][0]["message"]["content"] if "choices" in response else response["message"]["content"]
                parsed = raw if isinstance(raw, dict) else json.loads(raw)
                if not isinstance(parsed, dict):
                    raise TypeError(f"expected JSON object, got {type(parsed).__name__}")
                return parsed
            except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
                raw_excerpt = str(raw if raw is not None else response)[:4000]
                logger.warning(
                    "vision_json_parse_failed model=%s attempt=%d max_tokens=%d error=%s raw_excerpt=%s",
                    self.config.model,
                    attempt,
                    request_max_tokens,
                    type(exc).__name__ + ": " + str(exc),
                    raw_excerpt,
                )
                if attempt == 2:
                    raise LLMResponseParseError(
                        f"Vision model response cannot be parsed as JSON after {attempt} attempts"
                    ) from exc

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
