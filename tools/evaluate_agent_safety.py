"""Run the deterministic Agent safety regression suite without external services."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python_agent"))

from after_sales_agent.evaluation import evaluate_cases, load_cases, render_markdown  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset",
        type=Path,
        default=ROOT / "python_agent" / "evaluation" / "agent_safety_cases.jsonl",
    )
    parser.add_argument("--output-prefix", type=Path)
    parser.add_argument("--check", action="store_true", help="Exit non-zero when a quality gate fails.")
    args = parser.parse_args()

    report = evaluate_cases(load_cases(args.dataset))
    if args.output_prefix:
        args.output_prefix.parent.mkdir(parents=True, exist_ok=True)
        args.output_prefix.with_suffix(".json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        args.output_prefix.with_suffix(".md").write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, ensure_ascii=False, indent=2))
    return 1 if args.check and not report["quality_gate_passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
