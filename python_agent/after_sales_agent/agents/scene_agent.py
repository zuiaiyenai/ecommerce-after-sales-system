from __future__ import annotations

from dataclasses import dataclass
import re

from ..models import AfterSalesRequest, AfterSalesScene, DecisionContext, Intent


SCENE_DISPLAY_NAMES: dict[AfterSalesScene, str] = {
    AfterSalesScene.PRODUCT_DAMAGE: "商品破损",
    AfterSalesScene.PACKAGE_DAMAGE: "包装破损",
    AfterSalesScene.QUALITY_ISSUE: "质量问题/功能异常",
    AfterSalesScene.WRONG_OR_MISSING_ITEMS: "少发漏发/错发",
    AfterSalesScene.LOGISTICS_ISSUE: "物流异常",
    AfterSalesScene.PROGRESS_QUERY: "进度查询",
    AfterSalesScene.GENERAL: "普通咨询",
}


@dataclass(frozen=True)
class SceneAgent:
    def infer(
        self,
        context_or_request: DecisionContext | AfterSalesRequest,
        intent: Intent | None = None,
    ) -> AfterSalesScene:
        request = (
            context_or_request.request
            if isinstance(context_or_request, DecisionContext)
            else context_or_request
        )
        if intent == Intent.RETURN_LOGISTICS:
            return AfterSalesScene.LOGISTICS_ISSUE
        if intent == Intent.REFUND_PROGRESS:
            return AfterSalesScene.PROGRESS_QUERY
        if request.llm_scene is not None:
            return request.llm_scene

        text = self.normalize_text(
            " ".join(part for part in (request.message, request.reason, request.description) if part)
        )
        return self._infer_from_text(text)

    def describe(
        self,
        context_or_request: DecisionContext | AfterSalesRequest,
        intent: Intent | None = None,
    ) -> str:
        return SCENE_DISPLAY_NAMES[self.infer(context_or_request, intent)]

    @staticmethod
    def display_name(scene: AfterSalesScene) -> str:
        return SCENE_DISPLAY_NAMES[scene]

    @staticmethod
    def normalize_text(text: str) -> str:
        normalized = text.lower().strip()
        return re.sub(r"\s+", "", normalized)

    @staticmethod
    def contains_any(text: str, keywords: tuple[str, ...]) -> bool:
        return any(keyword in text for keyword in keywords)

    @classmethod
    def _infer_from_text(cls, text: str) -> AfterSalesScene:
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
                "屏幕异常",
                "屏幕闪烁",
                "黑块",
                "玻璃裂纹",
            ),
        )
        has_package = cls.contains_any(
            text,
            ("包装破损", "外包装", "快递袋破", "纸箱破", "包装盒破", "压瘪", "挤压"),
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
                "漏水",
                "异味",
                "加热不工作",
                "连接失败",
            ),
        )

        if has_package:
            return AfterSalesScene.PACKAGE_DAMAGE
        if has_damage:
            return AfterSalesScene.PRODUCT_DAMAGE
        if cls.contains_any(text, ("少发", "漏发", "错发", "发错")):
            return AfterSalesScene.WRONG_OR_MISSING_ITEMS
        if cls.contains_any(text, ("物流", "快递", "没收到货", "未收到货", "单号", "运费")):
            return AfterSalesScene.LOGISTICS_ISSUE
        if has_quality_issue:
            return AfterSalesScene.QUALITY_ISSUE
        if cls.contains_any(text, ("到账", "退款进度", "审核到哪", "进度", "多久到账")):
            return AfterSalesScene.PROGRESS_QUERY
        return AfterSalesScene.GENERAL
