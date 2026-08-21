package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.request.SupplementAfterSalesRequest;
import com.ecommerce.aftersales.response.SupplementAfterSalesResponse;

public interface AfterSalesSupplementService {

    SupplementAfterSalesResponse supplement(
            Long userId,
            Long ticketId,
            SupplementAfterSalesRequest request
    );
}
