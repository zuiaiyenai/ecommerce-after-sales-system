package com.ecommerce.aftersales.dto;

import lombok.Data;

@Data
public class CreateOrderRequest {
    private Long productId;
    private Integer quantity;
    private String receiverName;
    private String receiverPhone;
    private String receiverAddress;
    private String status;
}
