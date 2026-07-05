package com.ecommerce.aftersales.controller;

import com.ecommerce.aftersales.common.ApiResponse;
import com.ecommerce.aftersales.common.annotation.CurrentUserId;
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

    @GetMapping
    public ApiResponse<List<OrderVO>> listByUserId(@CurrentUserId Long userId) {
        return ApiResponse.success("获取成功", orderService.listByUserId(userId));
    }

    @GetMapping("/{id}")
    public ApiResponse<OrderVO> getById(@PathVariable Long id, @CurrentUserId Long userId) {
        OrderVO order = orderService.getById(id, userId);
        if (order == null) {
            return ApiResponse.fail(404, "订单不存在");
        }
        return ApiResponse.success("获取成功", order);
    }

    @PostMapping
    public ApiResponse<OrderVO> create(@CurrentUserId Long userId, @RequestBody CreateOrderRequest request) {
        return ApiResponse.success("创建成功", orderService.create(userId, request));
    }

    @PutMapping("/{id}/status")
    public ApiResponse<Void> updateStatus(@PathVariable Long id,
                                          @CurrentUserId Long userId,
                                          @RequestParam String status) {
        orderService.updateStatus(id, userId, status);
        return ApiResponse.success("更新成功", null);
    }
}
