package com.ecommerce.aftersales.vo;

import com.fasterxml.jackson.databind.annotation.JsonSerialize;
import com.fasterxml.jackson.databind.ser.std.ToStringSerializer;
import lombok.Data;

import java.math.BigDecimal;

@Data
public class ProductVO {
    @JsonSerialize(using = ToStringSerializer.class)
    private Long id;
    private String productName;
    private String productCode;
    @JsonSerialize(using = ToStringSerializer.class)
    private Long merchantId;
    private String merchantCode;
    private String merchantDisplayName;
    private String category;
    private String description;
    private String mainImage;
    private String images;
    private BigDecimal price;
    private Integer status;
}
