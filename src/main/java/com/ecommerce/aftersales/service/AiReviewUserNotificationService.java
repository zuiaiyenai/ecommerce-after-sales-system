package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.entity.AfterSalesTicket;

public interface AiReviewUserNotificationService {

    void notifyReviewApproved(AfterSalesTicket ticket);

    void notifyManualReviewRequired(AfterSalesTicket ticket);
}
