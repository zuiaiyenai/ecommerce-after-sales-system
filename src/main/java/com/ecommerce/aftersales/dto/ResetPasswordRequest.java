package com.ecommerce.aftersales.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import lombok.Data;

@Data
public class ResetPasswordRequest {

    @NotBlank(message = "不能为空")
    @Pattern(regexp = "^1[3-9]\\d{9}$", message = "格式不正确")
    private String phone;

    @NotBlank(message = "不能为空")
    private String code;

    @NotBlank(message = "不能为空")
    @Size(min = 6, max = 32, message = "长度应为6到32位")
    private String newPassword;

    @NotBlank(message = "不能为空")
    @Size(min = 6, max = 32, message = "长度应为6到32位")
    private String confirmPassword;
}
