package com.ecommerce.aftersales.config;

import org.slf4j.MDC;
import org.springframework.http.HttpHeaders;
import org.springframework.util.StringUtils;

import java.util.Locale;
import java.util.UUID;
import java.util.regex.Pattern;

/** Small correlation context that can later be bridged to OpenTelemetry. */
public final class TraceContext {

    public static final String HEADER = "X-Trace-Id";
    public static final String MDC_KEY = "traceId";
    private static final Pattern VALID_TRACE_ID = Pattern.compile("^[0-9a-f]{32}$");

    private TraceContext() {
    }

    public static String normalizeOrCreate(String value) {
        String candidate = value == null ? "" : value.trim().toLowerCase(Locale.ROOT);
        return VALID_TRACE_ID.matcher(candidate).matches() ? candidate : newTraceId();
    }

    public static String newTraceId() {
        return UUID.randomUUID().toString().replace("-", "");
    }

    public static String currentTraceId() {
        String value = MDC.get(MDC_KEY);
        return StringUtils.hasText(value) ? value : null;
    }

    public static String currentOrCreate() {
        String current = currentTraceId();
        return current == null ? newTraceId() : current;
    }

    public static void putHeader(HttpHeaders headers) {
        String traceId = currentTraceId();
        if (traceId != null) {
            headers.set(HEADER, traceId);
        }
    }
}
