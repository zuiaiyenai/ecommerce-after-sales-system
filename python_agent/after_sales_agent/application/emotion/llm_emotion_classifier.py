from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
import re
from typing import Any

from ...providers.llm_client import LLMError, OpenAICompatibleClient, OpenAICompatibleConfig, get_llm_client
from ...domain.models import AfterSalesRequest, ConversationMessage, Order

logger = logging.getLogger("after_sales_agent.emotion")


@dataclass(frozen=True)
class LLMEmotionResult:
    label: str
    emotion_score: float
    confidence: float
    need_human_priority: bool
    reason: str
    raw: dict[str, Any]


class LLMEmotionBackend:
    """Emotion classification driven only by Qwen structured output."""

    SCORE_RANGES = {
        "satisfied": (0.0, 0.15),
        "calm": (0.16, 0.35),
        "anxious": (0.30, 0.55),
        "dissatisfied": (0.50, 0.75),
        "angry": (0.75, 0.95),
    }

    _EMOTION_SCHEMA = {
        "type": "object",
        "required": ["emotion_score", "confidence", "need_human_priority", "reason"],
        "properties": {
            "emotion_score": {"type": "number"},
            "confidence": {"type": "number"},
            "need_human_priority": {"type": "boolean"},
            "reason": {"type": "string"},
        },
    }

    def __init__(self, config: OpenAICompatibleConfig | None = None) -> None:
        if config is None:
            base = OpenAICompatibleConfig.from_env()
            config = OpenAICompatibleConfig(
                base_url=os.getenv("EMOTION_BASE_URL", base.base_url),
                api_key=os.getenv("EMOTION_API_KEY", base.api_key),
                model=os.getenv("EMOTION_MODEL", base.model),
                timeout_seconds=int(os.getenv("EMOTION_TIMEOUT_SECONDS", str(base.timeout_seconds))),
                ollama_keep_alive=base.ollama_keep_alive,
                provider=base.provider,
            )
        self.client = get_llm_client(config)

    def analyze(
        self,
        request: AfterSalesRequest,
        order: Order | None = None,
        *,
        recent_history: tuple[ConversationMessage, ...] = (),
        recent_user_messages: tuple[str, ...] = (),
    ) -> LLMEmotionResult:
        user_prompt = self._user_prompt(
            request=request,
            order=order,
            recent_history=recent_history,
            recent_user_messages=recent_user_messages,
        )
        logger.info(
            "emotion analyze input message=%s recent_history=%d recent_user_messages=%d",
            (request.message or "")[:200],
            len(recent_history),
            len(recent_user_messages),
        )
        logger.debug("emotion analyze prompt=%s", user_prompt)

        raw = self.client.generate_structured(
            system_prompt=self._system_prompt(),
            user_prompt=user_prompt,
            schema={
                "type": "object",
                "required": ["emotion_score", "confidence", "need_human_priority", "reason"],
                "properties": {
                    "emotion_score": {"type": "number"},
                    "confidence": {"type": "number"},
                    "need_human_priority": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
            },
            temperature=0.0,
            max_tokens=260,
        )
        logger.info("emotion raw output=%s", json.dumps(raw, ensure_ascii=False, default=str)[:1600])

        try:
            result = self._parse_result(raw)
        except LLMError as exc:
            logger.warning("emotion parse failed error=%s raw=%s", exc, json.dumps(raw, ensure_ascii=False, default=str)[:1600])
            repaired_raw = self._self_check(
                user_prompt=user_prompt,
                previous_raw=raw,
                previous_error=str(exc),
            )
            logger.info("emotion self_check output=%s", json.dumps(repaired_raw, ensure_ascii=False, default=str)[:1600])
            final_result = self._normalize_result(self._parse_result(repaired_raw))
            self._log_final_result("self_check_parse_repair", final_result)
            return final_result

        if self._needs_self_check(result):
            logger.info(
                "emotion self_check triggered label=%s score=%s confidence=%s",
                result.label,
                result.emotion_score,
                result.confidence,
            )
            repaired_raw = self._self_check(
                user_prompt=user_prompt,
                previous_raw=raw,
                previous_error="emotion label/score/handoff consistency check failed",
            )
            logger.info("emotion self_check output=%s", json.dumps(repaired_raw, ensure_ascii=False, default=str)[:1600])
            repaired_result = self._parse_result(repaired_raw)
            result = repaired_result

        normalized = self._normalize_result(result)
        normalized = self._apply_short_refund_demand_floor(request.message, normalized)
        logger.info(
            "emotion normalized label=%s score=%s confidence=%s need_human_priority=%s reason=%s",
            normalized.label,
            normalized.emotion_score,
            normalized.confidence,
            normalized.need_human_priority,
            normalized.reason,
        )
        final_result = normalized
        self._log_final_result("final", final_result)
        return final_result

    @staticmethod
    def _system_prompt() -> str:
        schema = {
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
            "emotion_score 必须是 0 到 1 之间的单个小数，例如 0.18、0.42、0.87。"
            "confidence 必须是 0 到 1 之间的单个小数，例如 0.66、0.91。"
            "need_human_priority 必须是 true 或 false。"
            "严禁输出区间、范围、文字说明或多个候选值。"
            "例如 emotion_score 不能写成 0.5-1.0、0.5~1.0、较高、medium。"
            "例如 confidence 不能写成 0.6-0.8、较高、high。"
            "need_human_priority 是单独的服务升级建议，不等于情绪强度，不能把它当作 emotion_score 的直接映射。"
            "请按下面 4 类明确区分，不要把它们混为一谈："
            "第一类，中性流程询问：例如‘这个怎么处理’‘退款流程是什么’‘什么时候能处理完’，这类主要是询问流程或进度，可判为 calm 或 anxious；"
            "第二类，强硬处理要求：例如‘立即退款’‘立刻退款’‘必须退款’‘今天就给我退钱’，这类已经带有施压和强硬要求，至少应判为 dissatisfied，不应按普通流程询问处理；"
            "第三类，明确负面评价：例如‘产品太差了’‘质量太差’‘你们这也太慢了’，这类属于明显不满，通常应判为 dissatisfied 或更高；"
            "第四类，升级威胁：例如‘我要投诉12315’‘再不处理我就举报’‘曝光你们’，这类属于强烈负面，通常应判为 angry。"
            "最近历史只能作为辅助线索，不能因为前文有售后问题，就把当前一句中性流程询问直接判成高负面。"
            "只允许类似下面这样的合法输出："
            '{"emotion_score":0.44,"confidence":0.88,"need_human_priority":false,"reason":"用户表达着急，担心处理进度"}'
            "补充示例："
            "“好的谢谢”应更接近低分；"
            "“这个问题怎么处理”更接近低分或中低分；"
            "“转人工”更接近中低分，不应直接高负面；"
            "“你们这也太慢了”可以是中等偏高分；"
            "“再不处理我就投诉12315”应明显更高。"
            "few-shot 示例："
            "输入：‘好的，谢谢’ -> 输出示例：{\"emotion_score\":0.12,\"confidence\":0.90,\"need_human_priority\":false,\"reason\":\"用户表达感谢，情绪平稳偏正向\"}；"
            "输入：‘这个怎么处理’ -> 输出示例：{\"emotion_score\":0.28,\"confidence\":0.88,\"need_human_priority\":false,\"reason\":\"用户在平静询问处理方式\"}；"
            "输入：‘什么时候退款’ -> 输出示例：{\"emotion_score\":0.40,\"confidence\":0.88,\"need_human_priority\":false,\"reason\":\"用户在追问进度，带有催促和着急\"}；"
            "输入：‘转人工’ -> 输出示例：{\"emotion_score\":0.42,\"confidence\":0.90,\"need_human_priority\":true,\"reason\":\"用户要求人工介入，但未明显表达强烈不满\"}；"
            "输入：‘立即退款’ -> 输出示例：{\"emotion_score\":0.58,\"confidence\":0.90,\"need_human_priority\":true,\"reason\":\"用户在强硬要求退款，属于强硬处理要求，已出现明显不满\"}；"
            "输入：‘必须退款，今天就退钱’ -> 输出示例：{\"emotion_score\":0.68,\"confidence\":0.90,\"need_human_priority\":true,\"reason\":\"用户强硬要求退款并施压，负面情绪明显\"}；"
            "输入：‘产品太差了’ -> 输出示例：{\"emotion_score\":0.60,\"confidence\":0.90,\"need_human_priority\":true,\"reason\":\"用户对产品体验作出明确负面评价\"}；"
            "输入：‘你们这也太慢了’ -> 输出示例：{\"emotion_score\":0.58,\"confidence\":0.90,\"need_human_priority\":true,\"reason\":\"用户对处理效率表达明确不满\"}；"
            "输入：‘我要投诉12315’ -> 输出示例：{\"emotion_score\":0.88,\"confidence\":0.90,\"need_human_priority\":true,\"reason\":\"用户明确提到投诉升级，负面情绪强烈\"}；"
            "输入：‘再不处理我就举报了’ -> 输出示例：{\"emotion_score\":0.86,\"confidence\":0.90,\"need_human_priority\":true,\"reason\":\"用户带有威胁升级意味，情绪强烈\"}；"
            "“立即退款”“立刻退款”“马上退款”“必须退款”这类强硬退款要求，不应低于 0.50；"
            "“产品太差了”“质量太差”“太垃圾了”这类明确负面评价，不应低于 0.50；"
            "“我要投诉”“我要举报”“12315”“曝光你们”这类升级威胁，通常应不低于 0.75；"
            "如果一句话同时包含强硬退款要求和明显负面评价，通常应落在 dissatisfied 或更高，不应给出 calm/anxious 的低分。"
            "系统会按 emotion_score 自动映射情绪区间，你只需要输出分数本身。"
            "系统区间参考如下："
            "satisfied=0.00-0.15；"
            "calm=0.16-0.35；"
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
            "你的任务不是解释，而是把上一轮结果修正成一份合法、稳定的 JSON。"
            "只能输出一个 JSON 对象，字段固定为 emotion_score、confidence、need_human_priority、reason。"
            "emotion_score、confidence 必须是 0 到 1 之间的单个小数。"
            "need_human_priority 必须是 true 或 false。"
            "如果上一轮输出结构错了、字段缺失、或数值越界，请直接修正。"
            "判断时请明确区分：中性流程询问、强硬处理要求、明确负面评价、升级威胁。"
            "中性流程询问如‘这个怎么处理’，不应给出过高负面分；"
            "强硬处理要求如‘立即退款’‘必须退款’，不应修正到 0.50 以下；"
            "明确负面评价如‘产品太差了’‘质量太差’，不应修正到 0.50 以下；"
            "升级威胁如‘投诉’‘举报’‘12315’，通常应修正到 0.75 及以上。"
            "例如“好的谢谢你，明白了”不应给出高负面分；“转人工”通常不应直接给到很高负面分；“你们一直不处理，我要投诉12315”应给出明显更高的分数。"
            "few-shot 校准示例："
            "‘立即退款’ 若被打到 0.50 以下，应上调到 dissatisfied 区间；"
            "‘产品太差了’ 若被打到 0.50 以下，应上调到 dissatisfied 区间；"
            "‘我要投诉12315’ 若被打到 0.75 以下，应上调到 angry 区间；"
            "‘转人工’ 若被打到 0.50 以上但没有强烈负面表达，可下调到 anxious 区间。"
            "need_human_priority 是独立的服务升级建议，不要求和 emotion_score 同高同低。"
            "如果分不清边界，优先把结果修正到更保守、更居中的分数。"
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
        return self.client.generate_structured(
            system_prompt=self._self_check_system_prompt(),
            user_prompt=json.dumps(repair_payload, ensure_ascii=False, indent=2),
            schema=_EMOTION_SCHEMA,
            temperature=0.0,
            max_tokens=260,
        )

    @classmethod
    def _parse_result(cls, raw: dict[str, Any]) -> LLMEmotionResult:
        if "assistant_reply" in raw and len(raw) == 1:
            raise LLMError("emotion model did not return structured JSON")

        emotion_score = cls._parse_required_float(raw.get("emotion_score"), "emotion_score")
        confidence = cls._parse_required_float(raw.get("confidence"), "confidence")
        need_human_priority = cls._parse_required_bool(raw.get("need_human_priority"), "need_human_priority")
        label = cls._label_from_score(emotion_score)

        return LLMEmotionResult(
            label=label,
            emotion_score=max(0.0, min(1.0, emotion_score)),
            confidence=max(0.0, min(1.0, confidence)),
            need_human_priority=need_human_priority,
            reason=str(raw.get("reason") or "").strip(),
            raw=raw,
        )

    @classmethod
    def _needs_self_check(cls, result: LLMEmotionResult) -> bool:
        if result.emotion_score < 0.0 or result.emotion_score > 1.0:
            return True
        if result.confidence < 0.0 or result.confidence > 1.0:
            return True
        return False

    @classmethod
    def _normalize_result(cls, result: LLMEmotionResult) -> LLMEmotionResult:
        normalized_score = min(max(result.emotion_score, 0.0), 1.0)
        normalized_confidence = min(max(result.confidence, 0.0), 1.0)
        normalized_label = cls._label_from_score(normalized_score)
        return LLMEmotionResult(
            label=normalized_label,
            emotion_score=normalized_score,
            confidence=normalized_confidence,
            need_human_priority=result.need_human_priority,
            reason=result.reason,
            raw=result.raw,
        )

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
    def _label_from_score(cls, score: float) -> str:
        normalized = min(max(float(score), 0.0), 1.0)
        if normalized >= cls.SCORE_RANGES["angry"][0]:
            return "angry"
        if normalized >= cls.SCORE_RANGES["dissatisfied"][0]:
            return "dissatisfied"
        if normalized >= cls.SCORE_RANGES["anxious"][0]:
            return "anxious"
        if normalized >= cls.SCORE_RANGES["calm"][0]:
            return "calm"
        return "satisfied"

    @classmethod
    def _apply_short_refund_demand_floor(
        cls,
        message: str | None,
        result: LLMEmotionResult,
    ) -> LLMEmotionResult:
        text = str(message or "").strip()
        compact = re.sub(r"\s+", "", text)
        if not compact:
            return result
        if len(compact) > 8:
            return result
        has_refund_intent = any(keyword in compact for keyword in ("退款", "退钱"))
        has_forceful_urgency = any(keyword in compact for keyword in ("立即", "立刻", "马上", "必须", "赶紧", "快"))
        if not (has_refund_intent and has_forceful_urgency):
            return result
        if result.emotion_score >= 0.50:
            return result
        adjusted_score = 0.58
        return LLMEmotionResult(
            label=cls._label_from_score(adjusted_score),
            emotion_score=adjusted_score,
            confidence=result.confidence,
            need_human_priority=True,
            reason="短句强硬退款诉求下限保护",
            raw=result.raw,
        )

    @staticmethod
    def _log_final_result(stage: str, result: LLMEmotionResult) -> None:
        logger.info(
            "emotion %s result label=%s score=%s confidence=%s need_human_priority=%s reason=%s",
            stage,
            result.label,
            result.emotion_score,
            result.confidence,
            result.need_human_priority,
            result.reason,
        )
