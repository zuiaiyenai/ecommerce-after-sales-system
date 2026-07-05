from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..models import AfterSalesRequest, ConversationMessage, EmotionAnalysisResult, EmotionLabel, Order


DEFAULT_MIN_SCORE_BY_CODE = {
    "satisfied": 0,
    "calm": 0,
    "anxious": 20,
    "dissatisfied": 40,
    "angry": 75,
}

DEFAULT_RANK_BY_CODE = {
    "satisfied": 0,
    "calm": 1,
    "anxious": 2,
    "dissatisfied": 3,
    "angry": 4,
}

DEFAULT_HUMAN_HANDOFF_MIN_LEVEL = "dissatisfied"

COMPLAINT_KEYWORDS = ("投诉", "举报", "差评", "骗人", "黑猫", "报警", "诈骗")
ANGER_KEYWORDS = ("生气", "气死", "太过分", "受不了", "你们到底", "不满意", "离谱", "火大")
ANXIOUS_KEYWORDS = (
    "着急",
    "有点着急",
    "很着急",
    "有些着急",
    "尽快",
    "快一点",
    "快点",
    "麻烦快点",
    "抓紧",
    "赶紧",
    "催一下",
    "帮我催",
    "多久能处理好",
    "多久处理好",
    "多久能好",
    "什么时候处理",
    "什么时候能处理",
    "什么时候能好",
    "怎么还没处理",
    "还没处理",
    "一直没处理",
    "一直没有处理",
)
ORDER_DELAY_KEYWORDS = ("超时", "未更新", "停滞", "延迟", "异常", "过久")


@dataclass(frozen=True)
class EmotionAgent:
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
        current_text = " ".join(
            part.strip() for part in (request.message, request.reason, request.description) if part
        )
        history_text = " ".join(message.content for message in recent_history if message.content)
        user_history_text = " ".join(message.strip() for message in recent_user_messages if message)
        combined_text = " ".join(
            part for part in (history_text, user_history_text, current_text) if part
        ).strip()

        score = 0
        triggers: list[str] = []

        score += self._hit_score(combined_text, COMPLAINT_KEYWORDS, 55, triggers)
        score += self._hit_score(combined_text, ANGER_KEYWORDS, 45, triggers)
        score += self._hit_score(combined_text, ANXIOUS_KEYWORDS, 10, triggers)

        punctuation_score = self._punctuation_score(combined_text)
        if punctuation_score > 0:
            score += punctuation_score
            triggers.append("strong_tone")

        if self._mentions_waiting_progress(combined_text):
            score += 6
            triggers.append("waiting_progress")

        if request.human_request_count >= 1:
            score += 15
            triggers.append("ask_human")
        if request.human_request_count >= 2:
            score += 20
            triggers.append("repeat_ask_human")

        recent_user_history = [message for message in recent_history if message.role == "user"]
        user_message_count = max(
            len(recent_user_history),
            len([message for message in recent_user_messages if message]),
        )
        if user_message_count >= 2:
            score += 10
            triggers.append("repeat_follow_up")

        if order is not None:
            status_text = f"{order.refund_status} {order.logistics_status}"
            if any(keyword in status_text for keyword in ORDER_DELAY_KEYWORDS):
                score += 15
                triggers.append("timeout")
            if order.merchant_rejected_before:
                score += 20
                triggers.append("merchant_rejected")

        normalized_score = min(score, 100)
        emotion_levels = self._resolve_emotion_levels(knowledge_base)
        label = self._resolve_label(normalized_score, emotion_levels)
        need_human_priority = self._need_human_priority(
            label,
            emotion_levels,
            handoff_min_level,
        )

        return EmotionAnalysisResult(
            label=label,
            score=normalized_score,
            confidence=self._confidence(normalized_score, triggers),
            triggers=tuple(dict.fromkeys(triggers)),
            need_human_priority=need_human_priority,
            reply_tone=self._reply_tone(label),
            comfort_prefix=self._comfort_prefix(label),
            comfort_examples=self._comfort_examples(label),
        )

    @staticmethod
    def _hit_score(
        text: str,
        keywords: tuple[str, ...],
        unit_score: int,
        triggers: list[str],
    ) -> int:
        matched = [keyword for keyword in keywords if keyword in text]
        if not matched:
            return 0
        triggers.extend(matched)
        return unit_score + max(0, len(matched) - 1) * 5

    @staticmethod
    def _mentions_waiting_progress(text: str) -> bool:
        return any(
            phrase in text
            for phrase in (
                "多久",
                "什么时候",
                "还没",
                "一直没",
                "还没有",
                "尽快",
                "进度",
                "催",
            )
        )

    @staticmethod
    def _punctuation_score(text: str) -> int:
        score = 0
        if "!!!" in text or "???" in text or "？！" in text:
            score += 12
        if text.count("!") >= 3 or text.count("！") >= 3:
            score += 8
        if text.count("?") >= 3 or text.count("？") >= 3:
            score += 8
        return score

    @staticmethod
    def _resolve_emotion_levels(knowledge_base: dict[str, Any] | None) -> tuple[dict[str, int | str], ...]:
        raw_items = knowledge_base.get("emotion_levels") if isinstance(knowledge_base, dict) else None
        if not isinstance(raw_items, list):
            raw_items = []

        levels: list[dict[str, int | str]] = []
        seen_codes: set[str] = set()
        for index, item in enumerate(raw_items):
            if not isinstance(item, dict):
                continue
            code = str(item.get("code") or "").strip().lower()
            if not code or code in seen_codes or code not in DEFAULT_MIN_SCORE_BY_CODE:
                continue
            seen_codes.add(code)
            levels.append(
                {
                    "code": code,
                    "rank": EmotionAgent._to_int(item.get("rank"), DEFAULT_RANK_BY_CODE[code], index),
                    "min_score": EmotionAgent._to_int(
                        item.get("min_score"),
                        DEFAULT_MIN_SCORE_BY_CODE[code],
                        DEFAULT_MIN_SCORE_BY_CODE[code],
                    ),
                }
            )

        if not levels:
            levels = [
                {
                    "code": code,
                    "rank": rank,
                    "min_score": DEFAULT_MIN_SCORE_BY_CODE[code],
                }
                for code, rank in sorted(DEFAULT_RANK_BY_CODE.items(), key=lambda item: item[1])
            ]

        levels.sort(key=lambda item: (int(item["rank"]), int(item["min_score"])))
        return tuple(levels)

    @staticmethod
    def _to_int(value: Any, fallback: int, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback if fallback is not None else default

    @staticmethod
    def _resolve_label(score: int, emotion_levels: tuple[dict[str, int | str], ...]) -> EmotionLabel:
        candidates = sorted(
            emotion_levels,
            key=lambda item: (int(item["min_score"]), int(item["rank"])),
            reverse=True,
        )
        for item in candidates:
            if score < int(item["min_score"]):
                continue
            label = EmotionAgent._emotion_label_from_code(str(item["code"]))
            if label is not None:
                return label
        return EmotionLabel.CALM

    @staticmethod
    def _emotion_label_from_code(code: str) -> EmotionLabel | None:
        mapping = {
            "calm": EmotionLabel.CALM,
            "anxious": EmotionLabel.ANXIOUS,
            "dissatisfied": EmotionLabel.DISSATISFIED,
            "angry": EmotionLabel.ANGRY,
            "satisfied": EmotionLabel.CALM,
        }
        return mapping.get(code)

    @staticmethod
    def _need_human_priority(
        label: EmotionLabel,
        emotion_levels: tuple[dict[str, int | str], ...],
        handoff_min_level: str | None,
    ) -> bool:
        threshold_code = str(handoff_min_level or DEFAULT_HUMAN_HANDOFF_MIN_LEVEL).strip().lower()
        rank_map = {str(item["code"]): int(item["rank"]) for item in emotion_levels}
        threshold_rank = rank_map.get(
            threshold_code,
            rank_map.get(DEFAULT_HUMAN_HANDOFF_MIN_LEVEL, DEFAULT_RANK_BY_CODE[DEFAULT_HUMAN_HANDOFF_MIN_LEVEL]),
        )
        current_rank = rank_map.get(label.value, DEFAULT_RANK_BY_CODE.get(label.value, 1))
        return current_rank >= threshold_rank

    @staticmethod
    def _confidence(score: int, triggers: list[str]) -> float:
        if score >= 70 or score <= 10:
            return 0.92
        if len(triggers) >= 2:
            return 0.88
        if score >= 20:
            return 0.82
        return 0.78

    @staticmethod
    def _reply_tone(label: EmotionLabel) -> str:
        mapping = {
            EmotionLabel.CALM: "clear",
            EmotionLabel.ANXIOUS: "comfort_and_progress",
            EmotionLabel.DISSATISFIED: "comfort_and_action",
            EmotionLabel.ANGRY: "priority_human_support",
        }
        return mapping[label]

    @staticmethod
    def _comfort_prefix(label: EmotionLabel) -> str:
        mapping = {
            EmotionLabel.CALM: "",
            EmotionLabel.ANXIOUS: "您好，理解您现在比较着急，",
            EmotionLabel.DISSATISFIED: "您好，确实让您久等了，",
            EmotionLabel.ANGRY: "您好，很抱歉给您带来不好的体验，",
        }
        return mapping[label]

    @staticmethod
    def _comfort_examples(label: EmotionLabel) -> tuple[str, ...]:
        mapping = {
            EmotionLabel.CALM: (
                "我先帮您看当前状态。",
                "这边按页面流程继续推进。",
            ),
            EmotionLabel.ANXIOUS: (
                "我先帮您确认当前进度。",
                "状态一更新我会第一时间同步您。",
            ),
            EmotionLabel.DISSATISFIED: (
                "这边我先帮您把流程往前推进。",
                "我会继续帮您跟进处理结果。",
            ),
            EmotionLabel.ANGRY: (
                "我先帮您优先处理。",
                "如有需要也可以继续转人工跟进。",
            ),
        }
        return mapping[label]
