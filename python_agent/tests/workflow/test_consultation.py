from __future__ import annotations

from after_sales_agent.agent.workflows.consultation import ConsultationWorkflow
from after_sales_agent.application.rag_query_rewrite import (
    RagQueryCandidate,
    RagRewriteDecision,
)
from after_sales_agent.tools import ToolResult
from after_sales_agent.infrastructure.request_tracing import (
    TraceRecorder,
    current_trace_id,
)


class ChatLlm:
    def __init__(self) -> None:
        self.system_prompts: list[str] = []

    def chat_json(self, **kwargs):
        return {"assistant_reply": "根据当前售后政策，商品质量问题需要提供可核验的问题凭证。"}

    def generate_structured(self, *, system_prompt, user_prompt, schema, **kwargs):
        self.system_prompts.append(system_prompt)
        return {"assistant_reply": "根据当前售后政策，商品质量问题需要提供可核验的问题凭证。"}


class ChatTools:
    def __init__(self, *, trusted: bool) -> None:
        self.trusted = trusted
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.trace_ids: list[str | None] = []

    def call(self, name: str, arguments: dict[str, object]) -> ToolResult:
        self.trace_ids.append(current_trace_id())
        self.calls.append((name, dict(arguments)))
        if name == "retrieve_knowledge":
            return ToolResult(
                ok=True,
                name=name,
                data={
                    "mode": "hybrid_reranked",
                    "filter_level": "strict",
                    "reranker_succeeded": True,
                    "trusted_policy_eligible": self.trusted,
                    "hits": (
                        [
                            {
                                "source_type": "after_sales_policy",
                                "trusted_policy_eligible": True,
                                "relaxation_level": "strict",
                                "rerank_score": 0.92,
                                "snippet": "质量问题应提交可核验的问题凭证。",
                                "citations": [
                                    {
                                        "source_code": "POLICY-001",
                                        "chunk_id": "chunk-001",
                                    }
                                ],
                            }
                        ]
                        if self.trusted
                        else []
                    ),
                },
            )
        if name == "append_chat_message":
            return ToolResult(
                ok=True,
                name=name,
                data={"message_id": "90071992547409931", "session_id": "12"},
            )
        if name == "handoff_to_human":
            return ToolResult(
                ok=True,
                name=name,
                data={"session_id": "12", "mode": "HUMAN", "status": "WAITING"},
            )
        raise AssertionError(f"unexpected tool: {name}")


def payload() -> dict[str, object]:
    return {
        "user_id": "7",
        "session_id": "12",
        "order_id": "99",
        "message": "耳机出现功能异常，售后需要什么凭证？",
        "client_context": {
            "source": "java_gateway",
            "selected_order_hint": {
                "merchant_code": "MERCHANT_DEMO",
                "category": "headphone",
                "policy_version": "v2",
            },
        },
    }


def test_trusted_rag_answer_is_persisted_through_java() -> None:
    tools = ChatTools(trusted=True)
    llm = ChatLlm()
    service = ConsultationWorkflow(tools=tools, llm=llm)
    trace = TraceRecorder(
        "chat",
        trace_id="0123456789abcdef0123456789abcdef",
    )

    result = service.handle(payload(), trace)

    assert result["raw"]["runtime"] == "agentic_rag_chat"
    assert result["need_human"] is False
    assert result["session_mode"] == "AI"
    assert [name for name, _ in tools.calls] == [
        "retrieve_knowledge",
        "append_chat_message",
    ]
    append_arguments = tools.calls[-1][1]
    assert append_arguments["role"] == "ASSISTANT"
    assert append_arguments["knowledge_retrieval_mode"] == "hybrid_reranked"
    assert result["raw"]["policy_citations"][0]["chunk_id"] == "chunk-001"
    assert set(result["raw"]["skill_versions"]) == {"policy-consultation"}
    assert "Active skill (policy-consultation@" in llm.system_prompts[-1]
    assert "只有通过运行时政策 Gate" in llm.system_prompts[-1]
    assert tools.trace_ids == [trace.trace_id, trace.trace_id]
    assert [step["name"] for step in trace.to_dict()["steps"]] == [
        "chat_validate_input",
        "rag_retrieve_initial",
        "rag_assess_initial",
        "chat_generate_answer",
        "java_append_chat_message",
    ]
    assert all(
        step["status"] == "SUCCESS"
        for step in trace.to_dict()["steps"]
    )


def test_untrusted_rag_result_hands_off_through_java() -> None:
    tools = ChatTools(trusted=False)
    service = ConsultationWorkflow(tools=tools, llm=ChatLlm())

    result = service.handle(payload())

    assert result["need_human"] is True
    assert result["session_mode"] == "HUMAN"
    assert [name for name, _ in tools.calls] == [
        "retrieve_knowledge",
        "handoff_to_human",
    ]
    assert result["raw"]["handoff_reason"] == "knowledge_not_trusted"
    assert set(result["raw"]["skill_versions"]) == {"human-handoff"}
    handoff_arguments = tools.calls[-1][1]
    assert "用户诉求：" in handoff_arguments["summary"]
    assert "建议下一步：" in handoff_arguments["summary"]


def test_agentic_rag_rewrites_once_and_uses_trusted_multi_query_result() -> None:
    class Rewrite:
        def evaluate(self, **kwargs):
            return RagRewriteDecision(
                sufficient=False,
                confidence=0.82,
                covered_aspects=("问题现象",),
                missing_aspects=("适用政策",),
                queries=(
                    RagQueryCandidate(
                        query="蓝牙耳机功能异常售后政策与凭证要求",
                        focus="适用政策",
                    ),
                ),
            )

    class RewriteTools(ChatTools):
        def __init__(self) -> None:
            super().__init__(trusted=False)

        def call(self, name, arguments):
            if name == "retrieve_knowledge_multi":
                self.calls.append((name, dict(arguments)))
                return ToolResult(
                    ok=True,
                    name=name,
                    data={
                        "mode": "multi_query_reranked",
                        "filter_level": "strict",
                        "reranker_succeeded": True,
                        "trusted_policy_eligible": True,
                        "hits": [
                            {
                                "source_type": "after_sales_policy",
                                "trusted_policy_eligible": True,
                                "relaxation_level": "strict",
                                "rerank_score": 0.9,
                                "snippet": "功能异常需要提供问题凭证。",
                                "citations": [
                                    {
                                        "source_code": "POLICY-002",
                                        "chunk_id": "chunk-002",
                                    }
                                ],
                            }
                        ],
                    },
                )
            return super().call(name, arguments)

    tools = RewriteTools()
    service = ConsultationWorkflow(
        tools=tools,
        llm=ChatLlm(),
        rag_rewrite_service=Rewrite(),
    )

    result = service.handle(payload())

    assert result["need_human"] is False
    assert [name for name, _ in tools.calls] == [
        "retrieve_knowledge",
        "retrieve_knowledge_multi",
        "append_chat_message",
    ]
    assert result["raw"]["knowledge_mode"] == "multi_query_reranked"
