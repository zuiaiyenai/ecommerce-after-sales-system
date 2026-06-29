package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.vo.AfterSalesVO;

import java.util.List;

public interface AfterSalesService {
    List<AfterSalesVO> listByUserId(Long userId);
    AfterSalesVO getById(Long id, Long userId);
    AfterSalesVO getByTicketNo(String ticketNo);
    AfterSalesVO create(AfterSalesVO afterSalesVO);
}
