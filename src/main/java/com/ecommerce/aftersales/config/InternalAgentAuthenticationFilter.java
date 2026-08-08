package com.ecommerce.aftersales.config;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.util.AntPathMatcher;
import org.springframework.util.StringUtils;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.List;

/** Protects server-to-server Agent endpoints from browser access. */
@Component
@RequiredArgsConstructor
public class InternalAgentAuthenticationFilter extends OncePerRequestFilter {

    private static final String HEADER = "X-Agent-Internal-Token";
    private static final AntPathMatcher PATH_MATCHER = new AntPathMatcher();
    private static final List<String> PROTECTED_PATHS = List.of(
            "/api/internal/agent-tools/**",
            "/api/internal/agent-metrics/**",
            "/api/agent/policies/**",
            "/api/agent/knowledge/**",
            "/api/actuator/prometheus"
    );

    private final AgentGatewayProperties properties;

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        return PROTECTED_PATHS.stream().noneMatch(pattern -> PATH_MATCHER.match(pattern, request.getRequestURI()));
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response,
                                    FilterChain filterChain) throws ServletException, IOException {
        String expectedToken = properties.getInternalToken();
        String actualToken = resolveInternalToken(request);
        if (!StringUtils.hasText(expectedToken) || !StringUtils.hasText(actualToken)
                || !MessageDigest.isEqual(expectedToken.getBytes(StandardCharsets.UTF_8), actualToken.getBytes(StandardCharsets.UTF_8))) {
            response.setStatus(HttpStatus.UNAUTHORIZED.value());
            response.setCharacterEncoding(StandardCharsets.UTF_8.name());
            response.setContentType("application/json;charset=UTF-8");
            response.getWriter().write("{\"success\":false,\"code\":401,\"message\":\"Agent 内部认证失败\",\"data\":null}");
            return;
        }
        SecurityContextHolder.getContext().setAuthentication(new UsernamePasswordAuthenticationToken(
                "internal-agent", null, List.of(new SimpleGrantedAuthority("ROLE_AGENT"))));
        filterChain.doFilter(request, response);
    }

    private static String resolveInternalToken(HttpServletRequest request) {
        String internalHeader = request.getHeader(HEADER);
        if (StringUtils.hasText(internalHeader)) {
            return internalHeader;
        }
        String authorization = request.getHeader("Authorization");
        if (StringUtils.hasText(authorization) && authorization.regionMatches(true, 0, "Bearer ", 0, 7)) {
            return authorization.substring(7);
        }
        return null;
    }
}
