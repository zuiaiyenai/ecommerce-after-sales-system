package com.ecommerce.aftersales.vo;

import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;

@Data
public class OrderVO {
    private Long id;
    private String orderNo;
    private Long merchantId;
    private String merchantCode;
    private BigDecimal totalAmount;
    private BigDecimal payAmount;
    private String status;
    private String statusText;
    private String receiverName;
    private String receiverPhone;
    private String receiverAddress;
    private String trackingCompany;
    private String trackingNo;
    private LocalDateTime payTime;
    private LocalDateTime shipTime;
    private LocalDateTime receiveTime;
    private LocalDateTime createTime;
    private List<OrderItemVO> items;
}
