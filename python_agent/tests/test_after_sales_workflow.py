from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from after_sales_agent.application.after_sales_workflow import LangGraphAfterSalesAgent
from after_sales_agent.application.function_calling import FunctionCallingProtocolError
from after_sales_agent.application.rag_query_rewrite import (
    RagQueryCandidate,
    RagRewriteDecision,
    RagRewriteModelError,
)
from after_sales_agent.application.tool_registry import ToolResult
from after_sales_agent.api.http_server import build_attachments
from after_sales_agent.providers.resilient_llm_runtime import LLMError, LLMResponseParseError

class FakeLlm:
    def __init__(self) -> None:
        self.calls = 0

    def chat_json(self, **_: object) -> dict[str, object]:
        self.calls += 1
        return {
            "action": "human_handoff",
            "tool_name": None,
            "tool_arguments": {},
            "assistant_reply": "已为您转接人工客服，请稍等。",
            "need_human": True,
            "evidence_needed": [],
        }

    def chat(self, messages: list[dict[str, object]], **_: object) -> dict[str, object]:
        self.calls += 1
        return native_response(
            "call-default-handoff",
            "handoff_to_human",
            {"assistant_reply": "已为您转接人工客服，请稍等。"},
        )


def native_response(call_id: str, name: str, arguments: dict[str, object]) -> dict[str, object]:
    return {
        "choices": [{"message": {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": call_id,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(arguments, ensure_ascii=False),
                },
            }],
        }}],
    }


def ollama_response(name: str, arguments: dict[str, object]) -> dict[str, object]:
    return {
        "model": "qwen3:8b",
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": name, "arguments": arguments}}],
        },
        "done": True,
    }


class RecordingNativeLlm:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, object]] = []

    def chat(self, messages: list[dict[str, object]], **kwargs: object) -> dict[str, object]:
        self.requests.append({"messages": messages, **kwargs})
        if not self.responses:
            raise AssertionError("unexpected native chat request")
        return self.responses.pop(0)


class SwitchingDecisionLlm:
    def __init__(self, native_responses: list[object], legacy_responses: list[object]) -> None:
        self.native_responses = list(native_responses)
        self.legacy_responses = list(legacy_responses)
        self.native_calls = 0
        self.legacy_calls = 0
        self.legacy_requests: list[dict[str, object]] = []

    def chat(self, _messages: list[dict[str, object]], **_: object) -> dict[str, object]:
        self.native_calls += 1
        response = self.native_responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response  # type: ignore[return-value]

    def chat_json(self, **kwargs: object) -> dict[str, object]:
        self.legacy_calls += 1
        self.legacy_requests.append(kwargs)
        response = self.legacy_responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response  # type: ignore[return-value]


class HandoffPathRecordingAgent(LangGraphAfterSalesAgent):
    def __init__(self, **kwargs: object) -> None:
        self.tool_call_node_calls = 0
        self.observe_node_calls = 0
        self.handoff_node_calls = 0
        self.handoff_input: dict[str, object] = {}
        self.handoff_output: dict[str, object] = {}
        super().__init__(**kwargs)

    def tool_call(self, state: dict[str, object]) -> dict[str, object]:
        self.tool_call_node_calls += 1
        return super().tool_call(state)  # type: ignore[arg-type, return-value]

    def observe_tool_result(self, state: dict[str, object]) -> dict[str, object]:
        self.observe_node_calls += 1
        return super().observe_tool_result(state)  # type: ignore[arg-type, return-value]

    def human_handoff(self, state: dict[str, object]) -> dict[str, object]:
        self.handoff_node_calls += 1
        self.handoff_input = dict(state)
        result = super().human_handoff(state)  # type: ignore[arg-type]
        self.handoff_output = {
            "session_mode": result.get("session_mode"),
            "need_human": result.get("need_human"),
            "handoff_succeeded": result.get("handoff_succeeded"),
            "last_observation": dict(result.get("last_observation") or {}),
            "handoff_trace": dict((result.get("tool_results") or [])[-1]),
            "assistant_reply": result.get("assistant_reply"),
        }
        return result  # type: ignore[return-value]


class FakeTools:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def tool_specs(self) -> list[dict[str, object]]:
        return [
            {
                "name": "handoff_to_human",
                "description": "Move to human service.",
                "input_schema": {
                    "type": "object",
                    "required": [],
                    "properties": {"assistant_reply": {"type": "string"}},
                    "additionalProperties": False,
                },
            }
        ]

    def registry(self) -> dict[str, object]:
        return {"handoff_to_human": object()}

    def call(self, name: str, arguments: dict[str, object]) -> ToolResult:
        self.calls.append(name)
        if name == "search_user_orders":
            return ToolResult(
                ok=True,
                name=name,
                data=[
                    {
                        "order_no": "ORD1783516556124",
                        "product_name": "蛋白粉(巧克力味)",
                        "product_category": "食品",
                        "merchant_code": "MERCHANT_DEMO",
                        "existing_ticket_no": "AS1783516664614",
                        "after_sales_status": "PENDING_REVIEW",
                    }
                ],
            )
        if name == "get_after_sales_ticket":
            return ToolResult(ok=True, name=name, data={
                "ticket_id": arguments.get("ticket_id"),
                "ticket_no": "AS1783516664614",
                "order_no": "ORD1783516556124",
                "order_id": "ORD1783516556124",
                "product_name": "蛋白粉(巧克力味)",
                "product_category": "食品",
                "merchant_code": "MERCHANT_DEMO",
                "create_time": "2026-07-20T09:00:00+08:00",
                "status": "PENDING_REVIEW",
            })
        if name == "handoff_to_human":
            return ToolResult(ok=True, name=name, data={"session_mode": "HUMAN", "status": "WAITING"})
        if name == "append_chat_message":
            return ToolResult(ok=True, name=name, data={"session_id": 123})
        return ToolResult(ok=False, name=name, error=f"unexpected tool call: {name}")


class NativeWorkflowTools:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.arguments: list[dict[str, object]] = []

    def registry(self) -> dict[str, object]:
        return {name: object() for name in (
            "lookup", "fail_lookup", "search_user_orders", "submit_ai_review",
            "handoff_to_human", "append_chat_message", "nested_lookup",
        )}

    def tool_specs(self) -> list[dict[str, object]]:
        def spec(name: str, properties: dict[str, object] | None = None, required: list[str] | None = None) -> dict[str, object]:
            return {
                "name": name,
                "description": name,
                "input_schema": {
                    "type": "object",
                    "required": required or [],
                    "properties": properties or {},
                    "additionalProperties": False,
                },
            }
        return [
            spec("lookup"),
            spec("fail_lookup"),
            spec("search_user_orders", {"keyword": {"type": "string"}}, ["keyword"]),
            spec("submit_ai_review", {"verdict": {"type": "string"}}, ["verdict"]),
            spec("handoff_to_human", {"assistant_reply": {"type": "string"}}),
            spec("append_chat_message", {"content": {"type": "string"}}, ["content"]),
            spec("nested_lookup", {
                "filter": {
                    "type": "object",
                    "properties": {"status": {"type": "string"}},
                    "required": ["status"],
                    "additionalProperties": False,
                },
            }, ["filter"]),
        ]

    def call(self, name: str, arguments: dict[str, object]) -> ToolResult:
        self.calls.append(name)
        self.arguments.append(dict(arguments))
        if name == "fail_lookup":
            return ToolResult(
                ok=False, name=name, error="upstream failed: raw-secret-data",
                error_code="UPSTREAM", error_category="tool_error",
            )
        if name == "handoff_to_human":
            return ToolResult(ok=True, name=name, data={"session_mode": "HUMAN", "status": "WAITING"})
        if name == "append_chat_message":
            return ToolResult(ok=True, name=name, data={"session_id": "native-session"})
        if name == "submit_ai_review":
            return ToolResult(ok=True, name=name, data={"ticket_no": "AS-NATIVE", "verdict": arguments.get("verdict")})
        return ToolResult(ok=True, name=name, data={"raw_secret": "do-not-send-to-model"})


class NativeHandoffFailureTools(NativeWorkflowTools):
    def call(self, name: str, arguments: dict[str, object]) -> ToolResult:
        if name == "handoff_to_human":
            self.calls.append(name)
            self.arguments.append(dict(arguments))
            return ToolResult(
                ok=False,
                name=name,
                error="handoff unavailable",
                error_code="SERVICE_UNAVAILABLE",
                error_category="service_unavailable",
                retryable=True,
            )
        return super().call(name, arguments)


class FakeHandoffSessionTools(FakeTools):
    def __init__(self) -> None:
        super().__init__()
        self.append_arguments: list[dict[str, object]] = []

    def call(self, name: str, arguments: dict[str, object]) -> ToolResult:
        self.calls.append(name)
        if name == "handoff_to_human":
            return ToolResult(ok=True, name=name, data={
                "sessionId": "9001",
                "mode": "HUMAN",
                "status": "WAITING",
            })
        if name == "append_chat_message":
            self.append_arguments.append(dict(arguments))
            return ToolResult(ok=True, name=name, data={"session_id": arguments.get("session_id")})
        return super().call(name, arguments)


class FakeUnconfirmedHandoffTools(FakeTools):
    def call(self, name: str, arguments: dict[str, object]) -> ToolResult:
        self.calls.append(name)
        if name == "handoff_to_human":
            return ToolResult(ok=True, name=name, data={
                "session_id": "9002",
                "mode": "AI",
                "status": "ACTIVE",
            })
        return super().call(name, arguments)


class FakeUnverifiableImageTools:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def tool_specs(self) -> list[dict[str, object]]:
        return []

    def call(self, name: str, arguments: dict[str, object]) -> ToolResult:
        self.calls.append(name)
        if name == "search_user_orders":
            return ToolResult(
                ok=True,
                name=name,
                data=[
                    {
                        "order_no": "ORD1783562416783",
                        "product_name": "蓝牙降噪耳机",
                        "product_category": "数码",
                        "merchant_code": "MERCHANT_DEMO",
                    }
                ],
            )
        if name == "review_images":
            return ToolResult(
                ok=True,
                name=name,
                data={
                    "success": True,
                    "all_clear": True,
                    "has_damage_area": False,
                    "has_outer_package": False,
                    "has_logistics_label": False,
                    "missing_visual_evidence": ["商品照片"],
                    "summary": "图片中未见可自动核验的客观异常",
                },
            )
        if name == "retrieve_knowledge":
            return ToolResult(ok=True, name=name, data={"hits": [], "mode": "pgvector"})
        if name == "get_after_sales_ticket":
            return ToolResult(ok=True, name=name, data={
                "ticket_id": arguments.get("ticket_id"),
                "ticket_no": "AS1783562492249",
                "order_no": "ORD1783562416783",
                "order_id": "ORD1783562416783",
                "product_name": "蓝牙降噪耳机",
                "product_category": "数码",
                "merchant_code": "MERCHANT_DEMO",
                "create_time": "2026-07-20T09:00:00+08:00",
                "status": "PENDING_REVIEW",
            })
        if name == "submit_ai_review":
            return ToolResult(
                ok=True,
                name=name,
                data={
                    "ticket_no": "AS1783562492249",
                    "ticket_id": arguments.get("ticket_id"),
                    "verdict": arguments.get("verdict"),
                    "status": "PENDING_REVIEW",
                },
            )
        if name == "handoff_to_human":
            return ToolResult(ok=True, name=name, data={"session_mode": "HUMAN", "status": "WAITING"})
        if name == "append_chat_message":
            return ToolResult(ok=True, name=name, data={"session_id": 456})
        return ToolResult(ok=False, name=name, error=f"unexpected tool call: {name}")


class FakeExistingTicketImageTools:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def tool_specs(self) -> list[dict[str, object]]:
        return FakeTools.tool_specs(self)

    def registry(self) -> dict[str, object]:
        return {"handoff_to_human": object()}

    def call(self, name: str, arguments: dict[str, object]) -> ToolResult:
        self.calls.append(name)
        if name == "search_user_orders":
            return ToolResult(
                ok=True,
                name=name,
                data=[
                    {
                        "order_no": "ORD1783564088864",
                        "product_name": "蓝牙降噪耳机",
                        "product_category": "数码",
                        "merchant_code": "MERCHANT_DEMO",
                        "existing_ticket_no": "AS1783564161927",
                        "after_sales_status": "PENDING_REVIEW",
                    }
                ],
            )
        if name == "review_images":
            return ToolResult(
                ok=True,
                name=name,
                data={
                    "success": True,
                    "all_clear": True,
                    "has_damage_area": False,
                    "has_outer_package": False,
                    "has_logistics_label": False,
                    "missing_visual_evidence": ["商品照片"],
                    "summary": "图片中未见可自动核验的客观异常",
                },
            )
        if name == "retrieve_knowledge":
            return ToolResult(ok=True, name=name, data={"hits": [], "mode": "pgvector"})
        if name == "get_after_sales_ticket":
            return ToolResult(ok=True, name=name, data={
                "ticket_id": arguments.get("ticket_id"),
                "ticket_no": "AS1783564161927",
                "order_no": "ORD1783564088864",
                "order_id": "ORD1783564088864",
                "product_name": "蓝牙降噪耳机",
                "product_category": "数码",
                "merchant_code": "MERCHANT_DEMO",
                "create_time": "2026-07-20T09:00:00+08:00",
                "status": "PENDING_REVIEW",
            })
        if name == "submit_ai_review":
            return ToolResult(ok=True, name=name, data={
                "ticket_no": "AS1783564161927",
                "ticket_id": arguments.get("ticket_id"),
                "verdict": arguments.get("verdict"),
                "status": "PENDING_REVIEW",
            })
        if name == "handoff_to_human":
            return ToolResult(ok=True, name=name, data={"session_mode": "HUMAN", "status": "WAITING"})
        if name == "append_chat_message":
            return ToolResult(ok=True, name=name, data={"session_id": 789})
        return ToolResult(ok=False, name=name, error=f"unexpected tool call: {name}")


class FakeDamageImageTools:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.create_arguments: dict[str, object] | None = None

    def tool_specs(self) -> list[dict[str, object]]:
        return FakeTools.tool_specs(self)

    def registry(self) -> dict[str, object]:
        return {"handoff_to_human": object()}

    def call(self, name: str, arguments: dict[str, object]) -> ToolResult:
        self.calls.append(name)
        if name == "search_user_orders":
            return ToolResult(
                ok=True,
                name=name,
                data=[
                    {
                        "order_no": "ORD1783595519525",
                        "product_name": "蓝牙降噪耳机",
                        "product_category": "数码",
                        "merchant_code": "MERCHANT_DEMO",
                    }
                ],
            )
        if name == "review_images":
            return ToolResult(
                ok=True,
                name=name,
                data={
                    "success": True,
                    "all_clear": False,
                    "has_damage_area": True,
                    "has_outer_package": False,
                    "has_logistics_label": False,
                    "items": [{"confidence": 0.95, "contains_damage_area": True, "image_type": "商品照片"}],
                    "missing_visual_evidence": ["外包装照片", "物流面单照片"],
                    "summary": "图片可见耳机外壳破裂",
                },
            )
        if name == "retrieve_knowledge":
            return ToolResult(
                ok=True,
                name=name,
                data={
                    "mode": "hybrid_reranked",
                    "filter_level": "strict",
                    "reranker_succeeded": True,
                    "threshold": 0.75,
                    "no_answer": False,
                    "trusted_policy_eligible": True,
                    "relaxation_level": "strict",
                    "hits": [
                        {
                            "source_type": "after_sales_policy",
                            "source_code": "POLICY-DIGITAL-DAMAGE",
                            "title": "数码商品破损售后规则",
                            "snippet": "商品破损需要提供商品问题照片和问题描述，图片清晰可见破损即可进入审核。",
                            "score": 0.82,
                            "rerank_score": 0.91,
                            "rerank_score": 0.82,
                            "threshold": 0.75,
                            "trusted_policy_eligible": True,
                            "relaxation_level": "strict",
                            "citations": [{
                                "chunk_id": "POLICY-DIGITAL-DAMAGE-1",
                                "source_code": "POLICY-DIGITAL-DAMAGE",
                            }],
                            "metadata": {
                                "merchant_code": "MERCHANT_DEMO",
                                "source_type": "after_sales_policy",
                                "policy_version": "v2",
                                "valid_from": "2026-07-01T00:00:00+08:00",
                                "valid_to": "2026-08-01T00:00:00+08:00",
                                "default_evidence": ["商品问题照片", "问题描述"],
                            },
                        }
                    ],
                },
            )
        if name == "get_after_sales_ticket":
            return ToolResult(ok=True, name=name, data={
                "ticket_id": arguments.get("ticket_id"),
                "ticket_no": "AS1783595588024",
                "order_no": "ORD1783595519525",
                "order_id": "ORD1783595519525",
                "product_name": "蓝牙降噪耳机",
                "product_category": "数码",
                "merchant_code": "MERCHANT_DEMO",
                "policy_version": "v2",
                "create_time": "2026-07-20T09:00:00+08:00",
                "status": "PENDING_REVIEW",
            })
        if name == "submit_ai_review":
            self.create_arguments = arguments
            return ToolResult(
                ok=True,
                name=name,
                data={
                    "ticket_no": "AS1783595588024",
                    "ticket_id": arguments.get("ticket_id"),
                    "verdict": arguments.get("verdict"),
                    "status": "PROCESSING" if arguments.get("verdict") == "APPROVE" else "PENDING_REVIEW",
                },
            )
        if name == "append_chat_message":
            return ToolResult(ok=True, name=name, data={"session_id": 999})
        return ToolResult(ok=False, name=name, error=f"unexpected tool call: {name}")


class FakeEvidenceScenarioTools(FakeDamageImageTools):
    def __init__(self, review: dict[str, object]) -> None:
        super().__init__()
        self.review = review

    def call(self, name: str, arguments: dict[str, object]) -> ToolResult:
        if name == "review_images":
            self.calls.append(name)
            return ToolResult(ok=True, name=name, data=self.review)
        if name == "handoff_to_human":
            self.calls.append(name)
            return ToolResult(ok=True, name=name, data={"session_mode": "HUMAN", "status": "WAITING"})
        return super().call(name, arguments)


class FakeKeywordOnlyPolicyTools(FakeDamageImageTools):
    def call(self, name: str, arguments: dict[str, object]) -> ToolResult:
        if name == "retrieve_knowledge":
            self.calls.append(name)
            return ToolResult(
                ok=True,
                name=name,
                data={
                    "mode": "pgvector",
                    "trusted_policy_eligible": True,
                    "relaxation_level": "strict",
                    "hits": [
                        {
                            "source_type": "faq",
                            "source_code": "FAQ-DENSE",
                            "dense_score": 0.95,
                            "trusted_policy_eligible": True,
                            "relaxation_level": "strict",
                            "metadata": {"merchant_code": "MERCHANT_DEMO"},
                        },
                        {
                            "source_type": "after_sales_policy",
                            "source_code": "POLICY-KEYWORD-ONLY",
                            "score": 2.6,
                            "keyword_score": 2.6,
                            "rrf_score": 0.03,
                            "retrieval_channels": ["keyword"],
                            "trusted_policy_eligible": True,
                            "relaxation_level": "strict",
                            "metadata": {"merchant_code": "MERCHANT_DEMO"},
                        },
                    ],
                    "trace": {"trusted_policy_eligible": True, "relaxation_level": "strict"},
                },
            )
        return super().call(name, arguments)


class LangGraphHumanHandoffTest(unittest.TestCase):
    def test_data_image_attachment_is_not_used_as_persistent_file_url(self) -> None:
        image_url = "data:image/jpeg;base64,abc123"

        resolved = LangGraphAfterSalesAgent._first_attachment_file_url({
            "attachments": [{"name": "damage.jpg", "kind": "图片", "source": image_url}],
        })

        self.assertIsNone(resolved)

    def test_explicit_human_request_with_existing_ticket_goes_to_handoff(self) -> None:
        tools = FakeTools()
        agent = LangGraphAfterSalesAgent(tools=tools, llm=FakeLlm())

        result = agent.handle(
            {
                "user_id": "1",
                "session_id": 123,
                "message": "请帮我转人工客服",
                "order_id": "ORD1783516556124",
            }
        )

        self.assertTrue(result["need_human"])
        self.assertEqual("HUMAN", result["session_mode"])
        self.assertIn("人工客服", result["assistant_reply"])
        self.assertIn("handoff_to_human", result["tool_trace"][-3]["tool"])
        self.assertNotIn("retrieve_knowledge", tools.calls)

    def test_uploaded_image_and_description_handoff_when_image_cannot_verify_claim(self) -> None:
        tools = FakeUnverifiableImageTools()
        agent = LangGraphAfterSalesAgent(tools=tools, llm=FakeLlm())

        result = agent.handle(
            {
                "user_id": "1",
                "session_id": 456,
                "ticket_id": "1783562492249",
                "review_request_id": "review-456",
                "client_context": {"source": "kafka"},
                "message": "耳机声音有问题,有时候听不清,而且还会带电流声",
                "order_id": "ORD1783562416783",
                "attachments": [{"name": "earphone.jpg", "kind": "图片", "source": "https://example.com/earphone.jpg"}],
            }
        )

        self.assertTrue(result["need_human"])
        self.assertEqual("HUMAN", result["session_mode"])
        self.assertIn("AS1783562492249", result["assistant_reply"])
        self.assertIn("人工复核", result["assistant_reply"])
        self.assertIn("review_images", tools.calls)
        self.assertNotIn("retrieve_knowledge", tools.calls)
        self.assertIn("submit_ai_review", tools.calls)
        self.assertIn("handoff_to_human", tools.calls)
        self.assertLess(tools.calls.index("submit_ai_review"), tools.calls.index("handoff_to_human"))

    def test_existing_ticket_with_uploaded_image_runs_visual_review_before_reply(self) -> None:
        tools = FakeExistingTicketImageTools()
        agent = LangGraphAfterSalesAgent(tools=tools, llm=FakeLlm())

        result = agent.handle(
            {
                "user_id": "1",
                "session_id": 789,
                "ticket_id": "1783564161927",
                "review_request_id": "review-789",
                "client_context": {"source": "kafka"},
                "message": "耳机声音有问题,经常听不清,而且偶尔还会有电流声",
                "order_id": "ORD1783564088864",
                "attachments": [{"name": "earphone.jpg", "kind": "图片", "source": "https://example.com/earphone.jpg"}],
            }
        )

        self.assertTrue(result["need_human"])
        self.assertEqual("HUMAN", result["session_mode"])
        self.assertIn("AS1783564161927", result["assistant_reply"])
        self.assertIn("人工复核", result["assistant_reply"])
        self.assertIn("review_images", tools.calls)
        self.assertNotIn("retrieve_knowledge", tools.calls)
        self.assertIn("handoff_to_human", tools.calls)
        self.assertIn("submit_ai_review", tools.calls)

    def test_functional_issue_with_image_goes_to_manual_review(self) -> None:
        review = {
            "success": True,
            "all_clear": True,
            "has_damage_area": False,
            "has_outer_package": False,
            "has_logistics_label": False,
            "missing_visual_evidence": ["功能故障视频"],
            "items": [{"confidence": 0.96, "contains_damage_area": False, "image_type": "商品照片"}],
            "summary": "图片只能看到手机电量，无法核验充电是否异常",
        }
        tools = FakeEvidenceScenarioTools(review)
        agent = LangGraphAfterSalesAgent(tools=tools, llm=FakeLlm())

        result = agent.handle({
            "user_id": "1",
            "session_id": 1003,
            "ticket_id": "1783595588024",
            "review_request_id": "review-phone-charge",
            "client_context": {"source": "kafka"},
            "message": "[图片]",
            "recent_history": [{"role": "user", "content": "手机充电有问题，经常充电半个多小时才充进去几个电"}],
            "order_id": "ORD1783595519525",
            "attachments": [{"name": "battery.jpg", "kind": "图片", "source": "https://example.com/battery.jpg"}],
        })

        self.assertTrue(result["need_human"])
        self.assertEqual("HUMAN", result["session_mode"])
        self.assertIsNotNone(tools.create_arguments)
        self.assertEqual("MANUAL_REVIEW_REQUIRED", tools.create_arguments["verdict"])
        self.assertTrue(tools.create_arguments["visual_uncertain"])
        self.assertFalse(tools.create_arguments["evidence_consistent"])
        self.assertIn("handoff_to_human", tools.calls)

    def test_existing_ticket_functional_issue_without_image_asks_for_problem_photo(self) -> None:
        tools = FakeExistingTicketImageTools()
        agent = LangGraphAfterSalesAgent(tools=tools, llm=FakeLlm())

        result = agent.handle({
            "user_id": "1",
            "session_id": 1004,
            "ticket_id": "1783564161927",
            "message": "手机充电有问题，经常半个小时才充进去几格电",
            "order_id": "ORD1783564088864",
            "attachments": [],
        })

        self.assertFalse(result["need_human"])
        self.assertEqual("AI", result["session_mode"])
        self.assertIn("商品问题图片", result["assistant_reply"])
        self.assertIn("商品问题照片", result["evidence_needed"])
        self.assertIn("get_after_sales_ticket", tools.calls)
        self.assertNotIn("retrieve_knowledge", tools.calls)
        self.assertNotIn("submit_ai_review", tools.calls)
        self.assertNotIn("handoff_to_human", tools.calls)

    def test_existing_ticket_visible_damage_without_image_asks_for_problem_photo(self) -> None:
        tools = FakeExistingTicketImageTools()
        agent = LangGraphAfterSalesAgent(tools=tools, llm=FakeLlm())

        result = agent.handle({
            "user_id": "1",
            "session_id": 1005,
            "ticket_id": "1783997235307",
            "message": "刚刚收到耳机还没有使用就发现耳机外壳破裂",
            "order_id": "ORD1783997203700",
            "attachments": [],
        })

        self.assertFalse(result["need_human"])
        self.assertEqual("AI", result["session_mode"])
        self.assertIn("商品问题图片", result["assistant_reply"])
        self.assertIn("商品问题照片", result["evidence_needed"])
        self.assertIn("get_after_sales_ticket", tools.calls)
        self.assertNotIn("retrieve_knowledge", tools.calls)
        self.assertNotIn("submit_ai_review", tools.calls)
        self.assertNotIn("handoff_to_human", tools.calls)

    def test_damage_image_and_description_satisfy_evidence_and_auto_approve(self) -> None:
        tools = FakeDamageImageTools()
        agent = LangGraphAfterSalesAgent(tools=tools, llm=FakeLlm())

        result = agent.handle(
            {
                "user_id": "1",
                "session_id": 999,
                "ticket_id": "1783595588024",
                "review_request_id": "review-999",
                "client_context": {"source": "kafka"},
                "message": "耳机刚刚打开,还没有使用,就发现外壳破裂",
                "order_id": "ORD1783595519525",
                "attachments": [{"name": "damage.jpg", "kind": "图片", "source": "https://example.com/damage.jpg"}],
            }
        )

        self.assertFalse(result["need_human"])
        self.assertEqual("AI", result["session_mode"])
        self.assertIn("处理中", result["assistant_reply"])
        self.assertIn("review_images", tools.calls)
        self.assertIn("retrieve_knowledge", tools.calls)
        self.assertIn("submit_ai_review", tools.calls)
        self.assertIsNotNone(tools.create_arguments)
        self.assertEqual("APPROVE", tools.create_arguments["verdict"])
        self.assertEqual([], tools.create_arguments["evidence_needed"])
        self.assertTrue(tools.create_arguments["evidence_consistent"])
        self.assertEqual(0.95, tools.create_arguments["visual_confidence"])
        self.assertEqual("strict", tools.create_arguments["filter_level"])
        self.assertTrue(tools.create_arguments["reranker_succeeded"])
        self.assertTrue(tools.create_arguments["trusted_policy_eligible"])
        self.assertEqual("v2", tools.create_arguments["policy_version"])

    def test_keyword_only_policy_hit_cannot_auto_authorize_when_dense_results_exist(self) -> None:
        tools = FakeKeywordOnlyPolicyTools()
        agent = LangGraphAfterSalesAgent(tools=tools, llm=FakeLlm())

        agent.handle(
            {
                "user_id": "1",
                "session_id": 999,
                "ticket_id": "1783595588024",
                "review_request_id": "review-keyword-only",
                "client_context": {"source": "kafka"},
                "message": "耳机刚刚打开就发现外壳破裂",
                "order_id": "ORD1783595519525",
                "attachments": [{"name": "damage.jpg", "kind": "图片", "source": "https://example.com/damage.jpg"}],
            }
        )

        self.assertIsNotNone(tools.create_arguments)
        self.assertEqual("MANUAL_REVIEW_REQUIRED", tools.create_arguments["verdict"])
        self.assertTrue(tools.create_arguments["policy_uncertain"])

    def test_consultation_without_ticket_does_not_submit_review(self) -> None:
        tools = FakeDamageImageTools()
        agent = LangGraphAfterSalesAgent(tools=tools, llm=FakeLlm())

        result = agent.handle(
            {
                "user_id": "1",
                "session_id": 1000,
                "message": "耳机坏了可以退货吗",
                "order_id": "ORD1783595519525",
            }
        )

        self.assertFalse(result["need_human"])
        self.assertNotIn("submit_ai_review", tools.calls)
        self.assertNotIn("create_after_sales_ticket", tools.calls)
        self.assertIn("申请售后", result["assistant_reply"])

    def test_visual_edge_cases_require_human_review(self) -> None:
        scenarios = {
            "claim_visual_mismatch": {
                "success": True, "all_clear": True, "has_damage_area": False,
                "missing_visual_evidence": ["破损照片"],
                "items": [{"confidence": 0.96, "contains_damage_area": False, "image_type": "商品照片"}],
            },
            "low_confidence": {
                "success": True, "all_clear": True, "has_damage_area": True,
                "missing_visual_evidence": [],
                "items": [{"confidence": 0.62, "contains_damage_area": True, "image_type": "商品照片"}],
            },
            "blurry_image": {
                "success": True, "all_clear": False, "has_damage_area": False,
                "missing_visual_evidence": ["清晰破损照片"],
                "items": [{"confidence": 0.4, "contains_damage_area": False, "image_type": "不确定"}],
            },
            "irrelevant_image": {
                "success": True, "all_clear": True, "has_damage_area": False,
                "missing_visual_evidence": ["商品破损照片"],
                "items": [{"confidence": 0.93, "contains_damage_area": False, "image_type": "不确定"}],
            },
        }
        for name, review in scenarios.items():
            with self.subTest(name=name):
                tools = FakeEvidenceScenarioTools(review)
                agent = LangGraphAfterSalesAgent(tools=tools, llm=FakeLlm())
                result = agent.handle({
                    "user_id": "1",
                    "session_id": 1001,
                    "ticket_id": "1783595588024",
                    "review_request_id": f"review-{name}",
                    "client_context": {"source": "kafka"},
                    "message": "耳机刚拆开就发现外壳破裂",
                    "order_id": "ORD1783595519525",
                    "attachments": [{"name": f"{name}.jpg", "kind": "图片", "source": f"https://example.com/{name}.jpg"}],
                })
                self.assertTrue(result["need_human"])
                self.assertEqual("HUMAN", result["session_mode"])
                self.assertEqual("MANUAL_REVIEW_REQUIRED", tools.create_arguments["verdict"])
                self.assertIn("handoff_to_human", tools.calls)


    def test_visual_confidence_prefers_damage_probability(self) -> None:
        review = {
            "items": [{"confidence": 0.98, "damage_confidence": 0.64}]
        }

        self.assertEqual(0.64, LangGraphAfterSalesAgent._visual_confidence(review))

    def test_visual_confidence_supports_legacy_review(self) -> None:
        review = {"items": [{"confidence": 0.88}]}

        self.assertEqual(0.88, LangGraphAfterSalesAgent._visual_confidence(review))

    def test_policy_retrieval_uses_business_context_as_strict_filters(self) -> None:
        agent = LangGraphAfterSalesAgent(tools=FakeTools(), llm=FakeLlm())
        action = agent._retrieve_policy_action(
            {
                "user_id": "1",
                "message": "耳机电流声，申请换货",
                "history_summary": {"policy_version": "2026-07-02-v3"},
            },
            {
                "product_name": "蓝牙降噪耳机",
                "product_category": "数码",
                "merchant_code": "MERCHANT_DEMO",
                "policy_version": "2026-07-02-v3",
                "after_sales_applied_at": "2026-07-20T09:00:00+08:00",
            },
        )

        arguments = action["tool_arguments"]
        self.assertEqual("MERCHANT_DEMO", arguments["merchant_code"])
        self.assertEqual("headphone", arguments["product_category"])
        self.assertEqual("quality_issue", arguments["scene"])
        self.assertEqual("exchange", arguments["intent"])
        self.assertEqual("after_sales_policy", arguments["source_type"])
        self.assertEqual("2026-07-02-v3", arguments["policy_version"])
        self.assertEqual("2026-07-20T09:00:00+08:00", arguments["as_of_time"])

    def test_ticket_without_policy_snapshot_does_not_use_history_summary_version(self) -> None:
        agent = LangGraphAfterSalesAgent(tools=FakeTools(), llm=FakeLlm())
        state = {
            "user_id": "1",
            "message": "申请退款",
            "history_summary": {"policy_version": "forged-summary-version"},
        }
        order = {
            "merchant_code": "MERCHANT_DEMO",
            "product_category": "数码",
            "after_sales_applied_at": "2026-07-20T09:00:00+08:00",
        }

        action = agent._retrieve_policy_action(state, order)

        self.assertEqual("tool_call", action["action"])
        self.assertEqual("submit_ai_review", action["tool_name"])
        self.assertEqual("MANUAL_REVIEW_REQUIRED", action["tool_arguments"]["verdict"])
        self.assertIsNone(action["tool_arguments"]["policy_version"])
        self.assertTrue(action["need_human"])

    def test_historical_order_policy_explanation_uses_order_creation_time(self) -> None:
        agent = LangGraphAfterSalesAgent(tools=FakeTools(), llm=FakeLlm())

        action = agent._retrieve_evidence_action(
            {"user_id": "1", "message": "购买时的退货政策是什么"},
            {
                "product_name": "蓝牙降噪耳机",
                "product_category": "数码",
                "merchant_code": "MERCHANT_DEMO",
                "create_time": "2026-06-01T10:30:00+08:00",
                "policy_version": "2026-06-v1",
            },
        )

        arguments = action["tool_arguments"]
        self.assertEqual("2026-06-01T10:30:00+08:00", arguments["as_of_time"])
        self.assertEqual("2026-06-v1", arguments["policy_version"])

    def test_general_faq_retrieval_does_not_invent_business_time(self) -> None:
        agent = LangGraphAfterSalesAgent(tools=FakeTools(), llm=FakeLlm())

        action = agent._retrieve_evidence_action(
            {"user_id": "1", "message": "一般需要哪些售后凭证"},
            {"merchant_code": "MERCHANT_DEMO"},
        )

        self.assertNotIn("as_of_time", action["tool_arguments"])

    def test_policy_retrieval_without_verified_business_time_fails_safe(self) -> None:
        agent = LangGraphAfterSalesAgent(tools=FakeTools(), llm=FakeLlm())

        action = agent._retrieve_policy_action(
            {"user_id": "1", "message": "申请退款"},
            {"merchant_code": "MERCHANT_DEMO", "product_category": "数码"},
        )

        self.assertEqual("human_handoff", action["action"])
        self.assertTrue(action["need_human"])
        self.assertNotIn("tool_name", action)

    def test_policy_retrieval_without_java_owned_merchant_fails_safe(self) -> None:
        agent = LangGraphAfterSalesAgent(tools=FakeTools(), llm=FakeLlm())

        action = agent._retrieve_policy_action(
            {"user_id": "1", "message": "申请退款"},
            {
                "product_category": "数码",
                "policy_version": "v2",
                "after_sales_applied_at": "2026-07-20T09:00:00+08:00",
            },
        )

        self.assertEqual("human_handoff", action["action"])
        self.assertTrue(action["need_human"])
        self.assertNotIn("tool_name", action)

    def test_only_strict_high_score_same_merchant_policy_can_authorize_auto_review(self) -> None:
        order = {
            "merchant_code": "MERCHANT_DEMO",
            "policy_version": "v2",
            "after_sales_applied_at": "2026-07-20T09:00:00+08:00",
        }
        trusted_hit = {
            "source_type": "after_sales_policy",
            "rerank_score": 0.82,
            "threshold": 0.75,
            "trusted_policy_eligible": True,
            "relaxation_level": "strict",
            "citations": [{"source_code": "POLICY-2", "chunk_id": "C-2"}],
            "metadata": {
                "merchant_code": "MERCHANT_DEMO",
                "policy_version": "v2",
                "valid_from": "2026-07-01T00:00:00",
                "valid_to": "2026-08-01T00:00:00",
            },
        }
        strict_knowledge = {
            "mode": "hybrid_reranked",
            "filter_level": "strict",
            "reranker_succeeded": True,
            "threshold": 0.75,
            "no_answer": False,
            "trusted_policy_eligible": True,
            "relaxation_level": "strict",
            "hits": [trusted_hit],
        }

        self.assertEqual(
            [trusted_hit],
            LangGraphAfterSalesAgent._trusted_policy_hits(
                strict_knowledge,
                order,
            ),
        )
        self.assertEqual(
            [],
            LangGraphAfterSalesAgent._trusted_policy_hits(
                {**strict_knowledge, "trusted_policy_eligible": False, "relaxation_level": "category_relaxed"},
                order,
            ),
        )
        self.assertEqual(
            [],
            LangGraphAfterSalesAgent._trusted_policy_hits(
                {**strict_knowledge, "hits": [{**trusted_hit, "rerank_score": 0.2}]},
                order,
            ),
        )
        self.assertEqual(
            [],
            LangGraphAfterSalesAgent._trusted_policy_hits(
                {
                    **strict_knowledge,
                    "hits": [{
                        **trusted_hit,
                        "metadata": {**trusted_hit["metadata"], "merchant_code": "OTHER"},
                    }],
                },
                order,
            ),
        )
        self.assertEqual(
            [],
            LangGraphAfterSalesAgent._trusted_policy_hits(
                {**strict_knowledge, "hits": [{**trusted_hit, "citations": []}]},
                order,
            ),
        )
        for malformed_citations in (
            [{}],
            [{"source_code": "POLICY-2"}],
            [{"chunk_id": "C-2"}],
            [{"source_code": " ", "document_id": "D-2"}],
        ):
            with self.subTest(citations=malformed_citations):
                self.assertEqual(
                    [],
                    LangGraphAfterSalesAgent._trusted_policy_hits(
                        {
                            **strict_knowledge,
                            "hits": [{**trusted_hit, "citations": malformed_citations}],
                        },
                        order,
                    ),
                )
        self.assertEqual(
            [],
            LangGraphAfterSalesAgent._trusted_policy_hits(
                strict_knowledge,
                {**order, "policy_version": None},
                {"policy_version": "v2"},
            ),
        )
        self.assertEqual(
            [],
            LangGraphAfterSalesAgent._trusted_policy_hits(
                {
                    **strict_knowledge,
                    "hits": [{
                        **trusted_hit,
                        "metadata": {
                            **trusted_hit["metadata"],
                            "valid_to": "2026-07-20T09:00:00+08:00",
                        },
                    }],
                },
                order,
            ),
        )
        self.assertEqual(
            [],
            LangGraphAfterSalesAgent._trusted_policy_hits(
                {
                    **strict_knowledge,
                    "hits": [{
                        **trusted_hit,
                        "metadata": {**trusted_hit["metadata"], "policy_version": "v1"},
                    }],
                },
                order,
            ),
        )
        self.assertEqual(
            [],
            LangGraphAfterSalesAgent._trusted_policy_hits(
                {**strict_knowledge, "hits": [{**trusted_hit, "rerank_score": None, "dense_score": 0.99, "keyword_score": 2.8, "score": 2.8}]},
                order,
            ),
        )
        self.assertEqual(
            [],
            LangGraphAfterSalesAgent._trusted_policy_hits(
                {**strict_knowledge, "reranker_succeeded": False},
                order,
            ),
        )
        self.assertEqual(
            [],
            LangGraphAfterSalesAgent._trusted_policy_hits(
                {**strict_knowledge, "filter_level": "category_relaxed"},
                order,
            ),
        )

    def test_rrf_degraded_policy_hit_is_not_trusted(self) -> None:
        knowledge = {
            "mode": "hybrid_rrf_degraded",
            "filter_level": "strict",
            "reranker_succeeded": False,
            "trusted_policy_eligible": True,
            "relaxation_level": "strict",
            "hits": [{
                "source_type": "after_sales_policy",
                "rerank_score": 0.99,
                "threshold": 0.75,
                "merchant_code": "MERCHANT_DEMO",
                "policy_version": "v2",
                "trusted_policy_eligible": True,
                "relaxation_level": "strict",
                "citations": [{"source_code": "POLICY-2"}],
            }],
        }

        hits = LangGraphAfterSalesAgent._trusted_policy_hits(
            knowledge,
            {
                "merchant_code": "MERCHANT_DEMO",
                "policy_version": "v2",
                "after_sales_applied_at": "2026-07-20T09:00:00+08:00",
            },
        )

        self.assertEqual([], hits)

    def test_decision_confidence_is_calibrated_from_visual_and_policy_evidence(self) -> None:
        strong_policy = [{"rerank_score": 0.8}]

        approved = LangGraphAfterSalesAgent._decision_confidence(0.9, strong_policy, True)
        manual = LangGraphAfterSalesAgent._decision_confidence(0.9, [], False)

        self.assertEqual(0.87, approved)
        self.assertEqual(0.63, manual)

    def test_high_value_and_duplicate_evidence_require_review(self) -> None:
        state = {
            "attachments": [
                {"name": "a.jpg", "source": "same"},
                {"name": "b.jpg", "source": "same"},
            ]
        }

        reasons = LangGraphAfterSalesAgent._risk_review_reasons(state, {"amount": 300})

        self.assertIn("refund_amount_above_auto_limit", reasons)
        self.assertIn("duplicate_evidence_in_request", reasons)

    def test_emotion_priority_prevents_auto_approval_and_reaches_ticket(self) -> None:
        review = {
            "success": True, "all_clear": True, "has_damage_area": True,
            "missing_visual_evidence": [],
            "items": [{"damage_confidence": 0.96, "contains_damage_area": True, "image_type": "商品照片"}],
        }
        tools = FakeEvidenceScenarioTools(review)
        agent = LangGraphAfterSalesAgent(tools=tools, llm=FakeLlm())

        result = agent.handle({
            "user_id": "1", "session_id": 1002,
            "ticket_id": "1783595588024",
            "review_request_id": "review-emotion",
            "message": "产品已经坏了，再不处理我就投诉",
            "order_id": "ORD1783595519525",
            "attachments": [{"name": "damage.jpg", "kind": "图片", "source": "https://example.com/damage.jpg"}],
            "client_context": {"source": "kafka", "emotion": {
                "label": "angry", "score": 0.88, "confidence": 0.93,
                "need_human_priority": True,
            }},
        })

        self.assertTrue(result["need_human"])
        self.assertEqual("MANUAL_REVIEW_REQUIRED", tools.create_arguments["verdict"])

    def test_tool_timeout_retries_same_action_once(self) -> None:
        agent = LangGraphAfterSalesAgent(tools=FakeTools(), llm=FakeLlm())
        state = {
            "user_id": "1",
            "steps": 1,
            "tool_name": "search_user_orders",
            "tool_arguments": {"user_id": "1", "keyword": "ORD1"},
            "tool_results": [
                {
                    "tool": "search_user_orders",
                    "arguments": {"user_id": "1", "keyword": "ORD1"},
                    "ok": False,
                    "data": None,
                    "error": "timeout while calling Java tool",
                }
            ],
            "evidence_needed": [],
        }

        with patch.dict("os.environ", {"AI_REVIEW_FAST_RETRY_ENABLED": "true"}, clear=False):
            agent.observe_tool_result(state)
            agent.decide_next(state)

        self.assertEqual("tool_call", state["next_action"])
        self.assertEqual("search_user_orders", state["tool_name"])
        self.assertFalse(state["need_human"])

    def test_tool_timeout_does_not_retry_when_fast_retry_disabled(self) -> None:
        agent = LangGraphAfterSalesAgent(tools=FakeTools(), llm=FakeLlm())
        state = {
            "user_id": "1",
            "steps": 1,
            "tool_name": "search_user_orders",
            "tool_arguments": {"user_id": "1", "keyword": "ORD1"},
            "tool_results": [
                {
                    "tool": "search_user_orders",
                    "arguments": {"user_id": "1", "keyword": "ORD1"},
                    "ok": False,
                    "data": None,
                    "error": "timeout while calling Java tool",
                }
            ],
            "evidence_needed": [],
        }

        with patch.dict("os.environ", {"AI_REVIEW_FAST_RETRY_ENABLED": "false"}, clear=False):
            agent.observe_tool_result(state)
            agent.decide_next(state)

        self.assertEqual("human_handoff", state["next_action"])
        self.assertTrue(state["need_human"])

    def test_repeated_service_unavailable_routes_to_human(self) -> None:
        agent = LangGraphAfterSalesAgent(tools=FakeTools(), llm=FakeLlm())
        arguments = {"user_id": "1", "keyword": "ORD1"}
        state = {
            "user_id": "1",
            "steps": 2,
            "tool_name": "search_user_orders",
            "tool_arguments": arguments,
            "tool_results": [
                {"tool": "search_user_orders", "arguments": arguments, "ok": False, "error": "connection refused"},
                {"tool": "search_user_orders", "arguments": arguments, "ok": False, "error": "service unavailable"},
            ],
            "evidence_needed": [],
        }

        agent.observe_tool_result(state)
        agent.decide_next(state)

        self.assertEqual("human_handoff", state["next_action"])
        self.assertTrue(state["need_human"])
        self.assertIn("人工客服", state["assistant_reply"])

    def test_validation_failure_guides_user_to_add_order_info(self) -> None:
        agent = LangGraphAfterSalesAgent(tools=FakeTools(), llm=FakeLlm())
        state = {
            "user_id": "1",
            "steps": 1,
            "tool_name": "get_order_detail",
            "tool_arguments": {"user_id": "1"},
            "tool_results": [
                {"tool": "get_order_detail", "arguments": {"user_id": "1"}, "ok": False, "error": "order_id is required"}
            ],
            "evidence_needed": [],
        }

        agent.observe_tool_result(state)
        agent.decide_next(state)

        self.assertEqual("final_reply", state["next_action"])
        self.assertFalse(state["need_human"])
        self.assertIn("补充订单号", state["assistant_reply"])

    def test_empty_order_search_does_not_override_successful_order_detail(self) -> None:
        agent = LangGraphAfterSalesAgent(tools=FakeTools(), llm=FakeLlm())
        state = {
            "user_id": "1",
            "steps": 2,
            "message": "耳机声音有问题，声音很小还有电流声",
            "order_id_hint": "2077050375394852865",
            "tool_results": [
                {
                    "tool": "get_order_detail",
                    "arguments": {"order_id": "2077050375394852865"},
                    "ok": True,
                    "data": {
                        "order_id": "2077050375394852865",
                        "order_no": "ORD2077050375394852865",
                        "product_name": "蓝牙降噪耳机",
                        "product_category": "数码",
                        "merchant_code": "MERCHANT_DEMO",
                        "status": "SHIPPED",
                        "existing_ticket_no": "AS1784042405523",
                    },
                },
                {
                    "tool": "search_user_orders",
                    "arguments": {
                        "keyword": "2077050375394852865",
                        "order_id": "2077050375394852865",
                    },
                    "ok": True,
                    "data": [],
                    "error": "",
                },
            ],
            "evidence_needed": [],
        }

        agent.decide_next(state)

        self.assertEqual("tool_call", state["next_action"])
        self.assertEqual("retrieve_knowledge", state["tool_name"])
        self.assertNotIn("没有查询到", state.get("assistant_reply") or "")

    def test_existing_after_sales_consultation_guides_evidence_without_reapply_text(self) -> None:
        agent = LangGraphAfterSalesAgent(tools=FakeTools(), llm=FakeLlm())
        state = {
            "user_id": "1",
            "steps": 2,
            "message": "耳机经常听不见声音，还有电流声",
            "order_id_hint": "2077052091053932546",
            "tool_results": [
                {
                    "tool": "get_order_detail",
                    "arguments": {"order_id": "2077052091053932546"},
                    "ok": True,
                    "data": {
                        "order_id": "2077052091053932546",
                        "order_no": "ORD2077052091053932546",
                        "product_name": "蓝牙降噪耳机",
                        "product_category": "数码",
                        "merchant_code": "MERCHANT_DEMO",
                        "status": "RECEIVED",
                        "has_open_after_sales": True,
                        "existing_ticket_no": "AS1784042835860",
                    },
                },
                {
                    "tool": "retrieve_knowledge",
                    "arguments": {"query": "耳机 电流声 售后证据"},
                    "ok": True,
                    "data": {"hits": [], "mode": "pgvector_error"},
                },
            ],
            "evidence_needed": [],
        }

        agent.decide_next(state)

        self.assertEqual("final_reply", state["next_action"])
        self.assertIn("补充", state["assistant_reply"])
        self.assertNotIn("申请售后", state["assistant_reply"])

    def test_first_attachment_file_url_uses_only_reachable_url(self) -> None:
        state = {
            "attachments": [
                {"source": "data:image/png;base64,AAAA"},
                {"file_url": "/uploads/2026/07/14/evidence.png", "source": "data:image/png;base64,BBBB"},
            ]
        }

        self.assertEqual(
            "/uploads/2026/07/14/evidence.png",
            LangGraphAfterSalesAgent._first_attachment_file_url(state),
        )

    def test_first_attachment_file_url_accepts_camel_case_file_url(self) -> None:
        state = {
            "attachments": [
                {"fileUrl": "/uploads/2026/07/15/evidence.png", "source": "data:image/png;base64,BBBB"},
            ]
        }

        self.assertEqual(
            "/uploads/2026/07/15/evidence.png",
            LangGraphAfterSalesAgent._first_attachment_file_url(state),
        )

    def test_http_attachment_builder_preserves_uploaded_file_url(self) -> None:
        attachments = build_attachments([
            {
                "kind": "image",
                "name": "evidence.png",
                "fileUrl": "/uploads/2026/07/15/evidence.png",
                "source": "data:image/png;base64,AAAA",
            }
        ])

        self.assertEqual("/uploads/2026/07/15/evidence.png", attachments[0].file_url)

    def test_handoff_session_id_is_reused_for_persisted_messages(self) -> None:
        tools = FakeHandoffSessionTools()
        agent = LangGraphAfterSalesAgent(tools=tools, llm=FakeLlm())
        state = {
            "user_id": "1",
            "order_id_hint": "2077052091053932546",
            "ticket_id": "3001",
            "message": "请转人工",
            "assistant_reply": "已为您转接人工客服，请稍等。",
            "need_human": True,
            "tool_results": [],
        }

        agent.human_handoff(state)
        agent.final_reply(state)

        self.assertEqual("9001", str(state["session_id"]))
        self.assertTrue(tools.append_arguments)
        self.assertTrue(all(str(item.get("session_id")) == "9001" for item in tools.append_arguments))

    def test_handoff_requires_java_confirmed_human_waiting_session(self) -> None:
        tools = FakeUnconfirmedHandoffTools()
        agent = LangGraphAfterSalesAgent(tools=tools, llm=FakeLlm())
        state = {
            "user_id": "1",
            "order_id_hint": "2077052091053932546",
            "ticket_id": "3001",
            "message": "请转人工",
            "assistant_reply": "已为您转接人工客服，请稍等。",
            "need_human": True,
            "tool_results": [],
        }

        agent.human_handoff(state)

        self.assertFalse(state["handoff_succeeded"])
        self.assertEqual("AI", state["session_mode"])
        self.assertNotIn("已为您转交人工复核", state["assistant_reply"])

    def test_permission_failure_stops_without_retry(self) -> None:
        agent = LangGraphAfterSalesAgent(tools=FakeTools(), llm=FakeLlm())
        state = {
            "user_id": "1",
            "steps": 1,
            "tool_name": "submit_ai_review",
            "tool_arguments": {"user_id": "1", "ticket_id": "T1", "review_request_id": "R1"},
            "tool_results": [
                {
                    "tool": "submit_ai_review",
                    "arguments": {"user_id": "1", "ticket_id": "T1", "review_request_id": "R1"},
                    "ok": False,
                    "error": "403 forbidden",
                }
            ],
            "evidence_needed": [],
        }

        agent.observe_tool_result(state)
        agent.decide_next(state)

        self.assertEqual("final_reply", state["next_action"])
        self.assertFalse(state["need_human"])
        self.assertIn("无权操作", state["assistant_reply"])


class NativeFunctionCallingWorkflowTest(unittest.TestCase):
    @staticmethod
    def _payload(**overrides: object) -> dict[str, object]:
        return {
            "user_id": "trusted-user",
            "session_id": 501,
            "message": "请查询售后进度",
            "order_id": "trusted-order",
            **overrides,
        }

    def test_native_function_planner_uses_required_tools_and_traces_call_id(self) -> None:
        tools = NativeWorkflowTools()
        llm = RecordingNativeLlm([
            native_response("call-lookup", "lookup", {}),
            native_response("call-final", "final_reply", {"assistant_reply": "已查询到处理进度。"}),
        ])

        result = LangGraphAfterSalesAgent(tools=tools, llm=llm).handle(self._payload())

        self.assertEqual("required", llm.requests[0]["tool_choice"])
        self.assertTrue(any(item["function"]["name"] == "lookup" for item in llm.requests[0]["tools"]))
        self.assertIn("调用一个提供的 function", llm.requests[0]["messages"][0]["content"])
        self.assertEqual("lookup", result["tool_trace"][0]["tool"])
        self.assertEqual("call-lookup", result["tool_trace"][0]["tool_call_id"])
        self.assertEqual("native", result["tool_trace"][0]["function_call_mode"])
        self.assertEqual("openai", result["tool_trace"][0]["provider_tool_call_shape"])
        self.assertTrue(all("function_call_mode" in item for item in result["tool_trace"]))
        self.assertTrue(all("provider_tool_call_shape" in item for item in result["tool_trace"]))
        self.assertTrue(all(
            item["function_call_mode"] == "deterministic"
            and item["provider_tool_call_shape"] == "none"
            for item in result["tool_trace"]
            if item["tool"] == "append_chat_message"
        ))
        assistant_append = next(
            arguments
            for name, arguments in zip(tools.calls, tools.arguments)
            if name == "append_chat_message" and arguments.get("role") == "ASSISTANT"
        )
        java_visible_trace = json.loads(str(assistant_append["knowledge_hits_json"]))
        self.assertTrue(java_visible_trace)
        self.assertTrue(all(
            "function_call_mode" not in item
            and "provider_tool_call_shape" not in item
            for item in java_visible_trace
        ))

    def test_ollama_native_shape_succeeds_in_strict_mode_without_legacy(self) -> None:
        tools = NativeWorkflowTools()
        llm = RecordingNativeLlm([
            ollama_response("handoff_to_human", {"assistant_reply": "Connecting you now."}),
        ])
        agent = LangGraphAfterSalesAgent(
            tools=tools,
            llm=llm,
            legacy_tool_call_fallback_enabled=False,
        )

        result = agent.handle(self._payload(order_id=""))

        handoff_trace = next(item for item in result["tool_trace"] if item["tool"] == "handoff_to_human")
        self.assertRegex(handoff_trace["tool_call_id"], r"^call_ollama_[0-9a-f]{32}$")
        self.assertEqual("native", handoff_trace["function_call_mode"])
        self.assertEqual("ollama", handoff_trace["provider_tool_call_shape"])
        self.assertEqual("HUMAN", result["session_mode"])

    def test_malformed_ollama_shape_fails_closed_without_tool_execution(self) -> None:
        tools = NativeWorkflowTools()
        agent = LangGraphAfterSalesAgent(
            tools=tools,
            llm=RecordingNativeLlm([{
                "message": {
                    "role": "assistant",
                    "tool_calls": [{"function": {"name": "lookup", "arguments": []}}],
                },
            }]),
            legacy_tool_call_fallback_enabled=False,
        )
        state = {
            "user_id": "trusted-user",
            "message": "help",
            "tool_results": [],
            "function_messages": [],
            "last_observation": {},
        }

        agent.classify_or_plan(state)

        self.assertEqual([], tools.calls)
        self.assertEqual("fail_closed", state["decision_protocol"])
        self.assertEqual("final_reply", state["next_action"])

    def test_native_function_decider_receives_compressed_correlated_observation(self) -> None:
        tools = NativeWorkflowTools()
        first = native_response("call-observation", "lookup", {})
        llm = RecordingNativeLlm([
            first,
            native_response("call-final", "final_reply", {"assistant_reply": "处理完成。"}),
        ])

        agent = LangGraphAfterSalesAgent(tools=tools, llm=llm)
        result = agent.handle(self._payload())

        messages = llm.requests[1]["messages"]
        self.assertEqual({
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call-observation",
                "type": "function",
                "function": {"name": "lookup", "arguments": {}},
            }],
        }, messages[1])
        self.assertEqual(
            "{}",
            first["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"],
        )
        self.assertEqual("tool", messages[2]["role"])
        self.assertEqual("call-observation", messages[2]["tool_call_id"])
        self.assertEqual("lookup", messages[2]["name"])
        self.assertEqual(
            {"tool": "lookup", "ok": True, "data_type": "dict"},
            json.loads(messages[2]["content"]),
        )
        self.assertNotIn("raw_secret", messages[2]["content"])
        self.assertEqual("处理完成。", result["assistant_reply"])

    def test_native_function_failed_tool_observation_is_correlated(self) -> None:
        tools = NativeWorkflowTools()
        failed = native_response("call-failed", "fail_lookup", {})
        llm = RecordingNativeLlm([
            failed,
            native_response("call-final", "final_reply", {"assistant_reply": "请稍后再试。"}),
        ])

        agent = LangGraphAfterSalesAgent(tools=tools, llm=llm)
        agent.handle(self._payload())

        tool_message = llm.requests[1]["messages"][2]
        self.assertEqual("call-failed", tool_message["tool_call_id"])
        self.assertEqual("fail_lookup", tool_message["name"])
        self.assertEqual(
            {
                "tool": "fail_lookup", "ok": False, "error_type": "tool_error",
                "error": "upstream failed: raw-secret-data", "error_code": "UPSTREAM", "retryable": False,
            },
            json.loads(tool_message["content"]),
        )

    def test_native_function_false_completed_review_claim_is_corrected_end_to_end(self) -> None:
        tools = NativeWorkflowTools()
        llm = RecordingNativeLlm([
            native_response("call-lookup", "lookup", {}),
            native_response("call-false-claim", "final_reply", {"assistant_reply": "AI初审已完成并进入处理中。"}),
        ])

        result = LangGraphAfterSalesAgent(tools=tools, llm=llm).handle(self._payload())

        self.assertEqual(2, len(llm.requests))
        self.assertNotEqual("AI初审已完成并进入处理中。", result["assistant_reply"])
        self.assertIn("暂时不能声称AI初审已完成", result["assistant_reply"])
        self.assertNotIn("submit_ai_review", tools.calls)

    def test_native_function_cannot_replace_deterministic_required_action(self) -> None:
        tools = NativeWorkflowTools()
        llm = RecordingNativeLlm([
            native_response("call-lookup", "lookup", {}),
            native_response("call-forbidden-review", "submit_ai_review", {"verdict": "APPROVE"}),
        ])

        result = LangGraphAfterSalesAgent(tools=tools, llm=llm).handle(self._payload())

        self.assertEqual(2, len(llm.requests))
        self.assertIn("search_user_orders", tools.calls)
        self.assertNotIn("submit_ai_review", tools.calls)
        self.assertIn("补充具体订单号", result["assistant_reply"])
        self.assertEqual(
            ("native", "openai"),
            (
                result["tool_trace"][0]["function_call_mode"],
                result["tool_trace"][0]["provider_tool_call_shape"],
            ),
        )
        deterministic_search = next(
            item for item in result["tool_trace"]
            if item["tool"] == "search_user_orders"
        )
        self.assertEqual("deterministic", deterministic_search["function_call_mode"])
        self.assertEqual("none", deterministic_search["provider_tool_call_shape"])

    def test_native_function_apply_action_overwrites_trusted_identifiers(self) -> None:
        tools = NativeWorkflowTools()
        llm = RecordingNativeLlm([
            native_response("call-review", "submit_ai_review", {"verdict": "MANUAL_REVIEW_REQUIRED"}),
        ])
        agent = LangGraphAfterSalesAgent(tools=tools, llm=llm)
        state = {
            "user_id": "trusted-user",
            "session_id": 501,
            "order_id_hint": "trusted-order",
            "ticket_id": "trusted-ticket",
            "review_request_id": "trusted-review",
            "allow_ai_review_submit": True,
            "message": "审核",
            "tool_results": [{"tool": "lookup", "ok": True, "data": {}}],
            "last_observation": {},
        }

        agent.classify_or_plan(state)

        self.assertEqual("tool_call", state["next_action"])
        self.assertEqual(
            {
                "verdict": "MANUAL_REVIEW_REQUIRED",
                "user_id": "trusted-user",
                "session_id": 501,
                "order_id": "trusted-order",
                "ticket_id": "trusted-ticket",
                "review_request_id": "trusted-review",
            },
            state["tool_arguments"],
        )

    def test_native_function_multiple_calls_fail_closed_without_tool_execution(self) -> None:
        tools = NativeWorkflowTools()
        response = native_response("call-one", "lookup", {})
        response["choices"][0]["message"]["tool_calls"].append({
            "id": "call-two", "type": "function", "function": {"name": "lookup", "arguments": "{}"},
        })
        agent = LangGraphAfterSalesAgent(
            tools=tools,
            llm=RecordingNativeLlm([response]),
            legacy_tool_call_fallback_enabled=False,
        )
        state = {
            "user_id": "trusted-user",
            "order_id_hint": "trusted-order",
            "message": "请查询售后进度",
            "tool_results": [],
            "function_messages": [],
            "last_observation": {},
        }

        agent.classify_or_plan(state)

        self.assertEqual([], tools.calls)
        self.assertEqual("fail_closed", state["decision_protocol"])
        self.assertEqual("final_reply", state["next_action"])

    def test_native_function_final_reply_does_not_execute_control_function(self) -> None:
        tools = NativeWorkflowTools()
        agent = LangGraphAfterSalesAgent(
            tools=tools,
            llm=RecordingNativeLlm([
                native_response("call-final", "final_reply", {"assistant_reply": "这是最终答复。"}),
            ]),
        )

        result = agent.handle(self._payload(order_id=""))

        self.assertEqual("这是最终答复。", result["assistant_reply"])
        self.assertNotIn("final_reply", tools.calls)

    def test_native_function_handoff_routes_to_persistence_node(self) -> None:
        tools = NativeWorkflowTools()
        agent = LangGraphAfterSalesAgent(
            tools=tools,
            llm=RecordingNativeLlm([
                native_response("call-handoff", "handoff_to_human", {"assistant_reply": "正在为您转接。"}),
            ]),
        )

        result = agent.handle(self._payload(order_id=""))

        self.assertEqual("HUMAN", result["session_mode"])
        self.assertIn("handoff_to_human", tools.calls)
        handoff_trace = next(item for item in result["tool_trace"] if item["tool"] == "handoff_to_human")
        self.assertEqual("call-handoff", handoff_trace["tool_call_id"])
        self.assertEqual("native", handoff_trace["function_call_mode"])
        self.assertEqual("openai", handoff_trace["provider_tool_call_shape"])
        self.assertTrue(all(
            "tool_call_id" not in item
            for item in result["tool_trace"]
            if item["tool"] == "append_chat_message"
        ))

    def test_native_handoff_success_keeps_call_id_until_correlated_observation(self) -> None:
        tools = NativeWorkflowTools()
        agent = LangGraphAfterSalesAgent(
            tools=tools,
            llm=RecordingNativeLlm([
                native_response("call-handoff-success", "handoff_to_human", {"assistant_reply": "Connecting."}),
            ]),
        )
        state = {
            "user_id": "trusted-user",
            "session_id": 501,
            "message": "human please",
            "tool_results": [],
            "function_messages": [],
            "last_observation": {},
        }

        agent.classify_or_plan(state)
        self.assertEqual("call-handoff-success", state["pending_tool_call_id"])
        agent.human_handoff(state)

        trace = state["tool_results"][-1]
        self.assertTrue(trace["ok"])
        self.assertEqual("call-handoff-success", trace["tool_call_id"])
        self.assertEqual("native", trace["function_call_mode"])
        self.assertEqual("openai", trace["provider_tool_call_shape"])
        self.assertEqual(
            "call-handoff-success",
            state["function_messages"][-2]["tool_calls"][0]["id"],
        )
        self.assertEqual("tool", state["function_messages"][-1]["role"])
        self.assertEqual("call-handoff-success", state["function_messages"][-1]["tool_call_id"])
        self.assertEqual("handoff_to_human", state["function_messages"][-1]["name"])
        observation = json.loads(state["function_messages"][-1]["content"])
        self.assertTrue(observation["ok"])
        self.assertEqual("HUMAN", observation["session_mode"])
        self.assertTrue(observation["handoff_succeeded"])
        self.assertIsNone(state["pending_tool_call_id"])
        self.assertIsNone(state["pending_assistant_tool_call"])
        self.assertEqual("deterministic", state["current_function_call_mode"])
        self.assertEqual("none", state["current_provider_tool_call_shape"])

    def test_native_handoff_failure_keeps_call_id_until_correlated_observation(self) -> None:
        tools = NativeHandoffFailureTools()
        agent = LangGraphAfterSalesAgent(
            tools=tools,
            llm=RecordingNativeLlm([
                native_response("call-handoff-failure", "handoff_to_human", {"assistant_reply": "Connecting."}),
            ]),
        )
        state = {
            "user_id": "trusted-user",
            "session_id": 501,
            "message": "human please",
            "tool_results": [],
            "function_messages": [],
            "last_observation": {},
        }

        agent.classify_or_plan(state)
        self.assertEqual("call-handoff-failure", state["pending_tool_call_id"])
        agent.human_handoff(state)

        trace = state["tool_results"][-1]
        self.assertFalse(trace["ok"])
        self.assertEqual("call-handoff-failure", trace["tool_call_id"])
        self.assertEqual("native", trace["function_call_mode"])
        self.assertEqual("openai", trace["provider_tool_call_shape"])
        tool_message = state["function_messages"][-1]
        self.assertEqual("tool", tool_message["role"])
        self.assertEqual("call-handoff-failure", tool_message["tool_call_id"])
        self.assertEqual("handoff_to_human", tool_message["name"])
        observation = json.loads(tool_message["content"])
        self.assertFalse(observation["ok"])
        self.assertEqual("AI", observation["session_mode"])
        self.assertFalse(observation["handoff_succeeded"])
        self.assertEqual("service_unavailable", observation["error_type"])
        self.assertIsNone(state["pending_tool_call_id"])
        self.assertIsNone(state["pending_assistant_tool_call"])
        self.assertEqual("deterministic", state["current_function_call_mode"])
        self.assertEqual("none", state["current_provider_tool_call_shape"])

    def test_native_final_reply_need_human_from_planner_correlates_successful_handoff(self) -> None:
        tools = NativeWorkflowTools()
        agent = LangGraphAfterSalesAgent(
            tools=tools,
            llm=RecordingNativeLlm([
                native_response(
                    "call-implicit-planner-handoff",
                    "final_reply",
                    {"assistant_reply": "需要人工继续核对。", "need_human": True},
                ),
            ]),
        )

        result = agent.handle(self._payload(order_id=""))

        handoff_trace = next(item for item in result["tool_trace"] if item["tool"] == "handoff_to_human")
        self.assertTrue(handoff_trace["ok"])
        self.assertEqual("call-implicit-planner-handoff", handoff_trace["tool_call_id"])
        self.assertEqual("native", handoff_trace["function_call_mode"])
        self.assertEqual("openai", handoff_trace["provider_tool_call_shape"])
        self.assertEqual("HUMAN", result["session_mode"])

    def test_native_final_reply_need_human_from_terminal_decider_correlates_failed_handoff(self) -> None:
        tools = NativeHandoffFailureTools()
        agent = LangGraphAfterSalesAgent(
            tools=tools,
            llm=RecordingNativeLlm([
                native_response(
                    "call-implicit-terminal-handoff",
                    "final_reply",
                    {"assistant_reply": "需要人工继续核对。", "need_human": True},
                ),
            ]),
        )
        state = {
            "user_id": "trusted-user",
            "session_id": 501,
            "message": "继续处理",
            "steps": 1,
            "tool_results": [{"tool": "lookup", "ok": True, "data": {}}],
            "function_messages": [],
            "last_observation": {},
            "need_human": False,
        }

        with patch.object(agent, "_guarded_after_sales_action", return_value=None):
            agent.decide_next(state)

        self.assertEqual("human_handoff", agent.route_after_decision(state))
        self.assertEqual("call-implicit-terminal-handoff", state["pending_tool_call_id"])
        agent.human_handoff(state)

        trace = state["tool_results"][-1]
        self.assertFalse(trace["ok"])
        self.assertEqual("call-implicit-terminal-handoff", trace["tool_call_id"])
        self.assertEqual("native", trace["function_call_mode"])
        self.assertEqual("openai", trace["provider_tool_call_shape"])
        self.assertEqual(
            "call-implicit-terminal-handoff",
            state["function_messages"][-2]["tool_calls"][0]["id"],
        )
        self.assertEqual("call-implicit-terminal-handoff", state["function_messages"][-1]["tool_call_id"])
        self.assertEqual("final_reply", state["function_messages"][-1]["name"])
        observation = json.loads(state["function_messages"][-1]["content"])
        self.assertFalse(observation["ok"])
        self.assertEqual("AI", observation["session_mode"])
        self.assertFalse(observation["handoff_succeeded"])
        self.assertIsNone(state["pending_tool_call_id"])
        self.assertIsNone(state["pending_assistant_tool_call"])
        self.assertEqual("deterministic", state["current_function_call_mode"])
        self.assertEqual("none", state["current_provider_tool_call_shape"])

    def test_native_implicit_handoff_http_success_without_java_confirmation_is_not_reported_as_human(self) -> None:
        tools = FakeUnconfirmedHandoffTools()
        agent = LangGraphAfterSalesAgent(
            tools=tools,
            llm=RecordingNativeLlm([
                native_response(
                    "call-implicit-unconfirmed",
                    "final_reply",
                    {"assistant_reply": "需要人工继续核对。", "need_human": True},
                ),
            ]),
        )
        state = {
            "user_id": "trusted-user",
            "session_id": 501,
            "message": "请继续处理",
            "tool_results": [],
            "function_messages": [],
            "last_observation": {},
        }

        agent.classify_or_plan(state)
        agent.human_handoff(state)

        trace = state["tool_results"][-1]
        self.assertTrue(trace["ok"])
        self.assertEqual("handoff_to_human", trace["tool"])
        self.assertEqual("call-implicit-unconfirmed", trace["tool_call_id"])
        tool_message = state["function_messages"][-1]
        self.assertEqual("final_reply", tool_message["name"])
        self.assertEqual("call-implicit-unconfirmed", tool_message["tool_call_id"])
        observation = json.loads(tool_message["content"])
        self.assertFalse(observation["ok"])
        self.assertEqual("AI", observation["session_mode"])
        self.assertFalse(observation["handoff_succeeded"])
        self.assertEqual("AI", state["session_mode"])
        self.assertFalse(state["handoff_succeeded"])
        self.assertIsNone(state["pending_tool_call_id"])

    def test_native_function_deterministic_tool_does_not_inherit_stale_call_id(self) -> None:
        tools = NativeWorkflowTools()
        agent = LangGraphAfterSalesAgent(tools=tools, llm=RecordingNativeLlm([]))
        state = {
            "user_id": "trusted-user",
            "order_id_hint": "trusted-order",
            "message": "附件问题",
            "attachments": [{"name": "evidence.jpg", "source": "https://example.com/evidence.jpg"}],
            "tool_results": [],
            "function_messages": [],
            "pending_tool_call_id": "stale-call",
            "pending_assistant_tool_call": {"role": "assistant", "tool_calls": []},
        }

        agent.classify_or_plan(state)
        agent.tool_call(state)
        agent.observe_tool_result(state)

        self.assertNotIn("tool_call_id", state["tool_results"][0])
        self.assertEqual("deterministic", state["tool_results"][0]["function_call_mode"])
        self.assertEqual("none", state["tool_results"][0]["provider_tool_call_shape"])
        self.assertEqual([], state["function_messages"])
        self.assertIsNone(state["pending_tool_call_id"])
        self.assertIsNone(state["pending_assistant_tool_call"])

    def test_deterministic_limit_handoffs_do_not_inherit_native_or_legacy_trace_source(self) -> None:
        cases = []

        native_agent = LangGraphAfterSalesAgent(
            tools=NativeWorkflowTools(),
            llm=RecordingNativeLlm([]),
            max_tool_calls=0,
        )
        native_state = {
            "user_id": "trusted-user",
            "session_id": 501,
            "message": "查询",
            "steps": 0,
            "tool_name": "lookup",
            "tool_arguments": {"user_id": "trusted-user"},
            "tool_results": [],
            "function_messages": [],
            "pending_tool_call_id": "stale-native-call",
            "pending_assistant_tool_call": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "stale-native-call",
                    "type": "function",
                    "function": {"name": "lookup", "arguments": {}},
                }],
            },
            "current_function_call_mode": "native",
            "current_provider_tool_call_shape": "openai",
            "need_human": False,
        }
        native_agent.tool_call(native_state)
        native_agent.observe_tool_result(native_state)
        native_agent.decide_next(native_state)
        native_agent.human_handoff(native_state)
        cases.append(("native_max_tool", native_state, native_state["tool_results"][-2:]))

        legacy_agent = LangGraphAfterSalesAgent(
            tools=NativeWorkflowTools(),
            llm=RecordingNativeLlm([]),
            max_duplicate_tool_calls=1,
        )
        legacy_state = {
            "user_id": "trusted-user",
            "session_id": 501,
            "message": "查询",
            "steps": 0,
            "tool_name": "lookup",
            "tool_arguments": {"user_id": "trusted-user"},
            "tool_results": [{
                "tool": "lookup",
                "arguments": {"user_id": "trusted-user"},
                "ok": True,
            }],
            "function_messages": [],
            "pending_tool_call_id": None,
            "pending_assistant_tool_call": None,
            "current_function_call_mode": "legacy",
            "current_provider_tool_call_shape": "legacy_json",
            "need_human": False,
        }
        legacy_agent.tool_call(legacy_state)
        legacy_agent.observe_tool_result(legacy_state)
        legacy_agent.decide_next(legacy_state)
        legacy_agent.human_handoff(legacy_state)
        cases.append(("legacy_duplicate", legacy_state, legacy_state["tool_results"][-2:]))

        max_step_agent = LangGraphAfterSalesAgent(
            tools=NativeWorkflowTools(),
            llm=RecordingNativeLlm([]),
            max_steps=1,
        )
        max_step_state = {
            "user_id": "trusted-user",
            "session_id": 501,
            "message": "查询",
            "steps": 1,
            "tool_results": [],
            "function_messages": [],
            "pending_tool_call_id": "stale-max-step-call",
            "pending_assistant_tool_call": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "stale-max-step-call",
                    "type": "function",
                    "function": {"name": "lookup", "arguments": {}},
                }],
            },
            "current_function_call_mode": "native",
            "current_provider_tool_call_shape": "ollama",
            "need_human": True,
        }
        max_step_agent.decide_next(max_step_state)
        max_step_agent.human_handoff(max_step_state)
        cases.append(("max_step", max_step_state, max_step_state["tool_results"][-1:]))

        for name, state, new_traces in cases:
            with self.subTest(name=name):
                self.assertTrue(new_traces)
                self.assertTrue(all(
                    trace["function_call_mode"] == "deterministic"
                    and trace["provider_tool_call_shape"] == "none"
                    and "tool_call_id" not in trace
                    for trace in new_traces
                ))
                self.assertIsNone(state["pending_tool_call_id"])
                self.assertIsNone(state["pending_assistant_tool_call"])
                self.assertEqual("deterministic", state["current_function_call_mode"])
                self.assertEqual("none", state["current_provider_tool_call_shape"])


class NativeFunctionCallingFallbackWorkflowTest(unittest.TestCase):
    @staticmethod
    def _state() -> dict[str, object]:
        return {
            "user_id": "trusted-user",
            "session_id": 501,
            "order_id_hint": "trusted-order",
            "message": "请查询售后进度",
            "tool_results": [],
            "function_messages": [],
            "last_observation": {},
        }

    def test_native_function_disabled_uses_legacy_once_without_native_chat(self) -> None:
        llm = SwitchingDecisionLlm([], [{
            "action": "final_reply",
            "tool_name": None,
            "tool_arguments": {},
            "assistant_reply": "兼容回复",
            "need_human": False,
            "evidence_needed": [],
        }])
        agent = LangGraphAfterSalesAgent(
            tools=NativeWorkflowTools(),
            llm=llm,
            native_function_calling_enabled=False,
        )
        state = self._state()
        state["order_id_hint"] = None

        agent.classify_or_plan(state)

        self.assertEqual(0, llm.native_calls)
        self.assertEqual(1, llm.legacy_calls)
        self.assertEqual("legacy_disabled_native", state["decision_protocol"])
        self.assertIsNone(state.get("pending_tool_call_id"))
        self.assertEqual([], state["function_messages"])
        legacy_prompt = str(llm.legacy_requests[0]["system_prompt"])
        self.assertIn("Planner", legacy_prompt)
        self.assertIn("只输出一个完整 JSON 对象", legacy_prompt)
        for field in (
            "action",
            "tool_name",
            "tool_arguments",
            "assistant_reply",
            "need_human",
            "evidence_needed",
        ):
            self.assertIn(field, legacy_prompt)
        self.assertNotIn("调用一个提供的 function", legacy_prompt)
        self.assertIsInstance(json.loads(str(llm.legacy_requests[0]["user_prompt"])), dict)

    def test_native_planner_prompt_requires_function_without_legacy_json_envelope(self) -> None:
        llm = RecordingNativeLlm([
            native_response("call-final", "final_reply", {"assistant_reply": "正常回复"}),
        ])
        agent = LangGraphAfterSalesAgent(tools=NativeWorkflowTools(), llm=llm)
        state = self._state()
        state["order_id_hint"] = None

        agent.classify_or_plan(state)

        native_prompt = str(llm.requests[0]["messages"][0]["content"])
        self.assertIn("调用一个提供的 function", native_prompt)
        self.assertNotIn("只输出一个完整 JSON 对象", native_prompt)
        self.assertNotIn('"action"', native_prompt)

    def test_native_terminal_failure_uses_independent_legacy_decider_prompt_once(self) -> None:
        llm = SwitchingDecisionLlm(
            [LLMError("native unavailable")],
            [{
                "action": "final_reply",
                "tool_name": None,
                "tool_arguments": {},
                "assistant_reply": "兼容终态回复",
                "need_human": False,
                "evidence_needed": [],
            }],
        )
        agent = LangGraphAfterSalesAgent(tools=NativeWorkflowTools(), llm=llm)
        state = self._state()
        guarded = {
            "action": "final_reply",
            "assistant_reply": "确定性回复",
            "need_human": False,
            "evidence_needed": [],
        }

        result = agent._native_terminal_decision(state, guarded)

        self.assertEqual("兼容终态回复", result["assistant_reply"])
        self.assertEqual(1, llm.native_calls)
        self.assertEqual(1, llm.legacy_calls)
        legacy_prompt = str(llm.legacy_requests[0]["system_prompt"])
        self.assertIn("Terminal Decider", legacy_prompt)
        self.assertIn("只输出一个完整 JSON 对象", legacy_prompt)
        self.assertNotIn("调用一个提供的 function", legacy_prompt)

    def test_native_function_disabled_legacy_tool_trace_has_explicit_mode(self) -> None:
        tools = NativeWorkflowTools()
        llm = SwitchingDecisionLlm(
            [],
            [{"action": "tool_call", "tool_name": "lookup", "tool_arguments": {}}],
        )
        agent = LangGraphAfterSalesAgent(
            tools=tools,
            llm=llm,
            native_function_calling_enabled=False,
        )
        state = self._state()

        agent.classify_or_plan(state)
        agent.tool_call(state)

        trace = state["tool_results"][-1]
        self.assertEqual("legacy", trace["function_call_mode"])
        self.assertEqual("legacy_json", trace["provider_tool_call_shape"])

    def test_legacy_handoff_tool_call_routes_once_through_dedicated_node(self) -> None:
        cases = {
            "confirmed": (
                NativeWorkflowTools(),
                "HUMAN",
                True,
                True,
                None,
            ),
            "http_failure": (
                NativeHandoffFailureTools(),
                "AI",
                False,
                False,
                "service_unavailable",
            ),
            "unconfirmed": (
                FakeUnconfirmedHandoffTools(),
                "AI",
                False,
                True,
                "unconfirmed",
            ),
        }

        for name, (tools, expected_mode, succeeded, transport_ok, error_type) in cases.items():
            with self.subTest(name=name):
                llm = SwitchingDecisionLlm([], [{
                    "action": "tool_call",
                    "tool_name": "handoff_to_human",
                    "tool_arguments": {"assistant_reply": "正在连接人工客服。"},
                    "assistant_reply": "需要人工继续核对。",
                    "need_human": False,
                    "evidence_needed": ["订单凭证"],
                }])
                agent = HandoffPathRecordingAgent(
                    tools=tools,
                    llm=llm,
                    native_function_calling_enabled=False,
                )

                result = agent.handle({
                    "user_id": "trusted-user",
                    "session_id": 501,
                    "message": "需要继续核对售后情况",
                    "order_id": "",
                })

                self.assertEqual(0, llm.native_calls)
                self.assertEqual(1, llm.legacy_calls)
                self.assertEqual(0, agent.tool_call_node_calls)
                self.assertEqual(0, agent.observe_node_calls)
                self.assertEqual(1, agent.handoff_node_calls)
                self.assertEqual(1, tools.calls.count("handoff_to_human"))
                self.assertEqual("human_handoff", agent.handoff_input["next_action"])
                self.assertEqual("需要人工继续核对。", agent.handoff_input["assistant_reply"])
                self.assertEqual(["订单凭证"], agent.handoff_input["evidence_needed"])
                self.assertIsNone(agent.handoff_input.get("pending_tool_call_id"))
                self.assertEqual([], agent.handoff_input["function_messages"])
                self.assertEqual(expected_mode, result["session_mode"])
                self.assertEqual(expected_mode, agent.handoff_output["session_mode"])
                self.assertEqual(succeeded, agent.handoff_output["handoff_succeeded"])
                self.assertTrue(agent.handoff_output["need_human"])
                observation = agent.handoff_output["last_observation"]
                self.assertEqual(succeeded, observation["ok"])
                self.assertEqual(expected_mode, observation["session_mode"])
                self.assertEqual(succeeded, observation["handoff_succeeded"])
                if error_type is not None:
                    self.assertEqual(error_type, observation["error_type"])
                trace = agent.handoff_output["handoff_trace"]
                self.assertEqual("handoff_to_human", trace["tool"])
                self.assertEqual(transport_ok, trace["ok"])
                self.assertEqual("legacy", trace["function_call_mode"])
                self.assertEqual("legacy_json", trace["provider_tool_call_shape"])
                self.assertNotIn("tool_call_id", trace)
                if not succeeded:
                    self.assertNotIn(
                        "已为您转接人工客服，请稍等",
                        str(agent.handoff_output["assistant_reply"]),
                    )

    def test_direct_handoff_observation_requires_java_human_waiting_confirmation(self) -> None:
        agent = LangGraphAfterSalesAgent(
            tools=NativeWorkflowTools(),
            llm=RecordingNativeLlm([]),
        )
        state = {
            "user_id": "trusted-user",
            "session_mode": "AI",
            "need_human": False,
            "handoff_succeeded": None,
            "assistant_reply": "已为您转接人工客服，请稍等。",
            "tool_results": [{
                "tool": "handoff_to_human",
                "arguments": {"user_id": "trusted-user"},
                "ok": True,
                "data": {"mode": "AI", "status": "ACTIVE"},
                "error": None,
                "function_call_mode": "deterministic",
                "provider_tool_call_shape": "none",
            }],
            "function_messages": [],
            "last_observation": {},
        }

        agent.observe_tool_result(state)

        self.assertEqual("AI", state["session_mode"])
        self.assertTrue(state["need_human"])
        self.assertFalse(state["handoff_succeeded"])
        self.assertFalse(state["last_tool_ok"])
        self.assertTrue(state["last_tool_failed"])
        self.assertEqual("unconfirmed", state["last_error_type"])
        self.assertFalse(state["last_observation"]["ok"])
        self.assertEqual("AI", state["last_observation"]["session_mode"])
        self.assertFalse(state["last_observation"]["handoff_succeeded"])
        self.assertEqual("unconfirmed", state["last_observation"]["error_type"])
        self.assertNotIn("已为您转接人工客服，请稍等", state["assistant_reply"])
        self.assertTrue(state["tool_results"][-1]["ok"])

    def test_native_protocol_failure_uses_one_legacy_action_with_trusted_state(self) -> None:
        malformed = native_response("call-bad", "unknown_tool", {})
        llm = SwitchingDecisionLlm(
            [malformed],
            [{"action": "tool_call", "tool_name": "lookup", "tool_arguments": {}}],
        )
        agent = LangGraphAfterSalesAgent(tools=NativeWorkflowTools(), llm=llm)
        state = self._state()

        agent.classify_or_plan(state)

        self.assertEqual(1, llm.native_calls)
        self.assertEqual(1, llm.legacy_calls)
        self.assertEqual("legacy_fallback", state["decision_protocol"])
        self.assertEqual("tool_call", state["next_action"])
        self.assertEqual("trusted-user", state["tool_arguments"]["user_id"])
        self.assertNotIn("tool_call_id", state)

    def test_native_success_never_calls_legacy(self) -> None:
        llm = SwitchingDecisionLlm(
            [native_response("call-final", "final_reply", {"assistant_reply": "正常回复"})],
            [],
        )
        state = self._state()
        state["order_id_hint"] = None
        agent = LangGraphAfterSalesAgent(tools=NativeWorkflowTools(), llm=llm)

        agent.classify_or_plan(state)

        self.assertEqual(1, llm.native_calls)
        self.assertEqual(0, llm.legacy_calls)
        self.assertEqual("native", state["decision_protocol"])

    def test_native_failure_matrix_attempts_legacy_exactly_once(self) -> None:
        multiple = native_response("call-one", "lookup", {})
        multiple["choices"][0]["message"]["tool_calls"].append({
            "id": "call-two", "type": "function", "function": {"name": "lookup", "arguments": "{}"},
        })
        malformed_json = native_response("call-json", "lookup", {})
        malformed_json["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = "{"
        wrong_type = native_response("call-type", "search_user_orders", {"keyword": 12})
        cases = {
            "provider_error": LLMError("provider rejected tools"),
            "missing_call": {"choices": [{"message": {"role": "assistant", "tool_calls": []}}]},
            "multiple_calls": multiple,
            "malformed_json": malformed_json,
            "unknown_tool": native_response("call-unknown", "unknown_tool", {}),
            "wrong_type": wrong_type,
        }

        for name, native_failure in cases.items():
            with self.subTest(name=name):
                llm = SwitchingDecisionLlm(
                    [native_failure],
                    [{"action": "final_reply", "assistant_reply": "兼容回复"}],
                )
                agent = LangGraphAfterSalesAgent(tools=NativeWorkflowTools(), llm=llm)
                state = self._state()
                state["order_id_hint"] = None

                agent.classify_or_plan(state)

                self.assertEqual(1, llm.native_calls)
                self.assertEqual(1, llm.legacy_calls)
                self.assertEqual("legacy_fallback", state["decision_protocol"])

    def test_legacy_schema_invalid_actions_fail_closed_before_registry(self) -> None:
        invalid_actions = [
            {"action": "tool_call", "tool_name": "search_user_orders", "tool_arguments": {}},
            {"action": "tool_call", "tool_name": "search_user_orders", "tool_arguments": {"keyword": 1}},
            {"action": "tool_call", "tool_name": "lookup", "tool_arguments": {"unknown": True}},
            {"action": "tool_call", "tool_name": "nested_lookup", "tool_arguments": {"filter": {"status": "OPEN", "unknown": True}}},
            {"action": "tool_call", "tool_name": "submit_ai_review", "tool_arguments": {"verdict": "APPROVE", "ticket_id": "forged"}},
        ]

        for invalid in invalid_actions:
            with self.subTest(invalid=invalid):
                tools = NativeWorkflowTools()
                llm = SwitchingDecisionLlm(
                    [native_response("call-unknown", "unknown_tool", {})],
                    [invalid],
                )
                agent = LangGraphAfterSalesAgent(tools=tools, llm=llm)
                state = self._state()

                agent.classify_or_plan(state)

                self.assertEqual(1, llm.native_calls)
                self.assertEqual(1, llm.legacy_calls)
                self.assertEqual("fail_closed", state["decision_protocol"])
                self.assertEqual([], tools.calls)

    def test_legacy_non_dict_fails_closed(self) -> None:
        llm = SwitchingDecisionLlm(
            [native_response("call-unknown", "unknown_tool", {})],
            [["not", "an", "object"]],
        )
        state = self._state()
        agent = LangGraphAfterSalesAgent(tools=NativeWorkflowTools(), llm=llm)

        agent.classify_or_plan(state)

        self.assertEqual(1, llm.native_calls)
        self.assertEqual(1, llm.legacy_calls)
        self.assertEqual("fail_closed", state["decision_protocol"])

    def test_valid_legacy_fallback_executes_only_after_trusted_id_injection(self) -> None:
        tools = NativeWorkflowTools()
        llm = SwitchingDecisionLlm(
            [native_response("call-unknown", "unknown_tool", {})],
            [{"action": "tool_call", "tool_name": "lookup", "tool_arguments": {}}],
        )
        state = self._state()
        agent = LangGraphAfterSalesAgent(tools=tools, llm=llm)

        agent.classify_or_plan(state)
        agent.tool_call(state)

        self.assertEqual(1, llm.native_calls)
        self.assertEqual(1, llm.legacy_calls)
        self.assertEqual("legacy_fallback", state["decision_protocol"])
        self.assertEqual(["lookup"], tools.calls)
        self.assertEqual("trusted-user", tools.arguments[0]["user_id"])
        self.assertEqual("trusted-order", tools.arguments[0]["order_id"])
        self.assertEqual("legacy", state["tool_results"][-1]["function_call_mode"])
        self.assertEqual("legacy_json", state["tool_results"][-1]["provider_tool_call_shape"])

    def test_legacy_fallback_cannot_submit_review_from_non_kafka_source(self) -> None:
        tools = NativeWorkflowTools()
        llm = SwitchingDecisionLlm(
            [native_response("call-unknown", "unknown_tool", {})],
            [{"action": "tool_call", "tool_name": "submit_ai_review", "tool_arguments": {"verdict": "APPROVE"}}],
        )
        state = self._state()
        state.update({"ticket_id": "trusted-ticket", "tool_results": [{"tool": "lookup", "ok": True}]})
        agent = LangGraphAfterSalesAgent(tools=tools, llm=llm)

        agent.classify_or_plan(state)

        self.assertEqual(1, llm.native_calls)
        self.assertEqual(1, llm.legacy_calls)
        self.assertEqual("legacy_fallback", state["decision_protocol"])
        self.assertEqual("final_reply", state["next_action"])
        self.assertNotIn("submit_ai_review", tools.calls)

    def test_legacy_planner_false_completion_claim_is_guarded(self) -> None:
        llm = SwitchingDecisionLlm(
            [native_response("call-unknown", "unknown_tool", {})],
            [{"action": "final_reply", "assistant_reply": "AI初审已完成并进入处理中。"}],
        )
        state = self._state()
        agent = LangGraphAfterSalesAgent(tools=NativeWorkflowTools(), llm=llm)

        agent.classify_or_plan(state)

        self.assertEqual(1, llm.native_calls)
        self.assertEqual(1, llm.legacy_calls)
        self.assertEqual("legacy_fallback", state["decision_protocol"])
        self.assertNotIn("已完成并进入处理中", state.get("assistant_reply", ""))

    def test_terminal_decider_accepts_valid_legacy_final_reply(self) -> None:
        llm = SwitchingDecisionLlm(
            [native_response("call-unknown", "unknown_tool", {})],
            [{"action": "final_reply", "assistant_reply": "兼容终态回复"}],
        )
        state = self._state()
        agent = LangGraphAfterSalesAgent(tools=NativeWorkflowTools(), llm=llm)

        action = agent._native_terminal_decision(
            state,
            {"action": "final_reply", "assistant_reply": "确定性回复", "need_human": False},
        )

        self.assertEqual(1, llm.native_calls)
        self.assertEqual(1, llm.legacy_calls)
        self.assertEqual("legacy_fallback", state["decision_protocol"])
        self.assertEqual("兼容终态回复", action["assistant_reply"])

    def test_terminal_handle_decision_matrix_preserves_protocol_boundaries(self) -> None:
        cases = {
            "native_success": {
                "native": [
                    native_response("call-plan", "lookup", {}),
                    native_response("call-terminal", "final_reply", {"assistant_reply": "原生终态回复"}),
                ],
                "legacy": [],
                "agent_kwargs": {},
                "native_calls": 2,
                "legacy_calls": 0,
                "protocol": "native",
                "reply": "原生终态回复",
            },
            "native_disabled": {
                "native": [],
                "legacy": [
                    {"action": "tool_call", "tool_name": "lookup", "tool_arguments": {}},
                    {"action": "final_reply", "assistant_reply": "兼容终态回复"},
                ],
                "agent_kwargs": {"native_function_calling_enabled": False},
                "native_calls": 0,
                "legacy_calls": 2,
                "protocol": "legacy_disabled_native",
                "reply": "兼容终态回复",
            },
            "terminal_protocol_error_uses_one_legacy_attempt": {
                "native": [
                    native_response("call-plan", "lookup", {}),
                    native_response("call-terminal-invalid", "submit_ai_review", {"verdict": 1}),
                ],
                "legacy": [{"action": "final_reply", "assistant_reply": "兼容纠正回复"}],
                "agent_kwargs": {},
                "native_calls": 2,
                "legacy_calls": 1,
                "protocol": "legacy_fallback",
                "reply": "兼容纠正回复",
            },
            "terminal_invalid_legacy_schema_fails_closed": {
                "native": [
                    native_response("call-plan", "lookup", {}),
                    native_response("call-terminal-invalid", "submit_ai_review", {"verdict": 1}),
                ],
                "legacy": [{"action": "tool_call", "tool_name": "search_user_orders", "tool_arguments": {"keyword": 1}}],
                "agent_kwargs": {},
                "native_calls": 2,
                "legacy_calls": 1,
                "protocol": "fail_closed",
                "reply": "当前智能售后服务暂时不可用",
            },
            "terminal_legacy_false_review_completion_is_corrected": {
                "native": [
                    native_response("call-plan", "lookup", {}),
                    native_response("call-terminal-invalid", "submit_ai_review", {"verdict": 1}),
                ],
                "legacy": [{"action": "final_reply", "assistant_reply": "AI初审已完成并进入处理中。"}],
                "agent_kwargs": {},
                "native_calls": 2,
                "legacy_calls": 1,
                "protocol": "legacy_fallback",
                "reply": "暂时不能声称AI初审已完成",
            },
        }

        for name, case in cases.items():
            with self.subTest(name=name):
                tools = NativeWorkflowTools()
                llm = SwitchingDecisionLlm(case["native"], case["legacy"])
                agent = LangGraphAfterSalesAgent(tools=tools, llm=llm, **case["agent_kwargs"])

                result = agent.handle({"user_id": "trusted-user", "session_id": 501, "message": "帮助"})

                self.assertEqual(case["native_calls"], llm.native_calls)
                self.assertEqual(case["legacy_calls"], llm.legacy_calls)
                self.assertEqual(case["protocol"], result["raw"]["decision_protocol"])
                self.assertIn(case["reply"], result["assistant_reply"])
                self.assertEqual(1, tools.calls.count("lookup"))
                self.assertNotIn("submit_ai_review", tools.calls)
                self.assertEqual(["append_chat_message", "append_chat_message"], tools.calls[-2:])
                lookup_trace = next(item for item in result["tool_trace"] if item["tool"] == "lookup")
                if case["protocol"] == "legacy_disabled_native":
                    self.assertNotIn("tool_call_id", lookup_trace)
                else:
                    self.assertEqual("call-plan", lookup_trace["tool_call_id"])

    def test_terminal_fallback_disabled_fails_closed_without_requested_business_tool(self) -> None:
        tools = NativeWorkflowTools()
        llm = SwitchingDecisionLlm(
            [
                native_response("call-plan", "lookup", {}),
                native_response("call-terminal-invalid", "submit_ai_review", {"verdict": 1}),
            ],
            [],
        )
        agent = LangGraphAfterSalesAgent(
            tools=tools,
            llm=llm,
            legacy_tool_call_fallback_enabled=False,
        )

        result = agent.handle({"user_id": "trusted-user", "session_id": 501, "message": "帮助"})

        self.assertEqual(2, llm.native_calls)
        self.assertEqual(0, llm.legacy_calls)
        self.assertEqual("fail_closed", result["raw"]["decision_protocol"])
        self.assertEqual(1, tools.calls.count("lookup"))
        self.assertNotIn("submit_ai_review", tools.calls)
        self.assertEqual(["append_chat_message", "append_chat_message"], tools.calls[-2:])

    def test_function_calling_logs_exclude_model_tool_and_observation_content(self) -> None:
        secret = "SECRET-FUNCTION-CALL-CONTENT"
        llm = SwitchingDecisionLlm(
            [LLMError(secret)],
            [{"action": "final_reply", "assistant_reply": secret}],
        )
        tools = NativeWorkflowTools()
        agent = LangGraphAfterSalesAgent(tools=tools, llm=llm)
        state = self._state()
        state["message"] = secret

        with patch("after_sales_agent.application.after_sales_workflow.logger") as logger:
            agent.classify_or_plan(state)
            state.update({"tool_name": "fail_lookup", "tool_arguments": {"private": secret}})
            agent.tool_call(state)
            agent.observe_tool_result(state)
            agent.decide_next(state)
            agent.final_reply({
                "assistant_reply": secret,
                "tool_results": [],
                "attachments": [],
                "session_mode": "AI",
                "need_human": False,
                "steps": 0,
                "user_id": "trusted-user",
                "session_id": 501,
                "message": secret,
                "order_id_hint": None,
                "ticket_id": None,
            })

        logged = "\n".join(
            repr(call)
            for method in (logger.info, logger.warning, logger.error)
            for call in method.call_args_list
        )
        self.assertNotIn(secret, logged)
        self.assertNotIn("raw-secret-data", logged)
        self.assertIn("protocol=native", logged)
        self.assertIn(
            ("agent_function_decision protocol=native error_category=%s", "LLMError"),
            [call.args for call in logger.warning.call_args_list],
        )

    def test_double_failure_end_to_end_executes_only_final_message_persistence(self) -> None:
        tools = NativeWorkflowTools()
        llm = SwitchingDecisionLlm(
            [native_response("call-unknown", "unknown_tool", {})],
            [{"action": "tool_call", "tool_name": "lookup", "tool_arguments": {"unknown": True}}],
        )
        agent = LangGraphAfterSalesAgent(tools=tools, llm=llm)

        result = agent.handle({"user_id": "trusted-user", "session_id": 501, "message": "帮助"})

        self.assertEqual(1, llm.native_calls)
        self.assertEqual(1, llm.legacy_calls)
        self.assertEqual("fail_closed", result["raw"]["decision_protocol"])
        self.assertNotIn("lookup", tools.calls)
        self.assertEqual(["append_chat_message", "append_chat_message"], tools.calls)

    def test_native_and_legacy_failure_fail_closed_without_business_tool(self) -> None:
        malformed = native_response("call-bad", "unknown_tool", {})
        llm = SwitchingDecisionLlm([malformed], [LLMResponseParseError("malformed legacy response")])
        agent = LangGraphAfterSalesAgent(tools=NativeWorkflowTools(), llm=llm)
        state = self._state()

        agent.classify_or_plan(state)

        self.assertEqual(1, llm.native_calls)
        self.assertEqual(1, llm.legacy_calls)
        self.assertEqual("fail_closed", state["decision_protocol"])
        self.assertEqual("final_reply", state["next_action"])
        self.assertFalse(state["need_human"])

    def test_native_disabled_legacy_failure_fail_closed(self) -> None:
        llm = SwitchingDecisionLlm([], [LLMResponseParseError("malformed legacy response")])
        agent = LangGraphAfterSalesAgent(
            tools=NativeWorkflowTools(),
            llm=llm,
            native_function_calling_enabled=False,
        )
        state = self._state()

        agent.classify_or_plan(state)

        self.assertEqual(0, llm.native_calls)
        self.assertEqual(1, llm.legacy_calls)
        self.assertEqual("fail_closed", state["decision_protocol"])
        self.assertEqual("final_reply", state["next_action"])

    def test_terminal_ticket_failure_prefers_unconfirmed_human_handoff(self) -> None:
        llm = SwitchingDecisionLlm(
            [native_response("call-bad", "unknown_tool", {})],
            [LLMResponseParseError("malformed legacy response")],
        )
        agent = LangGraphAfterSalesAgent(tools=NativeWorkflowTools(), llm=llm)
        state = self._state()
        state["ticket_id"] = "trusted-ticket"
        guarded = {"action": "final_reply", "assistant_reply": "确定性回复", "need_human": False}

        action = agent._native_terminal_decision(state, guarded)

        self.assertEqual("fail_closed", state["decision_protocol"])
        self.assertEqual("human_handoff", action["action"])
        self.assertTrue(action["need_human"])
        self.assertNotIn("已完成", action["assistant_reply"])


class ControlledAgenticRagRetrievalTest(unittest.TestCase):
    class RewriteService:
        def __init__(
            self,
            decision: RagRewriteDecision | None = None,
            decisions: list[RagRewriteDecision] | None = None,
            error: Exception | None = None,
        ) -> None:
            self.decision = decision
            self.decisions = list(decisions or [])
            self.error = error
            self.calls: list[dict[str, object]] = []

        def evaluate(self, **kwargs: object) -> RagRewriteDecision:
            self.calls.append(kwargs)
            if self.error:
                raise self.error
            if self.decisions:
                return self.decisions.pop(0)
            assert self.decision is not None
            return self.decision

    @staticmethod
    def _ticket() -> dict[str, object]:
        return {
            "ticket_id": "TICKET-RAG-1",
            "ticket_no": "AS-RAG-1",
            "order_id": "ORDER-RAG-1",
            "product_name": "蓝牙降噪耳机",
            "product_category": "数码",
            "merchant_code": "MERCHANT_DEMO",
            "policy_version": "v2",
            "create_time": "2026-07-20T09:00:00+08:00",
            "status": "PENDING_REVIEW",
        }

    def _retrieval_state(self, result: dict[str, object]) -> dict[str, object]:
        arguments = {
            "user_id": "1",
            "query": "耳机声音异常 售后政策",
            "merchant_code": "MERCHANT_DEMO",
            "product_category": "数码",
            "scene": "quality_issue",
            "intent": "refund",
            "source_type": "after_sales_policy",
            "policy_version": "v2",
            "as_of_time": "2026-07-20T09:00:00+08:00",
            "top_k": 5,
        }
        return {
            "user_id": "1",
            "ticket_id": "TICKET-RAG-1",
            "order_id_hint": "ORDER-RAG-1",
            "message": "耳机声音异常",
            "steps": 1,
            "ticket": self._ticket(),
            "tool_name": "retrieve_knowledge",
            "tool_arguments": dict(arguments),
            "tool_results": [
                {
                    "tool": "get_after_sales_ticket",
                    "arguments": {"ticket_id": "TICKET-RAG-1"},
                    "ok": True,
                    "data": self._ticket(),
                },
                {
                    "tool": "retrieve_knowledge",
                    "arguments": dict(arguments),
                    "ok": True,
                    "data": result,
                },
            ],
            "retrieval_attempts": 0,
            "retrieval_query_count": 0,
            "retrieval_queries": [],
            "retrieval_assessment": {},
            "retrieval_rewrite_completed": False,
            "evidence_needed": [],
            "attachments": [],
        }

    def test_insufficient_result_uses_llm_candidates_and_preserves_filters(self) -> None:
        rewrite = self.RewriteService(
            RagRewriteDecision(
                sufficient=False,
                confidence=0.84,
                covered_aspects=("问题现象",),
                missing_aspects=("适用政策", "凭证要求"),
                queries=(
                    RagQueryCandidate("蓝牙耳机质量问题退款适用政策与排除条件", "适用政策"),
                    RagQueryCandidate("数码商品功能异常售后凭证与时效要求", "凭证要求"),
                ),
            )
        )
        agent = LangGraphAfterSalesAgent(
            tools=FakeTools(),
            llm=FakeLlm(),
            rag_rewrite_service=rewrite,  # type: ignore[arg-type]
        )
        state = self._retrieval_state(
            {
                "mode": "hybrid_reranked",
                "hits": [],
                "no_answer": True,
                "failure_reason": "NO_MATCH",
            }
        )
        original = dict(state["tool_arguments"])  # type: ignore[arg-type]

        agent.observe_tool_result(state)  # type: ignore[arg-type]
        agent.decide_next(state)  # type: ignore[arg-type]

        self.assertEqual("tool_call", state["next_action"])
        self.assertEqual("retrieve_knowledge_multi", state["tool_name"])
        rewritten = state["tool_arguments"]  # type: ignore[assignment]
        self.assertNotIn("query", rewritten)
        self.assertEqual(original["query"], rewritten["original_query"])
        self.assertEqual(
            [
                "蓝牙耳机质量问题退款适用政策与排除条件",
                "数码商品功能异常售后凭证与时效要求",
            ],
            rewritten["queries"],
        )
        for key in (
            "merchant_code",
            "product_category",
            "scene",
            "intent",
            "source_type",
            "policy_version",
            "as_of_time",
            "top_k",
        ):
            self.assertEqual(original.get(key), rewritten.get(key))
        self.assertEqual(1, len(rewrite.calls))
        self.assertFalse(rewrite.calls[0]["require_trusted_policy"])
        self.assertTrue(state["retrieval_rewrite_completed"])

    def test_kafka_review_retrieval_still_requires_trusted_policy(self) -> None:
        rewrite = self.RewriteService(
            RagRewriteDecision(
                sufficient=False,
                confidence=0.84,
                covered_aspects=("问题现象",),
                missing_aspects=("可信政策",),
                queries=(RagQueryCandidate("耳机声音异常是否适用质量售后政策？", "可信政策"),),
            )
        )
        agent = LangGraphAfterSalesAgent(
            tools=FakeTools(),
            llm=FakeLlm(),
            rag_rewrite_service=rewrite,  # type: ignore[arg-type]
        )
        state = self._retrieval_state(
            {
                "mode": "hybrid_reranked",
                "hits": [],
                "no_answer": True,
                "failure_reason": "NO_MATCH",
            }
        )
        state["allow_ai_review_submit"] = True

        agent.observe_tool_result(state)  # type: ignore[arg-type]
        agent.decide_next(state)  # type: ignore[arg-type]

        self.assertTrue(rewrite.calls[0]["require_trusted_policy"])

    def test_sufficient_result_does_not_execute_multi_query(self) -> None:
        rewrite = self.RewriteService(
            RagRewriteDecision(
                sufficient=True,
                confidence=0.95,
                covered_aspects=("适用政策", "凭证要求"),
                missing_aspects=(),
                queries=(),
            )
        )
        agent = LangGraphAfterSalesAgent(
            tools=FakeTools(),
            llm=FakeLlm(),
            rag_rewrite_service=rewrite,  # type: ignore[arg-type]
        )
        state = self._retrieval_state(
            {
                "mode": "hybrid_reranked",
                "hits": [{"source_type": "after_sales_policy"}],
                "no_answer": False,
            }
        )

        agent.observe_tool_result(state)  # type: ignore[arg-type]
        agent.decide_next(state)  # type: ignore[arg-type]

        self.assertNotEqual("retrieve_knowledge_multi", state.get("tool_name"))
        self.assertTrue(state["retrieval_assessment"]["sufficient"])  # type: ignore[index]
        self.assertEqual(1, len(rewrite.calls))

    def test_sufficient_label_below_confidence_floor_fails_closed(self) -> None:
        decision = RagRewriteDecision(
            sufficient=True,
            confidence=0.69,
            covered_aspects=("适用政策",),
            missing_aspects=(),
            queries=(),
        )

        with patch.dict("os.environ", {"RAG_SUFFICIENCY_MIN_CONFIDENCE": "0.70"}):
            self.assertFalse(
                LangGraphAfterSalesAgent._rag_decision_is_sufficient(decision)
            )

    def test_infrastructure_failure_does_not_call_rewrite_llm(self) -> None:
        rewrite = self.RewriteService(
            RagRewriteDecision(False, 0.5, (), ("知识不足",), (RagQueryCandidate("候选查询不能被调用", "测试"),))
        )
        agent = LangGraphAfterSalesAgent(
            tools=FakeTools(),
            llm=FakeLlm(),
            rag_rewrite_service=rewrite,  # type: ignore[arg-type]
        )
        state = self._retrieval_state(
            {
                "mode": "pgvector_error",
                "hits": [],
                "no_answer": True,
                "failure_reason": "PGVECTOR_ERROR",
            }
        )

        agent.observe_tool_result(state)  # type: ignore[arg-type]
        agent.decide_next(state)  # type: ignore[arg-type]

        self.assertNotEqual("retrieve_knowledge_multi", state.get("tool_name"))
        self.assertEqual(1, state["retrieval_attempts"])
        self.assertEqual(
            ["infrastructure_failure"],
            state["retrieval_assessment"]["reasons"],  # type: ignore[index]
        )
        self.assertEqual([], rewrite.calls)

    def test_rewrite_failure_does_not_use_fixed_fallback(self) -> None:
        rewrite = self.RewriteService(error=RagRewriteModelError("unavailable"))
        agent = LangGraphAfterSalesAgent(
            tools=FakeTools(),
            llm=FakeLlm(),
            rag_rewrite_service=rewrite,  # type: ignore[arg-type]
        )
        state = self._retrieval_state(
            {
                "mode": "hybrid_reranked",
                "hits": [],
                "no_answer": True,
                "failure_reason": "NO_MATCH",
            }
        )
        agent.observe_tool_result(state)  # type: ignore[arg-type]
        agent.decide_next(state)  # type: ignore[arg-type]

        self.assertNotEqual("retrieve_knowledge_multi", state.get("tool_name"))
        self.assertEqual(
            ["query_rewrite_error"],
            state["retrieval_assessment"]["reasons"],  # type: ignore[index]
        )
        self.assertTrue(state["retrieval_rewrite_completed"])

    def test_multi_result_is_reassessed_and_insufficient_result_hands_off(self) -> None:
        rewrite = self.RewriteService(
            RagRewriteDecision(
                False,
                0.6,
                (),
                ("政策覆盖",),
                (RagQueryCandidate("蓝牙耳机质量问题退款政策适用范围", "政策"),),
            )
        )
        agent = LangGraphAfterSalesAgent(
            tools=FakeTools(),
            llm=FakeLlm(),
            rag_rewrite_service=rewrite,  # type: ignore[arg-type]
        )
        state = self._retrieval_state(
            {"mode": "hybrid_reranked", "hits": [], "no_answer": True}
        )
        agent.observe_tool_result(state)  # type: ignore[arg-type]
        agent.decide_next(state)  # type: ignore[arg-type]
        multi_arguments = dict(state["tool_arguments"])  # type: ignore[arg-type]
        state["tool_results"].append(  # type: ignore[union-attr]
            {
                "tool": "retrieve_knowledge_multi",
                "arguments": multi_arguments,
                "ok": True,
                "data": {
                    "mode": "multi_query_reranked",
                    "hits": [{"source_type": "faq"}],
                    "no_answer": False,
                },
            }
        )
        state["steps"] = 2
        agent.observe_tool_result(state)  # type: ignore[arg-type]
        agent.decide_next(state)  # type: ignore[arg-type]

        self.assertEqual(2, len(rewrite.calls))
        self.assertNotEqual("retrieve_knowledge_multi", state.get("tool_name"))
        self.assertEqual(2, state["retrieval_attempts"])
        self.assertEqual(2, state["retrieval_query_count"])
        self.assertEqual("human_handoff", state["next_action"])
        self.assertTrue(state["need_human"])
        self.assertFalse(state["retrieval_assessment"]["sufficient"])  # type: ignore[index]
        self.assertTrue(state["retrieval_assessment"]["terminal"])  # type: ignore[index]
        self.assertEqual(
            ["post_rewrite_semantic_coverage_insufficient"],
            state["retrieval_assessment"]["reasons"],  # type: ignore[index]
        )

    def test_multi_result_is_reassessed_and_sufficient_result_continues(self) -> None:
        rewrite = self.RewriteService(
            decisions=[
                RagRewriteDecision(
                    False,
                    0.82,
                    ("问题现象",),
                    ("专项政策",),
                    (RagQueryCandidate("蓝牙耳机电流声质量售后专项规则", "专项政策"),),
                ),
                RagRewriteDecision(
                    True,
                    0.91,
                    ("问题现象", "专项政策", "凭证要求"),
                    (),
                    (),
                ),
            ]
        )
        agent = LangGraphAfterSalesAgent(
            tools=FakeTools(),
            llm=FakeLlm(),
            rag_rewrite_service=rewrite,  # type: ignore[arg-type]
        )
        state = self._retrieval_state(
            {"mode": "hybrid_reranked", "hits": [], "no_answer": True}
        )
        agent.observe_tool_result(state)  # type: ignore[arg-type]
        agent.decide_next(state)  # type: ignore[arg-type]
        multi_arguments = dict(state["tool_arguments"])  # type: ignore[arg-type]
        state["tool_results"].append(  # type: ignore[union-attr]
            {
                "tool": "retrieve_knowledge_multi",
                "arguments": multi_arguments,
                "ok": True,
                "data": {
                    "mode": "multi_query_reranked",
                    "hits": [{"source_type": "after_sales_policy"}],
                    "no_answer": False,
                    "filter_level": "strict",
                    "reranker_succeeded": True,
                },
            }
        )
        state["steps"] = 2

        agent.observe_tool_result(state)  # type: ignore[arg-type]
        agent.decide_next(state)  # type: ignore[arg-type]

        self.assertEqual(2, len(rewrite.calls))
        self.assertTrue(state["retrieval_assessment"]["sufficient"])  # type: ignore[index]
        self.assertFalse(state["retrieval_assessment"]["terminal"])  # type: ignore[index]
        self.assertNotEqual("human_handoff", state["next_action"])

    def test_best_knowledge_result_can_select_multi_query_result(self) -> None:
        agent = LangGraphAfterSalesAgent(tools=FakeTools(), llm=FakeLlm())
        state = self._retrieval_state(
            {
                "mode": "hybrid_reranked",
                "hits": [],
                "no_answer": True,
            }
        )
        state["tool_results"].append(  # type: ignore[union-attr]
            {
                "tool": "retrieve_knowledge_multi",
                "arguments": {"original_query": "耳机声音异常", "queries": ["质量问题退款政策"]},
                "ok": True,
                "data": {
                    "mode": "multi_query_reranked",
                "hits": [
                    {
                        "source_type": "after_sales_policy",
                            "source_code": "POLICY-MULTI",
                        "trusted_policy_eligible": True,
                        "relaxation_level": "strict",
                        "score": 0.95,
                        "threshold": 0.75,
                        "metadata": {
                            "merchant_code": "MERCHANT_DEMO",
                            "policy_version": "v2",
                            "valid_from": "2026-07-01T00:00:00+08:00",
                            "valid_to": "2026-08-01T00:00:00+08:00",
                        },
                    }
                ],
                "no_answer": False,
                "filter_level": "strict",
                "relaxation_level": "strict",
                "reranker_succeeded": True,
                "trusted_policy_eligible": True,
                },
            }
        )

        best = agent._best_knowledge_result(  # type: ignore[attr-defined]
            state,  # type: ignore[arg-type]
            self._ticket(),
        )

        self.assertEqual("POLICY-MULTI", best["hits"][0]["source_code"])

    def test_rag_product_category_normalizes_catalog_categories_and_subtypes(self) -> None:
        self.assertEqual(
            "headphone",
            LangGraphAfterSalesAgent._rag_product_category(
                {"category": "数码", "product_name": "蓝牙降噪耳机"}
            ),
        )
        self.assertEqual(
            "phone",
            LangGraphAfterSalesAgent._rag_product_category(
                {"category": "数码", "product_name": "手机"}
            ),
        )
        self.assertEqual(
            "apparel",
            LangGraphAfterSalesAgent._rag_product_category(
                {"category": "服装", "product_name": "纯棉圆领T恤"}
            ),
        )
        self.assertEqual(
            "daily",
            LangGraphAfterSalesAgent._rag_product_category(
                {"category": "日用", "product_name": "相纸"}
            ),
        )
        self.assertEqual(
            "food",
            LangGraphAfterSalesAgent._rag_product_category(
                {"category": "食品", "product_name": "蛋白粉"}
            ),
        )

    def test_rag_query_expansion_uses_scene_terms_without_cross_category_noise(self) -> None:
        quality_expansion = LangGraphAfterSalesAgent._rag_query_expansion("QUALITY", "RETURN_REFUND")

        self.assertIn("质量问题", quality_expansion)
        self.assertIn("问题现象", quality_expansion)
        self.assertIn("退货退款", quality_expansion)
        self.assertNotIn("电流声", quality_expansion)
        self.assertNotIn("异响", quality_expansion)
        self.assertNotIn("外壳破裂", quality_expansion)


if __name__ == "__main__":
    unittest.main()
