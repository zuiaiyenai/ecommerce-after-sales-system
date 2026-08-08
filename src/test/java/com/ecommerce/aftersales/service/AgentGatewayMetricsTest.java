package com.ecommerce.aftersales.service;

import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import io.micrometer.prometheusmetrics.PrometheusConfig;
import io.micrometer.prometheusmetrics.PrometheusMeterRegistry;
import org.junit.jupiter.api.Test;

import java.util.Map;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;

class AgentGatewayMetricsTest {

    @Test
    void exposesPhase3MetricsWithOnlyFixedLowCardinalityLabels() {
        AgentGatewayMetrics metrics = new AgentGatewayMetrics();

        metrics.recordAiReviewApply("applied");
        metrics.recordAiReviewApply("ticket-10001");
        metrics.recordAiReviewManualHandoff("AGENT_TOOL");
        metrics.recordAiReviewManualHandoff("DLQ_submit_manual_fallback");
        metrics.recordOutboxPublish("DEAD");
        metrics.recordKafkaDlq("replay");
        metrics.recordAgentEventIdempotency("completed");
        metrics.setMerchantQueueUnrepliedCount(7);
        metrics.record("success", 80_000_000L);
        metrics.recordChat(false, 2);

        Map<String, Object> snapshot = metrics.snapshot();
        assertThat(counter(snapshot, "ai_review_apply_total"))
                .containsEntry("applied", 1L)
                .doesNotContainKey("ticket-10001");
        assertThat(counter(snapshot, "ai_review_manual_handoff_total"))
                .containsEntry("consumer", 1L)
                .containsEntry("dlq_replay", 1L);
        assertThat(counter(snapshot, "outbox_publish_total")).containsEntry("dead", 1L);
        assertThat(counter(snapshot, "kafka_dlq_total")).containsEntry("replay", 1L);
        assertThat(counter(snapshot, "agent_event_idempotency_total")).containsEntry("completed", 1L);
        assertThat(snapshot.get("merchant_queue_unreplied_count")).isEqualTo(7L);
        assertThat(snapshot.get("success_rate")).isEqualTo(1D);
        assertThat(snapshot.get("human_handoff_rate")).isEqualTo(0D);
        assertThat(snapshot.get("knowledge_hit_chat_rate")).isEqualTo(1D);
        assertThat(counter(snapshot, "gateway_latency_bucket_total")).containsEntry("le_100ms", 1L);
    }

    @Test
    void publishesTheSameBusinessSignalsToMicrometer() {
        SimpleMeterRegistry registry = new SimpleMeterRegistry();
        AgentGatewayMetrics metrics = new AgentGatewayMetrics(registry);

        metrics.record("success", 250_000_000L);
        metrics.recordChat(true, 3);
        metrics.recordAiReviewApply("manual_required");
        metrics.recordOutboxPublish("DEAD");
        metrics.setMerchantQueueUnrepliedCount(4);

        assertThat(registry.get("agent.gateway.requests").tag("outcome", "success").counter().count()).isEqualTo(1D);
        assertThat(registry.get("agent.gateway.duration").timer().totalTime(TimeUnit.MILLISECONDS)).isEqualTo(250D);
        assertThat(registry.get("agent.chat.requests").counter().count()).isEqualTo(1D);
        assertThat(registry.get("agent.chat.handoffs").counter().count()).isEqualTo(1D);
        assertThat(registry.get("agent.chat.knowledge_hits").counter().count()).isEqualTo(3D);
        assertThat(registry.get("agent.ai_review.applies").tag("result", "manual_required").counter().count()).isEqualTo(1D);
        assertThat(registry.get("agent.outbox.publishes").tag("status", "dead").counter().count()).isEqualTo(1D);
        assertThat(registry.get("agent.merchant.queue.unreplied").gauge().value()).isEqualTo(4D);
    }

    @Test
    void prometheusNamesMatchProvisionedDashboardQueries() {
        PrometheusMeterRegistry registry = new PrometheusMeterRegistry(PrometheusConfig.DEFAULT);
        AgentGatewayMetrics metrics = new AgentGatewayMetrics(registry);

        metrics.record("success", 250_000_000L);
        metrics.recordOutboxPublish("published");
        metrics.recordKafkaDlq("replay");
        metrics.setMerchantQueueUnrepliedCount(2);

        String scrape = registry.scrape();
        assertThat(scrape).contains("agent_gateway_requests_total{outcome=\"success\"} 1.0");
        assertThat(scrape).contains("agent_gateway_duration_seconds_bucket");
        assertThat(scrape).contains("agent_outbox_publishes_total{status=\"published\"} 1.0");
        assertThat(scrape).contains("agent_kafka_dlq_events_total{stage=\"replay\"} 1.0");
        assertThat(scrape).contains("agent_merchant_queue_unreplied 2.0");
    }

    @SuppressWarnings("unchecked")
    private Map<String, Long> counter(Map<String, Object> snapshot, String name) {
        return (Map<String, Long>) snapshot.get(name);
    }
}
