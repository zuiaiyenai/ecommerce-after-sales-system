package com.ecommerce.aftersales.service;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.ecommerce.aftersales.common.BizException;
import com.ecommerce.aftersales.dto.AgentGatewayDtos;
import com.ecommerce.aftersales.entity.ChatMessage;
import com.ecommerce.aftersales.entity.ChatSession;
import com.ecommerce.aftersales.entity.AfterSalesTicket;
import com.ecommerce.aftersales.entity.OrderInfo;
import com.ecommerce.aftersales.entity.OrderItem;
import com.ecommerce.aftersales.entity.ProductInfo;
import com.ecommerce.aftersales.mapper.AfterSalesTicketMapper;
import com.ecommerce.aftersales.mapper.ChatMessageMapper;
import com.ecommerce.aftersales.mapper.ChatSessionMapper;
import com.ecommerce.aftersales.mapper.OrderInfoMapper;
import com.ecommerce.aftersales.mapper.OrderItemMapper;
import com.ecommerce.aftersales.mapper.ProductInfoMapper;
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
    @Mock private OrderInfoMapper orderInfoMapper;
    @Mock private OrderItemMapper orderItemMapper;
    @Mock private ProductInfoMapper productInfoMapper;
    @Mock private AfterSalesTicketMapper afterSalesTicketMapper;
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
        when(orderInfoMapper.selectOne(any(Wrapper.class))).thenReturn(order(9007199254740995L, 11L));
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
    void rebuildsSelectedOrderFromMysqlAndIgnoresClientFields() {
        AgentGatewayDtos.ChatRequest request = request("11", null);
        request.setOrder_id("9001");
        AgentGatewayDtos.SelectedOrderDto forged = new AgentGatewayDtos.SelectedOrderDto();
        forged.setMerchant_code("OTHER_MERCHANT");
        forged.setCategory("forged-category");
        request.setSelected_order(forged);

        OrderInfo order = order(9001L, 11L);
        OrderItem item = new OrderItem();
        item.setId(1L);
        item.setOrderId(9001L);
        item.setProductId(7L);
        ProductInfo product = new ProductInfo();
        product.setId(7L);
        product.setProductName("纯棉圆领T恤");
        product.setCategory("apparel");
        AfterSalesTicket ticket = new AfterSalesTicket();
        ticket.setId(88L);
        ticket.setOrderId(9001L);
        ticket.setStatus("PENDING_REVIEW");
        ticket.setPolicyVersion("2026-07-02-v3");
        ticket.setCreateTime(LocalDateTime.of(2026, 9, 21, 16, 30));
        when(orderInfoMapper.selectOne(any(Wrapper.class))).thenReturn(order);
        when(orderItemMapper.selectOne(any(Wrapper.class))).thenReturn(item);
        when(productInfoMapper.selectById(7L)).thenReturn(product);
        when(afterSalesTicketMapper.selectOne(any(Wrapper.class))).thenReturn(ticket);

        service.hydrateTrustedContext(request);

        assertThat(request.getSelected_order().getMerchant_code()).isEqualTo("MERCHANT_DEMO");
        assertThat(request.getSelected_order().getProduct_name()).isEqualTo("纯棉圆领T恤");
        assertThat(request.getSelected_order().getCategory()).isEqualTo("apparel");
        assertThat(request.getSelected_order().getPolicy_version()).isEqualTo("2026-07-02-v3");
        assertThat(request.getSelected_order().getBusiness_time()).isEqualTo("2026-09-21T16:30+08:00");
        assertThat(request.getTicket_id()).isEqualTo("88");
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

    private static OrderInfo order(Long id, Long userId) {
        OrderInfo order = new OrderInfo();
        order.setId(id);
        order.setUserId(userId);
        order.setMerchantCode("MERCHANT_DEMO");
        order.setPayAmount(java.math.BigDecimal.valueOf(35));
        order.setStatus("AFTERSALE");
        order.setCreateTime(LocalDateTime.of(2026, 9, 21, 16, 29));
        return order;
    }
}
