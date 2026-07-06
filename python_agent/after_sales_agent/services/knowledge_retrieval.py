from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any
from urllib import error, request

from ..infra.trace import TraceRecorder


def _derive_default_base_url() -> str:
    policy_base_url = os.getenv("AFTERSALES_POLICY_BASE_URL", "http://127.0.0.1:8080/api/agent/policies").strip().rstrip("/")
    if policy_base_url.endswith("/policies"):
        return policy_base_url[: -len("/policies")] + "/knowledge"
    return "http://127.0.0.1:8080/api/agent/knowledge"


@dataclass(frozen=True)
class KnowledgeRetrievalConfig:
    base_url: str
    timeout_seconds: int = 4
    top_k: int = 4

    @classmethod
    def from_env(cls) -> "KnowledgeRetrievalConfig":
        return cls(
            base_url=os.getenv("AFTERSALES_KNOWLEDGE_BASE_URL", _derive_default_base_url()),
            timeout_seconds=int(os.getenv("AFTERSALES_KNOWLEDGE_TIMEOUT_SECONDS", "4")),
            top_k=int(os.getenv("AFTERSALES_KNOWLEDGE_TOP_K", "4")),
        )


class KnowledgeRetrievalClient:
    def __init__(self, config: KnowledgeRetrievalConfig | None = None) -> None:
        self.config = config or KnowledgeRetrievalConfig.from_env()
        self.trace_recorder: TraceRecorder | None = None

    def bind_trace(self, trace_recorder: TraceRecorder | None) -> None:
        self.trace_recorder = trace_recorder

    def retrieve(
        self,
        *,
        query: str,
        merchant_code: str | None = None,
        product_category: str | None = None,
        scene: str | None = None,
        intent: str | None = None,
        top_k: int | None = None,
        sources: list[str] | None = None,
    ) -> dict[str, Any]:
        normalized_query = str(query or "").strip()
        if not normalized_query or not self.config.base_url.strip():
            return {
                "mode": "skipped",
                "query": normalized_query,
                "hits": [],
            }
        effective_top_k = max(1, min(top_k or self.config.top_k, 8))
        if self.trace_recorder is not None:
            with self.trace_recorder.step(
                "knowledge_retrieve",
                top_k=effective_top_k,
                scene=scene or "",
                intent=intent or "",
            ):
                return self._retrieve_core(
                    query=normalized_query,
                    merchant_code=merchant_code,
                    product_category=product_category,
                    scene=scene,
                    intent=intent,
                    top_k=effective_top_k,
                    sources=sources,
                )
        return self._retrieve_core(
            query=normalized_query,
            merchant_code=merchant_code,
            product_category=product_category,
            scene=scene,
            intent=intent,
            top_k=effective_top_k,
            sources=sources,
        )

    def _retrieve_core(
        self,
        *,
        query: str,
        merchant_code: str | None,
        product_category: str | None,
        scene: str | None,
        intent: str | None,
        top_k: int,
        sources: list[str] | None,
    ) -> dict[str, Any]:
        payload = {
            "query": query,
            "merchantCode": merchant_code,
            "productCategory": product_category,
            "scene": scene,
            "intent": intent,
            "topK": top_k,
            "sources": sources or [],
        }
        try:
            req = request.Request(
                self.config.base_url.rstrip("/") + "/retrieve",
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json; charset=utf-8"},
                method="POST",
            )
            with request.urlopen(req, timeout=self.config.timeout_seconds) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
        except (error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            return {
                "mode": "unavailable",
                "query": query,
                "hits": [],
                "error": str(exc),
            }

        data = raw.get("data") if isinstance(raw, dict) and "data" in raw else raw
        if not isinstance(data, dict):
            return {
                "mode": "invalid_response",
                "query": query,
                "hits": [],
            }
        return {
            "mode": "retrieved",
            "query": query,
            "retrieval_mode": data.get("retrieval_mode"),
            "total_hits": data.get("total_hits"),
            "hits": list(data.get("hits") or []),
            "trace": data.get("trace") if isinstance(data.get("trace"), dict) else {},
        }
