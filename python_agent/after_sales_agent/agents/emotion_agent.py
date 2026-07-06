from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..models import AfterSalesRequest, ConversationMessage, EmotionAnalysisResult, EmotionLabel, Order


DEFAULT_MIN_SCORE_BY_CODE = {
    "satisfied": 0,
    "calm": 0,
    "anxious": 20,
    "dissatisfied": 45,
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


@dataclass(frozen=True)
class EmotionKeywordGroup:
    group_code: str
    emotion_code: str
    source_scope: str
    trigger_code: str
    keywords: tuple[str, ...]
    hit_score: int


@dataclass(frozen=True)
class EmotionResponseStrategy:
    emotion_code: str
    reply_tone: str
    comfort_prefix: str
    comfort_examples: tuple[str, ...]


DEFAULT_EMOTION_KEYWORD_GROUPS = (
    EmotionKeywordGroup(
        group_code="complaint_keywords",
        emotion_code="angry",
        source_scope="conversation",
        trigger_code="complaint",
        keywords=("投诉", "举报", "差评", "黑猫", "12315", "骗人"),
        hit_score=55,
    ),
    EmotionKeywordGroup(
        group_code="anger_keywords",
        emotion_code="angry",
        source_scope="conversation",
        trigger_code="anger",
        keywords=("生气", "气死", "太过分", "受不了", "离谱", "火大", "很火"),
        hit_score=42,
    ),
    EmotionKeywordGroup(
        group_code="dissatisfied_keywords",
        emotion_code="dissatisfied",
        source_scope="conversation",
        trigger_code="dissatisfied",
        keywords=("不满意", "太慢", "很差", "一直没处理", "还没处理", "没人管"),
        hit_score=26,
    ),
    EmotionKeywordGroup(
        group_code="anxious_keywords",
        emotion_code="anxious",
        source_scope="conversation",
        trigger_code="anxious",
        keywords=(
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
            "什么时候处理",
            "什么时候能处理",
            "多久能处理好",
            "多久能好",
        ),
        hit_score=20,
    ),
    EmotionKeywordGroup(
        group_code="waiting_progress_keywords",
        emotion_code="anxious",
        source_scope="conversation",
        trigger_code="waiting_progress",
        keywords=("多久", "什么时候", "还没", "一直没", "进度", "催"),
        hit_score=6,
    ),
    EmotionKeywordGroup(
        group_code="order_delay_keywords",
        emotion_code="anxious",
        source_scope="order_status",
        trigger_code="timeout",
        keywords=("超时", "未更新", "停滞", "延迟", "异常", "过久"),
        hit_score=15,
    ),
)

DEFAULT_EMOTION_STRATEGIES = {
    "calm": EmotionResponseStrategy(
        emotion_code="calm",
        reply_tone="clear",
        comfort_prefix="",
        comfort_examples=("我先帮您看当前状态。", "这边按售后流程继续推进。"),
    ),
    "anxious": EmotionResponseStrategy(
        emotion_code="anxious",
        reply_tone="comfort_and_progress",
        comfort_prefix="您好，我理解您现在比较着急，",
        comfort_examples=("我先帮您确认当前进度。", "有结果后我会尽快同步给您。"),
    ),
    "dissatisfied": EmotionResponseStrategy(
        emotion_code="dissatisfied",
        reply_tone="comfort_and_action",
        comfort_prefix="您好，确实让您久等了，",
        comfort_examples=("这边我先继续帮您往前推进处理。", "我会继续跟进处理结果。"),
    ),
    "angry": EmotionResponseStrategy(
        emotion_code="angry",
        reply_tone="priority_human_support",
        comfort_prefix="您好，很抱歉给您带来不好的体验，",
        comfort_examples=("我先优先帮您处理。", "如有需要也可以继续转人工跟进。"),
    ),
}


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
        current_text = " ".join(part.strip() for part in (request.message, request.reason, request.description) if part)
        history_text = " ".join(message.content for message in recent_history if message.content)
        user_history_text = " ".join(message.strip() for message in recent_user_messages if message)
        combined_text = " ".join(part for part in (history_text, user_history_text, current_text) if part).strip()

        keyword_groups = self._resolve_keyword_groups(knowledge_base)
        score, triggers = self._score_from_scope_text(
            combined_text,
            keyword_groups,
            source_scope="conversation",
        )

        punctuation_score = self._punctuation_score(combined_text)
        if punctuation_score > 0:
            score += punctuation_score
            triggers.append("strong_tone")

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
            status_score, status_triggers = self._score_from_scope_text(
                status_text,
                keyword_groups,
                source_scope="order_status",
            )
            score += status_score
            triggers.extend(status_triggers)
            if order.merchant_rejected_before:
                score += 20
                triggers.append("merchant_rejected")

        normalized_score = min(max(score, 0), 100)
        emotion_levels = self._resolve_emotion_levels(knowledge_base)
        label = self._resolve_label(normalized_score, emotion_levels)
        need_human_priority = self._need_human_priority(label, emotion_levels, handoff_min_level)
        strategy = self._resolve_strategy(label, knowledge_base)

        return EmotionAnalysisResult(
            label=label,
            score=normalized_score,
            confidence=self._confidence(normalized_score, triggers),
            triggers=tuple(dict.fromkeys(triggers)),
            need_human_priority=need_human_priority,
            reply_tone=strategy.reply_tone,
            comfort_prefix=strategy.comfort_prefix,
            comfort_examples=strategy.comfort_examples,
        )

    @staticmethod
    def _score_from_scope_text(
        text: str,
        keyword_groups: tuple[EmotionKeywordGroup, ...],
        *,
        source_scope: str,
    ) -> tuple[int, list[str]]:
        if not text:
            return 0, []

        total_score = 0
        triggers: list[str] = []
        for group in keyword_groups:
            if group.source_scope != source_scope:
                continue
            matched = [keyword for keyword in group.keywords if keyword and keyword in text]
            if not matched:
                continue
            total_score += group.hit_score + max(0, len(matched) - 1) * 5
            triggers.append(group.trigger_code)
        return total_score, triggers

    @staticmethod
    def _punctuation_score(text: str) -> int:
        score = 0
        if "!!!" in text or "？？？" in text:
            score += 12
        if text.count("!") >= 3 or text.count("！") >= 3:
            score += 8
        if text.count("?") >= 3 or text.count("？") >= 3:
            score += 8
        return score

    @staticmethod
    def _resolve_emotion_levels(
        knowledge_base: dict[str, Any] | None,
    ) -> tuple[dict[str, int | str], ...]:
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
                    "rank": EmotionAgent._to_int(item.get("rank"), DEFAULT_RANK_BY_CODE[code]),
                    "min_score": EmotionAgent._to_int(item.get("min_score"), DEFAULT_MIN_SCORE_BY_CODE[code]),
                    "index": index,
                }
            )

        if not levels:
            levels = [
                {
                    "code": code,
                    "rank": rank,
                    "min_score": DEFAULT_MIN_SCORE_BY_CODE[code],
                    "index": rank,
                }
                for code, rank in sorted(DEFAULT_RANK_BY_CODE.items(), key=lambda item: item[1])
            ]

        levels.sort(key=lambda item: (int(item["rank"]), int(item["min_score"]), int(item["index"])))
        return tuple(levels)

    @staticmethod
    def _resolve_keyword_groups(
        knowledge_base: dict[str, Any] | None,
    ) -> tuple[EmotionKeywordGroup, ...]:
        raw_items = knowledge_base.get("emotion_keyword_knowledge") if isinstance(knowledge_base, dict) else None
        if not isinstance(raw_items, list):
            return DEFAULT_EMOTION_KEYWORD_GROUPS

        groups: list[EmotionKeywordGroup] = []
        seen_codes: set[str] = set()
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            group_code = str(item.get("group_code") or "").strip().lower()
            emotion_code = str(item.get("emotion") or item.get("emotion_code") or "").strip().lower()
            source_scope = str(item.get("source_scope") or "conversation").strip().lower()
            trigger_code = str(item.get("trigger_code") or group_code or "").strip().lower()
            keywords_raw = item.get("keywords")
            if not isinstance(keywords_raw, list):
                continue
            keywords = tuple(str(keyword).strip() for keyword in keywords_raw if str(keyword).strip())
            if not group_code or group_code in seen_codes or not keywords:
                continue
            if emotion_code not in DEFAULT_MIN_SCORE_BY_CODE:
                continue
            seen_codes.add(group_code)
            groups.append(
                EmotionKeywordGroup(
                    group_code=group_code,
                    emotion_code=emotion_code,
                    source_scope=source_scope,
                    trigger_code=trigger_code,
                    keywords=keywords,
                    hit_score=EmotionAgent._to_int(item.get("hit_score"), 10),
                )
            )
        return tuple(groups) or DEFAULT_EMOTION_KEYWORD_GROUPS

    @staticmethod
    def _resolve_strategy(
        label: EmotionLabel,
        knowledge_base: dict[str, Any] | None,
    ) -> EmotionResponseStrategy:
        raw_items = knowledge_base.get("emotion_strategy_knowledge") if isinstance(knowledge_base, dict) else None
        if isinstance(raw_items, list):
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                code = str(item.get("emotion") or item.get("emotion_code") or "").strip().lower()
                if code != label.value:
                    continue
                return EmotionResponseStrategy(
                    emotion_code=code,
                    reply_tone=str(item.get("reply_tone") or "clear"),
                    comfort_prefix=str(item.get("comfort_prefix") or ""),
                    comfort_examples=tuple(
                        str(example).strip()
                        for example in item.get("comfort_examples") or []
                        if str(example).strip()
                    ),
                )
        return DEFAULT_EMOTION_STRATEGIES.get(label.value, DEFAULT_EMOTION_STRATEGIES["calm"])

    @staticmethod
    def _resolve_label(
        score: int,
        emotion_levels: tuple[dict[str, int | str], ...],
    ) -> EmotionLabel:
        selected_code = "calm"
        for item in emotion_levels:
            if score >= int(item["min_score"]):
                selected_code = str(item["code"])
        mapping = {
            "satisfied": EmotionLabel.CALM,
            "calm": EmotionLabel.CALM,
            "anxious": EmotionLabel.ANXIOUS,
            "dissatisfied": EmotionLabel.DISSATISFIED,
            "angry": EmotionLabel.ANGRY,
        }
        return mapping.get(selected_code, EmotionLabel.CALM)

    @staticmethod
    def _need_human_priority(
        label: EmotionLabel,
        emotion_levels: tuple[dict[str, int | str], ...],
        handoff_min_level: str | None,
    ) -> bool:
        min_level = str(handoff_min_level or DEFAULT_HUMAN_HANDOFF_MIN_LEVEL).strip().lower()
        rank_map = {str(item["code"]): int(item["rank"]) for item in emotion_levels}
        current_rank = rank_map.get(label.value, DEFAULT_RANK_BY_CODE.get(label.value, 0))
        threshold_rank = rank_map.get(min_level, DEFAULT_RANK_BY_CODE.get(min_level, 3))
        return current_rank >= threshold_rank

    @staticmethod
    def _confidence(score: int, triggers: list[str]) -> float:
        base = 0.55
        trigger_bonus = min(len(set(triggers)) * 0.08, 0.25)
        score_bonus = min(score / 200, 0.2)
        return round(min(base + trigger_bonus + score_bonus, 0.98), 2)

    @staticmethod
    def _to_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
