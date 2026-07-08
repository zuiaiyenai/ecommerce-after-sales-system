package com.ecommerce.aftersales.vo;

import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;

@Data
public class AfterSalesVO {
    private Long id;
    private String ticketNo;
    private Long orderId;
    private String orderNo;
    private Long merchantId;
    private String merchantCode;
    private String merchantDisplayName;
    private String productName;
    private String productImage;
    private String afterSaleType;
    private String reason;
    private String reasonDetail;
    private String description;
    private BigDecimal refundAmount;
    private String aiClassifyResult;
    private BigDecimal aiConfidence;
    private String aiRecommendType;
    private Boolean autoApproved;
    private String status;
    private String statusText;
    private Integer priority;
    private String auditOpinion;
    private LocalDateTime auditTime;
    private LocalDateTime completeTime;
    private LocalDateTime createTime;
    private List<String> attachmentUrls;
    private List<AfterSalesLogVO> logs;
}
