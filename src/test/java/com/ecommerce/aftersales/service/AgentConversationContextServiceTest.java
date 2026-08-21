package com.ecommerce.aftersales.service;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.ecommerce.aftersales.common.BizException;
import com.ecommerce.aftersales.dto.AgentGatewayDtos;
import com.ecommerce.aftersales.entity.ChatMessage;
import com.ecommerce.aftersales.entity.ChatSession;
import com.ecommerce.aftersales.mapper.ChatMessageMapper;
import com.ecommerce.aftersales.mapper.ChatSessionMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.time.LocalDateTime;
import java.util.List;
import java.util.stream.IntStream;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class AgentConversationContextServiceTest {

    @Mock private ChatSessionMapper chatSessionMapper;
    @Mock private ChatMessageMapper chatMessageMapper;
    @InjectMocks private AgentConversationContextService service;

    @Test
    void replacesClientHistoryWithChronologicalMysqlHistoryAndTrustedBindings() {
        AgentGatewayDtos.ChatRequest request = request("11", 101L);
        request.setOrder_id("forged-order");
        request.setTicket_id("forged-ticket");
        request.setRecent_history(List.of(messageDto("user", "client supplied")));

        ChatSession session = new ChatSession();
        session.setId(101L);
        session.setUserId(11L);
        session.setOrderId(9007199254740995L);
        session.setTicketId(9007199254740993L);
        session.setMode("AI");
        session.setStatus("ACTIVE");
        session.setPolicyCode("REFUND_POLICY");
        session.setPolicyVersion("v2");
        when(chatSessionMapper.selectById(101L)).thenReturn(session);
        when(chatMessageMapper.selectList(any(Wrapper.class))).thenReturn(List.of(
                message(2L, "ASSISTANT", "second", LocalDateTime.now()),
                message(1L, "USER", "first", LocalDateTime.now().minusMinutes(1))
        ));

        service.hydrateTrustedContext(request);

        assertThat(request.getOrder_id()).isEqualTo("9007199254740995");
        assertThat(request.getTicket_id()).isEqualTo("9007199254740993");
        assertThat(request.getRecent_history()).extracting(AgentGatewayDtos.ConversationMessageDto::getContent)
                .containsExactly("first", "second");
        assertThat(request.getRecent_history()).extracting(AgentGatewayDtos.ConversationMessageDto::getRole)
                .containsExactly("user", "assistant");
        assertThat(request.getHistory_summary())
                .containsEntry("source", "mysql")
                .containsEntry("authoritative", true)
                .containsEntry("message_count", 2)
                .containsEntry("policy_version", "v2");
    }

    @Test
    void rejectsAConversationOwnedByAnotherUser() {
        AgentGatewayDtos.ChatRequest request = request("12", 101L);
        ChatSession session = new ChatSession();
        session.setId(101L);
        session.setUserId(11L);
        when(chatSessionMapper.selectById(101L)).thenReturn(session);

        assertThatThrownBy(() -> service.hydrateTrustedContext(request))
                .isInstanceOf(BizException.class)
                .extracting("code")
                .isEqualTo(404);
    }

    @Test
    void discardsClientHistoryEvenWhenNoSessionIsBound() {
        AgentGatewayDtos.ChatRequest request = request("11", null);
        request.setRecent_history(List.of(messageDto("user", "client supplied")));

        service.hydrateTrustedContext(request);

        assertThat(request.getRecent_history()).isEmpty();
        assertThat(request.getHistory_summary()).containsEntry("source", "mysql");
    }

    @Test
    void keepsTenRecentMessagesAndMarksOlderSummaryAsNonAuthoritative() {
        AgentGatewayDtos.ChatRequest request = request("11", 101L);
        ChatSession session = new ChatSession();
        session.setId(101L);
        session.setUserId(11L);
        session.setMode("AI");
        session.setStatus("ACTIVE");
        when(chatSessionMapper.selectById(101L)).thenReturn(session);
        List<ChatMessage> newestFirst = IntStream.rangeClosed(1, 14)
                .mapToObj(index -> message(
                        (long) index,
                        index % 2 == 0 ? "USER" : "ASSISTANT",
                        "message-" + index,
                        LocalDateTime.now().plusMinutes(index)))
                .sorted((left, right) -> right.getId().compareTo(left.getId()))
                .toList();
        when(chatMessageMapper.selectList(any(Wrapper.class))).thenReturn(newestFirst);

        service.hydrateTrustedContext(request);

        assertThat(request.getRecent_history()).hasSize(10);
        assertThat(request.getRecent_history().get(0).getContent()).isEqualTo("message-5");
        assertThat(request.getHistory_summary())
                .containsEntry("window_message_count", 14)
                .containsEntry("message_count", 10)
                .containsEntry("conversation_summary_authoritative", false)
                .containsEntry("summary_through_message_id", "4")
                .containsEntry("current_user_goal", "message-14");
        assertThat(String.valueOf(request.getHistory_summary().get("conversation_summary")))
                .contains("message-1")
                .contains("message-4");
    }

    @Test
    void persistsCurrentUserMessageBeforeCallingAgent() {
        AgentGatewayDtos.ChatRequest request = request("11", 101L);
        request.setMessage("耳机外壳破裂，希望退款");
        ChatSession session = new ChatSession();
        session.setId(101L);
        session.setUserId(11L);
        session.setMode("AI");
        session.setStatus("AI_ACTIVE");
        when(chatSessionMapper.selectById(101L)).thenReturn(session);

        service.persistCurrentUserMessage(request);

        ArgumentCaptor<ChatMessage> messageCaptor = ArgumentCaptor.forClass(ChatMessage.class);
        verify(chatMessageMapper).insert(messageCaptor.capture());
        assertThat(messageCaptor.getValue().getSessionId()).isEqualTo(101L);
        assertThat(messageCaptor.getValue().getRole()).isEqualTo("USER");
        assertThat(messageCaptor.getValue().getMessageType()).isEqualTo("TEXT");
        assertThat(messageCaptor.getValue().getContent()).isEqualTo("耳机外壳破裂，希望退款");
        assertThat(session.getUserQuery()).isEqualTo("耳机外壳破裂，希望退款");
        assertThat(session.getUserHidden()).isZero();
        verify(chatSessionMapper).updateById(session);
    }

    private static AgentGatewayDtos.ChatRequest request(String userId, Long sessionId) {
        AgentGatewayDtos.ChatRequest request = new AgentGatewayDtos.ChatRequest();
        request.setUser_id(userId);
        request.setSession_id(sessionId);
        return request;
    }

    private static AgentGatewayDtos.ConversationMessageDto messageDto(String role, String content) {
        AgentGatewayDtos.ConversationMessageDto dto = new AgentGatewayDtos.ConversationMessageDto();
        dto.setRole(role);
        dto.setContent(content);
        return dto;
    }

    private static ChatMessage message(Long id, String role, String content, LocalDateTime createTime) {
        ChatMessage message = new ChatMessage();
        message.setId(id);
        message.setRole(role);
        message.setContent(content);
        message.setCreateTime(createTime);
        return message;
    }
}
