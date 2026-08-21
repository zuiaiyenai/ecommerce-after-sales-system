package com.ecommerce.aftersales.controller;

import com.ecommerce.aftersales.config.ChatWebSocketHandler;
import com.ecommerce.aftersales.dto.InternalAgentToolDtos;
import com.ecommerce.aftersales.entity.AfterSalesTicket;
import com.ecommerce.aftersales.mapper.AfterSalesTicketMapper;
import com.ecommerce.aftersales.mapper.ChatMessageMapper;
import com.ecommerce.aftersales.mapper.ChatSessionMapper;
import com.ecommerce.aftersales.mapper.OrderInfoMapper;
import com.ecommerce.aftersales.mapper.OrderItemMapper;
import com.ecommerce.aftersales.mapper.ProductInfoMapper;
import com.ecommerce.aftersales.mapper.TicketAttachmentMapper;
import com.ecommerce.aftersales.mapper.TicketLogMapper;
import com.ecommerce.aftersales.service.AgentGatewayMetrics;
import com.ecommerce.aftersales.service.AgentPolicyCatalogService;
import com.ecommerce.aftersales.service.AiReviewManualHandoffService;
import com.ecommerce.aftersales.service.AiReviewStatusCacheService;
import com.ecommerce.aftersales.service.AiReviewUserNotificationService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;
import java.util.function.Consumer;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class InternalAgentToolsControllerAiReviewGuardTest {

    @Test
    void controlledMultiAgentApproveUsesJavaIssuedContextVersion() {
        Fixture fixture = fixture();
        InternalAgentToolDtos.SubmitAiReviewRequest request = validApproveRequest();
        String contextVersion = fixture.controller()
                .afterSalesTicket(null, 2001L, 4001L, null)
                .getData()
                .getContextVersion();
        request.setAgentArchitecture("controlled_multi_agent");
        request.setContextVersion(contextVersion);

        var response = fixture.controller().submitAiReview(null, request);

        assertThat(response.getData().getVerdict()).isEqualTo("APPROVE");
        assertThat(response.getData().getReviewApplied()).isTrue();
        verify(fixture.ticketMapper()).applyAiApprovalIfPending(
                any(), any(), any(), any(), any(), any(), any(), any());
        verify(fixture.handoffService(), never()).markManualRequired(
                any(), any(), any(), any(), any(), any(), any());
    }

    @Test
    void malformedApproveRequestsAreDowngradedToManualReview() {
        List<Consumer<InternalAgentToolDtos.SubmitAiReviewRequest>> invalidations = List.of(
                request -> request.setPolicyUncertain(true),
                request -> request.setPolicyUncertain(null),
                request -> request.setEvidenceConsistent(false),
                request -> request.setFilterLevel("category_relaxed"),
                request -> request.setRerankerSucceeded(false),
                request -> request.setTrustedPolicyEligible(false),
                request -> request.setPolicyVersion("v1"),
                request -> request.setAiReviewConfidence(null),
                request -> request.setAiReviewConfidence(new BigDecimal("0.74")),
                request -> request.setPolicyCitations(List.of(Map.of())),
                request -> request.setPolicyCitations(List.of(Map.of("source_code", "POLICY-2"))),
                request -> request.setPolicyCitations(List.of(Map.of("chunk_id", "C-2"))),
                request -> {
                    request.setAgentArchitecture("controlled_multi_agent");
                    request.setContextVersion("stale-context");
                }
        );

        for (Consumer<InternalAgentToolDtos.SubmitAiReviewRequest> invalidate : invalidations) {
            Fixture fixture = fixture();
            InternalAgentToolDtos.SubmitAiReviewRequest request = validApproveRequest();
            invalidate.accept(request);

            var response = fixture.controller().submitAiReview(null, request);

            assertThat(response.getData().getVerdict()).isEqualTo("MANUAL_REVIEW_REQUIRED");
            assertThat(response.getData().getStatus()).isEqualTo("PENDING_REVIEW");
            verify(fixture.ticketMapper(), never()).applyAiApprovalIfPending(
                    any(), any(), any(), any(), any(), any(), any(), any());
            verify(fixture.handoffService()).markManualRequired(
                    any(), any(), any(), any(), any(), any(), any());
        }
    }

    private Fixture fixture() {
        AfterSalesTicketMapper ticketMapper = mock(AfterSalesTicketMapper.class);
        TicketAttachmentMapper attachmentMapper = mock(TicketAttachmentMapper.class);
        AiReviewManualHandoffService handoffService = mock(AiReviewManualHandoffService.class);
        AfterSalesTicket pending = ticket("PENDING_REVIEW", null, null);
        AfterSalesTicket manual = ticket("PENDING_REVIEW", "MANUAL_REVIEW_REQUIRED", "review-1");
        when(ticketMapper.selectById(4001L)).thenReturn(pending);
        pending.setAiReviewRequestId("review-1");
        pending.setAiReviewStatus("RUNNING");
        pending.setEvidenceRevision(0);
        when(ticketMapper.applyAiApprovalIfPending(
                any(), any(), any(), any(), any(), any(), any(), any())).thenReturn(1);
        when(attachmentMapper.selectList(any())).thenReturn(List.of());
        manual.setEvidenceRevision(0);
        when(handoffService.markManualRequired(any(), any(), any(), any(), any(), any(), any()))
                .thenReturn(new AiReviewManualHandoffService.ManualHandoffResult(manual, true, false, null));

        InternalAgentToolsController controller = new InternalAgentToolsController(
                mock(OrderInfoMapper.class),
                mock(OrderItemMapper.class),
                mock(ProductInfoMapper.class),
                ticketMapper,
                attachmentMapper,
                mock(TicketLogMapper.class),
                mock(ChatSessionMapper.class),
                mock(ChatMessageMapper.class),
                mock(AgentPolicyCatalogService.class),
                mock(AiReviewStatusCacheService.class),
                handoffService,
                mock(AiReviewUserNotificationService.class),
                new AgentGatewayMetrics(),
                new ObjectMapper(),
                mock(ChatWebSocketHandler.class)
        );
        return new Fixture(controller, ticketMapper, handoffService);
    }

    private InternalAgentToolDtos.SubmitAiReviewRequest validApproveRequest() {
        InternalAgentToolDtos.SubmitAiReviewRequest request = new InternalAgentToolDtos.SubmitAiReviewRequest();
        request.setUserId(2001L);
        request.setTicketId(4001L);
        request.setReviewRequestId("review-1");
        request.setEvidenceRevision(0);
        request.setVerdict("APPROVE");
        request.setPolicyUncertain(false);
        request.setEvidenceConsistent(true);
        request.setFilterLevel("strict");
        request.setRerankerSucceeded(true);
        request.setTrustedPolicyEligible(true);
        request.setPolicyVersion("v2");
        request.setAiReviewConfidence(new BigDecimal("0.85"));
        request.setPolicyCitations(List.of(Map.of(
                "source_code", "POLICY-2",
                "chunk_id", "C-2"
        )));
        return request;
    }

    private AfterSalesTicket ticket(String status, String result, String requestId) {
        AfterSalesTicket ticket = new AfterSalesTicket();
        ticket.setId(4001L);
        ticket.setUserId(2001L);
        ticket.setOrderId(1001L);
        ticket.setOrderNo("ORDER-1001");
        ticket.setMerchantCode("MERCHANT_DEMO");
        ticket.setPolicyVersion("v2");
        ticket.setStatus(status);
        ticket.setAiReviewResult(result);
        ticket.setAiReviewRequestId(requestId);
        return ticket;
    }

    private record Fixture(
            InternalAgentToolsController controller,
            AfterSalesTicketMapper ticketMapper,
            AiReviewManualHandoffService handoffService
    ) {
    }
}
