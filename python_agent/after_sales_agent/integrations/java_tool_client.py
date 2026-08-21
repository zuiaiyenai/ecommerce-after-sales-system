from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any
from urllib import error, parse, request

from ..config.runtime_settings import resolve_agent_internal_token
from ..infrastructure.request_tracing import current_trace_id


class JavaToolError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        category: str,
        retryable: bool,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.category = category
        self.retryable = retryable
        self.http_status = http_status


@dataclass(frozen=True)
class JavaToolConfig:
    base_url: str
    timeout_seconds: int = 8
    internal_token: str = ""

    @classmethod
    def from_env(cls) -> "JavaToolConfig":
        return cls(
            base_url=os.getenv("AFTERSALES_JAVA_TOOL_BASE_URL", "http://127.0.0.1:8080/api/internal/agent-tools"),
            timeout_seconds=int(os.getenv("AFTERSALES_JAVA_TOOL_TIMEOUT_SECONDS", "8")),
            internal_token=resolve_agent_internal_token(),
        )


class JavaToolClient:
    """HTTP client for ordinary Java business APIs.

    The Python Agent owns tool schemas and reasoning. Java only receives normal
    business requests and performs authority, state-machine, and transaction checks.
    """

    def __init__(self, config: JavaToolConfig | None = None) -> None:
        self.config = config or JavaToolConfig.from_env()

    def get(self, path: str, params: dict[str, Any]) -> Any:
        query = parse.urlencode({key: value for key, value in params.items() if value is not None})
        url = f"{self.config.base_url.rstrip('/')}/{path.lstrip('/')}?{query}"
        req = request.Request(url, headers=self._headers(), method="GET")
        return self._send(req)

    def post(self, path: str, payload: dict[str, Any]) -> Any:
        url = f"{self.config.base_url.rstrip('/')}/{path.lstrip('/')}"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(url, data=body, headers=self._headers(), method="POST")
        return self._send(req)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
        }
        if self.config.internal_token:
            headers["X-Agent-Internal-Token"] = self.config.internal_token
        trace_id = current_trace_id()
        if trace_id:
            headers["X-Trace-Id"] = trace_id
        return headers

    def _send(self, req: request.Request) -> Any:
        try:
            with request.urlopen(req, timeout=self.config.timeout_seconds) as resp:
                raw = resp.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise JavaToolError(
                self._safe_error_message(detail, f"Java business API rejected request (HTTP {exc.code})"),
                code=f"JAVA_HTTP_{exc.code}",
                category=self._http_error_category(exc.code),
                retryable=exc.code == 429 or exc.code >= 500,
                http_status=exc.code,
            ) from exc
        except error.URLError as exc:
            is_timeout = isinstance(exc.reason, TimeoutError)
            raise JavaToolError(
                "Java business API timed out" if is_timeout else "Java business API is unavailable",
                code="JAVA_TIMEOUT" if is_timeout else "JAVA_UNAVAILABLE",
                category="timeout" if is_timeout else "service_unavailable",
                retryable=True,
            ) from exc

        try:
            body = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise JavaToolError(
                "Java business API returned an invalid response",
                code="JAVA_INVALID_RESPONSE",
                category="tool_error",
                retryable=False,
            ) from exc

        if isinstance(body, dict) and body.get("code") not in (None, 200):
            status = self._optional_int(body.get("code"))
            raise JavaToolError(
                str(body.get("message") or "Java business API rejected request"),
                code=f"JAVA_BUSINESS_{body.get('code')}",
                category=self._http_error_category(status),
                retryable=status == 429 or bool(status and status >= 500),
                http_status=status,
            )
        return body.get("data") if isinstance(body, dict) and "data" in body else body

    @staticmethod
    def _safe_error_message(detail: str, fallback: str) -> str:
        try:
            body = json.loads(detail)
        except (json.JSONDecodeError, TypeError):
            return fallback
        if isinstance(body, dict):
            return str(body.get("message") or body.get("error") or fallback)[:240]
        return fallback

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _http_error_category(status: int | None) -> str:
        if status in {401, 403}:
            return "permission"
        if status == 404:
            return "not_found"
        if status == 408:
            return "timeout"
        if status == 429 or bool(status and status >= 500):
            return "service_unavailable"
        if status is not None and 400 <= status < 500:
            return "validation"
        return "tool_error"
