package com.ecommerce.aftersales.request;

import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import lombok.Data;

import java.math.BigDecimal;
import java.util.List;

@Data
public class CreateAfterSalesRequest {

    @NotNull(message = "订单ID不能为空")
    private Long orderId;

    @NotBlank(message = "售后类型不能为空")
    @Size(max = 30, message = "售后类型长度不能超过30")
    private String afterSaleType;

    @NotBlank(message = "售后原因不能为空")
    @Size(max = 50, message = "售后原因长度不能超过50")
    private String reason;

    @Size(max = 100, message = "原因补充长度不能超过100")
    private String reasonDetail;

    @Size(max = 1000, message = "问题描述长度不能超过1000")
    private String description;

    @DecimalMin(value = "0.00", message = "退款金额不能为负数")
    private BigDecimal refundAmount;

    @Size(max = 9, message = "附件最多上传9个")
    private List<@Size(max = 500, message = "附件地址长度不能超过500") String> attachmentUrls;
}
