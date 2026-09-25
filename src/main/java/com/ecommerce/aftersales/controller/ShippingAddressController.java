package com.ecommerce.aftersales.controller;

import com.ecommerce.aftersales.common.ApiResponse;
import com.ecommerce.aftersales.common.annotation.CurrentUserId;
import com.ecommerce.aftersales.dto.ShippingAddressDtos;
import com.ecommerce.aftersales.service.ShippingAddressService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequiredArgsConstructor
@RequestMapping("/miniapp/user/addresses")
public class ShippingAddressController {
    private final ShippingAddressService shippingAddressService;

    @GetMapping
    public ApiResponse<List<ShippingAddressDtos.Response>> list(@CurrentUserId Long userId) {
        return ApiResponse.success(shippingAddressService.list(userId));
    }

    @GetMapping("/default")
    public ApiResponse<ShippingAddressDtos.Response> getDefault(@CurrentUserId Long userId) {
        return ApiResponse.success(shippingAddressService.getDefault(userId));
    }

    @PostMapping
    public ApiResponse<ShippingAddressDtos.Response> create(
            @CurrentUserId Long userId,
            @Valid @RequestBody ShippingAddressDtos.UpsertRequest request) {
        return ApiResponse.success("地址已创建", shippingAddressService.create(userId, request));
    }

    @PutMapping("/{addressId}")
    public ApiResponse<ShippingAddressDtos.Response> update(
            @CurrentUserId Long userId,
            @PathVariable Long addressId,
            @Valid @RequestBody ShippingAddressDtos.UpsertRequest request) {
        return ApiResponse.success("地址已更新", shippingAddressService.update(userId, addressId, request));
    }

    @DeleteMapping("/{addressId}")
    public ApiResponse<Void> delete(@CurrentUserId Long userId, @PathVariable Long addressId) {
        shippingAddressService.delete(userId, addressId);
        return ApiResponse.success("地址已删除", null);
    }

    @PutMapping("/{addressId}/default")
    public ApiResponse<ShippingAddressDtos.Response> setDefault(
            @CurrentUserId Long userId,
            @PathVariable Long addressId) {
        return ApiResponse.success("默认地址已更新", shippingAddressService.setDefault(userId, addressId));
    }
}
