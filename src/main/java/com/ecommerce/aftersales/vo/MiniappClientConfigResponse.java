package com.ecommerce.aftersales.vo;

import lombok.Builder;
import lombok.Value;

import java.util.List;

@Value
@Builder
public class MiniappClientConfigResponse {
    String environmentCode;
    String environmentLabel;
    String backendOrigin;
    String apiBaseUrl;
    String agentBaseUrl;
    Integer requestTimeout;
    Integer agentRequestTimeout;
    DemoAccount demoAccount;
    List<Preset> presets;

    @Value
    @Builder
    public static class DemoAccount {
        Boolean enabled;
        String phone;
        String password;
        String nickname;
    }

    @Value
    @Builder
    public static class Preset {
        String code;
        String label;
        String baseOrigin;
        String apiBaseUrl;
        String agentBaseUrl;
        Boolean recommended;
    }
}
