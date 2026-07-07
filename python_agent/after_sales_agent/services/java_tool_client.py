from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any
from urllib import error, parse, request


class JavaToolError(RuntimeError):
    pass


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
            internal_token=os.getenv("AFTERSALES_AGENT_INTERNAL_TOKEN", ""),
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
        return headers

    def _send(self, req: request.Request) -> Any:
        try:
            with request.urlopen(req, timeout=self.config.timeout_seconds) as resp:
                raw = resp.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise JavaToolError(f"Java business API failed: HTTP {exc.code} {detail}") from exc
        except error.URLError as exc:
            raise JavaToolError(f"Java business API unavailable: {exc}") from exc

        try:
            body = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise JavaToolError(f"Java business API returned non-JSON: {raw[:200]}") from exc

        if isinstance(body, dict) and body.get("code") not in (None, 200):
            raise JavaToolError(str(body.get("message") or "Java business API rejected request"))
        return body.get("data") if isinstance(body, dict) and "data" in body else body
