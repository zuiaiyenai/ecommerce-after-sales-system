package com.ecommerce.aftersales.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import lombok.Data;

@Data
public class SendCodeRequest {

    @NotBlank(message = "不能为空")
    @Pattern(regexp = "^1[3-9]\\d{9}$", message = "格式不正确")
    private String phone;

    @NotBlank(message = "不能为空")
    @Pattern(regexp = "^(REGISTER|RESET_PASSWORD)$", message = "只能是REGISTER或RESET_PASSWORD")
    private String scene;
}
