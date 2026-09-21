from __future__ import annotations

import io
import json
from types import SimpleNamespace
import urllib.error
from unittest.mock import patch

import pytest

from after_sales_agent.infrastructure.embedding_service import EmbeddingService


class _Response:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self._body


def _config(**overrides):
    values = {
        "embedding_api_key": "test-key",
        "embedding_provider": "dashscope",
        "embedding_base_url": "https://embedding.test/api",
        "embedding_model": "text-embedding-v3",
        "dimensions": 3,
        "embedding_timeout_seconds": 5,
        "embedding_max_retries": 1,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_dashscope_payload_and_response_contract() -> None:
    captured = {}

    def urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["authorization"] = request.get_header("Authorization")
        captured["timeout"] = timeout
        return _Response({"output": {"embeddings": [{"embedding": [0.1, 0.2, 0.3]}]}})

    with patch("urllib.request.urlopen", side_effect=urlopen):
        vectors = EmbeddingService(_config()).embed_many(["退款规则"])

    assert vectors == [[0.1, 0.2, 0.3]]
    assert captured == {
        "payload": {
            "model": "text-embedding-v3",
            "input": {"texts": ["退款规则"]},
            "parameters": {"dimension": 3, "output_type": "dense"},
        },
        "authorization": "Bearer test-key",
        "timeout": 5,
    }


def test_openai_compatible_contract_appends_endpoint() -> None:
    service = EmbeddingService(
        _config(
            embedding_provider="openai_compatible",
            embedding_base_url="https://embedding.test/v1",
        )
    )

    assert service._embedding_url() == "https://embedding.test/v1/embeddings"
    assert service._embedding_payload(["a"]) == {
        "model": "text-embedding-v3",
        "input": ["a"],
    }
    assert service._parse_embedding_response(
        {"data": [{"embedding": [0.1, 0.2, 0.3]}]}
    ) == [[0.1, 0.2, 0.3]]


def test_http_provider_error_is_not_swallowed() -> None:
    error = urllib.error.HTTPError(
        "https://embedding.test/api",
        400,
        "Bad Request",
        {},
        io.BytesIO(b'{"message":"invalid payload"}'),
    )

    with patch("urllib.request.urlopen", side_effect=error):
        with pytest.raises(RuntimeError, match="HTTP 400.*invalid payload"):
            EmbeddingService(_config()).get_embedding("退款规则")


def test_embedding_dimension_is_validated() -> None:
    with patch(
        "urllib.request.urlopen",
        return_value=_Response({"output": {"embeddings": [{"embedding": [0.1]}]}}),
    ):
        with pytest.raises(RuntimeError, match="dimension mismatch"):
            EmbeddingService(_config()).get_embedding("退款规则")
