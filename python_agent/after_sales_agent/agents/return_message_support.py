from __future__ import annotations

from ..models import (
    AfterSalesRequest,
    AfterSalesScene,
    AfterSalesStatus,
    EmotionAnalysisResult,
    Intent,
    Order,
    RiskAssessmentResult,
    RiskLevel,
    Ticket,
    TicketStatus,
)


def build_state_reply(status: AfterSalesStatus, *, service_policy=None) -> str:
    template = _template(service_policy, f"state_reply.{status.value}")
    if template:
        return template
    fallback = {
        AfterSalesStatus.MERCHANT_REVIEW: "您好，当前售后申请仍在商家审核中，审核通过后才会进入下一步处理。",
        AfterSalesStatus.PLATFORM_REVIEW: "您好，当前售后申请正在平台复核中，请您耐心等待处理结果。",
        AfterSalesStatus.REFUND_PROCESSING: "您好，退款正在处理中，到账时间以支付渠道实际入账为准。",
        AfterSalesStatus.COMPLETED: "您好，当前售后已经处理完成，您可以查看处理结果。",
    }
    return fallback.get(status, "您好，当前状态暂不支持该操作，请按页面提示继续处理。")


def build_status_answer(
    order: Order | None,
    status: AfterSalesStatus,
    risk_level: RiskLevel,
    request: AfterSalesRequest,
    emotion_result: EmotionAnalysisResult,
    *,
    service_policy=None,
) -> str:
    if status == AfterSalesStatus.MERCHANT_REVIEW:
        return build_merchant_review_reply(order, request, service_policy=service_policy)
    if status == AfterSalesStatus.WAITING_EVIDENCE:
        return _template(service_policy, "status.waiting_evidence") or "您好，当前售后申请还需要补充材料，提交完成后平台会继续审核。"
    if status == AfterSalesStatus.REFUND_PROCESSING:
        return _template(service_policy, "status.refund_processing") or "您好，退款正在处理中，到账时间以支付渠道实际入账为准。"
    if status == AfterSalesStatus.WAITING_RETURN:
        logistics = order.logistics_status if order else "待更新"
        template = _template(service_policy, "status.waiting_return")
        return (template or "您好，请补充退货物流信息，我们会继续跟进售后进度。").format(logistics=logistics)
    if risk_level == RiskLevel.HIGH:
        return apply_emotion_prefix(
            _template(service_policy, "status.high_risk")
            or "您好，当前问题需要进一步核验，我会继续帮您跟进。",
            emotion_result,
        )
    return apply_emotion_prefix(
        _template(service_policy, "status.recorded") or "您好，当前售后信息已经记录，您可以继续关注处理进度。",
        emotion_result,
    )


def build_merchant_review_reply(
    order: Order | None,
    request: AfterSalesRequest,
    *,
    service_policy=None,
) -> str:
    text = " ".join(part for part in (request.message, request.reason, request.description) if part)
    normalized = text.replace(" ", "")

    if is_progress_stalled(order):
        return _template(service_policy, "merchant_review.stalled") or "您好，当前处理时间比平时略长，我会继续帮您跟进。"

    if is_anxious_progress_request(normalized):
        return _template(service_policy, "merchant_review.anxious") or "您好，我理解您在着急等待退款，我会继续帮您跟进进度。"

    return _template(service_policy, "merchant_review.default") or "您好，您的退款申请已收到，当前正在由商家审核。"


def is_anxious_progress_request(text: str) -> bool:
    keywords = ("怎么还没", "一直", "这么慢", "快点", "还不到账", "多久了", "到底")
    return any(keyword in text for keyword in keywords)


def is_progress_stalled(order: Order | None) -> bool:
    if order is None:
        return False
    status_text = f"{order.refund_status} {order.logistics_status}"
    stalled_keywords = ("超时", "未更新", "停滞", "延迟", "异常", "过久")
    return any(keyword in status_text for keyword in stalled_keywords)


def build_ticket_reply(
    ticket: Ticket,
    risk_result: RiskAssessmentResult,
    scene: AfterSalesScene | None = None,
    *,
    service_policy=None,
) -> str:
    del risk_result, scene
    if ticket.next_action == "等待包装补偿评估":
        return (
            _template(service_policy, "ticket_reply.package_damage")
            or f"您好，已为您记录包装破损问题并生成售后申请 {ticket.ticket_id}。"
        ).format(ticket_id=ticket.ticket_id)
    if ticket.status == TicketStatus.AUTO_APPROVED:
        return (
            _template(service_policy, "ticket_reply.auto_approved")
            or f"您好，已为您提交售后申请 {ticket.ticket_id}，系统会尽快推进后续流程。"
        ).format(ticket_id=ticket.ticket_id)
    if ticket.next_action == "等待商品破损审核":
        return (
            _template(service_policy, "ticket_reply.product_damage")
            or f"您好，已为您提交售后申请 {ticket.ticket_id}，预计 {ticket.expected_hours} 小时内更新进度。"
        ).format(ticket_id=ticket.ticket_id, expected_hours=ticket.expected_hours)
    return (
        _template(service_policy, "ticket_reply.default")
        or f"您好，已为您提交售后申请 {ticket.ticket_id}，预计 {ticket.expected_hours} 小时内更新进度。"
    ).format(ticket_id=ticket.ticket_id, expected_hours=ticket.expected_hours)


def build_quality_issue_detail_reply(*, service_policy=None) -> str:
    return _template(service_policy, "quality_issue.ask_for_detail") or (
        "您好，当前只有概括性的质量问题描述，图片也暂时无法直接确认具体异常。"
        "请补充实际表现，例如没有声音、无法开机、充电异常、按键失灵等，我再继续帮您处理。"
    )


def build_quality_issue_detail_progress(*, service_policy=None) -> str:
    return _template(service_policy, "quality_issue.ask_for_detail_progress") or "等待用户补充具体异常表现后继续判断。"


def build_quality_issue_visual_handoff_reply(*, service_policy=None) -> str:
    return _template(service_policy, "quality_issue.visual_handoff") or (
        "您好，已记录您的异常表现。当前图片暂时无法自动确认问题，我这边为您转客服进一步核实处理。"
    )


def build_quality_issue_visual_handoff_progress(*, service_policy=None) -> str:
    return _template(service_policy, "quality_issue.visual_handoff_progress") or (
        "已记录异常描述，但图片无法自动核验，转客服进一步核实。"
    )


def build_quality_issue_auto_approved_progress(*, service_policy=None) -> str:
    return _template(service_policy, "quality_issue.auto_approved_progress") or (
        "图片核验通过，AI 已自动审核并进入处理中状态。"
    )


def has_detailed_quality_description(request: AfterSalesRequest) -> bool:
    if request.quality_description_detailed is not None:
        return request.quality_description_detailed
    return False


def build_quality_handoff_summary(
    order: Order | None,
    request: AfterSalesRequest,
    risk_result: RiskAssessmentResult,
    emotion_result: EmotionAnalysisResult,
) -> dict[str, str]:
    return {
        "orderId": order.order_id if order else request.order_id or "unknown",
        "problem": request.description or request.message or "用户反馈功能异常",
        "currentStatus": order.after_sales_status.value if order else AfterSalesStatus.NOT_APPLIED.value,
        "evidence": "已上传图片，但图片暂时无法直接确认问题。",
        "risk": risk_result.risk_level.value,
        "userEmotion": emotion_result.label.value,
        "suggestedAction": "请客服根据用户描述进一步核实功能异常。",
    }


def apply_emotion_prefix(text: str, emotion_result: EmotionAnalysisResult) -> str:
    prefix = getattr(emotion_result, "comfort_prefix", "")
    if not prefix:
        return text
    if text.startswith(prefix):
        return text
    if text.startswith("您好，"):
        core = text.removeprefix("您好，")
        return f"{prefix}{core}"
    return f"{prefix}{text}"


def build_progress_hint(order: Order | None, status: AfterSalesStatus, *, service_policy=None) -> str:
    product_name = order.items[0].product_name if order and order.items else "当前商品"
    template_key = {
        AfterSalesStatus.SUBMITTED: "progress.submitted",
        AfterSalesStatus.WAITING_EVIDENCE: "progress.waiting_evidence",
        AfterSalesStatus.MERCHANT_REVIEW: "progress.merchant_review",
        AfterSalesStatus.REFUND_PROCESSING: "progress.refund_processing",
        AfterSalesStatus.HUMAN_PROCESSING: "progress.human_processing",
    }.get(status, "progress.default")
    template = _template(service_policy, template_key) or "{product_name} 当前售后状态为 {status_value}。"
    return template.format(product_name=product_name, status_value=status.value)


def build_audit_note(intent: Intent, risk_result: RiskAssessmentResult) -> str:
    return (
        f"intent={intent.value}; risk={risk_result.risk_level.value}; "
        f"auto_refund={str(risk_result.allow_auto_refund).lower()}; reason={risk_result.reason}"
    )


def _template(service_policy, key: str) -> str:
    if service_policy is None:
        return ""
    policy = getattr(service_policy, "service_policy", service_policy)
    getter = getattr(policy, "reply_template", None)
    if callable(getter):
        return getter(key, "")
    templates = getattr(policy, "reply_templates", None)
    if isinstance(templates, dict):
        return str(templates.get(key, ""))
    return ""
