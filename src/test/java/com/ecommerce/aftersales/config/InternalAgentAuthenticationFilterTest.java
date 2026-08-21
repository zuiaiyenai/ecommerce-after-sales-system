package com.ecommerce.aftersales.config;

import com.ecommerce.aftersales.util.JwtTokenUtil;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockFilterChain;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.security.core.context.SecurityContextHolder;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;

class InternalAgentAuthenticationFilterTest {

    @AfterEach
    void clearSecurityContext() {
        SecurityContextHolder.clearContext();
    }

    @Test
    void protectsPrometheusEndpointAndAcceptsBearerToken() throws Exception {
        AgentGatewayProperties properties = new AgentGatewayProperties();
        properties.setInternalToken("metrics-secret");
        InternalAgentAuthenticationFilter filter = new InternalAgentAuthenticationFilter(properties);
        MockHttpServletRequest request = new MockHttpServletRequest("GET", "/api/actuator/prometheus");
        request.addHeader("Authorization", "Bearer metrics-secret");
        MockHttpServletResponse response = new MockHttpServletResponse();
        MockFilterChain chain = new MockFilterChain();

        filter.doFilter(request, response, chain);

        assertThat(chain.getRequest()).isSameAs(request);
        assertThat(SecurityContextHolder.getContext().getAuthentication().getName()).isEqualTo("internal-agent");
    }

    @Test
    void rejectsPrometheusScrapeWithWrongToken() throws Exception {
        AgentGatewayProperties properties = new AgentGatewayProperties();
        properties.setInternalToken("metrics-secret");
        InternalAgentAuthenticationFilter filter = new InternalAgentAuthenticationFilter(properties);
        MockHttpServletRequest request = new MockHttpServletRequest("GET", "/api/actuator/prometheus");
        request.addHeader("Authorization", "Bearer wrong-secret");
        MockHttpServletResponse response = new MockHttpServletResponse();
        MockFilterChain chain = new MockFilterChain();

        filter.doFilter(request, response, chain);

        assertThat(response.getStatus()).isEqualTo(401);
        assertThat(chain.getRequest()).isNull();
    }

    @Test
    void healthEndpointRemainsPublicThroughJwtFilter() throws Exception {
        JwtAuthenticationFilter filter = new JwtAuthenticationFilter(mock(JwtTokenUtil.class));
        MockHttpServletRequest request = new MockHttpServletRequest("GET", "/api/actuator/health");
        MockHttpServletResponse response = new MockHttpServletResponse();
        MockFilterChain chain = new MockFilterChain();

        filter.doFilter(request, response, chain);

        assertThat(chain.getRequest()).isSameAs(request);
        assertThat(response.getStatus()).isEqualTo(200);
    }
}
