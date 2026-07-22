package com.ecommerce.aftersales.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.toolkit.IdWorker;
import com.ecommerce.aftersales.entity.AfterSalesEventOutbox;
import com.ecommerce.aftersales.config.TraceContext;
import com.ecommerce.aftersales.entity.AfterSalesTicket;
import com.ecommerce.aftersales.mapper.AfterSalesEventOutboxMapper;
import com.ecommerce.aftersales.service.AiReviewManualHandoffService;
import com.ecommerce.aftersales.service.AgentGatewayMetrics;
import com.ecommerce.aftersales.service.AfterSalesReviewEventService;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.BadSqlGrammarException;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

@Slf4j
@Service
@RequiredArgsConstructor
public class AfterSalesReviewEventServiceImpl implements AfterSalesReviewEventService {

    private static final String EVENT_TYPE = "after_sales.review.request";
    private static final String DEFAULT_TOPIC = "after_sales.review.request";

    private final AfterSalesEventOutboxMapper outboxMapper;
    private final ObjectMapper objectMapper;
    private final KafkaTemplate<String, String> kafkaTemplate;
    private final AiReviewManualHandoffService aiReviewManualHandoffService;
    private final AgentGatewayMetrics metrics;
    private boolean missingOutboxTableLogged;

    @Value("${app.after-sales.review-events.topic:" + DEFAULT_TOPIC + "}")
    private String reviewRequestTopic;

    @Value("${app.after-sales.review-events.max-retries:5}")
    private int maxRetries;

    @Value("${app.after-sales.review-events.batch-size:20}")
    private int batchSize;

    @Override
    public void enqueueReviewRequested(AfterSalesTicket ticket, Long sessionId) {
        if (ticket == null || ticket.getId() == null) {
            return;
        }
        String eventId = UUID.randomUUID().toString();
        AfterSalesEventOutbox outbox = new AfterSalesEventOutbox();
        outbox.setId(IdWorker.getId());
        outbox.setEventId(eventId);
        outbox.setEventType(EVENT_TYPE);
        outbox.setTopic(reviewRequestTopic);
        outbox.setAggregateType("after_sales_ticket");
        outbox.setAggregateId(ticket.getId());
        outbox.setPayload(writePayload(ticket, sessionId, eventId));
        outbox.setStatus("NEW");
        outbox.setRetryCount(0);
        outbox.setNextRetryTime(LocalDateTime.now());
        outboxMapper.insert(outbox);
    }

    @Override
    @Scheduled(fixedDelayString = "${app.after-sales.review-events.publish-fixed-delay-ms:3000}")
    public void publishPending() {
        List<AfterSalesEventOutbox> events;
        try {
            events = outboxMapper.selectList(
                    new LambdaQueryWrapper<AfterSalesEventOutbox>()
                            .in(AfterSalesEventOutbox::getStatus, List.of("NEW", "FAILED"))
                            .le(AfterSalesEventOutbox::getRetryCount, maxRetries)
                            .le(AfterSalesEventOutbox::getNextRetryTime, LocalDateTime.now())
                            .orderByAsc(AfterSalesEventOutbox::getCreateTime)
                            .last("limit " + Math.max(1, batchSize))
            );
        } catch (BadSqlGrammarException exception) {
            if (isMissingOutboxTable(exception)) {
                if (!missingOutboxTableLogged) {
                    missingOutboxTableLogged = true;
                    log.warn("after_sales_event_outbox table is missing; skip publishing review events. Apply sql/migrations/20260713_add_after_sales_event_outbox.sql before using async AI review.");
                }
                return;
            }
            throw exception;
        }
        for (AfterSalesEventOutbox event : events) {
            publishOne(event);
        }
    }

    @Transactional(rollbackFor = Exception.class)
    protected void publishOne(AfterSalesEventOutbox event) {
        try {
            kafkaTemplate.send(event.getTopic(), event.getEventId(), event.getPayload()).get();
            event.setStatus("PUBLISHED");
            event.setPublishedTime(LocalDateTime.now());
            event.setLastError(null);
            outboxMapper.updateById(event);
            metrics.recordOutboxPublish("published");
            log.info("after_sales_outbox event_id={} ticket_id={} transition=published failure_class=none",
                    event.getEventId(), event.getAggregateId());
        } catch (Exception exception) {
            int retryCount = event.getRetryCount() == null ? 0 : event.getRetryCount();
            int nextRetryCount = retryCount + 1;
            boolean exhausted = nextRetryCount > maxRetries;
            String failureReason = shortText(exception.getClass().getSimpleName() + ": " + exception.getMessage(), 500);
            event.setRetryCount(nextRetryCount);
            event.setStatus(exhausted ? "DEAD" : "FAILED");
            event.setLastError(failureReason);
            event.setNextRetryTime(LocalDateTime.now().plusSeconds(Math.min(300, 5L * (retryCount + 1))));
            if (exhausted) {
                AiReviewManualHandoffService.ManualHandoffResult handoff = aiReviewManualHandoffService.markManualRequired(
                        event.getAggregateId(),
                        event.getEventId(),
                        "AI初审事件投递失败，已转人工审核：" + failureReason,
                        "OUTBOX_DEAD",
                        null,
                        null
                );
                if (!handoff.applied() && !handoff.idempotentReplay()
                        && !"STATUS_CHANGED".equals(handoff.rejectReason())) {
                    // Do not make a dead event look handled when its business handoff did not persist.
                    event.setStatus("FAILED");
                    event.setRetryCount(maxRetries);
                }
            }
            outboxMapper.updateById(event);
            metrics.recordOutboxPublish(event.getStatus());
            log.warn("after_sales_outbox event_id={} ticket_id={} transition={} retry_count={} failure_class={}",
                    event.getEventId(), event.getAggregateId(), event.getStatus().toLowerCase(),
                    event.getRetryCount(), exception.getClass().getSimpleName());
        }
    }

    private String writePayload(AfterSalesTicket ticket, Long sessionId, String eventId) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("event_id", eventId);
        payload.put("trace_id", TraceContext.currentOrCreate());
        payload.put("event_type", EVENT_TYPE);
        payload.put("ticket_id", String.valueOf(ticket.getId()));
        payload.put("ticket_no", ticket.getTicketNo());
        payload.put("user_id", String.valueOf(ticket.getUserId()));
        payload.put("order_id", String.valueOf(ticket.getOrderId()));
        payload.put("order_no", ticket.getOrderNo());
        if (sessionId != null) {
            payload.put("session_id", String.valueOf(sessionId));
        }
        payload.put("created_at", OffsetDateTime.now(ZoneOffset.UTC).format(DateTimeFormatter.ISO_OFFSET_DATE_TIME));
        try {
            return objectMapper.writeValueAsString(payload);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Failed to serialize after-sales review event", exception);
        }
    }

    private String shortText(String value, int limit) {
        if (!StringUtils.hasText(value)) {
            return "";
        }
        return value.length() <= limit ? value : value.substring(0, limit);
    }

    private boolean isMissingOutboxTable(BadSqlGrammarException exception) {
        Throwable cause = exception.getMostSpecificCause();
        String message = cause == null ? exception.getMessage() : cause.getMessage();
        return message != null && message.contains("after_sales_event_outbox") && message.toLowerCase().contains("doesn't exist");
    }
}
