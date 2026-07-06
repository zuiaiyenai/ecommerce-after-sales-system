package com.ecommerce.aftersales.controller;

import com.ecommerce.aftersales.common.ApiResponse;
import com.ecommerce.aftersales.config.MiniappClientProperties;
import com.ecommerce.aftersales.vo.MiniappClientConfigResponse;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import org.springframework.util.StringUtils;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

@RestController
@RequiredArgsConstructor
@RequestMapping("/miniapp/public")
public class MiniappClientConfigController {

    private final MiniappClientProperties properties;

    @GetMapping("/client-config")
    public ApiResponse<MiniappClientConfigResponse> getClientConfig(
            HttpServletRequest request,
            @RequestHeader(value = "X-Forwarded-Proto", required = false) String forwardedProto,
            @RequestHeader(value = "X-Forwarded-Host", required = false) String forwardedHost
    ) {
        String backendOrigin = resolveBackendOrigin(request, forwardedProto, forwardedHost);
        String apiBaseUrl = backendOrigin + normalizeApiPath(properties.getApiPath());
        String agentBaseUrl = apiBaseUrl + "/agent";
        List<MiniappClientConfigResponse.Preset> presets = buildPresets(apiBaseUrl, agentBaseUrl);

        return ApiResponse.success(MiniappClientConfigResponse.builder()
                .environmentCode(properties.getEnvironmentCode())
                .environmentLabel(properties.getEnvironmentLabel())
                .backendOrigin(backendOrigin)
                .apiBaseUrl(apiBaseUrl)
                .agentBaseUrl(agentBaseUrl)
                .requestTimeout(properties.getRequestTimeoutMillis())
                .agentRequestTimeout(properties.getAgentRequestTimeoutMillis())
                .demoAccount(buildDemoAccount())
                .presets(presets)
                .build());
    }

    private MiniappClientConfigResponse.DemoAccount buildDemoAccount() {
        MiniappClientProperties.DemoUser demoUser = properties.getDemoUser();
        if (demoUser == null) {
            return MiniappClientConfigResponse.DemoAccount.builder()
                    .enabled(false)
                    .build();
        }
        return MiniappClientConfigResponse.DemoAccount.builder()
                .enabled(Boolean.TRUE.equals(demoUser.getEnabled()))
                .phone(demoUser.getPhone())
                .password(demoUser.getPassword())
                .nickname(demoUser.getNickname())
                .build();
    }

    private List<MiniappClientConfigResponse.Preset> buildPresets(String defaultApiBaseUrl, String defaultAgentBaseUrl) {
        List<MiniappClientConfigResponse.Preset> presets = new ArrayList<>();
        presets.add(MiniappClientConfigResponse.Preset.builder()
                .code("CURRENT")
                .label("当前 Spring Boot 地址")
                .baseOrigin(removeApiSuffix(defaultApiBaseUrl))
                .apiBaseUrl(defaultApiBaseUrl)
                .agentBaseUrl(defaultAgentBaseUrl)
                .recommended(true)
                .build());

        for (MiniappClientProperties.Preset preset : Optional.ofNullable(properties.getPresets()).orElse(List.of())) {
            String baseOrigin = trimTrailingSlash(preset.getBaseOrigin());
            if (!StringUtils.hasText(baseOrigin)) {
                continue;
            }
            String apiBaseUrl = baseOrigin + normalizeApiPath(properties.getApiPath());
            presets.add(MiniappClientConfigResponse.Preset.builder()
                    .code(preset.getCode())
                    .label(preset.getLabel())
                    .baseOrigin(baseOrigin)
                    .apiBaseUrl(apiBaseUrl)
                    .agentBaseUrl(apiBaseUrl + "/agent")
                    .recommended(Boolean.TRUE.equals(preset.getRecommended()))
                    .build());
        }
        return presets;
    }

    private String resolveBackendOrigin(HttpServletRequest request, String forwardedProto, String forwardedHost) {
        String scheme = StringUtils.hasText(forwardedProto) ? forwardedProto : request.getScheme();
        String host = StringUtils.hasText(forwardedHost) ? forwardedHost : request.getHeader("Host");
        if (!StringUtils.hasText(host)) {
            host = request.getServerName() + buildPortSuffix(request.getServerPort(), request.getScheme());
        }
        return scheme + "://" + host;
    }

    private String buildPortSuffix(int port, String scheme) {
        boolean defaultHttp = "http".equalsIgnoreCase(scheme) && port == 80;
        boolean defaultHttps = "https".equalsIgnoreCase(scheme) && port == 443;
        return defaultHttp || defaultHttps ? "" : ":" + port;
    }

    private String normalizeApiPath(String value) {
        String path = StringUtils.hasText(value) ? value.trim() : "/api";
        if (!path.startsWith("/")) {
            path = "/" + path;
        }
        return path.replaceAll("/+$", "");
    }

    private String trimTrailingSlash(String value) {
        return StringUtils.hasText(value) ? value.replaceAll("/+$", "") : "";
    }

    private String removeApiSuffix(String apiBaseUrl) {
        String apiPath = normalizeApiPath(properties.getApiPath());
        return apiBaseUrl.endsWith(apiPath) ? apiBaseUrl.substring(0, apiBaseUrl.length() - apiPath.length()) : apiBaseUrl;
    }
}
