package com.ecommerce.aftersales.service.impl;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.ecommerce.aftersales.config.ChatWebSocketHandler;
import com.ecommerce.aftersales.entity.AfterSalesTicket;
import com.ecommerce.aftersales.entity.ChatMessage;
import com.ecommerce.aftersales.entity.ChatSession;
import com.ecommerce.aftersales.mapper.ChatMessageMapper;
import com.ecommerce.aftersales.mapper.ChatSessionMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.atLeastOnce;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class AiReviewUserNotificationServiceImplTest {

    @Mock private ChatSessionMapper chatSessionMapper;
    @Mock private ChatMessageMapper chatMessageMapper;
    @Mock private ChatWebSocketHandler chatWebSocketHandler;

    @Test
    void manualReviewNotificationMovesSessionIntoMerchantQueue() {
        ChatSession session = new ChatSession();
        session.setId(101L);
        session.setUserId(11L);
        session.setMode("AI");
        session.setStatus("AI_ACTIVE");
        when(chatSessionMapper.selectOne(any(Wrapper.class))).thenReturn(session);

        AfterSalesTicket ticket = new AfterSalesTicket();
        ticket.setId(201L);
        ticket.setUserId(11L);
        ticket.setOrderId(301L);
        ticket.setMerchantCode("MERCHANT_DEMO");
        AiReviewUserNotificationServiceImpl service = new AiReviewUserNotificationServiceImpl(
                chatSessionMapper,
                chatMessageMapper,
                chatWebSocketHandler
        );

        service.notifyManualReviewRequired(ticket);

        assertThat(session.getMode()).isEqualTo("HUMAN");
        assertThat(session.getStatus()).isEqualTo("WAITING");
        assertThat(session.getTicketId()).isEqualTo(201L);
        assertThat(session.getUserHidden()).isZero();
        verify(chatSessionMapper, atLeastOnce()).updateById(session);
        ArgumentCaptor<ChatMessage> messageCaptor = ArgumentCaptor.forClass(ChatMessage.class);
        verify(chatMessageMapper).insert(messageCaptor.capture());
        assertThat(messageCaptor.getValue().getRole()).isEqualTo("SYSTEM");
    }
}
