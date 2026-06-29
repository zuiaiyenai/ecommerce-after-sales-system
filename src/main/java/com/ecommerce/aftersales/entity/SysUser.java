package com.ecommerce.aftersales.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@TableName("sys_user")
public class SysUser {

    @TableId
    private Long id;

    private String username;

    private String password;

    private String realName;

    private String phone;

    private String email;

    private String avatarUrl;

    private String roleType;

    private Integer status;

    private Integer onlineStatus;

    private Integer maxSessions;

    private LocalDateTime lastLoginTime;

    @TableLogic
    private Integer deleted;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createTime;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updateTime;
}
