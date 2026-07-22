package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.entity.AfterSalesTicket;

public interface AfterSalesReviewEventService {

    void enqueueReviewRequested(AfterSalesTicket ticket, Long sessionId);

    void publishPending();
}
