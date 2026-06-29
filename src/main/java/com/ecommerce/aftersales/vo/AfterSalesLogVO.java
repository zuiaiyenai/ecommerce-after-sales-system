package com.ecommerce.aftersales.vo;

import lombok.Data;

import java.time.LocalDateTime;

@Data
public class AfterSalesLogVO {
    private Long id;
    private String operatorType;
    private String fromStatus;
    private String toStatus;
    private String action;
    private String content;
    private LocalDateTime createTime;
}
