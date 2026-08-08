package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.entity.AfterSalesTicket;

import java.math.BigDecimal;

/** Persists the business fact that AI review must be handled by a human. */
public interface AiReviewManualHandoffService {

    ManualHandoffResult markManualRequired(
            Long ticketId,
            String reviewRequestId,
            String reason,
            String source,
            String auditPayload,
            BigDecimal confidence
    );

    record ManualHandoffResult(
            AfterSalesTicket ticket,
            boolean applied,
            boolean idempotentReplay,
            String rejectReason
    ) {
    }
}
