from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PYTHON_AGENT = ROOT / "python_agent"
if str(PYTHON_AGENT) not in sys.path:
    sys.path.insert(0, str(PYTHON_AGENT))

from after_sales_agent.evaluation.controlled_multi_agent_evaluator import (  # noqa: E402
    evaluate_controlled_multi_agent_cases,
    load_controlled_multi_agent_cases,
    render_controlled_multi_agent_markdown,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate recorded controlled multi-agent predictions without business writes."
    )
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output-prefix", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    report = evaluate_controlled_multi_agent_cases(
        load_controlled_multi_agent_cases(args.dataset)
    )
    if args.output_prefix:
        args.output_prefix.with_suffix(".json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        args.output_prefix.with_suffix(".md").write_text(
            render_controlled_multi_agent_markdown(report),
            encoding="utf-8",
        )
    else:
        print(render_controlled_multi_agent_markdown(report))
    return 1 if args.check and not report["quality_gate"]["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
