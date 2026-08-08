package com.ecommerce.aftersales.vo;

import com.fasterxml.jackson.databind.annotation.JsonSerialize;
import com.fasterxml.jackson.databind.ser.std.ToStringSerializer;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class LoginResponse {

    private String token;

    @JsonSerialize(using = ToStringSerializer.class)
    private Long userId;

    private String userAccount;

    private String phone;

    private String nickname;

    private String avatarUrl;

    private Integer bindStatus;
}
