from __future__ import annotations

import json
import logging
import os
from typing import Any

from after_sales_agent.application.emotion.emotion_service import EmotionAgent
from after_sales_agent.domain.models import (
    AfterSalesRequest,
    Attachment,
    ConversationMessage,
)


def build_attachments(payload_attachments: list[Any] | tuple[Any, ...] | None) -> tuple[Attachment, ...]:
    attachments: list[Attachment] = []
    for item in payload_attachments or []:
        if isinstance(item, str):
            kind = item.strip()
            if kind:
                attachments.append(Attachment(kind=kind, name=f"{kind}.jpg"))
            continue
        if isinstance(item, dict):
            kind = str(item.get("kind") or "商品照片").strip()
            name = str(item.get("name") or f"{kind}.jpg").strip()
            file_url = item.get("file_url") or item.get("fileUrl") or item.get("url")
            attachments.append(Attachment(kind=kind, name=name, source=item.get("source"), file_url=file_url))
    return tuple(attachments)


def build_recent_history_messages(payload_history: list[Any] | tuple[Any, ...] | None) -> tuple[ConversationMessage, ...]:
    messages: list[ConversationMessage] = []
    for item in payload_history or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        if role == "service":
            role = "assistant"
        if role not in {"user", "assistant"}:
            continue
        content = str(item.get("content") or "").strip()
        if content:
            messages.append(ConversationMessage(role=role, content=content))
    return tuple(messages[-8:])


def analyze_chat_emotion(data: dict[str, Any]) -> dict[str, Any] | None:
    logger = logging.getLogger("api_server.emotion")
    if os.getenv("CHAT_EMOTION_ANALYSIS_ENABLED", "true").strip().lower() in {
        "0",
        "false",
        "no",
        "off",
    }:
        logger.info("chat emotion analysis disabled by local configuration")
        return None
    try:
        message = str(data.get("message") or "").strip()
        attachments = build_attachments(data.get("attachments"))
        if attachments and message in {"", "[图片]", "[image]"}:
            return None
        if not message and not attachments:
            return None
        logger.info(
            "emotion request message=%s attachments=%d session_id=%s order_id=%s",
            message[:200],
            len(attachments),
            data.get("session_id"),
            data.get("order_id") or "",
        )

        selected = data.get("selected_order") if isinstance(data.get("selected_order"), dict) else {}
        user_id = (
            data.get("user_id")
            or selected.get("user_id")
            or "0"
        )
        request = AfterSalesRequest(
            user_id=str(user_id),
            message=message or ("用户发送了图片" if attachments else ""),
            order_id=str(data.get("order_id") or selected.get("order_id") or "") or None,
            description=str(data.get("description") or "").strip() or None,
            item_opened=data.get("item_opened"),
            human_request_count=int(data.get("human_request_count") or 0),
            attachments=attachments,
        )
        history = build_recent_history_messages(data.get("recent_history"))
        emotion = EmotionAgent().analyze(
            request,
            recent_history=history,
            recent_user_messages=tuple(message.content for message in history if message.role == "user"),
        )
        result = {
            "label": emotion.label.value,
            "score": emotion.score,
            "confidence": emotion.confidence,
            "triggers": list(emotion.triggers),
            "need_human_priority": emotion.need_human_priority,
            "reply_tone": emotion.reply_tone,
            "comfort_prefix": emotion.comfort_prefix,
            "comfort_examples": list(emotion.comfort_examples),
        }
        logger.info("emotion final context=%s", json.dumps(result, ensure_ascii=False, default=str))
        return result
    except Exception as exc:
        logger.exception("emotion analyze failed error=%s", exc)
        return None
