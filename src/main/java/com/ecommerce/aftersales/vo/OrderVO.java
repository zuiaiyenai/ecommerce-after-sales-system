package com.ecommerce.aftersales.vo;

import com.ecommerce.aftersales.common.OffsetLocalDateTimeSerializer;
import com.fasterxml.jackson.databind.annotation.JsonSerialize;
import com.fasterxml.jackson.databind.ser.std.ToStringSerializer;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;

@Data
public class OrderVO {
    @JsonSerialize(using = ToStringSerializer.class)
    private Long orderId;
    private String orderNo;
    @JsonSerialize(using = ToStringSerializer.class)
    private Long merchantId;
    private String merchantCode;
    private String merchantDisplayName;
    private BigDecimal totalAmount;
    private BigDecimal payAmount;
    private String status;
    private String statusText;
    private String receiverName;
    private String receiverPhone;
    private String receiverAddress;
    private String trackingCompany;
    private String trackingNo;
    private Boolean hasOpenAfterSales;
    private Boolean hasAnyAfterSales;
    private String afterSalesStatus;
    private String afterSalesStatusText;
    private String latestTicketId;
    private String latestTicketNo;
    @JsonSerialize(using = OffsetLocalDateTimeSerializer.class)
    private LocalDateTime payTime;
    @JsonSerialize(using = OffsetLocalDateTimeSerializer.class)
    private LocalDateTime shipTime;
    @JsonSerialize(using = OffsetLocalDateTimeSerializer.class)
    private LocalDateTime receiveTime;
    @JsonSerialize(using = OffsetLocalDateTimeSerializer.class)
    private LocalDateTime createTime;
    private List<OrderItemVO> items;
}
