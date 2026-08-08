package com.ecommerce.aftersales.service.impl;

import com.ecommerce.aftersales.entity.AfterSalesTicket;
import com.ecommerce.aftersales.mapper.AfterSalesTicketMapper;
import com.ecommerce.aftersales.mapper.TicketLogMapper;
import com.ecommerce.aftersales.service.AiReviewManualHandoffService;
import com.ecommerce.aftersales.service.AiReviewStatusCacheService;
import com.ecommerce.aftersales.service.AiReviewUserNotificationService;
import com.ecommerce.aftersales.service.AgentGatewayMetrics;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class AiReviewManualHandoffServiceImplTest {

    @Test
    void persistsManualReviewAndAuditForPendingTicket() {
        AfterSalesTicketMapper tickets = mock(AfterSalesTicketMapper.class);
        TicketLogMapper logs = mock(TicketLogMapper.class);
        AiReviewStatusCacheService cache = mock(AiReviewStatusCacheService.class);
        AfterSalesTicket pending = ticket("PENDING", null);
        AfterSalesTicket updated = ticket("PENDING_REVIEW", "event-1");
        when(tickets.selectById(1L)).thenReturn(pending, updated);
        when(tickets.applyManualReviewIfPending(any(), anyString(), anyString(), any(), any(), any())).thenReturn(1);

        AiReviewManualHandoffService.ManualHandoffResult result = new AiReviewManualHandoffServiceImpl(tickets, logs, cache, mock(AiReviewUserNotificationService.class), new AgentGatewayMetrics())
                .markManualRequired(1L, "event-1", "模型不可用", "CONSUMER", null, null);

        assertThat(result.applied()).isTrue();
        assertThat(result.idempotentReplay()).isFalse();
        ArgumentCaptor<com.ecommerce.aftersales.entity.TicketLog> logCaptor = ArgumentCaptor.forClass(com.ecommerce.aftersales.entity.TicketLog.class);
        verify(logs).insert(logCaptor.capture());
        assertThat(logCaptor.getValue().getAction()).isEqualTo("AI_REVIEW_MANUAL_CONSUMER");
        assertThat(logCaptor.getValue().getFromStatus()).isEqualTo("PENDING");
        assertThat(logCaptor.getValue().getToStatus()).isEqualTo("PENDING_REVIEW");
        verify(cache).cacheStatus(1L, "MANUAL_REQUIRED");
    }

    @Test
    void replayDoesNotWriteManualReviewTwice() {
        AfterSalesTicketMapper tickets = mock(AfterSalesTicketMapper.class);
        TicketLogMapper logs = mock(TicketLogMapper.class);
        AiReviewStatusCacheService cache = mock(AiReviewStatusCacheService.class);
        when(tickets.selectById(1L)).thenReturn(ticket("PENDING_REVIEW", "event-1"));

        AiReviewManualHandoffService.ManualHandoffResult result = new AiReviewManualHandoffServiceImpl(tickets, logs, cache, mock(AiReviewUserNotificationService.class), new AgentGatewayMetrics())
                .markManualRequired(1L, "event-1", "重复投递", "CONSUMER", null, null);

        assertThat(result.applied()).isFalse();
        assertThat(result.idempotentReplay()).isTrue();
        verify(tickets, never()).applyManualReviewIfPending(any(), anyString(), anyString(), any(), any(), any());
        verify(logs, never()).insert(any(com.ecommerce.aftersales.entity.TicketLog.class));
        verify(cache, never()).cacheStatus(any(), anyString());
    }

    @Test
    void terminalTicketIsNotOverwrittenByManualFallback() {
        AfterSalesTicketMapper tickets = mock(AfterSalesTicketMapper.class);
        TicketLogMapper logs = mock(TicketLogMapper.class);
        AiReviewStatusCacheService cache = mock(AiReviewStatusCacheService.class);
        when(tickets.selectById(1L)).thenReturn(ticket("REJECTED", null));

        AiReviewManualHandoffService.ManualHandoffResult result = new AiReviewManualHandoffServiceImpl(tickets, logs, cache, mock(AiReviewUserNotificationService.class), new AgentGatewayMetrics())
                .markManualRequired(1L, "event-1", "模型不可用", "DLQ", null, null);

        assertThat(result.applied()).isFalse();
        assertThat(result.rejectReason()).isEqualTo("STATUS_CHANGED");
        verify(tickets, never()).applyManualReviewIfPending(any(), anyString(), anyString(), any(), any(), any());
        verify(logs, never()).insert(any(com.ecommerce.aftersales.entity.TicketLog.class));
    }

    private AfterSalesTicket ticket(String status, String requestId) {
        AfterSalesTicket ticket = new AfterSalesTicket();
        ticket.setId(1L);
        ticket.setStatus(status);
        ticket.setAiReviewRequestId(requestId);
        return ticket;
    }
}
