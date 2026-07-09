from __future__ import annotations

import importlib.util
import pathlib
import sys
import types
import unittest


RUNTIME_PATH = pathlib.Path(__file__).resolve().parents[1] / "after_sales_agent" / "langgraph_runtime.py"


def load_runtime_module():
    package = types.ModuleType("after_sales_agent")
    package.__path__ = [str(RUNTIME_PATH.parent)]
    sys.modules.setdefault("after_sales_agent", package)

    langgraph = types.ModuleType("langgraph")
    langgraph_graph = types.ModuleType("langgraph.graph")

    END = "__END__"

    class CompiledGraph:
        def __init__(self, nodes, entry_point, edges, conditional_edges) -> None:
            self.nodes = nodes
            self.entry_point = entry_point
            self.edges = edges
            self.conditional_edges = conditional_edges

        def invoke(self, state):
            current = self.entry_point
            while current != END:
                state = self.nodes[current](state)
                if current in self.conditional_edges:
                    router, mapping = self.conditional_edges[current]
                    current = mapping[router(state)]
                else:
                    current = self.edges[current]
            return state

    class StateGraph:
        def __init__(self, _state_type) -> None:
            self.nodes = {}
            self.entry_point = None
            self.edges = {}
            self.conditional_edges = {}

        def add_node(self, name, fn) -> None:
            self.nodes[name] = fn

        def set_entry_point(self, name) -> None:
            self.entry_point = name

        def add_edge(self, start, end) -> None:
            self.edges[start] = end

        def add_conditional_edges(self, start, router, mapping) -> None:
            self.conditional_edges[start] = (router, mapping)

        def compile(self):
            return CompiledGraph(self.nodes, self.entry_point, self.edges, self.conditional_edges)

    langgraph_graph.END = END
    langgraph_graph.StateGraph = StateGraph
    sys.modules["langgraph"] = langgraph
    sys.modules["langgraph.graph"] = langgraph_graph

    agent_tools = types.ModuleType("after_sales_agent.agent_tools")

    class ToolResult:
        def __init__(self, ok: bool, name: str, data=None, error: str | None = None) -> None:
            self.ok = ok
            self.name = name
            self.data = data
            self.error = error

    class AfterSalesTools:
        def tool_specs(self) -> list[dict[str, object]]:
            return []

        def call(self, name: str, arguments: dict[str, object]) -> ToolResult:
            raise NotImplementedError

    agent_tools.ToolResult = ToolResult
    agent_tools.AfterSalesTools = AfterSalesTools
    sys.modules["after_sales_agent.agent_tools"] = agent_tools

    llm_module = types.ModuleType("after_sales_agent.services.llm")

    class OpenAICompatibleConfig:
        @staticmethod
        def from_env() -> "OpenAICompatibleConfig":
            return OpenAICompatibleConfig()

    class OpenAICompatibleClient:
        def __init__(self, *_: object, **__: object) -> None:
            pass

    llm_module.OpenAICompatibleClient = OpenAICompatibleClient
    llm_module.OpenAICompatibleConfig = OpenAICompatibleConfig
    sys.modules["after_sales_agent.services.llm"] = llm_module

    spec = importlib.util.spec_from_file_location("after_sales_agent.langgraph_runtime", RUNTIME_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["after_sales_agent.langgraph_runtime"] = module
    spec.loader.exec_module(module)
    return module, ToolResult


runtime_module, ToolResult = load_runtime_module()
LangGraphAfterSalesAgent = runtime_module.LangGraphAfterSalesAgent


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
                        "orderNo": "ORD1783516556124",
                        "productName": "蛋白粉(巧克力味)",
                        "productCategory": "食品",
                        "merchantCode": "MERCHANT_DEMO",
                        "existingTicketNo": "AS1783516664614",
                        "afterSalesStatus": "PENDING_REVIEW",
                    }
                ],
            )
        if name == "handoff_to_human":
            return ToolResult(ok=True, name=name, data={"sessionMode": "HUMAN"})
        if name == "append_chat_message":
            return ToolResult(ok=True, name=name, data={"sessionId": 123})
        return ToolResult(ok=False, name=name, error=f"unexpected tool call: {name}")


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
                        "orderNo": "ORD1783562416783",
                        "productName": "蓝牙降噪耳机",
                        "productCategory": "数码",
                        "merchantCode": "MERCHANT_DEMO",
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
        if name == "create_after_sales_ticket":
            return ToolResult(
                ok=True,
                name=name,
                data={
                    "ticketNo": "AS1783562492249",
                    "ticket_id": "AS1783562492249",
                    "status": "PENDING_REVIEW",
                },
            )
        if name == "handoff_to_human":
            return ToolResult(ok=True, name=name, data={"sessionMode": "HUMAN"})
        if name == "append_chat_message":
            return ToolResult(ok=True, name=name, data={"sessionId": 456})
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
                        "orderNo": "ORD1783564088864",
                        "productName": "蓝牙降噪耳机",
                        "productCategory": "数码",
                        "merchantCode": "MERCHANT_DEMO",
                        "existingTicketNo": "AS1783564161927",
                        "afterSalesStatus": "PENDING_REVIEW",
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
        if name == "handoff_to_human":
            return ToolResult(ok=True, name=name, data={"sessionMode": "HUMAN"})
        if name == "append_chat_message":
            return ToolResult(ok=True, name=name, data={"sessionId": 789})
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
                        "orderNo": "ORD1783595519525",
                        "productName": "蓝牙降噪耳机",
                        "productCategory": "数码",
                        "merchantCode": "MERCHANT_DEMO",
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
                    "missing_visual_evidence": ["外包装照片", "物流面单照片"],
                    "summary": "图片可见耳机外壳破裂",
                },
            )
        if name == "retrieve_knowledge":
            return ToolResult(
                ok=True,
                name=name,
                data={
                    "mode": "pgvector",
                    "hits": [
                        {
                            "title": "数码商品破损售后规则",
                            "snippet": "商品破损需要提供商品问题照片和问题描述，图片清晰可见破损即可进入审核。",
                            "metadata": {"default_evidence": ["商品问题照片", "问题描述"]},
                        }
                    ],
                },
            )
        if name == "create_after_sales_ticket":
            self.create_arguments = arguments
            return ToolResult(
                ok=True,
                name=name,
                data={
                    "ticketNo": "AS1783595588024",
                    "ticket_id": "AS1783595588024",
                    "status": "PROCESSING" if arguments.get("auto_approved") else "PENDING_REVIEW",
                },
            )
        if name == "append_chat_message":
            return ToolResult(ok=True, name=name, data={"sessionId": 999})
        return ToolResult(ok=False, name=name, error=f"unexpected tool call: {name}")


class LangGraphHumanHandoffTest(unittest.TestCase):
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
        self.assertIn("AS1783516664614", result["assistant_reply"])
        self.assertIn("handoff_to_human", result["tool_trace"][-3]["tool"])
        self.assertNotIn("retrieve_knowledge", tools.calls)

    def test_uploaded_image_and_description_handoff_when_image_cannot_verify_claim(self) -> None:
        tools = FakeUnverifiableImageTools()
        agent = LangGraphAfterSalesAgent(tools=tools, llm=FakeLlm())

        result = agent.handle(
            {
                "user_id": "1",
                "session_id": 456,
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
        self.assertIn("retrieve_knowledge", tools.calls)
        self.assertIn("create_after_sales_ticket", tools.calls)
        self.assertIn("handoff_to_human", tools.calls)
        self.assertLess(tools.calls.index("create_after_sales_ticket"), tools.calls.index("handoff_to_human"))

    def test_existing_ticket_with_uploaded_image_runs_visual_review_before_reply(self) -> None:
        tools = FakeExistingTicketImageTools()
        agent = LangGraphAfterSalesAgent(tools=tools, llm=FakeLlm())

        result = agent.handle(
            {
                "user_id": "1",
                "session_id": 789,
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
        self.assertIn("retrieve_knowledge", tools.calls)
        self.assertIn("handoff_to_human", tools.calls)
        self.assertNotIn("create_after_sales_ticket", tools.calls)

    def test_damage_image_and_description_satisfy_evidence_and_auto_approve(self) -> None:
        tools = FakeDamageImageTools()
        agent = LangGraphAfterSalesAgent(tools=tools, llm=FakeLlm())

        result = agent.handle(
            {
                "user_id": "1",
                "session_id": 999,
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
        self.assertIn("create_after_sales_ticket", tools.calls)
        self.assertIsNotNone(tools.create_arguments)
        self.assertTrue(tools.create_arguments["auto_approved"])
        classify = tools.create_arguments["ai_classify_result"]
        self.assertEqual([], classify["evidence_needed"])
        self.assertEqual("AI_RECOMMEND_APPROVE", classify["verdict"])


if __name__ == "__main__":
    unittest.main()
