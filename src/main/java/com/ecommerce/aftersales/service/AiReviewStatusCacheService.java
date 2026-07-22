package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.entity.AfterSalesTicket;

import java.util.Optional;

public interface AiReviewStatusCacheService {

    void cacheStatus(Long ticketId, String status);

    Optional<String> getStatus(Long ticketId);

    String resolveStatus(AfterSalesTicket ticket);
}
