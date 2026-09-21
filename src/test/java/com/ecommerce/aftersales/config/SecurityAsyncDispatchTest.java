package com.ecommerce.aftersales.config;

import com.ecommerce.aftersales.util.JwtTokenUtil;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Import;
import org.springframework.test.context.ContextConfiguration;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.context.request.async.DeferredResult;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import java.util.concurrent.CompletableFuture;

import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.asyncDispatch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.request;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(controllers = SecurityAsyncDispatchTest.AsyncController.class)
@Import(SecurityConfig.class)
@ContextConfiguration(classes = {
        SecurityConfig.class,
        SecurityAsyncDispatchTest.AsyncController.class
})
class SecurityAsyncDispatchTest {

    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private JwtTokenUtil jwtTokenUtil;

    @MockBean
    private AgentGatewayProperties agentGatewayProperties;

    @Test
    void authenticatedAsyncRequestCanCompleteAfterTheInitialRequestThreadReturns() throws Exception {
        when(jwtTokenUtil.parseUserId("valid-token")).thenReturn(1L);

        MvcResult pending = mockMvc.perform(get("/test/async")
                        .header("Authorization", "Bearer valid-token"))
                .andExpect(request().asyncStarted())
                .andReturn();

        mockMvc.perform(asyncDispatch(pending))
                .andExpect(status().isOk())
                .andExpect(content().string("done"));
    }

    @Test
    void initialRequestStillRequiresAuthentication() throws Exception {
        mockMvc.perform(get("/test/async"))
                .andExpect(status().isUnauthorized());
    }

    @RestController
    static class AsyncController {

        @GetMapping("/test/async")
        DeferredResult<String> async() {
            DeferredResult<String> result = new DeferredResult<>(5_000L);
            CompletableFuture.runAsync(() -> result.setResult("done"));
            return result;
        }
    }
}
