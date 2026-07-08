package com.ecommerce.aftersales.dto;

import lombok.Data;

import java.util.List;

public final class AdminConsoleDtos {

    private AdminConsoleDtos() {
    }

    @Data
    public static class AdminLoginRequest {
        private String account;
        private String password;
    }

    @Data
    public static class AdminLoginResponse {
        private String token;
        private AdminProfile admin;
    }

    @Data
    public static class AdminProfile {
        private Long adminId;
        private String account;
        private String realName;
        private String role;
        private String scope;
        private String phone;
    }

    @Data
    public static class AdminOverview {
        private String greeting;
        private String subtitle;
        private List<StatItem> stats;
        private List<String> focus;
    }

    @Data
    public static class StatItem {
        private String label;
        private Object value;
        private String accent;
    }

    @Data
    public static class ServiceAccountUpsertRequest {
        private String account;
        private String realName;
        private String merchantCode;
        private String phone;
        private String role;
        private String status;
        private Integer maxSessionCount;
        private String knowledgeScope;
        private String note;
    }

    @Data
    public static class ServiceAccountView {
        private Long id;
        private String staffNo;
        private String account;
        private String realName;
        private String merchantCode;
        private String phone;
        private String role;
        private String status;
        private String onlineStatus;
        private Integer maxSessionCount;
        private Integer currentSessionCount;
        private String knowledgeScope;
        private String lastLoginTime;
        private String note;
    }

    @Data
    public static class PasswordResetView {
        private Long accountId;
        private String account;
        private String temporaryPassword;
    }
}
