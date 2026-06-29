package com.ecommerce.aftersales.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@TableName("faq")
public class Faq {

    @TableId
    private Long id;

    private String question;

    private String answer;

    private String tags;

    private Integer hitCount;

    private Integer chunkCount;

    private Integer vectorStatus;

    private Integer status;

    private Integer version;

    private Long operatorId;

    @TableLogic
    private Integer deleted;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createTime;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updateTime;
}
