package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.entity.AfterSalesTicket;

public interface AfterSalesReviewEventService {

    void enqueueReviewStarted(AfterSalesTicket ticket, Long sessionId);

    void enqueueReviewResumed(
            AfterSalesTicket ticket,
            Long sessionId,
            String message,
            String eventId,
            Integer evidenceRevision
    );

    void publishPending();
}
