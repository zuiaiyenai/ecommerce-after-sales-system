package com.ecommerce.aftersales.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.toolkit.IdWorker;
import com.ecommerce.aftersales.common.BizException;
import com.ecommerce.aftersales.config.ChatWebSocketHandler;
import com.ecommerce.aftersales.dto.WsChatMessage;
import com.ecommerce.aftersales.entity.AfterSalesEventOutbox;
import com.ecommerce.aftersales.entity.AfterSalesTicket;
import com.ecommerce.aftersales.entity.ChatMessage;
import com.ecommerce.aftersales.entity.ChatSession;
import com.ecommerce.aftersales.entity.TicketAttachment;
import com.ecommerce.aftersales.entity.TicketLog;
import com.ecommerce.aftersales.mapper.AfterSalesEventOutboxMapper;
import com.ecommerce.aftersales.mapper.AfterSalesTicketMapper;
import com.ecommerce.aftersales.mapper.ChatMessageMapper;
import com.ecommerce.aftersales.mapper.ChatSessionMapper;
import com.ecommerce.aftersales.mapper.TicketAttachmentMapper;
import com.ecommerce.aftersales.mapper.TicketLogMapper;
import com.ecommerce.aftersales.request.SupplementAfterSalesRequest;
import com.ecommerce.aftersales.response.SupplementAfterSalesResponse;
import com.ecommerce.aftersales.service.AfterSalesReviewEventService;
import com.ecommerce.aftersales.service.AfterSalesSupplementService;
import com.ecommerce.aftersales.service.AiReviewStatusCacheService;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.util.StringUtils;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

@Service
@RequiredArgsConstructor
public class AfterSalesSupplementServiceImpl implements AfterSalesSupplementService {

    private final AfterSalesTicketMapper ticketMapper;
    private final TicketAttachmentMapper attachmentMapper;
    private final TicketLogMapper ticketLogMapper;
    private final ChatSessionMapper sessionMapper;
    private final ChatMessageMapper messageMapper;
    private final AfterSalesEventOutboxMapper outboxMapper;
    private final AfterSalesReviewEventService reviewEventService;
    private final AiReviewStatusCacheService aiReviewStatusCacheService;
    private final ChatWebSocketHandler chatWebSocketHandler;

    @Override
    @Transactional(rollbackFor = Exception.class)
    public SupplementAfterSalesResponse supplement(
            Long userId,
            Long ticketId,
            SupplementAfterSalesRequest request
    ) {
        AfterSalesTicket ticket = ticketMapper.selectById(ticketId);
        if (ticket == null || !userId.equals(ticket.getUserId())) {
            throw new BizException(404, "售后工单不存在");
        }
        if (!isReviewable(ticket)) {
            throw new BizException(409, "当前工单状态不允许触发 AI 补充审核");
        }

        String requestId = request.getRequestId().trim();
        AfterSalesEventOutbox existingEvent = outboxMapper.selectOne(
                new LambdaQueryWrapper<AfterSalesEventOutbox>()
                        .eq(AfterSalesEventOutbox::getEventId, requestId)
                        .last("limit 1")
        );
        if (existingEvent != null) {
            if (!ticketId.equals(existingEvent.getAggregateId())) {
                throw new BizException(409, "补充请求幂等键已被占用");
            }
            return response(ticketId, request.getSessionId(), requestId, 0, true);
        }

        ChatSession session = sessionMapper.selectById(request.getSessionId());
        if (session == null || !userId.equals(session.getUserId())
                || (session.getTicketId() != null && !ticketId.equals(session.getTicketId()))) {
            throw new BizException(404, "售后会话不存在");
        }

        List<TicketAttachment> existingAttachments = attachmentMapper.selectList(
                new LambdaQueryWrapper<TicketAttachment>()
                        .eq(TicketAttachment::getTicketId, ticketId)
                        .orderByAsc(TicketAttachment::getSortOrder)
        );
        Set<String> knownUrls = new LinkedHashSet<>();
        for (TicketAttachment attachment : existingAttachments) {
            if (StringUtils.hasText(attachment.getFileUrl())) {
                knownUrls.add(attachment.getFileUrl());
            }
        }

        int addedAttachmentCount = 0;
        int sortOrder = existingAttachments.size();
        if (request.getAttachmentUrls() != null) {
            for (String rawUrl : request.getAttachmentUrls()) {
                String url = rawUrl == null ? "" : rawUrl.trim();
                if (!StringUtils.hasText(url) || !knownUrls.add(url)) {
                    continue;
                }
                TicketAttachment attachment = new TicketAttachment();
                attachment.setId(IdWorker.getId());
                attachment.setTicketId(ticketId);
                attachment.setFileUrl(url);
                attachment.setFileType("IMAGE");
                attachment.setFileName(extractFilename(url));
                attachment.setFileSize(0L);
                attachment.setSortOrder(sortOrder++);
                attachmentMapper.insert(attachment);
                persistChatMessage(session.getId(), "IMAGE", "[图片]", url);
                addedAttachmentCount++;
            }
        }

        String message = normalizeMessage(request.getMessage());
        if (StringUtils.hasText(message)) {
            persistChatMessage(session.getId(), "TEXT", message, null);
            if (!StringUtils.hasText(ticket.getReasonDetail())
                    && !StringUtils.hasText(ticket.getDescription())) {
                ticket.setDescription(message);
            }
        }
        if (addedAttachmentCount == 0 && !StringUtils.hasText(message)) {
            throw new BizException(400, "请填写补充说明或上传凭证");
        }

        session.setTicketId(ticketId);
        session.setOrderId(ticket.getOrderId());
        session.setMerchantId(ticket.getMerchantId());
        session.setMerchantCode(ticket.getMerchantCode());
        session.setUserHidden(0);
        session.setResolved(0);
        if (StringUtils.hasText(message)) {
            session.setUserQuery(message);
        }
        if (session.getHumanAgentId() == null) {
            session.setMode("AI");
            session.setStatus("AI_ACTIVE");
        }
        session.setUpdateTime(LocalDateTime.now());
        sessionMapper.updateById(session);

        ticket.setAuditOpinion("已收到补充材料，AI 正在重新审核。");
        ticket.setUpdateTime(LocalDateTime.now());
        ticketMapper.updateById(ticket);

        TicketLog log = new TicketLog();
        log.setId(IdWorker.getId());
        log.setTicketId(ticketId);
        log.setOperatorId(userId);
        log.setOperatorType("USER");
        log.setFromStatus(ticket.getStatus());
        log.setToStatus(ticket.getStatus());
        log.setAction("SUPPLEMENT");
        log.setContent("用户补充售后说明或凭证，已重新进入 AI 正式审核。");
        ticketLogMapper.insert(log);

        reviewEventService.enqueueReviewRequested(ticket, session.getId(), message, requestId);
        runAfterCommit(() -> aiReviewStatusCacheService.cacheStatus(ticketId, "AI_REVIEWING"));
        return response(ticketId, session.getId(), requestId, addedAttachmentCount, false);
    }

    private boolean isReviewable(AfterSalesTicket ticket) {
        return !Integer.valueOf(1).equals(ticket.getManualReviewRequired())
                && Set.of("PENDING", "PENDING_REVIEW").contains(
                String.valueOf(ticket.getStatus()).toUpperCase()
        );
    }

    private void persistChatMessage(Long sessionId, String type, String content, String fileUrl) {
        ChatMessage message = new ChatMessage();
        message.setId(IdWorker.getId());
        message.setSessionId(sessionId);
        message.setRole("USER");
        message.setMessageType(type);
        message.setContent(content);
        message.setFileUrl(fileUrl);
        messageMapper.insert(message);
        runAfterCommit(() -> chatWebSocketHandler.broadcastToSession(sessionId, WsChatMessage.builder()
                .action("message")
                .sessionId(sessionId)
                .role("USER")
                .content(content)
                .messageType(type)
                .fileUrl(fileUrl)
                .createdAt(LocalDateTime.now().format(DateTimeFormatter.ISO_LOCAL_DATE_TIME))
                .build()));
    }

    private String normalizeMessage(String value) {
        String message = value == null ? "" : value.trim();
        return "[图片]".equals(message) ? "" : message;
    }

    private String extractFilename(String url) {
        int slash = url.lastIndexOf('/');
        return slash >= 0 ? url.substring(slash + 1) : url;
    }

    private SupplementAfterSalesResponse response(
            Long ticketId,
            Long sessionId,
            String eventId,
            int attachmentCount,
            boolean idempotent
    ) {
        SupplementAfterSalesResponse response = new SupplementAfterSalesResponse();
        response.setTicketId(ticketId);
        response.setSessionId(sessionId);
        response.setEventId(eventId);
        response.setAttachmentCount(attachmentCount);
        response.setIdempotent(idempotent);
        return response;
    }

    private void runAfterCommit(Runnable action) {
        if (!TransactionSynchronizationManager.isSynchronizationActive()) {
            action.run();
            return;
        }
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override
            public void afterCommit() {
                action.run();
            }
        });
    }
}
