package com.ecommerce.aftersales.response;

import com.ecommerce.aftersales.common.OffsetLocalDateTimeSerializer;
import com.fasterxml.jackson.databind.annotation.JsonSerialize;
import com.fasterxml.jackson.databind.ser.std.ToStringSerializer;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;

@Data
public class AfterSalesResponse {

    @JsonSerialize(using = ToStringSerializer.class)
    private Long ticketId;

    private String ticketNo;

    @JsonSerialize(using = ToStringSerializer.class)
    private Long orderId;

    private String orderNo;

    @JsonSerialize(using = ToStringSerializer.class)
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

    private String aiReviewAuditJson;

    private BigDecimal aiReviewConfidence;

    private String aiSuggestedAfterSaleType;

    private String aiReviewResult;

    private String aiReviewStatus;

    private Boolean manualReviewRequired;

    private Boolean autoApproved;

    private String status;

    private String statusText;

    private Integer priority;

    private String auditOpinion;

    @JsonSerialize(using = OffsetLocalDateTimeSerializer.class)
    private LocalDateTime auditTime;

    @JsonSerialize(using = OffsetLocalDateTimeSerializer.class)
    private LocalDateTime completeTime;

    @JsonSerialize(using = OffsetLocalDateTimeSerializer.class)
    private LocalDateTime createTime;

    private List<String> attachmentUrls;

    private List<AfterSalesLogResponse> logs;
}
