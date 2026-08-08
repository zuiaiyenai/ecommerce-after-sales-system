package com.ecommerce.aftersales.response;

import com.ecommerce.aftersales.common.OffsetLocalDateTimeSerializer;
import com.fasterxml.jackson.databind.annotation.JsonSerialize;
import com.fasterxml.jackson.databind.ser.std.ToStringSerializer;
import lombok.Data;

import java.time.LocalDateTime;

@Data
public class AfterSalesLogResponse {

    @JsonSerialize(using = ToStringSerializer.class)
    private Long id;

    private String operatorType;

    private String fromStatus;

    private String toStatus;

    private String action;

    private String content;

    @JsonSerialize(using = OffsetLocalDateTimeSerializer.class)
    private LocalDateTime createTime;
}
