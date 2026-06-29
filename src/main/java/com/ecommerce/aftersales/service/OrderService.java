package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.vo.OrderVO;
import com.ecommerce.aftersales.dto.CreateOrderRequest;

import java.util.List;

public interface OrderService {
    List<OrderVO> listByUserId(Long userId);
    OrderVO getById(Long id, Long userId);
    OrderVO create(Long userId, CreateOrderRequest request);
    void updateStatus(Long id, String status);
}
