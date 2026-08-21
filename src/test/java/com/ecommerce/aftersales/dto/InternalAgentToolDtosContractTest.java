package com.ecommerce.aftersales.dto;

import com.ecommerce.aftersales.controller.InternalAgentToolsController;
import com.ecommerce.aftersales.entity.AfterSalesTicket;
import com.ecommerce.aftersales.entity.OrderInfo;
import com.ecommerce.aftersales.mapper.AfterSalesTicketMapper;
import com.ecommerce.aftersales.mapper.OrderItemMapper;
import com.ecommerce.aftersales.mapper.TicketAttachmentMapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.lang.reflect.Constructor;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class InternalAgentToolDtosContractTest {

    private final ObjectMapper objectMapper = new ObjectMapper();

    @Test
    void ticketResultSeparatesStringTicketIdFromTicketNumber() {
        InternalAgentToolDtos.TicketResult result = new InternalAgentToolDtos.TicketResult();
        result.setTicketId(9_007_199_254_740_993L);
        result.setTicketNo("AS202607140001");
        result.setOrderId(9_007_199_254_740_995L);
        result.setOrderNo("ORDER-20260714-1");

        JsonNode json = objectMapper.valueToTree(result);

        assertThat(json.path("ticketId").asText()).isEqualTo("9007199254740993");
        assertThat(json.path("ticketNo").asText()).isEqualTo("AS202607140001");
        assertThat(json.path("orderId").asText()).isEqualTo("9007199254740995");
        assertThat(json.path("orderNo").asText()).isEqualTo("ORDER-20260714-1");
        assertThat(json.has("id")).isFalse();
    }

    @Test
    void orderSummaryUsesExplicitStringOrderId() {
        InternalAgentToolDtos.OrderSummary result = new InternalAgentToolDtos.OrderSummary();
        result.setOrderId(9_007_199_254_740_993L);
        result.setOrderNo("ORDER-20260714-2");

        JsonNode json = objectMapper.valueToTree(result);

        assertThat(json.path("orderId").asText()).isEqualTo("9007199254740993");
        assertThat(json.path("orderNo").asText()).isEqualTo("ORDER-20260714-2");
        assertThat(json.has("id")).isFalse();
    }

    @Test
    void internalAgentOrderAndTicketExposeJavaOwnedPolicyTimes() {
        InternalAgentToolsController controller = instantiateController();
        OrderInfo order = new OrderInfo();
        order.setId(9_007_199_254_740_993L);
        order.setCreateTime(LocalDateTime.of(2026, 6, 1, 10, 30));
        AfterSalesTicket ticket = new AfterSalesTicket();
        ticket.setId(9_007_199_254_740_995L);
        ticket.setPolicyVersion("v2");
        ticket.setReason("商品质量问题");
        ticket.setReasonDetail("外壳破裂");
        ticket.setDescription("刚拆封使用就发现耳机外壳破裂，希望退款。");
        ticket.setCreateTime(LocalDateTime.of(2026, 7, 20, 9, 0));

        InternalAgentToolDtos.OrderSummary orderResult = ReflectionTestUtils.invokeMethod(
                controller, "toOrderSummary", order);
        InternalAgentToolDtos.TicketResult ticketResult = ReflectionTestUtils.invokeMethod(
                controller, "toTicketResult", ticket, true);
        JsonNode orderJson = objectMapper.valueToTree(orderResult);
        JsonNode ticketJson = objectMapper.valueToTree(ticketResult);

        assertThat(OffsetDateTime.parse(orderJson.path("createTime").asText())).isNotNull();
        assertThat(ticketJson.path("policyVersion").asText()).isEqualTo("v2");
        assertThat(ticketJson.path("reason").asText()).isEqualTo("商品质量问题");
        assertThat(ticketJson.path("reasonDetail").asText()).isEqualTo("外壳破裂");
        assertThat(ticketJson.path("description").asText())
                .isEqualTo("刚拆封使用就发现耳机外壳破裂，希望退款。");
        assertThat(OffsetDateTime.parse(ticketJson.path("afterSalesAppliedAt").asText())).isNotNull();
    }

    @Test
    void userChatUsesTicketIdAndOnlyProducesTicketId() throws Exception {
        UserChatDtos.CreateSessionRequest request = objectMapper.readValue(
                "{\"ticketId\":\"9007199254740993\",\"orderId\":\"9007199254740995\"}",
                UserChatDtos.CreateSessionRequest.class);
        assertThat(request.getTicketId()).isEqualTo(9_007_199_254_740_993L);

        UserChatDtos.ChatSessionSummary summary = new UserChatDtos.ChatSessionSummary();
        summary.setSessionId(9_007_199_254_740_991L);
        summary.setOrderId(9_007_199_254_740_995L);
        summary.setTicketId(9_007_199_254_740_993L);
        JsonNode json = objectMapper.valueToTree(summary);

        assertThat(json.path("sessionId").asText()).isEqualTo("9007199254740991");
        assertThat(json.path("orderId").asText()).isEqualTo("9007199254740995");
        assertThat(json.path("ticketId").asText()).isEqualTo("9007199254740993");
        assertThat(json.has("afterSaleId")).isFalse();
    }

    @Test
    void userChatRejectsRemovedAfterSaleIdContract() {
        org.assertj.core.api.Assertions.assertThatThrownBy(() -> objectMapper.readValue(
                        "{\"afterSaleId\":\"9007199254740993\"}",
                        UserChatDtos.CreateSessionRequest.class))
                .isInstanceOf(com.fasterxml.jackson.core.JsonProcessingException.class);
    }

    @Test
    void userChatResponseIdsAreSerializedAsStrings() {
        UserChatDtos.ChatHistoryResponse history = new UserChatDtos.ChatHistoryResponse();
        history.setSessionId(9_007_199_254_740_991L);
        history.setNextBeforeMessageId(9_007_199_254_740_997L);
        UserChatDtos.ChatMessageView message = new UserChatDtos.ChatMessageView();
        message.setMessageId(9_007_199_254_740_999L);
        history.setList(java.util.List.of(message));

        JsonNode json = objectMapper.valueToTree(history);
        assertThat(json.path("sessionId").asText()).isEqualTo("9007199254740991");
        assertThat(json.path("nextBeforeMessageId").asText()).isEqualTo("9007199254740997");
        assertThat(json.path("list").get(0).path("messageId").asText()).isEqualTo("9007199254740999");
        assertThat(json.path("list").get(0).has("id")).isFalse();
    }

    private InternalAgentToolsController instantiateController() {
        try {
            Constructor<?> constructor = InternalAgentToolsController.class.getDeclaredConstructors()[0];
            constructor.setAccessible(true);
            InternalAgentToolsController controller = (InternalAgentToolsController) constructor.newInstance(
                    new Object[constructor.getParameterCount()]);
            OrderItemMapper orderItemMapper = mock(OrderItemMapper.class);
            AfterSalesTicketMapper ticketMapper = mock(AfterSalesTicketMapper.class);
            TicketAttachmentMapper attachmentMapper = mock(TicketAttachmentMapper.class);
            when(orderItemMapper.selectOne(any())).thenReturn(null);
            when(ticketMapper.selectOne(any())).thenReturn(null);
            when(attachmentMapper.selectList(any())).thenReturn(List.of());
            ReflectionTestUtils.setField(controller, "orderItemMapper", orderItemMapper);
            ReflectionTestUtils.setField(controller, "afterSalesTicketMapper", ticketMapper);
            ReflectionTestUtils.setField(controller, "ticketAttachmentMapper", attachmentMapper);
            return controller;
        } catch (ReflectiveOperationException exception) {
            throw new AssertionError(exception);
        }
    }
}
