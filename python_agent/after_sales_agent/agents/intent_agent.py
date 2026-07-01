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
        scene = request.llm_scene or self._infer_scene(text)
        scored_intents = self._score_all_rules(text, order, scene)

        if scored_intents:
            high_priority_override = self._pick_high_priority_override(scored_intents, text)
            if high_priority_override is not None:
                return self._to_intent_result(high_priority_override)

        llm_override = self._llm_override_result(request)
        if llm_override is not None:
            return llm_override

        if not scored_intents:
            return self._fallback_result()

        top = scored_intents[0]
        second = scored_intents[1] if len(scored_intents) > 1 else None

        if top.score < self.fallback_threshold:
            return self._fallback_result(score=top.score)

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

        return self._fallback_result(score=top.score)

    def infer_scene(self, request: AfterSalesRequest, intent: Intent) -> str:
        scene = self.infer_scene_enum(request, intent)
        scene_map = {
            AfterSalesScene.PRODUCT_DAMAGE: "商品破损",
            AfterSalesScene.PACKAGE_DAMAGE: "包装破损",
            AfterSalesScene.QUALITY_ISSUE: "质量问题/功能异常",
            AfterSalesScene.WRONG_OR_MISSING_ITEMS: "少发漏发/错发",
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
        scene = self._infer_scene(text)
        return scene

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
            and order.after_sales_status not in {
                AfterSalesStatus.NOT_APPLIED,
                AfterSalesStatus.COMPLETED,
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
                ("人工客服", "转人工", "真人客服"),
                ("人工", "真人", "客服"),
                high_priority=True,
            ),
            IntentRule(
                Intent.COMPLAINT,
                "人工升级",
                110,
                ("投诉", "差评", "举报", "报警"),
                ("太慢", "生气", "不满意"),
                need_human=True,
                high_priority=True,
            ),
            IntentRule(
                Intent.SUPPLEMENT_EVIDENCE,
                "证据检查",
                100,
                ("补充凭证", "上传凭证"),
                ("补充", "上传", "图片", "凭证", "材料", "照片"),
                high_priority=True,
            ),
            IntentRule(
                Intent.MERCHANT_REJECTED,
                "争议处理",
                95,
                ("商家拒绝", "驳回申请"),
                ("拒绝", "不同意", "驳回", "申诉"),
            ),
            IntentRule(
                Intent.REFUND_PROGRESS,
                "退款/状态查询",
                90,
                ("退款什么时候到账", "多久到账", "退款进度", "审核到哪", "还没到账"),
                ("退款", "到账", "退钱", "进度", "审核", "更新"),
                require_active_after_sales=True,
                high_priority=True,
            ),
            IntentRule(
                Intent.RETURN_LOGISTICS,
                "退货物流",
                85,
                ("物流异常", "没收到货", "未收到货", "物流没更新"),
                ("物流", "快递", "寄回", "运费", "单号", "没收到", "未收到"),
                high_priority=True,
            ),
            IntentRule(
                Intent.REFUND_ONLY,
                "仅退款规则",
                80,
                ("仅退款",),
                ("只退款",),
                require_active_after_sales=False,
            ),
            IntentRule(
                Intent.EXCHANGE_REPAIR,
                "换货/维修",
                75,
                ("换货", "维修", "修理"),
                ("换新", "返修"),
                require_active_after_sales=False,
            ),
            IntentRule(
                Intent.APPLY_AFTER_SALES,
                "售后申请",
                70,
                (
                    "破损",
                    "坏了",
                    "裂开",
                    "裂纹",
                    "断裂",
                    "碎了",
                    "质量",
                    "故障",
                    "少发",
                    "漏发",
                    "错发",
                    "花屏",
                    "碎屏",
                    "屏幕异常",
                    "屏幕闪烁",
                    "屏幕黑块",
                    "杂音",
                    "电流声",
                    "无法开机",
                    "开不了机",
                    "充电无反应",
                    "充不进去电",
                    "按键失灵",
                    "触控失灵",
                    "漏水",
                    "异味",
                    "加热不工作",
                ),
                ("售后", "退款", "退货", "申请", "怎么处理", "还能退吗", "刚拆开", "刚拆封"),
                require_active_after_sales=False,
            ),
        )

    @staticmethod
    def _matched_apply_keywords(text: str) -> tuple[str, ...]:
        keywords = (
            "售后",
            "退款",
            "退货",
            "申请",
            "坏了",
            "破损",
            "质量",
            "故障",
            "花屏",
            "杂音",
            "少发",
            "漏发",
            "错发",
        )
        return tuple(keyword for keyword in keywords if keyword in text)

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
            Intent.EXCHANGE_REPAIR: "换货或维修",
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
        both_are_actionable = {
            top.rule.intent,
            second.rule.intent,
        } <= {
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
        has_damage = cls.contains_any(
            text,
            (
                "破损",
                "裂开",
                "裂纹",
                "断裂",
                "碎了",
                "坏了",
                "凹陷",
                "变形",
                "花屏",
                "花了",
                "碎屏",
                "屏幕异常",
                "屏幕闪烁",
                "屏幕黑块",
                "屏幕破损",
                "玻璃裂纹",
                "后盖破裂",
            ),
        )
        has_package = cls.contains_any(
            text,
            ("包装破损", "外包装", "快递袋破", "纸箱破", "包装盒破", "封口撕裂", "压瘪", "挤压"),
        )
        has_quality_issue = cls.contains_any(
            text,
            (
                "质量",
                "故障",
                "异常",
                "没声音",
                "不能用",
                "失灵",
                "杂音",
                "电流声",
                "无法开机",
                "开不了机",
                "充电无反应",
                "充不进去电",
                "充电慢",
                "触控失灵",
                "按键失灵",
                "摄像头模糊",
                "漏水",
                "加热不工作",
                "异味",
                "无法闭合",
            ),
        )

        if has_package:
            return AfterSalesScene.PACKAGE_DAMAGE
        if has_damage:
            return AfterSalesScene.PRODUCT_DAMAGE
        if cls.contains_any(text, ("少发", "漏发", "错发", "发错")):
            return AfterSalesScene.WRONG_OR_MISSING_ITEMS
        if cls.contains_any(text, ("物流", "快递", "没收到", "未收到", "单号", "运费")):
            return AfterSalesScene.LOGISTICS_ISSUE
        if has_quality_issue:
            return AfterSalesScene.QUALITY_ISSUE
        if cls.contains_any(text, ("到账", "退款进度", "审核到哪", "进度", "多久到账")):
            return AfterSalesScene.PROGRESS_QUERY
        return AfterSalesScene.GENERAL
