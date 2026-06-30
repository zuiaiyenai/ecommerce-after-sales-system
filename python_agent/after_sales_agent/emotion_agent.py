from __future__ import annotations

from dataclasses import dataclass

from .models import AfterSalesRequest, ConversationMessage, EmotionAnalysisResult, EmotionLabel, Order


@dataclass(frozen=True)
class EmotionAgent:
    def analyze(
        self,
        request: AfterSalesRequest,
        order: Order | None = None,
        *,
        recent_history: tuple[ConversationMessage, ...] = (),
        recent_user_messages: tuple[str, ...] = (),
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

        score += self._hit_score(
            combined_text,
            ("投诉", "举报", "差评", "骗人", "黑猫", "报警", "诈骗"),
            55,
            triggers,
        )
        score += self._hit_score(
            combined_text,
            ("生气", "气死", "太过分", "受不了", "你们到底", "不满意", "离谱"),
            45,
            triggers,
        )
        score += self._hit_score(
            combined_text,
            ("怎么还", "一直没", "多久了", "快点", "催一下", "什么时候到账", "还没处理"),
            25,
            triggers,
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
            if any(keyword in status_text for keyword in ("超时", "未更新", "停滞", "延迟", "异常", "过久")):
                score += 15
                triggers.append("timeout")
            if order.merchant_rejected_before:
                score += 20
                triggers.append("merchant_rejected")

        label = self._resolve_label(score)
        return EmotionAnalysisResult(
            label=label,
            score=min(score, 100),
            triggers=tuple(dict.fromkeys(triggers)),
            need_human_priority=label in {EmotionLabel.DISSATISFIED, EmotionLabel.ANGRY},
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
    def _resolve_label(score: int) -> EmotionLabel:
        if score >= 75:
            return EmotionLabel.ANGRY
        if score >= 40:
            return EmotionLabel.DISSATISFIED
        if score >= 20:
            return EmotionLabel.ANXIOUS
        return EmotionLabel.CALM

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
