from __future__ import annotations

from dataclasses import dataclass, field
from contextlib import nullcontext
import json
from typing import Any, Protocol

from ...application.rag_query_rewrite import RagQueryRewriteService, RagRewriteError
from ...application.rag_retrieval_policy import RagRetrievalPolicy
from ...tools import AgentToolRegistry, ToolResult
from ...infrastructure.request_tracing import TraceRecorder, bind_trace_id
from ...providers.llm_client import get_llm_client
from ..skill_registry import AgentSkill, AgentSkillRegistry


class ChatLlm(Protocol):
    def generate_structured(self, *, system_prompt: str, user_prompt: str, schema: dict[str, Any], **kwargs: Any) -> dict[str, Any]: ...


class ChatTools(Protocol):
    def call(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        ...


class ChatRagRewrite(Protocol):
    def evaluate(self, **kwargs: Any) -> Any:
        ...


@dataclass
class ConsultationWorkflow:
    """Answer policy consultations from trusted RAG evidence or hand off."""

    tools: ChatTools = field(default_factory=AgentToolRegistry)
    llm: ChatLlm = field(default_factory=get_llm_client)
    skills: AgentSkillRegistry = field(default_factory=AgentSkillRegistry)
    rag_rewrite_service: ChatRagRewrite | None = None

    def __post_init__(self) -> None:
        if self.rag_rewrite_service is None:
            self.rag_rewrite_service = RagQueryRewriteService(llm=self.llm)

    def handle(
        self,
        payload: dict[str, Any],
        trace_recorder: Any | None = None,
    ) -> dict[str, Any]:
        trace = trace_recorder if isinstance(trace_recorder, TraceRecorder) else None
        bind_llm = getattr(self.llm, "bind_trace", None)
        if callable(bind_llm):
            bind_llm(trace)
        try:
            with bind_trace_id(trace.trace_id if trace else None):
                return self._handle_core(payload, trace)
        finally:
            if callable(bind_llm):
                bind_llm(None)

    def _handle_core(
        self,
        payload: dict[str, Any],
        trace_recorder: TraceRecorder | None,
    ) -> dict[str, Any]:
        message = str(payload.get("message") or "").strip()
        with self._trace_step(
            trace_recorder,
            "chat_validate_input",
            has_message=bool(message),
            has_session=bool(payload.get("session_id")),
            has_order=bool(payload.get("order_id")),
        ):
            if not message:
                return self._result(
                    reply="请描述您需要咨询的售后政策问题。",
                    session_mode="AI",
                    need_human=False,
                    trace=[],
                    raw={"handoff_reason": None},
                    payload=payload,
                )

        if self._explicit_human_request(message):
            with self._trace_step(
                trace_recorder,
                "chat_explicit_handoff",
                reason="explicit_human_request",
            ):
                return self._handoff(
                    payload,
                    [],
                    "explicit_human_request",
                    trace_recorder,
                )

        context = (
            payload.get("client_context")
            if isinstance(payload.get("client_context"), dict)
            else {}
        )
        order = (
            context.get("selected_order_hint")
            if isinstance(context.get("selected_order_hint"), dict)
            else {}
        )
        retrieval_arguments = {
            "user_id": str(payload.get("user_id") or ""),
            "query": message,
            "merchant_code": order.get("merchant_code") or context.get("merchant_code"),
            "product_category": (
                order.get("category")
                or order.get("product_category")
                or context.get("product_category")
            ),
            "source_type": "after_sales_policy",
            "policy_version": order.get("policy_version") or context.get("policy_version"),
            "as_of_time": order.get("business_time") or context.get("business_time"),
            "top_k": 5,
        }
        with self._trace_step(
            trace_recorder,
            "rag_retrieve_initial",
            retrieval_type="single_query",
        ) as trace_step:
            retrieval = self.tools.call(
                "retrieve_knowledge",
                retrieval_arguments,
            )
            trace_step.details.update(
                {
                    "ok": retrieval.ok,
                    "error_category": retrieval.error_category,
                }
            )
        tool_trace = [self._trace_entry(retrieval, retrieval_arguments)]
        knowledge = retrieval.data if retrieval.ok and isinstance(retrieval.data, dict) else {}
        with self._trace_step(
            trace_recorder,
            "rag_assess_initial",
            retrieval_mode=knowledge.get("mode"),
        ) as trace_step:
            trusted_hits = self._trusted_hits(knowledge)
            trace_step.details["trusted_hit_count"] = len(trusted_hits)
        if (
            not trusted_hits
            and retrieval.ok
            and not RagRetrievalPolicy().is_infrastructure_failure(knowledge)
        ):
            knowledge, trusted_hits, rewrite_trace = self._rewrite_and_retrieve(
                payload,
                retrieval_arguments,
                knowledge,
                trace_recorder,
            )
            tool_trace.extend(rewrite_trace)
        if not trusted_hits:
            reason = (
                retrieval.error_category or "knowledge_service_failed"
                if not retrieval.ok
                else "knowledge_not_trusted"
            )
            return self._handoff(
                payload,
                tool_trace,
                reason,
                trace_recorder,
            )

        citations = self._citations(trusted_hits)
        with self._trace_step(
            trace_recorder,
            "chat_generate_answer",
            retrieval_mode=knowledge.get("mode"),
            trusted_hit_count=len(trusted_hits),
            citation_count=len(citations),
        ):
            policy_skill = self._require_skill("policy_explanation")
            reply = self._generate_answer(
                payload,
                knowledge,
                trusted_hits,
                policy_skill,
            )
        append_arguments = {
            "user_id": payload.get("user_id"),
            "session_id": payload.get("session_id"),
            "order_id": payload.get("order_id"),
            "ticket_id": payload.get("ticket_id"),
            "role": "ASSISTANT",
            "content": reply,
            "message_type": "TEXT",
            "knowledge_query": message,
            "knowledge_retrieval_mode": knowledge.get("mode"),
            "knowledge_hit_count": len(trusted_hits),
            "knowledge_hits_json": json.dumps(
                trusted_hits[:5], ensure_ascii=False, default=str
            ),
            "knowledge_trace_json": json.dumps(
                {"citations": citations}, ensure_ascii=False, default=str
            ),
        }
        with self._trace_step(
            trace_recorder,
            "java_append_chat_message",
        ) as trace_step:
            persisted = self.tools.call(
                "append_chat_message",
                append_arguments,
            )
            trace_step.details.update(
                {
                    "ok": persisted.ok,
                    "error_category": persisted.error_category,
                }
            )
        tool_trace.append(self._trace_entry(persisted, append_arguments))
        if not persisted.ok:
            return self._handoff(
                payload,
                tool_trace,
                "answer_persistence_failed",
                trace_recorder,
            )

        return self._result(
            reply=reply,
            session_mode="AI",
            need_human=False,
            trace=tool_trace,
            raw={
                "knowledge_mode": knowledge.get("mode"),
                "knowledge_hit_count": len(trusted_hits),
                "policy_citations": citations,
                "skill_versions": {policy_skill.name: policy_skill.version},
                "handoff_reason": None,
            },
            payload=payload,
            persistence=persisted.data if isinstance(persisted.data, dict) else None,
        )

    def _rewrite_and_retrieve(
        self,
        payload: dict[str, Any],
        retrieval_arguments: dict[str, Any],
        knowledge: dict[str, Any],
        trace_recorder: TraceRecorder | None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        if self.rag_rewrite_service is None:
            return knowledge, [], []
        context = (
            payload.get("client_context")
            if isinstance(payload.get("client_context"), dict)
            else {}
        )
        order = (
            context.get("selected_order_hint")
            if isinstance(context.get("selected_order_hint"), dict)
            else {}
        )
        try:
            with self._trace_step(
                trace_recorder,
                "rag_query_rewrite",
                previous_mode=knowledge.get("mode"),
            ) as trace_step:
                decision = self.rag_rewrite_service.evaluate(
                    user_question=str(payload.get("message") or ""),
                    task="回答售后政策咨询；知识不足时转人工，不作业务审核决定。",
                    known_facts={
                        "product_name": order.get("product_name"),
                        "product_category": (
                            order.get("category") or order.get("product_category")
                        ),
                        "after_sales_type": order.get("after_sales_type"),
                    },
                    original_query=str(retrieval_arguments.get("query") or ""),
                    previous_queries=[],
                    require_trusted_policy=True,
                    retrieval_result=knowledge,
                    allow_rewrite=True,
                )
                trace_step.details.update(
                    {
                        "sufficient": bool(decision.sufficient),
                        "candidate_count": len(decision.queries),
                    }
                )
        except RagRewriteError:
            return knowledge, [], []
        queries = [
            str(item.query)
            for item in getattr(decision, "queries", ())
            if str(getattr(item, "query", "")).strip()
        ]
        if not queries:
            return knowledge, [], []
        multi_arguments = {
            key: value
            for key, value in retrieval_arguments.items()
            if key != "query"
        }
        multi_arguments.update(
            {
                "original_query": retrieval_arguments.get("query"),
                "queries": queries[:3],
            }
        )
        with self._trace_step(
            trace_recorder,
            "rag_retrieve_multi",
            query_count=len(queries[:3]),
        ) as trace_step:
            result = self.tools.call(
                "retrieve_knowledge_multi",
                multi_arguments,
            )
            trace_step.details.update(
                {
                    "ok": result.ok,
                    "error_category": result.error_category,
                }
            )
        tool_trace = [self._trace_entry(result, multi_arguments)]
        rewritten = (
            result.data
            if result.ok and isinstance(result.data, dict)
            else knowledge
        )
        with self._trace_step(
            trace_recorder,
            "rag_assess_rewritten",
            retrieval_mode=rewritten.get("mode"),
        ) as trace_step:
            trusted_hits = self._trusted_hits(rewritten)
            trace_step.details["trusted_hit_count"] = len(trusted_hits)
        return rewritten, trusted_hits, tool_trace

    def _generate_answer(
        self,
        payload: dict[str, Any],
        knowledge: dict[str, Any],
        hits: list[dict[str, Any]],
        skill: AgentSkill,
    ) -> str:
        raw = self.llm.generate_structured(
            system_prompt=(
                "你是售后政策咨询助手。只能依据提供的可信知识回答，"
                "不得承诺退款、退货、换货或审核已经通过。"
                "只输出 JSON：assistant_reply。\n"
                f"Active skill ({skill.name}@{skill.version}):\n"
                f"{skill.instructions}"
            ),
            user_prompt=json.dumps(
                {
                    "question": payload.get("message"),
                    "recent_history": list(payload.get("recent_history") or [])[-10:],
                    "knowledge_mode": knowledge.get("mode"),
                    "trusted_hits": hits[:5],
                },
                ensure_ascii=False,
                default=str,
            ),
            schema={"type": "object", "required": ["assistant_reply"], "properties": {"assistant_reply": {"type": "string", "minLength": 1}}, "additionalProperties": False},
            temperature=0.1,
            max_tokens=500,
        )
        reply = str(raw.get("assistant_reply") or "").strip()
        return reply or "已查询到相关售后政策，建议您按照政策要求准备对应的订单信息和问题凭证。"

    def _require_skill(self, stage: str) -> AgentSkill:
        skill = self.skills.select(stage)
        if skill is None:
            raise RuntimeError(f"required consultation skill is missing: {stage}")
        return skill

    def _handoff(
        self,
        payload: dict[str, Any],
        trace: list[dict[str, Any]],
        reason: str,
        trace_recorder: TraceRecorder | None,
    ) -> dict[str, Any]:
        handoff_skill = self._require_skill("human_handoff")
        reply = "当前知识库无法可靠回答该问题，已为您转接人工客服继续核对。"
        summary = "\n".join(
            (
                f"用户诉求：{str(payload.get('message') or '售后问题核对').strip()}",
                "已核实：自动知识检索未形成可直接回答的可信结论。",
                "待核实：适用政策、订单事实及后续处理方案。",
                f"转人工原因：{reason}",
                "建议下一步：人工客服结合订单和有效政策继续核对。",
            )
        )
        arguments = {
            "user_id": payload.get("user_id"),
            "session_id": payload.get("session_id"),
            "order_id": payload.get("order_id"),
            "ticket_id": payload.get("ticket_id"),
            "summary": summary,
        }
        with self._trace_step(
            trace_recorder,
            "java_handoff_to_human",
            reason=reason,
        ) as trace_step:
            result = self.tools.call("handoff_to_human", arguments)
            trace_step.details.update(
                {
                    "ok": result.ok,
                    "error_category": result.error_category,
                }
            )
        trace.append(self._trace_entry(result, arguments))
        confirmed = bool(
            result.ok
            and isinstance(result.data, dict)
            and str(result.data.get("mode") or "").upper() == "HUMAN"
        )
        if not confirmed:
            reply = "当前问题需要人工进一步核对，但人工转接暂未确认成功，请稍后重试。"
        return self._result(
            reply=reply,
            session_mode="HUMAN" if confirmed else "AI",
            need_human=True,
            trace=trace,
            raw={
                "knowledge_mode": None,
                "knowledge_hit_count": 0,
                "policy_citations": [],
                "handoff_reason": reason,
                "handoff_succeeded": confirmed,
                "skill_versions": {
                    handoff_skill.name: handoff_skill.version
                },
            },
            payload=payload,
            persistence=result.data if isinstance(result.data, dict) else None,
        )

    @staticmethod
    def _trusted_hits(knowledge: dict[str, Any]) -> list[dict[str, Any]]:
        if (
            knowledge.get("trusted_policy_eligible") is not True
            or str(knowledge.get("filter_level") or "") != "strict"
            or (
                knowledge.get("reranker_succeeded") is not True
                and str(knowledge.get("mode") or "") != "multi_query_rrf"
            )
            or str(knowledge.get("mode") or "")
            not in {
                "hybrid_reranked",
                "pgvector",
                "multi_query_reranked",
                "multi_query_rrf",
            }
        ):
            return []
        return [
            dict(hit)
            for hit in knowledge.get("hits") or []
            if isinstance(hit, dict)
            and str(hit.get("source_type") or "") == "after_sales_policy"
            and hit.get("trusted_policy_eligible") is True
            and str(hit.get("relaxation_level") or "") == "strict"
            and ConsultationWorkflow._citations([hit])
        ]

    @staticmethod
    def _citations(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
        citations: list[dict[str, Any]] = []
        for hit in hits:
            for item in hit.get("citations") or []:
                if (
                    isinstance(item, dict)
                    and str(item.get("source_code") or "").strip()
                    and str(item.get("chunk_id") or item.get("document_id") or "").strip()
                ):
                    normalized = dict(item)
                    if normalized not in citations:
                        citations.append(normalized)
        return citations

    @staticmethod
    def _explicit_human_request(message: str) -> bool:
        return any(
            keyword in message
            for keyword in ("转人工", "人工客服", "真人客服", "联系客服")
        )

    @staticmethod
    def _trace_entry(
        result: ToolResult,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "tool": result.name,
            "arguments": arguments,
            "ok": result.ok,
            "data": result.data,
            "error": result.error,
            "error_code": result.error_code,
            "error_category": result.error_category,
            "retryable": result.retryable,
        }

    @staticmethod
    def _trace_step(
        trace_recorder: TraceRecorder | None,
        name: str,
        **details: Any,
    ):
        return (
            trace_recorder.step(name, **details)
            if trace_recorder is not None
            else nullcontext(type("TraceDetails", (), {"details": {}})())
        )

    @staticmethod
    def _result(
        *,
        reply: str,
        session_mode: str,
        need_human: bool,
        trace: list[dict[str, Any]],
        raw: dict[str, Any],
        payload: dict[str, Any],
        persistence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        persisted = persistence or {}
        session_id = persisted.get("session_id") or persisted.get("sessionId")
        return {
            "assistant_reply": reply,
            "session_mode": session_mode,
            "tool_trace": trace,
            "ticket": None,
            "review_result": None,
            "need_human": need_human,
            "evidence_needed": [],
            "persistence": {
                "session_id": (
                    str(session_id)
                    if session_id is not None
                    else str(payload.get("session_id") or "") or None
                ),
                "ticket_no": None,
            },
            "raw": {"runtime": "agentic_rag_chat", **raw},
        }
