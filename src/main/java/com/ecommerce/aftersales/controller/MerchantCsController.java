package com.ecommerce.aftersales.controller;

import com.ecommerce.aftersales.common.ApiResponse;
import com.ecommerce.aftersales.common.PageResult;
import com.ecommerce.aftersales.dto.AgentGatewayDtos;
import com.ecommerce.aftersales.dto.MerchantCsDtos.*;
import com.ecommerce.aftersales.service.AgentPolicyCatalogService;
import com.ecommerce.aftersales.service.KnowledgeRetrievalService;
import com.ecommerce.aftersales.service.MerchantCsService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

@RestController
@RequiredArgsConstructor
@RequestMapping("/merchant-cs")
public class MerchantCsController {

    private final MerchantCsService merchantCsService;
    private final AgentPolicyCatalogService agentPolicyCatalogService;
    private final KnowledgeRetrievalService knowledgeRetrievalService;

    @PostMapping("/auth/login")
    public ApiResponse<LoginResponse> login(@RequestBody LoginRequest request) {
        return ApiResponse.success("登录成功", merchantCsService.login(request));
    }

    @PostMapping("/auth/code")
    public ApiResponse<Map<String, String>> sendAuthCode(@RequestBody AuthCodeRequest request) {
        return ApiResponse.success("验证码发送成功", Map.of("code", merchantCsService.sendAuthCode(request)));
    }

    @PostMapping("/auth/register")
    public ApiResponse<StaffProfile> register(@RequestBody RegisterRequest request) {
        return ApiResponse.success("注册申请已提交，请等待管理员审核", merchantCsService.register(request));
    }

    @PostMapping("/auth/password/reset")
    public ApiResponse<Void> resetPassword(@RequestBody ResetPasswordRequest request) {
        merchantCsService.resetPassword(request);
        return ApiResponse.success("密码重置成功", null);
    }

    @PostMapping("/auth/logout")
    public ApiResponse<Void> logout() {
        merchantCsService.logout();
        return ApiResponse.success("退出成功", null);
    }

    @GetMapping("/auth/me")
    public ApiResponse<StaffProfile> me() {
        return ApiResponse.success("获取成功", merchantCsService.getCurrentStaff());
    }

    @PutMapping("/work-status")
    public ApiResponse<StaffProfile> updateWorkStatus(@RequestBody WorkStatusRequest request) {
        return ApiResponse.success("更新成功", merchantCsService.updateWorkStatus(request.getOnlineStatus()));
    }

    @GetMapping("/agent-policy")
    public ApiResponse<Map<String, Object>> getCurrentAgentPolicy() {
        StaffProfile staff = merchantCsService.getCurrentStaff();
        return ApiResponse.success("获取成功", agentPolicyCatalogService.getMerchantPolicy(staff.getMerchantCode()));
    }

    @PutMapping("/agent-policy")
    public ApiResponse<Map<String, Object>> updateCurrentAgentPolicy(
            @RequestBody AgentGatewayDtos.PolicyConfigUpdateRequest request
    ) {
        StaffProfile staff = merchantCsService.getCurrentStaff();
        return ApiResponse.success("更新成功", agentPolicyCatalogService.updateMerchantPolicy(staff.getMerchantCode(), request));
    }

    @GetMapping("/knowledge/search")
    public ApiResponse<AgentGatewayDtos.KnowledgeRetrieveResponse> searchKnowledge(
            @RequestParam("keyword") String keyword,
            @RequestParam(required = false) String productCategory,
            @RequestParam(required = false) String scene,
            @RequestParam(required = false) String intent,
            @RequestParam(required = false) Integer topK,
            @RequestParam(required = false) List<String> source
    ) {
        StaffProfile staff = merchantCsService.getCurrentStaff();
        AgentGatewayDtos.KnowledgeRetrieveRequest request = new AgentGatewayDtos.KnowledgeRetrieveRequest();
        request.setQuery(keyword);
        request.setMerchantCode(staff.getMerchantCode());
        request.setProductCategory(productCategory);
        request.setScene(scene);
        request.setIntent(intent);
        request.setTopK(topK);
        request.setSources(source);
        return ApiResponse.success("鑾峰彇鎴愬姛", knowledgeRetrievalService.retrieve(request));
    }

    @GetMapping("/dashboard/overview")
    public ApiResponse<DashboardOverview> dashboardOverview() {
        return ApiResponse.success("获取成功", merchantCsService.getDashboardOverview());
    }

    @GetMapping("/dashboard/todos")
    public ApiResponse<List<TodoItem>> dashboardTodos() {
        return ApiResponse.success("获取成功", merchantCsService.getDashboardTodos());
    }

    @GetMapping("/dashboard/performance")
    public ApiResponse<DashboardPerformance> dashboardPerformance() {
        return ApiResponse.success("获取成功", merchantCsService.getDashboardPerformance());
    }

    @GetMapping("/sessions")
    public ApiResponse<PageResult<SessionView>> listSessions(@RequestParam(defaultValue = "1") long page,
                                                             @RequestParam(defaultValue = "10") long size,
                                                             @RequestParam(required = false) String status,
                                                             @RequestParam(required = false) String keyword) {
        return ApiResponse.success("获取成功", merchantCsService.listSessions(page, size, status, keyword));
    }

    @GetMapping("/sessions/{sessionId}")
    public ApiResponse<SessionView> getSession(@PathVariable Long sessionId) {
        return ApiResponse.success("获取成功", merchantCsService.getSession(sessionId));
    }

    @GetMapping("/sessions/{sessionId}/ai-assist")
    public ApiResponse<SessionAiAssistView> getSessionAiAssist(@PathVariable Long sessionId) {
        return ApiResponse.success("获取成功", merchantCsService.getSessionAiAssist(sessionId));
    }

    @GetMapping("/sessions/{sessionId}/messages")
    public ApiResponse<List<MessageView>> listSessionMessages(@PathVariable Long sessionId) {
        return ApiResponse.success("获取成功", merchantCsService.listSessionMessages(sessionId));
    }

    @PostMapping("/sessions/{sessionId}/messages")
    public ApiResponse<MessageView> sendSessionMessage(@PathVariable Long sessionId,
                                                       @RequestBody SendMessageRequest request) {
        return ApiResponse.success("发送成功", merchantCsService.sendSessionMessage(sessionId, request));
    }

    @PostMapping("/sessions/{sessionId}/evaluation-request")
    public ApiResponse<SessionView> requestSessionEvaluation(@PathVariable Long sessionId) {
        return ApiResponse.success("发起成功", merchantCsService.requestSessionEvaluation(sessionId));
    }

    @PostMapping("/sessions/{sessionId}/evaluation")
    public ApiResponse<SessionView> submitSessionEvaluation(@PathVariable Long sessionId,
                                                            @RequestBody EvaluationRequest request) {
        return ApiResponse.success("提交成功", merchantCsService.submitSessionEvaluation(sessionId, request));
    }

    @PostMapping("/sessions/{sessionId}/close")
    public ApiResponse<SessionView> closeSession(@PathVariable Long sessionId) {
        return ApiResponse.success("关闭成功", merchantCsService.closeSession(sessionId));
    }

    @GetMapping("/tickets")
    public ApiResponse<PageResult<TicketView>> listTickets(@RequestParam(defaultValue = "1") long page,
                                                           @RequestParam(defaultValue = "10") long size,
                                                           @RequestParam(required = false) String status,
                                                           @RequestParam(required = false) String type,
                                                           @RequestParam(required = false) String keyword) {
        return ApiResponse.success("获取成功", merchantCsService.listTickets(page, size, status, type, keyword));
    }

    @GetMapping("/tickets/{ticketId}")
    public ApiResponse<TicketView> getTicket(@PathVariable Long ticketId) {
        return ApiResponse.success("获取成功", merchantCsService.getTicket(ticketId));
    }

    @GetMapping("/tickets/{ticketId}/logs")
    public ApiResponse<List<TicketLogView>> listTicketLogs(@PathVariable Long ticketId) {
        return ApiResponse.success("获取成功", merchantCsService.listTicketLogs(ticketId));
    }

    @PostMapping("/tickets/{ticketId}/approve")
    public ApiResponse<TicketView> approveTicket(@PathVariable Long ticketId,
                                                 @RequestBody TicketApproveRequest request) {
        return ApiResponse.success("审核通过", merchantCsService.approveTicket(ticketId, request.getAuditOpinion()));
    }

    @PostMapping("/tickets/{ticketId}/reject")
    public ApiResponse<TicketView> rejectTicket(@PathVariable Long ticketId,
                                                @RequestBody TicketRejectRequest request) {
        return ApiResponse.success("驳回成功", merchantCsService.rejectTicket(ticketId, request.getRejectReason()));
    }

    @PostMapping("/tickets/{ticketId}/complete")
    public ApiResponse<TicketView> completeTicket(@PathVariable Long ticketId,
                                                  @RequestBody TicketCompleteRequest request) {
        return ApiResponse.success("处理完成", merchantCsService.completeTicket(ticketId, request.getCompleteNote()));
    }

    @GetMapping("/orders")
    public ApiResponse<PageResult<OrderView>> listOrders(@RequestParam(defaultValue = "1") long page,
                                                         @RequestParam(defaultValue = "10") long size,
                                                         @RequestParam(required = false) String status,
                                                         @RequestParam(required = false) String keyword) {
        return ApiResponse.success("获取成功", merchantCsService.listOrders(page, size, status, keyword));
    }

    @GetMapping("/orders/{orderId}")
    public ApiResponse<OrderDetail> getOrder(@PathVariable Long orderId) {
        return ApiResponse.success("获取成功", merchantCsService.getOrder(orderId));
    }

    @PostMapping("/orders/{orderId}/ship")
    public ApiResponse<OrderDetail> shipOrder(@PathVariable Long orderId) {
        return ApiResponse.success("发货成功", merchantCsService.shipOrder(orderId));
    }

    @GetMapping("/notices")
    public ApiResponse<PageResult<NoticeView>> listNotices(@RequestParam(defaultValue = "1") long page,
                                                           @RequestParam(defaultValue = "10") long size,
                                                           @RequestParam(required = false) String readStatus,
                                                           @RequestParam(required = false) String level) {
        return ApiResponse.success("获取成功", merchantCsService.listNotices(page, size, readStatus, level));
    }

    @PutMapping("/notices/{noticeId}/read")
    public ApiResponse<NoticeView> markNoticeRead(@PathVariable Long noticeId) {
        return ApiResponse.success("标记成功", merchantCsService.markNoticeRead(noticeId));
    }

    @GetMapping("/products")
    public ApiResponse<PageResult<ProductView>> listProducts(@RequestParam(defaultValue = "1") long page,
                                                             @RequestParam(defaultValue = "10") long size,
                                                             @RequestParam(required = false) String status,
                                                             @RequestParam(required = false) String keyword) {
        return ApiResponse.success("获取成功", merchantCsService.listProducts(page, size, status, keyword));
    }

    @PostMapping("/products")
    public ApiResponse<ProductView> createProduct(@RequestBody ProductUpsertRequest request) {
        return ApiResponse.success("创建成功", merchantCsService.createProduct(request));
    }

    @GetMapping("/products/{productId}")
    public ApiResponse<ProductView> getProduct(@PathVariable Long productId) {
        return ApiResponse.success("获取成功", merchantCsService.getProduct(productId));
    }

    @PutMapping("/products/{productId}")
    public ApiResponse<ProductView> updateProduct(@PathVariable Long productId,
                                                  @RequestBody ProductUpsertRequest request) {
        return ApiResponse.success("更新成功", merchantCsService.updateProduct(productId, request));
    }

    @PutMapping("/products/{productId}/status")
    public ApiResponse<ProductView> updateProductStatus(@PathVariable Long productId,
                                                        @RequestBody ProductStatusRequest request) {
        return ApiResponse.success("更新成功", merchantCsService.updateProductStatus(productId, request.getStatus()));
    }

    @GetMapping("/reviews")
    public ApiResponse<PageResult<ReviewView>> listReviews(@RequestParam(defaultValue = "1") long page,
                                                           @RequestParam(defaultValue = "10") long size,
                                                           @RequestParam(required = false) String score,
                                                           @RequestParam(required = false) String keyword) {
        return ApiResponse.success("获取成功", merchantCsService.getReviews(page, size, score, keyword));
    }
}
