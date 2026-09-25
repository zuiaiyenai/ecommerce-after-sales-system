package com.ecommerce.aftersales.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.ecommerce.aftersales.entity.ShippingAddress;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.List;

public interface ShippingAddressMapper extends BaseMapper<ShippingAddress> {
    @Select("""
            SELECT id, user_id, name, phone, province, city, district, detail,
                   is_default, deleted, create_time, update_time
            FROM shipping_address
            WHERE user_id = #{userId} AND deleted = 0
            ORDER BY is_default DESC, update_time DESC
            """)
    List<ShippingAddress> selectByUserId(@Param("userId") Long userId);

    @Select("""
            SELECT id, user_id, name, phone, province, city, district, detail,
                   is_default, deleted, create_time, update_time
            FROM shipping_address
            WHERE id = #{addressId} AND user_id = #{userId} AND deleted = 0
            LIMIT 1
            """)
    ShippingAddress selectOwned(@Param("userId") Long userId, @Param("addressId") Long addressId);

    @Select("""
            SELECT id, user_id, name, phone, province, city, district, detail,
                   is_default, deleted, create_time, update_time
            FROM shipping_address
            WHERE user_id = #{userId} AND is_default = 1 AND deleted = 0
            LIMIT 1
            """)
    ShippingAddress selectDefault(@Param("userId") Long userId);

    @Update("""
            UPDATE shipping_address
            SET is_default = 0, update_time = CURRENT_TIMESTAMP
            WHERE user_id = #{userId} AND is_default = 1 AND deleted = 0
            """)
    int clearDefault(@Param("userId") Long userId);

    @Update("""
            UPDATE shipping_address
            SET name = #{address.name},
                phone = #{address.phone},
                province = #{address.province},
                city = #{address.city},
                district = #{address.district},
                detail = #{address.detail},
                is_default = #{address.isDefault},
                update_time = CURRENT_TIMESTAMP
            WHERE id = #{address.id} AND user_id = #{userId} AND deleted = 0
            """)
    int updateOwned(@Param("userId") Long userId, @Param("address") ShippingAddress address);

    @Update("""
            UPDATE shipping_address
            SET deleted = 1, update_time = CURRENT_TIMESTAMP
            WHERE id = #{addressId} AND user_id = #{userId} AND deleted = 0
            """)
    int deleteOwned(@Param("userId") Long userId, @Param("addressId") Long addressId);
}
