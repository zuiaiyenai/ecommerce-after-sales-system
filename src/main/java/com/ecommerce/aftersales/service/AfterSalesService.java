package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.request.CreateAfterSalesRequest;
import com.ecommerce.aftersales.response.AfterSalesResponse;

import java.util.List;

public interface AfterSalesService {
    List<AfterSalesResponse> listByUserId(Long userId);
    AfterSalesResponse getById(Long id, Long userId);
    AfterSalesResponse getByTicketNo(String ticketNo);
    AfterSalesResponse create(Long userId, CreateAfterSalesRequest request);
}
