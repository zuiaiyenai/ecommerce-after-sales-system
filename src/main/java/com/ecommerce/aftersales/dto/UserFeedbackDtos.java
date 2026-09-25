package com.ecommerce.aftersales.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import com.fasterxml.jackson.databind.annotation.JsonSerialize;
import com.fasterxml.jackson.databind.ser.std.ToStringSerializer;
import lombok.Builder;
import lombok.Data;

import java.time.LocalDateTime;

public final class UserFeedbackDtos {
    private UserFeedbackDtos() {
    }

    @Data
    public static class SubmitRequest {
        @NotBlank(message = "反馈类型不能为空")
        @Pattern(regexp = "FUNCTION|EXPERIENCE|BUG|OTHER", message = "反馈类型不正确")
        private String type;

        @NotBlank(message = "反馈内容不能为空")
        @Size(min = 5, max = 1000, message = "反馈内容需为5到1000个字符")
        private String content;

        @Size(max = 100, message = "联系方式不能超过100个字符")
        private String contact;
    }

    @Data
    @Builder
    public static class Response {
        @JsonSerialize(using = ToStringSerializer.class)
        private Long id;
        @JsonSerialize(using = ToStringSerializer.class)
        private Long userId;
        private String type;
        private String content;
        private String contact;
        private String status;
        private LocalDateTime createTime;
        private LocalDateTime updateTime;
    }
}
