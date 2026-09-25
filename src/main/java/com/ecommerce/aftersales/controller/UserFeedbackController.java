package com.ecommerce.aftersales.controller;

import com.ecommerce.aftersales.common.ApiResponse;
import com.ecommerce.aftersales.common.PageResult;
import com.ecommerce.aftersales.common.annotation.CurrentUserId;
import com.ecommerce.aftersales.dto.UserFeedbackDtos;
import com.ecommerce.aftersales.service.UserFeedbackService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequiredArgsConstructor
public class UserFeedbackController {
    private final UserFeedbackService userFeedbackService;

    @PostMapping("/miniapp/user/feedback")
    public ApiResponse<UserFeedbackDtos.Response> submit(
            @CurrentUserId Long userId,
            @Valid @RequestBody UserFeedbackDtos.SubmitRequest request) {
        return ApiResponse.success("反馈提交成功", userFeedbackService.submit(userId, request));
    }

    @GetMapping("/admin/feedback")
    public ApiResponse<PageResult<UserFeedbackDtos.Response>> listForAdmin(
            @CurrentUserId Long adminId,
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "20") long size,
            @RequestParam(required = false) String status,
            @RequestParam(required = false) String type) {
        return ApiResponse.success(userFeedbackService.listForAdmin(adminId, page, size, status, type));
    }
}
