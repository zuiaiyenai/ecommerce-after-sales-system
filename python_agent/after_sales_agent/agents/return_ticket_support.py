from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from ..merchant_policy import MerchantServicePolicy
from ..models import (
    AfterSalesRequest,
    AfterSalesScene,
    AfterSalesType,
    Intent,
    Order,
    RiskAssessmentResult,
    Ticket,
    TicketStatus,
)


def build_ticket(
    order: Order | None,
    request: AfterSalesRequest,
    intent: Intent,
    risk_result: RiskAssessmentResult,
    scene: AfterSalesScene,
    *,
    service_policy: MerchantServicePolicy | None = None,
    force_auto_approve: bool = False,
) -> Ticket:
    after_sales_type = infer_type(
        intent,
        service_policy,
        scene=scene,
        request=request,
    )
    allow_auto_approve = force_auto_approve or (
        risk_result.allow_auto_refund and (service_policy.supports_auto_approve if service_policy else True)
    )
    status = TicketStatus.AUTO_APPROVED if allow_auto_approve else TicketStatus.PENDING_REVIEW
    expected_hours = service_policy.auto_review_hours if (service_policy and allow_auto_approve) else 12
    if not allow_auto_approve:
        expected_hours = service_policy.manual_review_hours if service_policy else 24
    product_name = order.items[0].product_name if order and order.items else "未知商品"
    summary = f"{product_name} 售后申请：{request.message or request.description or '用户发起售后'}"
    if scene == AfterSalesScene.PACKAGE_DAMAGE:
        next_action = "等待包装赔付评估"
    elif scene == AfterSalesScene.PRODUCT_DAMAGE:
        next_action = "等待商品破损审核"
    else:
        next_action = "等待系统处理退款" if allow_auto_approve else "等待审核结果"
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


def infer_type(
    intent: Intent,
    service_policy: MerchantServicePolicy | None = None,
    *,
    scene: AfterSalesScene | None = None,
    request: AfterSalesRequest | None = None,
) -> AfterSalesType:
    fallback_by_intent = {
        Intent.REFUND_ONLY.value: AfterSalesType.REFUND_ONLY,
        Intent.EXCHANGE_REPAIR.value: AfterSalesType.REISSUE,
        Intent.MERCHANT_REJECTED.value: AfterSalesType.RETURN_AND_REFUND,
        Intent.APPLY_AFTER_SALES.value: AfterSalesType.RETURN_AND_REFUND,
        Intent.HUMAN_SERVICE.value: AfterSalesType.RETURN_AND_REFUND,
    }
    fallback = fallback_by_intent.get(intent.value, AfterSalesType.RETURN_AND_REFUND)
    scheme_code = fallback.name
    if service_policy is not None:
        candidate_keys: list[str] = []
        if request is not None and request.requested_type is not None:
            candidate_keys.append(f"requested_type:{request.requested_type.value}")
        if scene is not None:
            candidate_keys.append(f"{intent.value}:{scene.value}")
            candidate_keys.append(f"scene:{scene.value}")
        candidate_keys.append(intent.value)
        scheme_code = service_policy.resolve_after_sales_scheme(tuple(candidate_keys), fallback.name)
    mapping = {
        "REFUND_ONLY": AfterSalesType.REFUND_ONLY,
        "RETURN_REFUND": AfterSalesType.RETURN_REFUND,
        "RETURN_AND_REFUND": AfterSalesType.RETURN_REFUND,
        "REISSUE": AfterSalesType.REISSUE,
        "EXCHANGE": AfterSalesType.REISSUE,
        "PARTIAL_REFUND": AfterSalesType.PARTIAL_REFUND,
        "REPAIR": AfterSalesType.RETURN_REFUND,
    }
    return mapping.get(str(scheme_code or "").strip().upper(), fallback)


def has_detailed_quality_description(request: AfterSalesRequest) -> bool:
    if request.quality_description_detailed is not None:
        return request.quality_description_detailed
    text = " ".join(
        part.strip()
        for part in (request.message, request.reason, request.description)
        if part and part.strip()
    )
    if not text:
        return False
    normalized = "".join(ch for ch in text.lower() if ch not in " ，。！？?!?:;/\\|_-")
    specific_markers = (
        "没声音",
        "没有声音",
        "无法开机",
        "开不了机",
        "充不进电",
        "充电无反应",
        "按键失灵",
        "触控失灵",
        "花屏",
        "闪屏",
        "黑屏",
        "异味",
        "漏水",
        "不能用",
        "故障",
        "异常",
    )
    return any(marker in normalized for marker in specific_markers)
