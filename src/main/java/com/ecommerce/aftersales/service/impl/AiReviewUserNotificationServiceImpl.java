package com.ecommerce.aftersales.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ecommerce.aftersales.config.ChatWebSocketHandler;
import com.ecommerce.aftersales.dto.WsChatMessage;
import com.ecommerce.aftersales.entity.AfterSalesTicket;
import com.ecommerce.aftersales.entity.ChatMessage;
import com.ecommerce.aftersales.entity.ChatSession;
import com.ecommerce.aftersales.mapper.ChatMessageMapper;
import com.ecommerce.aftersales.mapper.ChatSessionMapper;
import com.ecommerce.aftersales.service.AiReviewUserNotificationService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.util.StringUtils;

import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;

@Service
@RequiredArgsConstructor
@Slf4j
public class AiReviewUserNotificationServiceImpl implements AiReviewUserNotificationService {

    private static final String DEFAULT_MERCHANT_CODE = "MERCHANT_DEMO";
    private static final String MODE_AI = "AI";
    private static final String STATUS_AI_ACTIVE = "AI_ACTIVE";
    private static final String STATUS_CLOSED = "CLOSED";
    private static final String MESSAGE_APPROVED = "已通过初步审核，进入处理阶段";
    private static final String MESSAGE_MANUAL_REQUIRED = "已转交人工审核";

    private final ChatSessionMapper chatSessionMapper;
    private final ChatMessageMapper chatMessageMapper;
    private final ChatWebSocketHandler chatWebSocketHandler;

    @Override
    public void notifyReviewApproved(AfterSalesTicket ticket) {
        appendSystemNotification(ticket, MESSAGE_APPROVED, false);
    }

    @Override
    public void notifyManualReviewRequired(AfterSalesTicket ticket) {
        appendSystemNotification(ticket, MESSAGE_MANUAL_REQUIRED, true);
    }

    private void appendSystemNotification(
            AfterSalesTicket ticket,
            String content,
            boolean moveToHumanQueue
    ) {
        if (ticket == null || ticket.getUserId() == null) {
            return;
        }
        ChatSession session = resolveSession(ticket);

        ChatMessage message = new ChatMessage();
        message.setSessionId(session.getId());
        message.setRole("SYSTEM");
        message.setContent(content);
        message.setMessageType("TEXT");
        chatMessageMapper.insert(message);

        LocalDateTime messageTime = message.getCreateTime() == null ? LocalDateTime.now() : message.getCreateTime();
        session.setUserHidden(0);
        session.setUpdateTime(messageTime);
        if (moveToHumanQueue) {
            session.setMode("HUMAN");
            session.setStatus("WAITING");
            session.setResolved(0);
        }
        if (!StringUtils.hasText(session.getUserQuery())) {
            session.setUserQuery(shortText(firstNonBlank(ticket.getProductName(), "售后进度通知"), 500));
        }
        chatSessionMapper.updateById(session);

        Long sessionId = session.getId();
        runAfterCommit(() -> broadcast(sessionId, content, messageTime));
    }

    private ChatSession resolveSession(AfterSalesTicket ticket) {
        ChatSession session = findExistingSession(ticket);
        if (session != null) {
            fillBusinessContext(session, ticket);
            chatSessionMapper.updateById(session);
            return session;
        }

        ChatSession created = new ChatSession();
        created.setSessionNo("CS" + System.currentTimeMillis());
        created.setUserId(ticket.getUserId());
        created.setMode(MODE_AI);
        created.setStatus(STATUS_AI_ACTIVE);
        created.setResolved(0);
        created.setDeleted(0);
        created.setUserHidden(0);
        created.setUserQuery(shortText(firstNonBlank(ticket.getProductName(), "售后进度通知"), 500));
        fillBusinessContext(created, ticket);
        try {
            chatSessionMapper.insert(created);
            return created;
        } catch (DuplicateKeyException duplicateKeyException) {
            ChatSession existing = findExistingSession(ticket);
            if (existing == null) {
                throw duplicateKeyException;
            }
            fillBusinessContext(existing, ticket);
            existing.setUserHidden(0);
            chatSessionMapper.updateById(existing);
            return existing;
        }
    }

    private ChatSession findExistingSession(AfterSalesTicket ticket) {
        LambdaQueryWrapper<ChatSession> wrapper = new LambdaQueryWrapper<ChatSession>()
                .eq(ChatSession::getUserId, ticket.getUserId())
                .eq(ChatSession::getMerchantCode, normalizeMerchantCode(ticket.getMerchantCode()))
                .ne(ChatSession::getStatus, STATUS_CLOSED)
                .orderByDesc(ChatSession::getCreateTime)
                .last("limit 1");
        wrapper.and(group -> {
            group.eq(ChatSession::getTicketId, ticket.getId());
            if (ticket.getOrderId() != null) {
                group.or().eq(ChatSession::getOrderId, ticket.getOrderId());
            }
        });
        return chatSessionMapper.selectOne(wrapper);
    }

    private void fillBusinessContext(ChatSession session, AfterSalesTicket ticket) {
        session.setTicketId(ticket.getId());
        session.setOrderId(ticket.getOrderId());
        session.setMerchantId(ticket.getMerchantId());
        session.setMerchantCode(normalizeMerchantCode(ticket.getMerchantCode()));
    }

    private void broadcast(Long sessionId, String content, LocalDateTime messageTime) {
        try {
            chatWebSocketHandler.broadcastToSession(sessionId, WsChatMessage.builder()
                    .action("message")
                    .sessionId(sessionId)
                    .role("SYSTEM")
                    .content(content)
                    .messageType("TEXT")
                    .createdAt(formatTime(messageTime))
                    .build());
        } catch (Exception e) {
            log.warn("Failed to broadcast AI review notification session_id={}", sessionId, e);
        }
    }

    private String normalizeMerchantCode(String merchantCode) {
        return StringUtils.hasText(merchantCode) ? merchantCode.trim() : DEFAULT_MERCHANT_CODE;
    }

    private String firstNonBlank(String... values) {
        for (String value : values) {
            if (StringUtils.hasText(value)) {
                return value.trim();
            }
        }
        return "";
    }

    private String shortText(String value, int limit) {
        if (!StringUtils.hasText(value)) {
            return "";
        }
        String text = value.trim();
        return text.length() <= limit ? text : text.substring(0, limit);
    }

    private String formatTime(LocalDateTime time) {
        return time == null
                ? null
                : time.atZone(ZoneId.systemDefault()).format(DateTimeFormatter.ISO_OFFSET_DATE_TIME);
    }

    private void runAfterCommit(Runnable action) {
        if (TransactionSynchronizationManager.isSynchronizationActive()) {
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override
                public void afterCommit() {
                    action.run();
                }
            });
            return;
        }
        action.run();
    }
}
