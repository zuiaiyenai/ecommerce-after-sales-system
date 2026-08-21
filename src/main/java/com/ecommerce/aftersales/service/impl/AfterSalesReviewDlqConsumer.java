package com.ecommerce.aftersales.service.impl;

import com.ecommerce.aftersales.config.TraceContext;
import com.ecommerce.aftersales.service.AiReviewManualHandoffService;
import com.ecommerce.aftersales.service.AgentGatewayMetrics;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.slf4j.MDC;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

import java.util.Map;

/**
 * Replays only the business handoff aspect of review DLQ messages. Kafka retains
 * the message until Java can persist the manual-review fact in MySQL.
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class AfterSalesReviewDlqConsumer {

    private final ObjectMapper objectMapper;
    private final AiReviewManualHandoffService aiReviewManualHandoffService;
    private final AgentGatewayMetrics metrics;

    @KafkaListener(
            topics = "${app.after-sales.review-events.dlq-topic:after_sales.review.dlq}",
            groupId = "${app.after-sales.review-events.dlq-consumer-group:java-after-sales-review-dlq}"
    )
    public void recoverManualHandoff(String raw) throws Exception {
        Map<String, Object> event = objectMapper.readValue(raw, new TypeReference<>() { });
        String previousTraceId = MDC.get(TraceContext.MDC_KEY);
        MDC.put(
                TraceContext.MDC_KEY,
                TraceContext.normalizeOrCreate(text(event.get("trace_id")))
        );
        try {
            recoverManualHandoff(event);
        } finally {
            if (previousTraceId == null) {
                MDC.remove(TraceContext.MDC_KEY);
            } else {
                MDC.put(TraceContext.MDC_KEY, previousTraceId);
            }
        }
    }

    private void recoverManualHandoff(Map<String, Object> event) {
        Long ticketId = parseLong(event.get("ticket_id"));
        String reviewRequestId = text(event.get("review_request_id"));
        if (ticketId == null || !StringUtils.hasText(reviewRequestId)) {
            metrics.recordKafkaDlq("replay");
            log.error("after_sales_dlq ticket_id={} review_request_id={} transition=unrecoverable failure_class=INVALID_EVENT",
                    ticketId, reviewRequestId);
            return;
        }
        String reason = "AI初审异常，已转人工审核：" + text(event.get("error_message"));
        AiReviewManualHandoffService.ManualHandoffResult result = aiReviewManualHandoffService.markManualRequired(
                ticketId,
                reviewRequestId,
                reason,
                "DLQ_" + text(event.get("failed_stage")),
                null,
                null
        );
        if (!result.applied() && !result.idempotentReplay() && !"STATUS_CHANGED".equals(result.rejectReason())) {
            metrics.recordKafkaDlq("replay");
            log.error("after_sales_dlq ticket_id={} review_request_id={} transition=retry failure_class={}",
                    ticketId, reviewRequestId, result.rejectReason());
            throw new IllegalStateException("DLQ manual handoff was not persisted: " + result.rejectReason());
        }
        metrics.recordKafkaDlq("replay");
        log.info("after_sales_dlq ticket_id={} review_request_id={} transition={} failure_class=none",
                ticketId, reviewRequestId, result.idempotentReplay() ? "idempotent" : "manual_required");
    }

    private Long parseLong(Object value) {
        try {
            return value == null ? null : Long.valueOf(String.valueOf(value));
        } catch (NumberFormatException ignored) {
            return null;
        }
    }

    private String text(Object value) {
        return value == null ? "" : String.valueOf(value).trim();
    }
}
