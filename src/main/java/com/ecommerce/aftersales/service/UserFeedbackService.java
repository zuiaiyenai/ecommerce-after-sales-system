package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.common.PageResult;
import com.ecommerce.aftersales.dto.UserFeedbackDtos;

public interface UserFeedbackService {
    UserFeedbackDtos.Response submit(Long userId, UserFeedbackDtos.SubmitRequest request);

    PageResult<UserFeedbackDtos.Response> listForAdmin(Long adminId, long page, long size,
                                                       String status, String type);
}
