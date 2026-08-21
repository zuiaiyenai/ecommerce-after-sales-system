from __future__ import annotations

from collections import deque
from datetime import datetime
import json
import logging
from typing import Any

from .request_tracing import TraceRecorder
from .agent_metrics import AGENT_RUNTIME_METRICS

TRACE_HISTORY: deque[dict[str, object]] = deque(maxlen=120)


def record_trace_event(
    trace: TraceRecorder,
    *,
    path: str,
    order_id: str | None = None,
    session_id: int | None = None,
    reply_preview: str | None = None,
) -> None:
    event = {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "path": path,
        "order_id": order_id or "",
        "session_id": session_id,
        "reply_preview": (reply_preview or "")[:120],
        "trace": trace.to_dict(),
    }
    TRACE_HISTORY.appendleft(event)
    AGENT_RUNTIME_METRICS.record_trace(path, event["trace"])
    logging.getLogger("api_server.trace").info(
        "agent_trace=%s", json.dumps(event, ensure_ascii=False, separators=(",", ":"), default=str)
    )
