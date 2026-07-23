from __future__ import annotations

from dataclasses import dataclass, field
from contextvars import ContextVar
import base64
from datetime import datetime
import hashlib
import json
import logging
import os
import re
from typing import Any, ClassVar, Literal, Optional, TypedDict, TYPE_CHECKING

from langgraph.graph import END, StateGraph

from .function_calling import FunctionCallingAdapter, FunctionCallingProtocolError
from .skill_registry import AgentSkillRegistry
from .tool_registry import AgentToolRegistry
from ..infra.request_tracing import bind_trace_id
from ..infra.agent_metrics import AGENT_RUNTIME_METRICS
from ..providers.llm_client import OpenAICompatibleClient, get_llm_client
from ..providers.resilient_llm_runtime import LLMError

if TYPE_CHECKING:
    from ..infra.request_tracing import TraceRecorder

logger = logging.getLogger("after_sales_agent.langgraph")


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


class AgentGraphState(TypedDict, total=False):
    user_id: str
    session_id: Optional[int]
    ticket_id: Optional[str]
    review_request_id: Optional[str]
    message: str
    attachments: list[dict[str, Any]]
    order_id_hint: Optional[str]
    recent_history: list[dict[str, str]]
    history_summary: dict[str, Any]
    client_context: dict[str, Any]
    allow_ai_review_submit: bool
    steps: int
    next_action: str
    tool_name: Optional[str]
    tool_arguments: dict[str, Any]
    tool_results: list[dict[str, Any]]
    last_tool_name: Optional[str]
    last_tool_ok: bool
    last_tool_failed: bool
    last_tool_error: Optional[str]
    last_error_type: Optional[str]
    last_tool_retryable: bool
    last_observation: dict[str, Any]
    assistant_reply: str
    need_human: bool
    session_mode: str
    ticket: Optional[dict[str, Any]]
    review_result: Optional[dict[str, Any]]
    handoff_succeeded: Optional[bool]
    evidence_needed: list[str]
    explicit_human_request: bool
    active_skills: list[dict[str, str]]
    skill_versions: dict[str, str]
    final: bool
    pending_tool_call_id: Optional[str]
    pending_assistant_tool_call: Optional[dict[str, Any]]
    function_messages: list[dict[str, Any]]
    decision_protocol: str
    current_function_call_mode: str
    current_provider_tool_call_shape: str


@dataclass
class LangGraphAfterSalesAgent:
    SAFE_RETRY_TOOLS: ClassVar[set[str]] = {
        "search_user_orders",
        "get_after_sales_ticket",
        "retrieve_knowledge",
        "review_images",
    }
    IDEMPOTENT_WRITE_TOOLS: ClassVar[set[str]] = {
        "submit_ai_review",
        "handoff_to_human",
        "append_chat_message",
    }
    tools: AgentToolRegistry = field(default_factory=AgentToolRegistry)
    skills: AgentSkillRegistry = field(default_factory=AgentSkillRegistry)
    llm: OpenAICompatibleClient = field(
        default_factory=get_llm_client
    )
    max_steps: int = field(default_factory=lambda: int(os.getenv("MAX_AGENT_STEPS", "8")))
    max_tool_calls: int = field(default_factory=lambda: int(os.getenv("MAX_TOOL_CALLS", "10")))
    max_duplicate_tool_calls: int = field(default_factory=lambda: int(os.getenv("MAX_DUPLICATE_TOOL_CALLS", "2")))
    native_function_calling_enabled: bool = field(default_factory=lambda: _env_bool("LLM_NATIVE_FUNCTION_CALLING_ENABLED", True))
    legacy_tool_call_fallback_enabled: bool = field(default_factory=lambda: _env_bool("LLM_LEGACY_TOOL_CALL_FALLBACK_ENABLED", True))
    _trace_recorder: ContextVar[Any | None] = field(
        default_factory=lambda: ContextVar("langgraph_trace_recorder", default=None),
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        graph = StateGraph(AgentGraphState)
        graph.add_node("receive_message", self.receive_message)
        graph.add_node("classify_or_plan", self.classify_or_plan)
        graph.add_node("tool_call", self.tool_call)
        graph.add_node("observe_tool_result", self.observe_tool_result)
        graph.add_node("decide_next", self.decide_next)
        graph.add_node("final_reply", self.final_reply)
        graph.add_node("human_handoff", self.human_handoff)

        graph.set_entry_point("receive_message")
        graph.add_edge("receive_message", "classify_or_plan")
        graph.add_conditional_edges(
            "classify_or_plan",
            self.route_after_plan,
            {
                "tool_call": "tool_call",
                "human_handoff": "human_handoff",
                "final_reply": "final_reply",
            },
        )
        graph.add_edge("tool_call", "observe_tool_result")
        graph.add_edge("observe_tool_result", "decide_next")
        graph.add_conditional_edges(
            "decide_next",
            self.route_after_decision,
            {
                "tool_call": "tool_call",
                "human_handoff": "human_handoff",
                "final_reply": "final_reply",
            },
        )
        graph.add_edge("human_handoff", "final_reply")
        graph.add_edge("final_reply", END)
        self.graph = graph.compile()

    def handle(self, payload: dict[str, Any], trace_recorder: Any | None = None) -> dict[str, Any]:
        trace_token = self._trace_recorder.set(trace_recorder)
        bind_trace = getattr(self.llm, "bind_trace", None)
        if callable(bind_trace):
            bind_trace(trace_recorder)
        try:
            with bind_trace_id(getattr(trace_recorder, "trace_id", None)):
                return self._handle_core(payload)
        finally:
            if callable(bind_trace):
                bind_trace(None)
            self._trace_recorder.reset(trace_token)

    def _handle_core(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: AgentGraphState = {
            "user_id": str(payload.get("user_id") or "0"),
            "session_id": self._optional_int(payload.get("session_id")),
            "ticket_id": str(payload.get("ticket_id") or "") or None,
            "review_request_id": str(payload.get("review_request_id") or "") or None,
            "message": str(payload.get("message") or ""),
            "attachments": list(payload.get("attachments") or []),
            "order_id_hint": str(payload.get("order_id") or "") or None,
            "recent_history": list(payload.get("recent_history") or []),
            "history_summary": dict(payload.get("history_summary") or {}),
            "client_context": dict(payload.get("client_context") or {}),
            "allow_ai_review_submit": self._allow_ai_review_submit(payload),
            "steps": 0,
            "tool_results": [],
            "last_observation": {},
            "need_human": False,
            "session_mode": "AI",
            "ticket": None,
            "review_result": None,
            "handoff_succeeded": None,
            "evidence_needed": [],
            "explicit_human_request": self._is_explicit_human_request(
                str(payload.get("message") or ""),
                list(payload.get("recent_history") or []),
            ),
            "active_skills": [],
            "skill_versions": {},
            "final": False,
            "pending_tool_call_id": None,
            "pending_assistant_tool_call": None,
            "function_messages": [],
            "decision_protocol": "native",
            "current_function_call_mode": "deterministic",
            "current_provider_tool_call_shape": "none",
        }
        final_state = self.graph.invoke(state)
        normalized_ticket = self._normalize_ticket(final_state.get("ticket"))
        return {
            "assistant_reply": final_state.get("assistant_reply") or "",
            "session_mode": final_state.get("session_mode") or "AI",
            "tool_trace": final_state.get("tool_results") or [],
            "ticket": normalized_ticket,
            "review_result": final_state.get("review_result"),
            "need_human": bool(final_state.get("need_human")),
            "evidence_needed": final_state.get("evidence_needed") or [],
            "persistence": {
                "session_id": str(final_state.get("session_id")) if final_state.get("session_id") else None,
                "ticket_no": normalized_ticket.get("ticket_no") if normalized_ticket else None,
            },
            "raw": {
                "runtime": "langgraph_react",
                "steps": final_state.get("steps") or 0,
                "mode": "ticket_review" if final_state.get("ticket_id") else "consultation",
                "decision_protocol": final_state.get("decision_protocol") or "fail_closed",
                "allow_ai_review_submit": bool(final_state.get("allow_ai_review_submit")),
                "skill_versions": final_state.get("skill_versions") or {},
            },
        }

    @staticmethod
    def _allow_ai_review_submit(payload: dict[str, Any]) -> bool:
        client_context = payload.get("client_context") if isinstance(payload.get("client_context"), dict) else {}
        return str(client_context.get("source") or "").strip().lower() == "kafka"

    def receive_message(self, state: AgentGraphState) -> AgentGraphState:
        if not state.get("message") and not state.get("attachments"):
            state["assistant_reply"] = "请描述您遇到的售后问题。"
            state["final"] = True
            return state
        state["steps"] = int(state.get("steps") or 0)
        return state

    def classify_or_plan(self, state: AgentGraphState) -> AgentGraphState:
        if state.get("final"):
            return state
        # Image submissions always need trusted order lookup before review. Do
        # not send base64 images through the text planner.
        if state.get("ticket_id") and not state.get("tool_results"):
            self._apply_action(state, self._get_ticket_action(state))
            return state

        if state.get("attachments") and not state.get("tool_results"):
            if state.get("ticket_id"):
                self._apply_action(state, self._get_ticket_action(state))
            else:
                self._apply_action(state, self._order_lookup_action(state))
            return state

        raw = self._native_decision(state, self._planner_system_prompt())
        raw = self._guard_completed_review_claim(state, raw)

        # 小模型安全网：LLM 忽略了已提供的订单上下文时，强制查订单
        # 这不是关键词匹配 — 只检查"有 order_id / 有实质内容 / LLM 没调工具"
        if self._llm_ignored_order_context(state, raw):
            logger.info("agent_function_guard tool=search_user_orders")
            raw = self._order_lookup_action(state)

        self._apply_action(state, raw)
        if state.get("next_action") not in {"tool_call", "human_handoff"}:
            self._clear_pending_tool_call(state)
        return state

    @staticmethod
    def _llm_ignored_order_context(state: AgentGraphState, llm_raw: dict[str, Any]) -> bool:
        """小模型安全网：LLM 有订单上下文却没查订单也没做有用的事。"""
        # 已经有 tool_results，说明之前的步骤已正确处理
        if state.get("tool_results"):
            return False
        # LLM 选了 tool_call，信任它
        if llm_raw.get("action") == "tool_call" and llm_raw.get("tool_name"):
            return False
        # LLM 选了 human_handoff，但用户有订单 — 应该先查订单再转人工
        if llm_raw.get("action") == "human_handoff":
            return bool(state.get("order_id_hint"))
        # LLM 选了 final_reply — 检查是否有订单上下文被忽略
        has_order = bool(state.get("order_id_hint"))
        msg = str(state.get("message") or "").strip()
        has_attachments = bool(state.get("attachments"))
        # 有订单 + (有附件 或 消息足够长) → LLM 不应该直接 final_reply
        return has_order and (has_attachments or len(msg) >= 8)

    def _native_decision(self, state: AgentGraphState, system_prompt: str) -> dict[str, Any]:
        payload = self._planner_payload(state)
        if not self.native_function_calling_enabled:
            try:
                return self._legacy_decision(state, system_prompt, payload, "legacy_disabled_native")
            except (LLMError, FunctionCallingProtocolError) as exc:
                logger.warning("agent_function_decision protocol=legacy_disabled_native error_category=%s", exc.__class__.__name__)
                return self._fail_closed_decision(state)
        try:
            decision = FunctionCallingAdapter(
                client=self.llm,
                registry=self.tools,
                temperature=0.1,
                max_tokens=700,
            ).decide(
                system_prompt=system_prompt,
                payload=payload,
                prior_messages=list(state.get("function_messages") or []),
            )
        except (LLMError, FunctionCallingProtocolError) as exc:
            self._clear_pending_tool_call(state)
            logger.warning("agent_function_decision protocol=native error_category=%s", exc.__class__.__name__)
            if not self.legacy_tool_call_fallback_enabled:
                return self._fail_closed_decision(state)
            try:
                return self._legacy_decision(state, system_prompt, payload, "legacy_fallback")
            except (LLMError, FunctionCallingProtocolError) as fallback_exc:
                self._clear_pending_tool_call(state)
                logger.warning("agent_function_decision protocol=legacy_fallback error_category=%s", fallback_exc.__class__.__name__)
                return self._fail_closed_decision(state)
        action = dict(decision.action)
        action["_function_call_mode"] = "native"
        action["_provider_tool_call_shape"] = decision.provider_tool_call_shape
        state["pending_tool_call_id"] = action.get("tool_call_id")
        state["pending_assistant_tool_call"] = dict(decision.assistant_message)
        state["decision_protocol"] = "native"
        logger.info(
            "agent_function_decision protocol=native tool=%s call_id=%s",
            action.get("tool_name"),
            state["pending_tool_call_id"],
        )
        return action

    def _legacy_decision(self, state: AgentGraphState, system_prompt: str, payload: dict[str, Any], protocol: str) -> dict[str, Any]:
        self._clear_pending_tool_call(state)
        raw = self.llm.chat_json(
            system_prompt=system_prompt,
            user_prompt=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            temperature=0.1,
            max_tokens=700,
        )
        action = FunctionCallingAdapter(client=self.llm, registry=self.tools).validate_action(raw)
        action["_function_call_mode"] = "legacy"
        action["_provider_tool_call_shape"] = "legacy_json"
        state["decision_protocol"] = protocol
        logger.info(
            "agent_function_decision protocol=%s tool=%s call_id=%s",
            protocol,
            action.get("tool_name"),
            None,
        )
        return action

    @staticmethod
    def _fail_closed_decision(state: AgentGraphState) -> dict[str, Any]:
        state["decision_protocol"] = "fail_closed"
        if state.get("ticket_id"):
            return {
                "action": "human_handoff",
                "tool_name": None,
                "tool_arguments": {},
                "assistant_reply": "当前智能售后服务暂时不可用，正在尝试为您转接人工客服继续核对。",
                "need_human": True,
                "evidence_needed": state.get("evidence_needed") or [],
            }
        return {
            "action": "final_reply",
            "tool_name": None,
            "tool_arguments": {},
            "assistant_reply": "当前智能售后服务暂时不可用，请稍后重试或联系人工客服。",
            "need_human": False,
            "evidence_needed": state.get("evidence_needed") or [],
        }

    @staticmethod
    def _clear_pending_tool_call(state: AgentGraphState) -> None:
        state["pending_tool_call_id"] = None
        state["pending_assistant_tool_call"] = None

    @staticmethod
    def _trace_protocol(state: AgentGraphState) -> dict[str, str]:
        mode = state.get("current_function_call_mode")
        shape = state.get("current_provider_tool_call_shape")
        if mode == "native" and shape in {"openai", "ollama"}:
            return {
                "function_call_mode": "native",
                "provider_tool_call_shape": str(shape),
            }
        if mode == "legacy" and shape == "legacy_json":
            return {
                "function_call_mode": "legacy",
                "provider_tool_call_shape": "legacy_json",
            }
        return {
            "function_call_mode": "deterministic",
            "provider_tool_call_shape": "none",
        }

    @staticmethod
    def _java_visible_tool_results(state: AgentGraphState) -> list[Any]:
        internal_fields = {"function_call_mode", "provider_tool_call_shape"}
        return [
            {
                key: value
                for key, value in item.items()
                if key not in internal_fields
            }
            if isinstance(item, dict)
            else item
            for item in state.get("tool_results") or []
        ]

    def _correlate_tool_observation(
        self,
        state: AgentGraphState,
        latest: dict[str, Any],
        observation: dict[str, Any],
    ) -> None:
        call_id = state.get("pending_tool_call_id")
        assistant_message = state.get("pending_assistant_tool_call")
        if (
            not isinstance(call_id, str)
            or not call_id
            or not isinstance(assistant_message, dict)
            or latest.get("tool_call_id") != call_id
        ):
            return
        messages = list(state.get("function_messages") or [])
        messages.extend([
            assistant_message,
            {
                "role": "tool",
                "tool_call_id": call_id,
                "name": str(latest.get("tool") or ""),
                "content": json.dumps(observation, ensure_ascii=False, default=str),
            },
        ])
        state["function_messages"] = messages
        self._clear_pending_tool_call(state)

    @staticmethod
    def _is_explicit_human_request(message: str, recent_history: list[dict[str, Any]] | None = None) -> bool:
        keywords = ("转人工", "人工客服", "真人客服", "人工帮助", "联系客服", "转接人工")
        if any(keyword in message for keyword in keywords):
            return True
        for item in reversed(recent_history or []):
            if str(item.get("role") or "").upper() != "USER":
                continue
            content = str(item.get("content") or "")
            if any(keyword in content for keyword in keywords):
                return True
        return False

    def tool_call(self, state: AgentGraphState) -> AgentGraphState:
        name = str(state.get("tool_name") or "")
        arguments = state.get("tool_arguments") or {}
        prior = list(state.get("tool_results") or [])
        canonical_arguments = json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str)
        duplicate_count = sum(
            1 for item in prior
            if item.get("tool") == name
            and json.dumps(item.get("arguments") or {}, ensure_ascii=False, sort_keys=True, default=str) == canonical_arguments
        )
        if len(prior) >= self.max_tool_calls or duplicate_count >= self.max_duplicate_tool_calls:
            logger.warning("agent_tool_guard tool=%s error_category=guard_limit", name)
            guarded_trace: dict[str, Any] = {
                "tool": name,
                "arguments": arguments,
                "ok": False,
                "data": None,
                "error": "tool_call_limit_exceeded",
                **self._trace_protocol(state),
            }
            if state.get("pending_tool_call_id"):
                guarded_trace["tool_call_id"] = state["pending_tool_call_id"]
            state["tool_results"] = prior + [guarded_trace]
            state["steps"] = self.max_steps
            state["next_action"] = "final_reply"
            state["assistant_reply"] = "当前请求需要人工进一步核验，我已停止重复操作以保护您的订单。"
            state["need_human"] = True
            return state
        logger.info("agent_tool_call tool=%s call_id=%s", name, state.get("pending_tool_call_id"))
        trace_recorder = self._trace_recorder.get()
        if trace_recorder is not None:
            with trace_recorder.step("agent_tool_call", tool=name):
                result = self.tools.call(name, arguments)
        else:
            result = self.tools.call(name, arguments)
        logger.info(
            "agent_tool_result tool=%s call_id=%s error_category=%s",
            name,
            state.get("pending_tool_call_id"),
            result.error_category if not result.ok else "none",
        )
        AGENT_RUNTIME_METRICS.record_tool(name, result.ok, result.error_category)
        trace = list(state.get("tool_results") or [])
        trace_entry: dict[str, Any] = {
            "tool": name,
            "arguments": state.get("tool_arguments") or {},
            "ok": result.ok,
            "data": result.data,
            "error": result.error,
            "error_code": result.error_code,
            "error_category": result.error_category,
            "retryable": result.retryable,
            **self._trace_protocol(state),
        }
        if state.get("pending_tool_call_id"):
            trace_entry["tool_call_id"] = state["pending_tool_call_id"]
        trace.append(trace_entry)
        state["tool_results"] = trace
        state["steps"] = int(state.get("steps") or 0) + 1
        return state

    def observe_tool_result(self, state: AgentGraphState) -> AgentGraphState:
        latest = self._latest_tool_result(state)
        if not latest:
            state["last_observation"] = {}
            return state

        tool = str(latest.get("tool") or "")
        ok = bool(latest.get("ok"))
        error = str(latest.get("error") or "") or None
        data = latest.get("data")

        state["last_tool_name"] = tool
        state["last_tool_ok"] = ok
        state["last_tool_failed"] = not ok
        state["last_tool_error"] = error
        state["last_error_type"] = None if ok else str(latest.get("error_category") or self._classify_tool_error(error))
        state["last_tool_retryable"] = bool(latest.get("retryable"))

        observation = self._build_tool_observation(tool, ok, data, error)
        if not ok:
            observation["error_type"] = state["last_error_type"]
            observation["error_code"] = latest.get("error_code")
            observation["retryable"] = state["last_tool_retryable"]
        state["last_observation"] = observation
        logger.info(
            "agent_tool_observation tool=%s call_id=%s error_category=%s",
            tool,
            latest.get("tool_call_id"),
            state["last_error_type"] or "none",
        )
        self._correlate_tool_observation(state, latest, observation)

        if not ok:
            return state

        if tool == "get_after_sales_ticket" and isinstance(data, dict):
            state["ticket"] = data
            if data.get("order_id"):
                state["order_id_hint"] = str(data.get("order_id"))
            if not state.get("attachments") and isinstance(data.get("evidence_urls"), list):
                urls = data.get("evidence_urls") or []
                state["attachments"] = [
                    {"kind": "image", "name": f"ticket_evidence_{index}.jpg", "source": str(url)}
                    for index, url in enumerate(urls, start=1)
                    if url
                ]
            logger.info("agent_tool_state tool=get_after_sales_ticket")
        elif tool == "submit_ai_review" and isinstance(data, dict):
            state["review_result"] = data
            state["ticket"] = data
            logger.info("agent_tool_state tool=submit_ai_review")
        elif tool == "handoff_to_human":
            state["session_mode"] = "HUMAN"
            state["need_human"] = True
            state["handoff_succeeded"] = True
            AGENT_RUNTIME_METRICS.record_handoff()
            logger.info("agent_tool_state tool=handoff_to_human")
        return state

    def decide_next(self, state: AgentGraphState) -> AgentGraphState:
        steps = int(state.get("steps") or 0)
        logger.info(
            "agent_function_decider protocol=%s tool=%s error_category=%s",
            state.get("decision_protocol"),
            state.get("last_tool_name"),
            state.get("last_error_type") or "none",
        )

        if steps >= self.max_steps:
            logger.info("agent_function_guard error_category=max_steps")
            state["next_action"] = "final_reply"
            state.setdefault("assistant_reply", "已收到您的售后问题，我会根据当前信息继续为您处理。")
            return state
        if state.get("last_tool_failed"):
            failure_action = self._handle_tool_failure(state)
            if failure_action is not None:
                logger.info(
                    "agent_tool_failure tool=%s error_category=%s",
                    failure_action.get("tool_name") or state.get("last_tool_name"),
                    state.get("last_error_type"),
                )
                self._apply_action(state, failure_action)
                return state
        if self._has_empty_order_search(state):
            logger.info("agent_tool_state tool=search_user_orders error_category=empty_result")
            state["next_action"] = "final_reply"
            state["assistant_reply"] = "我没有查询到可用于售后的订单。请提供订单号，或从订单详情页进入售后咨询后再申请退款/退货。"
            state["evidence_needed"] = ["订单信息"]
            state["need_human"] = False
            return state
        if self._has_failed_order_search(state):
            logger.info("agent_tool_failure tool=search_user_orders error_category=tool_error")
            state["next_action"] = "final_reply"
            state["assistant_reply"] = "当前订单服务暂时不可用，我还不能核对订单或创建售后单。请稍后重试。"
            state["evidence_needed"] = ["订单信息"]
            state["need_human"] = False
            return state

        guarded = self._guarded_after_sales_action(state)
        if guarded is not None:
            logger.info("agent_function_guard tool=%s", guarded.get("tool_name"))
            action = guarded
            if guarded.get("action") == "final_reply":
                action = self._native_terminal_decision(state, guarded)
            self._apply_action(state, action)
            if state.get("next_action") not in {"tool_call", "human_handoff"}:
                self._clear_pending_tool_call(state)
            return state

        raw = self._native_decision(state, self._decider_system_prompt())
        raw = self._guard_completed_review_claim(state, raw)
        self._apply_action(state, raw)
        if state.get("next_action") not in {"tool_call", "human_handoff"}:
            self._clear_pending_tool_call(state)
        return state

    def _native_terminal_decision(
        self,
        state: AgentGraphState,
        guarded: dict[str, Any],
    ) -> dict[str, Any]:
        raw = self._native_decision(state, self._decider_system_prompt())
        if state.get("decision_protocol") == "fail_closed":
            return raw
        raw = self._guard_completed_review_claim(state, raw, terminal=True)
        if raw.get("action") != "final_reply":
            logger.warning(
                "agent_function_terminal_guard tool=%s error_category=terminal_action_rejected",
                raw.get("tool_name"),
            )
            return guarded

        constrained = dict(raw)
        constrained["tool_name"] = None
        constrained["tool_arguments"] = {}
        constrained["need_human"] = bool(guarded.get("need_human"))
        constrained["evidence_needed"] = list(guarded.get("evidence_needed") or [])
        return constrained

    def _guard_completed_review_claim(
        self,
        state: AgentGraphState,
        raw: dict[str, Any],
        *,
        terminal: bool = False,
    ) -> dict[str, Any]:
        if (
            not self._claims_review_completed(raw.get("assistant_reply"))
            or self._has_successful_tool(state, "submit_ai_review")
        ):
            return raw
        logger.info("agent_function_guard tool=submit_ai_review error_category=unconfirmed_review")
        if terminal or self._has_successful_tool(state, "search_user_orders"):
            return {
                "action": "final_reply",
                "tool_name": None,
                "tool_arguments": {},
                "assistant_reply": "我需要先核对您的售后申请和审核条件，暂时不能声称AI初审已完成。请稍后重试或联系人工客服。",
                "need_human": False,
                "evidence_needed": ["订单信息"],
            }
        return self._order_lookup_action(state)

    def _handle_tool_failure(self, state: AgentGraphState) -> dict[str, Any] | None:
        tool = str(state.get("last_tool_name") or state.get("tool_name") or "")
        error_type = str(state.get("last_error_type") or "tool_error")
        arguments = dict(state.get("tool_arguments") or {})

        if error_type in {"timeout", "service_unavailable"}:
            if (
                tool
                and self._can_retry_tool(tool, arguments)
                and self._tool_attempts(state, tool, arguments) <= self._fast_retry_max_attempts()
            ):
                return {
                    "action": "tool_call",
                    "tool_name": tool,
                    "tool_arguments": arguments,
                    "assistant_reply": "",
                    "need_human": False,
                    "evidence_needed": state.get("evidence_needed") or [],
                }
            if tool in {"review_images", "retrieve_knowledge"} and state.get("ticket_id") and not self._has_successful_tool(state, "submit_ai_review"):
                return self._manual_review_for_tool_failure(state, tool)
            if tool == "submit_ai_review":
                state["review_result"] = {"submit_failed": True, "error_type": error_type}
                if self._has_successful_tool(state, "get_after_sales_ticket") and self._tool_attempts(state, "get_after_sales_ticket") < 2:
                    return self._get_ticket_action(state)
            return {
                "action": "human_handoff",
                "tool_name": None,
                "tool_arguments": {},
                "assistant_reply": "当前智能售后服务暂时不可用，我已为您转接人工客服继续处理。",
                "need_human": True,
                "evidence_needed": state.get("evidence_needed") or [],
            }

        if error_type in {"validation", "not_found"}:
            return {
                "action": "final_reply",
                "tool_name": None,
                "tool_arguments": {},
                "assistant_reply": "当前信息不完整或无法匹配订单，请补充订单号、售后问题描述或相关凭证后再试。",
                "need_human": False,
                "evidence_needed": ["订单信息"],
            }

        if error_type == "permission":
            return {
                "action": "final_reply",
                "tool_name": None,
                "tool_arguments": {},
                "assistant_reply": "当前账号无权操作该订单，请确认订单是否属于当前账号后再试。",
                "need_human": False,
                "evidence_needed": ["订单信息"],
            }

        if error_type == "guard_limit":
            return {
                "action": "final_reply",
                "tool_name": None,
                "tool_arguments": {},
                "assistant_reply": state.get("assistant_reply") or "当前请求需要人工进一步核验，我已停止重复操作以保护您的订单。",
                "need_human": bool(state.get("need_human")),
                "evidence_needed": state.get("evidence_needed") or [],
            }

        return None

    def _manual_review_for_tool_failure(self, state: AgentGraphState, tool: str) -> dict[str, Any]:
        reason_code = "visual_service_unavailable" if tool == "review_images" else "policy_uncertain"
        reason_text = "图片审核服务暂时不可用，AI无法确认凭证真实性，需人工复核。" if tool == "review_images" else "知识库政策检索暂时不可用或无明确命中，需人工复核。"
        state["need_human"] = True
        state["evidence_needed"] = state.get("evidence_needed") or []
        return {
            "action": "tool_call",
            "tool_name": "submit_ai_review",
            "tool_arguments": {
                "user_id": state.get("user_id"),
                "session_id": state.get("session_id"),
                "ticket_id": state.get("ticket_id"),
                "review_request_id": state.get("review_request_id"),
                "order_id": state.get("order_id_hint"),
                "verdict": "MANUAL_REVIEW_REQUIRED",
                "ai_review_confidence": 0.0,
                "reason": reason_text,
                "evidence_needed": state.get("evidence_needed") or [],
                "visual_uncertain": tool == "review_images",
                "policy_uncertain": tool == "retrieve_knowledge",
                "evidence_consistent": False,
                "visual_confidence": 0.0,
                "risk_review_reasons": [reason_code],
                "policy_citations": [],
                "image_review": None,
            },
            "assistant_reply": "",
            "need_human": True,
            "evidence_needed": state.get("evidence_needed") or [],
        }

    def human_handoff(self, state: AgentGraphState) -> AgentGraphState:
        logger.info("agent_handoff_requested tool=handoff_to_human")
        ticket_id = state.get("ticket_id") or (
            (state.get("ticket") or {}).get("ticket_id")
            if isinstance(state.get("ticket"), dict)
            else None
        )
        args = {
            "user_id": state.get("user_id"),
            "session_id": state.get("session_id"),
            "order_id": state.get("order_id_hint"),
            "ticket_id": ticket_id,
            "summary": state.get("assistant_reply") or state.get("message") or "AI 建议转人工",
        }
        result = self.tools.call("handoff_to_human", args)
        trace = list(state.get("tool_results") or [])
        trace_entry: dict[str, Any] = {
            "tool": "handoff_to_human",
            "arguments": args,
            "ok": result.ok,
            "data": result.data,
            "error": result.error,
            "error_code": result.error_code,
            "error_category": result.error_category,
            "retryable": result.retryable,
            **self._trace_protocol(state),
        }
        if state.get("pending_tool_call_id"):
            trace_entry["tool_call_id"] = state["pending_tool_call_id"]
        trace.append(trace_entry)
        state["tool_results"] = trace
        observation = self._build_tool_observation(
            "handoff_to_human",
            result.ok,
            result.data,
            result.error,
        )
        if not result.ok:
            observation["error_type"] = result.error_category or self._classify_tool_error(result.error)
            observation["error_code"] = result.error_code
            observation["retryable"] = result.retryable
        self._correlate_tool_observation(state, trace_entry, observation)
        self._clear_pending_tool_call(state)
        handoff_ok = self._is_successful_handoff_result(result)
        if result.ok and not handoff_ok:
            logger.warning("agent_handoff_result tool=handoff_to_human error_category=unconfirmed")
        state["session_mode"] = "HUMAN" if handoff_ok else "AI"
        state["need_human"] = True
        state["handoff_succeeded"] = handoff_ok
        if handoff_ok:
            if isinstance(result.data, dict):
                session_id = result.data.get("session_id") or result.data.get("sessionId")
                if session_id:
                    state["session_id"] = session_id
            ticket = state.get("ticket") if isinstance(state.get("ticket"), dict) else None
            if ticket:
                ticket_no = ticket.get("ticket_no")
                ticket_label = f" {ticket_no}" if ticket_no else ""
                state["assistant_reply"] = f"您的售后申请{ticket_label}已完成AI初审，但图片或政策条件仍需人工确认，当前继续保持待审核状态，已为您转交人工复核。"
            else:
                state["assistant_reply"] = "已为您转接人工客服，请稍等。"
        else:
            state["assistant_reply"] = "当前人工转接暂时未确认成功，我已保留您的售后申请记录，请稍后重试或联系人工客服。"
        return state

    def final_reply(self, state: AgentGraphState) -> AgentGraphState:
        reply = state.get("assistant_reply") or self._ticket_reply(state) or "已收到您的售后问题，我会继续为您处理。"
        # 最终防线：确保 reply 不是泄漏的 JSON 数据
        reply = self._sanitize_reply(reply)
        logger.info("agent_final_reply tool=append_chat_message")
        ticket_id = state.get("ticket_id") or (
            (state.get("ticket") or {}).get("ticket_id")
            if isinstance(state.get("ticket"), dict)
            else None
        )
        attachment_url = self._first_attachment_file_url(state)
        user_message_type = "IMAGE" if attachment_url and str(state.get("message") or "").strip() in {"", "[图片]", "[image]"} else "TEXT"
        append_user = {
            "user_id": state.get("user_id"),
            "session_id": state.get("session_id"),
            "order_id": state.get("order_id_hint"),
            "ticket_id": ticket_id,
            "role": "USER",
            "content": state.get("message") or "用户发送了售后凭证",
            "message_type": user_message_type,
        }
        if attachment_url:
            append_user["file_url"] = attachment_url
        append_assistant = {
            "user_id": state.get("user_id"),
            "session_id": state.get("session_id"),
            "order_id": state.get("order_id_hint"),
            "ticket_id": ticket_id,
            "role": "ASSISTANT",
            "content": reply,
            "message_type": "TEXT",
            "knowledge_hits_json": json.dumps(
                self._java_visible_tool_results(state),
                ensure_ascii=False,
            ),
        }
        trace = list(state.get("tool_results") or [])
        user_result = self.tools.call("append_chat_message", append_user)
        trace.append({
            "tool": "append_chat_message",
            "arguments": append_user,
            "ok": user_result.ok,
            "data": user_result.data,
            "error": user_result.error,
            "function_call_mode": "deterministic",
            "provider_tool_call_shape": "none",
        })
        if user_result.ok and isinstance(user_result.data, dict) and not state.get("session_id"):
            state["session_id"] = user_result.data.get("session_id")
        append_assistant["session_id"] = state.get("session_id")
        assistant_result = self.tools.call("append_chat_message", append_assistant)
        trace.append({
            "tool": "append_chat_message",
            "arguments": append_assistant,
            "ok": assistant_result.ok,
            "data": assistant_result.data,
            "error": assistant_result.error,
            "function_call_mode": "deterministic",
            "provider_tool_call_shape": "none",
        })
        state["tool_results"] = trace
        state["assistant_reply"] = reply
        state["final"] = True
        return state

    @staticmethod
    def _first_attachment_file_url(state: AgentGraphState) -> str | None:
        for item in state.get("attachments") or []:
            if not isinstance(item, dict):
                continue
            source = str(
                item.get("file_url")
                or item.get("fileUrl")
                or item.get("url")
                or item.get("source")
                or ""
            ).strip()
            lowered = source.lower()
            if (
                lowered.startswith("/uploads/")
                or lowered.startswith("http://")
                or lowered.startswith("https://")
            ):
                return source
        return None

    def route_after_plan(self, state: AgentGraphState) -> Literal["tool_call", "human_handoff", "final_reply"]:
        if state.get("final"):
            return "final_reply"
        action = state.get("next_action")
        if action == "tool_call" and state.get("tool_name"):
            return "tool_call"
        if action == "human_handoff" or state.get("need_human"):
            return "human_handoff"
        return "final_reply"

    def route_after_decision(self, state: AgentGraphState) -> Literal["tool_call", "human_handoff", "final_reply"]:
        action = state.get("next_action")
        if action == "tool_call" and state.get("tool_name"):
            return "tool_call"
        if action == "human_handoff" or state.get("need_human"):
            return "human_handoff"
        return "final_reply"

    def _planner_payload(self, state: AgentGraphState) -> dict[str, Any]:
        attachments = [
            {"kind": item.get("kind"), "name": item.get("name"), "has_source": bool(item.get("source"))}
            for item in (state.get("attachments") or []) if isinstance(item, dict)
        ]
        skill = self.skills.select(self._skill_stage(state))
        active_skills = [skill.context()] if skill is not None else []
        state["active_skills"] = active_skills
        versions = dict(state.get("skill_versions") or {})
        if skill is not None:
            versions[skill.name] = skill.version
        state["skill_versions"] = versions
        return {
            "user": {
                "user_id": state.get("user_id"),
                "message": state.get("message"),
                "attachments": attachments,
                "order_id_hint": state.get("order_id_hint"),
            "client_context": state.get("client_context"),
            "ticket_id": state.get("ticket_id"),
            "review_request_id": state.get("review_request_id"),
            },
            "recent_history": state.get("recent_history") or [],
            "history_summary": state.get("history_summary") or {},
            "active_skills": active_skills,
            "available_tools": self.tools.tool_specs(),
            "tool_results": self._summarize_tool_results(state),
            "last_observation": state.get("last_observation") or {},
            "current_ticket": self._summarize_ticket_for_llm(state.get("ticket")),
            "evidence_needed": state.get("evidence_needed") or [],
        }

    @staticmethod
    def _skill_stage(state: AgentGraphState) -> str:
        if state.get("explicit_human_request") or state.get("need_human"):
            return "human_handoff"
        knowledge = LangGraphAfterSalesAgent._latest_tool_data(state, "retrieve_knowledge")
        if isinstance(knowledge, dict) and knowledge.get("hits"):
            return "policy_explanation"
        return "evidence_collection"

    @staticmethod
    def _summarize_tool_results(state: AgentGraphState) -> list[dict[str, Any]]:
        """压缩 tool_results，避免 LLM 看到内部 JSON 后复述给用户。"""
        summary: list[dict[str, Any]] = []
        for item in state.get("tool_results") or []:
            tool = item.get("tool")
            ok = item.get("ok")
            data = item.get("data")
            error = str(item.get("error") or "")[:120]
            entry: dict[str, Any] = {"tool": tool, "ok": ok, "error": error}
            if tool == "search_user_orders" and isinstance(data, list):
                entry["orders_found"] = len(data)
                entry["order_ids"] = [
                    str(o.get("order_id") or "")
                    for o in data if isinstance(o, dict)
                ][:5]
            elif tool == "review_images" and isinstance(data, dict):
                entry["summary"] = {
                    "all_clear": data.get("all_clear"),
                    "has_damage_area": data.get("has_damage_area"),
                    "has_outer_package": data.get("has_outer_package"),
                    "has_logistics_label": data.get("has_logistics_label"),
                    "missing_visual_evidence": data.get("missing_visual_evidence"),
                }
            elif tool == "retrieve_knowledge" and isinstance(data, dict):
                entry["hits_count"] = len(data.get("hits") or [])
                entry["top_titles"] = [
                    (h.get("title") or "") + (" ✓" if h.get("source_code", "").endswith("_001") else "")
                    for h in (data.get("hits") or [])[:5] if isinstance(h, dict)
                ]
            elif tool == "get_after_sales_ticket" and isinstance(data, dict):
                entry["ticket_id"] = data.get("ticket_id")
                entry["ticket_no"] = data.get("ticket_no")
                entry["status"] = data.get("status")
            elif tool == "submit_ai_review" and isinstance(data, dict):
                entry["review_submitted"] = True
                entry["verdict"] = data.get("verdict") or data.get("ai_review_result")
                entry["status"] = data.get("status")
            elif tool == "handoff_to_human":
                entry["note"] = "已发起人工转接" if ok else "转接失败"
            elif tool == "append_chat_message":
                entry["note"] = "消息已保存" if ok else "保存失败"
            summary.append(entry)
        return summary

    @staticmethod
    def _summarize_ticket_for_llm(ticket: Any) -> dict[str, Any] | None:
        """压缩 current_ticket，避免 LLM 看到完整的建单 JSON 后复述。"""
        if not isinstance(ticket, dict):
            return None
        return {
            "ticket_id": ticket.get("ticket_id"),
            "ticket_no": ticket.get("ticket_no"),
            "status": ticket.get("status"),
            "existing": bool(ticket.get("existing")),
        }

    @staticmethod
    def _planner_system_prompt() -> str:
        return (
            "你是电商售后 ReAct Agent。决策规则（按优先级）：\n"
            "1. 没有 ticket_id 时是咨询模式：可以查订单和RAG，但不得创建工单或更新工单状态。\n"
            "2. 正式售后申请只能由用户在订单详情页提交，Agent不得代替用户创建。\n"
            "3. 携带 ticket_id 时是工单审核模式：先 get_after_sales_ticket 校验已有工单，再审核图片和RAG。\n"
            "4. 图片审核和RAG政策明确、证据一致、置信度达标且低风险时，调用 submit_ai_review 提交 APPROVE。\n"
            "5. 图片不确定、政策不明确、证据不一致、置信度不足或存在风险时，调用 submit_ai_review 提交 MANUAL_REVIEW_REQUIRED。\n"
            "6. 不要声称已创建售后工单；只能说明 AI初审已完成、继续待审核或已转人工复核。\n"
            "7. 工单和状态是否更新成功，必须以Java工具返回结果为准。\n"
            "⚠️ assistant_reply 必须是给用户看的自然中文文本，绝对禁止包含 JSON、工具调用参数、\n"
            "   base64、长数字ID序列或任何机器可读数据。回复应像真人客服一样亲切、简洁、信息明确。\n"
            "调用一个提供的 function 完成当前决策。"
        )

    @staticmethod
    def _decider_system_prompt() -> str:
        return (
            "你是售后 Agent 的观察/决策节点。根据 tool_results 决定继续调用工具、转人工或最终回复。\n"
            "AI初审必须以 submit_ai_review 的结果为准；不要编造工具未返回的订单、售后单、政策或状态更新。\n"
            "没有 ticket_id 时只能做咨询和引导用户去订单详情页申请售后，不得提交AI审核。\n"
            "⚠️ assistant_reply 必须是给用户看的自然中文文本，绝对禁止包含 JSON、工具调用参数、\n"
            "   base64、长数字ID序列或任何机器可读数据。回复应像真人客服一样亲切、简洁、信息明确。\n"
            "调用一个提供的 function 完成当前决策。"
        )

    def _guarded_after_sales_action(self, state: AgentGraphState) -> dict[str, Any] | None:
        """确定性售后路由：无 ticket_id 只咨询；有 ticket_id 才做 AI 初审。"""
        if not state.get("ticket_id"):
            return self._consultation_action(state)

        if not self._has_successful_tool(state, "get_after_sales_ticket"):
            return self._get_ticket_action(state)

        if isinstance(state.get("review_result"), dict) and state["review_result"].get("submit_failed"):
            return {
                "action": "human_handoff",
                "assistant_reply": "AI初审结果暂时无法确认是否已提交成功，当前不会声称状态已更新，我会为您转接人工客服继续核对。",
                "need_human": True,
                "evidence_needed": state.get("evidence_needed") or [],
            }

        if self._has_successful_tool(state, "submit_ai_review"):
            if (state.get("need_human") or self._ticket_requires_handoff(state)) and not self._has_successful_tool(state, "handoff_to_human"):
                return {
                    "action": "human_handoff",
                    "assistant_reply": "您的售后申请已完成AI初审，但图片或政策条件仍需人工确认，当前继续保持待审核状态，已为您转交人工复核。",
                    "need_human": True,
                    "evidence_needed": state.get("evidence_needed") or [],
                }
            return {
                "action": "final_reply",
                "assistant_reply": self._ticket_reply(state),
                "need_human": bool(state.get("need_human")),
                "evidence_needed": state.get("evidence_needed") or [],
            }

        ticket = self._latest_tool_data(state, "get_after_sales_ticket")
        if not isinstance(ticket, dict):
            return {
                "action": "final_reply",
                "assistant_reply": "暂时无法读取您的售后申请，请稍后重试或联系人工客服。",
                "need_human": False,
                "evidence_needed": [],
            }
        state["ticket"] = ticket
        status = str(ticket.get("status") or "").upper()
        if status not in {"PENDING_REVIEW", "PENDING"}:
            return {
                "action": "final_reply",
                "assistant_reply": f"已读取到您的售后申请，当前状态为{status}，AI不会覆盖人工或系统已经作出的处理结果。",
                "need_human": False,
                "evidence_needed": [],
            }

        order = self._order_from_ticket(ticket)
        if state.get("attachments") and not self._has_tool_result(state, "review_images"):
            return self._review_images_action(state, order)
        if (
            not state.get("attachments")
            and not self._ticket_has_uploaded_images(ticket)
            and self._needs_problem_image_evidence(state)
        ):
            evidence_needed = ["商品问题照片"]
            state["evidence_needed"] = evidence_needed
            return {
                "action": "final_reply",
                "assistant_reply": "已收到您的售后申请和问题描述。当前还没有可用于核验问题现象的商品问题图片，请补充上传商品异常界面、故障现象或相关问题凭证后，我再继续为您推进审核。",
                "need_human": False,
                "evidence_needed": evidence_needed,
            }
        if not self._has_tool_result(state, "retrieve_knowledge"):
            return self._retrieve_policy_action(state, order)
        if not self._has_successful_tool(state, "submit_ai_review"):
            return self._build_ai_review_action(state, order)
        return {
            "action": "final_reply",
            "assistant_reply": self._ticket_reply(state),
            "need_human": bool(state.get("need_human")),
            "evidence_needed": state.get("evidence_needed") or [],
        }

    def _consultation_action(self, state: AgentGraphState) -> dict[str, Any] | None:
        if (
            not self._has_successful_tool(state, "search_user_orders")
            and not self._has_successful_tool(state, "get_order_detail")
        ):
            return self._order_lookup_action(state)
        order = self._selected_order(state)
        if order is None:
            return {
                "action": "final_reply",
                "assistant_reply": "我查到了多笔可能相关的订单，请补充具体订单号，或从对应订单详情页点击“申请售后”正式提交申请。",
                "evidence_needed": ["订单号"],
                "need_human": False,
            }
        if bool(state.get("explicit_human_request")) and not self._has_successful_tool(state, "handoff_to_human"):
            return {
                "action": "human_handoff",
                "assistant_reply": "我会为您转接人工客服继续处理。正式提交售后申请仍需要从对应订单详情页点击“申请售后”。",
                "need_human": True,
                "evidence_needed": [],
            }
        if not self._has_tool_result(state, "retrieve_knowledge"):
            return self._retrieve_evidence_action(state, order)
        evidence_needed = self._build_evidence_needed(state, order)
        reply = self._build_evidence_guidance(state, order, evidence_needed)
        if bool(order.get("has_open_after_sales")) or self._existing_ticket_no(order):
            return {
                "action": "final_reply",
                "assistant_reply": reply,
                "need_human": False,
                "evidence_needed": evidence_needed,
            }
        return {
            "action": "final_reply",
            "assistant_reply": f"{reply} 您可以从对应订单详情页点击“申请售后”正式提交申请，提交后系统会自动进行初步审核。",
            "need_human": False,
            "evidence_needed": evidence_needed,
        }

    def _build_ai_review_action(self, state: AgentGraphState, order: dict[str, Any]) -> dict[str, Any]:
        review = self._latest_tool_data(state, "review_images")
        knowledge = self._latest_tool_data(state, "retrieve_knowledge")
        policy_hits = self._policy_hits(knowledge)
        trusted_policy_hits = self._trusted_policy_hits(
            knowledge,
            order,
        )
        has_attachments = bool(state.get("attachments"))

        # A policy hit is mandatory for automatic processing. Missing policy
        # context remains a human-review case instead of a model-only decision.
        policy_uncertain = not trusted_policy_hits

        # 优化视觉判断逻辑：
        # 1. 图片识别失败 → uncertain
        # 2. 用户明确描述破损，但图片完全看不出问题且missing_evidence明确指出缺失 → uncertain
        user_claims_damage = self._mentions_visible_damage(state)
        user_claims_functional_issue = self._mentions_functional_quality_issue(state)
        image_shows_damage = isinstance(review, dict) and review.get("has_damage_area")
        visual_confidence = self._visual_confidence(review)
        evidence_consistent = self._evidence_consistent(state, review)
        minimum_visual_confidence = float(os.getenv("VISION_AUTO_APPROVE_MIN_CONFIDENCE", "0.90"))
        risk_review_reasons = self._risk_review_reasons(state, order)
        emotion = self._emotion_context(state)
        emotion_priority = bool(emotion.get("need_human_priority"))

        visual_uncertain = has_attachments and (
            not isinstance(review, dict)
            or not review.get("success")
            or (user_claims_damage and not image_shows_damage and self._review_missing_damage(review))
            or (user_claims_functional_issue and not image_shows_damage)
        )

        evidence_needed = self._build_evidence_needed(state, order)

        auto_approved = bool(
            has_attachments
            and isinstance(review, dict)
            and review.get("success")
            and (image_shows_damage or (user_claims_damage and not visual_uncertain))
            and evidence_consistent is True
            and visual_confidence >= minimum_visual_confidence
            and not policy_uncertain
            and not risk_review_reasons
            and not emotion_priority
        )
        review_requires_human = bool(
            visual_uncertain
            or policy_uncertain
            or evidence_consistent is not True
            or visual_confidence < minimum_visual_confidence
            or bool(risk_review_reasons)
            or emotion_priority
        )

        reason = self._ai_suggestion_reason(
            state,
            review,
            knowledge,
            auto_approved,
            visual_uncertain,
            policy_uncertain,
            evidence_needed,
        )

        order_id = str(order.get("order_id") or state.get("order_id_hint") or "")
        decision_confidence = self._decision_confidence(
            visual_confidence,
            trusted_policy_hits,
            auto_approved,
        )
        best_policy_score = self._best_policy_score(trusted_policy_hits)
        payload = {
            "user_id": state.get("user_id"),
            "session_id": state.get("session_id"),
            "ticket_id": state.get("ticket_id"),
            "review_request_id": state.get("review_request_id"),
            "order_id": order_id,
            "verdict": "APPROVE" if auto_approved else "MANUAL_REVIEW_REQUIRED",
            "ai_review_confidence": decision_confidence,
            "reason": reason,
            "evidence_needed": evidence_needed,
            "visual_uncertain": visual_uncertain,
            "policy_uncertain": policy_uncertain,
            "evidence_consistent": evidence_consistent,
            "visual_confidence": visual_confidence,
            "risk_review_reasons": risk_review_reasons,
            "knowledge_retrieval_mode": knowledge.get("mode") if isinstance(knowledge, dict) else None,
            "filter_level": knowledge.get("filter_level") if isinstance(knowledge, dict) else None,
            "reranker_succeeded": knowledge.get("reranker_succeeded") is True if isinstance(knowledge, dict) else False,
            "trusted_policy_eligible": bool(auto_approved and trusted_policy_hits),
            "policy_version": str(order.get("policy_version") or "").strip() or None,
            "policy_match_score": best_policy_score,
            "skill_versions": state.get("skill_versions") or {},
            "policy_citations": self._policy_citations(trusted_policy_hits if auto_approved else policy_hits),
            "image_review": review if isinstance(review, dict) else None,
        }
        AGENT_RUNTIME_METRICS.record_rag_mode(
            knowledge.get("mode") if isinstance(knowledge, dict) else None
        )
        AGENT_RUNTIME_METRICS.record_review(payload["verdict"])
        state["evidence_needed"] = evidence_needed

        state["need_human"] = review_requires_human and not auto_approved
        self._log_ticket_decision(
            state=state,
            order=order,
            review=review,
            policy_hits=policy_hits,
            policy_uncertain=policy_uncertain,
            visual_confidence=visual_confidence,
            evidence_consistent=evidence_consistent,
            risk_review_reasons=risk_review_reasons,
            emotion_priority=emotion_priority,
            auto_approved=auto_approved,
            evidence_needed=evidence_needed,
        )

        return {
            "action": "tool_call",
            "tool_name": "submit_ai_review",
            "tool_arguments": payload,
            "need_human": review_requires_human and not auto_approved,
            "evidence_needed": evidence_needed,
        }

    @staticmethod
    def _log_ticket_decision(
        *,
        state: AgentGraphState,
        order: dict[str, Any],
        review: Any,
        policy_hits: list[dict[str, Any]],
        policy_uncertain: bool,
        visual_confidence: float,
        evidence_consistent: bool | None,
        risk_review_reasons: list[str],
        emotion_priority: bool,
        auto_approved: bool,
        evidence_needed: list[str],
    ) -> None:
        """Log decision inputs without leaking image payloads or full model output."""
        logger.info(
            "after_sales_ticket_decision order_id=%s attachments=%d vision_success=%s "
            "image_damage=%s visual_confidence=%.3f evidence_consistent=%s "
            "policy_hits=%d policy_uncertain=%s risk_reasons=%s emotion_priority=%s "
            "auto_approved=%s evidence_needed=%s",
            order.get("order_id") or state.get("order_id_hint"),
            len(state.get("attachments") or []),
            review.get("success") if isinstance(review, dict) else False,
            review.get("has_damage_area") if isinstance(review, dict) else False,
            visual_confidence,
            evidence_consistent,
            len(policy_hits),
            policy_uncertain,
            risk_review_reasons,
            emotion_priority,
            auto_approved,
            evidence_needed,
        )

    def _retrieve_policy_action(self, state: AgentGraphState, order: dict[str, Any]) -> dict[str, Any]:
        reason = self._reason_type(state)
        after_sales_type = self._after_sales_type(state)
        category = order.get("category") or order.get("product_category")
        merchant_code = str(order.get("merchant_code") or "").strip()
        as_of_time = order.get("after_sales_applied_at") or order.get("create_time")
        if not merchant_code or not str(as_of_time or "").strip():
            return {
                "action": "human_handoff",
                "assistant_reply": "当前售后申请缺少可验证的商家或业务发生时间，无法安全匹配当时生效的政策，我会转交人工客服复核。",
                "need_human": True,
                "evidence_needed": [],
            }
        scene = self._scene_for_reason(reason)
        intent = self._intent_for_type(after_sales_type)
        policy_version = str(order.get("policy_version") or "").strip()
        if not policy_version:
            return {
                "action": "tool_call",
                "tool_name": "submit_ai_review",
                "tool_arguments": {
                    "user_id": state.get("user_id"),
                    "session_id": state.get("session_id"),
                    "ticket_id": state.get("ticket_id"),
                    "review_request_id": state.get("review_request_id"),
                    "order_id": order.get("order_id") or state.get("order_id_hint"),
                    "verdict": "MANUAL_REVIEW_REQUIRED",
                    "ai_review_confidence": 0.0,
                    "reason": "工单缺少创建时保存的政策版本，禁止自动审核，需人工复核。",
                    "evidence_needed": [],
                    "visual_uncertain": False,
                    "policy_uncertain": True,
                    "evidence_consistent": False,
                    "visual_confidence": 0.0,
                    "risk_review_reasons": ["missing_ticket_policy_snapshot"],
                    "policy_citations": [],
                    "policy_version": None,
                    "image_review": None,
                },
                "assistant_reply": "",
                "need_human": True,
                "evidence_needed": [],
            }
        query_parts = [
            self._conversation_issue_text(state),
            str(order.get("product_name") or ""),
            str(category or ""),
            scene,
            after_sales_type,
            self._rag_query_expansion(reason, after_sales_type),
            "售后政策 凭证要求 审核规则",
        ]
        return {
            "action": "tool_call",
            "tool_name": "retrieve_knowledge",
            "tool_arguments": {
                "user_id": state.get("user_id"),
                "query": " ".join(part for part in query_parts if part).strip(),
                "merchant_code": merchant_code,
                "product_category": category,
                "scene": scene,
                "intent": intent,
                "source_type": "after_sales_policy",
                "policy_version": policy_version,
                "as_of_time": as_of_time,
                "top_k": 5,
            },
            "need_human": False,
            "evidence_needed": [],
        }

    def _retrieve_evidence_action(self, state: AgentGraphState, order: dict[str, Any]) -> dict[str, Any]:
        """RAG 检索证据模板 — 提前到决策阶段调用，用语义匹配替代硬编码关键词。"""
        reason = self._reason_type(state)
        product_name = str(order.get("product_name") or "")
        category = order.get("category") or order.get("product_category") or ""
        merchant_code = str(order.get("merchant_code") or "").strip() or None
        message = self._conversation_issue_text(state)
        query_parts = [
            message,
            product_name,
            category,
            self._scene_for_reason(reason),
            self._rag_query_expansion(reason, self._after_sales_type(state)),
            "售后证据要求 凭证模板 需要什么照片",
        ]
        tool_arguments = {
            "user_id": state.get("user_id"),
            "query": " ".join(p for p in query_parts if p).strip(),
            "merchant_code": merchant_code,
            "product_category": category if category else None,
            "scene": self._scene_for_reason(reason),
            "top_k": 5,
        }
        order_created_at = order.get("create_time")
        if str(order_created_at or "").strip():
            tool_arguments["as_of_time"] = order_created_at
        policy_version = order.get("policy_version")
        if str(policy_version or "").strip():
            tool_arguments["policy_version"] = policy_version
        return {
            "action": "tool_call",
            "tool_name": "retrieve_knowledge",
            "tool_arguments": tool_arguments,
            "need_human": False,
            "evidence_needed": [],
        }

    def _build_evidence_needed(self, state: AgentGraphState, order: dict[str, Any]) -> list[str]:
        """从 RAG 结果 + 订单上下文动态生成 evidence_needed，替代硬编码 _missing_evidence。"""
        knowledge = self._latest_tool_data(state, "retrieve_knowledge")
        product_name = str(order.get("product_name") or "")
        category = str(order.get("category") or order.get("product_category") or "")

        # 尝试从 RAG 知识库提取场景级证据模板
        scene_evidence = self._extract_scene_evidence(knowledge)
        if scene_evidence:
            logger.info("   📋 RAG 命中场景证据模板: %s", scene_evidence)
            return self._subtract_satisfied_evidence(scene_evidence, state, order)

        # RAG 未命中 → LLM 根据品类+问题描述常识推断
        logger.info("   📋 RAG 未命中场景证据, LLM 常识推断 (品类=%s 商品=%s)", category, product_name)
        return self._subtract_satisfied_evidence(["商品问题照片", "问题描述"], state, order)

    @staticmethod
    def _subtract_satisfied_evidence(required: list[str], state: AgentGraphState, order: dict[str, Any]) -> list[str]:
        satisfied = LangGraphAfterSalesAgent._satisfied_evidence_keys(state, order)
        missing: list[str] = []
        for item in required:
            text = str(item or "").strip()
            if not text:
                continue
            keys = LangGraphAfterSalesAgent._evidence_keys(text)
            if keys and keys.issubset(satisfied):
                continue
            if keys and keys.intersection(satisfied):
                continue
            if text not in missing:
                missing.append(text)
        return missing

    @staticmethod
    def _satisfied_evidence_keys(state: AgentGraphState, order: dict[str, Any]) -> set[str]:
        keys: set[str] = set()
        message = str(state.get("message") or "").strip()
        if len(message) >= 4:
            keys.add("description")

        attachments = state.get("attachments") or []
        if attachments:
            keys.update({"image", "product_image"})

        review = LangGraphAfterSalesAgent._latest_tool_data(state, "review_images")
        if isinstance(review, dict) and review.get("success"):
            if review.get("has_damage_area"):
                keys.update({"image", "product_image", "damage_image"})
            if review.get("has_outer_package"):
                keys.add("package_image")
            if review.get("has_logistics_label"):
                keys.add("logistics_label")

        context = state.get("client_context") if isinstance(state.get("client_context"), dict) else {}
        selected = context.get("selected_order_hint") if isinstance(context.get("selected_order_hint"), dict) else {}
        uploaded = []
        for source in (order, selected):
            value = source.get("uploaded_evidence") or source.get("uploadedEvidence")
            if isinstance(value, list):
                uploaded.extend(value)
            elif value:
                uploaded.append(value)
        for item in uploaded:
            keys.update(LangGraphAfterSalesAgent._evidence_keys(str(item)))
        return keys

    @staticmethod
    def _evidence_keys(text: str) -> set[str]:
        normalized = str(text or "")
        keys: set[str] = set()
        if any(word in normalized for word in ("描述", "说明", "问题现象", "情况")):
            keys.add("description")
        if any(word in normalized for word in ("照片", "图片", "图", "影像", "视频", "凭证")):
            keys.add("image")
        if any(word in normalized for word in ("商品", "问题照片", "问题图片", "实物", "耳机", "产品")):
            keys.update({"image", "product_image"})
        if any(word in normalized for word in ("破损", "损坏", "破裂", "裂纹", "外壳", "碎", "断")):
            keys.update({"image", "product_image", "damage_image"})
        if any(word in normalized for word in ("包装", "外包装")):
            keys.update({"image", "package_image"})
        if any(word in normalized for word in ("物流", "面单", "运单", "快递单")):
            keys.update({"image", "logistics_label"})
        return keys

    def _build_evidence_guidance(self, state: AgentGraphState, order: dict[str, Any], evidence_needed: list[str]) -> str:
        """Build deterministic guidance for a rule-decided missing-evidence path.

        The rule and RAG layers have already chosen the evidence list here, so a
        third 7B call only rewrites tone and adds roughly 1.2s in the measured
        hot path. Keep the wording deterministic; complex or uncertain cases
        still use the normal Agent/model route.
        """
        product_name = str(order.get("product_name") or "该商品")
        items_text = "、".join(evidence_needed) if evidence_needed else "相关凭证"
        if not evidence_needed:
            return "已了解您的问题。请补充相关凭证以便为您处理售后。"
        return f"已收到您关于{product_name}的售后咨询。为了继续核实并处理，请补充上传{items_text}。"

    @staticmethod
    def _extract_scene_evidence(knowledge: Any) -> list[str] | None:
        """从 RAG 知识库 hits 中提取场景级证据模板。"""
        if not isinstance(knowledge, dict):
            return None
        hits = knowledge.get("hits")
        if not isinstance(hits, list) or not hits:
            return None
        # 遍历 hits 寻找 scene_evidence_knowledge 或 default_evidence 字段
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            metadata = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
            # 检查 metadata 中的 default_evidence
            evidence = metadata.get("default_evidence")
            if isinstance(evidence, list) and evidence:
                return [str(item) for item in evidence if str(item).strip()]
            # 检查 snippet/content 中是否包含证据关键词
            snippet = str(hit.get("snippet") or "")
            title = str(hit.get("title") or "")
            combined = f"{title} {snippet}"
            if any(kw in combined for kw in ("需要提供", "请上传", "凭证", "照片", "证据要求")):
                # 从文本中提取可能的证据项
                items = _extract_evidence_from_text(combined)
                if items:
                    return items
        return None

    def _review_images_action(self, state: AgentGraphState, order: dict[str, Any]) -> dict[str, Any]:
        return {
            "action": "tool_call",
            "tool_name": "review_images",
            "tool_arguments": {
                "user_id": state.get("user_id"),
                "order_id": order.get("order_id"),
                "attachments": state.get("attachments") or [],
                "order_hint": self._order_hint(order),
            },
            "need_human": False,
            "evidence_needed": [],
        }

    @classmethod
    def _apply_action(cls, state: AgentGraphState, raw: dict[str, Any]) -> None:
        action = str(raw.get("action") or "final_reply")
        function_call_mode = raw.get("_function_call_mode")
        provider_tool_call_shape = raw.get("_provider_tool_call_shape")
        if (
            function_call_mode == "native"
            and provider_tool_call_shape in {"openai", "ollama"}
        ):
            state["current_function_call_mode"] = "native"
            state["current_provider_tool_call_shape"] = str(provider_tool_call_shape)
        elif (
            function_call_mode == "legacy"
            and provider_tool_call_shape == "legacy_json"
        ):
            state["current_function_call_mode"] = "legacy"
            state["current_provider_tool_call_shape"] = "legacy_json"
        else:
            state["current_function_call_mode"] = "deterministic"
            state["current_provider_tool_call_shape"] = "none"
        if not raw.get("tool_call_id"):
            LangGraphAfterSalesAgent._clear_pending_tool_call(state)
        state["next_action"] = action
        state["tool_name"] = raw.get("tool_name")
        arguments = raw.get("tool_arguments") if isinstance(raw.get("tool_arguments"), dict) else {}
        arguments["user_id"] = state.get("user_id")
        if state.get("session_id") is not None:
            arguments["session_id"] = state.get("session_id")
        if state.get("order_id_hint"):
            arguments["order_id"] = state.get("order_id_hint")
        if state.get("ticket_id"):
            arguments["ticket_id"] = state.get("ticket_id")
        if state.get("review_request_id"):
            arguments["review_request_id"] = state.get("review_request_id")
        state["tool_arguments"] = arguments
        if action == "tool_call" and str(state.get("tool_name") or "") == "submit_ai_review" and not state.get("allow_ai_review_submit"):
            state["next_action"] = "final_reply"
            state["tool_name"] = None
            state["tool_arguments"] = {}
            state["assistant_reply"] = "您的售后申请已提交，AI初审正在后台排队处理；我会先保存当前沟通内容，不会在聊天里重复触发审核。"
            state["need_human"] = False
            if isinstance(raw.get("evidence_needed"), list):
                state["evidence_needed"] = [str(item) for item in raw["evidence_needed"]]
            logger.info("agent_tool_guard tool=submit_ai_review error_category=source_not_kafka")
            return
        if raw.get("assistant_reply"):
            sanitized = cls._sanitize_reply(raw.get("assistant_reply"))
            if sanitized:
                state["assistant_reply"] = sanitized
            # 如果被 sanitize 掉了（variant="silent" 返回空），保留原有 reply 不改
            else:
                pass
        if isinstance(raw.get("evidence_needed"), list):
            state["evidence_needed"] = [str(item) for item in raw["evidence_needed"]]
        state["need_human"] = bool(raw.get("need_human") or action == "human_handoff")

    @staticmethod
    def _claims_review_completed(reply: Any) -> bool:
        text = str(reply or "").lower()
        keywords = ("初审通过", "ai初审已完成", "已完成ai初审", "已进入处理中", "进入处理中", "review approved", "review completed")
        return any(keyword.lower() in text for keyword in keywords)

    @staticmethod
    def _has_successful_tool(state: AgentGraphState, tool_name: str) -> bool:
        if tool_name == "handoff_to_human":
            return any(
                item.get("tool") == tool_name
                and LangGraphAfterSalesAgent._is_successful_handoff_trace(item)
                for item in state.get("tool_results") or []
            )
        return any(item.get("tool") == tool_name and item.get("ok") for item in state.get("tool_results") or [])

    @staticmethod
    def _is_successful_handoff_result(result: ToolResult) -> bool:
        if not result.ok or not isinstance(result.data, dict):
            return False
        return LangGraphAfterSalesAgent._is_human_waiting_session(result.data)

    @staticmethod
    def _is_successful_handoff_trace(item: dict[str, Any]) -> bool:
        if not item.get("ok"):
            return False
        data = item.get("data")
        return isinstance(data, dict) and LangGraphAfterSalesAgent._is_human_waiting_session(data)

    @staticmethod
    def _is_human_waiting_session(data: dict[str, Any]) -> bool:
        mode = str(data.get("mode") or data.get("session_mode") or data.get("sessionMode") or "").upper()
        status = str(data.get("status") or "").upper()
        return mode == "HUMAN" and status in {"WAITING", "PROCESSING"}

    @staticmethod
    def _has_tool_result(state: AgentGraphState, tool_name: str) -> bool:
        return any(item.get("tool") == tool_name for item in state.get("tool_results") or [])

    @staticmethod
    def _latest_tool_result(state: AgentGraphState) -> dict[str, Any] | None:
        results = state.get("tool_results") or []
        latest = results[-1] if results else None
        return latest if isinstance(latest, dict) else None

    @staticmethod
    def _tool_attempts(state: AgentGraphState, tool_name: str, arguments: dict[str, Any] | None = None) -> int:
        expected = json.dumps(arguments or {}, ensure_ascii=False, sort_keys=True, default=str)
        attempts = 0
        for item in state.get("tool_results") or []:
            if item.get("tool") != tool_name:
                continue
            if arguments is not None:
                actual = json.dumps(item.get("arguments") or {}, ensure_ascii=False, sort_keys=True, default=str)
                if actual != expected:
                    continue
            attempts += 1
        return attempts

    def _can_retry_tool(self, tool: str, arguments: dict[str, Any]) -> bool:
        if os.getenv("AI_REVIEW_FAST_RETRY_ENABLED", "false").strip().lower() not in {"1", "true", "yes", "on"}:
            return False
        if tool in self.SAFE_RETRY_TOOLS:
            return True
        if tool == "submit_ai_review":
            return bool(arguments.get("review_request_id"))
        if tool == "append_chat_message":
            return bool(arguments.get("message_id"))
        if tool == "handoff_to_human":
            return bool(
                arguments.get("ticket_id")
                and arguments.get("session_id")
            )
        return False

    @staticmethod
    def _fast_retry_max_attempts() -> int:
        try:
            return max(0, int(os.getenv("AI_REVIEW_FAST_RETRY_MAX_ATTEMPTS", "1")))
        except ValueError:
            return 1

    @staticmethod
    def _latest_tool_data(state: AgentGraphState, tool_name: str) -> Any:
        for item in reversed(state.get("tool_results") or []):
            if item.get("tool") == tool_name and item.get("ok"):
                return item.get("data")
        return None

    @staticmethod
    def _classify_tool_error(error: str | None) -> str:
        text = str(error or "").lower()
        if not text:
            return "unknown"
        if "limit" in text or "duplicate" in text or "tool_call_limit" in text:
            return "guard_limit"
        if "timeout" in text or "timed out" in text:
            return "timeout"
        if "not found" in text or "404" in text:
            return "not_found"
        if "permission" in text or "forbidden" in text or "403" in text or "unauthorized" in text or "401" in text:
            return "permission"
        if "required" in text or "invalid" in text or "400" in text:
            return "validation"
        if "connection" in text or "connect" in text or "refused" in text or "unavailable" in text:
            return "service_unavailable"
        return "tool_error"

    @staticmethod
    def _build_tool_observation(tool: str, ok: bool, data: Any, error: str | None) -> dict[str, Any]:
        observation: dict[str, Any] = {
            "tool": tool,
            "ok": ok,
        }
        if not ok:
            observation["error_type"] = LangGraphAfterSalesAgent._classify_tool_error(error)
            observation["error"] = str(error or "")[:160]
            return observation

        if tool == "search_user_orders":
            orders = data if isinstance(data, list) else []
            observation["orders_found"] = len(orders)
            observation["empty"] = len(orders) == 0
            observation["single_match"] = len(orders) == 1
        elif tool == "get_order_detail" and isinstance(data, dict):
            observation["order_found"] = True
            observation["order_id"] = data.get("order_id")
            observation["status"] = data.get("status")
            observation["existing_ticket_no"] = data.get("existing_ticket_no")
        elif tool == "get_existing_after_sales":
            observation["existing_ticket_found"] = isinstance(data, dict) and bool(data)
        elif tool == "retrieve_knowledge" and isinstance(data, dict):
            hits = data.get("hits") if isinstance(data.get("hits"), list) else []
            observation["mode"] = data.get("mode")
            observation["hits_count"] = len(hits)
            observation["has_policy"] = bool(hits)
        elif tool == "review_images" and isinstance(data, dict):
            observation["success"] = bool(data.get("success"))
            observation["has_damage_area"] = bool(data.get("has_damage_area"))
            observation["has_outer_package"] = bool(data.get("has_outer_package"))
            observation["has_logistics_label"] = bool(data.get("has_logistics_label"))
            observation["missing_visual_evidence"] = data.get("missing_visual_evidence") or []
        elif tool == "get_after_sales_ticket" and isinstance(data, dict):
            observation["ticket_found"] = True
            observation["ticket_no"] = data.get("ticket_no")
            observation["status"] = data.get("status")
            observation["existing"] = bool(data.get("existing"))
        elif tool == "submit_ai_review" and isinstance(data, dict):
            observation["review_submitted"] = True
            observation["verdict"] = data.get("verdict") or data.get("ai_review_result")
            observation["ticket_no"] = data.get("ticket_no")
            observation["status"] = data.get("status")
        elif tool == "handoff_to_human":
            observation["session_mode"] = "HUMAN"
        elif tool == "append_chat_message" and isinstance(data, dict):
            observation["message_saved"] = True
            observation["session_id"] = data.get("session_id")
        else:
            observation["data_type"] = type(data).__name__
        return observation

    @staticmethod
    def _has_empty_order_search(state: AgentGraphState) -> bool:
        if LangGraphAfterSalesAgent._has_successful_tool(state, "get_order_detail"):
            return False
        for item in state.get("tool_results") or []:
            if item.get("tool") != "search_user_orders" or not item.get("ok"):
                continue
            data = item.get("data")
            return isinstance(data, list) and not data
        return False

    @staticmethod
    def _has_failed_order_search(state: AgentGraphState) -> bool:
        return any(item.get("tool") == "search_user_orders" and not item.get("ok") for item in state.get("tool_results") or [])

    @staticmethod
    def _order_lookup_action(state: AgentGraphState) -> dict[str, Any]:
        return {
            "action": "tool_call",
            "tool_name": "search_user_orders",
            "tool_arguments": {
                "user_id": state.get("user_id"),
                "keyword": state.get("order_id_hint") or state.get("message") or "",
            },
            "assistant_reply": "",
            "need_human": False,
            "evidence_needed": [],
        }

    @staticmethod
    def _get_ticket_action(state: AgentGraphState) -> dict[str, Any]:
        return {
            "action": "tool_call",
            "tool_name": "get_after_sales_ticket",
            "tool_arguments": {
                "user_id": state.get("user_id"),
                "ticket_id": state.get("ticket_id"),
                "order_id": state.get("order_id_hint"),
            },
            "assistant_reply": "",
            "need_human": False,
            "evidence_needed": [],
        }

    @staticmethod
    def _selected_order(state: AgentGraphState) -> dict[str, Any] | None:
        order_detail = LangGraphAfterSalesAgent._latest_tool_data(state, "get_order_detail")
        if isinstance(order_detail, dict):
            return order_detail
        orders = LangGraphAfterSalesAgent._latest_tool_data(state, "search_user_orders")
        if not isinstance(orders, list) or not orders:
            return None
        hint = str(state.get("order_id_hint") or "")
        if hint:
            for order in orders:
                if not isinstance(order, dict):
                    continue
                if hint in {
                    str(order.get("order_id") or ""),
                    str(order.get("order_no") or ""),
                }:
                    return order
        dict_orders = [order for order in orders if isinstance(order, dict)]
        return dict_orders[0] if len(dict_orders) == 1 else None

    @staticmethod
    def _existing_ticket_no(order: dict[str, Any] | None) -> str | None:
        if not isinstance(order, dict):
            return None
        ticket_no = order.get("existing_ticket_no")
        return str(ticket_no) if ticket_no else None

    @staticmethod
    def _ticket_from_existing_order(order: dict[str, Any]) -> dict[str, Any]:
        ticket_no = LangGraphAfterSalesAgent._existing_ticket_no(order)
        return {
            "ticket_id": order.get("existing_ticket_id"),
            "ticket_no": ticket_no,
            "status": order.get("after_sales_status") or order.get("existing_ticket_status") or "PENDING_REVIEW",
            "existing": True,
        }

    @staticmethod
    def _order_from_ticket(ticket: dict[str, Any]) -> dict[str, Any]:
        return {
            "order_id": ticket.get("order_id"),
            "order_no": ticket.get("order_no"),
            "product_name": ticket.get("product_name"),
            "product_category": ticket.get("product_category") or ticket.get("category"),
            "category": ticket.get("category") or ticket.get("product_category"),
            "merchant_code": ticket.get("merchant_code"),
            "policy_version": ticket.get("policy_version"),
            "after_sales_applied_at": ticket.get("after_sales_applied_at") or ticket.get("create_time"),
            "amount": ticket.get("refund_amount"),
        }

    @staticmethod
    def _ticket_has_uploaded_images(ticket: dict[str, Any]) -> bool:
        for key in ("attachmentUrls", "attachment_urls", "attachments", "images", "imageUrls", "image_urls"):
            value = ticket.get(key)
            if isinstance(value, list) and value:
                return True
            if isinstance(value, str) and value.strip():
                return True
        return False

    @staticmethod
    def _order_hint(order: dict[str, Any]) -> str:
        return f"订单号：{order.get('order_no') or ''}；商品：{order.get('product_name') or ''}"

    @staticmethod
    def _mentions_visible_damage(state: AgentGraphState) -> bool:
        text = LangGraphAfterSalesAgent._conversation_issue_text(state)
        return bool(re.search(r"破|裂|坏|损|碎|断|电流|异响|噪", text))

    @staticmethod
    def _after_sales_type(state: AgentGraphState) -> str:
        text = str(state.get("message") or "")
        if "换" in text:
            return "EXCHANGE"
        if "补发" in text:
            return "REISSUE"
        if "退款" in text or "退货" in text:
            return "RETURN_REFUND"
        return "RETURN_REFUND"

    @staticmethod
    def _reason_type(state: AgentGraphState) -> str:
        text = LangGraphAfterSalesAgent._conversation_issue_text(state)
        if any(word in text for word in ("破", "裂", "坏", "损", "碎", "断")):
            return "DAMAGE"
        if any(word in text for word in ("质量", "电流", "异响", "噪", "充电", "充不", "充了", "掉电", "耗电", "续航", "开不了机", "无法开机", "死机", "重启", "卡顿")):
            return "QUALITY"
        return "OTHER"

    @staticmethod
    def _conversation_issue_text(state: AgentGraphState) -> str:
        parts = [str(state.get("message") or "")]
        for item in reversed(state.get("recent_history") or []):
            if str(item.get("role") or "").lower() == "user":
                content = str(item.get("content") or "").strip()
                if content and content != "[图片]":
                    parts.append(content)
                    break
        return " ".join(parts)

    @staticmethod
    def _quality_visual_handoff_action(state: AgentGraphState) -> dict[str, Any] | None:
        if not LangGraphAfterSalesAgent._quality_visual_unverifiable(state):
            return None
        return {
            "action": "human_handoff",
            "assistant_reply": "您描述的是功能类质量问题，当前图片无法直接核验问题现象，我会为您转接人工客服继续处理。",
            "need_human": True,
            "evidence_needed": [],
        }

    @staticmethod
    def _quality_visual_unverifiable(state: AgentGraphState) -> bool:
        if not state.get("attachments"):
            return False
        if not LangGraphAfterSalesAgent._mentions_functional_quality_issue(state):
            return False
        review = LangGraphAfterSalesAgent._latest_tool_data(state, "review_images")
        if not isinstance(review, dict):
            return False
        if not review.get("success"):
            return True
        if review.get("has_damage_area"):
            return False
        return True

    @staticmethod
    def _mentions_functional_quality_issue(state: AgentGraphState) -> bool:
        text = LangGraphAfterSalesAgent._conversation_issue_text(state)
        markers = (
            "充电", "充不", "充了", "冲了", "掉电", "耗电", "电池", "续航", "电量",
            "电流声", "异响", "杂音", "噪音", "破音",
            "开不了机", "无法开机", "死机", "重启", "卡顿", "闪屏",
            "无声", "没声音", "单边无声", "连接不上", "断连", "蓝牙",
            "按键失灵", "触控失灵", "功能", "故障", "质量问题",
        )
        return any(marker in text for marker in markers)

    @staticmethod
    def _review_missing_damage(review: Any) -> bool:
        if not isinstance(review, dict) or review.get("has_damage_area"):
            return False
        missing = review.get("missing_visual_evidence")
        return isinstance(missing, list) and any("破损" in str(item) or "损坏" in str(item) for item in missing)

    @staticmethod
    def _evidence_refs(state: AgentGraphState) -> list[str]:
        refs: list[str] = []
        for index, item in enumerate(state.get("attachments") or [], start=1):
            if not isinstance(item, dict):
                continue
            refs.append(str(item.get("name") or f"uploaded_image_{index}.jpg"))
        return refs

    @staticmethod
    def _visual_confidence(review: Any) -> float:
        if not isinstance(review, dict):
            return 0.0
        values = []
        for item in review.get("items") or []:
            if isinstance(item, dict):
                try:
                    value = item.get("damage_confidence")
                    if value is None:
                        value = item.get("confidence")
                    values.append(float(value or 0.0))
                except (TypeError, ValueError):
                    pass
        return max(values, default=0.0)

    @staticmethod
    def _evidence_consistent(state: AgentGraphState, review: Any) -> bool | None:
        claims_damage = LangGraphAfterSalesAgent._mentions_visible_damage(state)
        if LangGraphAfterSalesAgent._mentions_functional_quality_issue(state):
            return False
        if not claims_damage:
            return None
        return bool(isinstance(review, dict) and review.get("success") and review.get("has_damage_area"))

    @staticmethod
    def _needs_problem_image_evidence(state: AgentGraphState) -> bool:
        return (
            LangGraphAfterSalesAgent._mentions_visible_damage(state)
            or LangGraphAfterSalesAgent._mentions_functional_quality_issue(state)
        )

    @staticmethod
    def _evidence_audit(state: AgentGraphState) -> list[dict[str, Any]]:
        audit: list[dict[str, Any]] = []
        for index, item in enumerate(state.get("attachments") or [], start=1):
            if not isinstance(item, dict):
                continue
            source = str(item.get("source") or "")
            content = source
            if source.startswith("data:") and "," in source:
                try:
                    content = base64.b64decode(source.split(",", 1)[1], validate=False)
                except Exception:
                    content = source.encode("utf-8")
            elif isinstance(content, str):
                content = content.encode("utf-8")
            audit.append({
                "index": index,
                "name": str(item.get("name") or f"image_{index}"),
                "sha256": hashlib.sha256(content).hexdigest(),
            })
        return audit

    @staticmethod
    def _risk_review_reasons(state: AgentGraphState, order: dict[str, Any]) -> list[str]:
        """Deterministic guardrails that must pass before any model-led approval."""
        reasons: list[str] = []
        try:
            amount = float(order.get("amount") or order.get("orderAmount") or 0)
        except (TypeError, ValueError):
            amount = 0.0
        limit = float(os.getenv("AGENT_AUTO_REFUND_LIMIT", "50"))
        if amount > limit:
            reasons.append("refund_amount_above_auto_limit")

        hashes = [item["sha256"] for item in LangGraphAfterSalesAgent._evidence_audit(state)]
        if hashes and len(hashes) != len(set(hashes)):
            reasons.append("duplicate_evidence_in_request")
        return reasons

    @staticmethod
    def _emotion_context(state: AgentGraphState) -> dict[str, Any]:
        client_context = state.get("client_context") or {}
        emotion = client_context.get("emotion") if isinstance(client_context, dict) else None
        return emotion if isinstance(emotion, dict) else {}

    @staticmethod
    def _visual_review_reason(
        *,
        visual_uncertain: bool,
        policy_uncertain: bool,
        evidence_consistent: bool | None,
        visual_confidence: float,
        minimum_visual_confidence: float,
    ) -> str:
        reasons: list[str] = []
        if visual_uncertain:
            reasons.append("visual_uncertain")
        if policy_uncertain:
            reasons.append("policy_uncertain")
        if evidence_consistent is not True:
            reasons.append("claim_visual_mismatch")
        if visual_confidence < minimum_visual_confidence:
            reasons.append("visual_confidence_below_threshold")
        return ",".join(reasons) or "auto_approve_conditions_satisfied"

    @staticmethod
    def _ai_suggestion_reason(
        state: AgentGraphState,
        review: Any,
        knowledge: Any,
        auto_approved: bool,
        visual_uncertain: bool,
        policy_uncertain: bool,
        evidence_needed: list[str],
    ) -> str:
        policy_summary = LangGraphAfterSalesAgent._policy_summary(knowledge)
        if auto_approved:
            return (
                "用户描述为商品损坏/质量问题，图片审核可见对应破损；"
                f"知识库政策依据：{policy_summary}；"
                "建议通过售后申请并进入处理中，最终由人工完成处理。"
            )
        if visual_uncertain:
            return "用户已提交售后申请，但图片审核无法确认图片与描述一致，建议人工复核。"
        if policy_uncertain:
            return "用户已提交售后申请，但知识库未命中明确售后政策或凭证规则，建议人工复核。"
        if evidence_needed:
            return f"知识库政策依据：{policy_summary}；当前证据仍不完整，需补充：" + "、".join(evidence_needed)
        return f"用户已提交售后申请，知识库政策依据：{policy_summary}；等待人工审核。"

    @staticmethod
    def _policy_hits(knowledge: Any) -> list[dict[str, Any]]:
        if not isinstance(knowledge, dict):
            return []
        hits = knowledge.get("hits")
        if not isinstance(hits, list):
            return []
        return [hit for hit in hits if isinstance(hit, dict)]

    @staticmethod
    def _trusted_policy_hits(
        knowledge: Any,
        order: dict[str, Any],
        history_summary: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Return only policy evidence strong enough to authorize an automatic decision."""
        if not isinstance(knowledge, dict):
            return []
        if knowledge.get("reranker_succeeded") is not True:
            return []
        if knowledge.get("filter_level") != "strict":
            return []
        if knowledge.get("no_answer") is True:
            return []
        if knowledge.get("trusted_policy_eligible") is not True:
            return []
        if knowledge.get("relaxation_level") != "strict":
            return []
        merchant_code = str(order.get("merchant_code") or "").strip()
        if not merchant_code:
            return []
        expected_policy_version = str(order.get("policy_version") or "").strip()
        business_time = LangGraphAfterSalesAgent._parse_offset_time(
            order.get("after_sales_applied_at") or order.get("create_time")
        )
        if not expected_policy_version or business_time is None:
            return []
        minimum_score = float(os.getenv("RAG_AUTO_APPROVE_MIN_SCORE", "0.65"))
        trusted: list[dict[str, Any]] = []
        for hit in LangGraphAfterSalesAgent._policy_hits(knowledge):
            if hit.get("trusted_policy_eligible") is not True:
                continue
            if hit.get("relaxation_level") != "strict":
                continue
            citations = hit.get("citations")
            if not isinstance(citations, list) or not any(
                LangGraphAfterSalesAgent._is_traceable_citation(item) for item in citations
            ):
                continue
            metadata = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
            if str(hit.get("source_type") or metadata.get("source_type") or "") != "after_sales_policy":
                continue
            if str(hit.get("merchant_code") or metadata.get("merchant_code") or "") != merchant_code:
                continue
            policy_version = str(hit.get("policy_version") or metadata.get("policy_version") or "").strip()
            if policy_version != expected_policy_version:
                continue
            valid_from = LangGraphAfterSalesAgent._parse_policy_bound(
                hit.get("valid_from") or metadata.get("valid_from"),
                business_time,
            )
            valid_to = LangGraphAfterSalesAgent._parse_policy_bound(
                hit.get("valid_to") or metadata.get("valid_to"),
                business_time,
            )
            if valid_from is None or valid_to is None or not (valid_from <= business_time < valid_to):
                continue
            try:
                hit_threshold = float(hit.get("threshold", knowledge.get("threshold", minimum_score)))
            except (TypeError, ValueError):
                continue
            if LangGraphAfterSalesAgent._policy_hit_score(hit) < max(minimum_score, hit_threshold):
                continue
            trusted.append(hit)
        return trusted

    @staticmethod
    def _parse_offset_time(raw: Any) -> datetime | None:
        if not isinstance(raw, str) or not raw.strip():
            return None
        value = raw.strip()
        normalized = f"{value[:-1]}+00:00" if value.endswith(("Z", "z")) else value
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed

    @staticmethod
    def _parse_policy_bound(raw: Any, business_time: datetime) -> datetime | None:
        if not isinstance(raw, str) or not raw.strip():
            return None
        value = raw.strip()
        normalized = f"{value[:-1]}+00:00" if value.endswith(("Z", "z")) else value
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            parsed = parsed.replace(tzinfo=business_time.tzinfo)
        return parsed

    @staticmethod
    def _policy_hit_score(hit: dict[str, Any]) -> float:
        raw = hit.get("calibrated_policy_confidence")
        if raw is None:
            raw = hit.get("rerank_score")
        try:
            return max(0.0, min(float(raw or 0.0), 1.0))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _best_policy_score(hits: list[dict[str, Any]]) -> float:
        return round(max((LangGraphAfterSalesAgent._policy_hit_score(hit) for hit in hits), default=0.0), 4)

    @staticmethod
    def _decision_confidence(
        visual_confidence: float,
        trusted_policy_hits: list[dict[str, Any]],
        auto_approved: bool,
    ) -> float:
        visual_score = max(0.0, min(float(visual_confidence or 0.0), 1.0))
        policy_score = LangGraphAfterSalesAgent._best_policy_score(trusted_policy_hits)
        combined = (visual_score * 0.7) + (policy_score * 0.3)
        if auto_approved:
            return round(max(0.5, min(combined, 0.99)), 4)
        return round(max(0.0, min(combined, 0.69)), 4)

    @staticmethod
    def _policy_citations(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
        citations: list[dict[str, Any]] = []
        for hit in hits[:5]:
            explicit = hit.get("citations")
            if isinstance(explicit, list):
                citations.extend(
                    dict(item)
                    for item in explicit
                    if LangGraphAfterSalesAgent._is_traceable_citation(item)
                )
        return citations

    @staticmethod
    def _is_traceable_citation(value: Any) -> bool:
        if not isinstance(value, dict):
            return False
        source_code = str(value.get("source_code") or "").strip()
        trace_id = str(value.get("chunk_id") or value.get("document_id") or "").strip()
        return bool(source_code and trace_id)

    @staticmethod
    def _policy_summary(knowledge: Any) -> str:
        hits = LangGraphAfterSalesAgent._policy_hits(knowledge)
        if not hits:
            return "未命中明确政策"
        summaries: list[str] = []
        for hit in hits[:2]:
            title = str(hit.get("title") or hit.get("source_code") or "知识条目")
            snippet = str(hit.get("snippet") or "")
            summaries.append(f"{title}：{snippet[:80]}")
        return "；".join(summaries)

    @staticmethod
    def _scene_for_reason(reason: str) -> str:
        return {
            "DAMAGE": "damage",
            "QUALITY": "quality_issue",
            "LOGISTICS": "logistics_damage",
        }.get(reason, "after_sales")

    @staticmethod
    def _intent_for_type(after_sales_type: str) -> str:
        return {
            "RETURN_REFUND": "refund",
            "REFUND_ONLY": "refund",
            "EXCHANGE": "exchange",
            "REISSUE": "reissue",
        }.get(after_sales_type, "after_sales")

    @staticmethod
    def _rag_query_expansion(reason: str, after_sales_type: str) -> str:
        parts: list[str] = []
        if reason == "DAMAGE":
            parts.extend(["商品破损", "外壳破裂", "裂纹", "破损照片", "退货退款", "换货"])
        elif reason == "QUALITY":
            parts.extend(["质量问题", "功能故障", "电流声", "异响", "无法正常使用", "故障描述"])
        if after_sales_type in {"RETURN_REFUND", "REFUND_ONLY"}:
            parts.extend(["退款", "退货退款", "退款规则"])
        elif after_sales_type == "EXCHANGE":
            parts.extend(["换货", "换货规则"])
        return " ".join(parts)

    @staticmethod
    def _ticket_requires_handoff(state: AgentGraphState) -> bool:
        ticket = state.get("ticket")
        if not isinstance(ticket, dict):
            return False
        arguments = {}
        for item in reversed(state.get("tool_results") or []):
            if item.get("tool") == "submit_ai_review":
                arguments = item.get("arguments") if isinstance(item.get("arguments"), dict) else {}
                break
        verdict = str(arguments.get("verdict") or "").upper()
        return verdict == "MANUAL_REVIEW" or bool(arguments.get("visual_uncertain") or arguments.get("policy_uncertain"))

    @staticmethod
    def _ticket_reply(state: AgentGraphState) -> str | None:
        ticket = state.get("ticket")
        if not isinstance(ticket, dict):
            return None
        ticket_no = ticket.get("ticket_no")
        status = str(ticket.get("status") or "").upper()
        verdict = str(ticket.get("verdict") or ticket.get("ai_review_result") or "").upper()
        evidence_needed = state.get("evidence_needed") or []
        if status == "PROCESSING" or verdict == "APPROVE":
            return "您的售后申请已完成AI初审，当前已进入处理中，后续结果请留意进度通知。"
        if evidence_needed:
            return f"您的售后申请已完成AI初审，当前继续保持待审核状态。为便于继续审核，请补充：{'、'.join(evidence_needed)}。"
        ticket_label = f" {ticket_no}" if ticket_no else ""
        return f"已读取到您的售后申请{ticket_label}，当前继续保持待审核状态，客服会继续处理。"

    _JSON_LEAKAGE_PATTERNS: ClassVar[tuple[str, ...]] = (
        r'"tool"\s*:\s*"submit_ai_review"',
        r'"arguments"\s*:\s*\{',
        r'"user_id"\s*:\s*"\d{15,}"',
        r'"session_id"\s*:\s*\d{15,}',
        r'"verdict"\s*:\s*"',
        r'"ai_review_confidence"\s*:\s*[\d.]+',
        r'"review_request_id"\s*:\s*"',
        r'"image_review"\s*:\s*\{',
        r'data:image/[a-z]+;base64,',
    )

    @classmethod
    def _looks_like_json_leakage(cls, text: Any) -> bool:
        """检测 assistant_reply 是否像泄漏的 JSON/机器数据而非自然语言回复。"""
        if not isinstance(text, str) or not text.strip():
            return False
        stripped = text.strip()
        # 纯 JSON 开头
        if stripped.startswith("{") or stripped.startswith("["):
            return True
        # 包含工具调用的完整 JSON
        if "submit_ai_review" in stripped and '"tool"' in stripped:
            return True
        # 包含长数字 ID + JSON 键名
        for pattern in cls._JSON_LEAKAGE_PATTERNS:
            if re.search(pattern, text):
                return True
        return False

    _FALLBACK_REPLY: ClassVar[str] = (
        "已收到您的售后问题。正式售后申请请从对应订单详情页提交；已提交的申请会继续由系统和客服处理。"
    )

    @classmethod
    def _sanitize_reply(cls, reply: Any, variant: str = "default") -> str:
        """确保 reply 是自然语言而非泄漏的 JSON。"""
        text = str(reply or "").strip()
        if not text:
            return "" if variant == "silent" else cls._FALLBACK_REPLY
        if cls._looks_like_json_leakage(text):
            if variant == "silent":
                return ""
            return cls._FALLBACK_REPLY
        return text

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_ticket(ticket: Any) -> dict[str, Any] | None:
        if not isinstance(ticket, dict):
            return None
        ticket_id = ticket.get("ticket_id")
        ticket_no = ticket.get("ticket_no")
        status = str(ticket.get("status") or "").lower()
        return {
            "ticket_id": str(ticket_id) if ticket_id is not None else None,
            "ticket_no": str(ticket_no) if ticket_no is not None else None,
            "status": status,
            "order_id": str(ticket.get("order_id") or "") or None,
            "existing": bool(ticket.get("existing")),
        }
_EVIDENCE_PATTERNS = [
    r"(?:请|需要|还需|补充)(?:上传|提供|提交)?([^，。；\n]{2,30}?(?:照片|图片|视频|凭证|截图|标签|单据|证明))",
    r"(?:照片|图片|视频|凭证|截图|标签|单据|证明)[：:]*([^，。；\n]{2,20})",
]


def _extract_evidence_from_text(text: str) -> list[str] | None:
    """从 RAG 知识库文本中提取证据要求项，避免硬编码关键词。"""
    import re as _re
    items: list[str] = []
    for pattern in _EVIDENCE_PATTERNS:
        for match in _re.finditer(pattern, text):
            item = (match.group(1) or "").strip()
            if item and len(item) >= 2 and item not in items:
                items.append(item)
    return items if items else None
