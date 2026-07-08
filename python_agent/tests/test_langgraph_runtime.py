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


if __name__ == "__main__":
    unittest.main()
