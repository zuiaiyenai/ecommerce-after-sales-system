package com.ecommerce.aftersales.service.impl;

import com.ecommerce.aftersales.dto.MerchantCsDtos.SessionView;
import com.ecommerce.aftersales.entity.AfterSalesTicket;
import com.ecommerce.aftersales.entity.ChatMessage;
import com.ecommerce.aftersales.entity.ChatSession;
import com.ecommerce.aftersales.entity.OrderInfo;
import com.ecommerce.aftersales.entity.User;
import com.ecommerce.aftersales.mapper.AfterSalesTicketMapper;
import com.ecommerce.aftersales.mapper.ChatMessageMapper;
import com.ecommerce.aftersales.mapper.OrderInfoMapper;
import com.ecommerce.aftersales.mapper.UserMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyCollection;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class MerchantCsSessionBatchProjectionTest {

    @Mock private ChatMessageMapper chatMessageMapper;
    @Mock private UserMapper userMapper;
    @Mock private OrderInfoMapper orderInfoMapper;
    @Mock private AfterSalesTicketMapper afterSalesTicketMapper;
    @InjectMocks private MerchantCsServiceImpl service;

    @Test
    @SuppressWarnings("unchecked")
    void batchProjectionUsesFixedQueriesAndPreservesReplyEmotionAndPrioritySemantics() {
        LocalDateTime now = LocalDateTime.now();
        ChatSession assistantSession = session(1L, 11L, 21L, 31L, now.minusMinutes(20));
        ChatSession serviceSession = session(2L, 12L, 22L, 32L, now.minusMinutes(5));

        when(userMapper.selectBatchIds(anyCollection())).thenReturn(List.of(user(11L, "用户甲"), user(12L, "用户乙")));
        when(orderInfoMapper.selectBatchIds(anyCollection())).thenReturn(List.of(order(21L, "O-21"), order(22L, "O-22")));
        when(afterSalesTicketMapper.selectBatchIds(anyCollection())).thenReturn(List.of(ticket(31L, "T-31"), ticket(32L, "T-32")));
        when(chatMessageMapper.selectLatestBySessionIds(anyCollection())).thenReturn(List.of(
                message(101L, 1L, "ASSISTANT", "AI 建议", null, now.minusMinutes(20)),
                message(102L, 2L, "SERVICE", "人工回复", null, now.minusMinutes(5))));
        when(chatMessageMapper.selectRecentUserEmotionsBySessionIds(anyCollection())).thenReturn(List.of(
                message(201L, 1L, "USER", "", new BigDecimal("0.30"), now.minusMinutes(30)),
                message(202L, 1L, "USER", "", new BigDecimal("0.90"), now.minusMinutes(20)),
                message(203L, 2L, "USER", "", new BigDecimal("0.20"), now.minusMinutes(5))));

        List<SessionView> views = ReflectionTestUtils.invokeMethod(
                service,
                "toSessionViews",
                List.of(assistantSession, serviceSession));

        assertThat(views).hasSize(2);
        SessionView assistant = views.get(0);
        SessionView human = views.get(1);
        assertThat(assistant.getLastMessageSender()).isEqualTo("ASSISTANT");
        assertThat(assistant.getReplyStatus()).isEqualTo("UNREPLIED");
        assertThat(assistant.getEmotionTrend()).isEqualTo("UP");
        assertThat(assistant.getRiskLevel()).isEqualTo("HIGH");
        assertThat(human.getLastMessageSender()).isEqualTo("SERVICE");
        assertThat(human.getReplyStatus()).isEqualTo("REPLIED");
        assertThat(human.getWait()).isEqualTo("已回复");
        assertThat(assistant.getWait()).startsWith("等待 ");
        assertThat(assistant.getPriorityScore()).isGreaterThan(human.getPriorityScore());
        assertThat(views.stream().sorted(MerchantSessionPriorityPolicy.sessionComparator()).toList().get(0).getSessionId())
                .isEqualTo(1L);

        verify(userMapper, times(1)).selectBatchIds(anyCollection());
        verify(orderInfoMapper, times(1)).selectBatchIds(anyCollection());
        verify(afterSalesTicketMapper, times(1)).selectBatchIds(anyCollection());
        verify(chatMessageMapper, times(1)).selectLatestBySessionIds(anyCollection());
        verify(chatMessageMapper, times(1)).selectRecentUserEmotionsBySessionIds(anyCollection());
        verify(userMapper, never()).selectById(org.mockito.ArgumentMatchers.any());
        verify(orderInfoMapper, never()).selectById(org.mockito.ArgumentMatchers.any());
        verify(afterSalesTicketMapper, never()).selectById(org.mockito.ArgumentMatchers.any());
    }

    @Test
    @SuppressWarnings("unchecked")
    void messageQueryCountStaysFixedForTwentySessions() {
        LocalDateTime now = LocalDateTime.now();
        List<ChatSession> sessions = java.util.stream.LongStream.rangeClosed(1, 20)
                .mapToObj(id -> session(id, 0L, 0L, 0L, now.minusMinutes(id)))
                .peek(session -> {
                    session.setUserId(null);
                    session.setOrderId(null);
                    session.setTicketId(null);
                })
                .toList();
        when(chatMessageMapper.selectLatestBySessionIds(anyCollection())).thenReturn(List.of());
        when(chatMessageMapper.selectRecentUserEmotionsBySessionIds(anyCollection())).thenReturn(List.of());

        List<SessionView> views = ReflectionTestUtils.invokeMethod(service, "toSessionViews", sessions);

        assertThat(views).hasSize(20);
        verify(chatMessageMapper, times(1)).selectLatestBySessionIds(anyCollection());
        verify(chatMessageMapper, times(1)).selectRecentUserEmotionsBySessionIds(anyCollection());
        verify(userMapper, never()).selectBatchIds(anyCollection());
        verify(orderInfoMapper, never()).selectBatchIds(anyCollection());
        verify(afterSalesTicketMapper, never()).selectBatchIds(anyCollection());
    }

    private static ChatSession session(long id, long userId, long orderId, long ticketId, LocalDateTime updateTime) {
        ChatSession session = new ChatSession();
        session.setId(id);
        session.setSessionNo("S-" + id);
        session.setUserId(userId);
        session.setOrderId(orderId);
        session.setTicketId(ticketId);
        session.setMerchantCode("MERCHANT_DEMO");
        session.setMode("HUMAN");
        session.setStatus("ACTIVE");
        session.setCreateTime(updateTime.minusMinutes(10));
        session.setUpdateTime(updateTime);
        return session;
    }

    private static User user(long id, String nickname) {
        User user = new User();
        user.setId(id);
        user.setNickname(nickname);
        return user;
    }

    private static OrderInfo order(long id, String orderNo) {
        OrderInfo order = new OrderInfo();
        order.setId(id);
        order.setOrderNo(orderNo);
        return order;
    }

    private static AfterSalesTicket ticket(long id, String ticketNo) {
        AfterSalesTicket ticket = new AfterSalesTicket();
        ticket.setId(id);
        ticket.setTicketNo(ticketNo);
        ticket.setProductName("商品-" + id);
        return ticket;
    }

    private static ChatMessage message(
            long id,
            long sessionId,
            String role,
            String content,
            BigDecimal emotionScore,
            LocalDateTime createTime) {
        ChatMessage message = new ChatMessage();
        message.setId(id);
        message.setSessionId(sessionId);
        message.setRole(role);
        message.setContent(content);
        message.setEmotionScore(emotionScore);
        message.setCreateTime(createTime);
        return message;
    }
}
