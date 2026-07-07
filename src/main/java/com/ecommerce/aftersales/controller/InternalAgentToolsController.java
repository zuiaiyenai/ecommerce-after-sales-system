package com.ecommerce.aftersales.controller;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ecommerce.aftersales.common.ApiResponse;
import com.ecommerce.aftersales.common.BizException;
import com.ecommerce.aftersales.dto.InternalAgentToolDtos;
import com.ecommerce.aftersales.entity.AfterSalesTicket;
import com.ecommerce.aftersales.entity.ChatMessage;
import com.ecommerce.aftersales.entity.ChatSession;
import com.ecommerce.aftersales.entity.MessageNotice;
import com.ecommerce.aftersales.entity.OrderInfo;
import com.ecommerce.aftersales.entity.OrderItem;
import com.ecommerce.aftersales.entity.ProductInfo;
import com.ecommerce.aftersales.entity.TicketAttachment;
import com.ecommerce.aftersales.entity.TicketLog;
import com.ecommerce.aftersales.mapper.AfterSalesTicketMapper;
import com.ecommerce.aftersales.mapper.ChatMessageMapper;
import com.ecommerce.aftersales.mapper.ChatSessionMapper;
import com.ecommerce.aftersales.mapper.MessageNoticeMapper;
import com.ecommerce.aftersales.mapper.OrderInfoMapper;
import com.ecommerce.aftersales.mapper.OrderItemMapper;
import com.ecommerce.aftersales.mapper.ProductInfoMapper;
import com.ecommerce.aftersales.mapper.TicketAttachmentMapper;
import com.ecommerce.aftersales.mapper.TicketLogMapper;
import com.ecommerce.aftersales.service.AgentPolicyCatalogService;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.transaction.annotation.Transactional;
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
import java.util.List;
import java.util.Map;
import java.util.Optional;

@RestController
@RequiredArgsConstructor
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
    private final MessageNoticeMapper messageNoticeMapper;
    private final AgentPolicyCatalogService agentPolicyCatalogService;
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

    @GetMapping("/policies/merchant")
    public ApiResponse<Map<String, Object>> merchantPolicy(
            @RequestHeader(value = "X-Agent-Internal-Token", required = false) String token,
            @RequestParam(required = false) String merchantCode
    ) {
        verifyInternalToken(token);
        return ApiResponse.success("ok", agentPolicyCatalogService.getMerchantPolicy(normalizeMerchantCode(merchantCode)));
    }

    @PostMapping("/aftersales/create")
    @Transactional(rollbackFor = Exception.class)
    public ApiResponse<InternalAgentToolDtos.TicketResult> createAfterSales(
            @RequestHeader(value = "X-Agent-Internal-Token", required = false) String token,
            @RequestBody InternalAgentToolDtos.CreateTicketRequest request
    ) {
        verifyInternalToken(token);
        requireUser(request.getUserId());
        OrderInfo order = resolveOwnedOrder(request.getUserId(), request.getOrderId());
        validateOrderCanCreateAfterSales(order);
        AfterSalesTicket existing = findOpenTicket(order.getId());
        if (existing != null) {
            // 如果售后单已存在，但AI判断通过且当前状态是PENDING，则更新为PROCESSING
            boolean aiRecommendApprove = Boolean.TRUE.equals(request.getAutoApproved());
            if (aiRecommendApprove && "PENDING".equals(existing.getStatus())) {
                String aiSuggestionReason = aiSuggestionReason(request.getAiClassifyResult());
                existing.setStatus("PROCESSING");
                existing.setPriority(0);
                existing.setAuditOpinion(shortText("AI 建议通过：" + firstNonBlank(aiSuggestionReason, "符合当前售后规则，已进入处理中，等待人工最终处理"), 500));
                existing.setAuditTime(LocalDateTime.now());
                existing.setExpectedCompleteTime(LocalDateTime.now().plusHours(12));
                existing.setUpdateTime(LocalDateTime.now());
                afterSalesTicketMapper.updateById(existing);
                bindSessionToTicket(request.getSessionId(), existing);
                addTicketLog(existing.getId(), "PENDING", "PROCESSING", "AI_RECOMMEND_APPROVE", existing.getAuditOpinion());
                return ApiResponse.success("updated_to_processing", toTicketResult(existing, false));
            }
            bindSessionToTicket(request.getSessionId(), existing);
            return ApiResponse.success("existing", toTicketResult(existing, true));
        }

        ProductInfo product = firstProduct(order.getId()).orElse(null);
        AfterSalesTicket ticket = new AfterSalesTicket();
        ticket.setTicketNo("AS" + System.currentTimeMillis());
        ticket.setOrderId(order.getId());
        ticket.setOrderNo(order.getOrderNo());
        ticket.setUserId(order.getUserId());
        ticket.setMerchantId(order.getMerchantId());
        ticket.setMerchantCode(normalizeMerchantCode(order.getMerchantCode()));
        ticket.setPolicyCode(request.getPolicyCode());
        ticket.setPolicyVersion(request.getPolicyVersion());
        ticket.setProductName(product == null ? "售后商品" : product.getProductName());
        ticket.setAfterSaleType(normalizeAfterSalesType(request.getAfterSalesType()));
        ticket.setReason(normalizeReason(request.getReason()));
        ticket.setReasonDetail(shortText(firstNonBlank(request.getReasonDetail(), request.getDescription(), "AI 售后申请"), 500));
        ticket.setDescription(shortText(request.getDescription(), 1000));
        ticket.setRefundAmount(resolveRefundAmount(request.getRefundAmount(), order));
        ticket.setAiClassifyResult(shortText(writeJson(request.getAiClassifyResult()), 200));
        ticket.setAiConfidence(normalizeScore(request.getAiConfidence()));
        ticket.setAiRecommendType(normalizeAfterSalesType(firstNonBlank(request.getAiRecommendType(), ticket.getAfterSaleType())));
        boolean aiRecommendApprove = Boolean.TRUE.equals(request.getAutoApproved());
        String aiSuggestionReason = aiSuggestionReason(request.getAiClassifyResult());
        ticket.setStatus(aiRecommendApprove ? "PROCESSING" : "PENDING");
        ticket.setPriority(aiRecommendApprove ? 0 : 1);
        ticket.setAuditOpinion(aiRecommendApprove
                ? shortText("AI 建议通过：" + firstNonBlank(aiSuggestionReason, "符合当前售后规则，已进入处理中，等待人工最终处理"), 500)
                : shortText(firstNonBlank(aiSuggestionReason, "AI 已创建售后申请，等待人工审核或补充凭证"), 500));
        if (aiRecommendApprove) {
            ticket.setAuditTime(LocalDateTime.now());
        }
        ticket.setExpectedCompleteTime(LocalDateTime.now().plusHours(aiRecommendApprove ? 12 : 24));
        ticket.setDeleted(0);
        afterSalesTicketMapper.insert(ticket);
        bindSessionToTicket(request.getSessionId(), ticket);

        saveAttachments(ticket.getId(), request.getEvidenceUrls());
        addTicketLog(ticket.getId(), null, "PENDING", "AI_SUBMIT", "用户已提交售后申请，进入待审核");
        if (aiRecommendApprove) {
            addTicketLog(ticket.getId(), "PENDING", "PROCESSING", "AI_RECOMMEND_APPROVE", ticket.getAuditOpinion());
        }
        createNotice(order.getUserId(), "售后申请已创建", "您的售后申请 " + ticket.getTicketNo() + " 已创建", ticket.getId());
        return ApiResponse.success("created", toTicketResult(ticket, false));
    }

    private void bindSessionToTicket(Long sessionId, AfterSalesTicket ticket) {
        if (sessionId == null || ticket == null) {
            return;
        }
        ChatSession session = chatSessionMapper.selectById(sessionId);
        if (session == null || !ticket.getUserId().equals(session.getUserId())) {
            return;
        }
        session.setTicketId(ticket.getId());
        session.setOrderId(ticket.getOrderId());
        session.setMerchantId(ticket.getMerchantId());
        session.setMerchantCode(ticket.getMerchantCode());
        session.setUpdateTime(LocalDateTime.now());
        chatSessionMapper.updateById(session);
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

        ChatMessage message = new ChatMessage();
        message.setSessionId(session.getId());
        message.setRole(normalizeRole(request.getRole()));
        message.setContent(firstNonBlank(request.getContent(), ""));
        message.setMessageType(firstNonBlank(request.getMessageType(), "TEXT"));
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

        session.setUserQuery(shortText(message.getContent(), 500));
        session.setUpdateTime(LocalDateTime.now());
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
        session.setMode("HUMAN");
        session.setStatus("WAITING");
        session.setTicketId(request.getTicketId() == null ? session.getTicketId() : request.getTicketId());
        session.setEmotionLabel(request.getEmotionLabel());
        session.setEmotionScore(normalizeScore(request.getEmotionScore()));
        session.setEmotionConfidence(normalizeScore(request.getEmotionConfidence()));
        session.setUserQuery(shortText(firstNonBlank(request.getSummary(), "AI 建议转人工"), 500));
        session.setResolved(0);
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

    private void validateOrderCanCreateAfterSales(OrderInfo order) {
        String status = Optional.ofNullable(order.getStatus()).orElse("");
        if (!List.of("PAID", "SHIPPED", "RECEIVED", "COMPLETED", "CLOSED").contains(status)) {
            throw new BizException(400, "current order status does not allow after-sales");
        }
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
        summary.setId(order.getId());
        summary.setOrderNo(order.getOrderNo());
        summary.setUserId(order.getUserId());
        summary.setMerchantId(order.getMerchantId());
        summary.setMerchantCode(normalizeMerchantCode(order.getMerchantCode()));
        summary.setStatus(order.getStatus());
        summary.setAmount(firstPositive(order.getPayAmount(), order.getTotalAmount(), BigDecimal.ZERO));
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
        result.setId(ticket.getId());
        result.setTicketNo(ticket.getTicketNo());
        result.setOrderId(ticket.getOrderId());
        result.setOrderNo(ticket.getOrderNo());
        result.setUserId(ticket.getUserId());
        result.setMerchantCode(ticket.getMerchantCode());
        result.setStatus(ticket.getStatus());
        result.setAfterSalesType(ticket.getAfterSaleType());
        result.setRefundAmount(ticket.getRefundAmount());
        result.setExisting(existing);
        return result;
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

    private void saveAttachments(Long ticketId, List<String> urls) {
        if (urls == null || urls.isEmpty()) {
            return;
        }
        int sort = 0;
        for (String url : urls) {
            if (!StringUtils.hasText(url)) {
                continue;
            }
            TicketAttachment attachment = new TicketAttachment();
            attachment.setTicketId(ticketId);
            attachment.setFileUrl(url);
            attachment.setFileType("IMAGE");
            attachment.setFileName(url.substring(url.lastIndexOf('/') + 1));
            attachment.setFileSize(0L);
            attachment.setSortOrder(sort++);
            ticketAttachmentMapper.insert(attachment);
        }
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

    private void createNotice(Long userId, String title, String content, Long ticketId) {
        MessageNotice notice = new MessageNotice();
        notice.setUserId(userId);
        notice.setTitle(title);
        notice.setContent(content);
        notice.setNoticeType("AFTER_SALE");
        notice.setRefType("TICKET");
        notice.setRefId(ticketId);
        notice.setIsRead(0);
        messageNoticeMapper.insert(notice);
    }

    private BigDecimal resolveRefundAmount(BigDecimal requested, OrderInfo order) {
        BigDecimal orderAmount = firstPositive(order.getPayAmount(), order.getTotalAmount(), BigDecimal.ZERO);
        if (requested == null || requested.compareTo(BigDecimal.ZERO) <= 0) {
            return orderAmount;
        }
        if (orderAmount.compareTo(BigDecimal.ZERO) > 0 && requested.compareTo(orderAmount) > 0) {
            throw new BizException(400, "refund amount exceeds order amount");
        }
        return requested;
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

    private String normalizeAfterSalesType(String type) {
        String value = firstNonBlank(type, "RETURN_REFUND").trim().toUpperCase();
        return switch (value) {
            case "REFUND", "REFUND_ONLY" -> "REFUND_ONLY";
            case "REISSUE", "RESEND", "EXCHANGE" -> "REISSUE";
            case "PARTIAL_REFUND" -> "PARTIAL_REFUND";
            default -> "RETURN_REFUND";
        };
    }

    private String normalizeReason(String reason) {
        String value = firstNonBlank(reason, "QUALITY").trim().toUpperCase();
        return switch (value) {
            case "DAMAGE", "LOGISTICS", "OTHER", "QUALITY" -> value;
            default -> "OTHER";
        };
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

    private String aiSuggestionReason(Map<String, Object> payload) {
        if (payload == null || payload.isEmpty()) {
            return "";
        }
        Object reason = payload.get("reason");
        if (reason == null) {
            reason = payload.get("ai_suggestion_reason");
        }
        if (reason == null) {
            reason = payload.get("suggestionReason");
        }
        return reason == null ? "" : String.valueOf(reason);
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
