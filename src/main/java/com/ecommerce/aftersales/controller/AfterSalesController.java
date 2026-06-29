package com.ecommerce.aftersales.controller;

import com.ecommerce.aftersales.common.ApiResponse;
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

    // 开发阶段默认使用 userId=1
    private static final Long DEFAULT_USER_ID = 1L;

    @GetMapping
    public ApiResponse<List<AfterSalesVO>> listByUserId() {
        return ApiResponse.success("获取成功", afterSalesService.listByUserId(DEFAULT_USER_ID));
    }

    @GetMapping("/{id}")
    public ApiResponse<AfterSalesVO> getById(@PathVariable Long id) {
        AfterSalesVO afterSales = afterSalesService.getById(id, DEFAULT_USER_ID);
        if (afterSales == null) {
            return ApiResponse.fail(404, "售后工单不存在");
        }
        return ApiResponse.success("获取成功", afterSales);
    }

    @GetMapping("/byTicketNo/{ticketNo}")
    public ApiResponse<AfterSalesVO> getByTicketNo(@PathVariable String ticketNo) {
        AfterSalesVO afterSales = afterSalesService.getByTicketNo(ticketNo);
        if (afterSales == null) {
            return ApiResponse.fail(404, "售后工单不存在");
        }
        return ApiResponse.success("获取成功", afterSales);
    }

    @PostMapping
    public ApiResponse<AfterSalesVO> create(@RequestBody AfterSalesVO afterSalesVO) {
        return ApiResponse.success("创建成功", afterSalesService.create(afterSalesVO));
    }
}
