package com.ecommerce.aftersales.vo;

import com.fasterxml.jackson.databind.annotation.JsonSerialize;
import com.fasterxml.jackson.databind.ser.std.ToStringSerializer;
import lombok.Data;

import java.math.BigDecimal;

@Data
public class OrderItemVO {
    @JsonSerialize(using = ToStringSerializer.class)
    private Long id;
    @JsonSerialize(using = ToStringSerializer.class)
    private Long productId;
    private String productName;
    private String productImage;
    private String productSpec;
    private BigDecimal price;
    private Integer quantity;
    private BigDecimal subtotal;
}
