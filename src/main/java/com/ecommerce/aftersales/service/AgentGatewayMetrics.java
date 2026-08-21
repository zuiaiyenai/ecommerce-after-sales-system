package com.ecommerce.aftersales.service;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.Gauge;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.LongAdder;

/** Agent gateway metrics exposed both as a diagnostic JSON snapshot and Micrometer meters. */
@Component
public class AgentGatewayMetrics {
    private final LongAdder total = new LongAdder();
    private final LongAdder success = new LongAdder();
    private final LongAdder failure = new LongAdder();
    private final LongAdder rejected = new LongAdder();
    private final LongAdder totalLatencyNanos = new LongAdder();
    private final LongAdder humanHandoffs = new LongAdder();
    private final LongAdder knowledgeHits = new LongAdder();
    private final LongAdder chatRequests = new LongAdder();
    private final LongAdder chatsWithKnowledge = new LongAdder();
    private final Map<String, LongAdder> gatewayLatencyBuckets = counters(
            "le_100ms", "le_500ms", "le_1s", "le_3s", "le_10s", "le_30s", "le_90s", "gt_90s");
    private final Map<String, LongAdder> aiReviewApply = counters(
            "applied", "stale", "idempotent", "manual_required");
    private final Map<String, LongAdder> aiReviewManualHandoff = counters(
            "consumer", "outbox_dead", "dlq_replay");
    private final Map<String, LongAdder> outboxPublish = counters(
            "published", "failed", "dead");
    private final Map<String, LongAdder> kafkaDlq = counters(
            "decode_event", "validate_event", "submit_manual_fallback", "replay");
    private final Map<String, LongAdder> agentEventIdempotency = counters(
            "claimed", "duplicate_terminal", "duplicate_processing", "stale_takeover",
            "released", "completed", "manual_required", "failed");
    private final AtomicLong merchantQueueUnrepliedCount = new AtomicLong();
    private final Map<String, Counter> gatewayRequestMeters;
    private final Map<String, Counter> aiReviewApplyMeters;
    private final Map<String, Counter> aiReviewManualHandoffMeters;
    private final Map<String, Counter> outboxPublishMeters;
    private final Map<String, Counter> kafkaDlqMeters;
    private final Map<String, Counter> agentEventIdempotencyMeters;
    private final Counter chatRequestMeter;
    private final Counter humanHandoffMeter;
    private final Counter knowledgeHitMeter;
    private final Counter knowledgeHitChatMeter;
    private final Timer gatewayDurationMeter;
    private final AtomicLong gatewayCapacity = new AtomicLong();
    private final AtomicInteger gatewayInFlight = new AtomicInteger();
    private final AtomicInteger sseInFlight = new AtomicInteger();
    private final Counter sseRejectedMeter;

    /** Keeps focused unit tests and manually constructed services dependency-free. */
    public AgentGatewayMetrics() {
        this(null);
    }

    @Autowired
    public AgentGatewayMetrics(MeterRegistry registry) {
        gatewayRequestMeters = meterCounters(registry, "agent.gateway.requests", "outcome",
                "success", "failure", "rejected");
        aiReviewApplyMeters = meterCounters(registry, "agent.ai_review.applies", "result",
                "applied", "stale", "idempotent", "manual_required");
        aiReviewManualHandoffMeters = meterCounters(registry, "agent.ai_review.manual_handoffs", "source",
                "consumer", "outbox_dead", "dlq_replay");
        outboxPublishMeters = meterCounters(registry, "agent.outbox.publishes", "status",
                "published", "failed", "dead");
        kafkaDlqMeters = meterCounters(registry, "agent.kafka.dlq.events", "stage",
                "decode_event", "validate_event", "submit_manual_fallback", "replay");
        agentEventIdempotencyMeters = meterCounters(registry, "agent.event.idempotency", "outcome",
                "claimed", "duplicate_terminal", "duplicate_processing", "stale_takeover",
                "released", "completed", "manual_required", "failed");
        chatRequestMeter = meterCounter(registry, "agent.chat.requests", "Agent chat requests");
        humanHandoffMeter = meterCounter(registry, "agent.chat.handoffs", "Chat requests routed to a human");
        knowledgeHitMeter = meterCounter(registry, "agent.chat.knowledge_hits", "Knowledge chunks returned");
        knowledgeHitChatMeter = meterCounter(registry, "agent.chat.knowledge_hit_chats", "Chat requests with knowledge hits");
        gatewayDurationMeter = registry == null ? null : Timer.builder("agent.gateway.duration")
                .description("Java-to-Python Agent gateway duration")
                .publishPercentileHistogram()
                .serviceLevelObjectives(
                        Duration.ofMillis(100), Duration.ofMillis(500), Duration.ofSeconds(1),
                        Duration.ofSeconds(3), Duration.ofSeconds(10), Duration.ofSeconds(30),
                        Duration.ofSeconds(90))
                .register(registry);
        sseRejectedMeter = meterCounter(registry, "agent.gateway.sse.rejections",
                "Agent SSE requests rejected before execution");
        if (registry != null) {
            Gauge.builder("agent.merchant.queue.unreplied", merchantQueueUnrepliedCount, AtomicLong::get)
                    .description("Current unreplied merchant customer-service sessions")
                    .register(registry);
            Gauge.builder("agent.gateway.capacity", gatewayCapacity, AtomicLong::get)
                    .description("Configured Java-to-Agent concurrency capacity")
                    .register(registry);
            Gauge.builder("agent.gateway.inflight", gatewayInFlight, AtomicInteger::get)
                    .description("Current Java-to-Agent requests holding a concurrency permit")
                    .register(registry);
            Gauge.builder("agent.gateway.sse.inflight", sseInFlight, AtomicInteger::get)
                    .description("Current Agent SSE requests holding a concurrency permit")
                    .register(registry);
        }
    }

    public void setGatewayCapacity(long capacity) {
        gatewayCapacity.set(Math.max(0, capacity));
    }

    public void permitAcquired() {
        gatewayInFlight.incrementAndGet();
    }

    public void permitReleased() {
        gatewayInFlight.updateAndGet(value -> Math.max(0, value - 1));
    }

    public void sseStarted() {
        sseInFlight.incrementAndGet();
    }

    public void sseFinished() {
        sseInFlight.updateAndGet(value -> Math.max(0, value - 1));
    }

    public void recordSseRejected() {
        if (sseRejectedMeter != null) {
            sseRejectedMeter.increment();
        }
    }

    public void record(String outcome, long elapsedNanos) {
        String normalizedOutcome = switch (outcome) {
            case "success" -> "success";
            case "rejected" -> "rejected";
            default -> "failure";
        };
        total.increment();
        totalLatencyNanos.add(Math.max(0, elapsedNanos));
        incrementAdder(gatewayLatencyBuckets, latencyBucket(elapsedNanos));
        incrementMeter(gatewayRequestMeters, normalizedOutcome);
        if (gatewayDurationMeter != null) {
            gatewayDurationMeter.record(Math.max(0, elapsedNanos), TimeUnit.NANOSECONDS);
        }
        switch (normalizedOutcome) {
            case "success" -> success.increment();
            case "rejected" -> rejected.increment();
            default -> failure.increment();
        }
    }

    public void recordChat(Boolean needHuman, Integer hitCount) {
        chatRequests.increment();
        incrementMeter(chatRequestMeter);
        if (Boolean.TRUE.equals(needHuman)) {
            humanHandoffs.increment();
            incrementMeter(humanHandoffMeter);
        }
        if (hitCount != null && hitCount > 0) {
            knowledgeHits.add(hitCount);
            chatsWithKnowledge.increment();
            incrementMeter(knowledgeHitMeter, hitCount);
            incrementMeter(knowledgeHitChatMeter);
        }
    }

    public void recordAiReviewApply(String result) {
        incrementAdder(aiReviewApply, result);
        incrementMeter(aiReviewApplyMeters, result);
    }

    public void recordAiReviewManualHandoff(String source) {
        String normalizedSource = normalizeHandoffSource(source);
        incrementAdder(aiReviewManualHandoff, normalizedSource);
        incrementMeter(aiReviewManualHandoffMeters, normalizedSource);
    }

    public void recordOutboxPublish(String status) {
        String normalizedStatus = lower(status);
        incrementAdder(outboxPublish, normalizedStatus);
        incrementMeter(outboxPublishMeters, normalizedStatus);
    }

    public void recordKafkaDlq(String stage) {
        String normalizedStage = lower(stage);
        incrementAdder(kafkaDlq, normalizedStage);
        incrementMeter(kafkaDlqMeters, normalizedStage);
    }

    public void recordAgentEventIdempotency(String outcome) {
        String normalizedOutcome = lower(outcome);
        incrementAdder(agentEventIdempotency, normalizedOutcome);
        incrementMeter(agentEventIdempotencyMeters, normalizedOutcome);
    }

    public void setMerchantQueueUnrepliedCount(long count) {
        merchantQueueUnrepliedCount.set(Math.max(0, count));
    }

    public Map<String, Object> snapshot() {
        long requests = total.sum();
        Map<String, Object> values = new LinkedHashMap<>();
        values.put("requests", requests);
        values.put("success", success.sum());
        values.put("failure", failure.sum());
        values.put("rejected", rejected.sum());
        values.put("avg_latency_ms", requests == 0 ? 0D : totalLatencyNanos.sum() / 1_000_000D / requests);
        values.put("success_rate", requests == 0 ? 0D : success.sum() / (double) requests);
        values.put("gateway_latency_bucket_total", snapshot(gatewayLatencyBuckets));
        values.put("human_handoffs", humanHandoffs.sum());
        values.put("human_handoff_rate", chatRequests.sum() == 0 ? 0D : humanHandoffs.sum() / (double) chatRequests.sum());
        values.put("knowledge_hits", knowledgeHits.sum());
        values.put("knowledge_hit_chat_rate", chatRequests.sum() == 0 ? 0D : chatsWithKnowledge.sum() / (double) chatRequests.sum());
        values.put("ai_review_apply_total", snapshot(aiReviewApply));
        values.put("ai_review_manual_handoff_total", snapshot(aiReviewManualHandoff));
        values.put("outbox_publish_total", snapshot(outboxPublish));
        values.put("kafka_dlq_total", snapshot(kafkaDlq));
        values.put("agent_event_idempotency_total", snapshot(agentEventIdempotency));
        values.put("merchant_queue_unreplied_count", merchantQueueUnrepliedCount.get());
        return values;
    }

    private static Map<String, LongAdder> counters(String... labels) {
        Map<String, LongAdder> values = new ConcurrentHashMap<>();
        Set.of(labels).forEach(label -> values.put(label, new LongAdder()));
        return values;
    }

    private static void incrementAdder(Map<String, LongAdder> counters, String label) {
        LongAdder counter = counters.get(label);
        if (counter != null) {
            counter.increment();
        }
    }

    private static Map<String, Counter> meterCounters(MeterRegistry registry, String name, String tag,
                                                       String... labels) {
        if (registry == null) {
            return Map.of();
        }
        Map<String, Counter> values = new LinkedHashMap<>();
        for (String label : labels) {
            values.put(label, Counter.builder(name).tag(tag, label).register(registry));
        }
        return values;
    }

    private static Counter meterCounter(MeterRegistry registry, String name, String description) {
        return registry == null ? null : Counter.builder(name).description(description).register(registry);
    }

    private static void incrementMeter(Map<String, Counter> counters, String label) {
        Counter counter = counters.get(label);
        if (counter != null) {
            counter.increment();
        }
    }

    private static void incrementMeter(Counter counter) {
        incrementMeter(counter, 1D);
    }

    private static void incrementMeter(Counter counter, double amount) {
        if (counter != null) {
            counter.increment(amount);
        }
    }

    private static Map<String, Long> snapshot(Map<String, LongAdder> counters) {
        Map<String, Long> values = new LinkedHashMap<>();
        counters.keySet().stream().sorted().forEach(label -> values.put(label, counters.get(label).sum()));
        return values;
    }

    private static String normalizeHandoffSource(String source) {
        String value = lower(source);
        if (value.startsWith("dlq")) {
            return "dlq_replay";
        }
        if ("outbox_dead".equals(value)) {
            return value;
        }
        if ("consumer".equals(value) || "agent_tool".equals(value)) {
            return "consumer";
        }
        return "";
    }

    private static String latencyBucket(long elapsedNanos) {
        long millis = Math.max(0, elapsedNanos) / 1_000_000L;
        if (millis <= 100) return "le_100ms";
        if (millis <= 500) return "le_500ms";
        if (millis <= 1_000) return "le_1s";
        if (millis <= 3_000) return "le_3s";
        if (millis <= 10_000) return "le_10s";
        if (millis <= 30_000) return "le_30s";
        if (millis <= 90_000) return "le_90s";
        return "gt_90s";
    }

    private static String lower(String value) {
        return value == null ? "" : value.trim().toLowerCase();
    }
}
