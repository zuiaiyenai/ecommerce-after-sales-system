from __future__ import annotations

import unittest
from unittest.mock import patch

from after_sales_agent.application.after_sales_workflow import LangGraphAfterSalesAgent
from after_sales_agent.application.tool_registry import ToolResult
from after_sales_agent.api.http_server import build_attachments

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


class FakeTools:
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
        return []

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
        return []

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
        self.assertEqual("数码", arguments["product_category"])
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


if __name__ == "__main__":
    unittest.main()
