package com.ecommerce.aftersales.dto;

import lombok.Data;

@Data
public class UpdateUserProfileRequest {

    private String nickname;

    private String avatarUrl;
}
