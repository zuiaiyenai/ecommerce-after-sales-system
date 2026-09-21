package com.ecommerce.aftersales.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ecommerce.aftersales.common.BizException;
import com.ecommerce.aftersales.dto.AgentGatewayDtos;
import com.ecommerce.aftersales.entity.AfterSalesTicket;
import com.ecommerce.aftersales.entity.ChatMessage;
import com.ecommerce.aftersales.entity.ChatSession;
import com.ecommerce.aftersales.entity.OrderInfo;
import com.ecommerce.aftersales.entity.OrderItem;
import com.ecommerce.aftersales.entity.ProductInfo;
import com.ecommerce.aftersales.mapper.AfterSalesTicketMapper;
import com.ecommerce.aftersales.mapper.ChatMessageMapper;
import com.ecommerce.aftersales.mapper.ChatSessionMapper;
import com.ecommerce.aftersales.mapper.OrderInfoMapper;
import com.ecommerce.aftersales.mapper.OrderItemMapper;
import com.ecommerce.aftersales.mapper.ProductInfoMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/** Builds the short-term Agent context exclusively from Java-owned business data. */
@Service
@RequiredArgsConstructor
public class AgentConversationContextService {

    private static final int CONTEXT_WINDOW_LIMIT = 60;
    private static final int RECENT_MESSAGE_LIMIT = 10;
    private static final int SUMMARY_MAX_CHARS = 1200;
    private static final int USER_GOAL_MAX_CHARS = 300;
    private static final ZoneId BUSINESS_ZONE = ZoneId.of("Asia/Shanghai");

    private final ChatSessionMapper chatSessionMapper;
    private final ChatMessageMapper chatMessageMapper;
    private final OrderInfoMapper orderInfoMapper;
    private final OrderItemMapper orderItemMapper;
    private final ProductInfoMapper productInfoMapper;
    private final AfterSalesTicketMapper afterSalesTicketMapper;

    public void hydrateTrustedContext(AgentGatewayDtos.ChatRequest request) {
        request.setRecent_history(List.of());
        request.setHistory_summary(emptySummary());
        request.setSelected_order(null);
        if (request.getSession_id() == null) {
            hydrateSelectedOrder(request);
            return;
        }

        ChatSession session = chatSessionMapper.selectById(request.getSession_id());
        if (session == null || !belongsToUser(session, request.getUser_id())) {
            throw new BizException(404, "会话不存在");
        }

        request.setOrder_id(stringId(session.getOrderId()));
        request.setTicket_id(stringId(session.getTicketId()));
        hydrateSelectedOrder(request);

        List<ChatMessage> newestFirst = chatMessageMapper.selectList(
                new LambdaQueryWrapper<ChatMessage>()
                        .eq(ChatMessage::getSessionId, session.getId())
                        .orderByDesc(ChatMessage::getCreateTime)
                        .orderByDesc(ChatMessage::getId)
                        .last("LIMIT " + CONTEXT_WINDOW_LIMIT)
        );
        List<ChatMessage> chronological = new ArrayList<>(newestFirst == null ? List.of() : newestFirst);
        Collections.reverse(chronological);
        List<ChatMessage> nonBlankMessages = chronological.stream()
                .filter(message -> message.getContent() != null && !message.getContent().isBlank())
                .toList();
        int recentStart = Math.max(0, nonBlankMessages.size() - RECENT_MESSAGE_LIMIT);
        List<ChatMessage> summarizedMessages = nonBlankMessages.subList(0, recentStart);
        List<AgentGatewayDtos.ConversationMessageDto> history = nonBlankMessages.subList(
                        recentStart,
                        nonBlankMessages.size())
                .stream()
                .map(this::toConversationMessage)
                .toList();
        request.setRecent_history(history);

        Map<String, Object> summary = emptySummary();
        summary.put("session_id", stringId(session.getId()));
        summary.put("session_mode", session.getMode());
        summary.put("session_status", session.getStatus());
        summary.put("order_id", stringId(session.getOrderId()));
        summary.put("ticket_id", stringId(session.getTicketId()));
        summary.put("policy_code", session.getPolicyCode());
        summary.put("policy_version", session.getPolicyVersion());
        summary.put("message_count", history.size());
        summary.put("window_message_count", nonBlankMessages.size());
        summary.put("conversation_summary_authoritative", false);
        summary.put("conversation_summary_type", "deterministic_mysql_window");
        summary.put("conversation_summary", summarizeMessages(summarizedMessages));
        summary.put("summary_through_message_id", summarizedMessages.isEmpty()
                ? null
                : stringId(summarizedMessages.get(summarizedMessages.size() - 1).getId()));
        summary.put("current_user_goal", currentUserGoal(nonBlankMessages));
        summary.put("user_claims", recentUserClaims(nonBlankMessages));
        request.setHistory_summary(summary);
    }

    private void hydrateSelectedOrder(AgentGatewayDtos.ChatRequest request) {
        if (!StringUtils.hasText(request.getOrder_id())) {
            return;
        }
        Long orderId;
        Long userId;
        try {
            orderId = Long.valueOf(request.getOrder_id());
            userId = Long.valueOf(request.getUser_id());
        } catch (NumberFormatException exception) {
            throw new BizException(404, "订单不存在");
        }
        OrderInfo order = orderInfoMapper.selectOne(new LambdaQueryWrapper<OrderInfo>()
                .eq(OrderInfo::getId, orderId)
                .eq(OrderInfo::getUserId, userId)
                .last("limit 1"));
        if (order == null) {
            throw new BizException(404, "订单不存在");
        }

        OrderItem item = orderItemMapper.selectOne(new LambdaQueryWrapper<OrderItem>()
                .eq(OrderItem::getOrderId, orderId)
                .orderByAsc(OrderItem::getId)
                .last("limit 1"));
        ProductInfo product = item == null || item.getProductId() == null
                ? null
                : productInfoMapper.selectById(item.getProductId());
        AfterSalesTicket ticket = afterSalesTicketMapper.selectOne(new LambdaQueryWrapper<AfterSalesTicket>()
                .eq(AfterSalesTicket::getOrderId, orderId)
                .orderByDesc(AfterSalesTicket::getCreateTime)
                .orderByDesc(AfterSalesTicket::getId)
                .last("limit 1"));

        AgentGatewayDtos.SelectedOrderDto selected = new AgentGatewayDtos.SelectedOrderDto();
        selected.setOrder_id(order.getId().toString());
        selected.setUser_id(order.getUserId().toString());
        selected.setMerchant_code(order.getMerchantCode());
        selected.setProduct_name(product == null ? null : product.getProductName());
        selected.setCategory(product == null ? null : product.getCategory());
        selected.setPolicy_version(ticket == null ? null : ticket.getPolicyVersion());
        LocalDateTime businessTime = ticket != null && ticket.getCreateTime() != null
                ? ticket.getCreateTime()
                : order.getCreateTime();
        selected.setBusiness_time(businessTime == null
                ? null
                : businessTime.atZone(BUSINESS_ZONE).toOffsetDateTime().toString());
        selected.setStatus(order.getStatus());
        selected.setAfter_sales_status(ticket == null ? null : ticket.getStatus());
        selected.setAmount(order.getPayAmount() == null ? null : order.getPayAmount().doubleValue());
        request.setSelected_order(selected);
        if (request.getTicket_id() == null && ticket != null) {
            request.setTicket_id(ticket.getId().toString());
        }
    }

    @Transactional(rollbackFor = Exception.class)
    public void persistCurrentUserMessage(AgentGatewayDtos.ChatRequest request) {
        if (request.getSession_id() == null || !StringUtils.hasText(request.getMessage())) {
            return;
        }
        ChatSession session = chatSessionMapper.selectById(request.getSession_id());
        if (session == null || !belongsToUser(session, request.getUser_id())) {
            throw new BizException(404, "会话不存在");
        }

        LocalDateTime now = LocalDateTime.now();
        ChatMessage message = new ChatMessage();
        message.setSessionId(session.getId());
        message.setRole("USER");
        message.setMessageType("TEXT");
        message.setContent(request.getMessage().trim());
        message.setCreateTime(now);
        chatMessageMapper.insert(message);

        session.setUserQuery(compactText(message.getContent(), USER_GOAL_MAX_CHARS));
        session.setUserHidden(0);
        session.setUpdateTime(now);
        chatSessionMapper.updateById(session);
    }

    private boolean belongsToUser(ChatSession session, String userId) {
        try {
            return userId != null && Objects.equals(session.getUserId(), Long.valueOf(userId));
        } catch (NumberFormatException ignored) {
            return false;
        }
    }

    private AgentGatewayDtos.ConversationMessageDto toConversationMessage(ChatMessage message) {
        AgentGatewayDtos.ConversationMessageDto dto = new AgentGatewayDtos.ConversationMessageDto();
        dto.setRole("USER".equalsIgnoreCase(message.getRole()) ? "user" : "assistant");
        dto.setContent(message.getContent());
        return dto;
    }

    private Map<String, Object> emptySummary() {
        Map<String, Object> summary = new LinkedHashMap<>();
        summary.put("source", "mysql");
        summary.put("authoritative", true);
        summary.put("message_count", 0);
        return summary;
    }

    private String summarizeMessages(List<ChatMessage> messages) {
        StringBuilder summary = new StringBuilder();
        for (ChatMessage message : messages) {
            String role = "USER".equalsIgnoreCase(message.getRole()) ? "用户" : "客服";
            String content = compactText(message.getContent(), 180);
            if (content.isBlank()) {
                continue;
            }
            String item = role + "：" + content;
            if (summary.length() > 0) {
                item = "；" + item;
            }
            if (summary.length() + item.length() > SUMMARY_MAX_CHARS) {
                int remaining = SUMMARY_MAX_CHARS - summary.length();
                if (remaining > 0) {
                    summary.append(item, 0, Math.min(remaining, item.length()));
                }
                break;
            }
            summary.append(item);
        }
        return summary.toString();
    }

    private String currentUserGoal(List<ChatMessage> messages) {
        for (int index = messages.size() - 1; index >= 0; index--) {
            ChatMessage message = messages.get(index);
            if ("USER".equalsIgnoreCase(message.getRole())) {
                return compactText(message.getContent(), USER_GOAL_MAX_CHARS);
            }
        }
        return "";
    }

    private List<String> recentUserClaims(List<ChatMessage> messages) {
        List<String> claims = new ArrayList<>();
        for (int index = messages.size() - 1; index >= 0 && claims.size() < 5; index--) {
            ChatMessage message = messages.get(index);
            if ("USER".equalsIgnoreCase(message.getRole())) {
                String claim = compactText(message.getContent(), 240);
                if (!claim.isBlank() && !claims.contains(claim)) {
                    claims.add(claim);
                }
            }
        }
        Collections.reverse(claims);
        return claims;
    }

    private String compactText(String value, int limit) {
        if (value == null) {
            return "";
        }
        String normalized = value.replaceAll("\\s+", " ").trim();
        return normalized.length() <= limit ? normalized : normalized.substring(0, limit);
    }

    private String stringId(Long value) {
        return value == null ? null : value.toString();
    }
}
