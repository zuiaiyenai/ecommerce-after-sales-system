package com.ecommerce.aftersales.service.impl;

import com.ecommerce.aftersales.config.TraceContext;
import com.ecommerce.aftersales.entity.AfterSalesEventOutbox;
import com.ecommerce.aftersales.entity.AfterSalesTicket;
import com.ecommerce.aftersales.mapper.AfterSalesEventOutboxMapper;
import com.ecommerce.aftersales.service.AiReviewManualHandoffService;
import com.ecommerce.aftersales.service.AgentGatewayMetrics;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.slf4j.MDC;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.OffsetDateTime;
import java.util.concurrent.CompletableFuture;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class AfterSalesReviewFailureHandoffTest {

    @Test
    void successfulPublishPersistsPublishedStateAndMetric() {
        AfterSalesEventOutboxMapper outboxMapper = mock(AfterSalesEventOutboxMapper.class);
        @SuppressWarnings("unchecked")
        KafkaTemplate<String, String> kafka = mock(KafkaTemplate.class);
        AgentGatewayMetrics metrics = new AgentGatewayMetrics();
        AfterSalesReviewEventServiceImpl service = new AfterSalesReviewEventServiceImpl(
                outboxMapper, new ObjectMapper(), kafka, mock(AiReviewManualHandoffService.class), metrics);
        AfterSalesEventOutbox event = event();
        when(kafka.send(anyString(), anyString(), anyString())).thenReturn(CompletableFuture.completedFuture(null));

        service.publishOne(event);

        assertThat(event.getStatus()).isEqualTo("PUBLISHED");
        assertThat(counter(metrics, "outbox_publish_total")).containsEntry("published", 1L);
        verify(outboxMapper).updateById(event);
    }

    @Test
    void reviewEventUsesCanonicalSnakeCaseEnvelopeAndOffsetTimestamp() throws Exception {
        AfterSalesEventOutboxMapper outboxMapper = mock(AfterSalesEventOutboxMapper.class);
        @SuppressWarnings("unchecked")
        KafkaTemplate<String, String> kafka = mock(KafkaTemplate.class);
        AfterSalesReviewEventServiceImpl service = new AfterSalesReviewEventServiceImpl(
                outboxMapper, new ObjectMapper(), kafka, mock(AiReviewManualHandoffService.class), new AgentGatewayMetrics());
        ReflectionTestUtils.setField(service, "reviewRequestTopic", "after_sales.review.request");
        AfterSalesTicket ticket = ticket("PENDING_REVIEW", null);
        ticket.setTicketNo("AS202607140001");
        ticket.setUserId(9007199254740993L);
        ticket.setOrderId(9007199254740995L);
        ticket.setOrderNo("ORDER-20260714-1");

        String traceId = "abcdef0123456789abcdef0123456789";
        MDC.put(TraceContext.MDC_KEY, traceId);
        try {
            service.enqueueReviewRequested(ticket, 9007199254740991L);
        } finally {
            MDC.remove(TraceContext.MDC_KEY);
        }

        ArgumentCaptor<AfterSalesEventOutbox> captor = ArgumentCaptor.forClass(AfterSalesEventOutbox.class);
        verify(outboxMapper).insert(captor.capture());
        AfterSalesEventOutbox outbox = captor.getValue();
        JsonNode payload = new ObjectMapper().readTree(outbox.getPayload());
        assertThat(outbox.getEventType()).isEqualTo("after_sales.review.request");
        assertThat(payload.path("event_type").asText()).isEqualTo("after_sales.review.request");
        assertThat(payload.path("ticket_id").asText()).isEqualTo("1");
        assertThat(payload.path("user_id").asText()).isEqualTo("9007199254740993");
        assertThat(payload.path("order_id").asText()).isEqualTo("9007199254740995");
        assertThat(payload.path("session_id").asText()).isEqualTo("9007199254740991");
        assertThat(payload.path("trace_id").asText()).isEqualTo(traceId);
        assertThat(OffsetDateTime.parse(payload.path("created_at").asText())).isNotNull();
        assertThat(payload.has("created_time")).isFalse();
        assertThat(payload.has("ticketId")).isFalse();
    }

    @Test
    void exhaustedOutboxFailurePersistsManualHandoffBeforeDeadStatus() {
        AfterSalesEventOutboxMapper outboxMapper = mock(AfterSalesEventOutboxMapper.class);
        @SuppressWarnings("unchecked")
        KafkaTemplate<String, String> kafka = mock(KafkaTemplate.class);
        AiReviewManualHandoffService handoff = mock(AiReviewManualHandoffService.class);
        AfterSalesReviewEventServiceImpl service = new AfterSalesReviewEventServiceImpl(
                outboxMapper, new ObjectMapper(), kafka, handoff, new AgentGatewayMetrics());
        ReflectionTestUtils.setField(service, "maxRetries", 0);
        AfterSalesEventOutbox event = event();
        when(kafka.send(anyString(), anyString(), anyString()))
                .thenReturn(CompletableFuture.failedFuture(new IllegalStateException("broker unavailable")));
        when(handoff.markManualRequired(any(), anyString(), anyString(), anyString(), any(), any()))
                .thenReturn(new AiReviewManualHandoffService.ManualHandoffResult(
                        ticket("PENDING_REVIEW", "event-1"), true, false, null));

        service.publishOne(event);

        assertThat(event.getStatus()).isEqualTo("DEAD");
        verify(handoff).markManualRequired(org.mockito.ArgumentMatchers.eq(1L), org.mockito.ArgumentMatchers.eq("event-1"), org.mockito.ArgumentMatchers.contains("broker unavailable"),
                org.mockito.ArgumentMatchers.eq("OUTBOX_DEAD"), org.mockito.ArgumentMatchers.isNull(), org.mockito.ArgumentMatchers.isNull());
        verify(outboxMapper).updateById(event);
    }

    @Test
    void outboxDoesNotBecomeDeadWhenManualHandoffFails() {
        AfterSalesEventOutboxMapper outboxMapper = mock(AfterSalesEventOutboxMapper.class);
        @SuppressWarnings("unchecked")
        KafkaTemplate<String, String> kafka = mock(KafkaTemplate.class);
        AiReviewManualHandoffService handoff = mock(AiReviewManualHandoffService.class);
        AfterSalesReviewEventServiceImpl service = new AfterSalesReviewEventServiceImpl(
                outboxMapper, new ObjectMapper(), kafka, handoff, new AgentGatewayMetrics());
        ReflectionTestUtils.setField(service, "maxRetries", 0);
        AfterSalesEventOutbox event = event();
        when(kafka.send(anyString(), anyString(), anyString()))
                .thenReturn(CompletableFuture.failedFuture(new IllegalStateException("broker unavailable")));
        when(handoff.markManualRequired(any(), anyString(), anyString(), anyString(), any(), any()))
                .thenReturn(new AiReviewManualHandoffService.ManualHandoffResult(null, false, false, "TICKET_NOT_FOUND"));

        service.publishOne(event);

        assertThat(event.getStatus()).isEqualTo("FAILED");
        verify(outboxMapper).updateById(event);
    }

    @Test
    void dlqFailurePropagatesSoKafkaListenerDoesNotAcknowledgeIt() {
        AiReviewManualHandoffService handoff = mock(AiReviewManualHandoffService.class);
        AfterSalesReviewDlqConsumer consumer = new AfterSalesReviewDlqConsumer(new ObjectMapper(), handoff, new AgentGatewayMetrics());
        when(handoff.markManualRequired(any(), anyString(), anyString(), anyString(), any(), any()))
                .thenReturn(new AiReviewManualHandoffService.ManualHandoffResult(null, false, false, "TICKET_NOT_FOUND"));

        assertThatThrownBy(() -> consumer.recoverManualHandoff("""
                {"ticket_id":"1","review_request_id":"event-1","error_message":"timeout","failed_stage":"submit_manual_fallback"}
                """))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("not persisted");
    }

    private AfterSalesEventOutbox event() {
        AfterSalesEventOutbox event = new AfterSalesEventOutbox();
        event.setEventId("event-1");
        event.setAggregateId(1L);
        event.setTopic("after_sales.review.request");
        event.setPayload("{}");
        event.setRetryCount(0);
        return event;
    }

    private AfterSalesTicket ticket(String status, String requestId) {
        AfterSalesTicket ticket = new AfterSalesTicket();
        ticket.setId(1L);
        ticket.setStatus(status);
        ticket.setAiReviewRequestId(requestId);
        return ticket;
    }

    @SuppressWarnings("unchecked")
    private Map<String, Long> counter(AgentGatewayMetrics metrics, String name) {
        return (Map<String, Long>) metrics.snapshot().get(name);
    }
}
