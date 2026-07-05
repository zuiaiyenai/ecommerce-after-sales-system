package com.ecommerce.aftersales.vo;

import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class UserProfileResponse {

    private Long userId;

    private String userAccount;

    private String phone;

    private String nickname;

    private String avatarUrl;

    private Integer bindStatus;
}
