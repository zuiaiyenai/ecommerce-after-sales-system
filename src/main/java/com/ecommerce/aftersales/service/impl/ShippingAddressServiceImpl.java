package com.ecommerce.aftersales.service.impl;

import com.ecommerce.aftersales.common.BizException;
import com.ecommerce.aftersales.dto.ShippingAddressDtos;
import com.ecommerce.aftersales.entity.ShippingAddress;
import com.ecommerce.aftersales.mapper.ShippingAddressMapper;
import com.ecommerce.aftersales.service.ShippingAddressService;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

@Service
@RequiredArgsConstructor
public class ShippingAddressServiceImpl implements ShippingAddressService {
    private final ShippingAddressMapper shippingAddressMapper;

    @Override
    public List<ShippingAddressDtos.Response> list(Long userId) {
        return shippingAddressMapper.selectByUserId(userId)
                .stream()
                .map(ShippingAddressServiceImpl::toResponse)
                .toList();
    }

    @Override
    public ShippingAddressDtos.Response getDefault(Long userId) {
        ShippingAddress address = shippingAddressMapper.selectDefault(userId);
        return address == null ? null : toResponse(address);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public ShippingAddressDtos.Response create(Long userId, ShippingAddressDtos.UpsertRequest request) {
        if (request.isDefault()) {
            clearDefault(userId);
        }
        ShippingAddress address = new ShippingAddress();
        address.setUserId(userId);
        apply(address, request);
        address.setDeleted(0);
        shippingAddressMapper.insert(address);
        return toResponse(address);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public ShippingAddressDtos.Response update(Long userId, Long addressId,
                                                ShippingAddressDtos.UpsertRequest request) {
        ShippingAddress address = requireOwned(userId, addressId);
        if (request.isDefault()) {
            clearDefault(userId);
        }
        apply(address, request);
        updateOwned(userId, address);
        return toResponse(address);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void delete(Long userId, Long addressId) {
        requireOwned(userId, addressId);
        shippingAddressMapper.deleteOwned(userId, addressId);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public ShippingAddressDtos.Response setDefault(Long userId, Long addressId) {
        ShippingAddress address = requireOwned(userId, addressId);
        clearDefault(userId);
        address.setIsDefault(1);
        updateOwned(userId, address);
        return toResponse(address);
    }

    private ShippingAddress requireOwned(Long userId, Long addressId) {
        ShippingAddress address = shippingAddressMapper.selectOwned(userId, addressId);
        if (address == null) {
            throw new BizException(404, "收货地址不存在");
        }
        return address;
    }

    private void clearDefault(Long userId) {
        shippingAddressMapper.clearDefault(userId);
    }

    private void updateOwned(Long userId, ShippingAddress address) {
        if (shippingAddressMapper.updateOwned(userId, address) == 0) {
            throw new BizException(404, "收货地址不存在");
        }
    }

    private static void apply(ShippingAddress address, ShippingAddressDtos.UpsertRequest request) {
        address.setName(request.getName().trim());
        address.setPhone(request.getPhone().trim());
        address.setProvince(request.getProvince().trim());
        address.setCity(request.getCity().trim());
        address.setDistrict(request.getDistrict().trim());
        address.setDetail(request.getDetail().trim());
        address.setIsDefault(request.isDefault() ? 1 : 0);
    }

    private static ShippingAddressDtos.Response toResponse(ShippingAddress address) {
        return ShippingAddressDtos.Response.builder()
                .id(address.getId())
                .name(address.getName())
                .phone(address.getPhone())
                .province(address.getProvince())
                .city(address.getCity())
                .district(address.getDistrict())
                .detail(address.getDetail())
                .isDefault(Integer.valueOf(1).equals(address.getIsDefault()))
                .createTime(address.getCreateTime())
                .updateTime(address.getUpdateTime())
                .build();
    }
}
