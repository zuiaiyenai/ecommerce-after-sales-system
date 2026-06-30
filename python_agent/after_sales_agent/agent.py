from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from .models import (
    AfterSalesRequest,
    AfterSalesScene,
    AfterSalesStatus,
    AfterSalesType,
    AgentResult,
    Decision,
    Intent,
    Order,
    RiskLevel,
    Ticket,
    TicketStatus,
)
from .policies import PolicyEngine


class ReturnAgent:
    def __init__(self, policy_engine: PolicyEngine | None = None) -> None:
        self.policy_engine = policy_engine or PolicyEngine()

    def handle(self, request: AfterSalesRequest, order: Order | None) -> AgentResult:
        if order is None and request.order_id is None:
            return AgentResult(
                decision=Decision.ASK_FOR_INFO,
                user_reply="请先选择需要处理的订单，我会根据订单状态继续帮您判断售后流程。",
                extracted_order_id=None,
                intent=Intent.GENERAL,
                next_agent="订单识别",
                need_human=False,
                current_status=AfterSalesStatus.NOT_APPLIED,
                scene=AfterSalesScene.GENERAL,
                missing_fields=("订单信息",),
                suggested_action="选择订单",
                audit_note="missing_order_context",
                emotion=self.policy_engine.analyze_emotion(request, order),
            )

        intent_result = self.policy_engine.classify_intent(request, order)
        scene = self.policy_engine.intent_agent.infer_scene_enum(request, intent_result.intent)
        emotion_result = self.policy_engine.analyze_emotion(request, order)

        if intent_result.needs_clarification:
            options_text = "还是".join(intent_result.clarification_options)
            return AgentResult(
                decision=Decision.ASK_FOR_INFO,
                user_reply=self._apply_emotion_prefix(
                    f"您好，我先帮您确认一下，您这次是想{options_text}？",
                    emotion_result,
                ),
                extracted_order_id=order.order_id if order else request.order_id,
                intent=intent_result.intent,
                next_agent="意图澄清",
                need_human=False,
                current_status=order.after_sales_status if order else AfterSalesStatus.NOT_APPLIED,
                scene=scene,
                missing_fields=("意图确认",),
                suggested_action="确认问题类型",
                progress_hint="当前问题可能对应多个处理方向，需要先确认。",
                audit_note=f"intent_clarify score={intent_result.score}; options={','.join(intent_result.clarification_options)}",
                emotion=emotion_result,
            )

        if intent_result.fallback:
            return AgentResult(
                decision=Decision.ASK_FOR_INFO,
                user_reply=self._apply_emotion_prefix(
                    "您好，为了更快帮您处理，请再说明一下您是想申请售后、查询进度，还是联系人工客服。",
                    emotion_result,
                ),
                extracted_order_id=order.order_id if order else request.order_id,
                intent=Intent.GENERAL,
                next_agent="普通咨询",
                need_human=False,
                current_status=order.after_sales_status if order else AfterSalesStatus.NOT_APPLIED,
                scene=scene,
                missing_fields=("问题类型",),
                suggested_action="补充问题描述",
                progress_hint="当前信息不足，暂时无法稳定判断问题类型。",
                audit_note=f"intent_fallback score={intent_result.score}",
                emotion=emotion_result,
            )

        state_result = self.policy_engine.evaluate_state(order, intent_result.intent)
        evidence_result = self.policy_engine.check_evidence(order, request, intent_result.intent)
        risk_result = self.policy_engine.assess_risk(order, request, intent_result.intent, evidence_result)
        handoff_result = self.policy_engine.evaluate_handoff(
            order,
            request,
            intent_result,
            risk_result,
            evidence_result,
            emotion_result,
        )

        if handoff_result.triggered:
            return AgentResult(
                decision=Decision.ESCALATE_HUMAN,
                user_reply="抱歉给您带来不便，当前问题已为您转接人工客服，订单信息和已提交材料会同步给客服继续处理。",
                extracted_order_id=order.order_id if order else request.order_id,
                intent=intent_result.intent,
                next_agent="人工客服",
                need_human=True,
                current_status=state_result.current_status,
                scene=scene,
                allowed_actions=state_result.allowed_actions,
                missing_fields=evidence_result.missing_items,
                risk_level=risk_result.risk_level,
                suggested_action="转接人工客服",
                progress_hint=handoff_result.reason,
                audit_note=self._build_audit_note(intent_result.intent, risk_result),
                handoff_summary=handoff_result.summary,
                emotion=emotion_result,
            )

        if intent_result.intent == Intent.HUMAN_SERVICE:
            missing_items = evidence_result.missing_items or ("问题描述",)
            missing_text = "、".join(missing_items)
            return AgentResult(
                decision=Decision.ASK_FOR_INFO,
                user_reply=self._apply_emotion_prefix(
                    f"您好，为了尽快帮您转接人工客服，请先补充{missing_text}。",
                    emotion_result,
                ),
                extracted_order_id=order.order_id if order else request.order_id,
                intent=intent_result.intent,
                next_agent="信息补充",
                need_human=False,
                current_status=state_result.current_status,
                scene=scene,
                allowed_actions=state_result.allowed_actions,
                missing_fields=missing_items,
                risk_level=risk_result.risk_level,
                suggested_action="补充必要信息后转人工",
                progress_hint="补充必要信息后可继续为您转接人工客服。",
                audit_note=self._build_audit_note(intent_result.intent, risk_result),
                emotion=emotion_result,
            )

        if not state_result.allowed:
            return AgentResult(
                decision=Decision.RESPOND,
                user_reply=self._apply_emotion_prefix(
                    self._build_state_reply(state_result.current_status),
                    emotion_result,
                ),
                extracted_order_id=order.order_id if order else request.order_id,
                intent=intent_result.intent,
                next_agent=intent_result.next_agent,
                need_human=False,
                current_status=state_result.current_status,
                scene=scene,
                allowed_actions=state_result.allowed_actions,
                risk_level=risk_result.risk_level,
                suggested_action="按当前状态继续处理",
                progress_hint=state_result.reason,
                audit_note=self._build_audit_note(intent_result.intent, risk_result),
                emotion=emotion_result,
            )

        if not evidence_result.evidence_complete and intent_result.intent in {
            Intent.APPLY_AFTER_SALES,
            Intent.SUPPLEMENT_EVIDENCE,
            Intent.MERCHANT_REJECTED,
            Intent.EXCHANGE_REPAIR,
            Intent.REFUND_ONLY,
        }:
            return AgentResult(
                decision=Decision.ASK_FOR_INFO,
                user_reply=self._apply_emotion_prefix(evidence_result.suggestion, emotion_result),
                extracted_order_id=order.order_id if order else request.order_id,
                intent=intent_result.intent,
                next_agent="证据检查",
                need_human=False,
                current_status=state_result.current_status,
                scene=scene,
                allowed_actions=state_result.allowed_actions,
                missing_fields=evidence_result.missing_items,
                risk_level=risk_result.risk_level,
                suggested_action="补充必要信息",
                progress_hint="补齐材料后可继续审核。",
                audit_note=self._build_audit_note(intent_result.intent, risk_result),
                emotion=emotion_result,
            )

        if intent_result.intent in {Intent.REFUND_PROGRESS, Intent.RETURN_LOGISTICS, Intent.GENERAL}:
            return AgentResult(
                decision=Decision.RESPOND,
                user_reply=self._build_status_answer(
                    order,
                    state_result.current_status,
                    risk_result.risk_level,
                    request,
                    emotion_result,
                ),
                extracted_order_id=order.order_id if order else request.order_id,
                intent=intent_result.intent,
                next_agent=intent_result.next_agent,
                need_human=False,
                current_status=state_result.current_status,
                scene=scene,
                allowed_actions=state_result.allowed_actions,
                risk_level=risk_result.risk_level,
                suggested_action="查看当前进度",
                progress_hint=self._build_progress_hint(order, state_result.current_status),
                audit_note=self._build_audit_note(intent_result.intent, risk_result),
                emotion=emotion_result,
            )

        special_result = self._handle_scene_specific_flow(
            request=request,
            order=order,
            intent=intent_result.intent,
            scene=scene,
            state_result=state_result,
            evidence_result=evidence_result,
            risk_result=risk_result,
            next_agent=intent_result.next_agent,
            emotion_result=emotion_result,
        )
        if special_result is not None:
            return special_result

        ticket = self._build_ticket(order, request, intent_result.intent, risk_result, scene)
        return AgentResult(
            decision=Decision.CREATE_TICKET,
            user_reply=self._apply_emotion_prefix(
                self._build_ticket_reply(ticket, risk_result, scene),
                emotion_result,
            ),
            extracted_order_id=order.order_id if order else request.order_id,
            intent=intent_result.intent,
            next_agent=intent_result.next_agent,
            need_human=risk_result.need_human_review,
            current_status=state_result.suggested_status,
            scene=scene,
            allowed_actions=state_result.allowed_actions,
            risk_level=risk_result.risk_level,
            ticket=ticket,
            suggested_action=ticket.next_action,
            progress_hint=self._build_progress_hint(order, state_result.suggested_status),
            audit_note=self._build_audit_note(intent_result.intent, risk_result),
            emotion=emotion_result,
        )

    @staticmethod
    def _build_ticket(
        order: Order | None,
        request: AfterSalesRequest,
        intent: Intent,
        risk_result,
        scene: AfterSalesScene,
    ) -> Ticket:
        after_sales_type = ReturnAgent._infer_type(intent)
        status = TicketStatus.AUTO_APPROVED if risk_result.allow_auto_refund else TicketStatus.PENDING_REVIEW
        expected_hours = 12 if risk_result.allow_auto_refund else 24
        product_name = order.items[0].product_name if order and order.items else "未知商品"
        summary = f"{product_name} 售后申请：{request.message or request.description or '用户发起售后'}"
        if scene == AfterSalesScene.PACKAGE_DAMAGE:
            next_action = "等待包装补偿评估"
        elif scene == AfterSalesScene.PRODUCT_DAMAGE:
            next_action = "等待商品破损审核"
        else:
            next_action = "等待系统处理退款" if risk_result.allow_auto_refund else "等待审核结果"
        return Ticket(
            ticket_id=f"AS{uuid4().hex[:10].upper()}",
            order_id=order.order_id if order else request.order_id or "unknown",
            user_id=request.user_id,
            after_sales_type=after_sales_type,
            intent=intent,
            status=status,
            risk_level=risk_result.risk_level,
            summary=summary,
            expected_hours=expected_hours,
            next_action=next_action,
            created_at=datetime.now(),
        )

    @staticmethod
    def _infer_type(intent: Intent) -> AfterSalesType:
        if intent == Intent.REFUND_ONLY:
            return AfterSalesType.REFUND_ONLY
        if intent == Intent.EXCHANGE_REPAIR:
            return AfterSalesType.EXCHANGE
        return AfterSalesType.RETURN_AND_REFUND

    @staticmethod
    def _build_state_reply(status: AfterSalesStatus) -> str:
        mapping = {
            AfterSalesStatus.MERCHANT_REVIEW: "您好，当前售后申请仍在商家审核中，审核通过后才会进入下一步处理。",
            AfterSalesStatus.PLATFORM_REVIEW: "您好，当前售后申请正在平台复核中，请您耐心等待处理结果。",
            AfterSalesStatus.REFUND_PROCESSING: "您好，退款正在处理中，具体到账时间以支付渠道实际入账为准。",
            AfterSalesStatus.COMPLETED: "您好，当前售后已经处理完成，您可以查看处理结果。",
        }
        return mapping.get(status, "您好，当前状态暂不支持该操作，请按页面提示继续处理。")

    @staticmethod
    def _build_status_answer(
        order: Order | None,
        status: AfterSalesStatus,
        risk_level: RiskLevel,
        request: AfterSalesRequest,
        emotion_result,
    ) -> str:
        if status == AfterSalesStatus.MERCHANT_REVIEW:
            return ReturnAgent._build_merchant_review_reply(order, request)
        if status == AfterSalesStatus.WAITING_EVIDENCE:
            return "您好，当前售后申请还需要补充材料，提交完成后平台会继续审核。"
        if status == AfterSalesStatus.REFUND_PROCESSING:
            return "您好，退款正在处理中，具体到账时间以支付渠道入账时间为准，请您留意进度更新。"
        if status == AfterSalesStatus.WAITING_RETURN:
            logistics = order.logistics_status if order else "待更新"
            return f"您好，当前待您补充退货物流信息，现有物流状态为{logistics}。"
        if risk_level == RiskLevel.HIGH:
            return ReturnAgent._apply_emotion_prefix(
                "您好，当前问题还需要进一步核验，建议您耐心等待处理结果，必要时我也可以继续帮您跟进。",
                emotion_result,
            )
        return ReturnAgent._apply_emotion_prefix(
            "您好，当前售后信息已经记录，您可以继续关注处理进度。",
            emotion_result,
        )

    @staticmethod
    def _build_merchant_review_reply(order: Order | None, request: AfterSalesRequest) -> str:
        text = " ".join(part for part in (request.message, request.reason, request.description) if part)
        normalized = text.replace(" ", "")

        if ReturnAgent._is_progress_stalled(order):
            return "您好，当前处理时间比平时稍长，确实让您久等了。我会继续帮您跟进审核进度，必要时也会协助您发起催办。"

        if ReturnAgent._is_anxious_progress_request(normalized):
            return "您好，理解您着急等退款的心情。目前申请还在商家审核中，暂时还没到退款打款阶段。我会继续帮您跟进，状态更新后第一时间通知您。"

        return "您好，已经收到您的退款申请了，目前正在由商家审核。审核通过后会立即进入退款流程，状态一有更新系统会第一时间通知您，您这边先不用重复提交。"

    @staticmethod
    def _is_anxious_progress_request(text: str) -> bool:
        keywords = ("怎么还没", "一直", "这么慢", "催", "快点", "还不到账", "多久了", "到底")
        return any(keyword in text for keyword in keywords)

    @staticmethod
    def _is_progress_stalled(order: Order | None) -> bool:
        if order is None:
            return False
        status_text = f"{order.refund_status} {order.logistics_status}"
        stalled_keywords = ("超时", "未更新", "停滞", "延迟", "异常", "过久")
        return any(keyword in status_text for keyword in stalled_keywords)

    @staticmethod
    def _build_ticket_reply(
        ticket: Ticket,
        risk_result,
        scene: AfterSalesScene | None = None,
    ) -> str:
        if ticket.next_action == "等待包装补偿评估":
            return (
                f"您好，已为您记录包装破损问题并生成售后申请 {ticket.ticket_id}，"
                "我会按包装补偿流程继续推进；如果商品本体也有异常，您可以继续补充商品照片。"
            )
        if ticket.status == TicketStatus.AUTO_APPROVED:
            return f"您好，已为您提交售后申请 {ticket.ticket_id}，当前符合自动处理条件，系统会尽快推进后续流程。"
        if ticket.next_action == "等待商品破损审核":
            return (
                f"您好，已为您提交售后申请 {ticket.ticket_id}，当前会先按商品破损情况进入审核，"
                f"预计 {ticket.expected_hours} 小时内更新进度。"
            )
        return f"您好，已为您提交售后申请 {ticket.ticket_id}，当前已进入审核流程，预计 {ticket.expected_hours} 小时内更新进度。"

    def _handle_scene_specific_flow(
        self,
        *,
        request: AfterSalesRequest,
        order: Order | None,
        intent: Intent,
        scene: AfterSalesScene,
        state_result,
        evidence_result,
        risk_result,
        next_agent: str,
        emotion_result,
    ) -> AgentResult | None:
        if intent not in {Intent.APPLY_AFTER_SALES, Intent.REFUND_ONLY, Intent.EXCHANGE_REPAIR}:
            return None

        if scene == AfterSalesScene.QUALITY_ISSUE:
            if not self._has_detailed_quality_description(request):
                return AgentResult(
                    decision=Decision.ASK_FOR_INFO,
                    user_reply=self._apply_emotion_prefix(
                        "您好，当前图片还无法直接确认问题，请您尽量详细描述异常表现，我再继续为您转客服跟进。",
                        emotion_result,
                    ),
                    extracted_order_id=order.order_id if order else request.order_id,
                    intent=intent,
                    next_agent="信息补充",
                    need_human=False,
                    current_status=state_result.current_status,
                    scene=scene,
                    allowed_actions=state_result.allowed_actions,
                    missing_fields=("问题描述",),
                    risk_level=risk_result.risk_level,
                    suggested_action="补充异常描述",
                    progress_hint="补充异常描述后转客服继续核实。",
                    audit_note=self._build_audit_note(intent, risk_result),
                    emotion=emotion_result,
                )

            summary = self._build_quality_handoff_summary(order, request, risk_result)
            return AgentResult(
                decision=Decision.ESCALATE_HUMAN,
                user_reply=self._apply_emotion_prefix(
                    "您好，已记录您的异常表现。当前图片暂时无法直接确认问题，我这边为您转客服进一步核实处理。",
                    emotion_result,
                ),
                extracted_order_id=order.order_id if order else request.order_id,
                intent=intent,
                next_agent="人工客服",
                need_human=True,
                current_status=state_result.current_status,
                scene=scene,
                allowed_actions=state_result.allowed_actions,
                missing_fields=(),
                risk_level=risk_result.risk_level,
                suggested_action="转人工核实功能异常",
                progress_hint="已记录异常描述，转客服进一步核实。",
                audit_note=self._build_audit_note(intent, risk_result),
                handoff_summary=summary,
                emotion=emotion_result,
            )

        if scene == AfterSalesScene.PACKAGE_DAMAGE:
            ticket = self._build_ticket(order, request, intent, risk_result, scene)
            return AgentResult(
                decision=Decision.CREATE_TICKET,
                user_reply=self._apply_emotion_prefix(
                    self._build_ticket_reply(ticket, risk_result, scene),
                    emotion_result,
                ),
                extracted_order_id=order.order_id if order else request.order_id,
                intent=intent,
                next_agent=next_agent,
                need_human=risk_result.need_human_review,
                current_status=state_result.suggested_status,
                scene=scene,
                allowed_actions=state_result.allowed_actions,
                missing_fields=evidence_result.missing_items,
                risk_level=risk_result.risk_level,
                ticket=ticket,
                suggested_action=ticket.next_action,
                progress_hint="已进入包装破损补偿评估流程。",
                audit_note=self._build_audit_note(intent, risk_result),
                emotion=emotion_result,
            )

        return None

    @staticmethod
    def _has_detailed_quality_description(request: AfterSalesRequest) -> bool:
        text = " ".join(
            part.strip() for part in (request.message, request.reason, request.description) if part
        )
        text = "".join(ch for ch in text if ch not in " ，。！？,.!?:;/\\|_-")
        return len(text) >= 8

    @staticmethod
    def _build_quality_handoff_summary(order: Order | None, request: AfterSalesRequest, risk_result) -> dict[str, str]:
        return {
            "orderId": order.order_id if order else request.order_id or "unknown",
            "problem": request.description or request.message or "用户反馈功能异常",
            "currentStatus": order.after_sales_status.value if order else AfterSalesStatus.NOT_APPLIED.value,
            "evidence": "已上传照片，但图片无法直接确认功能异常",
            "risk": risk_result.risk_level.value,
            "userEmotion": "平稳",
            "suggestedAction": "请客服根据用户描述进一步核实功能异常",
        }

    @staticmethod
    def _apply_emotion_prefix(text: str, emotion_result) -> str:
        prefix = getattr(emotion_result, "comfort_prefix", "")
        if not prefix:
            return text
        if text.startswith(prefix):
            return text
        if text.startswith("您好，"):
            core = text.removeprefix("您好，")
            return f"{prefix}{core}"
        return f"{prefix}{text}"

    @staticmethod
    def _build_progress_hint(order: Order | None, status: AfterSalesStatus) -> str:
        product_name = order.items[0].product_name if order and order.items else "当前商品"
        mapping = {
            AfterSalesStatus.SUBMITTED: f"{product_name} 已提交售后申请，下一步进入商家审核。",
            AfterSalesStatus.WAITING_EVIDENCE: f"{product_name} 当前待补充材料，补齐后进入审核。",
            AfterSalesStatus.MERCHANT_REVIEW: f"{product_name} 当前处于商家审核中。",
            AfterSalesStatus.REFUND_PROCESSING: f"{product_name} 当前进入退款处理阶段。",
            AfterSalesStatus.HUMAN_PROCESSING: f"{product_name} 当前已转人工处理。",
        }
        return mapping.get(status, f"{product_name} 当前售后状态为 {status.value}。")

    @staticmethod
    def _build_audit_note(intent: Intent, risk_result) -> str:
        return (
            f"intent={intent.value}; risk={risk_result.risk_level.value}; "
            f"auto_refund={str(risk_result.allow_auto_refund).lower()}; reason={risk_result.reason}"
        )
