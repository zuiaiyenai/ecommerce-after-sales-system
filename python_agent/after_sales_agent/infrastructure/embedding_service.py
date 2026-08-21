"""Embedding provider transport shared by retrieval and ingestion."""
from __future__ import annotations

import json
import socket
import time
from typing import Any
import urllib.error
import urllib.request


class EmbeddingService:
    """Generate validated embeddings using the configured provider contract."""

    def __init__(self, config: Any):
        self._config = config

    def get_embedding(self, text: str) -> list[float]:
        return self.embed_many([text])[0]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        if not self._config.embedding_api_key:
            raise RuntimeError(
                "EMBEDDING_API_KEY or DASHSCOPE_API_KEY is required for embedding service"
            )
        normalized_texts = [str(text or "").strip() for text in texts]
        if not normalized_texts:
            return []
        if any(not text for text in normalized_texts):
            raise RuntimeError("embedding input contains empty text")

        body = json.dumps(
            self._embedding_payload(normalized_texts),
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            self._embedding_url(),
            data=body,
            headers={
                "Authorization": f"Bearer {self._config.embedding_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        response_body = self._post_embedding(request)
        try:
            response_data = json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("embedding response is not valid JSON") from exc

        vectors = self._parse_embedding_response(response_data)
        if len(vectors) != len(normalized_texts):
            raise RuntimeError(
                f"embedding count mismatch: expected {len(normalized_texts)}, got {len(vectors)}"
            )
        for vector in vectors:
            if len(vector) != self._config.dimensions:
                raise RuntimeError(
                    "embedding dimension mismatch: "
                    f"expected {self._config.dimensions}, got {len(vector)}"
                )
        return vectors

    def _embedding_url(self) -> str:
        base_url = str(self._config.embedding_base_url or "").rstrip("/")
        if self._config.embedding_provider == "openai_compatible" and not base_url.endswith(
            "/embeddings"
        ):
            return f"{base_url}/embeddings"
        if base_url:
            return base_url
        raise RuntimeError("EMBEDDING_BASE_URL is required")

    def _embedding_payload(self, texts: list[str]) -> dict[str, Any]:
        if self._config.embedding_provider == "openai_compatible":
            # OpenAI-compatible format: {"model": "...", "input": ["text1", "text2"]}
            # Note: dimensions parameter is not supported by all providers (e.g., SiliconFlow)
            return {
                "model": self._config.embedding_model,
                "input": texts,
            }
        return {
            "model": self._config.embedding_model,
            "input": {"texts": texts},
            "parameters": {
                "dimension": self._config.dimensions,
                "output_type": "dense",
            },
        }

    def _parse_embedding_response(self, data: dict[str, Any]) -> list[list[float]]:
        if self._config.embedding_provider == "openai_compatible":
            items = data.get("data") or []
            if not items or any("embedding" not in item for item in items):
                raise RuntimeError("embedding response missing data[].embedding")
            return [[float(value) for value in item["embedding"]] for item in items]

        output = data.get("output") or {}
        embeddings = output.get("embeddings") or []
        if not embeddings or any("embedding" not in item for item in embeddings):
            raise RuntimeError("embedding response missing output.embeddings[].embedding")
        return [[float(value) for value in item["embedding"]] for item in embeddings]

    def _post_embedding(self, request: urllib.request.Request) -> str:
        last_error: Exception | None = None
        for attempt in range(1, self._config.embedding_max_retries + 1):
            try:
                with urllib.request.urlopen(
                    request,
                    timeout=self._config.embedding_timeout_seconds,
                ) as response:
                    return response.read().decode("utf-8")
            except urllib.error.HTTPError as exc:
                error_body = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(
                    f"embedding request failed with HTTP {exc.code}: {error_body}"
                ) from exc
            except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
                last_error = exc
                if attempt >= self._config.embedding_max_retries:
                    break
                time.sleep(min(2 ** (attempt - 1), 5))

        raise RuntimeError(
            "embedding request timed out or failed after "
            f"{self._config.embedding_max_retries} attempts; "
            f"url={self._embedding_url()}, "
            f"timeout={self._config.embedding_timeout_seconds}s, "
            f"last_error={last_error}"
        )


def embedding_error_info(exc: Exception) -> dict[str, Any]:
    """Extract a stable failure category without discarding the provider error."""
    message = str(exc)
    lowered = message.lower()
    info = {
        "error": exc.__class__.__name__,
        "message": message,
        "type": "embedding_error",
    }
    if "10013" in message or "permission" in lowered or "访问套接字" in message:
        info["type"] = "network_blocked"
        info["hint"] = "Outbound connection to embedding service is blocked by local OS/network policy."
    elif "timed out" in lowered or "timeout" in lowered:
        info["type"] = "network_timeout"
        info["hint"] = "Embedding service request timed out."
    elif "name or service not known" in lowered or "nodename nor servname provided" in lowered:
        info["type"] = "dns_error"
        info["hint"] = "Embedding host DNS resolution failed."
    return info
