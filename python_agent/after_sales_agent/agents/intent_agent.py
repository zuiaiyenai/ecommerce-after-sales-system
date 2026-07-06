from __future__ import annotations

from dataclasses import dataclass
import re

from ..models import (
    AfterSalesRequest,
    AfterSalesScene,
    AfterSalesStatus,
    Intent,
    IntentResult,
    Order,
)


@dataclass(frozen=True)
class IntentRule:
    intent: Intent
    next_agent: str
    priority: int
    strong_keywords: tuple[str, ...]
    weak_keywords: tuple[str, ...] = ()
    keywords_all: tuple[str, ...] = ()
    exclude_keywords: tuple[str, ...] = ()
    need_human: bool = False
    require_active_after_sales: bool | None = None
    high_priority: bool = False


@dataclass(frozen=True)
class ScoredIntent:
    rule: IntentRule
    score: int
    matched_keywords: tuple[str, ...]


@dataclass(frozen=True)
class IntentAgent:
    threshold: int = 60
    fallback_threshold: int = 40
    clarification_margin: int = 15
    high_priority_threshold: int = 70

    def classify(self, request: AfterSalesRequest, order: Order | None) -> IntentResult:
        text = self.normalize_text(
            " ".join(part for part in (request.message, request.reason, request.description) if part)
        )
        if (
            request.llm_intent == Intent.SUPPLEMENT_EVIDENCE
            and order is not None
            and getattr(order.after_sales_status, "value", order.after_sales_status)
            == AfterSalesStatus.NOT_APPLIED.value
        ):
            request = request.__class__(**{**request.__dict__, "llm_intent": Intent.APPLY_AFTER_SALES})

        scene = request.llm_scene or self._infer_scene(text)
        scored_intents = self._score_all_rules(text, order, scene)

        llm_override = self._llm_override_result(request)
        if llm_override is not None and (
            request.llm_intent == Intent.APPLY_AFTER_SALES
            and (
                order is None
                or getattr(order.after_sales_status, "value", order.after_sales_status)
                == AfterSalesStatus.NOT_APPLIED.value
            )
        ):
            return llm_override

        if scored_intents:
            high_priority_override = self._pick_high_priority_override(scored_intents, text)
            if high_priority_override is not None:
                return self._to_intent_result(high_priority_override)

        if llm_override is not None:
            return llm_override

        if not scored_intents:
            heuristic = self._heuristic_fallback(text, scene, order)
            return heuristic or self._fallback_result()

        top = scored_intents[0]
        second = scored_intents[1] if len(scored_intents) > 1 else None

        if (
            scene == AfterSalesScene.WRONG_OR_MISSING_ITEMS
            and top.rule.intent == Intent.EXCHANGE_REPAIR
            and second is not None
            and second.rule.intent == Intent.APPLY_AFTER_SALES
        ):
            return self._to_intent_result(top)

        if top.score < self.fallback_threshold:
            heuristic = self._heuristic_fallback(text, scene, order)
            return heuristic or self._fallback_result(score=top.score)

        if second and top.score >= self.threshold and second.score >= self.threshold:
            if self._should_clarify(text, top, second):
                return IntentResult(
                    intent=top.rule.intent,
                    next_agent="意图澄清",
                    need_human=False,
                    keywords=top.matched_keywords,
                    score=top.score,
                    needs_clarification=True,
                    clarification_options=(
                        self._intent_label(top.rule.intent),
                        self._intent_label(second.rule.intent),
                    ),
                )

        if top.score >= self.threshold:
            return self._to_intent_result(top)

        heuristic = self._heuristic_fallback(text, scene, order)
        return heuristic or self._fallback_result(score=top.score)

    def infer_scene(self, request: AfterSalesRequest, intent: Intent) -> str:
        scene = self.infer_scene_enum(request, intent)
        scene_map = {
            AfterSalesScene.PRODUCT_DAMAGE: "商品破损",
            AfterSalesScene.PACKAGE_DAMAGE: "包装破损",
            AfterSalesScene.QUALITY_ISSUE: "质量问题/功能异常",
            AfterSalesScene.WRONG_OR_MISSING_ITEMS: "少发错发",
            AfterSalesScene.LOGISTICS_ISSUE: "物流异常",
            AfterSalesScene.PROGRESS_QUERY: "进度查询",
            AfterSalesScene.GENERAL: "普通咨询",
        }
        return scene_map[scene]

    def infer_scene_enum(self, request: AfterSalesRequest, intent: Intent) -> AfterSalesScene:
        text = self.normalize_text(
            " ".join(part for part in (request.message, request.reason, request.description) if part)
        )
        if intent == Intent.RETURN_LOGISTICS:
            return AfterSalesScene.LOGISTICS_ISSUE
        if intent == Intent.REFUND_PROGRESS:
            return AfterSalesScene.PROGRESS_QUERY
        if request.llm_scene is not None:
            return request.llm_scene
        return self._infer_scene(text)

    @staticmethod
    def normalize_text(text: str) -> str:
        normalized = text.lower().strip()
        return re.sub(r"\s+", "", normalized)

    @staticmethod
    def contains_any(text: str, keywords: tuple[str, ...]) -> bool:
        return any(keyword in text for keyword in keywords)

    def _score_rule(
        self,
        rule: IntentRule,
        text: str,
        order: Order | None,
        scene: AfterSalesScene,
    ) -> ScoredIntent | None:
        if rule.keywords_all and not all(keyword in text for keyword in rule.keywords_all):
            return None
        if rule.exclude_keywords and any(keyword in text for keyword in rule.exclude_keywords):
            return None

        matched_strong = tuple(keyword for keyword in rule.strong_keywords if keyword in text)
        matched_weak = tuple(keyword for keyword in rule.weak_keywords if keyword in text)

        if rule.strong_keywords and rule.weak_keywords and not matched_strong and not matched_weak:
            return None
        if rule.strong_keywords and not rule.weak_keywords and not matched_strong:
            return None
        if rule.weak_keywords and not rule.strong_keywords and not matched_weak:
            return None

        is_active = bool(
            order
            and order.after_sales_status
            not in {
                AfterSalesStatus.NOT_APPLIED,
                AfterSalesStatus.COMPLETED,
                AfterSalesStatus.CLOSED,
            }
        )

        score = rule.priority
        if matched_strong:
            score += 50
        if matched_weak:
            score += len(matched_weak) * 20
        if len(matched_strong) > 1:
            score += (len(matched_strong) - 1) * 10

        if rule.require_active_after_sales is True:
            score += 20 if is_active else -40
        elif rule.require_active_after_sales is False:
            score += 20 if not is_active else -40

        score += self._scene_adjustment(rule.intent, scene)
        return ScoredIntent(
            rule=rule,
            score=score,
            matched_keywords=matched_strong + tuple(
                keyword for keyword in matched_weak if keyword not in matched_strong
            ),
        )

    @staticmethod
    def _rules() -> tuple[IntentRule, ...]:
        return (
            IntentRule(
                Intent.HUMAN_SERVICE,
                "人工升级",
                120,
                ("人工客服", "真人客服", "转人工"),
                ("人工", "真人", "客服"),
                high_priority=True,
            ),
            IntentRule(
                Intent.COMPLAINT,
                "投诉处理",
                110,
                ("投诉", "举报", "差评", "12315", "黑猫"),
                ("太差", "不满意", "离谱", "骗人", "生气"),
                need_human=True,
                high_priority=True,
            ),
            IntentRule(
                Intent.SUPPLEMENT_EVIDENCE,
                "证据检查",
                100,
                ("补充凭证", "上传凭证", "补充材料"),
                ("补充", "上传", "图片", "照片", "视频", "凭证", "截图"),
                high_priority=True,
            ),
            IntentRule(
                Intent.MERCHANT_REJECTED,
                "申诉处理",
                95,
                ("商家拒绝", "审核驳回"),
                ("驳回", "不同意", "被拒", "申诉"),
            ),
            IntentRule(
                Intent.REFUND_PROGRESS,
                "进度查询",
                90,
                ("退款到哪了", "退款进度", "多久到账", "还没到账", "审核到哪了"),
                ("退款", "到账", "进度", "审核", "更新"),
                require_active_after_sales=True,
                high_priority=True,
            ),
            IntentRule(
                Intent.RETURN_LOGISTICS,
                "退货物流",
                85,
                ("物流异常", "没收到货", "退货地址", "寄回地址"),
                ("物流", "快递", "单号", "寄回"),
                high_priority=True,
            ),
            IntentRule(
                Intent.REFUND_ONLY,
                "仅退款规则",
                80,
                ("仅退款",),
                ("只退款", "不要退货"),
                require_active_after_sales=False,
            ),
            IntentRule(
                Intent.EXCHANGE_REPAIR,
                "换货维修",
                75,
                ("换货", "维修", "修理", "补发"),
                ("换新", "返修"),
                require_active_after_sales=False,
            ),
            IntentRule(
                Intent.APPLY_AFTER_SALES,
                "售后申请",
                70,
                (
                    "申请售后",
                    "售后",
                    "退货退款",
                    "商品有问题",
                    "有问题",
                    "坏了",
                    "破损",
                    "裂开",
                    "裂纹",
                    "碎了",
                    "质量问题",
                    "故障",
                    "没声音",
                    "没有声音",
                    "无法开机",
                    "充不进电",
                    "按键失灵",
                    "触控失灵",
                    "少发",
                    "漏发",
                    "错发",
                ),
                ("退款", "退货", "申请", "处理", "怎么处理", "还能退吗"),
                require_active_after_sales=False,
            ),
        )

    def _score_all_rules(
        self,
        text: str,
        order: Order | None,
        scene: AfterSalesScene,
    ) -> list[ScoredIntent]:
        scored: list[ScoredIntent] = []
        for rule in self._rules():
            result = self._score_rule(rule, text, order, scene)
            if result is not None:
                scored.append(result)
        return sorted(scored, key=lambda item: item.score, reverse=True)

    def _pick_high_priority_override(
        self,
        scored_intents: list[ScoredIntent],
        text: str,
    ) -> ScoredIntent | None:
        if not scored_intents:
            return None
        top = scored_intents[0]
        if not top.rule.high_priority or top.score < self.high_priority_threshold:
            return None
        second = scored_intents[1] if len(scored_intents) > 1 else None
        if second and second.score >= self.threshold and self._should_clarify(text, top, second):
            return None
        return top

    @staticmethod
    def _intent_label(intent: Intent) -> str:
        mapping = {
            Intent.HUMAN_SERVICE: "联系人工客服",
            Intent.COMPLAINT: "投诉反馈",
            Intent.SUPPLEMENT_EVIDENCE: "补充凭证",
            Intent.MERCHANT_REJECTED: "申诉处理",
            Intent.REFUND_PROGRESS: "查询退款进度",
            Intent.RETURN_LOGISTICS: "查询物流问题",
            Intent.REFUND_ONLY: "仅退款",
            Intent.EXCHANGE_REPAIR: "换货、维修或补发",
            Intent.APPLY_AFTER_SALES: "申请售后",
            Intent.GENERAL: "普通咨询",
        }
        return mapping[intent]

    def _to_intent_result(self, scored_intent: ScoredIntent) -> IntentResult:
        return IntentResult(
            intent=scored_intent.rule.intent,
            next_agent=scored_intent.rule.next_agent,
            need_human=scored_intent.rule.need_human,
            keywords=scored_intent.matched_keywords,
            score=scored_intent.score,
        )

    def _llm_override_result(self, request: AfterSalesRequest) -> IntentResult | None:
        if request.llm_intent is None or request.llm_intent == Intent.GENERAL:
            return None
        if request.llm_confidence < 0.6:
            return None
        for rule in self._rules():
            if rule.intent == request.llm_intent:
                return IntentResult(
                    intent=rule.intent,
                    next_agent=rule.next_agent,
                    need_human=rule.need_human,
                    keywords=("llm_context",),
                    score=max(int(request.llm_confidence * 100), self.threshold),
                )
        return None

    @staticmethod
    def _fallback_result(score: int = 0) -> IntentResult:
        return IntentResult(
            intent=Intent.GENERAL,
            next_agent="普通咨询",
            need_human=False,
            score=score,
            fallback=True,
        )

    def _heuristic_fallback(
        self,
        text: str,
        scene: AfterSalesScene,
        order: Order | None,
    ) -> IntentResult | None:
        if scene == AfterSalesScene.LOGISTICS_ISSUE:
            return IntentResult(
                intent=Intent.RETURN_LOGISTICS,
                next_agent="退货物流",
                need_human=False,
                keywords=("logistics_scene_heuristic",),
                score=68,
            )
        if self.contains_any(text, ("退款到哪了", "多久到账", "进度", "审核")) and order is not None:
            return IntentResult(
                intent=Intent.REFUND_PROGRESS,
                next_agent="进度查询",
                need_human=False,
                keywords=("heuristic",),
                score=65,
            )
        if scene in {
            AfterSalesScene.PRODUCT_DAMAGE,
            AfterSalesScene.PACKAGE_DAMAGE,
            AfterSalesScene.QUALITY_ISSUE,
            AfterSalesScene.WRONG_OR_MISSING_ITEMS,
        }:
            return IntentResult(
                intent=Intent.APPLY_AFTER_SALES,
                next_agent="售后申请",
                need_human=False,
                keywords=("scene_heuristic",),
                score=65,
            )
        if self.contains_any(text, ("售后", "退货", "退款", "补发", "维修", "换货")):
            return IntentResult(
                intent=Intent.APPLY_AFTER_SALES,
                next_agent="售后申请",
                need_human=False,
                keywords=("keyword_heuristic",),
                score=60,
            )
        return None

    def _should_clarify(
        self,
        text: str,
        top: ScoredIntent,
        second: ScoredIntent,
    ) -> bool:
        if top.rule.intent == second.rule.intent:
            return False
        if top.score - second.score <= self.clarification_margin:
            return True

        multi_intent_markers = ("都想", "一起", "同时", "一并")
        has_multi_marker = any(marker in text for marker in multi_intent_markers)
        both_are_actionable = {top.rule.intent, second.rule.intent} <= {
            Intent.REFUND_PROGRESS,
            Intent.RETURN_LOGISTICS,
            Intent.APPLY_AFTER_SALES,
            Intent.SUPPLEMENT_EVIDENCE,
        }
        return has_multi_marker and both_are_actionable and second.score >= self.threshold

    @staticmethod
    def _scene_adjustment(intent: Intent, scene: AfterSalesScene) -> int:
        if intent == Intent.APPLY_AFTER_SALES and scene in {
            AfterSalesScene.PRODUCT_DAMAGE,
            AfterSalesScene.PACKAGE_DAMAGE,
            AfterSalesScene.QUALITY_ISSUE,
            AfterSalesScene.WRONG_OR_MISSING_ITEMS,
        }:
            return 20
        if intent == Intent.EXCHANGE_REPAIR and scene == AfterSalesScene.WRONG_OR_MISSING_ITEMS:
            return 20
        if intent == Intent.RETURN_LOGISTICS and scene == AfterSalesScene.LOGISTICS_ISSUE:
            return 20
        if intent == Intent.REFUND_PROGRESS and scene == AfterSalesScene.PROGRESS_QUERY:
            return 20
        if scene == AfterSalesScene.LOGISTICS_ISSUE and intent not in {
            Intent.RETURN_LOGISTICS,
            Intent.HUMAN_SERVICE,
            Intent.COMPLAINT,
        }:
            return -40
        if scene == AfterSalesScene.PROGRESS_QUERY and intent not in {
            Intent.REFUND_PROGRESS,
            Intent.HUMAN_SERVICE,
            Intent.COMPLAINT,
        }:
            return -40
        if scene in {
            AfterSalesScene.PRODUCT_DAMAGE,
            AfterSalesScene.PACKAGE_DAMAGE,
            AfterSalesScene.QUALITY_ISSUE,
            AfterSalesScene.WRONG_OR_MISSING_ITEMS,
        } and intent in {Intent.REFUND_PROGRESS, Intent.RETURN_LOGISTICS}:
            return -40
        return 0

    @classmethod
    def _infer_scene(cls, text: str) -> AfterSalesScene:
        if cls.contains_any(text, ("退款到哪了", "多久到账", "退款进度", "进度", "审核到哪了")):
            return AfterSalesScene.PROGRESS_QUERY
        if cls.contains_any(text, ("包装破损", "外包装", "快递箱破", "箱子破", "封口破损")):
            return AfterSalesScene.PACKAGE_DAMAGE
        if cls.contains_any(text, ("少发", "漏发", "错发", "发错", "少了一件")):
            return AfterSalesScene.WRONG_OR_MISSING_ITEMS
        if cls.contains_any(text, ("物流", "快递", "单号", "寄回", "退货地址", "没收到货")):
            return AfterSalesScene.LOGISTICS_ISSUE
        if cls.contains_any(
            text,
            (
                "破损",
                "裂开",
                "裂纹",
                "碎了",
                "磕碰",
                "凹陷",
                "变形",
                "花屏",
                "碎屏",
                "屏幕破损",
            ),
        ):
            return AfterSalesScene.PRODUCT_DAMAGE
        if cls.contains_any(
            text,
            (
                "质量问题",
                "有问题",
                "商品有问题",
                "故障",
                "异常",
                "没声音",
                "没有声音",
                "不能用",
                "失灵",
                "杂音",
                "无法开机",
                "充不进电",
                "充电无反应",
                "按键失灵",
                "触控失灵",
                "异味",
            ),
        ):
            return AfterSalesScene.QUALITY_ISSUE
        return AfterSalesScene.GENERAL
