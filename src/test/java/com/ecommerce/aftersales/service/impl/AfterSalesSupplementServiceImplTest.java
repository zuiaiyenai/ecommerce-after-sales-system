package com.ecommerce.aftersales.service.impl;

import com.ecommerce.aftersales.config.ChatWebSocketHandler;
import com.ecommerce.aftersales.entity.AfterSalesEventOutbox;
import com.ecommerce.aftersales.entity.AfterSalesTicket;
import com.ecommerce.aftersales.entity.ChatMessage;
import com.ecommerce.aftersales.entity.ChatSession;
import com.ecommerce.aftersales.entity.TicketAttachment;
import com.ecommerce.aftersales.mapper.AfterSalesEventOutboxMapper;
import com.ecommerce.aftersales.mapper.AfterSalesTicketMapper;
import com.ecommerce.aftersales.mapper.ChatMessageMapper;
import com.ecommerce.aftersales.mapper.ChatSessionMapper;
import com.ecommerce.aftersales.mapper.TicketAttachmentMapper;
import com.ecommerce.aftersales.mapper.TicketLogMapper;
import com.ecommerce.aftersales.request.SupplementAfterSalesRequest;
import com.ecommerce.aftersales.service.AfterSalesReviewEventService;
import com.ecommerce.aftersales.service.AiReviewStatusCacheService;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.argThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class AfterSalesSupplementServiceImplTest {

    @Test
    void persistsTicketEvidenceAndChatMessagesThenEnqueuesFormalReview() {
        AfterSalesTicketMapper ticketMapper = mock(AfterSalesTicketMapper.class);
        TicketAttachmentMapper attachmentMapper = mock(TicketAttachmentMapper.class);
        TicketLogMapper ticketLogMapper = mock(TicketLogMapper.class);
        ChatSessionMapper sessionMapper = mock(ChatSessionMapper.class);
        ChatMessageMapper messageMapper = mock(ChatMessageMapper.class);
        AfterSalesEventOutboxMapper outboxMapper = mock(AfterSalesEventOutboxMapper.class);
        AfterSalesReviewEventService reviewEvents = mock(AfterSalesReviewEventService.class);

        AfterSalesTicket ticket = new AfterSalesTicket();
        ticket.setId(21L);
        ticket.setUserId(7L);
        ticket.setOrderId(31L);
        ticket.setMerchantId(41L);
        ticket.setMerchantCode("MERCHANT_DEMO");
        ticket.setStatus("PENDING_REVIEW");
        ticket.setManualReviewRequired(0);
        when(ticketMapper.selectById(21L)).thenReturn(ticket);

        ChatSession session = new ChatSession();
        session.setId(12L);
        session.setUserId(7L);
        session.setTicketId(21L);
        session.setMode("AI");
        session.setStatus("AI_ACTIVE");
        when(sessionMapper.selectById(12L)).thenReturn(session);
        when(attachmentMapper.selectList(any())).thenReturn(List.of());
        when(outboxMapper.selectOne(any())).thenReturn(null);

        AfterSalesSupplementServiceImpl service = new AfterSalesSupplementServiceImpl(
                ticketMapper,
                attachmentMapper,
                ticketLogMapper,
                sessionMapper,
                messageMapper,
                outboxMapper,
                reviewEvents,
                mock(AiReviewStatusCacheService.class),
                mock(ChatWebSocketHandler.class)
        );

        SupplementAfterSalesRequest request = new SupplementAfterSalesRequest();
        request.setRequestId("supplement-001");
        request.setSessionId(12L);
        request.setMessage("补充商品破损照片");
        request.setAttachmentUrls(List.of("/uploads/2026/07/30/damage.png"));

        var result = service.supplement(7L, 21L, request);

        verify(attachmentMapper).insert(argThat((TicketAttachment attachment) ->
                Long.valueOf(21L).equals(attachment.getTicketId())
                        && "/uploads/2026/07/30/damage.png".equals(attachment.getFileUrl())
        ));
        verify(messageMapper).insert(argThat((ChatMessage message) ->
                "IMAGE".equals(message.getMessageType())
                        && "/uploads/2026/07/30/damage.png".equals(message.getFileUrl())
        ));
        verify(messageMapper).insert(argThat((ChatMessage message) ->
                "TEXT".equals(message.getMessageType())
                        && "补充商品破损照片".equals(message.getContent())
        ));
        verify(reviewEvents).enqueueReviewRequested(
                ticket,
                12L,
                "补充商品破损照片",
                "supplement-001"
        );
        assertThat(session.getMode()).isEqualTo("AI");
        assertThat(session.getStatus()).isEqualTo("AI_ACTIVE");
        assertThat(ticket.getDescription()).isEqualTo("补充商品破损照片");
        assertThat(result.getEventId()).isEqualTo("supplement-001");
        assertThat(result.getAttachmentCount()).isEqualTo(1);
        assertThat(result.getIdempotent()).isFalse();
    }

    @Test
    void returnsExistingResultForRepeatedSupplementRequest() {
        AfterSalesTicketMapper ticketMapper = mock(AfterSalesTicketMapper.class);
        AfterSalesEventOutboxMapper outboxMapper = mock(AfterSalesEventOutboxMapper.class);
        AfterSalesEventOutbox existing = new AfterSalesEventOutbox();
        existing.setEventId("supplement-001");
        existing.setAggregateId(21L);
        when(outboxMapper.selectOne(any())).thenReturn(existing);
        AfterSalesTicket ticket = new AfterSalesTicket();
        ticket.setId(21L);
        ticket.setUserId(7L);
        ticket.setStatus("PENDING_REVIEW");
        ticket.setManualReviewRequired(0);
        when(ticketMapper.selectById(21L)).thenReturn(ticket);

        AfterSalesSupplementServiceImpl service = new AfterSalesSupplementServiceImpl(
                ticketMapper,
                mock(TicketAttachmentMapper.class),
                mock(TicketLogMapper.class),
                mock(ChatSessionMapper.class),
                mock(ChatMessageMapper.class),
                outboxMapper,
                mock(AfterSalesReviewEventService.class),
                mock(AiReviewStatusCacheService.class),
                mock(ChatWebSocketHandler.class)
        );

        SupplementAfterSalesRequest request = new SupplementAfterSalesRequest();
        request.setRequestId("supplement-001");
        request.setSessionId(12L);
        request.setAttachmentUrls(List.of("/uploads/2026/07/30/damage.png"));

        var result = service.supplement(7L, 21L, request);

        assertThat(result.getIdempotent()).isTrue();
        assertThat(result.getEventId()).isEqualTo("supplement-001");
    }
}
