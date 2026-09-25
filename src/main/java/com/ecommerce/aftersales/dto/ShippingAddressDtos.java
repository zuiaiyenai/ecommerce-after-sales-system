package com.ecommerce.aftersales.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import com.fasterxml.jackson.databind.annotation.JsonSerialize;
import com.fasterxml.jackson.databind.ser.std.ToStringSerializer;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Builder;
import lombok.Data;

import java.time.LocalDateTime;

public final class ShippingAddressDtos {
    private ShippingAddressDtos() {
    }

    @Data
    public static class UpsertRequest {
        @NotBlank(message = "收货人不能为空")
        @Size(max = 50, message = "收货人不能超过50个字符")
        private String name;

        @NotBlank(message = "手机号不能为空")
        @Pattern(regexp = "^1\\d{10}$", message = "手机号格式不正确")
        private String phone;

        @NotBlank(message = "省份不能为空")
        @Size(max = 50, message = "省份不能超过50个字符")
        private String province;

        @NotBlank(message = "城市不能为空")
        @Size(max = 50, message = "城市不能超过50个字符")
        private String city;

        @NotBlank(message = "区县不能为空")
        @Size(max = 50, message = "区县不能超过50个字符")
        private String district;

        @NotBlank(message = "详细地址不能为空")
        @Size(max = 255, message = "详细地址不能超过255个字符")
        private String detail;

        @JsonProperty("isDefault")
        private boolean isDefault;
    }

    @Data
    @Builder
    public static class Response {
        @JsonSerialize(using = ToStringSerializer.class)
        private Long id;
        private String name;
        private String phone;
        private String province;
        private String city;
        private String district;
        private String detail;
        @JsonProperty("isDefault")
        private boolean isDefault;
        private LocalDateTime createTime;
        private LocalDateTime updateTime;
    }
}
