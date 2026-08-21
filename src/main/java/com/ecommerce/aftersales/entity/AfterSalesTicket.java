package com.ecommerce.aftersales.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDateTime;

@Data
@TableName("after_sales_ticket")
public class AfterSalesTicket {

    @TableId
    private Long id;

    private String ticketNo;

    private Long orderId;

    private String orderNo;

    private Long userId;

    private Long merchantId;

    private String merchantCode;

    private String policyCode;

    private String policyVersion;

    private String productName;

    private String afterSaleType;

    private String reason;

    private String reasonDetail;

    private String description;

    private BigDecimal refundAmount;

    private String aiReviewAuditJson;

    /** AI review confidence for the current audit decision. */
    private BigDecimal aiReviewConfidence;

    private String aiSuggestedAfterSaleType;

    private String aiReviewRequestId;

    private String aiReviewStatus;

    private Integer evidenceRevision;

    private String aiReviewResult;

    private String aiReviewReason;

    private LocalDateTime aiReviewTime;

    private Integer manualReviewRequired;

    private String status;

    private Integer priority;

    private Long assigneeId;

    private String auditOpinion;

    private LocalDateTime auditTime;

    private LocalDateTime expectedCompleteTime;

    private LocalDateTime completeTime;

    @TableLogic
    private Integer deleted;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createTime;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updateTime;

    /** Compatibility alias for callers that have not migrated to aiSuggestedAfterSaleType yet. */
    public String getAiRecommendType() {
        return aiSuggestedAfterSaleType;
    }

    public void setAiRecommendType(String aiRecommendType) {
        this.aiSuggestedAfterSaleType = aiRecommendType;
    }

    /** Compatibility alias for callers that have not migrated to aiReviewConfidence yet. */
    public BigDecimal getAiConfidence() {
        return aiReviewConfidence;
    }

    public void setAiConfidence(BigDecimal aiConfidence) {
        this.aiReviewConfidence = aiConfidence;
    }
}
