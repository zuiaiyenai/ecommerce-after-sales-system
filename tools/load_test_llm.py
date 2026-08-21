from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import statistics
import sys
from time import perf_counter


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python_agent"))


def load_env() -> None:
    for raw in (ROOT / "python_agent" / ".env").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * fraction))]


def main() -> None:
    parser = argparse.ArgumentParser(description="Cost-bounded real LLM concurrency smoke test")
    parser.add_argument("--real", action="store_true", help="required acknowledgement that this consumes real API quota")
    parser.add_argument("--levels", default="1,3,5,10,20")
    parser.add_argument("--max-requests", type=int, default=40)
    parser.add_argument("--max-tokens", type=int, default=24)
    args = parser.parse_args()
    if not args.real:
        raise SystemExit("Refusing to call a real API without --real")
    levels = [int(value) for value in args.levels.split(",")]
    if sum(levels) > args.max_requests:
        raise SystemExit("Requested load exceeds --max-requests cost guard")
    load_env()
    from after_sales_agent.providers.llm_client import OpenAICompatibleConfig, OpenAICompatibleClient

    client = OpenAICompatibleClient(OpenAICompatibleConfig.from_env())
    report = []
    try:
        for concurrency in levels:
            def call(index: int) -> dict[str, object]:
                started = perf_counter()
                try:
                    response = client.chat(
                        [{"role": "user", "content": f"Reply only OK. request={concurrency}-{index}"}],
                        temperature=0,
                        max_tokens=args.max_tokens,
                    )
                    return {"ok": bool(response.get("choices")), "latency_ms": (perf_counter() - started) * 1000}
                except Exception as exc:
                    return {"ok": False, "latency_ms": (perf_counter() - started) * 1000, "error": exc.__class__.__name__}

            started = perf_counter()
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                results = [future.result() for future in as_completed(executor.submit(call, index) for index in range(concurrency))]
            latencies = [float(item["latency_ms"]) for item in results]
            errors: dict[str, int] = {}
            for item in results:
                if not item["ok"]:
                    name = str(item.get("error") or "unknown")
                    errors[name] = errors.get(name, 0) + 1
            report.append({
                "concurrency": concurrency,
                "requests": len(results),
                "success_rate": round(sum(bool(item["ok"]) for item in results) / len(results), 4),
                "average_ms": round(statistics.mean(latencies), 1),
                "p95_ms": round(percentile(latencies, 0.95), 1),
                "wall_ms": round((perf_counter() - started) * 1000, 1),
                "errors": errors,
            })
    finally:
        client.close()
    print(json.dumps({"provider": "remote", "model": os.getenv("LLM_MODEL"), "max_tokens": args.max_tokens, "results": report}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
