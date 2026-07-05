package com.ecommerce.aftersales.controller;

import com.ecommerce.aftersales.common.ApiResponse;
import com.ecommerce.aftersales.common.annotation.CurrentUserId;
import com.ecommerce.aftersales.service.AfterSalesService;
import com.ecommerce.aftersales.vo.AfterSalesVO;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequiredArgsConstructor
@RequestMapping("/aftersales")
public class AfterSalesController {

    private final AfterSalesService afterSalesService;

    @GetMapping
    public ApiResponse<List<AfterSalesVO>> listByUserId(@CurrentUserId Long userId) {
        return ApiResponse.success("获取成功", afterSalesService.listByUserId(userId));
    }

    @GetMapping("/{id}")
    public ApiResponse<AfterSalesVO> getById(@PathVariable Long id, @CurrentUserId Long userId) {
        AfterSalesVO afterSales = afterSalesService.getById(id, userId);
        if (afterSales == null) {
            return ApiResponse.fail(404, "售后申请不存在");
        }
        return ApiResponse.success("获取成功", afterSales);
    }

    @GetMapping("/byTicketNo/{ticketNo}")
    public ApiResponse<AfterSalesVO> getByTicketNo(@PathVariable String ticketNo) {
        AfterSalesVO afterSales = afterSalesService.getByTicketNo(ticketNo);
        if (afterSales == null) {
            return ApiResponse.fail(404, "售后申请不存在");
        }
        return ApiResponse.success("获取成功", afterSales);
    }

    @PostMapping
    public ApiResponse<AfterSalesVO> create(@CurrentUserId Long userId, @RequestBody AfterSalesVO afterSalesVO) {
        return ApiResponse.success("创建成功", afterSalesService.create(userId, afterSalesVO));
    }
}
