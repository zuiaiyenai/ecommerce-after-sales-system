package com.ecommerce.aftersales.controller;

import com.ecommerce.aftersales.config.ChatWebSocketHandler;
import com.ecommerce.aftersales.dto.InternalAgentToolDtos;
import com.ecommerce.aftersales.dto.WsChatMessage;
import com.ecommerce.aftersales.entity.ChatMessage;
import com.ecommerce.aftersales.entity.ChatSession;
import com.ecommerce.aftersales.mapper.AfterSalesTicketMapper;
import com.ecommerce.aftersales.mapper.ChatMessageMapper;
import com.ecommerce.aftersales.mapper.ChatSessionMapper;
import com.ecommerce.aftersales.mapper.OrderInfoMapper;
import com.ecommerce.aftersales.mapper.OrderItemMapper;
import com.ecommerce.aftersales.mapper.ProductInfoMapper;
import com.ecommerce.aftersales.mapper.TicketAttachmentMapper;
import com.ecommerce.aftersales.mapper.TicketLogMapper;
import com.ecommerce.aftersales.service.AgentGatewayMetrics;
import com.ecommerce.aftersales.service.AgentPolicyCatalogService;
import com.ecommerce.aftersales.service.AiReviewManualHandoffService;
import com.ecommerce.aftersales.service.AiReviewStatusCacheService;
import com.ecommerce.aftersales.service.AiReviewUserNotificationService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.time.LocalDateTime;

import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class InternalAgentToolsControllerMessageBroadcastTest {

    @Test
    void broadcastsPersistedAssistantMessageOnlyAfterTransactionCommit() {
        ChatSessionMapper sessionMapper = mock(ChatSessionMapper.class);
        ChatMessageMapper messageMapper = mock(ChatMessageMapper.class);
        ChatWebSocketHandler webSocketHandler = mock(ChatWebSocketHandler.class);

        ChatSession session = new ChatSession();
        session.setId(12L);
        session.setUserId(7L);
        session.setMerchantCode("MERCHANT_DEMO");
        when(sessionMapper.selectById(12L)).thenReturn(session);
        doAnswer(invocation -> {
            ChatMessage message = invocation.getArgument(0);
            message.setId(100L);
            message.setCreateTime(LocalDateTime.of(2026, 7, 30, 12, 40));
            return 1;
        }).when(messageMapper).insert(org.mockito.ArgumentMatchers.any(ChatMessage.class));

        InternalAgentToolsController controller = new InternalAgentToolsController(
                mock(OrderInfoMapper.class),
                mock(OrderItemMapper.class),
                mock(ProductInfoMapper.class),
                mock(AfterSalesTicketMapper.class),
                mock(TicketAttachmentMapper.class),
                mock(TicketLogMapper.class),
                sessionMapper,
                messageMapper,
                mock(AgentPolicyCatalogService.class),
                mock(AiReviewStatusCacheService.class),
                mock(AiReviewManualHandoffService.class),
                mock(AiReviewUserNotificationService.class),
                new AgentGatewayMetrics(),
                new ObjectMapper(),
                webSocketHandler
        );

        InternalAgentToolDtos.AppendMessageRequest request = new InternalAgentToolDtos.AppendMessageRequest();
        request.setUserId(7L);
        request.setSessionId(12L);
        request.setRole("ASSISTANT");
        request.setMessageType("TEXT");
        request.setContent("为便于继续审核，请补充：商品问题照片。");

        TransactionSynchronizationManager.initSynchronization();
        try {
            controller.appendMessage("", request);

            verify(webSocketHandler, never()).broadcastToSession(eq(12L), org.mockito.ArgumentMatchers.any());
            for (TransactionSynchronization synchronization
                    : TransactionSynchronizationManager.getSynchronizations()) {
                synchronization.afterCommit();
            }

            verify(webSocketHandler).broadcastToSession(eq(12L), argThat(payload -> {
                WsChatMessage message = (WsChatMessage) payload;
                return "message".equals(message.getAction())
                        && "ASSISTANT".equals(message.getRole())
                        && "TEXT".equals(message.getMessageType())
                        && "为便于继续审核，请补充：商品问题照片。".equals(message.getContent());
            }));
        } finally {
            TransactionSynchronizationManager.clearSynchronization();
        }
    }

    @Test
    void handoffPersistsAndBroadcastsUserFacingNotice() {
        ChatSessionMapper sessionMapper = mock(ChatSessionMapper.class);
        ChatMessageMapper messageMapper = mock(ChatMessageMapper.class);
        ChatWebSocketHandler webSocketHandler = mock(ChatWebSocketHandler.class);

        ChatSession session = new ChatSession();
        session.setId(12L);
        session.setUserId(7L);
        session.setMerchantCode("MERCHANT_DEMO");
        when(sessionMapper.selectById(12L)).thenReturn(session);

        InternalAgentToolsController controller = new InternalAgentToolsController(
                mock(OrderInfoMapper.class),
                mock(OrderItemMapper.class),
                mock(ProductInfoMapper.class),
                mock(AfterSalesTicketMapper.class),
                mock(TicketAttachmentMapper.class),
                mock(TicketLogMapper.class),
                sessionMapper,
                messageMapper,
                mock(AgentPolicyCatalogService.class),
                mock(AiReviewStatusCacheService.class),
                mock(AiReviewManualHandoffService.class),
                mock(AiReviewUserNotificationService.class),
                new AgentGatewayMetrics(),
                new ObjectMapper(),
                webSocketHandler
        );
        InternalAgentToolDtos.HandoffRequest request = new InternalAgentToolDtos.HandoffRequest();
        request.setUserId(7L);
        request.setSessionId(12L);
        request.setSummary("需要人工进一步核验");

        controller.handoff("", request);

        verify(messageMapper).insert(argThat((ChatMessage message) ->
                "SYSTEM".equals(message.getRole())
                        && "TEXT".equals(message.getMessageType())
                        && message.getContent().contains("已转接人工客服")
        ));
        verify(webSocketHandler).broadcastToSession(eq(12L), argThat(payload -> {
            WsChatMessage message = (WsChatMessage) payload;
            return "SYSTEM".equals(message.getRole())
                    && message.getContent().contains("已转接人工客服");
        }));
    }
}
