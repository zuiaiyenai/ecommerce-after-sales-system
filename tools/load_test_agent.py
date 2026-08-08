"""Small dependency-free HTTP load test for the Agent gateway.

Default target is the safe health endpoint. To test chat, supply a JWT and a
JSON request body that uses a non-production test user/order.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import statistics
import time
from collections import Counter
from pathlib import Path
from typing import Any
from urllib import error, request


def percentile(values: list[float], percent: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent / 100
    lower, upper = int(position), min(int(position) + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def parse_json(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
        return value if isinstance(value, dict) else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}


def classify_response(status: int, body: dict[str, Any]) -> tuple[str, str]:
    if status < 200 or status >= 300:
        return "http_error", str(body.get("code") or status)
    if body.get("success") is False:
        return "application_error", str(body.get("code") or "unknown")

    data = body.get("data") if isinstance(body.get("data"), dict) else body
    raw = data.get("raw") if isinstance(data.get("raw"), dict) else {}
    trace = data.get("trace") if isinstance(data.get("trace"), dict) else {}
    if raw.get("fallback") is True or trace.get("fallback") is True:
        reason = raw.get("agent_error_code") or raw.get("fallback_reason") or trace.get("fallback_reason")
        return "fallback", str(reason or "unknown")
    tool_trace = data.get("tool_trace") if isinstance(data.get("tool_trace"), list) else []
    failed_tools = sorted({
        str(item.get("tool") or "unknown")
        for item in tool_trace
        if isinstance(item, dict) and item.get("ok") is False
    })
    if failed_tools:
        return "tool_failure", ",".join(failed_tools)
    return "success", ""


def send_one(url: str, method: str, payload: bytes | None, token: str, timeout: float) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    started = time.perf_counter()
    try:
        req = request.Request(url, data=payload, headers=headers, method=method)
        with request.urlopen(req, timeout=timeout) as response:
            body = parse_json(response.read())
            outcome, reason = classify_response(response.status, body)
            return {
                "status": response.status,
                "latency_ms": (time.perf_counter() - started) * 1000,
                "outcome": outcome,
                "reason": reason,
            }
    except error.HTTPError as exc:
        body = parse_json(exc.read())
        outcome, reason = classify_response(exc.code, body)
        return {
            "status": exc.code,
            "latency_ms": (time.perf_counter() - started) * 1000,
            "outcome": outcome,
            "reason": reason,
        }
    except Exception as exc:
        return {
            "status": 0,
            "latency_ms": (time.perf_counter() - started) * 1000,
            "outcome": "transport_error",
            "reason": exc.__class__.__name__,
        }


def latency_summary(values: list[float]) -> dict[str, float]:
    if not values:
        return {"avg": 0, "p50": 0, "p95": 0, "p99": 0, "max": 0}
    return {
        "avg": round(statistics.mean(values), 2),
        "p50": round(percentile(values, 50), 2),
        "p95": round(percentile(values, 95), 2),
        "p99": round(percentile(values, 99), 2),
        "max": round(max(values), 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Load test the ecommerce Agent gateway")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--endpoint", default="/api/agent/health")
    parser.add_argument("--requests", type=int, default=50)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=95)
    parser.add_argument("--token", default="", help="JWT required for protected Agent endpoints")
    parser.add_argument("--body-file", help="JSON object or object array; supplying it changes the request to POST")
    parser.add_argument("--warmup", type=int, default=0, help="sequential warm-up requests excluded from metrics")
    parser.add_argument("--output", help="optional JSON report path")
    args = parser.parse_args()

    if args.requests < 1 or args.concurrency < 1 or args.warmup < 0:
        parser.error("--requests and --concurrency must be positive; --warmup cannot be negative")
    payloads: list[bytes | None] = [None]
    method = "GET"
    if args.body_file:
        source = json.loads(Path(args.body_file).read_text(encoding="utf-8"))
        scenarios = source if isinstance(source, list) else [source]
        if not scenarios or not all(isinstance(item, dict) for item in scenarios):
            parser.error("--body-file must contain a JSON object or a non-empty array of objects")
        payloads = [json.dumps(item, ensure_ascii=False).encode("utf-8") for item in scenarios]
        method = "POST"
    url = args.base_url.rstrip("/") + "/" + args.endpoint.lstrip("/")
    print(
        f"target={url} method={method} requests={args.requests} concurrency={args.concurrency} "
        f"warmup={args.warmup} scenarios={len(payloads)}"
    )

    for index in range(args.warmup):
        send_one(url, method, payloads[index % len(payloads)], args.token, args.timeout)

    statuses: Counter[int] = Counter()
    outcomes: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    latencies: list[float] = []
    business_success_latencies: list[float] = []
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [
            executor.submit(send_one, url, method, payloads[index % len(payloads)], args.token, args.timeout)
            for index in range(args.requests)
        ]
        for future in as_completed(futures):
            result = future.result()
            status = int(result["status"])
            latency = float(result["latency_ms"])
            outcome = str(result["outcome"])
            reason = str(result["reason"])
            statuses[status] += 1
            outcomes[outcome] += 1
            if reason:
                reasons[f"{outcome}:{reason}"] += 1
            latencies.append(latency)
            if outcome == "success":
                business_success_latencies.append(latency)
    elapsed = time.perf_counter() - started
    http_successes = sum(count for status, count in statuses.items() if 200 <= status < 300)
    business_successes = outcomes["success"]
    report = {
        "elapsed_seconds": round(elapsed, 3),
        "throughput_rps": round(args.requests / elapsed, 2) if elapsed else 0,
        "http_success_rate": round(http_successes / args.requests, 4),
        "business_success_rate": round(business_successes / args.requests, 4),
        "fallback_rate": round(outcomes["fallback"] / args.requests, 4),
        "tool_failure_rate": round(outcomes["tool_failure"] / args.requests, 4),
        "status_counts": dict(sorted(statuses.items())),
        "outcome_counts": dict(sorted(outcomes.items())),
        "reason_counts": dict(sorted(reasons.items())),
        "latency_ms": latency_summary(latencies),
        "business_success_latency_ms": latency_summary(business_success_latencies),
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
