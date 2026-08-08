package com.ecommerce.aftersales.config;

import org.junit.jupiter.api.Test;
import org.slf4j.MDC;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

import static org.assertj.core.api.Assertions.assertThat;

class TraceContextFilterTest {

    private final TraceContextFilter filter = new TraceContextFilter();

    @Test
    void preservesAValidIncomingTraceIdDuringTheRequest() throws Exception {
        String traceId = "0123456789abcdef0123456789abcdef";
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.addHeader(TraceContext.HEADER, traceId);
        MockHttpServletResponse response = new MockHttpServletResponse();

        filter.doFilter(request, response, (req, res) ->
                assertThat(TraceContext.currentTraceId()).isEqualTo(traceId));

        assertThat(response.getHeader(TraceContext.HEADER)).isEqualTo(traceId);
        assertThat(MDC.get(TraceContext.MDC_KEY)).isNull();
    }

    @Test
    void replacesAnInvalidTraceIdWithAValidGeneratedValue() throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.addHeader(TraceContext.HEADER, "../../invalid");
        MockHttpServletResponse response = new MockHttpServletResponse();

        filter.doFilter(request, response, (req, res) -> { });

        assertThat(response.getHeader(TraceContext.HEADER)).matches("[0-9a-f]{32}");
    }
}
