package com.ecommerce.aftersales.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.Data;

public final class MiniappUserProfileDtos {
    private MiniappUserProfileDtos() {}

    @Data
    public static class UpdateRequest {
        @NotBlank(message = "昵称不能为空")
        @Size(max = 50, message = "昵称不能超过50个字符")
        private String nickname;

        @Size(max = 255, message = "头像地址不能超过255个字符")
        private String avatarUrl;
    }
}
