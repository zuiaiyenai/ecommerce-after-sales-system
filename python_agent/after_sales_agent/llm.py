from __future__ import annotations

from dataclasses import dataclass
import base64
import json
import os
from typing import Any
from urllib import error, request

from .trace import TraceRecorder


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
        self.trace_recorder: TraceRecorder | None = None

    def bind_trace(self, trace_recorder: TraceRecorder | None) -> None:
        self.trace_recorder = trace_recorder

    def chat_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 600,
    ) -> dict[str, Any]:
        if self.trace_recorder is not None:
            with self.trace_recorder.step(
                "text_model_call",
                model=self.config.model,
                mode="text",
                provider="ollama" if self._is_ollama_native() else "openai_compatible",
                max_tokens=max_tokens,
            ):
                return self._chat_json_core(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
        return self._chat_json_core(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def _chat_json_core(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
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
            return json.loads(content)
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise LLMError(f"模型返回内容无法解析为 JSON：{raw}") from exc

    def chat_multimodal_json(
        self,
        *,
        system_prompt: str,
        user_text: str,
        image_urls: list[str],
        temperature: float = 0.1,
        max_tokens: int = 180,
    ) -> dict[str, Any]:
        if self.trace_recorder is not None:
            with self.trace_recorder.step(
                "vision_model_call",
                model=self.config.model,
                mode="vision",
                provider="ollama" if self._is_ollama_native() else "openai_compatible",
                image_count=len(image_urls),
                max_tokens=max_tokens,
            ):
                return self._chat_multimodal_json_core(
                    system_prompt=system_prompt,
                    user_text=user_text,
                    image_urls=image_urls,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
        return self._chat_multimodal_json_core(
            system_prompt=system_prompt,
            user_text=user_text,
            image_urls=image_urls,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def _chat_multimodal_json_core(
        self,
        *,
        system_prompt: str,
        user_text: str,
        image_urls: list[str],
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        if self._is_ollama_native():
            return self._chat_multimodal_json_ollama(
                system_prompt=system_prompt,
                user_text=user_text,
                image_urls=image_urls,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
        for image_url in image_urls:
            content.append({"type": "image_url", "image_url": {"url": image_url}})
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        raw = self._post(payload)
        try:
            data = json.loads(raw)
            content_text = data["choices"][0]["message"]["content"]
            return json.loads(content_text)
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise LLMError(f"视觉模型返回内容无法解析为 JSON：{raw}") from exc

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
            return json.loads(content)
        except (KeyError, json.JSONDecodeError):
            try:
                data = json.loads(raw)
                content = str(data["message"]["content"]).strip()
                return {"assistant_reply": content}
            except (KeyError, json.JSONDecodeError) as exc:
                raise LLMError(f"Ollama 返回内容无法解析为 JSON：{raw}") from exc

    def _chat_multimodal_json_ollama(
        self,
        *,
        system_prompt: str,
        user_text: str,
        image_urls: list[str],
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        images = [self._extract_base64_image(image_url) for image_url in image_urls]
        if not images:
            raise LLMError("未检测到可用图片数据。")

        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": user_text,
                    "images": images,
                },
            ],
            "stream": False,
            "format": "json",
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        raw = self._post(payload, path="/api/chat")
        try:
            data = json.loads(raw)
            content = data["message"]["content"]
            return json.loads(content)
        except (KeyError, json.JSONDecodeError) as exc:
            raise LLMError(f"Ollama 视觉返回内容无法解析为 JSON：{raw}") from exc

    @staticmethod
    def _extract_base64_image(image_url: str) -> str:
        if image_url.startswith("data:"):
            parts = image_url.split(",", 1)
            if len(parts) != 2 or not parts[1]:
                raise LLMError("图片 data URL 格式无效。")
            return parts[1]
        try:
            return base64.b64encode(image_url.encode("utf-8")).decode("utf-8")
        except Exception as exc:  # pragma: no cover
            raise LLMError(f"图片数据转换失败：{exc}") from exc

    def _post(self, payload: dict[str, Any], path: str = "/v1/chat/completions") -> str:
        body = json.dumps(payload).encode("utf-8")
        endpoint = self.config.base_url.rstrip("/") + path
        req = request.Request(
            endpoint,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.api_key}",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.config.timeout_seconds) as resp:
                return resp.read().decode("utf-8")
        except error.URLError as exc:
            raise LLMError(f"无法连接到模型服务：{exc}") from exc
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise LLMError(f"模型服务返回错误：HTTP {exc.code} {detail}") from exc

    def _is_ollama_native(self) -> bool:
        return self.config.base_url.rstrip("/").endswith(":11434")
