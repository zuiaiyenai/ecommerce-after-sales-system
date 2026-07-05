from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any
from urllib import error, request


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class OpenAICompatibleConfig:
    base_url: str
    api_key: str
    model: str
    timeout_seconds: int = 60

    @classmethod
    def from_env(cls) -> "OpenAICompatibleConfig":
        return cls(
            base_url=os.getenv("QWEN_BASE_URL", "http://127.0.0.1:11434"),
            api_key=os.getenv("QWEN_API_KEY", "EMPTY"),
            model=os.getenv("QWEN_MODEL", "qwen2.5:1.5b"),
            timeout_seconds=int(os.getenv("QWEN_TIMEOUT_SECONDS", "60")),
        )


class OpenAICompatibleClient:
    def __init__(self, config: OpenAICompatibleConfig) -> None:
        self.config = config

    def chat_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 600,
    ) -> dict[str, Any]:
        if self._is_ollama_native():
            return self._chat_json_ollama(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=temperature,
            )

        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        raw = self._post(payload)
        try:
            data = json.loads(raw)
            content = data["choices"][0]["message"]["content"]
            return self._parse_json_content(content)
        except (KeyError, IndexError, json.JSONDecodeError, LLMError) as exc:
            raise LLMError(f"model output is not valid JSON: {raw}") from exc

    def _chat_json_ollama(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
    ) -> dict[str, Any]:
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "options": {"temperature": temperature},
        }
        raw = self._post(payload, path="/api/chat")
        try:
            data = json.loads(raw)
            content = data["message"]["content"]
            return self._parse_json_content(content)
        except (KeyError, json.JSONDecodeError, LLMError):
            try:
                data = json.loads(raw)
                content = str(data["message"]["content"]).strip()
                return {"assistant_reply": content}
            except (KeyError, json.JSONDecodeError) as exc:
                raise LLMError(f"ollama output is not valid JSON: {raw}") from exc

    @classmethod
    def _parse_json_content(cls, content: Any) -> dict[str, Any]:
        text = str(content or "").strip()
        for candidate in cls._json_candidates(text):
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
        raise LLMError(f"structured JSON not found in model output: {text[:600]}")

    @classmethod
    def _json_candidates(cls, text: str) -> list[str]:
        candidates: list[str] = []
        stripped = text.strip().lstrip("\ufeff")
        if stripped:
            candidates.append(cls._sanitize_json_text(stripped))

        fence_block = cls._extract_fenced_block(stripped)
        if fence_block:
            candidates.append(cls._sanitize_json_text(fence_block))

        extracted = cls._extract_first_json_object(stripped)
        if extracted:
            candidates.append(cls._sanitize_json_text(extracted))

        unique: list[str] = []
        for item in candidates:
            if item and item not in unique:
                unique.append(item)
        return unique

    @staticmethod
    def _sanitize_json_text(text: str) -> str:
        sanitized = text.strip().lstrip("\ufeff").strip(";")
        if sanitized.startswith("```") and sanitized.endswith("```"):
            sanitized = sanitized[3:-3].strip()
        if "\n" in sanitized:
            first_line, rest = sanitized.split("\n", 1)
            if first_line.strip().lower() in {"json", "javascript", "js"}:
                sanitized = rest.strip()
        return sanitized

    @staticmethod
    def _extract_fenced_block(text: str) -> str | None:
        start = text.find("```")
        if start < 0:
            return None
        end = text.find("```", start + 3)
        if end < 0:
            return None
        return text[start + 3 : end].strip()

    @staticmethod
    def _extract_first_json_object(text: str) -> str | None:
        decoder = json.JSONDecoder()
        positions = sorted(index for index in (text.find("{"), text.find("[")) if index >= 0)
        for start in positions:
            try:
                _, end = decoder.raw_decode(text[start:])
                return text[start : start + end]
            except json.JSONDecodeError:
                continue
        return None

    def _post(self, payload: dict[str, Any], path: str = "/v1/chat/completions") -> str:
        body = json.dumps(payload).encode("utf-8")
        endpoint = self.config.base_url.rstrip("/") + path
        req = request.Request(
            endpoint,
            data=body,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json; charset=utf-8",
                "Authorization": f"Bearer {self.config.api_key}",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.config.timeout_seconds) as resp:
                return resp.read().decode("utf-8")
        except error.URLError as exc:
            raise LLMError(f"cannot connect to model service: {exc}") from exc
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise LLMError(f"model service error: HTTP {exc.code} {detail}") from exc

    def _is_ollama_native(self) -> bool:
        return self.config.base_url.rstrip("/").endswith(":11434")
