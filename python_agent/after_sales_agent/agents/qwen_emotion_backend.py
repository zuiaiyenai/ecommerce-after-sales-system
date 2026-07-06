from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from ..llm_client import LLMError, OpenAICompatibleClient, OpenAICompatibleConfig
from ..models import AfterSalesRequest, ConversationMessage, Order


@dataclass(frozen=True)
class QwenEmotionResult:
    label: str
    emotion_score: float
    confidence: float
    need_human_priority: bool
    reason: str
    raw: dict[str, Any]


class QwenEmotionBackend:
    """Classify after-sales user emotion with negative-intensity scoring plus label/confidence."""

    HIGH_PRIORITY_KEYWORDS = (
        "马上",
        "立刻",
        "今天必须",
        "必须处理",
        "急用",
        "投诉",
        "曝光",
        "12315",
    )

    STRONG_NEGATIVE_KEYWORDS = (
        "投诉",
        "差评",
        "曝光",
        "骗子",
        "垃圾",
        "坑人",
        "退钱",
        "生气",
        "愤怒",
        "气死",
        "再不",
        "必须",
        "立刻",
        "马上",
        "12315",
    )

    NORMAL_AFTERSALES_KEYWORDS = (
        "申请售后",
        "想申请售后",
        "想退款",
        "想退货",
        "想换货",
        "想维修",
        "没有声音",
        "没声音",
        "无法开机",
        "坏了",
        "有问题",
        "不能用",
        "质量问题",
    )

    POSITIVE_ACK_KEYWORDS = (
        "谢谢",
        "感谢",
        "辛苦了",
        "收到",
        "明白了",
        "好的",
        "好",
    )

    LIGHT_URGENCY_KEYWORDS = (
        "尽快",
        "快点",
        "什么时候",
        "多久",
        "着急",
        "急",
        "催",
    )

    DEFAULT_SCORE_BY_LABEL = {
        "satisfied": 0.05,
        "calm": 0.22,
        "anxious": 0.48,
        "dissatisfied": 0.72,
        "angry": 0.92,
    }

    def __init__(self, config: OpenAICompatibleConfig | None = None) -> None:
        self.client = OpenAICompatibleClient(config or OpenAICompatibleConfig.from_env())

    def analyze(
        self,
        request: AfterSalesRequest,
        order: Order | None = None,
        *,
        recent_history: tuple[ConversationMessage, ...] = (),
        recent_user_messages: tuple[str, ...] = (),
    ) -> QwenEmotionResult:
        heuristic_result = self._fast_path_result(
            request=request,
            recent_user_messages=recent_user_messages,
        )
        if heuristic_result is not None:
            return heuristic_result

        raw = self.client.chat_json(
            system_prompt=self._system_prompt(),
            user_prompt=self._user_prompt(
                request=request,
                order=order,
                recent_history=recent_history,
                recent_user_messages=recent_user_messages,
            ),
            temperature=0.0,
            max_tokens=260,
        )
        return self._parse_result(raw, request=request, recent_user_messages=recent_user_messages)

    @classmethod
    def _fast_path_result(
        cls,
        *,
        request: AfterSalesRequest,
        recent_user_messages: tuple[str, ...],
    ) -> QwenEmotionResult | None:
        combined_text = " ".join(
            part
            for part in (
                request.message,
                request.reason or "",
                request.description or "",
                " ".join(recent_user_messages),
            )
            if part
        ).strip()
        if not combined_text:
            return None

        if any(keyword in combined_text for keyword in cls.STRONG_NEGATIVE_KEYWORDS):
            return None
        if any(keyword in combined_text for keyword in cls.HIGH_PRIORITY_KEYWORDS):
            return None

        if cls._is_positive_ack_only(combined_text):
            return QwenEmotionResult(
                label="calm",
                emotion_score=0.22,
                confidence=0.92,
                need_human_priority=False,
                reason="用户是在正常确认或礼貌回应，没有明显负面情绪。",
                raw={"mode": "heuristic_fast_path", "strategy": "positive_ack"},
            )

        if any(keyword in combined_text for keyword in cls.NORMAL_AFTERSALES_KEYWORDS):
            has_urgency = any(keyword in combined_text for keyword in cls.LIGHT_URGENCY_KEYWORDS)
            return QwenEmotionResult(
                label="anxious" if has_urgency or cls._contains_specific_issue(combined_text) else "calm",
                emotion_score=0.48 if has_urgency or cls._contains_specific_issue(combined_text) else 0.22,
                confidence=0.9 if has_urgency else 0.95,
                need_human_priority=False,
                reason=(
                    "用户是在正常描述售后问题，未出现强烈负面或投诉信号。"
                    if has_urgency or cls._contains_specific_issue(combined_text)
                    else "用户是在正常咨询售后流程，情绪整体较平稳。"
                ),
                raw={"mode": "heuristic_fast_path", "strategy": "normal_after_sales"},
            )

        return None

    @classmethod
    def _contains_specific_issue(cls, text: str) -> bool:
        issue_markers = (
            "没有声音",
            "没声音",
            "无法开机",
            "充电异常",
            "连不上",
            "连接失败",
            "坏了",
            "有问题",
            "不能用",
        )
        return any(marker in text for marker in issue_markers)

    @classmethod
    def _is_positive_ack_only(cls, text: str) -> bool:
        return any(keyword in text for keyword in cls.POSITIVE_ACK_KEYWORDS) and not any(
            keyword in text for keyword in cls.NORMAL_AFTERSALES_KEYWORDS + cls.STRONG_NEGATIVE_KEYWORDS
        )

    @staticmethod
    def _system_prompt() -> str:
        schema = {
            "label": "satisfied|calm|anxious|dissatisfied|angry",
            "emotion_score": "0.0-1.0，越高表示越负面、越需要关注",
            "confidence": "0.0-1.0，表示你对本次判断的把握程度",
            "need_human_priority": "boolean",
            "reason": "一句简短中文说明依据",
        }
        return (
            "你是电商售后客服系统里的用户情绪分析器。"
            "请只根据用户当前消息和最近上下文判断用户情绪，不要生成客服回复。"
            "你必须同时输出：情绪标签、负面强度分、判断置信度。"
            "其中 emotion_score 表示负面强度，0 接近积极或平静，1 接近强烈负面或愤怒。"
            "标签定义："
            "satisfied=明确满意、认可、感谢、正向反馈；"
            "calm=平静咨询、中性补充、普通追问；"
            "anxious=着急、催促、担心进度、急着使用；"
            "dissatisfied=明显不满、失望、体验差，但未到强烈谩骂或投诉威胁；"
            "angry=愤怒、强烈指责、辱骂、威胁投诉、要求升级处理。"
            "重要约束：仅仅描述商品故障、说明想申请售后、退款、换货、维修，默认不算 angry，也通常不算 dissatisfied。"
            "这类正常售后表达优先判定为 calm 或 anxious。"
            "如果出现“马上”“立刻”“今天必须”“急用”“投诉”“曝光”“12315”等高优先级信号，"
            "need_human_priority 应优先考虑 true。"
            "只输出 JSON，不要输出 Markdown 或额外解释。"
            f"JSON 示例：{json.dumps(schema, ensure_ascii=False)}"
        )

    @staticmethod
    def _user_prompt(
        *,
        request: AfterSalesRequest,
        order: Order | None,
        recent_history: tuple[ConversationMessage, ...],
        recent_user_messages: tuple[str, ...],
    ) -> str:
        payload = {
            "current_message": request.message,
            "reason": request.reason,
            "description": request.description,
            "human_request_count": request.human_request_count,
            "order": {
                "status": order.status.value if order else "",
                "after_sales_status": order.after_sales_status.value if order else "",
                "refund_status": order.refund_status if order else "",
                "logistics_status": order.logistics_status if order else "",
                "merchant_rejected_before": order.merchant_rejected_before if order else False,
            },
            "recent_history": [
                {"role": message.role, "content": message.content}
                for message in recent_history[-8:]
                if message.content
            ],
            "recent_user_messages": [message for message in recent_user_messages[-5:] if message],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    @classmethod
    def _parse_result(
        cls,
        raw: dict[str, Any],
        *,
        request: AfterSalesRequest,
        recent_user_messages: tuple[str, ...],
    ) -> QwenEmotionResult:
        if "assistant_reply" in raw and len(raw) == 1:
            raise LLMError("emotion model did not return structured JSON")

        label = cls._normalize_label(raw.get("label"))
        if label not in cls.DEFAULT_SCORE_BY_LABEL:
            raise LLMError(f"invalid emotion label: {label}")

        emotion_score = cls._parse_float(raw.get("emotion_score"))
        if emotion_score is None:
            emotion_score = cls.DEFAULT_SCORE_BY_LABEL[label]

        confidence = cls._parse_float(raw.get("confidence"))
        if confidence is None:
            confidence = 0.8

        need_human_priority = raw.get("need_human_priority")
        if not isinstance(need_human_priority, bool):
            need_human_priority = label == "angry" or emotion_score >= 0.8

        combined_text = " ".join(
            part
            for part in (
                request.message,
                request.reason or "",
                request.description or "",
                " ".join(recent_user_messages),
            )
            if part
        )
        if any(keyword in combined_text for keyword in cls.HIGH_PRIORITY_KEYWORDS):
            need_human_priority = True

        label, emotion_score, need_human_priority = cls._apply_normal_after_sales_guardrail(
            label=label,
            emotion_score=emotion_score,
            confidence=confidence,
            need_human_priority=need_human_priority,
            combined_text=combined_text,
        )

        return QwenEmotionResult(
            label=label,
            emotion_score=max(0.0, min(1.0, emotion_score)),
            confidence=max(0.0, min(1.0, confidence)),
            need_human_priority=need_human_priority,
            reason=str(raw.get("reason") or "").strip(),
            raw=raw,
        )

    @staticmethod
    def _parse_float(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _normalize_label(cls, value: Any) -> str:
        text = str(value or "").strip().lower()
        if text in cls.DEFAULT_SCORE_BY_LABEL:
            return text

        candidates = [item.strip() for item in text.replace("/", "|").replace(",", "|").split("|") if item.strip()]
        known = [item for item in candidates if item in cls.DEFAULT_SCORE_BY_LABEL]
        if not known:
            return text
        return max(known, key=lambda item: cls.DEFAULT_SCORE_BY_LABEL[item])

    @classmethod
    def _apply_normal_after_sales_guardrail(
        cls,
        *,
        label: str,
        emotion_score: float,
        confidence: float,
        need_human_priority: bool,
        combined_text: str,
    ) -> tuple[str, float, bool]:
        text = (combined_text or "").lower()
        has_strong_negative = any(keyword in text for keyword in cls.STRONG_NEGATIVE_KEYWORDS)
        is_normal_after_sales = any(keyword in text for keyword in cls.NORMAL_AFTERSALES_KEYWORDS)

        if not is_normal_after_sales or has_strong_negative:
            return label, emotion_score, need_human_priority

        if label == "angry":
            label = "anxious"
        elif label == "dissatisfied":
            label = "anxious"

        emotion_score = min(emotion_score, cls.DEFAULT_SCORE_BY_LABEL[label])
        need_human_priority = False
        return label, emotion_score, need_human_priority
