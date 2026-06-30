from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
from pathlib import Path
from time import perf_counter
from urllib.parse import parse_qs

from after_sales_agent import (
    AfterSalesStatus,
    Attachment,
    ConversationMessage,
    ConversationContext,
    ConversationPersistenceService,
    DatabaseConfig,
    ImageReviewItem,
    ImageReviewResult,
    MySQLRepository,
    Order,
    OrderItem,
    OrderStatus,
    QwenReturnService,
    ReturnConversationService,
)
from after_sales_agent.trace import TraceRecorder


def sample_orders() -> list[Order]:
    now = datetime.now()
    return [
        Order(
            order_id="202405220123456789",
            user_id="u1001",
            status=OrderStatus.DELIVERED,
            amount=39.0,
            created_at=now - timedelta(days=5),
            shipped_at=now - timedelta(days=4),
            delivered_at=now - timedelta(days=2),
            items=(OrderItem("sku-100", "轻音降噪无线耳机 X3", "数码", 1, 39.0),),
            after_sales_status=AfterSalesStatus.NOT_APPLIED,
        ),
        Order(
            order_id="202405180123456780",
            user_id="u1001",
            status=OrderStatus.AFTER_SALES,
            amount=899.0,
            created_at=now - timedelta(days=8),
            shipped_at=now - timedelta(days=7),
            delivered_at=now - timedelta(days=5),
            items=(OrderItem("sku-200", "智能香薰加湿器 Pro", "家电", 1, 899.0),),
            has_open_after_sales=True,
            after_sales_status=AfterSalesStatus.MERCHANT_REVIEW,
            refund_status="未进入退款流程",
            uploaded_evidence=("破损照片",),
        ),
        Order(
            order_id="202405150123456781",
            user_id="u1001",
            status=OrderStatus.AFTER_SALES,
            amount=459.0,
            created_at=now - timedelta(days=12),
            shipped_at=now - timedelta(days=11),
            delivered_at=now - timedelta(days=8),
            items=(OrderItem("sku-300", "纯棉针织衫", "服饰", 1, 459.0),),
            has_open_after_sales=True,
            after_sales_status=AfterSalesStatus.REJECTED,
            merchant_rejected_before=True,
        ),
    ]


SERVICE = ReturnConversationService()
QWEN_SERVICE = QwenReturnService()
PERSISTENCE = None
DB_REPOSITORY = None
TRACE_HISTORY: deque[dict[str, object]] = deque(maxlen=120)


def load_orders() -> list[Order]:
    try:
        repo = MySQLRepository(DatabaseConfig.from_env_file())
        orders = repo.list_orders(limit=20)
        if orders:
            return orders
    except Exception:
        pass
    return sample_orders()


ORDERS = load_orders()
ORDER_MAP = {order.order_id: order for order in ORDERS}

try:
    _repo = MySQLRepository(DatabaseConfig.from_env_file())
    DB_REPOSITORY = _repo
    PERSISTENCE = ConversationPersistenceService(_repo)
except Exception:
    PERSISTENCE = None
    DB_REPOSITORY = None


def build_order_from_payload(data: dict) -> Order | None:
    selected = data.get("selected_order")
    if not isinstance(selected, dict):
        return None

    status_value = str(selected.get("status") or "").strip().lower()
    after_sales_value = str(selected.get("after_sales_status") or "not_applied").strip().lower()
    status_map = {
        "paid": OrderStatus.PAID,
        "shipped": OrderStatus.SHIPPED,
        "delivered": OrderStatus.DELIVERED,
        "completed": OrderStatus.COMPLETED,
        "after_sales": OrderStatus.AFTER_SALES,
        "refunded": OrderStatus.REFUNDED,
    }
    after_sales_map = {
        "not_applied": AfterSalesStatus.NOT_APPLIED,
        "submitted": AfterSalesStatus.SUBMITTED,
        "waiting_evidence": AfterSalesStatus.WAITING_EVIDENCE,
        "merchant_review": AfterSalesStatus.MERCHANT_REVIEW,
        "platform_review": AfterSalesStatus.PLATFORM_REVIEW,
        "approved": AfterSalesStatus.APPROVED,
        "rejected": AfterSalesStatus.REJECTED,
        "waiting_return": AfterSalesStatus.WAITING_RETURN,
        "refund_processing": AfterSalesStatus.REFUND_PROCESSING,
        "exchange_processing": AfterSalesStatus.EXCHANGE_PROCESSING,
        "completed": AfterSalesStatus.COMPLETED,
        "human_processing": AfterSalesStatus.HUMAN_PROCESSING,
    }
    status = status_map.get(status_value)
    after_sales_status = after_sales_map.get(after_sales_value, AfterSalesStatus.NOT_APPLIED)
    if status is None:
        return None

    order_id = str(selected.get("order_id") or "").strip()
    user_id = str(selected.get("user_id") or "u1001").strip()
    product_name = str(selected.get("product_name") or "未知商品").strip()
    category = str(selected.get("category") or "未知分类").strip()
    amount = float(selected.get("amount") or 0)
    delivered_days = selected.get("delivered_days")
    delivered_at = None
    if isinstance(delivered_days, int):
        delivered_at = datetime.now() - timedelta(days=delivered_days)

    if not order_id:
        return None

    return Order(
        order_id=order_id,
        user_id=user_id,
        status=status,
        amount=amount,
        created_at=datetime.now() - timedelta(days=5),
        shipped_at=datetime.now() - timedelta(days=4),
        delivered_at=delivered_at,
        items=(OrderItem("sku-dynamic", product_name, category, 1, amount),),
        has_open_after_sales=bool(selected.get("has_open_after_sales")),
        after_sales_status=after_sales_status,
        refund_status=str(selected.get("refund_status") or "未开始"),
        logistics_status=str(selected.get("logistics_status") or "待更新"),
        uploaded_evidence=tuple(selected.get("uploaded_evidence") or ()),
        merchant_rejected_before=bool(selected.get("merchant_rejected_before")),
    )


def build_history_summary(
    *,
    selected_order: Order | None,
    message: str,
    human_request_count: int,
    recent_history: tuple[ConversationMessage, ...],
) -> dict[str, object]:
    user_messages = [item.content for item in recent_history if item.role == "user"]
    assistant_messages = [item.content for item in recent_history if item.role == "assistant"]
    combined_text = " ".join(user_messages + [message])
    emotion_text = "平稳"
    if any(keyword in combined_text for keyword in ("投诉", "差评", "举报", "太慢", "生气", "骗人")):
        emotion_text = "不满"
    elif any(keyword in combined_text for keyword in ("什么时候", "怎么还", "一直没", "多久", "催一下")):
        emotion_text = "着急"
    return {
        "用户核心诉求": infer_core_request(message, selected_order),
        "已提供证据": list(selected_order.uploaded_evidence if selected_order else ()),
        "仍缺少证据": [],
        "当前售后状态": selected_order.after_sales_status.value if selected_order else "unknown",
        "是否已解释过": any(
            any(keyword in content for keyword in ("审核", "进度", "退款流程", "状态更新", "处理中", "催办"))
            for content in assistant_messages
        ),
        "是否多次追问": len(user_messages) >= 2,
        "是否要求人工": human_request_count > 0 or "人工" in combined_text or "客服" in combined_text,
        "用户情绪": emotion_text,
    }


def infer_core_request(message: str, selected_order: Order | None) -> str:
    text = (message or "").strip()
    if any(keyword in text for keyword in ("退款", "到账", "退钱")):
        return "退款进度"
    if any(keyword in text for keyword in ("人工", "客服", "真人")):
        return "人工客服"
    if any(keyword in text for keyword in ("物流", "快递", "面单")):
        return "物流异常"
    if any(keyword in text for keyword in ("凭证", "上传", "补充", "照片")):
        return "补充凭证"
    if selected_order is not None and selected_order.after_sales_status == AfterSalesStatus.MERCHANT_REVIEW:
        return "售后进度"
    return "售后咨询"


def display_after_sales_status(status: AfterSalesStatus) -> str:
    mapping = {
        AfterSalesStatus.NOT_APPLIED: "未申请售后",
        AfterSalesStatus.SUBMITTED: "已提交申请",
        AfterSalesStatus.WAITING_EVIDENCE: "待补充凭证",
        AfterSalesStatus.MERCHANT_REVIEW: "商家审核中",
        AfterSalesStatus.PLATFORM_REVIEW: "平台复核中",
        AfterSalesStatus.APPROVED: "审核通过",
        AfterSalesStatus.REJECTED: "审核驳回",
        AfterSalesStatus.WAITING_RETURN: "待用户退货",
        AfterSalesStatus.REFUND_PROCESSING: "退款处理中",
        AfterSalesStatus.EXCHANGE_PROCESSING: "换货处理中",
        AfterSalesStatus.COMPLETED: "售后完成",
        AfterSalesStatus.HUMAN_PROCESSING: "人工处理中",
    }
    return mapping.get(status, status.value)


def record_trace_event(
    trace: TraceRecorder,
    *,
    path: str,
    order_id: str | None = None,
    session_id: int | None = None,
    reply_preview: str | None = None,
) -> None:
    payload = trace.to_dict()
    TRACE_HISTORY.appendleft(
        {
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "path": path,
            "order_id": order_id or "",
            "session_id": session_id,
            "reply_preview": (reply_preview or "")[:120],
            "trace": payload,
        }
    )


def list_trace_events(limit: int = 50) -> list[dict[str, object]]:
    return list(TRACE_HISTORY)[: max(1, min(limit, len(TRACE_HISTORY) or 1))]


def display_order_status(status: OrderStatus) -> str:
    mapping = {
        OrderStatus.PAID: "待发货",
        OrderStatus.SHIPPED: "运输中",
        OrderStatus.DELIVERED: "已签收",
        OrderStatus.COMPLETED: "已完成",
        OrderStatus.AFTER_SALES: "售后中",
        OrderStatus.REFUNDED: "已退款",
    }
    return mapping.get(status, status.value)


def current_millis() -> float:
    return perf_counter()


def elapsed_ms(started_at: float) -> int:
    return int((perf_counter() - started_at) * 1000)


def build_trace_meta(*, attachments: tuple[Attachment, ...], skip_image_review: bool) -> dict[str, object]:
    return {
        "attachment_count": len(attachments),
        "attachment_kinds": [attachment.kind for attachment in attachments],
        "skip_image_review": skip_image_review,
        "vision_model": SERVICE.vision_service.client.config.model,
        "text_model": QWEN_SERVICE.client.config.model,
    }


def render_page(result_html: str = "", form_values: dict[str, str] | None = None) -> str:
    values = form_values or {}
    selected_order_id = values.get("order_id", ORDERS[0].order_id)
    options = []
    for order in ORDERS:
        selected = "selected" if order.order_id == selected_order_id else ""
        label = f"{order.items[0].product_name} | 订单号 {order.order_id} | 状态 {display_after_sales_status(order.after_sales_status)}"
        options.append(f'<option value="{order.order_id}" {selected}>{html.escape(label)}</option>')
    message = html.escape(values.get("message", ""))
    description = html.escape(values.get("description", ""))
    opened = values.get("item_opened", "")
    opened_yes = "selected" if opened == "false" else ""
    opened_no = "selected" if opened == "true" else ""
    opened_unknown = "selected" if opened not in {"true", "false"} else ""
    has_photo = "checked" if values.get("has_photo") == "on" else ""

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>售后对话测试</title>
  <style>
    :root {{
      --bg: linear-gradient(160deg, #f7f2eb 0%, #eef4ff 48%, #f8fbff 100%);
      --card: rgba(255,255,255,0.78);
      --border: rgba(62,90,160,0.12);
      --text: #1f2a44;
      --muted: #6e7a96;
      --accent: #5b6cff;
      --shadow: 0 18px 60px rgba(45, 72, 140, 0.12);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      color: var(--text);
      background: var(--bg);
      min-height: 100vh;
      padding: 28px;
    }}
    .shell {{
      max-width: 1120px;
      margin: 0 auto;
      display: grid;
      grid-template-columns: 360px 1fr;
      gap: 24px;
    }}
    .panel {{
      background: var(--card);
      backdrop-filter: blur(18px);
      border: 1px solid var(--border);
      border-radius: 28px;
      box-shadow: var(--shadow);
      padding: 24px;
    }}
    h1 {{
      font-size: 34px;
      margin: 0 0 8px;
    }}
    .subtitle {{
      color: var(--muted);
      margin-bottom: 24px;
      line-height: 1.7;
    }}
    .order-list {{
      display: grid;
      gap: 14px;
    }}
    .order-card {{
      border: 1px solid var(--border);
      border-radius: 22px;
      padding: 16px;
      background: rgba(255,255,255,0.72);
    }}
    .order-card strong {{
      display: block;
      font-size: 19px;
      margin-bottom: 8px;
    }}
    .meta {{
      color: var(--muted);
      line-height: 1.8;
      font-size: 14px;
    }}
    .tag {{
      display: inline-block;
      margin-top: 10px;
      padding: 6px 12px;
      border-radius: 999px;
      background: rgba(91, 108, 255, 0.12);
      color: var(--accent);
      font-size: 13px;
    }}
    form {{
      display: grid;
      gap: 16px;
    }}
    label {{
      display: grid;
      gap: 8px;
      font-weight: 600;
    }}
    input, textarea, select {{
      width: 100%;
      border: 1px solid rgba(62,90,160,0.16);
      background: rgba(255,255,255,0.86);
      border-radius: 16px;
      padding: 14px 16px;
      font-size: 15px;
      color: var(--text);
    }}
    textarea {{
      min-height: 120px;
      resize: vertical;
    }}
    .row {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 14px;
    }}
    .check {{
      display: flex;
      align-items: center;
      gap: 10px;
      font-weight: 500;
      color: var(--muted);
    }}
    .check input {{
      width: 18px;
      height: 18px;
    }}
    button {{
      border: 0;
      border-radius: 18px;
      padding: 14px 18px;
      font-size: 16px;
      font-weight: 700;
      color: white;
      background: linear-gradient(135deg, var(--accent), #7887ff);
      cursor: pointer;
      box-shadow: 0 14px 30px rgba(91, 108, 255, 0.25);
    }}
    .result {{
      margin-top: 20px;
      padding: 18px;
      border-radius: 22px;
      background: linear-gradient(160deg, rgba(91,108,255,0.09), rgba(126,214,199,0.10));
      border: 1px solid rgba(91,108,255,0.12);
      line-height: 1.8;
    }}
    .result strong {{
      display: inline-block;
      min-width: 92px;
    }}
    .hint {{
      color: var(--muted);
      font-size: 14px;
    }}
    @media (max-width: 920px) {{
      .shell {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <section class="panel">
      <h1>售后服务中心</h1>
      <div class="subtitle">左侧是模拟订单，右侧是售后总控 Agent 的最小可运行测试页。现在的流程是：意图识别、状态机、证据检查、风险评估、人工升级，再由对话层生成回复。</div>
      <div class="order-list">
        {''.join(render_order_card(order) for order in ORDERS)}
      </div>
    </section>
    <section class="panel">
      <h1>AI 售后助手</h1>
      <div class="subtitle">先选择订单，再输入用户问题，比如“退款什么时候到账”“我要补充凭证”“商家拒绝了”。</div>
      <form method="post">
        <label>
          当前订单
          <select name="order_id">
            {''.join(options)}
          </select>
        </label>
        <label>
          用户问题
          <textarea name="message" placeholder="例如：我的耳机破损了，退款什么时候到账？">{message}</textarea>
        </label>
        <label>
          补充说明
          <textarea name="description" placeholder="例如：左耳没有声音，外壳裂开">{description}</textarea>
        </label>
        <div class="row">
          <label>
            商品是否拆封
            <select name="item_opened">
              <option value="" {opened_unknown}>暂未说明</option>
              <option value="false" {opened_yes}>未拆封</option>
              <option value="true" {opened_no}>已拆封</option>
            </select>
          </label>
          <label>
            凭证模拟
            <div class="check">
              <input type="checkbox" name="has_photo" {has_photo}>
              <span>已上传商品照片</span>
            </div>
            <div class="hint">用于模拟已上传凭证，便于测试证据检查流程。</div>
          </label>
        </div>
        <button type="submit">发送给售后 Agent</button>
      </form>
      {result_html}
    </section>
  </div>
</body>
</html>"""


def render_order_card(order: Order) -> str:
    return f"""
    <div class="order-card">
      <strong>{html.escape(order.items[0].product_name)}</strong>
      <div class="meta">
        订单号：{html.escape(order.order_id)}<br>
        商品分类：{html.escape(order.items[0].category)}<br>
        金额：{order.amount:.2f} 元<br>
        售后状态：{html.escape(display_after_sales_status(order.after_sales_status))}
      </div>
      <span class="tag">{html.escape(display_order_status(order.status))}</span>
    </div>"""


def render_result(result) -> str:
    ticket_block = ""
    if result.ticket:
        ticket_block = (
            f"<div><strong>工单编号</strong>{html.escape(result.ticket.ticket_id)}</div>"
            f"<div><strong>工单状态</strong>{html.escape(result.ticket.status.value)}</div>"
        )
    handoff = json.dumps(result.handoff_summary, ensure_ascii=False) if result.handoff_summary else "无"
    missing = "、".join(result.missing_fields) if result.missing_fields else "无"
    progress = result.progress_hint or "无"
    audit = result.audit_note or "无"
    return f"""
    <div class="result">
      <div><strong>决策</strong>{html.escape(result.decision.value)}</div>
      <div><strong>意图</strong>{html.escape(result.intent.value)}</div>
      <div><strong>下一模块</strong>{html.escape(result.next_agent)}</div>
      <div><strong>用户回复</strong>{html.escape(result.user_reply)}</div>
      <div><strong>缺失信息</strong>{html.escape(missing)}</div>
      {ticket_block}
      <div><strong>进度提示</strong>{html.escape(progress)}</div>
      <div><strong>审计信息</strong>{html.escape(audit)}</div>
      <div><strong>人工摘要</strong>{html.escape(handoff)}</div>
    </div>"""


def build_attachments(payload_attachments: list | tuple | None) -> tuple[Attachment, ...]:
    attachments: list[Attachment] = []
    for item in payload_attachments or []:
        if isinstance(item, str):
            kind = item.strip()
            if not kind:
                continue
            attachments.append(Attachment(kind=kind, name=f"{kind}.jpg"))
            continue
        if isinstance(item, dict):
            kind = str(item.get("kind") or "商品照片").strip()
            name = str(item.get("name") or f"{kind}.jpg").strip()
            source = item.get("source")
            attachments.append(Attachment(kind=kind, name=name, source=source))
    return tuple(attachments)


def parse_image_review_payload(data: dict | None) -> ImageReviewResult | None:
    if not isinstance(data, dict):
        return None
    item_payloads = data.get("items") or []
    items = tuple(
        ImageReviewItem(
            name=str(item.get("name") or ""),
            image_type=str(item.get("image_type") or ""),
            is_clear=bool(item.get("is_clear")),
            contains_damage_area=bool(item.get("contains_damage_area")),
            contains_outer_package=bool(item.get("contains_outer_package")),
            contains_logistics_label=bool(item.get("contains_logistics_label")),
            logistics_matches_order=bool(item.get("logistics_matches_order")),
            courier_company=str(item.get("courier_company") or ""),
            tracking_number=str(item.get("tracking_number") or ""),
            sender_name=str(item.get("sender_name") or ""),
            receiver_name=str(item.get("receiver_name") or ""),
            confidence=float(item.get("confidence") or 0.0),
            notes=str(item.get("notes") or ""),
        )
        for item in item_payloads
        if isinstance(item, dict)
    )
    return ImageReviewResult(
        success=bool(data.get("success")),
        items=items,
        all_clear=bool(data.get("all_clear")),
        has_damage_area=bool(data.get("has_damage_area")),
        has_outer_package=bool(data.get("has_outer_package")),
        has_logistics_label=bool(data.get("has_logistics_label")),
        logistics_matches_order=bool(data.get("logistics_matches_order")),
        courier_company=str(data.get("courier_company") or ""),
        tracking_number=str(data.get("tracking_number") or ""),
        sender_name=str(data.get("sender_name") or ""),
        receiver_name=str(data.get("receiver_name") or ""),
        missing_visual_evidence=tuple(data.get("missing_visual_evidence") or ()),
        summary=str(data.get("summary") or ""),
        raw=data.get("raw") or {},
    )


class DemoHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path in {"/", "/index.html"}:
            self._send_html(render_page())
            return
        if self.path == "/static":
            file_path = Path(__file__).with_name("static_demo.html")
            self._send_file(file_path, "text/html; charset=utf-8")
            return
        if self.path == "/monitor":
            file_path = Path(__file__).with_name("trace_monitor.html")
            self._send_file(file_path, "text/html; charset=utf-8")
            return
        if self.path == "/api/health":
            self._send_json({"ok": True})
            return
        if self.path.startswith("/api/traces"):
            self._handle_traces_api()
            return
        self._send_html(render_page())

    def do_POST(self) -> None:
        if self.path == "/api/chat":
            self._handle_chat_api()
            return
        if self.path == "/api/review-images":
            self._handle_review_images()
            return
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length).decode("utf-8")
        data = parse_qs(body)
        order_id = data.get("order_id", [""])[0]
        message = data.get("message", [""])[0]
        description = data.get("description", [""])[0] or None
        item_opened_value = data.get("item_opened", [""])[0]
        has_photo = "has_photo" in data

        item_opened = None
        if item_opened_value == "true":
            item_opened = True
        elif item_opened_value == "false":
            item_opened = False

        attachments = ()
        if has_photo:
            attachments = (Attachment(kind="商品照片", name="mock-photo.jpg"),)

        context = ConversationContext(
            user_id="u1001",
            selected_order=ORDER_MAP.get(order_id),
            message=message,
            description=description,
            item_opened=item_opened,
            human_request_count=1 if any(keyword in message for keyword in ("人工", "客服", "真人")) else 0,
            attachments=attachments,
        )
        result = SERVICE.handle(context)
        form_values = {
            "order_id": order_id,
            "message": message,
            "description": description or "",
            "item_opened": item_opened_value,
            "has_photo": "on" if has_photo else "",
        }
        self._send_html(render_page(render_result(result), form_values))

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def log_message(self, format: str, *args) -> None:
        return

    def _send_html(self, page: str) -> None:
        content = page.encode("utf-8")
        self.send_response(200)
        self._send_cors_headers()
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self._safe_write(content)

    def _send_file(self, path: Path, content_type: str) -> None:
        content = path.read_bytes()
        self.send_response(200)
        self._send_cors_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self._safe_write(content)

    def _send_json(self, payload: dict) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self._safe_write(content)

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def _safe_write(self, content: bytes) -> None:
        try:
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, socket.error):
            return

    def _handle_chat_api(self) -> None:
        trace = TraceRecorder(request_type="chat")
        content_length = int(self.headers.get("Content-Length", "0"))
        with trace.step("read_request_body"):
            body = self.rfile.read(content_length).decode("utf-8")
            data = json.loads(body or "{}")

        order_id = data.get("order_id")
        session_id = data.get("session_id")
        message = str(data.get("message") or "")
        description = data.get("description")
        item_opened = data.get("item_opened")
        human_request_count = int(data.get("human_request_count") or 0)
        skip_image_review = bool(data.get("skip_image_review"))
        image_review = parse_image_review_payload(data.get("image_review"))
        attachments = build_attachments(data.get("attachments"))
        trace.set_meta(**build_trace_meta(attachments=attachments, skip_image_review=skip_image_review))
        selected_order = build_order_from_payload(data)
        if selected_order is None and order_id:
            selected_order = ORDER_MAP.get(order_id)
        order_hint = None
        if selected_order is not None:
            order_hint = f"订单号：{selected_order.order_id}；商品：{selected_order.items[0].product_name}"
        if image_review is None and not skip_image_review:
            SERVICE.vision_service.bind_trace(trace)
            with trace.step("review_images", order_hint=bool(order_hint)):
                image_review = SERVICE.review_images(attachments, order_hint=order_hint)
            SERVICE.vision_service.bind_trace(None)
        elif image_review is not None:
            trace.set_meta(image_review_source="frontend_cached")
        elif skip_image_review:
            trace.set_meta(image_review_source="skipped")
        recent_history: tuple[ConversationMessage, ...] = ()
        history_summary = None
        if DB_REPOSITORY is not None and session_id is not None:
            try:
                with trace.step("load_recent_history", session_id=int(session_id), limit=6):
                    recent_history = DB_REPOSITORY.get_recent_messages(int(session_id), limit=6)
                    history_summary = build_history_summary(
                        selected_order=selected_order,
                        message=message,
                        human_request_count=human_request_count,
                        recent_history=recent_history,
                    )
            except Exception:
                recent_history = ()
                history_summary = None
        context = ConversationContext(
            user_id="u1001",
            selected_order=selected_order,
            message=message,
            session_id=int(session_id) if session_id is not None else None,
            description=description,
            item_opened=item_opened,
            human_request_count=human_request_count,
            attachments=attachments,
            image_review=image_review,
            recent_history=recent_history,
            history_summary=history_summary,
        )
        QWEN_SERVICE.bind_trace(trace)
        with trace.step("generate_assistant_reply"):
            result = QWEN_SERVICE.handle(context)
        QWEN_SERVICE.bind_trace(None)
        persistence_result = None
        if PERSISTENCE is not None:
            try:
                with trace.step("persist_interaction"):
                    persistence_result = PERSISTENCE.persist_interaction(
                        context=context,
                        result=result,
                        source_channel="H5",
                    )
            except Exception:
                persistence_result = None
        ticket = result.fallback_result.ticket
        self._send_json(
            {
                "assistant_reply": result.assistant_reply,
                "intent": result.intent,
                "suggested_action": result.suggested_action,
                "evidence_needed": list(result.evidence_needed),
                "fallback_decision": result.fallback_result.decision.value,
                "fallback_progress_hint": result.fallback_result.progress_hint,
                "fallback_need_human": result.fallback_result.need_human,
                "ticket": {
                    "ticket_id": ticket.ticket_id,
                    "status": ticket.status.value,
                    "expected_hours": ticket.expected_hours,
                }
                if ticket
                else None,
                "handoff_summary": result.fallback_result.handoff_summary,
                "emotion": {
                    "label": result.fallback_result.emotion.label.value,
                    "score": result.fallback_result.emotion.score,
                    "triggers": list(result.fallback_result.emotion.triggers),
                    "need_human_priority": result.fallback_result.emotion.need_human_priority,
                    "reply_tone": result.fallback_result.emotion.reply_tone,
                    "comfort_prefix": result.fallback_result.emotion.comfort_prefix,
                }
                if result.fallback_result.emotion
                else None,
                "image_review": self._serialize_image_review(image_review),
                "persistence": {
                    "session_id": persistence_result.session_id,
                    "session_no": persistence_result.session_no,
                    "user_message_id": persistence_result.user_message_id,
                    "assistant_message_id": persistence_result.assistant_message_id,
                    "ticket_log_id": persistence_result.ticket_log_id,
                    "notice_id": persistence_result.notice_id,
                }
                if persistence_result
                else None,
                "raw": result.raw,
                "trace": trace.to_dict(),
            }
        )
        record_trace_event(
            trace,
            path="/api/chat",
            order_id=str(order_id or ""),
            session_id=persistence_result.session_id if persistence_result else (int(session_id) if session_id is not None else None),
            reply_preview=result.assistant_reply,
        )

    def _handle_review_images(self) -> None:
        trace = TraceRecorder(request_type="review_images")
        content_length = int(self.headers.get("Content-Length", "0"))
        with trace.step("read_request_body"):
            body = self.rfile.read(content_length).decode("utf-8")
            data = json.loads(body or "{}")
        attachments = build_attachments(data.get("attachments"))
        order_hint = str(data.get("order_hint") or "").strip() or None
        trace.set_meta(
            attachment_count=len(attachments),
            attachment_kinds=[attachment.kind for attachment in attachments],
            vision_model=SERVICE.vision_service.client.config.model,
        )
        image_review = None
        try:
            SERVICE.vision_service.bind_trace(trace)
            with trace.step("review_images", order_hint=bool(order_hint)):
                image_review = SERVICE.review_images(attachments, order_hint=order_hint)
        except Exception as exc:
            image_review = ImageReviewResult(
                success=False,
                items=(),
                all_clear=False,
                has_damage_area=False,
                has_outer_package=False,
                has_logistics_label=False,
                logistics_matches_order=False,
                courier_company="",
                tracking_number="",
                sender_name="",
                receiver_name="",
                missing_visual_evidence=("图片分析结果待补充",),
                summary="图片分析暂时异常，我会先根据您的描述继续处理，稍后补充图片分析结果。",
                raw={
                    "mode": "review_images_exception",
                    "error": exc.__class__.__name__,
                    "message": str(exc),
                },
            )
        finally:
            SERVICE.vision_service.bind_trace(None)
        self._send_json(
            {
                "image_review": self._serialize_image_review(image_review),
                "trace": trace.to_dict(),
            }
        )
        record_trace_event(
            trace,
            path="/api/review-images",
            order_id="",
            session_id=None,
            reply_preview=image_review.summary if image_review else "",
        )

    def _handle_traces_api(self) -> None:
        self._send_json(
            {
                "items": list_trace_events(limit=60),
            }
        )

    @staticmethod
    def _serialize_image_review(image_review: ImageReviewResult | None) -> dict | None:
        if image_review is None:
            return None
        return {
            "success": image_review.success,
            "all_clear": image_review.all_clear,
            "has_damage_area": image_review.has_damage_area,
            "has_outer_package": image_review.has_outer_package,
            "has_logistics_label": image_review.has_logistics_label,
            "logistics_matches_order": image_review.logistics_matches_order,
            "courier_company": image_review.courier_company,
            "tracking_number": image_review.tracking_number,
            "sender_name": image_review.sender_name,
            "receiver_name": image_review.receiver_name,
            "missing_visual_evidence": list(image_review.missing_visual_evidence),
            "summary": image_review.summary,
            "items": [
                {
                    "name": item.name,
                    "image_type": item.image_type,
                    "is_clear": item.is_clear,
                    "contains_damage_area": item.contains_damage_area,
                    "contains_outer_package": item.contains_outer_package,
                    "contains_logistics_label": item.contains_logistics_label,
                    "logistics_matches_order": item.logistics_matches_order,
                    "courier_company": item.courier_company,
                    "tracking_number": item.tracking_number,
                    "sender_name": item.sender_name,
                    "receiver_name": item.receiver_name,
                    "confidence": item.confidence,
                    "notes": item.notes,
                }
                for item in image_review.items
            ],
            "raw": image_review.raw,
        }


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 8000), DemoHandler)
    print("Demo running at http://127.0.0.1:8000")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
