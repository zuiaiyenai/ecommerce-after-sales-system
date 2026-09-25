package com.ecommerce.aftersales.service.impl;

import com.ecommerce.aftersales.common.BizException;
import com.ecommerce.aftersales.dto.ShippingAddressDtos;
import com.ecommerce.aftersales.entity.ShippingAddress;
import com.ecommerce.aftersales.mapper.ShippingAddressMapper;
import org.junit.jupiter.api.Test;

import java.time.LocalDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class ShippingAddressServiceImplTest {

    @Test
    void listsOnlyAddressesOwnedByCurrentUser() {
        ShippingAddressMapper mapper = mock(ShippingAddressMapper.class);
        ShippingAddress address = address(11L, 7L, 1);
        when(mapper.selectByUserId(7L)).thenReturn(List.of(address));
        ShippingAddressServiceImpl service = new ShippingAddressServiceImpl(mapper);

        var result = service.list(7L);

        assertThat(result).hasSize(1);
        assertThat(result.getFirst().getId()).isEqualTo(11L);
        verify(mapper).selectByUserId(7L);
    }

    @Test
    void createsDefaultAddressForAuthenticatedUserAndClearsPreviousDefault() {
        ShippingAddressMapper mapper = mock(ShippingAddressMapper.class);
        doAnswer(invocation -> {
            ShippingAddress inserted = invocation.getArgument(0);
            inserted.setId(12L);
            inserted.setCreateTime(LocalDateTime.now());
            inserted.setUpdateTime(LocalDateTime.now());
            return 1;
        }).when(mapper).insert(any(ShippingAddress.class));
        ShippingAddressServiceImpl service = new ShippingAddressServiceImpl(mapper);

        var result = service.create(7L, request(true));

        verify(mapper).clearDefault(7L);
        verify(mapper).insert(any(ShippingAddress.class));
        assertThat(result.getId()).isEqualTo(12L);
        assertThat(result.isDefault()).isTrue();
        assertThat(result.getName()).isEqualTo("张三");
    }

    @Test
    void rejectsUpdatingAddressThatIsNotOwnedByCurrentUser() {
        ShippingAddressMapper mapper = mock(ShippingAddressMapper.class);
        when(mapper.selectOwned(7L, 99L)).thenReturn(null);
        ShippingAddressServiceImpl service = new ShippingAddressServiceImpl(mapper);

        assertThatThrownBy(() -> service.update(7L, 99L, request(false)))
                .isInstanceOf(BizException.class)
                .extracting("code")
                .isEqualTo(404);

        verify(mapper).selectOwned(7L, 99L);
        verify(mapper, never()).updateById(any(ShippingAddress.class));
    }

    @Test
    void setsDefaultOnlyAfterOwnershipCheck() {
        ShippingAddressMapper mapper = mock(ShippingAddressMapper.class);
        ShippingAddress owned = address(11L, 7L, 0);
        when(mapper.selectOwned(7L, 11L)).thenReturn(owned);
        doReturn(1).when(mapper).updateOwned(7L, owned);
        ShippingAddressServiceImpl service = new ShippingAddressServiceImpl(mapper);

        var result = service.setDefault(7L, 11L);

        verify(mapper).clearDefault(7L);
        verify(mapper).updateOwned(7L, owned);
        assertThat(result.isDefault()).isTrue();
    }

    @Test
    void updatesWithUserIdInTheFinalWritePredicate() {
        ShippingAddressMapper mapper = mock(ShippingAddressMapper.class);
        ShippingAddress owned = address(11L, 7L, 0);
        when(mapper.selectOwned(7L, 11L)).thenReturn(owned);
        when(mapper.updateOwned(7L, owned)).thenReturn(1);
        ShippingAddressServiceImpl service = new ShippingAddressServiceImpl(mapper);

        service.update(7L, 11L, request(false));

        verify(mapper).updateOwned(7L, owned);
        verify(mapper, never()).updateById(any(ShippingAddress.class));
    }

    private static ShippingAddressDtos.UpsertRequest request(boolean isDefault) {
        ShippingAddressDtos.UpsertRequest request = new ShippingAddressDtos.UpsertRequest();
        request.setName(" 张三 ");
        request.setPhone("13800138001");
        request.setProvince("北京市");
        request.setCity("北京市");
        request.setDistrict("朝阳区");
        request.setDetail("三里屯路19号院");
        request.setDefault(isDefault);
        return request;
    }

    private static ShippingAddress address(Long id, Long userId, int isDefault) {
        ShippingAddress address = new ShippingAddress();
        address.setId(id);
        address.setUserId(userId);
        address.setName("张三");
        address.setPhone("13800138001");
        address.setProvince("北京市");
        address.setCity("北京市");
        address.setDistrict("朝阳区");
        address.setDetail("三里屯路19号院");
        address.setIsDefault(isDefault);
        address.setCreateTime(LocalDateTime.now());
        address.setUpdateTime(LocalDateTime.now());
        return address;
    }

}
