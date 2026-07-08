from __future__ import annotations

from dataclasses import dataclass
import json
import re
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
    """Emotion classification driven only by Qwen structured output."""

    KNOWN_LABELS = {"satisfied", "calm", "anxious", "dissatisfied", "angry"}
    SCORE_RANGES = {
        "satisfied": (0.0, 0.15),
        "calm": (0.10, 0.35),
        "anxious": (0.30, 0.55),
        "dissatisfied": (0.50, 0.75),
        "angry": (0.75, 0.95),
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
        user_prompt = self._user_prompt(
            request=request,
            order=order,
            recent_history=recent_history,
            recent_user_messages=recent_user_messages,
        )

        raw = self.client.chat_json(
            system_prompt=self._system_prompt(),
            user_prompt=user_prompt,
            temperature=0.0,
            max_tokens=260,
        )

        try:
            result = self._parse_result(raw)
        except LLMError as exc:
            repaired_raw = self._self_check(
                user_prompt=user_prompt,
                previous_raw=raw,
                previous_error=str(exc),
            )
            return self._apply_message_priors(
                request.message,
                self._normalize_result(self._parse_result(repaired_raw)),
            )

        if self._needs_self_check(result):
            repaired_raw = self._self_check(
                user_prompt=user_prompt,
                previous_raw=raw,
                previous_error="emotion label/score/handoff consistency check failed",
            )
            repaired_result = self._parse_result(repaired_raw)
            result = repaired_result

        return self._apply_message_priors(
            request.message,
            self._normalize_result(result),
        )

    @staticmethod
    def _system_prompt() -> str:
        schema = {
            "label": "satisfied|calm|anxious|dissatisfied|angry",
            "emotion_score": "0.0-1.0 之间的单个小数，只表示当前话语的情绪强度，越高表示负面情绪越强",
            "confidence": "0.0-1.0 之间的单个小数，表示你对本次判断的把握程度",
            "need_human_priority": "boolean，表示是否建议优先人工跟进；它和 emotion_score 没有直接线性关系",
            "reason": "一句简短中文说明判断依据",
        }
        return (
            "你是电商售后系统里的用户情绪分析器。"
            "请只根据用户当前消息、最近上下文、订单状态和已有补充信息，判断用户情绪。"
            "不要生成客服回复，不要输出解释性段落。"
            "你必须严格输出 JSON。"
            "label 只能是 satisfied、calm、anxious、dissatisfied、angry 五选一。"
            "emotion_score 必须是 0 到 1 之间的单个小数，例如 0.18、0.42、0.87。"
            "confidence 必须是 0 到 1 之间的单个小数，例如 0.66、0.91。"
            "need_human_priority 必须是 true 或 false。"
            "严禁输出区间、范围、文字说明或多个候选值。"
            "例如 emotion_score 不能写成 0.5-1.0、0.5~1.0、较高、medium。"
            "例如 confidence 不能写成 0.6-0.8、较高、high。"
            "label 和 emotion_score 必须语义一致。"
            "need_human_priority 是单独的服务升级建议，不等于情绪强度，不能把它当作 emotion_score 的直接映射。"
            "“转人工”“人工客服”“联系客服”这类动作型诉求，本身不等于明显不满或愤怒。"
            "如果用户只是要求转人工、询问处理方式、要求尽快处理，而没有明确投诉、辱骂、威胁、激烈指责，情绪分应保持保守，不要轻易打到 dissatisfied 或 angry。"
            "最近历史只能作为辅助线索，不能因为前文有售后问题，就把当前一句中性或动作型表达直接判成高负面。"
            "如果在 calm / anxious / dissatisfied 之间拿不准，优先选择更保守、负面程度更低的那个标签。"
            "只允许类似下面这样的合法输出："
            '{"label":"anxious","emotion_score":0.44,"confidence":0.88,"need_human_priority":false,"reason":"用户表达着急，担心处理进度"}'
            "补充示例："
            "“好的谢谢”更接近 satisfied 或低分 calm；"
            "“这个问题怎么处理”更接近 calm；"
            "“转人工”更接近 anxious 或 calm，不应直接判 dissatisfied；"
            "“你们这也太慢了”可以是 anxious 或轻度 dissatisfied；"
            "“再不处理我就投诉12315”应明显高于普通 anxious。"
            "标签定义如下："
            "satisfied=明确满意、认可、感谢、积极反馈；"
            "calm=平静咨询、中性补充、普通追问；"
            "anxious=着急、催促、担心进度、急着使用；"
            "dissatisfied=明显不满、失望、体验差，但没有升级到激烈指责或威胁投诉；"
            "angry=愤怒、激烈指责、辱骂、威胁投诉、强烈要求升级处理。"
            "emotion_score 参考区间如下，并且必须与 label 保持一致："
            "satisfied=0.00-0.15；"
            "calm=0.10-0.35；"
            "anxious=0.30-0.55；"
            "dissatisfied=0.50-0.75；"
            "angry=0.75-0.95。"
            "need_human_priority 的判断规则："
            "它主要反映服务升级或人工介入优先级，而不是情绪本身；"
            "satisfied 和 calm 通常为 false；"
            "anxious 在多次催促、明确要求人工、升级风险较高时可以为 true；"
            "dissatisfied 和 angry 可以为 true，但不是必须由高情绪分推导得出。"
            f"输出字段说明：{json.dumps(schema, ensure_ascii=False)}"
        )

    @classmethod
    def _self_check_system_prompt(cls) -> str:
        return (
            "你是电商售后系统里的情绪结果质检器。"
            "你会收到同一条用户消息的原始上下文，以及上一轮情绪模型输出。"
            "你的任务不是解释，而是把上一轮结果修正成一份合法、稳定、语义一致的 JSON。"
            "只能输出一个 JSON 对象，字段固定为 label、emotion_score、confidence、need_human_priority、reason。"
            "label 只能是 satisfied、calm、anxious、dissatisfied、angry。"
            "emotion_score、confidence 必须是 0 到 1 之间的单个小数。"
            "need_human_priority 必须是 true 或 false。"
            "如果上一轮输出结构错了、标签和分数矛盾、或情绪强度明显偏激，请直接修正。"
            "修正规则：satisfied=0.00-0.15，calm=0.10-0.35，anxious=0.30-0.55，dissatisfied=0.50-0.75，angry=0.75-0.95。"
            "要保守评估情绪强度，不要把普通售后咨询、转人工诉求、处理中追问默认打成高负面。"
            "例如“好的谢谢你，明白了”不应给出高负面分；“转人工”通常不应直接给到 dissatisfied；“你们一直不处理，我要投诉12315”不应给出 calm 或 satisfied。"
            "need_human_priority 是独立的服务升级建议，不要求和 emotion_score 同高同低。"
            "如果分不清边界，优先把结果修正到更保守、更居中的分数，而不是贴着区间上边界。"
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

    def _self_check(self, *, user_prompt: str, previous_raw: dict[str, Any], previous_error: str) -> dict[str, Any]:
        repair_payload = {
            "original_context": json.loads(user_prompt),
            "previous_output": previous_raw,
            "previous_error": previous_error,
        }
        return self.client.chat_json(
            system_prompt=self._self_check_system_prompt(),
            user_prompt=json.dumps(repair_payload, ensure_ascii=False, indent=2),
            temperature=0.0,
            max_tokens=260,
        )

    @classmethod
    def _parse_result(cls, raw: dict[str, Any]) -> QwenEmotionResult:
        if "assistant_reply" in raw and len(raw) == 1:
            raise LLMError("emotion model did not return structured JSON")

        label = cls._normalize_label(raw.get("label"))
        if label not in cls.KNOWN_LABELS:
            raise LLMError(f"invalid emotion label: {label}")

        emotion_score = cls._parse_required_float(raw.get("emotion_score"), "emotion_score")
        confidence = cls._parse_required_float(raw.get("confidence"), "confidence")
        need_human_priority = cls._parse_required_bool(raw.get("need_human_priority"), "need_human_priority")

        return QwenEmotionResult(
            label=label,
            emotion_score=max(0.0, min(1.0, emotion_score)),
            confidence=max(0.0, min(1.0, confidence)),
            need_human_priority=need_human_priority,
            reason=str(raw.get("reason") or "").strip(),
            raw=raw,
        )

    @classmethod
    def _needs_self_check(cls, result: QwenEmotionResult) -> bool:
        score_min, score_max = cls.SCORE_RANGES[result.label]
        if result.emotion_score < score_min or result.emotion_score > score_max:
            return True
        if result.confidence < 0.0 or result.confidence > 1.0:
            return True
        return False

    @classmethod
    def _normalize_result(cls, result: QwenEmotionResult) -> QwenEmotionResult:
        score_min, score_max = cls.SCORE_RANGES[result.label]
        normalized_score = cls._soft_calibrate_score(result.label, result.emotion_score)
        normalized_confidence = min(max(result.confidence, 0.0), 1.0)
        if normalized_score != result.emotion_score:
            normalized_confidence = min(normalized_confidence, 0.78)
        return QwenEmotionResult(
            label=result.label,
            emotion_score=normalized_score,
            confidence=normalized_confidence,
            need_human_priority=result.need_human_priority,
            reason=result.reason,
            raw=result.raw,
        )

    @classmethod
    def _apply_message_priors(cls, message: str | None, result: QwenEmotionResult) -> QwenEmotionResult:
        text = str(message or "").strip()
        compact = re.sub(r"\s+", "", text)
        if not compact:
            return result

        if cls._is_positive_ack(compact):
            return cls._override_result(
                result,
                label="satisfied",
                score=0.12,
                confidence_floor=0.82,
                need_human_priority=False,
                reason="用户主要在表达确认或感谢，情绪偏平稳或正向",
            )

        if cls._is_human_handoff_request(compact) and not cls._has_strong_negative_signal(compact):
            return cls._override_result(
                result,
                label="anxious",
                score=0.42,
                confidence_floor=0.82,
                need_human_priority=result.need_human_priority,
                reason="用户主要在请求人工介入，属于升级诉求，不等于明显不满",
            )

        if cls._is_forceful_refund_demand(compact):
            return cls._override_result(
                result,
                label="dissatisfied",
                score=0.62,
                confidence_floor=0.82,
                need_human_priority=True,
                reason="用户在强硬催促退款，存在明显不满情绪",
            )

        if cls._is_neutral_refund_or_after_sales_request(compact) and not cls._has_strong_negative_signal(compact):
            score = 0.40 if cls._has_urgency_signal(compact) else 0.32
            label = "anxious" if cls._has_urgency_signal(compact) else "calm"
            return cls._override_result(
                result,
                label=label,
                score=score,
                confidence_floor=0.80,
                need_human_priority=False,
                reason="用户主要在描述售后诉求或处理动作，情绪应保持保守",
            )

        if cls._is_mild_dissatisfaction(compact) and not cls._has_complaint_threat(compact):
            return cls._override_result(
                result,
                label="dissatisfied",
                score=0.58,
                confidence_floor=0.80,
                need_human_priority=result.need_human_priority,
                reason="用户表达了明确不满，但尚未升级到投诉威胁",
            )

        if cls._has_complaint_threat(compact):
            return cls._override_result(
                result,
                label="angry",
                score=0.88,
                confidence_floor=0.80,
                need_human_priority=True,
                reason="用户已出现投诉或威胁升级信号，负面情绪较强",
            )

        return result

    @classmethod
    def _override_result(
        cls,
        result: QwenEmotionResult,
        *,
        label: str,
        score: float,
        confidence_floor: float,
        need_human_priority: bool,
        reason: str,
    ) -> QwenEmotionResult:
        normalized_score = cls._soft_calibrate_score(label, score)
        normalized_confidence = max(min(result.confidence, 1.0), confidence_floor)
        return QwenEmotionResult(
            label=label,
            emotion_score=normalized_score,
            confidence=normalized_confidence,
            need_human_priority=need_human_priority,
            reason=reason,
            raw=result.raw,
        )

    @classmethod
    def _soft_calibrate_score(cls, label: str, score: float) -> float:
        score_min, score_max = cls.SCORE_RANGES[label]
        center = (score_min + score_max) / 2
        if score < score_min:
            pulled = center - (center - score_min) * 0.6
            return round(max(score_min, min(score_max, pulled)), 2)
        if score > score_max:
            pulled = center + (score_max - center) * 0.6
            return round(max(score_min, min(score_max, pulled)), 2)
        return round(score, 2)

    @staticmethod
    def _is_positive_ack(text: str) -> bool:
        return text in {"好的", "好", "谢谢", "好的谢谢", "明白了", "收到", "行", "好的收到"}

    @staticmethod
    def _is_human_handoff_request(text: str) -> bool:
        keywords = ("转人工", "人工客服", "真人客服", "联系人工", "转接人工", "联系客服")
        return any(keyword in text for keyword in keywords) and len(text) <= 12

    @staticmethod
    def _is_neutral_refund_or_after_sales_request(text: str) -> bool:
        keywords = ("退款", "申请退款", "申请售后", "售后", "怎么处理", "看看进度", "商品有点问题", "收到的是", "马上处理")
        return any(keyword in text for keyword in keywords)

    @staticmethod
    def _is_forceful_refund_demand(text: str) -> bool:
        return any(keyword in text for keyword in ("立刻给我退款", "马上退款", "必须退款", "赶紧退款", "快点退款", "退钱"))

    @staticmethod
    def _has_urgency_signal(text: str) -> bool:
        return any(keyword in text for keyword in ("尽快", "快点", "着急", "什么时候", "多久", "马上", "立刻", "还没处理", "怎么还没"))

    @staticmethod
    def _is_mild_dissatisfaction(text: str) -> bool:
        return any(keyword in text for keyword in ("太慢了", "不满意", "太离谱了", "到底怎么回事", "体验太差"))

    @staticmethod
    def _has_complaint_threat(text: str) -> bool:
        return any(keyword in text for keyword in ("投诉", "12315", "举报", "差评", "曝光"))

    @staticmethod
    def _has_strong_negative_signal(text: str) -> bool:
        return any(keyword in text for keyword in ("投诉", "12315", "差评", "举报", "太离谱", "垃圾", "骗人", "你们到底", "必须退款", "退钱"))

    @staticmethod
    def _parse_required_float(value: Any, field_name: str) -> float:
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise LLMError(f"invalid or missing {field_name}: {value}") from exc

    @staticmethod
    def _parse_required_bool(value: Any, field_name: str) -> bool:
        if isinstance(value, bool):
            return value
        text = str(value or "").strip().lower()
        if text in {"true", "1", "yes"}:
            return True
        if text in {"false", "0", "no"}:
            return False
        raise LLMError(f"invalid or missing {field_name}: {value}")

    @classmethod
    def _normalize_label(cls, value: Any) -> str:
        text = str(value or "").strip().lower()
        if text in cls.KNOWN_LABELS:
            return text

        candidates = [item.strip() for item in text.replace("/", "|").replace(",", "|").split("|") if item.strip()]
        known = [item for item in candidates if item in cls.KNOWN_LABELS]
        if len(known) == 1:
            return known[0]
        return text
