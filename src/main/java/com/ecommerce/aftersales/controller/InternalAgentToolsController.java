package com.ecommerce.aftersales.controller;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ecommerce.aftersales.common.ApiResponse;
import com.ecommerce.aftersales.common.BizException;
import com.ecommerce.aftersales.dto.InternalAgentToolDtos;
import com.ecommerce.aftersales.entity.AfterSalesTicket;
import com.ecommerce.aftersales.entity.ChatMessage;
import com.ecommerce.aftersales.entity.ChatSession;
import com.ecommerce.aftersales.entity.OrderInfo;
import com.ecommerce.aftersales.entity.OrderItem;
import com.ecommerce.aftersales.entity.ProductInfo;
import com.ecommerce.aftersales.entity.TicketAttachment;
import com.ecommerce.aftersales.entity.TicketLog;
import com.ecommerce.aftersales.mapper.AfterSalesTicketMapper;
import com.ecommerce.aftersales.mapper.ChatMessageMapper;
import com.ecommerce.aftersales.mapper.ChatSessionMapper;
import com.ecommerce.aftersales.mapper.OrderInfoMapper;
import com.ecommerce.aftersales.mapper.OrderItemMapper;
import com.ecommerce.aftersales.mapper.ProductInfoMapper;
import com.ecommerce.aftersales.mapper.TicketAttachmentMapper;
import com.ecommerce.aftersales.mapper.TicketLogMapper;
import com.ecommerce.aftersales.service.AiReviewStatusCacheService;
import com.ecommerce.aftersales.service.AiReviewManualHandoffService;
import com.ecommerce.aftersales.service.AiReviewUserNotificationService;
import com.ecommerce.aftersales.service.AgentPolicyCatalogService;
import com.ecommerce.aftersales.service.AgentGatewayMetrics;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.util.StringUtils;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

@RestController
@RequiredArgsConstructor
@Slf4j
@RequestMapping("/internal/agent-tools")
public class InternalAgentToolsController {

    private static final String DEFAULT_MERCHANT_CODE = "MERCHANT_DEMO";

    private final OrderInfoMapper orderInfoMapper;
    private final OrderItemMapper orderItemMapper;
    private final ProductInfoMapper productInfoMapper;
    private final AfterSalesTicketMapper afterSalesTicketMapper;
    private final TicketAttachmentMapper ticketAttachmentMapper;
    private final TicketLogMapper ticketLogMapper;
    private final ChatSessionMapper chatSessionMapper;
    private final ChatMessageMapper chatMessageMapper;
    private final AgentPolicyCatalogService agentPolicyCatalogService;
    private final AiReviewStatusCacheService aiReviewStatusCacheService;
    private final AiReviewManualHandoffService aiReviewManualHandoffService;
    private final AiReviewUserNotificationService aiReviewUserNotificationService;
    private final AgentGatewayMetrics metrics;
    private final ObjectMapper objectMapper;

    @Value("${app.agent.internal-token:}")
    private String internalToken;

    @PostMapping("/orders/search")
    public ApiResponse<List<InternalAgentToolDtos.OrderSummary>> searchOrders(
            @RequestHeader(value = "X-Agent-Internal-Token", required = false) String token,
            @RequestBody InternalAgentToolDtos.OrderSearchRequest request
    ) {
        verifyInternalToken(token);
        requireUser(request.getUserId());
        LambdaQueryWrapper<OrderInfo> wrapper = new LambdaQueryWrapper<OrderInfo>()
                .eq(OrderInfo::getUserId, request.getUserId())
                .orderByDesc(OrderInfo::getCreateTime)
                .last("limit 20");
        if (request.getStatusFilter() != null && !request.getStatusFilter().isEmpty()) {
            wrapper.in(OrderInfo::getStatus, request.getStatusFilter());
        }
        List<InternalAgentToolDtos.OrderSummary> orders = orderInfoMapper.selectList(wrapper).stream()
                .map(this::toOrderSummary)
                .filter(item -> !StringUtils.hasText(request.getKeyword())
                        || containsAny(request.getKeyword(), item.getOrderNo(), item.getProductName(), item.getCategory()))
                .toList();
        return ApiResponse.success("ok", orders);
    }

    @GetMapping("/orders/detail")
    public ApiResponse<InternalAgentToolDtos.OrderSummary> orderDetail(
            @RequestHeader(value = "X-Agent-Internal-Token", required = false) String token,
            @RequestParam Long userId,
            @RequestParam String orderId
    ) {
        verifyInternalToken(token);
        return ApiResponse.success("ok", toOrderSummary(resolveOwnedOrder(userId, orderId)));
    }

    @GetMapping("/aftersales/existing")
    public ApiResponse<InternalAgentToolDtos.TicketResult> existingAfterSales(
            @RequestHeader(value = "X-Agent-Internal-Token", required = false) String token,
            @RequestParam Long userId,
            @RequestParam String orderId
    ) {
        verifyInternalToken(token);
        OrderInfo order = resolveOwnedOrder(userId, orderId);
        AfterSalesTicket ticket = findOpenTicket(order.getId());
        return ApiResponse.success("ok", ticket == null ? null : toTicketResult(ticket, true));
    }

    @GetMapping("/aftersales/ticket")
    public ApiResponse<InternalAgentToolDtos.TicketResult> afterSalesTicket(
            @RequestHeader(value = "X-Agent-Internal-Token", required = false) String token,
            @RequestParam Long userId,
            @RequestParam Long ticketId,
            @RequestParam(required = false) String orderId
    ) {
        verifyInternalToken(token);
        AfterSalesTicket ticket = resolveOwnedTicket(userId, ticketId, orderId);
        return ApiResponse.success("ok", toTicketResult(ticket, true));
    }

    @GetMapping("/policies/merchant")
    public ApiResponse<Map<String, Object>> merchantPolicy(
            @RequestHeader(value = "X-Agent-Internal-Token", required = false) String token,
            @RequestParam(required = false) String merchantCode
    ) {
        verifyInternalToken(token);
        return ApiResponse.success("ok", agentPolicyCatalogService.getMerchantPolicy(normalizeMerchantCode(merchantCode)));
    }

    @PostMapping("/aftersales/review")
    @Transactional(rollbackFor = Exception.class)
    public ApiResponse<InternalAgentToolDtos.TicketResult> submitAiReview(
            @RequestHeader(value = "X-Agent-Internal-Token", required = false) String token,
            @RequestBody InternalAgentToolDtos.SubmitAiReviewRequest request
    ) {
        verifyInternalToken(token);
        requireUser(request.getUserId());
        if (request.getTicketId() == null) {
            throw new BizException(400, "ticketId is required");
        }
        if (!StringUtils.hasText(request.getReviewRequestId())) {
            throw new BizException(400, "reviewRequestId is required");
        }
        String verdict = Optional.ofNullable(request.getVerdict()).orElse("").trim().toUpperCase();
        if ("MANUAL_REVIEW".equals(verdict)) {
            verdict = "MANUAL_REVIEW_REQUIRED";
        }
        if (!List.of("APPROVE", "MANUAL_REVIEW_REQUIRED").contains(verdict)) {
            throw new BizException(400, "verdict must be APPROVE or MANUAL_REVIEW_REQUIRED");
        }

        AfterSalesTicket ticket = resolveOwnedTicket(request.getUserId(), request.getTicketId(), request.getOrderId());
        if (request.getReviewRequestId().equals(ticket.getAiReviewRequestId())) {
            metrics.recordAiReviewApply("idempotent");
            log.info("ai_review_apply ticket_id={} review_request_id={} transition=idempotent failure_class=none",
                    ticket.getId(), request.getReviewRequestId());
            InternalAgentToolDtos.TicketResult result = toTicketResult(ticket, false);
            result.setVerdict(ticket.getAiReviewResult());
            result.setAiReviewResult(ticket.getAiReviewResult());
            result.setAiReviewStatus(reviewStatus(ticket.getAiReviewResult()));
            result.setReviewRequestId(ticket.getAiReviewRequestId());
            result.setReviewApplied(true);
            result.setIdempotentReplay(true);
            return ApiResponse.success("idempotent_replay", result);
        }

        String previousStatus = ticket.getStatus();
        if (!List.of("PENDING", "PENDING_REVIEW").contains(previousStatus)) {
            metrics.recordAiReviewApply("stale");
            log.info("ai_review_apply ticket_id={} review_request_id={} transition=stale failure_class=STATUS_CHANGED",
                    ticket.getId(), request.getReviewRequestId());
            InternalAgentToolDtos.TicketResult result = toTicketResult(ticket, false);
            result.setVerdict(verdict);
            result.setAiReviewResult(ticket.getAiReviewResult());
            result.setAiReviewStatus(reviewStatus(ticket.getAiReviewResult()));
            result.setReviewRequestId(request.getReviewRequestId());
            result.setReviewApplied(false);
            result.setIdempotentReplay(false);
            result.setReviewRejectReason("STATUS_CHANGED");
            return ApiResponse.success("status_not_reviewable", result);
        }

        boolean approve = "APPROVE".equals(verdict);
        if (approve) {
            LocalDateTime now = LocalDateTime.now();
            int changed = afterSalesTicketMapper.applyAiApprovalIfPending(
                    ticket.getId(),
                    request.getReviewRequestId(),
                    shortText(request.getReason(), 500),
                    writeJson(reviewAuditPayload(request)),
                    normalizeScore(request.getAiReviewConfidence()),
                    now,
                    now.plusHours(12)
            );
            if (changed == 0) {
                return staleReviewResult(request, verdict, ticket.getId());
            }
            ticket = afterSalesTicketMapper.selectById(ticket.getId());
            aiReviewUserNotificationService.notifyReviewApproved(ticket);
            addTicketLog(ticket.getId(), previousStatus, "PROCESSING", "AI_REVIEW_APPROVE", firstNonBlank(request.getReason(), "AI初审通过，进入处理中"));
        } else {
            AiReviewManualHandoffService.ManualHandoffResult handoff = aiReviewManualHandoffService.markManualRequired(
                    ticket.getId(),
                    request.getReviewRequestId(),
                    request.getReason(),
                    "AGENT_TOOL",
                    writeJson(reviewAuditPayload(request)),
                    normalizeScore(request.getAiReviewConfidence())
            );
            if (!handoff.applied() && !handoff.idempotentReplay()) {
                return staleReviewResult(request, verdict, ticket.getId());
            }
            ticket = handoff.ticket();
            if (handoff.idempotentReplay()) {
                metrics.recordAiReviewApply("idempotent");
                log.info("ai_review_apply ticket_id={} review_request_id={} transition=idempotent failure_class=none",
                        ticket.getId(), request.getReviewRequestId());
                InternalAgentToolDtos.TicketResult result = toTicketResult(ticket, false);
                result.setVerdict(ticket.getAiReviewResult());
                result.setAiReviewResult(ticket.getAiReviewResult());
                result.setAiReviewStatus(reviewStatus(ticket.getAiReviewResult()));
                result.setReviewRequestId(ticket.getAiReviewRequestId());
                result.setReviewApplied(true);
                result.setIdempotentReplay(true);
                return ApiResponse.success("idempotent_replay", result);
            }
        }
        bindSessionToTicket(request.getSessionId(), ticket, request.getUserId());
        Long reviewedTicketId = ticket.getId();
        runAfterCommit(() -> {
            aiReviewStatusCacheService.cacheStatus(reviewedTicketId, approve ? "PROCESSING" : "MANUAL_REQUIRED");
            metrics.recordAiReviewApply(approve ? "applied" : "manual_required");
            log.info("ai_review_apply ticket_id={} review_request_id={} transition={} failure_class=none",
                    reviewedTicketId, request.getReviewRequestId(), approve ? "applied" : "manual_required");
        });

        InternalAgentToolDtos.TicketResult result = toTicketResult(ticket, false);
        result.setVerdict(verdict);
        result.setAiReviewResult(verdict);
        result.setAiReviewStatus(reviewStatus(verdict));
        result.setReviewRequestId(request.getReviewRequestId());
        result.setReviewApplied(true);
        result.setIdempotentReplay(false);
        return ApiResponse.success(approve ? "review_approved" : "review_manual", result);
    }

    private ApiResponse<InternalAgentToolDtos.TicketResult> staleReviewResult(
            InternalAgentToolDtos.SubmitAiReviewRequest request,
            String verdict,
            Long ticketId
    ) {
        AfterSalesTicket current = afterSalesTicketMapper.selectById(ticketId);
        if (current != null && request.getReviewRequestId().equals(current.getAiReviewRequestId())) {
            metrics.recordAiReviewApply("idempotent");
            log.info("ai_review_apply ticket_id={} review_request_id={} transition=idempotent failure_class=none",
                    ticketId, request.getReviewRequestId());
            InternalAgentToolDtos.TicketResult replay = toTicketResult(current, false);
            replay.setVerdict(current.getAiReviewResult());
            replay.setAiReviewResult(current.getAiReviewResult());
            replay.setAiReviewStatus(reviewStatus(current.getAiReviewResult()));
            replay.setReviewRequestId(current.getAiReviewRequestId());
            replay.setReviewApplied(true);
            replay.setIdempotentReplay(true);
            return ApiResponse.success("idempotent_replay", replay);
        }
        if (current != null) {
            addTicketLog(
                    current.getId(),
                    current.getStatus(),
                    current.getStatus(),
                    "AI_REVIEW_STALE",
                    "AI初审结果未应用，工单状态已变化或已由其他审核请求处理。requestId="
                            + shortText(request.getReviewRequestId(), 64)
            );
        }
        InternalAgentToolDtos.TicketResult result = current == null
                ? new InternalAgentToolDtos.TicketResult()
                : toTicketResult(current, false);
        result.setVerdict(verdict);
        result.setAiReviewResult(current == null ? null : current.getAiReviewResult());
        result.setAiReviewStatus(current == null ? "PENDING" : reviewStatus(current.getAiReviewResult()));
        result.setReviewRequestId(request.getReviewRequestId());
        result.setReviewApplied(false);
        result.setIdempotentReplay(false);
        result.setReviewRejectReason(current == null ? "TICKET_NOT_FOUND" : "STALE_REVIEW");
        metrics.recordAiReviewApply("stale");
        log.info("ai_review_apply ticket_id={} review_request_id={} transition=stale failure_class={}",
                ticketId, request.getReviewRequestId(), result.getReviewRejectReason());
        return ApiResponse.success("stale_review", result);
    }

    private void bindSessionToTicket(Long sessionId, AfterSalesTicket ticket, Long userId) {
        if (sessionId == null || ticket == null) {
            return;
        }
        ChatSession session = chatSessionMapper.selectById(sessionId);
        if (session == null || !userId.equals(session.getUserId())) {
            return;
        }
        session.setTicketId(ticket.getId());
        session.setOrderId(ticket.getOrderId());
        session.setMerchantId(ticket.getMerchantId());
        session.setMerchantCode(ticket.getMerchantCode());
        session.setUpdateTime(LocalDateTime.now());
        chatSessionMapper.updateById(session);
    }

    private void applySessionBusinessContext(ChatSession session, Long userId, String orderId, Long ticketId) {
        if (session == null || userId == null) {
            return;
        }
        Long effectiveTicketId = ticketId == null ? session.getTicketId() : ticketId;
        if (effectiveTicketId != null) {
            AfterSalesTicket ticket = afterSalesTicketMapper.selectById(effectiveTicketId);
            if (ticket == null || !userId.equals(ticket.getUserId())) {
                throw new BizException(404, "ticket not found");
            }
            session.setTicketId(ticket.getId());
            session.setOrderId(ticket.getOrderId());
            session.setMerchantId(ticket.getMerchantId());
            session.setMerchantCode(normalizeMerchantCode(ticket.getMerchantCode()));
            return;
        }
        String effectiveOrderId = StringUtils.hasText(orderId)
                ? orderId
                : session.getOrderId() == null ? null : String.valueOf(session.getOrderId());
        if (StringUtils.hasText(effectiveOrderId)) {
            OrderInfo order = resolveOwnedOrder(userId, effectiveOrderId);
            session.setOrderId(order.getId());
            session.setMerchantId(order.getMerchantId());
            session.setMerchantCode(normalizeMerchantCode(order.getMerchantCode()));
        } else if (!StringUtils.hasText(session.getMerchantCode())) {
            session.setMerchantCode(DEFAULT_MERCHANT_CODE);
        }
    }

    @PostMapping("/sessions/message")
    @Transactional(rollbackFor = Exception.class)
    public ApiResponse<InternalAgentToolDtos.MessageResult> appendMessage(
            @RequestHeader(value = "X-Agent-Internal-Token", required = false) String token,
            @RequestBody InternalAgentToolDtos.AppendMessageRequest request
    ) {
        verifyInternalToken(token);
        requireUser(request.getUserId());
        ChatSession session = resolveOrCreateSession(request.getUserId(), request.getSessionId(), request.getOrderId(), request.getTicketId());
        assertSessionOwner(session, request.getUserId());
        applySessionBusinessContext(session, request.getUserId(), request.getOrderId(), request.getTicketId());

        ChatMessage message = new ChatMessage();
        message.setSessionId(session.getId());
        message.setRole(normalizeRole(request.getRole()));
        message.setMessageType(normalizeMessageType(request.getMessageType()));
        message.setFileUrl(resolveMessageFileUrl(message.getMessageType(), request.getFileUrl()));
        message.setContent(resolveMessageContent(message.getMessageType(), firstNonBlank(request.getContent(), "")));
        message.setConfidence(normalizeScore(request.getConfidence()));
        message.setEmotionLabel(request.getEmotionLabel());
        message.setEmotionScore(normalizeScore(request.getEmotionScore()));
        message.setEmotionConfidence(normalizeScore(request.getEmotionConfidence()));
        message.setKnowledgeQuery(request.getKnowledgeQuery());
        message.setKnowledgeRetrievalMode(request.getKnowledgeRetrievalMode());
        message.setKnowledgeHitCount(request.getKnowledgeHitCount());
        message.setKnowledgeHitsJson(request.getKnowledgeHitsJson());
        message.setKnowledgeTraceJson(request.getKnowledgeTraceJson());
        chatMessageMapper.insert(message);

        session.setUserHidden(0);
        if ("USER".equalsIgnoreCase(message.getRole()) && StringUtils.hasText(message.getContent())) {
            session.setUserQuery(shortText(message.getContent(), 500));
        } else if (!StringUtils.hasText(session.getUserQuery())) {
            session.setUserQuery(shortText(message.getContent(), 500));
        }
        session.setUpdateTime(message.getCreateTime() == null ? LocalDateTime.now() : message.getCreateTime());
        chatSessionMapper.updateById(session);

        InternalAgentToolDtos.MessageResult result = new InternalAgentToolDtos.MessageResult();
        result.setMessageId(message.getId());
        result.setSessionId(session.getId());
        return ApiResponse.success("ok", result);
    }

    @PostMapping("/sessions/handoff")
    @Transactional(rollbackFor = Exception.class)
    public ApiResponse<InternalAgentToolDtos.SessionResult> handoff(
            @RequestHeader(value = "X-Agent-Internal-Token", required = false) String token,
            @RequestBody InternalAgentToolDtos.HandoffRequest request
    ) {
        verifyInternalToken(token);
        requireUser(request.getUserId());
        ChatSession session = resolveOrCreateSession(request.getUserId(), request.getSessionId(), request.getOrderId(), request.getTicketId());
        assertSessionOwner(session, request.getUserId());
        applySessionBusinessContext(session, request.getUserId(), request.getOrderId(), request.getTicketId());
        session.setMode("HUMAN");
        session.setStatus("WAITING");
        session.setTicketId(request.getTicketId() == null ? session.getTicketId() : request.getTicketId());
        session.setEmotionLabel(request.getEmotionLabel());
        session.setEmotionScore(normalizeScore(request.getEmotionScore()));
        session.setEmotionConfidence(normalizeScore(request.getEmotionConfidence()));
        session.setUserQuery(shortText(firstNonBlank(request.getSummary(), "AI 建议转人工"), 500));
        session.setResolved(0);
        session.setUserHidden(0);
        session.setUpdateTime(LocalDateTime.now());
        chatSessionMapper.updateById(session);
        return ApiResponse.success("ok", toSessionResult(session));
    }

    @PostMapping("/sessions/request-evidence")
    @Transactional(rollbackFor = Exception.class)
    public ApiResponse<InternalAgentToolDtos.MessageResult> requestMissingEvidence(
            @RequestHeader(value = "X-Agent-Internal-Token", required = false) String token,
            @RequestBody InternalAgentToolDtos.MissingEvidenceRequest request
    ) {
        verifyInternalToken(token);
        InternalAgentToolDtos.AppendMessageRequest append = new InternalAgentToolDtos.AppendMessageRequest();
        append.setUserId(request.getUserId());
        append.setSessionId(request.getSessionId());
        append.setOrderId(request.getOrderId());
        append.setTicketId(request.getTicketId());
        append.setRole("ASSISTANT");
        append.setMessageType("TEXT");
        append.setContent(firstNonBlank(request.getAssistantReply(), "请补充必要售后凭证后继续处理。"));
        return appendMessage(token, append);
    }

    private void runAfterCommit(Runnable action) {
        if (TransactionSynchronizationManager.isSynchronizationActive()) {
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override
                public void afterCommit() {
                    action.run();
                }
            });
            return;
        }
        action.run();
    }

    private void verifyInternalToken(String token) {
        if (StringUtils.hasText(internalToken) && !internalToken.equals(token)) {
            throw new BizException(403, "invalid internal token");
        }
    }

    private void requireUser(Long userId) {
        if (userId == null) {
            throw new BizException(400, "userId is required");
        }
    }

    private OrderInfo resolveOwnedOrder(Long userId, String orderId) {
        requireUser(userId);
        if (!StringUtils.hasText(orderId)) {
            throw new BizException(400, "orderId is required");
        }
        LambdaQueryWrapper<OrderInfo> wrapper = new LambdaQueryWrapper<OrderInfo>()
                .eq(OrderInfo::getUserId, userId);
        Long numericId = parseLongOrNull(orderId);
        if (numericId != null) {
            wrapper.and(item -> item.eq(OrderInfo::getId, numericId).or().eq(OrderInfo::getOrderNo, orderId));
        } else {
            wrapper.eq(OrderInfo::getOrderNo, orderId);
        }
        OrderInfo order = orderInfoMapper.selectOne(wrapper.last("limit 1"));
        if (order == null) {
            throw new BizException(404, "order not found");
        }
        return order;
    }

    private AfterSalesTicket resolveOwnedTicket(Long userId, Long ticketId, String orderId) {
        requireUser(userId);
        if (ticketId == null) {
            throw new BizException(400, "ticketId is required");
        }
        AfterSalesTicket ticket = afterSalesTicketMapper.selectById(ticketId);
        if (ticket == null || !userId.equals(ticket.getUserId())) {
            throw new BizException(404, "ticket not found");
        }
        if (StringUtils.hasText(orderId)) {
            Long numericOrderId = parseLongOrNull(orderId);
            if (numericOrderId != null && !numericOrderId.equals(ticket.getOrderId())) {
                OrderInfo order = resolveOwnedOrder(userId, orderId);
                if (!order.getId().equals(ticket.getOrderId())) {
                    throw new BizException(404, "ticket not found");
                }
            } else if (numericOrderId == null && !orderId.equals(ticket.getOrderNo())) {
                throw new BizException(404, "ticket not found");
            }
        }
        return ticket;
    }

    private AfterSalesTicket findOpenTicket(Long orderId) {
        return afterSalesTicketMapper.selectOne(new LambdaQueryWrapper<AfterSalesTicket>()
                .eq(AfterSalesTicket::getOrderId, orderId)
                .in(AfterSalesTicket::getStatus, List.of("PENDING", "PENDING_REVIEW", "PROCESSING"))
                .orderByDesc(AfterSalesTicket::getUpdateTime)
                .last("limit 1"));
    }

    private Optional<ProductInfo> firstProduct(Long orderId) {
        OrderItem item = orderItemMapper.selectOne(new LambdaQueryWrapper<OrderItem>()
                .eq(OrderItem::getOrderId, orderId)
                .last("limit 1"));
        if (item == null || item.getProductId() == null) {
            return Optional.empty();
        }
        return Optional.ofNullable(productInfoMapper.selectById(item.getProductId()));
    }

    private InternalAgentToolDtos.OrderSummary toOrderSummary(OrderInfo order) {
        InternalAgentToolDtos.OrderSummary summary = new InternalAgentToolDtos.OrderSummary();
        summary.setOrderId(order.getId());
        summary.setOrderNo(order.getOrderNo());
        summary.setUserId(order.getUserId());
        summary.setMerchantId(order.getMerchantId());
        summary.setMerchantCode(normalizeMerchantCode(order.getMerchantCode()));
        summary.setStatus(order.getStatus());
        summary.setAmount(firstPositive(order.getPayAmount(), order.getTotalAmount(), BigDecimal.ZERO));
        summary.setCreateTime(order.getCreateTime());
        firstProduct(order.getId()).ifPresent(product -> {
            summary.setProductName(product.getProductName());
            summary.setCategory(product.getCategory());
        });
        AfterSalesTicket ticket = findOpenTicket(order.getId());
        if (ticket != null) {
            summary.setExistingTicketId(ticket.getId());
            summary.setExistingTicketNo(ticket.getTicketNo());
            summary.setExistingTicketStatus(ticket.getStatus());
        }
        return summary;
    }

    private InternalAgentToolDtos.TicketResult toTicketResult(AfterSalesTicket ticket, boolean existing) {
        InternalAgentToolDtos.TicketResult result = new InternalAgentToolDtos.TicketResult();
        result.setTicketId(ticket.getId());
        result.setTicketNo(ticket.getTicketNo());
        result.setOrderId(ticket.getOrderId());
        result.setOrderNo(ticket.getOrderNo());
        result.setUserId(ticket.getUserId());
        result.setMerchantId(ticket.getMerchantId());
        result.setMerchantCode(ticket.getMerchantCode());
        result.setStatus(ticket.getStatus());
        result.setAfterSalesType(ticket.getAfterSaleType());
        result.setRefundAmount(ticket.getRefundAmount());
        result.setExisting(existing);
        result.setProductName(ticket.getProductName());
        result.setPolicyVersion(ticket.getPolicyVersion());
        result.setAfterSalesAppliedAt(ticket.getCreateTime());
        result.setAiReviewResult(ticket.getAiReviewResult());
        result.setAiReviewStatus(reviewStatus(ticket.getAiReviewResult()));
        result.setReviewRequestId(ticket.getAiReviewRequestId());
        result.setReviewApplied(ticket.getAiReviewRequestId() != null);
        result.setIdempotentReplay(false);
        result.setEvidenceUrls(ticketAttachmentMapper.selectList(new LambdaQueryWrapper<TicketAttachment>()
                        .eq(TicketAttachment::getTicketId, ticket.getId())
                        .orderByAsc(TicketAttachment::getSortOrder))
                .stream()
                .map(TicketAttachment::getFileUrl)
                .filter(StringUtils::hasText)
                .toList());
        return result;
    }

    private String reviewStatus(String verdict) {
        if ("APPROVE".equals(verdict)) {
            return "APPROVED";
        }
        if ("MANUAL_REVIEW_REQUIRED".equals(verdict) || "MANUAL_REVIEW".equals(verdict)) {
            return "MANUAL_REQUIRED";
        }
        return "PENDING";
    }

    private Map<String, Object> reviewAuditPayload(InternalAgentToolDtos.SubmitAiReviewRequest request) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("verdict", request.getVerdict());
        payload.put("reason", request.getReason());
        payload.put("evidence_needed", request.getEvidenceNeeded());
        payload.put("visual_uncertain", request.getVisualUncertain());
        payload.put("policy_uncertain", request.getPolicyUncertain());
        payload.put("evidence_consistent", request.getEvidenceConsistent());
        payload.put("ai_review_confidence", request.getAiReviewConfidence());
        payload.put("visual_confidence", request.getVisualConfidence());
        payload.put("knowledge_retrieval_mode", request.getKnowledgeRetrievalMode());
        payload.put("policy_match_score", request.getPolicyMatchScore());
        payload.put("risk_review_reasons", request.getRiskReviewReasons());
        payload.put("policy_citations", request.getPolicyCitations());
        payload.put("skill_versions", request.getSkillVersions());
        payload.put("image_review", request.getImageReview());
        return payload;
    }

    private ChatSession resolveOrCreateSession(Long userId, Long sessionId, String orderId, Long ticketId) {
        if (sessionId != null) {
            ChatSession session = chatSessionMapper.selectById(sessionId);
            if (session == null) {
                throw new BizException(404, "session not found");
            }
            return session;
        }
        OrderInfo order = StringUtils.hasText(orderId) ? resolveOwnedOrder(userId, orderId) : null;
        AfterSalesTicket ticket = ticketId == null ? null : afterSalesTicketMapper.selectById(ticketId);
        if (ticket != null && !userId.equals(ticket.getUserId())) {
            throw new BizException(404, "ticket not found");
        }
        LambdaQueryWrapper<ChatSession> wrapper = new LambdaQueryWrapper<ChatSession>()
                .eq(ChatSession::getUserId, userId)
                .ne(ChatSession::getStatus, "CLOSED")
                .orderByDesc(ChatSession::getUpdateTime)
                .last("limit 1");
        if (ticket != null) {
            wrapper.eq(ChatSession::getTicketId, ticket.getId());
        } else if (order != null) {
            wrapper.eq(ChatSession::getOrderId, order.getId());
        } else {
            wrapper.isNull(ChatSession::getOrderId).isNull(ChatSession::getTicketId);
        }
        ChatSession existing = chatSessionMapper.selectOne(wrapper);
        if (existing != null) {
            return existing;
        }
        ChatSession session = new ChatSession();
        session.setSessionNo("CS" + System.currentTimeMillis());
        session.setUserId(userId);
        session.setOrderId(order == null ? null : order.getId());
        session.setTicketId(ticket == null ? null : ticket.getId());
        session.setMerchantId(ticket != null ? ticket.getMerchantId() : order == null ? null : order.getMerchantId());
        session.setMerchantCode(ticket != null ? ticket.getMerchantCode() : order == null ? DEFAULT_MERCHANT_CODE : normalizeMerchantCode(order.getMerchantCode()));
        session.setMode("AI");
        session.setStatus("ACTIVE");
        session.setResolved(0);
        session.setDeleted(0);
        session.setUserHidden(0);
        session.setUserQuery("AI 售后咨询");
        chatSessionMapper.insert(session);
        return session;
    }

    private void assertSessionOwner(ChatSession session, Long userId) {
        if (session == null || !userId.equals(session.getUserId())) {
            throw new BizException(404, "session not found");
        }
    }

    private InternalAgentToolDtos.SessionResult toSessionResult(ChatSession session) {
        InternalAgentToolDtos.SessionResult result = new InternalAgentToolDtos.SessionResult();
        result.setSessionId(session.getId());
        result.setSessionNo(session.getSessionNo());
        result.setMode(session.getMode());
        result.setStatus(session.getStatus());
        result.setTicketId(session.getTicketId());
        return result;
    }

    private void addTicketLog(Long ticketId, String oldStatus, String newStatus, String action, String content) {
        TicketLog log = new TicketLog();
        log.setTicketId(ticketId);
        log.setOperatorId(0L);
        log.setOperatorType("AI");
        log.setFromStatus(oldStatus);
        log.setToStatus(newStatus);
        log.setAction(action);
        log.setContent(content);
        ticketLogMapper.insert(log);
    }

    private BigDecimal firstPositive(BigDecimal... values) {
        for (BigDecimal value : values) {
            if (value != null && value.compareTo(BigDecimal.ZERO) > 0) {
                return value;
            }
        }
        return BigDecimal.ZERO;
    }

    private BigDecimal normalizeScore(BigDecimal value) {
        if (value == null) {
            return null;
        }
        if (value.compareTo(BigDecimal.ONE) > 0) {
            value = value.movePointLeft(2);
        }
        if (value.compareTo(BigDecimal.ZERO) < 0) {
            return BigDecimal.ZERO;
        }
        return value.compareTo(BigDecimal.ONE) > 0 ? BigDecimal.ONE : value;
    }

    private String normalizeMessageType(String messageType) {
        String normalized = StringUtils.hasText(messageType) ? messageType.trim().toUpperCase() : "TEXT";
        return List.of("TEXT", "IMAGE", "FILE").contains(normalized) ? normalized : "TEXT";
    }

    private String resolveMessageFileUrl(String messageType, String fileUrl) {
        if (!List.of("IMAGE", "FILE").contains(normalizeMessageType(messageType))) {
            return null;
        }
        if (StringUtils.hasText(fileUrl)) {
            return fileUrl.trim();
        }
        throw new BizException("图片或文件消息必须提供 fileUrl");
    }

    private String resolveMessageContent(String messageType, String content) {
        String normalized = normalizeMessageType(messageType);
        if ("IMAGE".equals(normalized)) {
            return StringUtils.hasText(content) ? content : "[图片]";
        }
        if ("FILE".equals(normalized)) {
            return StringUtils.hasText(content) ? content : "文件";
        }
        return content == null ? "" : content;
    }

    private String normalizeRole(String role) {
        String value = firstNonBlank(role, "ASSISTANT").trim().toUpperCase();
        return switch (value) {
            case "USER", "SYSTEM", "ASSISTANT", "AI" -> "AI".equals(value) ? "ASSISTANT" : value;
            default -> "ASSISTANT";
        };
    }

    private String normalizeMerchantCode(String merchantCode) {
        return StringUtils.hasText(merchantCode) ? merchantCode.trim() : DEFAULT_MERCHANT_CODE;
    }

    private String firstNonBlank(String... values) {
        for (String value : values) {
            if (StringUtils.hasText(value)) {
                return value;
            }
        }
        return "";
    }

    private String shortText(String value, int limit) {
        if (value == null) {
            return null;
        }
        return value.length() <= limit ? value : value.substring(0, limit);
    }

    private boolean containsAny(String keyword, String... values) {
        return Arrays.stream(values).filter(StringUtils::hasText).anyMatch(value -> value.contains(keyword));
    }

    private String writeJson(Map<String, Object> payload) {
        if (payload == null || payload.isEmpty()) {
            return null;
        }
        try {
            return objectMapper.writeValueAsString(payload);
        } catch (JsonProcessingException exception) {
            return "{}";
        }
    }

    private Long parseLongOrNull(String value) {
        if (!StringUtils.hasText(value) || !value.chars().allMatch(Character::isDigit)) {
            return null;
        }
        try {
            return Long.valueOf(value);
        } catch (NumberFormatException exception) {
            return null;
        }
    }
}
