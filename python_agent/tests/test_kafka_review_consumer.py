from __future__ import annotations

from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import pytest

from after_sales_agent.api.kafka_review_consumer import (
    AfterSalesReviewKafkaConsumer,
    ClaimResult,
    ConsumerMetrics,
    KafkaReviewConsumerConfig,
)


class FakeAgent:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result or {"tool_trace": [{"tool": "submit_ai_review", "ok": True, "data": {"review_applied": True}}]}
        self.error = error
        self.payloads = []

    def handle(self, payload):
        self.payloads.append(payload)
        if self.error:
            raise self.error
        return self.result


class FakeJavaToolClient:
    posts = []
    failures_before_success = 0

    def post(self, path, payload):
        self.__class__.posts.append((path, payload))
        if self.__class__.failures_before_success > 0:
            self.__class__.failures_before_success -= 1
            raise RuntimeError("HTTP 503 unavailable")
        return {"reviewApplied": True, "reviewRequestId": payload["reviewRequestId"]}


def config() -> KafkaReviewConsumerConfig:
    return KafkaReviewConsumerConfig(
        bootstrap_servers="localhost:9092",
        request_topic="after_sales.review.request",
        dlq_topic="after_sales.review.dlq",
        group_id="test-group",
        processed_store=Path(tempfile.gettempdir()) / "agent-review-test.jsonl",
        redis_url="",
        idempotency_ttl_seconds=60,
        processing_stale_seconds=120,
        processing_heartbeat_seconds=10,
        submit_retry_attempts=1,
        agent_timeout_seconds=20,
    )


class KafkaReviewConsumerTest(unittest.TestCase):
    def setUp(self) -> None:
        FakeJavaToolClient.posts = []
        FakeJavaToolClient.failures_before_success = 0

    def test_config_has_no_retry_topic(self) -> None:
        cfg = config()

        self.assertEqual("after_sales.review.request", cfg.request_topic)
        self.assertEqual("after_sales.review.dlq", cfg.dlq_topic)
        self.assertFalse(hasattr(cfg, "retry_topic"))

    def test_agent_failure_submits_manual_fallback_with_same_review_request_id(self) -> None:
        consumer = AfterSalesReviewKafkaConsumer(config(), agent=FakeAgent(error=TimeoutError("LLM timed out")))
        event = {
            "event_id": "evt-1",
            "ticket_id": "10001",
            "user_id": "20001",
            "order_id": "30001",
            "created_at": "2026-07-13T10:00:00+08:00",
        }

        with patch("after_sales_agent.integrations.java_tool_client.JavaToolClient", FakeJavaToolClient):
            result = consumer._submit_manual_fallback(event, "timeout", "AI timeout")

        self.assertTrue(result["reviewApplied"])
        path, payload = FakeJavaToolClient.posts[0]
        self.assertEqual("/aftersales/review", path)
        self.assertEqual("evt-1", payload["reviewRequestId"])
        self.assertEqual("MANUAL_REVIEW_REQUIRED", payload["verdict"])
        self.assertEqual("10001", payload["ticketId"])
        self.assertEqual("30001", payload["orderId"])

    def test_order_number_does_not_replace_required_order_id(self) -> None:
        event = {
            "event_id": "evt-order-contract",
            "ticket_id": "10001",
            "user_id": "20001",
            "order_no": "ORDER-30001",
        }

        self.assertFalse(AfterSalesReviewKafkaConsumer._is_valid_event(event))

    def test_missing_required_fields_goes_to_invalid_message_dlq_shape(self) -> None:
        event = {"event_id": "evt-2", "ticket_id": "10001"}

        self.assertFalse(AfterSalesReviewKafkaConsumer._is_valid_event(event))
        dlq = AfterSalesReviewKafkaConsumer._build_dlq_event(
            event=event,
            error=ValueError("review event requires event_id, ticket_id, user_id and order_id"),
            failed_stage="validate_event",
            error_type="invalid_message",
        )

        self.assertEqual("evt-2", dlq["event_id"])
        self.assertEqual("evt-2", dlq["review_request_id"])
        self.assertEqual("10001", dlq["ticket_id"])
        self.assertEqual("validate_event", dlq["failed_stage"])
        self.assertNotIn("\n", dlq["error_message"])

    @pytest.mark.smoke
    def test_review_applied_true_is_the_only_successful_submit(self) -> None:
        result = {"tool_trace": [{"tool": "submit_ai_review", "ok": True, "data": {"review_applied": True}}]}

        self.assertTrue(AfterSalesReviewKafkaConsumer._has_successful_review_submit(result))
        self.assertEqual("APPLIED", AfterSalesReviewKafkaConsumer._review_submit_outcome(result))

    def test_manual_required_without_application_uses_java_manual_fallback(self) -> None:
        consumer = AfterSalesReviewKafkaConsumer(config(), agent=FakeAgent())
        consumer.idempotency = Mock()
        event = {"event_id": "evt-3", "ticket_id": "10001", "user_id": "20001", "order_id": "30001"}
        result = {
            "tool_trace": [{
                "tool": "submit_ai_review",
                "ok": True,
                "data": {"review_applied": False, "review_reject_reason": "MANUAL_REQUIRED"},
            }]
        }

        with patch.object(consumer, "_submit_manual_fallback", return_value={"reviewApplied": True}) as fallback:
            consumer._finalize_review_result("evt-3", event, result)

        fallback.assert_called_once()
        consumer.idempotency.mark_manual_required.assert_called_once_with("evt-3")
        consumer.idempotency.mark_completed.assert_not_called()

    def test_evidence_request_is_a_terminal_success_without_manual_fallback(self) -> None:
        consumer = AfterSalesReviewKafkaConsumer(config(), agent=FakeAgent())
        consumer.idempotency = Mock()
        event = {
            "event_id": "evt-evidence",
            "ticket_id": "10001",
            "user_id": "20001",
            "order_id": "30001",
        }
        result = {
            "tool_trace": [
                {
                    "tool": "request_missing_evidence",
                    "ok": True,
                    "data": {"message_id": "40001", "session_id": "50001"},
                }
            ],
            "raw": {"gate_action": "REQUEST_EVIDENCE"},
        }

        with patch.object(consumer, "_submit_manual_fallback") as fallback:
            consumer._finalize_review_result("evt-evidence", event, result)

        fallback.assert_not_called()
        consumer.idempotency.mark_evidence_required.assert_called_once_with(
            "evt-evidence"
        )
        consumer.idempotency.mark_manual_required.assert_not_called()

    @pytest.mark.smoke
    def test_status_changed_does_not_repeat_manual_handoff_or_mark_redis_success(self) -> None:
        consumer = AfterSalesReviewKafkaConsumer(config(), agent=FakeAgent())
        consumer.idempotency = Mock()
        event = {"event_id": "evt-4", "ticket_id": "10001", "user_id": "20001", "order_id": "30001"}
        result = {
            "tool_trace": [{
                "tool": "submit_ai_review",
                "ok": True,
                "data": {"review_applied": False, "review_reject_reason": "STATUS_CHANGED"},
            }]
        }

        with patch.object(consumer, "_submit_manual_fallback") as fallback:
            consumer._finalize_review_result("evt-4", event, result)

        fallback.assert_not_called()
        consumer.idempotency.release.assert_called_once_with("evt-4")
        consumer.idempotency.mark_completed.assert_not_called()
        consumer.idempotency.mark_manual_required.assert_not_called()

    def test_redis_manual_state_is_not_written_before_java_applies_fallback(self) -> None:
        consumer = AfterSalesReviewKafkaConsumer(config(), agent=FakeAgent())
        consumer.idempotency = Mock()
        event = {"event_id": "evt-5", "ticket_id": "10001", "user_id": "20001", "order_id": "30001"}
        result = {"tool_trace": [{"tool": "submit_ai_review", "ok": True, "data": {"review_applied": False}}]}

        with patch.object(consumer, "_submit_manual_fallback", return_value={"reviewApplied": False}):
            with self.assertRaisesRegex(RuntimeError, "not applied"):
                consumer._finalize_review_result("evt-5", event, result)

        consumer.idempotency.mark_manual_required.assert_not_called()
        consumer.idempotency.mark_completed.assert_not_called()

    def test_dlq_is_confirmed_before_failed_state_and_offset_commit(self) -> None:
        events: list[str] = []

        class RejectingJavaToolClient:
            def post(self, path, payload):
                return {"reviewApplied": False, "reviewRejectReason": "TICKET_NOT_FOUND"}

        class Future:
            def get(self, timeout):
                events.append("dlq_sent")
                return None

        class Producer:
            def __init__(self, **kwargs):
                pass

            def send(self, *args, **kwargs):
                return Future()

        payload = (
            b'{"event_id":"evt-run","ticket_id":"10001","user_id":"20001",'
            b'"order_id":"30001"}'
        )

        class Consumer:
            def __init__(self, *args, **kwargs):
                pass

            def __iter__(self):
                return iter([SimpleNamespace(value=payload, key="evt-run")])

            def commit(self):
                events.append("commit")

        kafka_module = SimpleNamespace(
            KafkaConsumer=Consumer,
            KafkaProducer=Producer,
            TopicPartition=lambda topic, partition: (topic, partition),
        )
        consumer = AfterSalesReviewKafkaConsumer(config(), agent=FakeAgent(error=TimeoutError("timeout")))
        consumer.idempotency = Mock()
        consumer.idempotency.claim.return_value = ClaimResult(claimed=True, status="PROCESSING", attempt=1)
        consumer.idempotency.mark_failed.side_effect = lambda event_id: events.append("redis_failed")

        with patch.dict(sys.modules, {"kafka": kafka_module}), patch(
            "after_sales_agent.integrations.java_tool_client.JavaToolClient", RejectingJavaToolClient
        ):
            consumer.run_forever()

        self.assertEqual(["dlq_sent", "redis_failed", "commit"], events)
        consumer.idempotency.mark_manual_required.assert_not_called()

    def test_fresh_processing_is_deferred_and_only_terminal_state_is_committed(self) -> None:
        events: list[object] = []
        payload = (
            b'{"event_id":"evt-processing","ticket_id":"10001","user_id":"20001",'
            b'"order_id":"30001"}'
        )
        message = SimpleNamespace(
            value=payload,
            key="evt-processing",
            topic="after_sales.review.request",
            partition=0,
            offset=7,
        )

        class Consumer:
            def __init__(self, *args, **kwargs):
                pass

            def __iter__(self):
                return iter([message, message])

            def pause(self, topic_partition):
                events.append(("pause", topic_partition))

            def seek(self, topic_partition, offset):
                events.append(("seek", topic_partition, offset))

            def resume(self, topic_partition):
                events.append(("resume", topic_partition))

            def commit(self):
                events.append("commit")

        class Producer:
            def __init__(self, **kwargs):
                pass

        kafka_module = SimpleNamespace(
            KafkaConsumer=Consumer,
            KafkaProducer=Producer,
            TopicPartition=lambda topic, partition: (topic, partition),
        )
        consumer = AfterSalesReviewKafkaConsumer(config(), agent=FakeAgent())
        consumer.idempotency = Mock()
        consumer.idempotency.claim.side_effect = [
            ClaimResult(claimed=False, status="PROCESSING", should_ack=False, attempt=1),
            ClaimResult(claimed=False, status="COMPLETED", should_ack=True, attempt=1),
        ]

        with patch.dict(sys.modules, {"kafka": kafka_module}), patch(
            "after_sales_agent.api.kafka_review_consumer.time.sleep"
        ):
            consumer.run_forever()

        self.assertEqual(
            [
                ("pause", ("after_sales.review.request", 0)),
                ("seek", ("after_sales.review.request", 0), 7),
                ("resume", ("after_sales.review.request", 0)),
                "commit",
            ],
            events,
        )
        self.assertEqual(2, consumer.idempotency.claim.call_count)
        self.assertEqual(0, len(consumer.agent.payloads))

    def test_metrics_have_fixed_labels_and_ignore_dynamic_values(self) -> None:
        metrics = ConsumerMetrics()
        metrics.record_idempotency("claimed")
        metrics.record_idempotency("event-123")
        metrics.record_dlq("validate_event")
        metrics.record_dlq("ticket-10001")

        snapshot = metrics.snapshot()
        self.assertEqual(1, snapshot["agent_event_idempotency_total"]["claimed"])
        self.assertNotIn("event-123", snapshot["agent_event_idempotency_total"])
        self.assertEqual(1, snapshot["kafka_dlq_total"]["validate_event"])
        self.assertNotIn("ticket-10001", snapshot["kafka_dlq_total"])


if __name__ == "__main__":
    unittest.main()
