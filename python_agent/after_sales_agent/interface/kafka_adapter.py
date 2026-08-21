from __future__ import annotations

from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
import json
import logging
import os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socket
import threading
import time
from typing import Any, Protocol
import uuid

from after_sales_agent.config.environment import load_agent_env

load_agent_env()

from after_sales_agent.agent import AfterSalesAgent
from after_sales_agent.infrastructure.agent_metrics import AGENT_RUNTIME_METRICS
from after_sales_agent.infrastructure.review_checkpoint import (
    ReviewCheckpointRuntime,
    build_review_checkpoint_runtime_from_env,
)
from after_sales_agent.infrastructure.request_tracing import (
    TraceRecorder,
    bind_trace_id,
    install_trace_logging_filter,
    normalize_trace_id,
    trace_id_from_seed,
)

logger = logging.getLogger("after_sales_agent.kafka_adapter")


class AfterSalesRuntime(Protocol):
    def start_formal_review(
        self,
        payload: dict[str, Any],
        trace_recorder: Any | None = None,
    ) -> dict[str, Any]:
        ...

    def resume_formal_review(
        self,
        review_id: str,
        resume_signal: dict[str, Any],
        trace_recorder: Any | None = None,
    ) -> dict[str, Any]:
        ...


class ConsumerMetrics:
    """Thread-safe, low-cardinality metrics for the review consumer.

    The consumer is currently single-threaded, but these metrics are protected
    by one lock so the same implementation remains safe when worker
    concurrency is introduced.
    """

    IDEMPOTENCY_OUTCOMES = {
        "claimed", "duplicate_terminal", "duplicate_processing", "stale_takeover",
        "released", "completed", "evidence_required", "manual_required", "failed",
    }
    DLQ_STAGES = {"decode_event", "validate_event", "submit_manual_fallback"}
    REVIEW_OUTCOMES = {"completed", "manual_required", "dlq", "failed"}
    REVIEW_DURATION_BUCKETS_MS = (1000, 5000, 10000, 20000, 30000, 60000, 120000)

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._idempotency = {label: 0 for label in self.IDEMPOTENCY_OUTCOMES}
        self._dlq = {label: 0 for label in self.DLQ_STAGES}
        self._review_outcomes = {label: 0 for label in self.REVIEW_OUTCOMES}
        self._review_duration_count = 0
        self._review_duration_total_ms = 0.0
        self._review_duration_max_ms = 0.0
        self._review_duration_buckets = {
            bucket: 0 for bucket in self.REVIEW_DURATION_BUCKETS_MS
        }
        self._review_inflight = 0

    def record_idempotency(self, outcome: str) -> None:
        self._increment(self._idempotency, outcome)

    def record_dlq(self, stage: str) -> None:
        self._increment(self._dlq, stage)

    def start_review(self) -> float:
        """Mark a claimed review as in-flight and return its monotonic start time."""
        started_at = time.perf_counter()
        with self._lock:
            self._review_inflight += 1
        return started_at

    def finish_review(self, started_at: float, outcome: str) -> None:
        """Record end-to-end consumer processing time for one claimed event."""
        duration_ms = max(0.0, (time.perf_counter() - started_at) * 1000)
        normalized = str(outcome or "failed").strip().lower()
        if normalized not in self.REVIEW_OUTCOMES:
            normalized = "failed"
        with self._lock:
            self._review_inflight = max(0, self._review_inflight - 1)
            self._review_outcomes[normalized] += 1
            self._review_duration_count += 1
            self._review_duration_total_ms += duration_ms
            self._review_duration_max_ms = max(self._review_duration_max_ms, duration_ms)
            for bucket in self.REVIEW_DURATION_BUCKETS_MS:
                if duration_ms <= bucket:
                    self._review_duration_buckets[bucket] += 1
            inflight = self._review_inflight
            total = self._review_outcomes[normalized]
        logger.info(
            "consumer_metric name=review_processing_total outcome=%s value=%s "
            "duration_ms=%.1f inflight=%s",
            normalized,
            total,
            duration_ms,
            inflight,
        )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            count = self._review_duration_count
            return {
                "agent_event_idempotency_total": dict(sorted(self._idempotency.items())),
                "kafka_dlq_total": dict(sorted(self._dlq.items())),
                "review_processing_total": dict(sorted(self._review_outcomes.items())),
                "review_processing_duration_ms": {
                    "count": count,
                    "total": round(self._review_duration_total_ms, 1),
                    "average": round(self._review_duration_total_ms / count, 1) if count else 0.0,
                    "max": round(self._review_duration_max_ms, 1),
                    "buckets": dict(self._review_duration_buckets),
                },
                "review_inflight": self._review_inflight,
            }

    def prometheus_payload(self) -> bytes:
        """Return a small, fixed-label Prometheus exposition payload."""
        snapshot = self.snapshot()
        lines = [
            "# HELP after_sales_review_processing_total Terminal review processing outcomes.",
            "# TYPE after_sales_review_processing_total counter",
        ]
        for outcome, value in snapshot["review_processing_total"].items():
            lines.append(
                f'after_sales_review_processing_total{{outcome="{outcome}"}} {value}'
            )
        duration = snapshot["review_processing_duration_ms"]
        lines.extend(
            [
                "# HELP after_sales_review_processing_duration_ms Review processing duration in milliseconds.",
                "# TYPE after_sales_review_processing_duration_ms histogram",
                f'after_sales_review_processing_duration_ms_sum {duration["total"]}',
                f'after_sales_review_processing_duration_ms_count {duration["count"]}',
                f'after_sales_review_processing_duration_ms_max {duration["max"]}',
                "# HELP after_sales_review_inflight Reviews currently being processed.",
                "# TYPE after_sales_review_inflight gauge",
                f'after_sales_review_inflight {snapshot["review_inflight"]}',
            ]
        )
        for bucket, value in duration["buckets"].items():
            lines.insert(
                -4,
                f'after_sales_review_processing_duration_ms_bucket{{le="{bucket}"}} {value}',
            )
        lines.insert(
            -4,
            'after_sales_review_processing_duration_ms_bucket{le="+Inf"} '
            f'{duration["count"]}',
        )
        return ("\n".join(lines) + "\n").encode("utf-8")

    def _increment(self, counters: dict[str, int], label: str) -> None:
        normalized = str(label or "").strip().lower()
        with self._lock:
            if normalized in counters:
                counters[normalized] += 1
                logger.info(
                    "consumer_metric name=%s label=%s value=%s",
                    "agent_event_idempotency_total" if counters is self._idempotency else "kafka_dlq_total",
                    normalized,
                    counters[normalized],
                )


@dataclass(frozen=True)
class KafkaReviewConsumerConfig:
    bootstrap_servers: str
    request_topic: str
    dlq_topic: str
    group_id: str
    processed_store: Path
    redis_url: str
    idempotency_ttl_seconds: int
    processing_stale_seconds: int
    processing_heartbeat_seconds: int
    submit_retry_attempts: int
    agent_timeout_seconds: int

    @classmethod
    def from_env(cls) -> "KafkaReviewConsumerConfig":
        return cls(
            bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
            request_topic=os.getenv("AFTER_SALES_REVIEW_TOPIC", "after_sales.review.request"),
            dlq_topic=os.getenv("AFTER_SALES_REVIEW_DLQ_TOPIC", "after_sales.review.dlq"),
            group_id=os.getenv("AFTER_SALES_REVIEW_CONSUMER_GROUP", "python-after-sales-agent-review"),
            processed_store=Path(os.getenv("AFTER_SALES_REVIEW_PROCESSED_STORE", ".agent_processed_review_events.jsonl")),
            redis_url=os.getenv("AFTER_SALES_REVIEW_IDEMPOTENCY_REDIS_URL", os.getenv("REDIS_URL", "")),
            idempotency_ttl_seconds=int(os.getenv("AFTER_SALES_REVIEW_IDEMPOTENCY_TTL_SECONDS", "86400")),
            processing_stale_seconds=int(os.getenv("AFTER_SALES_REVIEW_PROCESSING_STALE_SECONDS", "120")),
            processing_heartbeat_seconds=int(os.getenv("AFTER_SALES_REVIEW_PROCESSING_HEARTBEAT_SECONDS", "10")),
            submit_retry_attempts=int(os.getenv("AFTER_SALES_REVIEW_SUBMIT_RETRY_ATTEMPTS", "1")),
            agent_timeout_seconds=int(os.getenv("AFTER_SALES_REVIEW_AGENT_TIMEOUT_SECONDS", "20")),
        )


@dataclass(frozen=True)
class ClaimResult:
    claimed: bool
    status: str | None = None
    should_ack: bool = False
    attempt: int = 0


class EventIdempotencyStore:
    def claim(self, event_id: str) -> ClaimResult:
        raise NotImplementedError

    def refresh_processing(self, event_id: str) -> None:
        raise NotImplementedError

    def mark_completed(self, event_id: str) -> None:
        raise NotImplementedError

    def mark_manual_required(self, event_id: str) -> None:
        raise NotImplementedError

    def mark_evidence_required(self, event_id: str) -> None:
        raise NotImplementedError

    def mark_failed(self, event_id: str) -> None:
        raise NotImplementedError

    def release(self, event_id: str) -> None:
        raise NotImplementedError


class ProcessedEventStore(EventIdempotencyStore):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._processed = self._load()
        self._inflight: set[str] = set()

    def _load(self) -> set[str]:
        if not self.path.is_file():
            return set()
        processed: set[str] = set()
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            event_id = str(item.get("event_id") or "")
            if event_id:
                processed.add(event_id)
        return processed

    def claim(self, event_id: str) -> ClaimResult:
        if event_id in self._processed or event_id in self._inflight:
            return ClaimResult(claimed=False, status="COMPLETED", should_ack=True)
        self._inflight.add(event_id)
        return ClaimResult(claimed=True, status="PROCESSING", attempt=1)

    def refresh_processing(self, event_id: str) -> None:
        return

    def mark_completed(self, event_id: str) -> None:
        if event_id in self._processed:
            return
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"event_id": event_id, "status": "COMPLETED", "processed_at": time.time()}, ensure_ascii=False) + "\n")
        self._processed.add(event_id)
        self._inflight.discard(event_id)

    def mark_manual_required(self, event_id: str) -> None:
        self.mark_completed(event_id)

    def mark_evidence_required(self, event_id: str) -> None:
        self.mark_completed(event_id)

    def mark_failed(self, event_id: str) -> None:
        self.mark_completed(event_id)

    def release(self, event_id: str) -> None:
        self._inflight.discard(event_id)


class RedisEventIdempotencyStore(EventIdempotencyStore):
    TERMINAL_STATUSES = {
        "COMPLETED",
        "EVIDENCE_REQUIRED",
        "MANUAL_REQUIRED",
        "FAILED",
    }

    def __init__(self, redis_url: str, ttl_seconds: int, stale_seconds: int, consumer_id: str) -> None:
        try:
            import redis
        except ImportError as exc:
            raise RuntimeError("redis is required when AFTER_SALES_REVIEW_IDEMPOTENCY_REDIS_URL is configured.") from exc
        self.redis = redis.Redis.from_url(redis_url, decode_responses=True)
        self.redis.ping()
        self.ttl_seconds = max(60, ttl_seconds)
        self.stale_seconds = max(30, stale_seconds)
        self.consumer_id = consumer_id

    def _key(self, event_id: str) -> str:
        return f"agent:event:{event_id}"

    def _now(self) -> float:
        return time.time()

    def _payload(self, status: str, attempt: int = 1) -> str:
        now = self._now()
        return json.dumps(
            {
                "status": status,
                "consumer_id": self.consumer_id,
                "attempt": attempt,
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(now)),
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(now)),
                "updated_at_epoch": now,
            },
            ensure_ascii=False,
        )

    def _read_payload(self, raw: str | None) -> dict[str, Any]:
        if not raw:
            return {}
        if raw in {"processing", "processed"}:
            return {"status": "PROCESSING" if raw == "processing" else "COMPLETED", "attempt": 1}
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return {"status": "UNKNOWN", "attempt": 1}
        return value if isinstance(value, dict) else {"status": "UNKNOWN", "attempt": 1}

    def claim(self, event_id: str) -> ClaimResult:
        key = self._key(event_id)
        if self.redis.set(key, self._payload("PROCESSING", 1), nx=True, ex=self.ttl_seconds):
            return ClaimResult(claimed=True, status="PROCESSING", attempt=1)

        while True:
            raw = self.redis.get(key)
            current = self._read_payload(raw)
            status = str(current.get("status") or "UNKNOWN").upper()
            attempt = int(current.get("attempt") or 1)
            if status in self.TERMINAL_STATUSES:
                return ClaimResult(claimed=False, status=status, should_ack=True, attempt=attempt)
            if status != "PROCESSING":
                return ClaimResult(claimed=False, status=status, should_ack=False, attempt=attempt)

            updated_at = float(current.get("updated_at_epoch") or 0)
            if updated_at > 0 and self._now() - updated_at < self.stale_seconds:
                # PROCESSING is not a durable business outcome. The previous
                # consumer may have died after claiming the event but before
                # Java/MySQL applied the review, so a fresh processing marker
                # must never make us acknowledge the Kafka record.
                return ClaimResult(claimed=False, status=status, should_ack=False, attempt=attempt)

            try:
                with self.redis.pipeline() as pipe:
                    pipe.watch(key)
                    watched = pipe.get(key)
                    if watched != raw:
                        pipe.unwatch()
                        continue
                    pipe.multi()
                    pipe.set(key, self._payload("PROCESSING", attempt + 1), ex=self.ttl_seconds)
                    pipe.execute()
                return ClaimResult(claimed=True, status="PROCESSING", attempt=attempt + 1)
            except Exception:
                logger.exception("Failed to take over stale review event event_id=%s", event_id)
                return ClaimResult(claimed=False, status=status, should_ack=False, attempt=attempt)

    def refresh_processing(self, event_id: str) -> None:
        key = self._key(event_id)
        raw = self.redis.get(key)
        current = self._read_payload(raw)
        if str(current.get("status") or "").upper() != "PROCESSING":
            return
        if current.get("consumer_id") not in {None, self.consumer_id}:
            return
        attempt = int(current.get("attempt") or 1)
        self.redis.set(key, self._payload("PROCESSING", attempt), ex=self.ttl_seconds)

    def mark_completed(self, event_id: str) -> None:
        self.redis.set(self._key(event_id), self._payload("COMPLETED"), ex=self.ttl_seconds)

    def mark_manual_required(self, event_id: str) -> None:
        self.redis.set(self._key(event_id), self._payload("MANUAL_REQUIRED"), ex=self.ttl_seconds)

    def mark_evidence_required(self, event_id: str) -> None:
        self.redis.set(self._key(event_id), self._payload("EVIDENCE_REQUIRED"), ex=self.ttl_seconds)

    def mark_failed(self, event_id: str) -> None:
        self.redis.set(self._key(event_id), self._payload("FAILED"), ex=self.ttl_seconds)

    def release(self, event_id: str) -> None:
        key = self._key(event_id)
        current = self._read_payload(self.redis.get(key))
        if str(current.get("status") or "").upper() == "PROCESSING" and current.get("consumer_id") in {None, self.consumer_id}:
            self.redis.delete(key)


class AfterSalesReviewKafkaConsumer:
    def __init__(
        self,
        config: KafkaReviewConsumerConfig | None = None,
        agent: AfterSalesRuntime | Any | None = None,
        metrics: ConsumerMetrics | None = None,
    ) -> None:
        self.config = config or KafkaReviewConsumerConfig.from_env()
        self.checkpoint_runtime: ReviewCheckpointRuntime | None = None
        if agent is None:
            self.checkpoint_runtime = build_review_checkpoint_runtime_from_env()
            self.agent = AfterSalesAgent(
                checkpointer=self.checkpoint_runtime.saver,
            )
        else:
            self.agent = agent
        self.consumer_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self.metrics = metrics or ConsumerMetrics()
        self.idempotency = self._build_idempotency_store()

    def close(self) -> None:
        if self.checkpoint_runtime is not None:
            self.checkpoint_runtime.close()
            self.checkpoint_runtime = None

    def _build_idempotency_store(self) -> EventIdempotencyStore:
        if self.config.redis_url:
            try:
                return RedisEventIdempotencyStore(
                    self.config.redis_url,
                    self.config.idempotency_ttl_seconds,
                    self.config.processing_stale_seconds,
                    self.consumer_id,
                )
            except Exception:
                logger.exception("Redis idempotency unavailable, falling back to local processed-event store")
        return ProcessedEventStore(self.config.processed_store)

    def _start_processing_heartbeat(self, event_id: str) -> tuple[threading.Event, threading.Thread]:
        stop_event = threading.Event()

        def refresh_loop() -> None:
            interval = max(1, self.config.processing_heartbeat_seconds)
            while not stop_event.wait(interval):
                try:
                    self.idempotency.refresh_processing(event_id)
                except Exception:
                    logger.exception("Failed to refresh review event idempotency TTL event_id=%s", event_id)

        thread = threading.Thread(target=refresh_loop, name=f"review-heartbeat-{event_id[:8]}", daemon=True)
        thread.start()
        return stop_event, thread

    def _defer_processing_message(
        self,
        consumer: Any,
        topic_partition: Any,
        offset: int,
        event_id: str,
    ) -> None:
        """Keep a fresh PROCESSING record pending without advancing its partition."""
        delay_seconds = min(max(float(self.config.processing_heartbeat_seconds) / 2, 0.1), 1.0)
        consumer.pause(topic_partition)
        try:
            consumer.seek(topic_partition, offset)
            logger.info(
                "Review event deferred event_id=%s offset=%s wait_seconds=%s",
                event_id,
                offset,
                delay_seconds,
            )
            time.sleep(delay_seconds)
        finally:
            consumer.resume(topic_partition)

    def run_forever(self) -> None:
        try:
            from kafka import KafkaConsumer, KafkaProducer, TopicPartition
        except ImportError as exc:
            raise RuntimeError("kafka-python is required. Install python_agent requirements first.") from exc

        consumer = KafkaConsumer(
            self.config.request_topic,
            bootstrap_servers=self.config.bootstrap_servers,
            group_id=self.config.group_id,
            enable_auto_commit=False,
            key_deserializer=lambda raw: raw.decode("utf-8") if raw else None,
            auto_offset_reset="earliest",
        )
        producer = KafkaProducer(
            bootstrap_servers=self.config.bootstrap_servers,
            value_serializer=lambda value: json.dumps(value, ensure_ascii=False).encode("utf-8"),
            key_serializer=lambda value: str(value).encode("utf-8") if value is not None else None,
        )
        logger.info("Kafka review consumer started topic=%s group=%s", self.config.request_topic, self.config.group_id)
        for message in consumer:
            try:
                event = self._decode_event(message.value)
            except Exception as exc:
                dlq_event = self._build_dlq_event(
                    event={},
                    error=exc,
                    failed_stage="decode_event",
                    error_type="invalid_message",
                    raw_message=self._safe_raw_message(message.value),
                )
                producer.send(self.config.dlq_topic, key=message.key, value=dlq_event).get(timeout=10)
                self.metrics.record_dlq("decode_event")
                logger.error("review_event event_id= ticket_id= transition=dlq failure_class=decode_event")
                consumer.commit()
                continue

            event_id = str(event.get("event_id") or "")
            if not self._is_valid_event(event):
                dlq_event = self._build_dlq_event(
                    event=event,
                    error=ValueError(
                        "review event requires event_id, review_request_id, ticket_id, user_id and order_id"
                    ),
                    failed_stage="validate_event",
                    error_type="invalid_message",
                )
                producer.send(self.config.dlq_topic, key=event_id or message.key, value=dlq_event).get(timeout=10)
                self.metrics.record_dlq("validate_event")
                logger.error(
                    "review_event event_id=%s ticket_id=%s transition=dlq failure_class=validate_event",
                    event_id,
                    event.get("ticket_id"),
                )
                consumer.commit()
                continue

            trace = self._trace_for_event(event)
            trace_outcome = "unknown"
            review_started_at: float | None = None
            with bind_trace_id(trace.trace_id):
                try:
                    with trace.step("kafka_idempotency_claim") as trace_step:
                        claim = self.idempotency.claim(event_id)
                        trace_step.details.update(
                            {
                                "claimed": claim.claimed,
                                "status": claim.status,
                                "attempt": claim.attempt,
                                "should_ack": claim.should_ack,
                            }
                        )
                    if claim.claimed:
                        self.metrics.record_idempotency(
                            "stale_takeover" if claim.attempt > 1 else "claimed"
                        )
                    else:
                        self.metrics.record_idempotency(
                            "duplicate_terminal"
                            if claim.status in RedisEventIdempotencyStore.TERMINAL_STATUSES
                            else "duplicate_processing"
                        )
                    if not claim.claimed:
                        logger.info(
                            "Review event not claimed event_id=%s status=%s should_ack=%s",
                            event_id,
                            claim.status,
                            claim.should_ack,
                        )
                        if claim.should_ack:
                            with trace.step(
                                "kafka_commit_duplicate",
                                idempotency_status=claim.status,
                            ):
                                consumer.commit()
                            trace_outcome = "duplicate_terminal"
                        elif str(claim.status or "").upper() == "PROCESSING":
                            with trace.step("kafka_defer_processing"):
                                self._defer_processing_message(
                                    consumer,
                                    TopicPartition(message.topic, message.partition),
                                    message.offset,
                                    event_id,
                                )
                            trace_outcome = "duplicate_processing"
                        continue
                    review_started_at = self.metrics.start_review()
                    heartbeat_stop, heartbeat_thread = self._start_processing_heartbeat(event_id)
                    try:
                        result = self._process_event(event, trace)
                        with trace.step("kafka_finalize_review") as trace_step:
                            self._finalize_review_result(event_id, event, result)
                            trace_step.details.update(
                                {
                                    "gate_action": (result.get("raw") or {}).get(
                                        "gate_action"
                                    ),
                                    "submit_outcome": self._review_submit_outcome(result),
                                    "evidence_request_applied": self._evidence_request_applied(
                                        result
                                    ),
                                }
                            )
                        with trace.step("kafka_commit_offset"):
                            consumer.commit()
                        trace_outcome = "completed"
                    except Exception as exc:
                        logger.exception(
                            "Review event failed, trying manual fallback event_id=%s",
                            event_id,
                        )
                        try:
                            with trace.step(
                                "kafka_manual_fallback",
                                error_type=self._classify_error(exc),
                            ) as trace_step:
                                fallback = self._submit_manual_fallback(
                                    event,
                                    self._classify_error(exc),
                                    self._manual_reason(exc),
                                )
                                applied = self._manual_fallback_applied(fallback)
                                trace_step.details["review_applied"] = applied
                                if not applied:
                                    raise RuntimeError(
                                        "manual fallback was not applied by Java/MySQL"
                                    )
                            self.idempotency.mark_manual_required(event_id)
                            self.metrics.record_idempotency("manual_required")
                            with trace.step("kafka_commit_manual_fallback"):
                                consumer.commit()
                            trace_outcome = "manual_required"
                        except Exception as fallback_exc:
                            logger.exception(
                                "Manual fallback failed event_id=%s",
                                event_id,
                            )
                            dlq_event = self._build_dlq_event(
                                event=event,
                                error=fallback_exc,
                                failed_stage="submit_manual_fallback",
                                error_type=self._classify_error(fallback_exc),
                            )
                            with trace.step(
                                "kafka_publish_dlq",
                                failed_stage="submit_manual_fallback",
                            ):
                                producer.send(
                                    self.config.dlq_topic,
                                    key=event_id,
                                    value=dlq_event,
                                ).get(timeout=10)
                            self.metrics.record_dlq("submit_manual_fallback")
                            with trace.step("kafka_mark_failed"):
                                self.idempotency.mark_failed(event_id)
                            self.metrics.record_idempotency("failed")
                            with trace.step("kafka_commit_dlq"):
                                consumer.commit()
                            trace_outcome = "dlq"
                    finally:
                        heartbeat_stop.set()
                        heartbeat_thread.join(timeout=1)
                finally:
                    if review_started_at is not None:
                        self.metrics.finish_review(review_started_at, trace_outcome)
                    self._record_kafka_trace(trace, trace_outcome)

    def _process_event(
        self,
        event: dict[str, Any],
        trace_recorder: TraceRecorder | None = None,
    ) -> dict[str, Any]:
        event_id = str(event["event_id"])
        review_id = self._review_id(event)
        payload = {
            "user_id": str(event.get("user_id") or ""),
            "session_id": event.get("session_id"),
            "ticket_id": str(event.get("ticket_id") or ""),
            "review_request_id": review_id,
            "order_id": str(event.get("order_id") or ""),
            "message": "\u552e\u540e\u7533\u8bf7\u5df2\u63d0\u4ea4\uff0c\u8bf7\u8fdb\u884cAI\u521d\u5ba1\u3002",
            "attachments": [],
            "recent_history": [],
            "client_context": {
                "source": "kafka",
                "event_id": event_id,
                "event_type": event.get("event_type"),
                "ticket_no": event.get("ticket_no"),
            },
        }
        trace = trace_recorder or self._trace_for_event(event)
        with bind_trace_id(trace.trace_id):
            with trace.step(
                "kafka_agent_execution",
                agent_runtime="formal_review_skill",
            ) as trace_step:
                result = self._run_agent_with_timeout(
                    payload,
                    trace,
                    event=event,
                    review_id=review_id,
                )
                trace_step.details.update(
                    {
                        "need_human": bool(result.get("need_human")),
                        "gate_action": (result.get("raw") or {}).get("gate_action"),
                        "failure_reason": (result.get("raw") or {}).get(
                            "failure_reason"
                        ),
                    }
                )
            logger.info(
                "review_event event_id=%s ticket_id=%s transition=agent_processed need_human=%s failure_class=none",
                event_id,
                event.get("ticket_id"),
                result.get("need_human"),
            )
            return result

    @staticmethod
    def _trace_for_event(event: dict[str, Any]) -> TraceRecorder:
        event_id = str(event.get("event_id") or "")
        event_trace_id = str(event.get("trace_id") or "")
        trace = TraceRecorder(
            request_type="kafka_review",
            trace_id=(
                normalize_trace_id(event_trace_id)
                if event_trace_id
                else trace_id_from_seed(event_id)
            ),
        )
        trace.set_meta(
            event_id=event_id,
            ticket_id=str(event.get("ticket_id") or ""),
            order_id=str(event.get("order_id") or ""),
        )
        return trace

    @staticmethod
    def _record_kafka_trace(trace: TraceRecorder, outcome: str) -> None:
        trace.set_meta(outcome=outcome)
        serialized = trace.to_dict()
        AGENT_RUNTIME_METRICS.record_trace("/kafka/review", serialized)
        logger.info(
            "review_trace=%s",
            json.dumps(
                serialized,
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            ),
        )

    def _run_agent_with_timeout(
        self,
        payload: dict[str, Any],
        trace_recorder: TraceRecorder | None = None,
        *,
        event: dict[str, Any],
        review_id: str,
    ) -> dict[str, Any]:
        timeout = max(1, self.config.agent_timeout_seconds)
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ai-review-agent")
        if self._is_resume_event(event):
            resume = getattr(self.agent, "resume_formal_review", None)
            callable_resume = (
                resume if callable(resume) else getattr(self.agent, "resume")
            )
            future = executor.submit(
                callable_resume,
                review_id,
                {
                    "event_id": str(event.get("event_id") or ""),
                    "evidence_revision": self._evidence_revision(event),
                },
                trace_recorder,
            )
        else:
            start = getattr(self.agent, "start_formal_review", None)
            if not callable(start):
                start = getattr(self.agent, "start", None)
            callable_start = (
                start if callable(start) else getattr(self.agent, "handle")
            )
            future = executor.submit(callable_start, payload, trace_recorder)
        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError as exc:
            future.cancel()
            raise TimeoutError(f"AI review agent exceeded {timeout}s") from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _submit_manual_fallback(self, event: dict[str, Any], error_type: str, reason: str) -> Any:
        payload = {
            "userId": event.get("user_id"),
            "sessionId": event.get("session_id"),
            "ticketId": event.get("ticket_id"),
            "orderId": event.get("order_id"),
            "reviewRequestId": event.get("review_request_id"),
            # Java's SubmitAiReviewRequest field is evidenceRevision.  The
            # previous expectedEvidenceRevision name was silently ignored by
            # Jackson and made every fallback request fail validation.
            "evidenceRevision": self._evidence_revision(event),
            "verdict": "MANUAL_REVIEW_REQUIRED",
            "aiReviewConfidence": 0,
            "reason": reason,
            "evidenceNeeded": [],
            "visualUncertain": True,
            "policyUncertain": True,
            "evidenceConsistent": False,
            "visualConfidence": 0,
            "riskReviewReasons": [error_type],
            "policyCitations": [],
            "imageReview": None,
        }
        last_error: Exception | None = None
        from after_sales_agent.integrations.java_tool_client import JavaToolClient

        java = JavaToolClient()
        for _ in range(max(1, self.config.submit_retry_attempts + 1)):
            try:
                return java.post("/aftersales/review", payload)
            except Exception as exc:
                last_error = exc
        raise RuntimeError(f"submit manual fallback failed: {last_error}") from last_error

    @staticmethod
    def _decode_event(raw: bytes) -> dict[str, Any]:
        event = json.loads(raw.decode("utf-8"))
        if not isinstance(event, dict):
            raise ValueError("review event must be a JSON object")
        return event

    @staticmethod
    def _is_valid_event(event: dict[str, Any]) -> bool:
        required = (
            "event_id",
            "review_request_id",
            "ticket_id",
            "user_id",
            "order_id",
        )
        if not all(str(event.get(key) or "").strip() for key in required):
            return False
        return not (
            AfterSalesReviewKafkaConsumer._is_resume_event(event)
            and AfterSalesReviewKafkaConsumer._evidence_revision(event) < 1
        )

    @staticmethod
    def _review_id(event: dict[str, Any]) -> str:
        review_id = str(event.get("review_request_id") or "").strip()
        if not review_id:
            raise ValueError("review event requires review_request_id")
        return review_id

    @staticmethod
    def _is_resume_event(event: dict[str, Any]) -> bool:
        event_type = str(
            event.get("event_type") or event.get("command") or event.get("action") or ""
        ).strip().upper()
        return "RESUME" in event_type

    @staticmethod
    def _evidence_revision(event: dict[str, Any]) -> int:
        try:
            return max(0, int(event.get("evidence_revision") or 0))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _has_successful_review_submit(result: dict[str, Any]) -> bool:
        return AfterSalesReviewKafkaConsumer._review_submit_outcome(result) == "APPLIED"

    @staticmethod
    def _review_submit_outcome(result: dict[str, Any]) -> str:
        for item in result.get("tool_trace") or []:
            if item.get("tool") != "submit_ai_review" or not item.get("ok"):
                continue
            data = item.get("data")
            if not isinstance(data, dict):
                continue
            if data.get("review_applied") is True:
                return "APPLIED"
            reason = str(data.get("review_reject_reason") or "").strip().upper()
            if reason in {"STALE_REVIEW", "STATUS_CHANGED"}:
                return reason
        return "NOT_APPLIED"

    def _finalize_review_result(self, event_id: str, event: dict[str, Any], result: dict[str, Any]) -> None:
        if self._evidence_request_applied(result):
            self.idempotency.mark_evidence_required(event_id)
            self.metrics.record_idempotency("evidence_required")
            return
        if self._is_paused(result):
            self.idempotency.mark_completed(event_id)
            self.metrics.record_idempotency("completed")
            return
        outcome = self._review_submit_outcome(result)
        if outcome == "APPLIED":
            self._mark_review_terminal_status(event_id, result)
            return
        if outcome in {"STALE_REVIEW", "STATUS_CHANGED"}:
            # Java/MySQL is authoritative: a stale result or an already changed
            # status must neither overwrite the ticket nor become a Redis success.
            logger.info("AI review result not applied event_id=%s outcome=%s", event_id, outcome)
            self.idempotency.release(event_id)
            self.metrics.record_idempotency("released")
            return

        fallback = self._submit_manual_fallback(
            event,
            "agent_no_reliable_review_result",
            "AI未能形成可靠自动审核结论，已转人工审核。",
        )
        if not self._manual_fallback_applied(fallback):
            raise RuntimeError("manual fallback was not applied by Java/MySQL")
        self.idempotency.mark_manual_required(event_id)
        self.metrics.record_idempotency("manual_required")

    @staticmethod
    def _evidence_request_applied(result: dict[str, Any]) -> bool:
        raw = result.get("raw") if isinstance(result.get("raw"), dict) else {}
        if str(raw.get("gate_action") or "").upper() != "REQUEST_EVIDENCE":
            return False
        for item in result.get("tool_trace") or []:
            if (
                isinstance(item, dict)
                and item.get("tool") == "request_missing_evidence"
                and item.get("ok") is True
                and isinstance(item.get("data"), dict)
                and (
                    item["data"].get("message_id")
                    or item["data"].get("messageId")
                )
            ):
                return True
        return False

    @staticmethod
    def _is_paused(result: dict[str, Any]) -> bool:
        raw = result.get("raw") if isinstance(result.get("raw"), dict) else {}
        return raw.get("paused") is True

    @staticmethod
    def _manual_fallback_applied(response: Any) -> bool:
        return isinstance(response, dict) and response.get("reviewApplied") is True

    def _mark_review_terminal_status(self, event_id: str, result: dict[str, Any]) -> None:
        for item in result.get("tool_trace") or []:
            if item.get("tool") != "submit_ai_review" or not item.get("ok"):
                continue
            arguments = item.get("arguments") or item.get("args") or {}
            verdict = str(arguments.get("verdict") or "").upper()
            if verdict in {"MANUAL_REVIEW_REQUIRED", "MANUAL_REVIEW"}:
                self.idempotency.mark_manual_required(event_id)
                self.metrics.record_idempotency("manual_required")
                return
        self.idempotency.mark_completed(event_id)
        self.metrics.record_idempotency("completed")

    @staticmethod
    def _classify_error(exc: Exception) -> str:
        text = f"{exc.__class__.__name__}: {exc}".lower()
        if "timeout" in text or "timed out" in text:
            return "timeout"
        if "connection refused" in text:
            return "connection_refused"
        if "connection reset" in text:
            return "connection_reset"
        if "502" in text:
            return "http_502"
        if "503" in text:
            return "http_503"
        if "400" in text or "validation" in text:
            return "validation"
        if "401" in text or "403" in text or "permission" in text:
            return "permission"
        if "404" in text or "not found" in text:
            return "not_found"
        if "429" in text:
            return "rate_limited"
        return "ai_review_failed"

    @staticmethod
    def _manual_reason(exc: Exception) -> str:
        error_type = AfterSalesReviewKafkaConsumer._classify_error(exc)
        reason_map = {
            "timeout": "AI初审服务响应超时，已转人工审核，不影响售后申请继续处理。",
            "connection_refused": "AI初审依赖服务暂时不可用，已转人工审核。",
            "connection_reset": "AI初审网络连接异常，已转人工审核。",
            "http_502": "AI初审依赖服务暂时异常，已转人工审核。",
            "http_503": "AI初审依赖服务暂时不可用，已转人工审核。",
            "validation": "AI初审所需信息不完整或格式异常，已转人工审核。",
            "permission": "AI初审无法完成权限校验，已转人工审核。",
            "not_found": "AI初审无法匹配到必要业务数据，已转人工审核。",
            "rate_limited": "AI初审服务繁忙，已转人工审核。",
        }
        return reason_map.get(error_type, "AI初审未能形成可靠自动审核结论，已转人工审核。")

    @staticmethod
    def _build_dlq_event(
        *,
        event: dict[str, Any],
        error: Exception,
        failed_stage: str,
        error_type: str,
        raw_message: str | None = None,
    ) -> dict[str, Any]:
        event_id = str(event.get("event_id") or "")
        return {
            "event_id": event_id,
            "review_request_id": str(event.get("review_request_id") or ""),
            "trace_id": str(event.get("trace_id") or ""),
            "ticket_id": str(event.get("ticket_id") or ""),
            "error_type": error_type,
            "error_code": error.__class__.__name__,
            "error_message": AfterSalesReviewKafkaConsumer._sanitize_error(str(error)),
            "failed_stage": failed_stage,
            "original_created_at": event.get("created_at"),
            "failed_time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "raw_message": raw_message,
        }

    @staticmethod
    def _sanitize_error(message: str) -> str:
        return str(message or "").replace("\r", " ").replace("\n", " ")[:500]

    @staticmethod
    def _safe_raw_message(raw: bytes) -> str:
        return raw.decode("utf-8", errors="replace")[:500]


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] trace=%(trace_id)s %(name)s - %(message)s",
    )
    install_trace_logging_filter()
    logging.getLogger("kafka").setLevel(
        os.getenv("KAFKA_CLIENT_LOG_LEVEL", "WARNING")
    )
    consumer = AfterSalesReviewKafkaConsumer()
    metrics_server = _start_metrics_server(consumer.metrics)
    try:
        consumer.run_forever()
    finally:
        metrics_server.shutdown()
        consumer.close()


def _start_metrics_server(metrics: ConsumerMetrics) -> ThreadingHTTPServer:
    port = max(0, int(os.getenv("AFTER_SALES_REVIEW_METRICS_PORT", "8001")))

    class MetricsHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            if self.path != "/metrics":
                self.send_error(404)
                return
            payload = metrics.prometheus_payload()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = ThreadingHTTPServer(("0.0.0.0", port), MetricsHandler)
    thread = threading.Thread(
        target=server.serve_forever,
        name="review-consumer-metrics",
        daemon=True,
    )
    thread.start()
    logger.info("Review consumer metrics server started port=%s", server.server_port)
    return server


if __name__ == "__main__":
    main()
