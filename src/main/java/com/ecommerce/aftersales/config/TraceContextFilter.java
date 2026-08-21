package com.ecommerce.aftersales.config;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.MDC;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;

@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class TraceContextFilter extends OncePerRequestFilter {

    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            HttpServletResponse response,
            FilterChain filterChain
    ) throws ServletException, IOException {
        String previous = MDC.get(TraceContext.MDC_KEY);
        String traceId = TraceContext.normalizeOrCreate(request.getHeader(TraceContext.HEADER));
        MDC.put(TraceContext.MDC_KEY, traceId);
        request.setAttribute(TraceContext.MDC_KEY, traceId);
        response.setHeader(TraceContext.HEADER, traceId);
        try {
            filterChain.doFilter(request, response);
        } finally {
            if (previous == null) {
                MDC.remove(TraceContext.MDC_KEY);
            } else {
                MDC.put(TraceContext.MDC_KEY, previous);
            }
        }
    }
}
