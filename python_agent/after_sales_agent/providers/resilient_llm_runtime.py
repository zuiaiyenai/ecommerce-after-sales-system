from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import logging
import random
import threading
import time
from typing import Any, AsyncIterator, Iterator, Protocol

import httpx

from after_sales_agent.infrastructure import CircuitBreaker, CircuitOpenError


logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    retryable = False


class LLMTimeoutError(LLMError):
    retryable = True


class LLMRateLimitError(LLMError):
    retryable = True


class LLMAuthenticationError(LLMError):
    pass


class LLMInvalidRequestError(LLMError):
    pass


class LLMProviderUnavailableError(LLMError):
    retryable = True


class LLMContextLengthError(LLMInvalidRequestError):
    pass


class LLMResponseParseError(LLMError):
    pass


class LLMStreamInterruptedError(LLMError):
    retryable = True


class LLMConcurrencyLimitError(LLMError):
    retryable = True


class LLMCircuitOpenError(LLMProviderUnavailableError):
    pass


class LLMClient(Protocol):
    provider: str
    model: str

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, **kwargs: Any) -> dict[str, Any]: ...
    def stream_chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, **kwargs: Any) -> Iterator[dict[str, Any]]: ...
    def close(self) -> None: ...


def _render_tool_history(
    messages: list[dict[str, Any]],
    *,
    provider: str,
) -> list[dict[str, Any]]:
    rendered = _normalize_tool_history(messages)
    for index, message in enumerate(rendered):
        if message.get("tool_calls") is not None:
            _render_assistant_tool_message(message, provider=provider, index=index)
        elif message.get("role") == "tool":
            _render_tool_observation_message(message, provider=provider, index=index)
    return rendered


def _normalize_tool_history(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(messages, list):
        raise LLMInvalidRequestError("LLM messages must be a list")
    normalized = deepcopy(messages)
    pending: tuple[str, str] | None = None
    seen_call_ids: set[str] = set()
    for index, message in enumerate(normalized):
        if not isinstance(message, dict):
            raise LLMInvalidRequestError(f"LLM message {index} must be an object")
        is_tool_observation = message.get("role") == "tool"
        has_tool_calls = message.get("tool_calls") is not None
        if pending is not None:
            if not is_tool_observation:
                raise LLMInvalidRequestError(
                    f"LLM assistant tool call before message {index} requires an adjacent tool observation"
                )
            _normalize_tool_observation(message, pending=pending, index=index)
            pending = None
            continue
        if is_tool_observation:
            raise LLMInvalidRequestError(f"LLM tool message {index} is orphaned or duplicated")
        if has_tool_calls:
            call_id, name = _normalize_assistant_tool_call(message, index=index)
            if call_id in seen_call_ids:
                raise LLMInvalidRequestError(
                    f"LLM message {index} reuses tool call id {call_id}"
                )
            seen_call_ids.add(call_id)
            pending = (call_id, name)
    if pending is not None:
        raise LLMInvalidRequestError("LLM assistant tool call is missing its adjacent tool observation")
    return normalized


def _normalize_assistant_tool_call(
    message: dict[str, Any],
    *,
    index: int,
) -> tuple[str, str]:
    if message.get("role") != "assistant":
        raise LLMInvalidRequestError(f"LLM message {index} tool calls require assistant role")
    content = message.get("content")
    if content is not None and not isinstance(content, str):
        raise LLMInvalidRequestError(f"LLM message {index} content must be text or null")
    calls = message.get("tool_calls")
    if not isinstance(calls, list) or len(calls) != 1:
        raise LLMInvalidRequestError(
            f"LLM message {index} tool_calls must contain exactly one call"
        )
    call = calls[0]
    if not isinstance(call, dict):
        raise LLMInvalidRequestError(f"LLM message {index} tool call 0 must be an object")
    call_id = call.get("id")
    if not isinstance(call_id, str) or not call_id.strip():
        raise LLMInvalidRequestError(f"LLM message {index} tool call 0 requires id")
    call_id = call_id.strip()
    if call.get("type") != "function":
        raise LLMInvalidRequestError(
            f"LLM message {index} tool call 0 must use function type"
        )
    function = call.get("function")
    if not isinstance(function, dict):
        raise LLMInvalidRequestError(f"LLM message {index} tool call 0 requires function")
    name = function.get("name")
    if not isinstance(name, str) or not name.strip():
        raise LLMInvalidRequestError(
            f"LLM message {index} tool call 0 requires function name"
        )
    name = name.strip()
    arguments = function.get("arguments")
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments, parse_constant=_reject_json_constant)
        except (json.JSONDecodeError, ValueError) as exc:
            raise LLMInvalidRequestError(
                f"LLM message {index} tool call 0 arguments must be valid JSON"
            ) from exc
    if not isinstance(arguments, dict):
        raise LLMInvalidRequestError(
            f"LLM message {index} tool call 0 arguments must be an object"
        )
    try:
        json.dumps(arguments, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise LLMInvalidRequestError(
            f"LLM message {index} tool call 0 arguments are not JSON-compatible"
        ) from exc
    call["id"] = call_id
    function["name"] = name
    function["arguments"] = arguments
    return call_id, name


def _normalize_tool_observation(
    message: dict[str, Any],
    *,
    pending: tuple[str, str],
    index: int,
) -> None:
    if message.get("tool_calls") is not None:
        raise LLMInvalidRequestError(f"LLM tool message {index} cannot contain tool_calls")
    pending_id, pending_name = pending
    call_id = message.get("tool_call_id")
    if not isinstance(call_id, str) or not call_id.strip():
        raise LLMInvalidRequestError(f"LLM tool message {index} requires tool_call_id")
    if call_id.strip() != pending_id:
        raise LLMInvalidRequestError(
            f"LLM tool message {index} tool_call_id does not match the pending call"
        )
    if "name" not in message:
        message["name"] = pending_name
    else:
        name = message.get("name")
        if not isinstance(name, str) or name.strip() != pending_name:
            raise LLMInvalidRequestError(
                f"LLM tool message {index} name does not match the pending call"
            )
        message["name"] = name.strip()
    if not isinstance(message.get("content"), str):
        raise LLMInvalidRequestError(f"LLM tool message {index} content must be text")
    message["tool_call_id"] = pending_id


def _reject_json_constant(value: str) -> Any:
    raise ValueError(f"invalid JSON constant: {value}")


def _render_assistant_tool_message(
    message: dict[str, Any],
    *,
    provider: str,
    index: int,
) -> None:
    if message.get("role") != "assistant":
        raise LLMInvalidRequestError(f"LLM message {index} tool calls require assistant role")
    content = message.get("content")
    if content is not None and not isinstance(content, str):
        raise LLMInvalidRequestError(f"LLM message {index} content must be text or null")
    calls = message.get("tool_calls")
    if not isinstance(calls, list) or not calls:
        raise LLMInvalidRequestError(f"LLM message {index} tool_calls must be a non-empty list")
    for call_index, call in enumerate(calls):
        if not isinstance(call, dict):
            raise LLMInvalidRequestError(
                f"LLM message {index} tool call {call_index} must be an object"
            )
        call_id = call.get("id")
        if not isinstance(call_id, str) or not call_id.strip():
            raise LLMInvalidRequestError(
                f"LLM message {index} tool call {call_index} requires id"
            )
        if call.get("type") != "function":
            raise LLMInvalidRequestError(
                f"LLM message {index} tool call {call_index} must use function type"
            )
        function = call.get("function")
        if not isinstance(function, dict):
            raise LLMInvalidRequestError(
                f"LLM message {index} tool call {call_index} requires function"
            )
        name = function.get("name")
        if not isinstance(name, str) or not name.strip():
            raise LLMInvalidRequestError(
                f"LLM message {index} tool call {call_index} requires function name"
            )
        arguments = function.get("arguments")
        if not isinstance(arguments, dict):
            raise LLMInvalidRequestError(
                f"LLM message {index} tool call {call_index} arguments must be an object"
            )
        if provider == "openai":
            try:
                function["arguments"] = json.dumps(
                    arguments,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=False,
                )
            except (TypeError, ValueError) as exc:
                raise LLMInvalidRequestError(
                    f"LLM message {index} tool call {call_index} arguments are not JSON-compatible"
                ) from exc
        else:
            call.pop("id", None)
            call.pop("type", None)


def _render_tool_observation_message(
    message: dict[str, Any],
    *,
    provider: str,
    index: int,
) -> None:
    call_id = message.get("tool_call_id")
    if not isinstance(call_id, str) or not call_id.strip():
        raise LLMInvalidRequestError(f"LLM tool message {index} requires tool_call_id")
    name = message.get("name")
    if not isinstance(name, str) or not name.strip():
        raise LLMInvalidRequestError(f"LLM tool message {index} requires name")
    if not isinstance(message.get("content"), str):
        raise LLMInvalidRequestError(f"LLM tool message {index} content must be text")
    if provider == "ollama":
        message.pop("tool_call_id", None)
        message.pop("name", None)


class AsyncLLMClient(Protocol):
    """Reserved boundary for a future async service; no sync implementation is wrapped here."""
    provider: str
    model: str

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, **kwargs: Any) -> dict[str, Any]: ...
    def stream_chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, **kwargs: Any) -> AsyncIterator[dict[str, Any]]: ...
    async def close(self) -> None: ...


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    base_url: str
    api_key: str
    model: str
    connect_timeout: float
    read_timeout: float
    write_timeout: float
    pool_timeout: float
    total_timeout: float
    max_concurrent: int
    max_queue_wait: float
    max_connections: int
    max_keepalive_connections: int
    keepalive_expiry: float
    max_retries: int
    retry_base_delay: float
    retry_max_delay: float
    circuit_failure_threshold: int
    circuit_recovery_seconds: float
    ollama_keep_alive: str = "30m"


class BaseHTTPModelClient:
    def __init__(self, config: ProviderConfig, client: httpx.Client | None = None) -> None:
        self.config = config
        self.provider = config.provider
        self.model = config.model
        self._semaphore = threading.BoundedSemaphore(max(1, config.max_concurrent))
        self._circuit = CircuitBreaker(
            threshold=config.circuit_failure_threshold,
            recovery_seconds=config.circuit_recovery_seconds,
        )
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=config.base_url.rstrip("/"),
            timeout=httpx.Timeout(connect=config.connect_timeout, read=config.read_timeout, write=config.write_timeout, pool=config.pool_timeout),
            limits=httpx.Limits(max_connections=config.max_connections, max_keepalive_connections=config.max_keepalive_connections, keepalive_expiry=config.keepalive_expiry),
            headers={"Authorization": f"Bearer {config.api_key}"} if config.api_key else {},
        )
        self._use_urllib = False  # Flag to fallback to urllib if httpx has SSL issues

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _acquire(self) -> float:
        started = time.monotonic()
        if not self._semaphore.acquire(timeout=self.config.max_queue_wait):
            raise LLMConcurrencyLimitError("LLM request queue wait timeout")
        return (time.monotonic() - started) * 1000

    def _request(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        queue_ms = self._acquire()
        started = time.monotonic()
        try:
            self._circuit.before_call()
            for attempt in range(self.config.max_retries + 1):
                try:
                    if self._use_urllib:
                        result = self._request_with_urllib(path, payload)
                    else:
                        try:
                            response = self._client.post(path, json=payload, timeout=self.config.total_timeout)
                            if response.status_code >= 400:
                                raise self._classify_status(response)
                            result = response.json()
                        except (httpx.ConnectError, httpx.NetworkError) as exc:
                            # SSL issue detected, fallback to urllib
                            logger.warning("llm_httpx_fallback_to_urllib provider=%s model=%s error=%s", self.provider, self.model, type(exc).__name__)
                            self._use_urllib = True
                            result = self._request_with_urllib(path, payload)
                    self._circuit.success()
                    logger.info("llm_call provider=%s model=%s queue_ms=%.1f total_ms=%.1f retries=%d", self.provider, self.model, queue_ms, (time.monotonic() - started) * 1000, attempt)
                    return result
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    error: LLMError = LLMTimeoutError("LLM request timed out") if isinstance(exc, httpx.TimeoutException) else LLMProviderUnavailableError("LLM network unavailable")
                except json.JSONDecodeError as exc:
                    raise LLMResponseParseError("LLM response is not valid JSON") from exc
                except LLMError as exc:
                    error = exc
                if not error.retryable or attempt >= self.config.max_retries:
                    if error.retryable:
                        self._circuit.failure()
                    raise error
                delay = min(self.config.retry_max_delay, self.config.retry_base_delay * (2 ** attempt))
                delay *= random.uniform(0.5, 1.5)
                logger.warning("llm_retry provider=%s model=%s attempt=%d error=%s", self.provider, self.model, attempt + 1, error.__class__.__name__)
                time.sleep(delay)
            raise LLMProviderUnavailableError("LLM request failed")
        finally:
            self._semaphore.release()

    def _request_with_urllib(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Fallback to urllib when httpx has SSL issues."""
        import urllib.error
        import urllib.request

        base_url = self.config.base_url.rstrip("/")
        url = f"{base_url}/{path}"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
        }
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.config.total_timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            # Create a mock response for _classify_status
            raise LLMProviderUnavailableError(f"LLM provider unavailable (HTTP {exc.code}): {error_body[:200]}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise LLMTimeoutError(f"LLM request timed out: {exc}") from exc

    @staticmethod
    def _classify_status(response: httpx.Response) -> LLMError:
        status = response.status_code
        detail = response.text[:500].lower()
        if status in (401, 403):
            return LLMAuthenticationError(f"LLM authentication failed (HTTP {status})")
        if status == 429:
            return LLMRateLimitError("LLM rate limit exceeded")
        if status in (502, 503, 504) or status >= 500:
            return LLMProviderUnavailableError(f"LLM provider unavailable (HTTP {status})")
        if "context" in detail and ("length" in detail or "token" in detail):
            return LLMContextLengthError("LLM context length exceeded")
        provider_detail = BaseHTTPModelClient._provider_error_detail(response)
        suffix = f": {provider_detail}" if provider_detail else ""
        return LLMInvalidRequestError(f"LLM request rejected (HTTP {status}){suffix}")

    @staticmethod
    def _provider_error_detail(response: httpx.Response) -> str:
        """Keep provider error code/message while never echoing the request payload."""
        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError):
            return ""
        error = payload.get("error") if isinstance(payload, dict) else None
        if not isinstance(error, dict):
            return ""
        code = str(error.get("code") or "").strip()
        message = str(error.get("message") or "").strip().replace("\r", " ").replace("\n", " ")
        parts = [part for part in (code[:100], message[:300]) if part]
        return " - ".join(parts)


class OpenAICompatibleHTTPClient(BaseHTTPModelClient):
    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, **kwargs: Any) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": _render_tool_history(messages, provider="openai"),
            "stream": False,
            **kwargs,
        }
        if tools:
            payload["tools"] = tools
        return self._request("v1/chat/completions", payload)

    def stream_chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, **kwargs: Any) -> Iterator[dict[str, Any]]:
        payload = {
            "model": self.model,
            "messages": _render_tool_history(messages, provider="openai"),
            "stream": True,
            **kwargs,
        }
        if tools:
            payload["tools"] = tools
        self._circuit.before_call()
        queue_ms = self._acquire()
        emitted = False
        started = time.monotonic()
        try:
            with self._client.stream("POST", "v1/chat/completions", json=payload, timeout=self.config.total_timeout) as response:
                if response.status_code >= 400:
                    response.read()
                    raise self._classify_status(response)
                for line in response.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError as exc:
                        raise LLMStreamInterruptedError("Invalid LLM stream event") from exc
                    if not emitted:
                        logger.info("llm_first_token provider=%s model=%s queue_ms=%.1f first_token_ms=%.1f", self.provider, self.model, queue_ms, (time.monotonic() - started) * 1000)
                        emitted = True
                    yield event
            self._circuit.success()
        except GeneratorExit:
            raise
        except (httpx.HTTPError, LLMError) as exc:
            self._circuit.failure()
            if isinstance(exc, LLMError):
                raise
            raise LLMStreamInterruptedError("LLM stream interrupted") from exc
        finally:
            self._semaphore.release()


class OllamaHTTPClient(BaseHTTPModelClient):
    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, **kwargs: Any) -> dict[str, Any]:
        options = {"temperature": kwargs.pop("temperature", 0.2), "num_predict": kwargs.pop("max_tokens", 600)}
        payload = {
            "model": self.model,
            "messages": _render_tool_history(messages, provider="ollama"),
            "stream": False,
            "format": kwargs.pop("response_format", "json"),
            "keep_alive": self.config.ollama_keep_alive,
            "options": options,
        }
        if tools:
            payload["tools"] = tools
        return self._request("api/chat", payload)

    def stream_chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, **kwargs: Any) -> Iterator[dict[str, Any]]:
        raise LLMInvalidRequestError("Ollama streaming is not exposed by the current Agent HTTP protocol")


class FallbackLLMClient:
    def __init__(self, primary: LLMClient, fallback: LLMClient | None) -> None:
        self.primary = primary
        self.fallback = fallback
        self.provider = primary.provider
        self.model = primary.model

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, **kwargs: Any) -> dict[str, Any]:
        try:
            return self.primary.chat(messages, tools, **kwargs)
        except (LLMTimeoutError, LLMRateLimitError, LLMProviderUnavailableError, LLMConcurrencyLimitError) as exc:
            if self.fallback is None:
                raise
            logger.warning("llm_fallback from_provider=%s to_provider=%s reason=%s", self.primary.provider, self.fallback.provider, exc.__class__.__name__)
            return self.fallback.chat(messages, tools, **kwargs)

    def stream_chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, **kwargs: Any) -> Iterator[dict[str, Any]]:
        # Only fall back before the first chunk; replaying after output starts duplicates content.
        try:
            iterator = self.primary.stream_chat(messages, tools, **kwargs)
            first = next(iterator)
        except StopIteration:
            return
        except (LLMTimeoutError, LLMRateLimitError, LLMProviderUnavailableError, LLMConcurrencyLimitError):
            if self.fallback is None:
                raise
            yield from self.fallback.stream_chat(messages, tools, **kwargs)
            return
        yield first
        yield from iterator

    def close(self) -> None:
        self.primary.close()
        if self.fallback is not None:
            self.fallback.close()
