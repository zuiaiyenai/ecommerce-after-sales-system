package com.ecommerce.aftersales.vo;

import lombok.Data;

import java.math.BigDecimal;

@Data
public class ProductVO {
    private Long id;
    private String productName;
    private String productCode;
    private String category;
    private String description;
    private String mainImage;
    private String images;
    private BigDecimal price;
    private Integer status;
}
