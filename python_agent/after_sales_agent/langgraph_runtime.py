from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
import re
from typing import Any, ClassVar, Literal, TypedDict

from langgraph.graph import END, StateGraph

from .agent_tools import AfterSalesTools
from .services.llm import OpenAICompatibleClient, OpenAICompatibleConfig

logger = logging.getLogger("after_sales_agent.langgraph")


class AgentGraphState(TypedDict, total=False):
    user_id: str
    session_id: int | None
    message: str
    attachments: list[dict[str, Any]]
    order_id_hint: str | None
    recent_history: list[dict[str, str]]
    client_context: dict[str, Any]
    steps: int
    next_action: str
    tool_name: str | None
    tool_arguments: dict[str, Any]
    tool_results: list[dict[str, Any]]
    assistant_reply: str
    need_human: bool
    session_mode: str
    ticket: dict[str, Any] | None
    evidence_needed: list[str]
    explicit_human_request: bool
    final: bool


@dataclass
class LangGraphAfterSalesAgent:
    tools: AfterSalesTools = field(default_factory=AfterSalesTools)
    llm: OpenAICompatibleClient = field(
        default_factory=lambda: OpenAICompatibleClient(OpenAICompatibleConfig.from_env())
    )
    max_steps: int = 7

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

    def handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: AgentGraphState = {
            "user_id": str(payload.get("user_id") or payload.get("userId") or "0"),
            "session_id": self._optional_int(payload.get("session_id") or payload.get("sessionId")),
            "message": str(payload.get("message") or ""),
            "attachments": list(payload.get("attachments") or []),
            "order_id_hint": str(payload.get("order_id") or payload.get("orderId") or "") or None,
            "recent_history": list(payload.get("recent_history") or payload.get("recentHistory") or []),
            "client_context": dict(payload.get("client_context") or payload.get("clientContext") or {}),
            "steps": 0,
            "tool_results": [],
            "need_human": False,
            "session_mode": "AI",
            "ticket": None,
            "evidence_needed": [],
            "explicit_human_request": self._is_explicit_human_request(
                str(payload.get("message") or ""),
                list(payload.get("recent_history") or payload.get("recentHistory") or []),
            ),
            "final": False,
        }
        final_state = self.graph.invoke(state)
        normalized_ticket = self._normalize_ticket(final_state.get("ticket"))
        return {
            "assistant_reply": final_state.get("assistant_reply") or "",
            "session_mode": final_state.get("session_mode") or "AI",
            "tool_trace": final_state.get("tool_results") or [],
            "ticket": normalized_ticket,
            "need_human": bool(final_state.get("need_human")),
            "evidence_needed": final_state.get("evidence_needed") or [],
            "persistence": {
                "session_id": str(final_state.get("session_id")) if final_state.get("session_id") else None,
                "ticket_no": normalized_ticket.get("ticket_id") if normalized_ticket else None,
            },
            "raw": {
                "runtime": "langgraph_react",
                "steps": final_state.get("steps") or 0,
            },
        }

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
        msg = str(state.get("message") or "")
        logger.info("=" * 70)
        logger.info("🔍 [classify_or_plan] 用户消息: %s", msg[:200])
        logger.info("   attachments: %d 个", len(state.get("attachments") or []))
        logger.info("   order_id_hint: %s", state.get("order_id_hint"))
        logger.info("   existing tool_results: %d", len(state.get("tool_results") or []))

        raw = self.llm.chat_json(
            system_prompt=self._planner_system_prompt(),
            user_prompt=json.dumps(self._planner_payload(state), ensure_ascii=False, indent=2),
            temperature=0.1,
            max_tokens=700,
        )
        logger.info("📡 LLM planner 原始返回: action=%s tool=%s need_human=%s",
                    raw.get("action"), raw.get("tool_name"), raw.get("need_human"))
        logger.info("   assistant_reply 预览: %s", str(raw.get("assistant_reply") or "")[:150])

        # 小模型安全网：LLM 忽略了已提供的订单上下文时，强制查订单
        # 这不是关键词匹配 — 只检查"有 order_id / 有实质内容 / LLM 没调工具"
        if self._llm_ignored_order_context(state, raw):
            logger.info("⚡ 安全网触发: LLM 忽略了订单上下文, 强制 search_user_orders")
            raw = self._order_lookup_action(state)

        self._apply_action(state, raw)
        logger.info("🎯 最终决策: next_action=%s tool_name=%s need_human=%s",
                    state.get("next_action"), state.get("tool_name"), state.get("need_human"))
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
        logger.info("🔧 [tool_call] step=%d 调用工具: %s", int(state.get("steps") or 0) + 1, name)
        # 隐藏敏感字段的日志
        safe_args = {k: v for k, v in arguments.items() if k not in ("user_id", "session_id")}
        logger.info("   参数: %s", json.dumps(safe_args, ensure_ascii=False, default=str)[:300])
        result = self.tools.call(name, arguments)
        logger.info("   结果: ok=%s error=%s", result.ok, (result.error or "")[:100])
        trace = list(state.get("tool_results") or [])
        trace.append(
            {
                "tool": name,
                "arguments": state.get("tool_arguments") or {},
                "ok": result.ok,
                "data": result.data,
                "error": result.error,
            }
        )
        state["tool_results"] = trace
        state["steps"] = int(state.get("steps") or 0) + 1
        if name == "create_after_sales_ticket" and result.ok and isinstance(result.data, dict):
            state["ticket"] = result.data
            logger.info("   ✅ 售后单已创建: %s status=%s",
                        result.data.get("ticketNo") or result.data.get("ticket_no"),
                        result.data.get("status"))
        if name == "handoff_to_human" and result.ok:
            state["session_mode"] = "HUMAN"
            state["need_human"] = True
            logger.info("   🚨 已转人工")
        return state

    def observe_tool_result(self, state: AgentGraphState) -> AgentGraphState:
        return state

    def decide_next(self, state: AgentGraphState) -> AgentGraphState:
        steps = int(state.get("steps") or 0)
        logger.info("🧠 [decide_next] step=%d/%d, tool_results=%d",
                    steps, self.max_steps, len(state.get("tool_results") or []))

        if steps >= self.max_steps:
            logger.info("   ⏰ 达到最大步数, 进入 final_reply")
            state["next_action"] = "final_reply"
            state.setdefault("assistant_reply", "已收到您的售后问题，我会根据当前信息继续为您处理。")
            return state
        if self._has_empty_order_search(state):
            logger.info("   📭 订单查询为空, 进入 final_reply")
            state["next_action"] = "final_reply"
            state["assistant_reply"] = "我没有查询到可用于售后的订单。请提供订单号，或从订单详情页进入售后咨询后再申请退款/退货。"
            state["evidence_needed"] = ["订单信息"]
            state["need_human"] = False
            return state
        if self._has_failed_order_search(state):
            logger.info("   ❌ 订单查询失败, 进入 final_reply")
            state["next_action"] = "final_reply"
            state["assistant_reply"] = "当前订单服务暂时不可用，我还不能核对订单或创建售后单。请稍后重试。"
            state["evidence_needed"] = ["订单信息"]
            state["need_human"] = False
            return state

        guarded = self._guarded_after_sales_action(state)
        if guarded is not None:
            logger.info("   🛡️ guarded_action 接管: action=%s tool=%s need_human=%s",
                        guarded.get("action"), guarded.get("tool_name"), guarded.get("need_human"))
            self._apply_action(state, guarded)
            return state

        logger.info("   🤖 LLM decider 决策中...")
        raw = self.llm.chat_json(
            system_prompt=self._decider_system_prompt(),
            user_prompt=json.dumps(self._planner_payload(state), ensure_ascii=False, indent=2),
            temperature=0.1,
            max_tokens=700,
        )
        logger.info("   📡 LLM decider: action=%s tool=%s need_human=%s",
                    raw.get("action"), raw.get("tool_name"), raw.get("need_human"))
        if self._claims_ticket_created(raw.get("assistant_reply")) and not self._has_successful_tool(state, "create_after_sales_ticket"):
            logger.info("   ⚠️ LLM声称已建单但实际未建, 纠正中...")
            raw = self._order_lookup_action(state) if not self._has_successful_tool(state, "search_user_orders") else {
                "action": "final_reply",
                "tool_name": None,
                "tool_arguments": {},
                "assistant_reply": "我需要先核对您的订单信息和售后条件，暂时不能直接创建售后单。请提供订单号或从订单详情页进入售后咨询。",
                "need_human": False,
                "evidence_needed": ["订单信息"],
            }
        self._apply_action(state, raw)
        logger.info("   🎯 decide_next 结果: next_action=%s tool=%s need_human=%s",
                    state.get("next_action"), state.get("tool_name"), state.get("need_human"))
        return state

    def human_handoff(self, state: AgentGraphState) -> AgentGraphState:
        logger.info("🚨 [human_handoff] 触发转人工")
        ticket_id = (state.get("ticket") or {}).get("id") if isinstance(state.get("ticket"), dict) else None
        logger.info("   ticket_id=%s session_id=%s order_id=%s",
                    ticket_id, state.get("session_id"), state.get("order_id_hint"))
        args = {
            "user_id": state.get("user_id"),
            "session_id": state.get("session_id"),
            "order_id": state.get("order_id_hint"),
            "ticket_id": ticket_id,
            "summary": state.get("assistant_reply") or state.get("message") or "AI 建议转人工",
        }
        result = self.tools.call("handoff_to_human", args)
        trace = list(state.get("tool_results") or [])
        trace.append({"tool": "handoff_to_human", "arguments": args, "ok": result.ok, "data": result.data, "error": result.error})
        state["tool_results"] = trace
        state["session_mode"] = "HUMAN" if result.ok else "AI"
        state["need_human"] = result.ok
        if result.ok:
            ticket = state.get("ticket") if isinstance(state.get("ticket"), dict) else None
            if ticket:
                ticket_no = ticket.get("ticketNo") or ticket.get("ticket_no") or ticket.get("ticket_id")
                state["assistant_reply"] = f"已为您提交售后申请 {ticket_no}，当前图片与描述仍需人工复核，已为您转接人工客服。"
            else:
                state["assistant_reply"] = "已为您转接人工客服，请稍等。"
        else:
            state["assistant_reply"] = "当前人工转接暂时失败，请稍后重试。"
        return state

    def final_reply(self, state: AgentGraphState) -> AgentGraphState:
        reply = state.get("assistant_reply") or self._ticket_reply(state) or "已收到您的售后问题，我会继续为您处理。"
        # 最终防线：确保 reply 不是泄漏的 JSON 数据
        reply = self._sanitize_reply(reply)
        logger.info("💬 [final_reply] 最终回复: %s", reply[:200])
        logger.info("   session_mode=%s need_human=%s steps=%d",
                    state.get("session_mode"), state.get("need_human"), state.get("steps"))
        logger.info("=" * 70)
        ticket_id = (state.get("ticket") or {}).get("id") if isinstance(state.get("ticket"), dict) else None
        append_user = {
            "user_id": state.get("user_id"),
            "session_id": state.get("session_id"),
            "order_id": state.get("order_id_hint"),
            "ticket_id": ticket_id,
            "role": "USER",
            "content": state.get("message") or "用户发送了售后凭证",
            "message_type": "TEXT",
        }
        append_assistant = {
            "user_id": state.get("user_id"),
            "session_id": state.get("session_id"),
            "order_id": state.get("order_id_hint"),
            "ticket_id": ticket_id,
            "role": "ASSISTANT",
            "content": reply,
            "message_type": "TEXT",
            "knowledge_hits_json": json.dumps(state.get("tool_results") or [], ensure_ascii=False),
        }
        trace = list(state.get("tool_results") or [])
        user_result = self.tools.call("append_chat_message", append_user)
        trace.append({"tool": "append_chat_message", "arguments": append_user, "ok": user_result.ok, "data": user_result.data, "error": user_result.error})
        if user_result.ok and isinstance(user_result.data, dict) and not state.get("session_id"):
            state["session_id"] = user_result.data.get("sessionId") or user_result.data.get("session_id")
        append_assistant["session_id"] = state.get("session_id")
        assistant_result = self.tools.call("append_chat_message", append_assistant)
        trace.append({"tool": "append_chat_message", "arguments": append_assistant, "ok": assistant_result.ok, "data": assistant_result.data, "error": assistant_result.error})
        state["tool_results"] = trace
        state["assistant_reply"] = reply
        state["final"] = True
        return state

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
        return {
            "user": {
                "user_id": state.get("user_id"),
                "message": state.get("message"),
                "attachments": state.get("attachments"),
                "order_id_hint": state.get("order_id_hint"),
                "client_context": state.get("client_context"),
            },
            "recent_history": state.get("recent_history") or [],
            "available_tools": self.tools.tool_specs(),
            "tool_results": self._summarize_tool_results(state),
            "current_ticket": self._summarize_ticket_for_llm(state.get("ticket")),
            "evidence_needed": state.get("evidence_needed") or [],
        }

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
                    str(o.get("orderNo") or o.get("order_no") or o.get("id") or "")
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
            elif tool == "create_after_sales_ticket" and isinstance(data, dict):
                entry["ticket_id"] = data.get("ticketNo") or data.get("ticket_no") or data.get("ticket_id")
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
            "ticket_id": ticket.get("ticketNo") or ticket.get("ticket_no") or ticket.get("ticket_id"),
            "status": ticket.get("status"),
            "existing": bool(ticket.get("existing")),
        }

    @staticmethod
    def _planner_system_prompt() -> str:
        return (
            "你是电商售后 ReAct Agent。决策规则（按优先级）：\n"
            "1. 用户表达任何不满/投诉/退换货/商品问题（无论品类和用词）→ 先 search_user_orders\n"
            "2. 查到订单后 → 调用 retrieve_knowledge 查询该品类+场景对应的证据模板和售后政策\n"
            "3. 纯政策/时效咨询（不用建单）→ 用 retrieve_knowledge 回答，不建单\n"
            "4. 证据不足 → 用 final_reply 引导用户补充具体凭证，参考 retrieve_knowledge 返回的证据模板\n"
            "5. 凭证齐全后 → create_after_sales_ticket；视觉审核不确定或政策不匹配 → human_handoff\n"
            "6. 不要声称已建单除非工具成功；不要信任前端传来的订单详情\n"
            "⚠️ assistant_reply 必须是给用户看的自然中文文本，绝对禁止包含 JSON、工具调用参数、\n"
            "   base64、长数字ID序列或任何机器可读数据。回复应像真人客服一样亲切、简洁、信息明确。\n"
            "只输出 JSON："
            "{\"action\":\"tool_call|final_reply|human_handoff\","
            "\"tool_name\":\"工具名或null\",\"tool_arguments\":{},"
            "\"assistant_reply\":\"给用户看的中文自然语言回复（禁止JSON/数据）\","
            "\"need_human\":false,\"evidence_needed\":[]}"
        )

    @staticmethod
    def _decider_system_prompt() -> str:
        return (
            "你是售后 Agent 的观察/决策节点。根据 tool_results 决定继续调用工具、转人工或最终回复。\n"
            "售后申请必须以 create_after_sales_ticket 的结果为准；不要编造工具未返回的订单、售后单、政策或退款结果。\n"
            "⚠️ assistant_reply 必须是给用户看的自然中文文本，绝对禁止包含 JSON、工具调用参数、\n"
            "   base64、长数字ID序列或任何机器可读数据。回复应像真人客服一样亲切、简洁、信息明确。\n"
            "只输出 JSON，字段同规划节点。"
        )

    def _guarded_after_sales_action(self, state: AgentGraphState) -> dict[str, Any] | None:
        """语义路由 + RAG 证据驱动。信任 LLM 判断是否需要售后操作。

        流程：查订单 → RAG查证据模板 → 动态生成 evidence_needed → 引导/审核/建单
        """
        # 如果还没查过订单，先查
        if not self._has_successful_tool(state, "search_user_orders"):
            return self._order_lookup_action(state)

        order = self._selected_order(state)
        if order is None:
            return {
                "action": "final_reply",
                "assistant_reply": "我查到了多笔可能相关的订单，请补充具体订单号，或从对应订单详情页进入售后申请。",
                "evidence_needed": ["订单号"],
                "need_human": False,
            }

        # === 已有售后单：补充材料 / 转人工 ===
        if bool(state.get("explicit_human_request")) and not self._has_successful_tool(state, "handoff_to_human"):
            existing_ticket_no = self._existing_ticket_no(order)
            if existing_ticket_no:
                state["ticket"] = self._ticket_from_existing_order(order)
                return {
                    "action": "human_handoff",
                    "assistant_reply": f"已记录您的售后申请 {existing_ticket_no}，我会为您转接人工客服继续处理。",
                    "need_human": True,
                    "evidence_needed": [],
                }

        if order.get("existingTicketNo") or order.get("existing_ticket_no"):
            existing_ticket_no = self._existing_ticket_no(order)
            if state.get("attachments") and not self._has_tool_result(state, "review_images"):
                return self._review_images_action(state, order)
            # RAG 驱动的证据需求
            if not self._has_tool_result(state, "retrieve_knowledge"):
                return self._retrieve_evidence_action(state, order)
            evidence_needed = self._build_evidence_needed(state, order)
            if evidence_needed:
                reply = self._build_evidence_guidance(state, order, evidence_needed)
                return {
                    "action": "final_reply",
                    "assistant_reply": f"您的售后申请 {existing_ticket_no} 已创建（待审核）。{reply}",
                    "need_human": False,
                    "evidence_needed": evidence_needed,
                }
            visual_handoff = self._quality_visual_handoff_action(state)
            if visual_handoff:
                state["ticket"] = self._ticket_from_existing_order(order)
                return visual_handoff
            if not self._has_successful_tool(state, "create_after_sales_ticket"):
                return self._create_ticket_action(state, order)
            return None  # fall through to LLM decider

        # === 新售后申请 ===
        # 1. 无附件 → RAG 查证据模板 → LLM 动态生成引导
        if not state.get("attachments"):
            if not self._has_tool_result(state, "retrieve_knowledge"):
                return self._retrieve_evidence_action(state, order)
            evidence_needed = self._build_evidence_needed(state, order)
            reply = self._build_evidence_guidance(state, order, evidence_needed)
            return {
                "action": "final_reply",
                "assistant_reply": reply,
                "need_human": False,
                "evidence_needed": evidence_needed,
            }

        # 2. 有附件 → 图片审核
        if not self._has_tool_result(state, "review_images"):
            return self._review_images_action(state, order)

        # 3. 查 RAG 政策
        if not self._has_tool_result(state, "retrieve_knowledge"):
            return self._retrieve_policy_action(state, order)

        # 4. 建单
        if not self._has_successful_tool(state, "create_after_sales_ticket"):
            return self._create_ticket_action(state, order)

        # 5. 建单后需要转人工?
        if (state.get("need_human") or self._ticket_requires_handoff(state)) and not self._has_successful_tool(state, "handoff_to_human"):
            return {
                "action": "human_handoff",
                "assistant_reply": "图片与问题描述仍需人工复核，我会为您转接人工客服继续处理。",
                "need_human": True,
                "evidence_needed": [],
            }

        return {
            "action": "final_reply",
            "assistant_reply": self._ticket_reply(state),
            "need_human": bool(state.get("need_human")),
            "evidence_needed": state.get("evidence_needed") or [],
        }

    def _create_ticket_action(self, state: AgentGraphState, order: dict[str, Any]) -> dict[str, Any]:
        review = self._latest_tool_data(state, "review_images")
        knowledge = self._latest_tool_data(state, "retrieve_knowledge")
        policy_hits = self._policy_hits(knowledge)
        has_attachments = bool(state.get("attachments"))

        # 放宽：不强制要求知识库匹配，只作为参考
        policy_uncertain = not policy_hits

        # 打印调试信息
        print("\n" + "="*80)
        print("🔍 AI售后判断 - 调试信息")
        print("="*80)
        print(f"📎 has_attachments: {has_attachments}")
        print(f"📊 review结果: {review}")
        if isinstance(review, dict):
            print(f"  ✓ success: {review.get('success')}")
            print(f"  ✓ has_damage_area: {review.get('has_damage_area')}")
            print(f"  ✓ all_clear: {review.get('all_clear')}")
            print(f"  ✓ missing_visual_evidence: {review.get('missing_visual_evidence')}")
        print(f"📚 policy_hits数量: {len(policy_hits)}")
        print(f"📚 knowledge mode: {knowledge.get('mode') if isinstance(knowledge, dict) else 'missing'}")
        print(f"📚 knowledge trace: {knowledge.get('trace') if isinstance(knowledge, dict) else None}")
        if policy_hits:
            for hit in policy_hits[:3]:
                print(f"  - {hit.get('title')} score={hit.get('score')} source={hit.get('source_type')}:{hit.get('source_code')}")
        print(f"📝 policy_uncertain: {policy_uncertain}")

        # 优化视觉判断逻辑：
        # 1. 图片识别失败 → uncertain
        # 2. 用户明确描述破损，但图片完全看不出问题且missing_evidence明确指出缺失 → uncertain
        user_claims_damage = self._mentions_visible_damage(state)
        image_shows_damage = isinstance(review, dict) and review.get("has_damage_area")

        visual_uncertain = has_attachments and (
            not isinstance(review, dict)
            or not review.get("success")
            or (user_claims_damage and not image_shows_damage and self._review_missing_damage(review))
        )

        print(f"👤 user_claims_damage: {user_claims_damage}")
        print(f"🖼️ image_shows_damage: {image_shows_damage}")
        print(f"❓ visual_uncertain: {visual_uncertain}")

        evidence_needed = self._build_evidence_needed(state, order)
        print(f"📋 evidence_needed: {evidence_needed}")

        auto_approved = bool(
            has_attachments
            and isinstance(review, dict)
            and review.get("success")
            and (image_shows_damage or (user_claims_damage and not visual_uncertain))
            and not policy_uncertain
        )

        print(f"✅ auto_approved: {auto_approved}")
        print("="*80 + "\n")
        reason = self._ai_suggestion_reason(
            state,
            review,
            knowledge,
            auto_approved,
            visual_uncertain,
            policy_uncertain,
            evidence_needed,
        )

        order_no = str(order.get("orderNo") or order.get("order_no") or order.get("id") or state.get("order_id_hint") or "")
        payload = {
            "user_id": state.get("user_id"),
            "session_id": state.get("session_id"),
            "order_id": order_no,
            "after_sales_type": self._after_sales_type(state),
            "reason": self._reason_type(state),
            "reason_detail": state.get("message") or "用户提交售后申请",
            "description": state.get("message") or "",
            "refund_amount": order.get("amount"),
            "ai_confidence": 0.86 if auto_approved else 0.55,
            "ai_recommend_type": self._after_sales_type(state),
            "evidence_urls": self._evidence_refs(state),
            "auto_approved": auto_approved,
            "ai_classify_result": {
                "verdict": "AI_RECOMMEND_APPROVE" if auto_approved else "PENDING_REVIEW",
                "reason": reason,
                "evidence_needed": evidence_needed,
                "visual_uncertain": visual_uncertain,
                "policy_uncertain": policy_uncertain,
                "image_review": review if isinstance(review, dict) else None,
                "policy_citations": self._policy_citations(policy_hits),
            },
        }
        state["evidence_needed"] = evidence_needed

        state["need_human"] = (visual_uncertain or policy_uncertain) and not auto_approved

        return {
            "action": "tool_call",
            "tool_name": "create_after_sales_ticket",
            "tool_arguments": payload,
            "need_human": (visual_uncertain or policy_uncertain) and not auto_approved,
            "evidence_needed": evidence_needed,
        }

    def _retrieve_policy_action(self, state: AgentGraphState, order: dict[str, Any]) -> dict[str, Any]:
        reason = self._reason_type(state)
        after_sales_type = self._after_sales_type(state)
        category = order.get("category") or order.get("productCategory") or order.get("product_category")
        merchant_code = order.get("merchantCode") or order.get("merchant_code") or "MERCHANT_DEMO"
        query_parts = [
            str(state.get("message") or ""),
            str(order.get("productName") or order.get("product_name") or ""),
            str(category or ""),
            self._scene_for_reason(reason),
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
                "top_k": 5,
            },
            "need_human": False,
            "evidence_needed": [],
        }

    def _retrieve_evidence_action(self, state: AgentGraphState, order: dict[str, Any]) -> dict[str, Any]:
        """RAG 检索证据模板 — 提前到决策阶段调用，用语义匹配替代硬编码关键词。"""
        reason = self._reason_type(state)
        product_name = str(order.get("productName") or order.get("product_name") or "")
        category = order.get("category") or order.get("productCategory") or order.get("product_category") or ""
        merchant_code = order.get("merchantCode") or order.get("merchant_code") or "MERCHANT_DEMO"
        message = str(state.get("message") or "")
        query_parts = [
            message,
            product_name,
            category,
            self._scene_for_reason(reason),
            self._rag_query_expansion(reason, self._after_sales_type(state)),
            "售后证据要求 凭证模板 需要什么照片",
        ]
        return {
            "action": "tool_call",
            "tool_name": "retrieve_knowledge",
            "tool_arguments": {
                "user_id": state.get("user_id"),
                "query": " ".join(p for p in query_parts if p).strip(),
                "merchant_code": merchant_code,
                "product_category": category if category else None,
                "scene": self._scene_for_reason(reason),
                "top_k": 5,
            },
            "need_human": False,
            "evidence_needed": [],
        }

    def _build_evidence_needed(self, state: AgentGraphState, order: dict[str, Any]) -> list[str]:
        """从 RAG 结果 + 订单上下文动态生成 evidence_needed，替代硬编码 _missing_evidence。"""
        knowledge = self._latest_tool_data(state, "retrieve_knowledge")
        product_name = str(order.get("productName") or order.get("product_name") or "")
        category = str(order.get("category") or order.get("productCategory") or order.get("product_category") or "")

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
        """动态生成证据引导文案，替代硬编码 _missing_inputs_reply。"""
        product_name = str(order.get("productName") or order.get("product_name") or "该商品")
        items_text = "、".join(evidence_needed) if evidence_needed else "相关凭证"
        msg = str(state.get("message") or "")

        # 尝试让 LLM 根据品类+问题生成更友好的引导
        try:
            raw = self.llm.chat_json(
                system_prompt=(
                    "你是电商客服。根据商品信息和用户问题，生成一句引导用户上传证据的友好中文回复。"
                    "必须包含需要上传的具体证据类型，语气亲切专业。只输出JSON："
                    '{"reply": "引导文案"}'
                ),
                user_prompt=json.dumps({
                    "product": product_name,
                    "issue": msg,
                    "evidence_items": evidence_needed,
                }, ensure_ascii=False),
                temperature=0.3,
                max_tokens=200,
            )
            reply = str(raw.get("reply") or "").strip()
            if reply and len(reply) >= 10:
                return reply
        except Exception:
            pass

        # LLM 失败 → 通用模板
        if not evidence_needed:
            return "已了解您的问题。请补充相关凭证以便为您处理售后。"
        return f"已了解您的问题。为了继续判断售后规则，请上传{items_text}。"

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
                "order_id": order.get("orderNo") or order.get("order_no") or order.get("id"),
                "attachments": state.get("attachments") or [],
                "order_hint": self._order_hint(order),
            },
            "need_human": False,
            "evidence_needed": [],
        }

    @classmethod
    def _apply_action(cls, state: AgentGraphState, raw: dict[str, Any]) -> None:
        action = str(raw.get("action") or "final_reply")
        state["next_action"] = action
        state["tool_name"] = raw.get("tool_name")
        arguments = raw.get("tool_arguments") if isinstance(raw.get("tool_arguments"), dict) else {}
        arguments.setdefault("user_id", state.get("user_id"))
        if state.get("session_id") is not None:
            arguments.setdefault("session_id", state.get("session_id"))
        if state.get("order_id_hint"):
            arguments.setdefault("order_id", state.get("order_id_hint"))
        state["tool_arguments"] = arguments
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
    def _claims_ticket_created(reply: Any) -> bool:
        text = str(reply or "").lower()
        keywords = ("已创建售后", "已提交售后", "售后单已创建", "已建单", "已进入处理", "created after-sales", "ticket created")
        return any(keyword.lower() in text for keyword in keywords)

    @staticmethod
    def _has_successful_tool(state: AgentGraphState, tool_name: str) -> bool:
        return any(item.get("tool") == tool_name and item.get("ok") for item in state.get("tool_results") or [])

    @staticmethod
    def _has_tool_result(state: AgentGraphState, tool_name: str) -> bool:
        return any(item.get("tool") == tool_name for item in state.get("tool_results") or [])

    @staticmethod
    def _latest_tool_data(state: AgentGraphState, tool_name: str) -> Any:
        for item in reversed(state.get("tool_results") or []):
            if item.get("tool") == tool_name and item.get("ok"):
                return item.get("data")
        return None

    @staticmethod
    def _has_empty_order_search(state: AgentGraphState) -> bool:
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
    def _selected_order(state: AgentGraphState) -> dict[str, Any] | None:
        orders = LangGraphAfterSalesAgent._latest_tool_data(state, "search_user_orders")
        if not isinstance(orders, list) or not orders:
            return None
        hint = str(state.get("order_id_hint") or "")
        if hint:
            for order in orders:
                if not isinstance(order, dict):
                    continue
                if hint in {str(order.get("id") or ""), str(order.get("orderNo") or order.get("order_no") or "")}:
                    return order
        dict_orders = [order for order in orders if isinstance(order, dict)]
        return dict_orders[0] if len(dict_orders) == 1 else None

    @staticmethod
    def _existing_ticket_no(order: dict[str, Any] | None) -> str | None:
        if not isinstance(order, dict):
            return None
        ticket_no = order.get("existingTicketNo") or order.get("existing_ticket_no")
        return str(ticket_no) if ticket_no else None

    @staticmethod
    def _ticket_from_existing_order(order: dict[str, Any]) -> dict[str, Any]:
        ticket_no = LangGraphAfterSalesAgent._existing_ticket_no(order)
        return {
            "ticketNo": ticket_no,
            "ticket_id": ticket_no,
            "status": order.get("afterSalesStatus") or order.get("after_sales_status") or "PENDING_REVIEW",
            "existing": True,
        }

    @staticmethod
    def _order_hint(order: dict[str, Any]) -> str:
        return f"订单号：{order.get('orderNo') or order.get('order_no') or order.get('id') or ''}；商品：{order.get('productName') or order.get('product_name') or ''}"

    @staticmethod
    def _mentions_visible_damage(state: AgentGraphState) -> bool:
        text = str(state.get("message") or "")
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
        text = str(state.get("message") or "")
        if any(word in text for word in ("破", "裂", "坏", "损", "碎", "断")):
            return "DAMAGE"
        if any(word in text for word in ("质量", "电流", "异响", "噪", "充电", "充不", "充了", "掉电", "耗电", "续航", "开不了机", "无法开机", "死机", "重启", "卡顿")):
            return "QUALITY"
        return "OTHER"

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
        text = str(state.get("message") or "")
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
    def _policy_citations(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
        citations: list[dict[str, Any]] = []
        for hit in hits[:5]:
            citations.append(
                {
                    "source_type": hit.get("source_type"),
                    "source_code": hit.get("source_code"),
                    "title": hit.get("title"),
                    "score": hit.get("score"),
                    "metadata": hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {},
                }
            )
        return citations

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
            "REISSUE": "resend",
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
            if item.get("tool") == "create_after_sales_ticket":
                arguments = item.get("arguments") if isinstance(item.get("arguments"), dict) else {}
                break
        classify = arguments.get("ai_classify_result") or arguments.get("aiClassifyResult") or {}
        return isinstance(classify, dict) and bool(classify.get("visual_uncertain") or classify.get("policy_uncertain"))

    @staticmethod
    def _ticket_reply(state: AgentGraphState) -> str | None:
        ticket = state.get("ticket")
        if not isinstance(ticket, dict):
            return None
        ticket_no = ticket.get("ticketNo") or ticket.get("ticket_no") or ticket.get("ticket_id")
        status = str(ticket.get("status") or "").upper()
        evidence_needed = state.get("evidence_needed") or []
        if status == "PROCESSING":
            return f"已为您提交售后申请 {ticket_no}，AI 初审建议通过，当前已进入处理中。最终处理仍由人工客服确认，请留意后续进度。"
        if evidence_needed:
            return f"已为您提交售后申请 {ticket_no}，当前进入待审核。为便于继续审核，请补充：{'、'.join(evidence_needed)}。"
        return f"已为您提交售后申请 {ticket_no}，当前进入待审核，客服会继续处理。"

    _JSON_LEAKAGE_PATTERNS: ClassVar[tuple[str, ...]] = (
        r'"tool"\s*:\s*"create_after_sales_ticket"',
        r'"arguments"\s*:\s*\{',
        r'"user_id"\s*:\s*"\d{15,}"',
        r'"session_id"\s*:\s*\d{15,}',
        r'"after_sales_type"\s*:\s*"',
        r'"refund_amount"\s*:\s*[\d.]+',
        r'"ai_confidence"\s*:\s*[\d.]+',
        r'"ai_recommend_type"\s*:\s*"',
        r'"evidence_urls"\s*:\s*\[',
        r'"auto_approved"\s*:',
        r'"ai_classify_result"\s*:\s*\{',
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
        if "create_after_sales_ticket" in stripped and '"tool"' in stripped:
            return True
        # 包含长数字 ID + JSON 键名
        for pattern in cls._JSON_LEAKAGE_PATTERNS:
            if re.search(pattern, text):
                return True
        return False

    _FALLBACK_REPLY: ClassVar[str] = (
        "已收到您的售后问题，我已为您提交了售后申请。"
        "如需查看进度或补充材料，请随时告诉我。"
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
        ticket_no = ticket.get("ticket_id") or ticket.get("ticketNo") or ticket.get("ticket_no")
        status = str(ticket.get("status") or "").lower()
        return {
            "ticket_id": ticket_no,
            "ticket_no": ticket_no,
            "status": status,
            "id": str(ticket.get("id")) if ticket.get("id") is not None else None,
            "order_id": str(ticket.get("orderId") or ticket.get("order_id") or "") or None,
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
