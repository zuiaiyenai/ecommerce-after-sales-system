package com.ecommerce.aftersales.controller;

import com.ecommerce.aftersales.common.ApiResponse;
import com.ecommerce.aftersales.common.BizException;
import com.ecommerce.aftersales.common.annotation.CurrentUserId;
import com.ecommerce.aftersales.request.CreateAfterSalesRequest;
import com.ecommerce.aftersales.response.AfterSalesResponse;
import com.ecommerce.aftersales.service.AfterSalesService;
import com.ecommerce.aftersales.service.RedisRateLimiterService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequiredArgsConstructor
@RequestMapping("/aftersales")
public class AfterSalesController {

    private final AfterSalesService afterSalesService;
    private final RedisRateLimiterService redisRateLimiterService;

    @Value("${app.rate-limit.after-sales-submit.enabled:true}")
    private boolean afterSalesSubmitRateLimitEnabled;

    @Value("${app.rate-limit.after-sales-submit.limit:5}")
    private int afterSalesSubmitRateLimit;

    @Value("${app.rate-limit.after-sales-submit.window-seconds:60}")
    private long afterSalesSubmitRateLimitWindowSeconds;

    @GetMapping
    public ApiResponse<List<AfterSalesResponse>> listByUserId(@CurrentUserId Long userId) {
        return ApiResponse.success("获取成功", afterSalesService.listByUserId(userId));
    }

    @GetMapping("/{id}")
    public ApiResponse<AfterSalesResponse> getById(@PathVariable Long id, @CurrentUserId Long userId) {
        AfterSalesResponse afterSales = afterSalesService.getById(id, userId);
        if (afterSales == null) {
            throw new BizException(404, "售后申请不存在");
        }
        return ApiResponse.success("获取成功", afterSales);
    }

    @GetMapping("/byTicketNo/{ticketNo}")
    public ApiResponse<AfterSalesResponse> getByTicketNo(@PathVariable String ticketNo) {
        AfterSalesResponse afterSales = afterSalesService.getByTicketNo(ticketNo);
        if (afterSales == null) {
            throw new BizException(404, "售后申请不存在");
        }
        return ApiResponse.success("获取成功", afterSales);
    }

    @PostMapping
    public ApiResponse<AfterSalesResponse> create(@CurrentUserId Long userId,
                                                  @Valid @RequestBody CreateAfterSalesRequest request) {
        if (afterSalesSubmitRateLimitEnabled
                && !redisRateLimiterService.tryAcquire("rate:user:" + userId + ":after_sales",
                afterSalesSubmitRateLimit, afterSalesSubmitRateLimitWindowSeconds)) {
            throw new BizException(429, "提交过于频繁，请稍后再试");
        }
        return ApiResponse.success("创建成功", afterSalesService.create(userId, request));
    }
}
