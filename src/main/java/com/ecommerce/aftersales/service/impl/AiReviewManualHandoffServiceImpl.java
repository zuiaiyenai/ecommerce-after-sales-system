package com.ecommerce.aftersales.service.impl;

import com.ecommerce.aftersales.entity.AfterSalesTicket;
import com.ecommerce.aftersales.entity.TicketLog;
import com.ecommerce.aftersales.mapper.AfterSalesTicketMapper;
import com.ecommerce.aftersales.mapper.TicketLogMapper;
import com.ecommerce.aftersales.service.AiReviewManualHandoffService;
import com.ecommerce.aftersales.service.AiReviewStatusCacheService;
import com.ecommerce.aftersales.service.AiReviewUserNotificationService;
import com.ecommerce.aftersales.service.AgentGatewayMetrics;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;

@Service
@RequiredArgsConstructor
@Slf4j
public class AiReviewManualHandoffServiceImpl implements AiReviewManualHandoffService {

    private final AfterSalesTicketMapper afterSalesTicketMapper;
    private final TicketLogMapper ticketLogMapper;
    private final AiReviewStatusCacheService aiReviewStatusCacheService;
    private final AiReviewUserNotificationService aiReviewUserNotificationService;
    private final AgentGatewayMetrics metrics;

    @Override
    @Transactional(rollbackFor = Exception.class)
    public ManualHandoffResult markManualRequired(
            Long ticketId,
            String reviewRequestId,
            Integer evidenceRevision,
            String reason,
            String source,
            String auditPayload,
            BigDecimal confidence
    ) {
        AfterSalesTicket ticket = ticketId == null ? null : afterSalesTicketMapper.selectById(ticketId);
        if (ticket == null || !StringUtils.hasText(reviewRequestId)) {
            log.warn("ai_review_manual_handoff ticket_id={} review_request_id={} transition=rejected failure_class=TICKET_NOT_FOUND",
                    ticketId, reviewRequestId);
            return new ManualHandoffResult(ticket, false, false, "TICKET_NOT_FOUND");
        }
        if (reviewRequestId.equals(ticket.getAiReviewRequestId()) && ticket.getAiReviewResult() != null) {
            log.info("ai_review_manual_handoff ticket_id={} review_request_id={} transition=idempotent source={}",
                    ticketId, reviewRequestId, normalizeSource(source));
            return new ManualHandoffResult(ticket, false, true, null);
        }
        if (!reviewRequestId.equals(ticket.getAiReviewRequestId())) {
            return new ManualHandoffResult(ticket, false, false, "INSTANCE_MISMATCH");
        }
        if (evidenceRevision != null && !evidenceRevision.equals(ticket.getEvidenceRevision())) {
            return new ManualHandoffResult(ticket, false, false, "STALE_EVIDENCE");
        }
        if (!List.of("PENDING", "PENDING_REVIEW").contains(ticket.getStatus())) {
            log.info("ai_review_manual_handoff ticket_id={} review_request_id={} transition=stale source={} failure_class=STATUS_CHANGED",
                    ticketId, reviewRequestId, normalizeSource(source));
            return new ManualHandoffResult(ticket, false, false, "STATUS_CHANGED");
        }

        String previousStatus = ticket.getStatus();
        LocalDateTime now = LocalDateTime.now();
        String normalizedReason = shortText(reason, 500);
        int changed = afterSalesTicketMapper.applyManualReviewIfPending(
                ticket.getId(), reviewRequestId, evidenceRevision, normalizedReason, auditPayload, confidence, now
        );
        if (changed == 0) {
            AfterSalesTicket current = afterSalesTicketMapper.selectById(ticket.getId());
            if (current != null && reviewRequestId.equals(current.getAiReviewRequestId())) {
                log.info("ai_review_manual_handoff ticket_id={} review_request_id={} transition=idempotent source={}",
                        ticketId, reviewRequestId, normalizeSource(source));
                return new ManualHandoffResult(current, false, true, null);
            }
            log.info("ai_review_manual_handoff ticket_id={} review_request_id={} transition=stale source={} failure_class=STALE_REVIEW",
                    ticketId, reviewRequestId, normalizeSource(source));
            return new ManualHandoffResult(current, false, false, "STALE_REVIEW");
        }

        AfterSalesTicket updated = afterSalesTicketMapper.selectById(ticket.getId());
        TicketLog log = new TicketLog();
        log.setTicketId(ticket.getId());
        log.setOperatorType("SYSTEM");
        log.setAction("AI_REVIEW_MANUAL_" + normalizeSource(source));
        log.setFromStatus(previousStatus);
        log.setToStatus(updated == null ? "PENDING_REVIEW" : updated.getStatus());
        log.setContent(firstNonBlank(normalizedReason, "AI初审需要人工复核"));
        ticketLogMapper.insert(log);
        aiReviewUserNotificationService.notifyManualReviewRequired(updated == null ? ticket : updated);
        runAfterCommit(() -> {
            aiReviewStatusCacheService.cacheStatus(ticket.getId(), "MANUAL_REQUIRED");
            metrics.recordAiReviewManualHandoff(source);
            this.log.info("ai_review_manual_handoff ticket_id={} review_request_id={} transition=manual_required source={}",
                    ticketId, reviewRequestId, normalizeSource(source));
        });
        return new ManualHandoffResult(updated, true, false, null);
    }

    private String normalizeSource(String source) {
        String value = StringUtils.hasText(source) ? source.trim().toUpperCase() : "UNKNOWN";
        return value.replaceAll("[^A-Z0-9_]+", "_");
    }

    private String shortText(String value, int limit) {
        if (!StringUtils.hasText(value)) {
            return "";
        }
        String text = value.trim();
        return text.length() <= limit ? text : text.substring(0, limit);
    }

    private String firstNonBlank(String... values) {
        for (String value : values) {
            if (StringUtils.hasText(value)) {
                return value;
            }
        }
        return "";
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
