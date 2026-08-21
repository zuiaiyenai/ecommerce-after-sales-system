"""Reproducible real-model benchmark for the repository's after-sales images."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import statistics
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python_agent"))

from after_sales_agent.config.environment import load_agent_env  # noqa: E402
from after_sales_agent.domain.models import Attachment  # noqa: E402
from after_sales_agent.providers.vision_review_service import VisionReviewService  # noqa: E402


def percentile(values: list[float], percent: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    position = (len(values) - 1) * percent / 100
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def dataset() -> list[dict[str, Any]]:
    evidence_root = next(
        path for path in ROOT.iterdir()
        if path.is_dir() and (path / "01_商品破损照片").is_dir()
    )
    groups = [
        ("visible_damage", evidence_root / "01_商品破损照片", True, False),
        ("functional_issue", evidence_root / "90_需视频或描述补充", False, True),
        ("hard_damage", evidence_root / "91_模型识别不稳定", True, True),
        ("imported_damage", evidence_root / "_import_tmp", True, False),
        ("catalog_normal", ROOT / "image", False, False),
    ]
    rows: list[dict[str, Any]] = []
    for group, folder, expected, hard in groups:
        for path in sorted(folder.rglob("*.png")):
            rows.append({
                "path": path,
                "file": str(path.relative_to(ROOT)),
                "group": group,
                "expected_damage": expected,
                "hard_sample": hard,
            })
    return rows


def metrics(rows: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
    successful = [row for row in rows if row.get("success")]
    predicted = [
        bool(row.get("predicted_damage")) and float(row.get("damage_confidence") or 0) >= threshold
        for row in successful
    ]
    expected = [bool(row["expected_damage"]) for row in successful]
    tp = sum(p and e for p, e in zip(predicted, expected))
    fp = sum(p and not e for p, e in zip(predicted, expected))
    fn = sum(not p and e for p, e in zip(predicted, expected))
    tn = sum(not p and not e for p, e in zip(predicted, expected))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    latencies = [float(row["latency_ms"]) for row in successful]
    return {
        "threshold": threshold,
        "samples": len(rows),
        "successful": len(successful),
        "failures": len(rows) - len(successful),
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0,
        "false_positive_rate": round(fp / (fp + tn), 4) if fp + tn else 0.0,
        "latency_ms": {
            "average": round(statistics.mean(latencies), 2) if latencies else 0.0,
            "p50": round(percentile(latencies, 50), 2),
            "p95": round(percentile(latencies, 95), 2),
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    best = report["metrics"]
    lines = [
        "# 售后视觉模型离线评测报告", "",
        f"- 模型：`{report['model']}`",
        f"- 样本：{best['samples']} 张（成功 {best['successful']}，失败 {best['failures']}）",
        f"- 自动审批破损阈值：{best['threshold']}",
        f"- Precision：{best['precision']:.2%}",
        f"- Recall：{best['recall']:.2%}",
        f"- F1：{best['f1']:.2%}",
        f"- 正常/功能问题误通过率：{best['false_positive_rate']:.2%}",
        f"- 延迟：平均 {best['latency_ms']['average']:.0f} ms，P50 {best['latency_ms']['p50']:.0f} ms，P95 {best['latency_ms']['p95']:.0f} ms", "",
        "## 混淆矩阵", "",
        "| TP | FP | FN | TN |", "|---:|---:|---:|---:|",
        f"| {best['tp']} | {best['fp']} | {best['fn']} | {best['tn']} |", "",
        "## 阈值对比", "",
        "| 阈值 | Precision | Recall | F1 | 误通过率 |", "|---:|---:|---:|---:|---:|",
    ]
    for item in report["thresholds"]:
        lines.append(f"| {item['threshold']} | {item['precision']:.2%} | {item['recall']:.2%} | {item['f1']:.2%} | {item['false_positive_rate']:.2%} |")
    errors = [row for row in report["results"] if not row.get("success") or row["expected_damage"] != (row.get("predicted_damage") and row.get("damage_confidence", 0) >= best["threshold"])]
    lines.extend(["", "## 错误样本", ""])
    if not errors:
        lines.append("本轮没有错误样本。")
    else:
        for row in errors:
            lines.append(f"- `{row['file']}`：expected={row['expected_damage']} predicted={row.get('predicted_damage')} damage_confidence={row.get('damage_confidence')} error={row.get('error', '')}")
    lines.extend(["", "> 该数据集来自仓库现有演示图片，不等同于线上真实流量；简历应同时标注样本规模。", ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", type=float, default=0.85)
    parser.add_argument("--output", default=str(ROOT / "docs" / "视觉模型离线评测报告"))
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    load_agent_env()
    service = VisionReviewService()
    service._cache.clear()
    samples = dataset()[: args.limit or None]
    rows: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    for index, sample in enumerate(samples, 1):
        path: Path = sample.pop("path")
        content = path.read_bytes()
        content_hash = hashlib.sha256(content).hexdigest()
        expected_cache_hit = content_hash in seen_hashes
        seen_hashes.add(content_hash)
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        source = f"data:{mime};base64," + base64.b64encode(content).decode("ascii")
        started = time.perf_counter()
        result = service.review_attachments((Attachment(kind="image", name=path.name, source=source),))
        item = result.items[0] if result.items else None
        row = {
            **sample,
            "sha256": content_hash,
            "expected_cache_hit": expected_cache_hit,
            "success": result.success,
            "predicted_damage": result.has_damage_area,
            "confidence": item.confidence if item else 0.0,
            "damage_confidence": item.damage_confidence if item else 0.0,
            "image_type": item.image_type if item else "",
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "error": str(result.raw.get("error") or "") if isinstance(result.raw, dict) else "",
        }
        rows.append(row)
        print(f"[{index}/{len(samples)}] {row['group']} damage={row['predicted_damage']} p={row['damage_confidence']} {row['latency_ms']}ms", flush=True)
    thresholds = [metrics(rows, value) for value in (0.70, 0.75, 0.80, 0.85, 0.90, 0.95)]
    report = {
        "model": service.client.config.model,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "metrics": metrics(rows, args.threshold),
        "thresholds": thresholds,
        "results": rows,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    output.with_suffix(".md").write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
