package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.dto.ShippingAddressDtos;

import java.util.List;

public interface ShippingAddressService {
    List<ShippingAddressDtos.Response> list(Long userId);

    ShippingAddressDtos.Response getDefault(Long userId);

    ShippingAddressDtos.Response create(Long userId, ShippingAddressDtos.UpsertRequest request);

    ShippingAddressDtos.Response update(Long userId, Long addressId, ShippingAddressDtos.UpsertRequest request);

    void delete(Long userId, Long addressId);

    ShippingAddressDtos.Response setDefault(Long userId, Long addressId);
}
