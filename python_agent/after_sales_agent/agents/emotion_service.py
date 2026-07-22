from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..domain_models import AfterSalesRequest, ConversationMessage, EmotionAnalysisResult, EmotionLabel, Order
from .llm_emotion_classifier import LLMEmotionBackend


DEFAULT_RANK_BY_CODE = {
    "satisfied": 0,
    "calm": 1,
    "anxious": 2,
    "dissatisfied": 3,
    "angry": 4,
}

DEFAULT_HUMAN_HANDOFF_MIN_LEVEL = "dissatisfied"


@dataclass(frozen=True)
class EmotionResponseStrategy:
    emotion_code: str
    reply_tone: str
    comfort_prefix: str
    comfort_examples: tuple[str, ...]


DEFAULT_EMOTION_STRATEGIES = {
    "satisfied": EmotionResponseStrategy(
        emotion_code="satisfied",
        reply_tone="warm_ack",
        comfort_prefix="",
        comfort_examples=("感谢您的反馈。", "这边继续为您跟进后续进度。"),
    ),
    "calm": EmotionResponseStrategy(
        emotion_code="calm",
        reply_tone="clear",
        comfort_prefix="",
        comfort_examples=("我先帮您看当前状态。", "这边按售后流程继续推进。"),
    ),
    "anxious": EmotionResponseStrategy(
        emotion_code="anxious",
        reply_tone="comfort_and_progress",
        comfort_prefix="我理解您现在比较着急，",
        comfort_examples=("我先帮您确认当前进度。", "有结果后我会尽快同步给您。"),
    ),
    "dissatisfied": EmotionResponseStrategy(
        emotion_code="dissatisfied",
        reply_tone="comfort_and_action",
        comfort_prefix="抱歉给您带来不好的体验，",
        comfort_examples=("这边我先继续帮您往前推进处理。", "我会继续跟进处理结果。"),
    ),
    "angry": EmotionResponseStrategy(
        emotion_code="angry",
        reply_tone="priority_human_support",
        comfort_prefix="非常抱歉给您带来困扰，",
        comfort_examples=("我先优先帮您处理。", "如有需要也可以继续转人工跟进。"),
    ),
}


@dataclass(frozen=True)
class EmotionAgent:
    backend: LLMEmotionBackend = field(default_factory=LLMEmotionBackend)

    def analyze(
        self,
        request: AfterSalesRequest,
        order: Order | None = None,
        *,
        recent_history: tuple[ConversationMessage, ...] = (),
        recent_user_messages: tuple[str, ...] = (),
        knowledge_base: dict[str, Any] | None = None,
        handoff_min_level: str | None = None,
    ) -> EmotionAnalysisResult:
        del knowledge_base

        llm_result = self.backend.analyze(
            request,
            order,
            recent_history=recent_history,
            recent_user_messages=recent_user_messages,
        )
        label = self._map_label(llm_result.label)
        strategy = DEFAULT_EMOTION_STRATEGIES.get(label.value, DEFAULT_EMOTION_STRATEGIES["calm"])
        triggers = self._build_triggers(llm_result)
        need_human_priority = self._resolve_human_priority(
            label,
            handoff_min_level=handoff_min_level,
            llm_need_human_priority=llm_result.need_human_priority,
        )

        return EmotionAnalysisResult(
            label=label,
            score=max(0.0, min(1.0, float(llm_result.emotion_score))),
            confidence=max(0.0, min(1.0, float(llm_result.confidence))),
            triggers=triggers,
            need_human_priority=need_human_priority,
            reply_tone=strategy.reply_tone,
            comfort_prefix=strategy.comfort_prefix,
            comfort_examples=strategy.comfort_examples,
        )

    @staticmethod
    def _map_label(label: str) -> EmotionLabel:
        mapping = {
            "satisfied": EmotionLabel.SATISFIED,
            "calm": EmotionLabel.CALM,
            "anxious": EmotionLabel.ANXIOUS,
            "dissatisfied": EmotionLabel.DISSATISFIED,
            "angry": EmotionLabel.ANGRY,
        }
        return mapping.get(str(label or "").strip().lower(), EmotionLabel.CALM)

    @staticmethod
    def _build_triggers(result: Any) -> tuple[str, ...]:
        triggers = ["llm_emotion"]
        if getattr(result, "reason", ""):
            triggers.append("llm_reasoned")
        return tuple(dict.fromkeys(triggers))

    @staticmethod
    def _resolve_human_priority(
        label: EmotionLabel,
        *,
        handoff_min_level: str | None,
        llm_need_human_priority: bool,
    ) -> bool:
        if handoff_min_level:
            min_level = str(handoff_min_level).strip().lower()
            current_rank = DEFAULT_RANK_BY_CODE.get(label.value, DEFAULT_RANK_BY_CODE["calm"])
            threshold_rank = DEFAULT_RANK_BY_CODE.get(min_level, DEFAULT_RANK_BY_CODE[DEFAULT_HUMAN_HANDOFF_MIN_LEVEL])
            return current_rank >= threshold_rank
        return bool(llm_need_human_priority)
