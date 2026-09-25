package com.ecommerce.aftersales.controller;

import com.ecommerce.aftersales.config.ChatWebSocketHandler;
import com.ecommerce.aftersales.dto.UserChatDtos.CreateSessionRequest;
import com.ecommerce.aftersales.entity.ChatSession;
import com.ecommerce.aftersales.mapper.AfterSalesTicketMapper;
import com.ecommerce.aftersales.mapper.ChatMessageMapper;
import com.ecommerce.aftersales.mapper.ChatSessionMapper;
import com.ecommerce.aftersales.mapper.OrderInfoMapper;
import com.ecommerce.aftersales.service.ChatEmotionAnalysisService;
import com.ecommerce.aftersales.service.NotificationService;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.time.LocalDateTime;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class UserChatControllerTest {

    @Test
    void forceNewClosesExistingConversationBeforeCreatingAnother() {
        ChatSessionMapper sessionMapper = mock(ChatSessionMapper.class);
        ChatMessageMapper messageMapper = mock(ChatMessageMapper.class);
        ChatSession existing = new ChatSession();
        existing.setId(10L);
        existing.setStatus("WAITING");
        existing.setMerchantCode("MERCHANT_DEMO");
        when(sessionMapper.selectOne(any())).thenReturn(existing);
        doAnswer(invocation -> {
            ChatSession inserted = invocation.getArgument(0);
            inserted.setId(20L);
            inserted.setCreateTime(LocalDateTime.now());
            return 1;
        }).when(sessionMapper).insert(any(ChatSession.class));

        UserChatController controller = new UserChatController(
                sessionMapper,
                messageMapper,
                mock(AfterSalesTicketMapper.class),
                mock(OrderInfoMapper.class),
                mock(ChatWebSocketHandler.class),
                mock(NotificationService.class),
                mock(ChatEmotionAnalysisService.class));
        CreateSessionRequest request = new CreateSessionRequest();
        request.setForceNew(true);

        var response = controller.createSession(1L, request);

        assertThat(response.getData().getSessionId()).isEqualTo(20L);
        assertThat(existing.getStatus()).isEqualTo("CLOSED");
        assertThat(existing.getCloseTime()).isNotNull();
        ArgumentCaptor<ChatSession> inserted = ArgumentCaptor.forClass(ChatSession.class);
        verify(sessionMapper).insert(inserted.capture());
        assertThat(inserted.getValue().getStatus()).isEqualTo("AI_ACTIVE");
        verify(sessionMapper, times(1)).updateById(existing);
    }
}
