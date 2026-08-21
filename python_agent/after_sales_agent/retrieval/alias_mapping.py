"""Scene and product category alias mapping, extracted from PgVectorKnowledgeRetriever."""
from __future__ import annotations


def scene_aliases(scene: str | None) -> list[str]:
    value = str(scene or "").strip()
    if not value:
        return []
    alias_map = {
        "damage": ["damage", "product_damage"],
        "product_damage": ["product_damage", "damage"],
        "quality_issue": ["quality_issue"],
        "package_damage": ["package_damage"],
        "wrong_or_missing_items": ["wrong_or_missing_items"],
        "logistics_issue": ["logistics_issue", "logistics_damage"],
        "logistics_damage": ["logistics_damage", "logistics_issue"],
    }
    aliases = alias_map.get(value, [value])
    return list(dict.fromkeys(aliases))


def product_category_aliases(product_category: str | None) -> list[str]:
    value = str(product_category or "").strip()
    if not value:
        return []
    lowered = value.lower()
    alias_map = {
        "数码": ["数码", "digital", "headphone", "phone"],
        "digital": ["digital", "数码", "headphone", "phone"],
        "耳机": ["耳机", "headphone", "digital", "数码"],
        "蓝牙耳机": ["蓝牙耳机", "耳机", "headphone", "digital", "数码"],
        "蓝牙降噪耳机": ["蓝牙降噪耳机", "蓝牙耳机", "耳机", "headphone", "digital", "数码"],
        "headphone": ["headphone", "耳机", "digital", "数码"],
        "手机": ["手机", "phone", "digital", "数码"],
        "phone": ["phone", "手机", "digital", "数码"],
        "服装": ["服装", "apparel"],
        "apparel": ["apparel", "服装"],
        "日用": ["日用", "daily"],
        "daily": ["daily", "日用"],
        "鞋靴": ["鞋靴", "shoes"],
        "shoes": ["shoes", "鞋靴"],
        "食品": ["食品", "food"],
        "food": ["food", "食品"],
        "家居": ["家居", "home"],
        "home": ["home", "家居"],
        "其他": ["其他", "other"],
        "other": ["other", "其他"],
        "综合": ["综合", "general", "通用"],
        "通用": ["通用", "general"],
        "general": ["general", "通用"],
    }
    aliases = alias_map.get(value) or alias_map.get(lowered) or [value]
    return list(dict.fromkeys([str(item).strip() for item in aliases if str(item).strip()]))
