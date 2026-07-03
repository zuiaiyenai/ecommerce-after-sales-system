package com.ecommerce.aftersales.config;

import com.ecommerce.aftersales.util.JwtTokenUtil;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.util.AntPathMatcher;
import org.springframework.util.StringUtils;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.List;

@RequiredArgsConstructor
public class JwtAuthenticationFilter extends OncePerRequestFilter {

    private final JwtTokenUtil jwtTokenUtil;
    private static final AntPathMatcher PATH_MATCHER = new AntPathMatcher();

    private static final List<String> PUBLIC_PATHS = List.of(
            "/api/miniapp/auth/**",
            "/api/products/**",
            "/api/merchant-cs/auth/login",
            "/api/static/**",
            "/api/uploads/**"
    );

    private static final List<String> STAFF_PATHS = List.of(
            "/api/merchant-cs/**"
    );

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain filterChain) throws ServletException, IOException {
        String requestURI = request.getRequestURI();

        // Public paths: pass through without requiring authentication
        if (isPublicPath(requestURI)) {
            filterChain.doFilter(request, response);
            return;
        }

        String token = extractToken(request);
        if (!StringUtils.hasText(token)) {
            sendUnauthorized(response, "未提供认证token");
            return;
        }

        Long userId;
        try {
            userId = jwtTokenUtil.parseUserId(token);
        } catch (Exception e) {
            sendUnauthorized(response, "token无效或已过期");
            return;
        }

        // Set request attributes for @CurrentUserId / @CurrentStaffId
        request.setAttribute("currentUserId", userId);
        if (isStaffPath(requestURI)) {
            request.setAttribute("currentStaffId", userId);
        }

        // Set Spring Security Authentication so SecurityContext is populated
        List<SimpleGrantedAuthority> authorities = List.of(new SimpleGrantedAuthority("ROLE_USER"));
        UsernamePasswordAuthenticationToken authentication =
                new UsernamePasswordAuthenticationToken(userId, null, authorities);
        SecurityContextHolder.getContext().setAuthentication(authentication);

        filterChain.doFilter(request, response);
    }

    private boolean isPublicPath(String uri) {
        return PUBLIC_PATHS.stream().anyMatch(pattern -> PATH_MATCHER.match(pattern, uri));
    }

    private boolean isStaffPath(String uri) {
        return STAFF_PATHS.stream().anyMatch(pattern -> PATH_MATCHER.match(pattern, uri));
    }

    private String extractToken(HttpServletRequest request) {
        String authorization = request.getHeader("Authorization");
        if (StringUtils.hasText(authorization) && authorization.startsWith("Bearer ")) {
            return authorization.substring(7);
        }
        return null;
    }

    private void sendUnauthorized(HttpServletResponse response, String message) throws IOException {
        response.setStatus(HttpStatus.UNAUTHORIZED.value());
        response.setContentType("application/json;charset=UTF-8");
        response.getWriter().write("{\"success\":false,\"code\":401,\"message\":\"" + message + "\",\"data\":null}");
    }
}
