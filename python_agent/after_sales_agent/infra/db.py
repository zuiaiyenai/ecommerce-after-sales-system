from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pymysql

from ..models import AfterSalesStatus, AfterSalesType, ConversationMessage, Order, OrderItem, OrderStatus, Ticket


@dataclass(frozen=True)
class DatabaseConfig:
    host: str
    port: int
    user: str
    password: str
    database: str
    charset: str = "utf8mb4"

    @classmethod
    def from_env_file(cls, env_path: str | Path | None = None) -> "DatabaseConfig":
        values = _read_env_file(env_path)
        return cls(
            host=values.get("MYSQL_HOST", "localhost"),
            port=int(values.get("MYSQL_PORT", "3306")),
            user=values["MYSQL_USER"],
            password=values["MYSQL_PASSWORD"],
            database=values["MYSQL_DATABASE"],
            charset=values.get("MYSQL_CHARSET", "utf8mb4"),
        )


class MySQLRepository:
    def __init__(self, config: DatabaseConfig) -> None:
        self.config = config

    @staticmethod
    def _new_id() -> int:
        """Generate a BIGINT id for tables whose ids are assigned by the Java layer."""
        return int(datetime.now().timestamp() * 1_000_000) * 1024 + (uuid4().int & 0x3FF)

    def list_orders(self, limit: int = 20) -> list[Order]:
        sql = """
        SELECT
            o.id,
            o.order_no,
            o.user_id,
            o.total_amount,
            o.pay_amount,
            o.status,
            o.tracking_company,
            o.tracking_no,
            o.pay_time,
            o.ship_time,
            o.receive_time,
            o.create_time
        FROM order_info o
        WHERE o.deleted = 0
        ORDER BY o.create_time DESC
        LIMIT %s
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (limit,))
                rows = cur.fetchall()
        return self._build_orders(rows)

    def get_order_by_order_no(self, order_no: str) -> Order | None:
        sql = """
        SELECT
            o.id,
            o.order_no,
            o.user_id,
            o.total_amount,
            o.pay_amount,
            o.status,
            o.tracking_company,
            o.tracking_no,
            o.pay_time,
            o.ship_time,
            o.receive_time,
            o.create_time
        FROM order_info o
        WHERE o.deleted = 0 AND o.order_no = %s
        LIMIT 1
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (order_no,))
                row = cur.fetchone()
        if not row:
            return None
        orders = self._build_orders((row,))
        return orders[0] if orders else None

    def get_order_by_id(self, order_id: int) -> Order | None:
        sql = """
        SELECT
            o.id,
            o.order_no,
            o.user_id,
            o.total_amount,
            o.pay_amount,
            o.status,
            o.tracking_company,
            o.tracking_no,
            o.pay_time,
            o.ship_time,
            o.receive_time,
            o.create_time
        FROM order_info o
        WHERE o.deleted = 0 AND o.id = %s
        LIMIT 1
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (order_id,))
                row = cur.fetchone()
        if not row:
            return None
        orders = self._build_orders((row,))
        return orders[0] if orders else None

    def get_recent_ticket_snapshot(self, order_id: int) -> dict[str, Any] | None:
        sql = """
        SELECT
            t.id,
            t.ticket_no,
            t.after_sale_type,
            t.reason,
            t.reason_detail,
            t.description,
            t.refund_amount,
            t.ai_recommend_type,
            t.status,
            t.priority,
            t.audit_opinion,
            t.expected_complete_time,
            t.complete_time,
            t.create_time
        FROM after_sales_ticket t
        WHERE t.order_id = %s AND t.deleted = 0
        ORDER BY t.update_time DESC, t.create_time DESC
        LIMIT 1
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (order_id,))
                row = cur.fetchone()
        if not row:
            return None
        columns = (
            "id",
            "ticket_no",
            "after_sale_type",
            "reason",
            "reason_detail",
            "description",
            "refund_amount",
            "ai_recommend_type",
            "status",
            "priority",
            "audit_opinion",
            "expected_complete_time",
            "complete_time",
            "create_time",
        )
        return dict(zip(columns, row))

    def get_ticket_attachments(self, ticket_id: int) -> tuple[str, ...]:
        sql = """
        SELECT file_type
        FROM ticket_attachment
        WHERE ticket_id = %s
        ORDER BY sort_order ASC, create_time ASC
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (ticket_id,))
                rows = cur.fetchall()
        return tuple(self._normalize_attachment_type(row[0]) for row in rows)

    def count_user_after_sales(self, user_id: int) -> int:
        sql = """
        SELECT COUNT(*)
        FROM after_sales_ticket
        WHERE user_id = %s AND deleted = 0
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (user_id,))
                row = cur.fetchone()
        return int(row[0] or 0)

    def resolve_order_db_id(self, order_no: str) -> int | None:
        sql = """
        SELECT id
        FROM order_info
        WHERE order_no = %s AND deleted = 0
        LIMIT 1
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (order_no,))
                row = cur.fetchone()
        return int(row[0]) if row else None

    def update_order_status_to_aftersale(self, order_db_id: int) -> None:
        sql = """
        UPDATE order_info
        SET status = 'AFTERSALE', update_time = NOW()
        WHERE id = %s AND deleted = 0
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (order_db_id,))
                conn.commit()

    def resolve_recent_ticket_id(self, order_db_id: int) -> int | None:
        sql = """
        SELECT id
        FROM after_sales_ticket
        WHERE order_id = %s AND deleted = 0
        ORDER BY update_time DESC, create_time DESC
        LIMIT 1
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (order_db_id,))
                row = cur.fetchone()
        return int(row[0]) if row else None

    def resolve_ticket_no(self, ticket_id: int | None) -> str | None:
        if ticket_id is None:
            return None
        sql = """
        SELECT ticket_no
        FROM after_sales_ticket
        WHERE id = %s AND deleted = 0
        LIMIT 1
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (ticket_id,))
                row = cur.fetchone()
        return str(row[0]) if row and row[0] is not None else None

    def find_or_create_handoff_ticket(
        self,
        *,
        order_db_id: int,
        order_no: str,
        user_id: int,
        product_name: str,
        refund_amount: float,
        description: str,
        ai_summary: dict[str, str] | None = None,
    ) -> int:
        existing_sql = """
        SELECT id
        FROM after_sales_ticket
        WHERE order_id = %s
          AND deleted = 0
          AND status IN ('PENDING', 'PENDING_REVIEW', 'PROCESSING', 'COMPLETED')
        ORDER BY update_time DESC, create_time DESC
        LIMIT 1
        """
        order_sql = """
        SELECT merchant_id, merchant_code
        FROM order_info
        WHERE id = %s AND deleted = 0
        LIMIT 1
        """
        insert_sql = """
        INSERT INTO after_sales_ticket (
            id, ticket_no, order_id, order_no, user_id, merchant_id, merchant_code,
            product_name, after_sale_type, reason, reason_detail, description,
            refund_amount, ai_classify_result, ai_confidence, ai_recommend_type,
            status, priority, audit_opinion, expected_complete_time,
            deleted, create_time, update_time
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s,
            %s, 'REPAIR', 'QUALITY', %s, %s,
            %s, %s, 0.80, 'HUMAN_REVIEW',
            'PENDING', 1, %s, DATE_ADD(NOW(), INTERVAL 24 HOUR),
            0, NOW(), NOW()
        )
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(existing_sql, (order_db_id,))
                row = cur.fetchone()
                if row:
                    cur.execute(
                        "UPDATE order_info SET status = 'AFTERSALE', update_time = NOW() WHERE id = %s AND deleted = 0",
                        (order_db_id,),
                    )
                    conn.commit()
                    return int(row[0])

                cur.execute(order_sql, (order_db_id,))
                order_row = cur.fetchone()
                merchant_id = int(order_row[0]) if order_row and order_row[0] is not None else None
                merchant_code = str(order_row[1] or "MERCHANT_DEMO") if order_row else "MERCHANT_DEMO"
                ticket_no = f"AS{uuid4().hex[:10].upper()}"
                reason_detail = (description or "AI建议转人工核实").strip()[:500]
                classify_result = self._json_dumps(ai_summary or {})
                audit_opinion = "AI建议转人工：请客服核实图片材料与用户描述是否一致。"
                ticket_id = self._new_id()
                cur.execute(
                    insert_sql,
                    (
                        ticket_id,
                        ticket_no,
                        order_db_id,
                        order_no,
                        user_id,
                        merchant_id,
                        merchant_code,
                        product_name[:200],
                        reason_detail,
                        description,
                        refund_amount,
                        classify_result[:200],
                        audit_opinion,
                    ),
                )
                cur.execute(
                    "UPDATE order_info SET status = 'AFTERSALE', update_time = NOW() WHERE id = %s AND deleted = 0",
                    (order_db_id,),
                )
                conn.commit()
                return ticket_id

    def find_or_create_agent_ticket(
        self,
        *,
        order_db_id: int,
        order_no: str,
        user_id: int,
        product_name: str,
        refund_amount: float,
        description: str,
        ticket: Ticket,
        confidence: float,
        audit_note: str | None = None,
    ) -> int:
        existing_sql = """
        SELECT id, status
        FROM after_sales_ticket
        WHERE order_id = %s
          AND deleted = 0
          AND status IN ('PENDING', 'PENDING_REVIEW', 'PROCESSING', 'COMPLETED')
        ORDER BY update_time DESC, create_time DESC
        LIMIT 1
        """
        ticket_no_sql = """
        SELECT id
        FROM after_sales_ticket
        WHERE ticket_no = %s AND deleted = 0
        LIMIT 1
        """
        order_sql = """
        SELECT merchant_id, merchant_code
        FROM order_info
        WHERE id = %s AND deleted = 0
        LIMIT 1
        """
        insert_sql = """
        INSERT INTO after_sales_ticket (
            id, ticket_no, order_id, order_no, user_id, merchant_id, merchant_code,
            product_name, after_sale_type, reason, reason_detail, description,
            refund_amount, ai_classify_result, ai_confidence, ai_recommend_type,
            status, priority, audit_opinion, audit_time, expected_complete_time,
            deleted, create_time, update_time
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s, DATE_ADD(NOW(), INTERVAL %s HOUR),
            0, NOW(), NOW()
        )
        """
        db_status = self._map_agent_ticket_status(ticket.status.value)
        after_sale_type = self._map_agent_after_sale_type(ticket.after_sales_type.value)
        reason = self._map_agent_reason(ticket.summary)
        recommend_type = "AI_AUTO_APPROVE" if db_status == "PROCESSING" else "AI_REVIEW"
        audit_opinion = audit_note or (
            "AI识别图片与用户描述一致，自动审核通过，进入处理中。"
            if db_status == "PROCESSING"
            else "AI已创建售后申请，等待客服审核。"
        )
        classify_result = self._json_dumps(
            {
                "intent": ticket.intent.value,
                "risk": ticket.risk_level.value,
                "agent_status": ticket.status.value,
                "summary": ticket.summary,
            }
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(ticket_no_sql, (ticket.ticket_id,))
                row = cur.fetchone()
                if row:
                    return int(row[0])

                cur.execute(existing_sql, (order_db_id,))
                row = cur.fetchone()
                if row:
                    existing_ticket_id = int(row[0])
                    existing_status = str(row[1] or "")
                    if db_status == "PROCESSING" and existing_status in {"PENDING", "PENDING_REVIEW"}:
                        cur.execute(
                            """
                            UPDATE after_sales_ticket
                            SET status = 'PROCESSING',
                                ai_recommend_type = 'AI_AUTO_APPROVE',
                                ai_confidence = GREATEST(COALESCE(ai_confidence, 0), %s),
                                audit_opinion = %s,
                                audit_time = COALESCE(audit_time, NOW()),
                                update_time = NOW()
                            WHERE id = %s AND deleted = 0
                            """,
                            (
                                Decimal(str(max(0.0, min(1.0, confidence)))),
                                audit_opinion[:500],
                                existing_ticket_id,
                            ),
                        )
                    cur.execute(
                        "UPDATE order_info SET status = 'AFTERSALE', update_time = NOW() WHERE id = %s AND deleted = 0",
                        (order_db_id,),
                    )
                    conn.commit()
                    return existing_ticket_id

                cur.execute(order_sql, (order_db_id,))
                order_row = cur.fetchone()
                merchant_id = int(order_row[0]) if order_row and order_row[0] is not None else None
                merchant_code = str(order_row[1] or "MERCHANT_DEMO") if order_row else "MERCHANT_DEMO"
                ticket_id = self._new_id()
                cur.execute(
                    insert_sql,
                    (
                        ticket_id,
                        ticket.ticket_id,
                        order_db_id,
                        order_no,
                        user_id,
                        merchant_id,
                        merchant_code,
                        product_name[:200],
                        after_sale_type,
                        reason,
                        (description or ticket.summary)[:500],
                        description or ticket.summary,
                        refund_amount,
                        classify_result[:200],
                        Decimal(str(max(0.0, min(1.0, confidence)))),
                        recommend_type,
                        db_status,
                        1 if db_status == "PROCESSING" else 0,
                        audit_opinion[:500],
                        None,
                        max(1, int(ticket.expected_hours or 24)),
                    ),
                )
                if db_status == "PROCESSING":
                    cur.execute(
                        "UPDATE after_sales_ticket SET audit_time = NOW() WHERE id = %s",
                        (ticket_id,),
                    )
                cur.execute(
                    "UPDATE order_info SET status = 'AFTERSALE', update_time = NOW() WHERE id = %s AND deleted = 0",
                    (order_db_id,),
                )
                conn.commit()
                return ticket_id

    def resolve_order_owner_user_id(self, order_no: str) -> int | None:
        sql = """
        SELECT user_id
        FROM order_info
        WHERE order_no = %s AND deleted = 0
        LIMIT 1
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (order_no,))
                row = cur.fetchone()
        return int(row[0]) if row else None

    def find_or_create_session(
        self,
        *,
        user_id: int,
        order_db_id: int | None,
        ticket_id: int | None,
        source_channel: str = "H5",
    ) -> dict[str, Any]:
        query_sql = """
        SELECT id, session_no, status, merchant_code, ticket_id
        FROM chat_session
        WHERE user_id = %s
          AND (
            (ticket_id = %s)
            OR (order_id = %s)
            OR (%s IS NULL AND %s IS NULL AND order_id IS NULL AND ticket_id IS NULL)
          )
          AND deleted = 0
        ORDER BY update_time DESC, create_time DESC
        LIMIT 1
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                merchant_id, merchant_code = self._resolve_session_merchant(cur, order_db_id, ticket_id)
                cur.execute(query_sql, (user_id, ticket_id, order_db_id, order_db_id, ticket_id))
                row = cur.fetchone()
                if row:
                    next_status = "ACTIVE" if row[2] == "CLOSED" else row[2]
                    if not row[3] or (ticket_id is not None and row[4] is None):
                        cur.execute(
                            """
                            UPDATE chat_session
                            SET merchant_id = %s, merchant_code = %s, ticket_id = COALESCE(ticket_id, %s),
                                status = %s, resolved = 0, update_time = NOW()
                            WHERE id = %s
                            """,
                            (merchant_id, merchant_code, ticket_id, next_status, row[0]),
                        )
                        conn.commit()
                    elif row[2] == "CLOSED":
                        cur.execute(
                            """
                            UPDATE chat_session
                            SET status = 'ACTIVE', resolved = 0, update_time = NOW()
                            WHERE id = %s
                            """,
                            (row[0],),
                        )
                        conn.commit()
                    return {"id": int(row[0]), "session_no": row[1], "session_status": next_status}

                session_no = f"S{datetime.now():%Y%m%d%H%M%S}{uuid4().hex[:4].upper()}"
                insert_sql = """
                INSERT INTO chat_session (
                    id, session_no, user_id, merchant_id, merchant_code, order_id, ticket_id, mode, status,
                    user_query, resolved, create_time, update_time, deleted
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'AI', 'ACTIVE', %s, 0, NOW(), NOW(), 0)
                """
                session_id = self._new_id()
                cur.execute(
                    insert_sql,
                    (
                        session_id,
                        session_no,
                        user_id,
                        merchant_id,
                        merchant_code,
                        order_db_id,
                        ticket_id,
                        f"{source_channel} 会话",
                    ),
                )
                conn.commit()
                return {
                    "id": session_id,
                    "session_no": session_no,
                    "session_status": "ACTIVE",
                }

    @staticmethod
    def _resolve_session_merchant(cur, order_db_id: int | None, ticket_id: int | None) -> tuple[int | None, str]:
        """Resolve merchant fields because the merchant console filters sessions by merchant_code."""
        if order_db_id is not None:
            cur.execute(
                """
                SELECT merchant_id, merchant_code
                FROM order_info
                WHERE id = %s AND deleted = 0
                LIMIT 1
                """,
                (order_db_id,),
            )
            row = cur.fetchone()
            if row:
                return (int(row[0]) if row[0] is not None else None, str(row[1] or "MERCHANT_DEMO"))

        if ticket_id is not None:
            cur.execute(
                """
                SELECT merchant_id, merchant_code
                FROM after_sales_ticket
                WHERE id = %s AND deleted = 0
                LIMIT 1
                """,
                (ticket_id,),
            )
            row = cur.fetchone()
            if row:
                return (int(row[0]) if row[0] is not None else None, str(row[1] or "MERCHANT_DEMO"))

        return None, "MERCHANT_DEMO"

    def mark_session_waiting_human(
        self,
        *,
        session_id: int,
        ticket_id: int | None,
        summary: str,
        emotion_label: str = "NEUTRAL",
    ) -> None:
        sql = """
        UPDATE chat_session
        SET mode = 'HUMAN',
            status = 'WAITING',
            ticket_id = COALESCE(%s, ticket_id),
            emotion_label = %s,
            user_query = %s,
            resolved = 0,
            update_time = NOW()
        WHERE id = %s
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (ticket_id, emotion_label, summary[:500], session_id))
                conn.commit()

    def insert_chat_message(
        self,
        *,
        session_id: int,
        sender_id: int,
        sender_role: str,
        content: str,
        ai_intent: str | None,
        emotion_label: str = "NEUTRAL",
        message_type: str = "TEXT",
    ) -> int:
        del sender_id, ai_intent
        sql = """
        INSERT INTO chat_message (
            id, session_id, role, content, message_type, emotion_label, create_time
        ) VALUES (%s, %s, %s, %s, %s, %s, NOW())
        """
        role = self._map_chat_role(sender_role)
        message_id = self._new_id()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (message_id, session_id, role, content, message_type, emotion_label))
                conn.commit()
                return message_id

    def get_chat_session_by_id(self, session_id: int) -> dict[str, Any] | None:
        """Return session {id, session_no, mode, status, user_id} or None."""
        sql = """
        SELECT id, session_no, mode, status, user_id
        FROM chat_session
        WHERE id = %s AND deleted = 0
        LIMIT 1
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (session_id,))
                row = cur.fetchone()
        if not row:
            return None
        return {
            "id": int(row[0]),
            "session_no": row[1],
            "mode": str(row[2] or "AI"),
            "status": str(row[3] or "ACTIVE"),
            "user_id": int(row[4]) if row[4] else None,
        }

    def get_recent_messages(self, session_id: int, limit: int = 6) -> tuple[ConversationMessage, ...]:
        sql = """
        SELECT role, content, create_time
        FROM chat_message
        WHERE session_id = %s
        ORDER BY create_time DESC, id DESC
        LIMIT %s
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (session_id, limit))
                rows = cur.fetchall()
        messages = []
        for role, content, create_time in reversed(rows):
            text = str(content or "").strip()
            if not text:
                continue
            messages.append(
                ConversationMessage(
                    role=self._normalize_chat_role(str(role or "")),
                    content=text,
                    create_time=create_time,
                )
            )
        return tuple(messages)

    def update_session_snapshot(
        self,
        *,
        session_id: int,
        last_message_content: str,
        ai_summary: str | None = None,
        increase_service_unread: bool = False,
        increase_user_unread: bool = False,
    ) -> None:
        del increase_service_unread, increase_user_unread
        summary = ai_summary or last_message_content
        sql = """
        UPDATE chat_session
        SET user_query = %s,
            update_time = NOW()
        WHERE id = %s
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (summary[:500], session_id))
                conn.commit()

    def insert_ticket_log(
        self,
        *,
        ticket_id: int,
        operator_id: int,
        operator_role: str,
        old_status: str | None,
        new_status: str | None,
        action_type: str,
        action_desc: str,
    ) -> int:
        sql = """
        INSERT INTO ticket_log (
            id, ticket_id, operator_id, operator_type, from_status, to_status,
            action, content, create_time
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
        """
        log_id = self._new_id()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    (
                        log_id,
                        ticket_id,
                        operator_id,
                        self._map_operator_type(operator_role),
                        old_status,
                        new_status or "UNKNOWN",
                        action_type,
                        action_desc[:500],
                    ),
                )
                conn.commit()
                return log_id

    def insert_message_notice(
        self,
        *,
        receiver_id: int,
        receiver_role: str,
        title: str,
        content: str,
        notice_type: str = "SYSTEM",
        business_type: str | None = None,
        business_id: int | None = None,
        send_channel: str = "SITE",
    ) -> int:
        del receiver_role, send_channel
        sql = """
        INSERT INTO message_notice (
            id, user_id, title, content, notice_type, ref_id, ref_type, is_read, create_time
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, 0, NOW())
        """
        notice_id = self._new_id()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    (
                        notice_id,
                        receiver_id,
                        title,
                        content,
                        self._map_notice_type(notice_type),
                        business_id,
                        business_type,
                    ),
                )
                conn.commit()
                return notice_id

    def _build_orders(self, rows: tuple[tuple[Any, ...], ...] | list[tuple[Any, ...]]) -> list[Order]:
        if not rows:
            return []

        order_ids = [int(row[0]) for row in rows]
        items_map = self._load_order_items(order_ids)
        ticket_map = self._load_latest_tickets(order_ids)

        orders: list[Order] = []
        for row in rows:
            (
                db_id,
                order_no,
                user_id,
                total_amount,
                pay_amount,
                order_status,
                tracking_company,
                tracking_no,
                pay_time,
                ship_time,
                receive_time,
                create_time,
            ) = row

            ticket_snapshot = ticket_map.get(int(db_id))
            uploaded_evidence: tuple[str, ...] = ()
            after_sales_type = None
            refund_status = "未开始"
            merchant_rejected_before = False
            if ticket_snapshot:
                uploaded_evidence = self.get_ticket_attachments(int(ticket_snapshot["id"]))
                after_sales_type = self._map_after_sales_type(ticket_snapshot["after_sale_type"])
                refund_status = self._map_refund_status(str(ticket_snapshot["status"] or ""))
                merchant_rejected_before = str(ticket_snapshot["status"] or "").upper() == "REJECTED"

            items = items_map.get(int(db_id), ())
            if not items:
                items = (
                    OrderItem(
                        sku_id="unknown",
                        product_name="未知商品",
                        category="未分类",
                        quantity=1,
                        unit_price=float(self._to_float(pay_amount)),
                    ),
                )

            orders.append(
                Order(
                    order_id=str(order_no),
                    user_id=str(user_id),
                    status=self._map_order_status(str(order_status)),
                    amount=float(self._to_float(pay_amount or total_amount)),
                    created_at=self._ensure_datetime(create_time) or datetime.now(),
                    shipped_at=self._ensure_datetime(ship_time),
                    delivered_at=self._ensure_datetime(receive_time),
                    items=items,
                    has_open_after_sales=ticket_snapshot is not None,
                    after_sales_status=self._map_after_sales_status(ticket_snapshot),
                    after_sales_type=after_sales_type,
                    refund_status=refund_status,
                    logistics_status=self._map_logistics_text(tracking_company, tracking_no, order_status),
                    uploaded_evidence=uploaded_evidence,
                    user_after_sales_count=self.count_user_after_sales(int(user_id)),
                    merchant_rejected_before=merchant_rejected_before,
                )
            )
        return orders

    def _load_order_items(self, order_ids: list[int]) -> dict[int, tuple[OrderItem, ...]]:
        placeholders = ", ".join(["%s"] * len(order_ids))
        sql = f"""
        SELECT
            oi.order_id,
            oi.product_id,
            p.product_name,
            p.category,
            oi.quantity,
            oi.price
        FROM order_item oi
        LEFT JOIN product_info p ON p.id = oi.product_id
        WHERE oi.order_id IN ({placeholders})
        ORDER BY oi.order_id ASC, oi.id ASC
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(order_ids))
                rows = cur.fetchall()

        items_map: dict[int, list[OrderItem]] = {order_id: [] for order_id in order_ids}
        for order_id, product_id, product_name, category, quantity, price in rows:
            items_map[int(order_id)].append(
                OrderItem(
                    sku_id=str(product_id),
                    product_name=str(product_name or "未知商品"),
                    category=str(category or "未分类"),
                    quantity=int(quantity or 1),
                    unit_price=float(self._to_float(price)),
                )
            )
        return {key: tuple(value) for key, value in items_map.items()}

    def _load_latest_tickets(self, order_ids: list[int]) -> dict[int, dict[str, Any]]:
        placeholders = ", ".join(["%s"] * len(order_ids))
        sql = f"""
        SELECT
            t.id,
            t.order_id,
            t.ticket_no,
            t.after_sale_type,
            t.reason,
            t.reason_detail,
            t.description,
            t.refund_amount,
            t.ai_recommend_type,
            t.status,
            t.priority,
            t.audit_opinion,
            t.expected_complete_time,
            t.complete_time,
            t.create_time
        FROM after_sales_ticket t
        WHERE t.order_id IN ({placeholders}) AND t.deleted = 0
        ORDER BY t.order_id ASC, t.update_time DESC, t.create_time DESC
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(order_ids))
                rows = cur.fetchall()

        latest: dict[int, dict[str, Any]] = {}
        columns = (
            "id",
            "order_id",
            "ticket_no",
            "after_sale_type",
            "reason",
            "reason_detail",
            "description",
            "refund_amount",
            "ai_recommend_type",
            "status",
            "priority",
            "audit_opinion",
            "expected_complete_time",
            "complete_time",
            "create_time",
        )
        for row in rows:
            order_id = int(row[1])
            if order_id not in latest:
                latest[order_id] = dict(zip(columns, row))
        return latest

    def _connect(self):
        return pymysql.connect(
            host=self.config.host,
            port=self.config.port,
            user=self.config.user,
            password=self.config.password,
            database=self.config.database,
            charset=self.config.charset,
        )

    @staticmethod
    def _map_order_status(value: str) -> OrderStatus:
        mapping = {
            "PENDING": OrderStatus.PAID,
            "PAID": OrderStatus.PAID,
            "SHIPPED": OrderStatus.SHIPPED,
            "RECEIVED": OrderStatus.DELIVERED,
            "CLOSED": OrderStatus.COMPLETED,
        }
        return mapping.get(value.upper(), OrderStatus.PAID)

    @staticmethod
    def _map_after_sales_status(ticket_snapshot: dict[str, Any] | None) -> AfterSalesStatus:
        if not ticket_snapshot:
            return AfterSalesStatus.NOT_APPLIED

        ticket_status = str(ticket_snapshot.get("status") or "").upper()
        mapping = {
            "PENDING": AfterSalesStatus.SUBMITTED,
            "PROCESSING": AfterSalesStatus.MERCHANT_REVIEW,
            "APPROVED": AfterSalesStatus.APPROVED,
            "REJECTED": AfterSalesStatus.REJECTED,
            "COMPLETED": AfterSalesStatus.COMPLETED,
            "CLOSED": AfterSalesStatus.HUMAN_PROCESSING,
        }
        return mapping.get(ticket_status, AfterSalesStatus.NOT_APPLIED)

    @staticmethod
    def _map_after_sales_type(value: str | None) -> AfterSalesType | None:
        if not value:
            return None
        mapping = {
            "REFUND_ONLY": AfterSalesType.REFUND_ONLY,
            "REFUND_RETURN": AfterSalesType.RETURN_AND_REFUND,
            "EXCHANGE": AfterSalesType.EXCHANGE,
            "REPAIR": AfterSalesType.REPAIR,
        }
        return mapping.get(value.upper())

    @staticmethod
    def _map_agent_ticket_status(value: str) -> str:
        mapping = {
            "waiting_user": "PENDING",
            "pending_review": "PENDING",
            "auto_approved": "PROCESSING",
            "human_handoff": "PENDING",
            "closed": "CLOSED",
        }
        return mapping.get(str(value or "").lower(), "PENDING")

    @staticmethod
    def _map_agent_after_sale_type(value: str) -> str:
        mapping = {
            "refund_only": "REFUND_ONLY",
            "return_and_refund": "REFUND_RETURN",
            "exchange": "EXCHANGE",
            "repair": "REPAIR",
        }
        return mapping.get(str(value or "").lower(), "REFUND_RETURN")

    @staticmethod
    def _map_agent_reason(summary: str) -> str:
        text = str(summary or "")
        if any(marker in text for marker in ("破", "裂", "损", "碎", "坏", "damage")):
            return "DAMAGE"
        if any(marker in text for marker in ("少", "漏", "错", "wrong", "missing")):
            return "WRONG_ITEM"
        return "QUALITY"

    @staticmethod
    def _normalize_attachment_type(value: str) -> str:
        mapping = {
            "IMAGE": "商品照片",
            "VIDEO": "故障照片或视频",
            "FILE": "问题说明文件",
        }
        return mapping.get(str(value).upper(), str(value))

    @staticmethod
    def _map_refund_status(ticket_status: str) -> str:
        mapping = {
            "PENDING": "待审核",
            "PROCESSING": "处理中",
            "APPROVED": "审核通过",
            "REJECTED": "审核拒绝",
            "COMPLETED": "已完成",
            "CLOSED": "已关闭",
        }
        return mapping.get(ticket_status.upper(), "未开始")

    @staticmethod
    def _map_logistics_text(company: Any, tracking_no: Any, order_status: Any) -> str:
        status = str(order_status or "").upper()
        status_text = {
            "PENDING": "待发货",
            "PAID": "待发货",
            "SHIPPED": "运输中",
            "RECEIVED": "已签收",
            "CLOSED": "已关闭",
        }.get(status, "待更新")
        if tracking_no:
            return f"{status_text}（{str(company or '快递')} {tracking_no}）"
        return status_text

    @staticmethod
    def _map_chat_role(sender_role: str) -> str:
        mapping = {
            "USER": "USER",
            "AI": "ASSISTANT",
            "AGENT": "ASSISTANT",
            "SYSTEM": "SYSTEM",
            "TOOL": "TOOL",
        }
        return mapping.get(sender_role.upper(), "ASSISTANT")

    @staticmethod
    def _normalize_chat_role(sender_role: str) -> str:
        mapping = {
            "USER": "user",
            "CUSTOMER": "user",
            "ASSISTANT": "assistant",
            "AI": "assistant",
            "AGENT": "assistant",
            "SYSTEM": "system",
            "TOOL": "system",
        }
        return mapping.get(sender_role.upper(), "assistant")

    @staticmethod
    def _map_operator_type(operator_role: str) -> str:
        mapping = {
            "AI": "AI",
            "USER": "USER",
            "AGENT": "AGENT",
            "SYSTEM": "SYSTEM",
        }
        return mapping.get(operator_role.upper(), "AI")

    @staticmethod
    def _map_notice_type(notice_type: str) -> str:
        mapping = {
            "SYSTEM": "SYSTEM",
            "TICKET": "AFTER_SALE",
            "ORDER": "ORDER",
            "CHAT": "CHAT",
        }
        return mapping.get(notice_type.upper(), "SYSTEM")

    @staticmethod
    def _to_float(value: Decimal | float | int | None) -> float:
        if value is None:
            return 0.0
        return float(value)

    @staticmethod
    def _json_dumps(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, default=str)

    @staticmethod
    def _ensure_datetime(value: Any) -> datetime | None:
        return value if isinstance(value, datetime) else None


def _read_env_file(path: str | Path) -> dict[str, str]:
    env: dict[str, str] = {}
    file_path = _resolve_env_file(path)
    for line in file_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        env[key.strip()] = value.strip()
    return env


def _resolve_env_file(path: str | Path | None) -> Path:
    if path is not None:
        file_path = Path(path)
        if file_path.exists():
            return file_path
        raise FileNotFoundError(f"Database config file not found: {file_path}")

    candidates = (
        Path.cwd() / "db.local.env",
        Path.cwd() / "python_agent" / "db.local.env",
        Path(__file__).resolve().parents[2] / "db.local.env",
        Path(__file__).resolve().parents[3] / "db.local.env",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "Database config file not found. Checked: "
        + ", ".join(str(candidate) for candidate in candidates)
    )
