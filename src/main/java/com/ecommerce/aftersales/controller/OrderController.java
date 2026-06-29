package com.ecommerce.aftersales.controller;

import com.ecommerce.aftersales.common.ApiResponse;
import com.ecommerce.aftersales.dto.CreateOrderRequest;
import com.ecommerce.aftersales.service.OrderService;
import com.ecommerce.aftersales.vo.OrderVO;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequiredArgsConstructor
@RequestMapping("/orders")
public class OrderController {

    private final OrderService orderService;

    // 开发阶段默认使用 userId=1
    private static final Long DEFAULT_USER_ID = 1L;

    @GetMapping
    public ApiResponse<List<OrderVO>> listByUserId() {
        return ApiResponse.success("获取成功", orderService.listByUserId(DEFAULT_USER_ID));
    }

    @GetMapping("/{id}")
    public ApiResponse<OrderVO> getById(@PathVariable Long id) {
        OrderVO order = orderService.getById(id, DEFAULT_USER_ID);
        if (order == null) {
            return ApiResponse.fail(404, "订单不存在");
        }
        return ApiResponse.success("获取成功", order);
    }

    @PostMapping
    public ApiResponse<OrderVO> create(@RequestBody CreateOrderRequest request) {
        return ApiResponse.success("创建成功", orderService.create(DEFAULT_USER_ID, request));
    }

    @PutMapping("/{id}/status")
    public ApiResponse<Void> updateStatus(@PathVariable Long id, @RequestParam String status) {
        orderService.updateStatus(id, status);
        return ApiResponse.success("更新成功", null);
    }
}
