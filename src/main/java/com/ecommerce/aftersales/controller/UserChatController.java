package com.ecommerce.aftersales.controller;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ecommerce.aftersales.common.ApiResponse;
import com.ecommerce.aftersales.common.BizException;
import com.ecommerce.aftersales.common.annotation.CurrentUserId;
import com.ecommerce.aftersales.config.ChatWebSocketHandler;
import com.ecommerce.aftersales.dto.UserChatDtos.ChatEvaluationRequest;
import com.ecommerce.aftersales.dto.UserChatDtos.ChatHistoryResponse;
import com.ecommerce.aftersales.dto.UserChatDtos.ChatMessageView;
import com.ecommerce.aftersales.dto.UserChatDtos.ChatSessionListResponse;
import com.ecommerce.aftersales.dto.UserChatDtos.ChatSessionSummary;
import com.ecommerce.aftersales.dto.UserChatDtos.CreateSessionRequest;
import com.ecommerce.aftersales.dto.UserChatDtos.CreateSessionResponse;
import com.ecommerce.aftersales.dto.UserChatDtos.HideSessionRequest;
import com.ecommerce.aftersales.dto.UserChatDtos.SendMessageRequest;
import com.ecommerce.aftersales.dto.UserChatDtos.SendMessageResponse;
import com.ecommerce.aftersales.dto.WsChatMessage;
import com.ecommerce.aftersales.entity.AfterSalesTicket;
import com.ecommerce.aftersales.entity.ChatMessage;
import com.ecommerce.aftersales.entity.ChatSession;
import com.ecommerce.aftersales.entity.OrderInfo;
import com.ecommerce.aftersales.mapper.AfterSalesTicketMapper;
import com.ecommerce.aftersales.mapper.ChatMessageMapper;
import com.ecommerce.aftersales.mapper.ChatSessionMapper;
import com.ecommerce.aftersales.mapper.OrderInfoMapper;
import com.ecommerce.aftersales.service.ChatEmotionAnalysisService;
import com.ecommerce.aftersales.service.NotificationService;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.util.StringUtils;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.HashMap;
import java.util.Collections;

@RestController
@RequestMapping("/chat")
public class UserChatController {

    private static final String DEFAULT_MERCHANT_CODE = "MERCHANT_DEMO";
    private static final String MODE_AI = "AI";
    private static final String MODE_HUMAN = "HUMAN";
    private static final String STATUS_AI_ACTIVE = "AI_ACTIVE";
    private static final String STATUS_WAITING = "WAITING";
    private static final String STATUS_CLOSED = "CLOSED";

    private final ChatSessionMapper chatSessionMapper;
    private final ChatMessageMapper chatMessageMapper;
    private final AfterSalesTicketMapper afterSalesTicketMapper;
    private final OrderInfoMapper orderInfoMapper;
    private final ChatWebSocketHandler chatWebSocketHandler;
    private final NotificationService notificationService;
    private final ChatEmotionAnalysisService chatEmotionAnalysisService;

    public UserChatController(ChatSessionMapper chatSessionMapper,
                              ChatMessageMapper chatMessageMapper,
                              AfterSalesTicketMapper afterSalesTicketMapper,
                              OrderInfoMapper orderInfoMapper,
                              ChatWebSocketHandler chatWebSocketHandler,
                              NotificationService notificationService,
                              ChatEmotionAnalysisService chatEmotionAnalysisService) {
        this.chatSessionMapper = chatSessionMapper;
        this.chatMessageMapper = chatMessageMapper;
        this.afterSalesTicketMapper = afterSalesTicketMapper;
        this.orderInfoMapper = orderInfoMapper;
        this.chatWebSocketHandler = chatWebSocketHandler;
        this.notificationService = notificationService;
        this.chatEmotionAnalysisService = chatEmotionAnalysisService;
    }

    @PostMapping("/session")
    @Transactional(rollbackFor = Exception.class)
    public ApiResponse<CreateSessionResponse> createSession(@CurrentUserId Long userId,
                                                            @RequestBody CreateSessionRequest request) {
        ChatSession session = findExistingSession(userId, request);
        if (Boolean.TRUE.equals(request.getForceNew()) && session != null) {
            LocalDateTime now = LocalDateTime.now();
            session.setStatus(STATUS_CLOSED);
            session.setCloseTime(now);
            session.setUpdateTime(now);
            chatSessionMapper.updateById(session);
            session = null;
        }
        boolean created = false;
        if (session == null) {
            session = new ChatSession();
            session.setSessionNo("CS" + System.currentTimeMillis());
            session.setUserId(userId);
            session.setMode(MODE_AI);
            session.setStatus(STATUS_AI_ACTIVE);
            session.setResolved(0);
            fillBusinessContext(session, userId, request);
            session.setUserQuery(resolveUserQuery(request));
            session.setDeleted(0);
            try {
                chatSessionMapper.insert(session);
                created = true;
            } catch (DuplicateKeyException duplicateKeyException) {
                // Another request created the same active business conversation
                // after our lookup. Reuse it rather than creating a duplicate.
                session = findExistingSession(userId, request);
                if (session == null) {
                    throw duplicateKeyException;
                }
                fillBusinessContext(session, userId, request);
                session.setUserHidden(0);
                chatSessionMapper.updateById(session);
            }
        } else if (Integer.valueOf(1).equals(session.getUserHidden())) {
            fillBusinessContext(session, userId, request);
            session.setUserHidden(0);
            chatSessionMapper.updateById(session);
        } else {
            fillBusinessContext(session, userId, request);
            chatSessionMapper.updateById(session);
        }
        if (created) {
            addMessage(session.getId(), "SYSTEM", welcomeMessage(session), "TEXT");
        }
        if (StringUtils.hasText(request.getMessage())) {
            addMessage(session.getId(), "USER", request.getMessage(), "TEXT");
        }
        CreateSessionResponse response = new CreateSessionResponse();
        response.setSessionId(session.getId());
        response.setSessionNo(session.getSessionNo());
        response.setMerchantCode(session.getMerchantCode());
        response.setMerchantDisplayName(resolveMerchantDisplayName(session.getMerchantCode()));
        response.setMode(session.getMode());
        response.setStatus(session.getStatus());
        response.setWelcomeMessage(welcomeMessage(session));
        return ApiResponse.success("会话创建成功", response);
    }

    @GetMapping("/sessions")
    public ApiResponse<ChatSessionListResponse> sessions(@CurrentUserId Long userId,
                                                          @RequestParam(defaultValue = "100") Integer limit) {
        int pageSize = Math.max(1, Math.min(limit == null ? 100 : limit, 200));
        List<ChatSession> sessions = chatSessionMapper.selectList(new LambdaQueryWrapper<ChatSession>()
                        .eq(ChatSession::getUserId, userId)
                        .eq(ChatSession::getUserHidden, 0)
                        .ne(ChatSession::getStatus, STATUS_CLOSED)
                        .orderByDesc(ChatSession::getUpdateTime)
                        .last("limit " + pageSize));
        Set<Long> orderIds = sessions.stream().map(ChatSession::getOrderId).filter(java.util.Objects::nonNull).collect(java.util.stream.Collectors.toSet());
        Set<Long> ticketIds = sessions.stream().map(ChatSession::getTicketId).filter(java.util.Objects::nonNull).collect(java.util.stream.Collectors.toSet());
        Set<Long> sessionIds = sessions.stream().map(ChatSession::getId).collect(java.util.stream.Collectors.toSet());
        Map<Long, OrderInfo> orders = orderIds.isEmpty() ? Map.of() : orderInfoMapper.selectByIds(orderIds).stream()
                .collect(java.util.stream.Collectors.toMap(OrderInfo::getId, item -> item));
        Map<Long, AfterSalesTicket> tickets = ticketIds.isEmpty() ? Map.of() : afterSalesTicketMapper.selectByIds(ticketIds).stream()
                .collect(java.util.stream.Collectors.toMap(AfterSalesTicket::getId, item -> item));
        Map<Long, ChatMessage> lastMessages = new HashMap<>();
        if (!sessionIds.isEmpty()) {
            chatMessageMapper.selectLatestBySessionIds(sessionIds)
                    .forEach(message -> lastMessages.putIfAbsent(message.getSessionId(), message));
        }
        List<ChatSessionSummary> summaries = sessions.stream()
                .map(session -> toSessionSummary(session, orders.get(session.getOrderId()),
                        tickets.get(session.getTicketId()), lastMessages.get(session.getId())))
                .toList();
        ChatSessionListResponse response = new ChatSessionListResponse();
        response.setList(summaries);
        return ApiResponse.success("获取成功", response);
    }

    @PostMapping("/send")
    @Transactional(rollbackFor = Exception.class)
    public ApiResponse<SendMessageResponse> send(@CurrentUserId Long userId, @RequestBody SendMessageRequest request) {
        if (request.getSessionId() == null) {
            throw new BizException("会话ID不能为空");
        }
        ChatSession session = chatSessionMapper.selectById(request.getSessionId());
        if (session == null || !userId.equals(session.getUserId())) {
            throw new BizException(404, "会话不存在");
        }

        String messageType = normalizeMessageType(request.getMessageType());
        String fileUrl = resolveMessageFileUrl(messageType, request.getFileUrl());
        if (!StringUtils.hasText(request.getMessage()) && !StringUtils.hasText(fileUrl)) {
            throw new BizException("消息内容不能为空");
        }
        addMessage(session.getId(), "USER", resolveMessageContent(messageType, request.getMessage()), messageType, fileUrl);

        boolean humanSession = MODE_HUMAN.equals(session.getMode());
        boolean transferToHuman = !humanSession && shouldTransferToHuman(request.getMessage());
        String reply = null;

        if (transferToHuman) {
            session.setMode(MODE_HUMAN);
            session.setStatus(STATUS_WAITING);
            chatSessionMapper.updateById(session);
            reply = "已为您转接人工客服，请稍候。人工客服接入后可以看到您前面和智能客服的对话内容。";
            addMessage(session.getId(), "ASSISTANT", reply, "TEXT", null);
            notifyMerchant(session, request.getMessage());
        } else if (humanSession) {
            broadcastToSession(session.getId(), "USER", resolveMessageContent(messageType, request.getMessage()), messageType, fileUrl);
            notifyMerchant(session, request.getMessage());
        } else {
            session.setStatus(STATUS_AI_ACTIVE);
            chatSessionMapper.updateById(session);
        }

        SendMessageResponse response = new SendMessageResponse();
        response.setSessionId(session.getId());
        response.setMode(session.getMode());
        response.setStatus(session.getStatus());
        response.setReply(reply);
        response.setMessage(transferToHuman || humanSession ? "MESSAGE_SENT_TO_HUMAN" : "MESSAGE_RECORDED");
        return ApiResponse.success("发送成功", response);
    }

    @GetMapping("/history")
    public ApiResponse<ChatHistoryResponse> history(@CurrentUserId Long userId,
                                                     @RequestParam Long sessionId,
                                                     @RequestParam(required = false) Long beforeMessageId,
                                                     @RequestParam(defaultValue = "100") Integer limit) {
        ChatSession session = chatSessionMapper.selectById(sessionId);
        if (session == null || !userId.equals(session.getUserId())) {
            throw new BizException(404, "会话不存在");
        }
        int pageSize = Math.max(1, Math.min(limit == null ? 100 : limit, 200));
        LambdaQueryWrapper<ChatMessage> wrapper = new LambdaQueryWrapper<ChatMessage>()
                .eq(ChatMessage::getSessionId, sessionId);
        if (beforeMessageId != null) {
            wrapper.lt(ChatMessage::getId, beforeMessageId);
        }
        List<ChatMessage> page = chatMessageMapper.selectList(wrapper.orderByDesc(ChatMessage::getId)
                .last("limit " + (pageSize + 1)));
        boolean hasMore = page.size() > pageSize;
        if (hasMore) {
            page = page.subList(0, pageSize);
        }
        Long nextBeforeId = hasMore && !page.isEmpty() ? page.get(page.size() - 1).getId() : null;
        Collections.reverse(page);
        List<ChatMessageView> messages = page.stream().map(this::toMessageView).toList();
        ChatHistoryResponse response = new ChatHistoryResponse();
        response.setSessionId(sessionId);
        response.setMerchantCode(session.getMerchantCode());
        response.setMerchantDisplayName(resolveMerchantDisplayName(session.getMerchantCode()));
        response.setMode(session.getMode());
        response.setStatus(session.getStatus());
        response.setList(messages);
        response.setHasMore(hasMore);
        response.setNextBeforeMessageId(nextBeforeId);
        return ApiResponse.success("获取成功", response);
    }

    @PutMapping("/session/hide")
    @Transactional(rollbackFor = Exception.class)
    public ApiResponse<Void> hideSession(@CurrentUserId Long userId, @RequestBody HideSessionRequest request) {
        if (request.getSessionId() == null) {
            throw new BizException("会话ID不能为空");
        }
        ChatSession session = chatSessionMapper.selectById(request.getSessionId());
        if (session == null || !userId.equals(session.getUserId())) {
            throw new BizException(404, "会话不存在");
        }
        session.setUserHidden(1);
        chatSessionMapper.updateById(session);
        return ApiResponse.success("移除成功", null);
    }

    @PostMapping("/evaluation")
    @Transactional(rollbackFor = Exception.class)
    public ApiResponse<Void> submitEvaluation(@CurrentUserId Long userId, @RequestBody ChatEvaluationRequest request) {
        if (request.getSessionId() == null) {
            throw new BizException("会话ID不能为空");
        }
        ChatSession session = chatSessionMapper.selectById(request.getSessionId());
        if (session == null || !userId.equals(session.getUserId())) {
            throw new BizException(404, "会话不存在");
        }
        session.setSatisfaction(request.getRating() == null ? 5 : request.getRating());
        session.setResolved(1);
        session.setStatus("READY_TO_CLOSE");
        session.setCloseTime(LocalDateTime.now());
        chatSessionMapper.updateById(session);
        addMessage(
                session.getId(),
                "SYSTEM",
                StringUtils.hasText(request.getContent()) ? request.getContent() : "用户已完成服务评价",
                "TEXT"
        );
        return ApiResponse.success("评价成功", null);
    }

    private void broadcastToSession(Long sessionId, String role, String content, String messageType, String fileUrl) {
        try {
            chatWebSocketHandler.broadcastToSession(sessionId, WsChatMessage.builder()
                    .action("message")
                    .sessionId(sessionId)
                    .role(role)
                    .content(content)
                    .messageType(messageType)
                    .fileUrl(fileUrl)
                    .createdAt(formatTime(LocalDateTime.now()))
                    .build());
        } catch (Exception ignored) {
            // WebSocket broadcast failure should not break the HTTP response.
        }
    }

    private ChatSession findExistingSession(Long userId, CreateSessionRequest request) {
        String merchantCode = resolveMerchantCode(request);
        Long relatedOrderId = resolveRelatedOrderId(request);
        LambdaQueryWrapper<ChatSession> wrapper = new LambdaQueryWrapper<ChatSession>()
                .eq(ChatSession::getUserId, userId)
                .eq(ChatSession::getMerchantCode, merchantCode)
                .ne(ChatSession::getStatus, STATUS_CLOSED)
                .orderByDesc(ChatSession::getCreateTime)
                .last("limit 1");
        if (request.getTicketId() != null) {
            wrapper.and(group -> {
                group.eq(ChatSession::getTicketId, request.getTicketId());
                if (relatedOrderId != null) {
                    group.or().eq(ChatSession::getOrderId, relatedOrderId);
                }
            });
        } else if (request.getOrderId() != null) {
            wrapper.eq(ChatSession::getOrderId, request.getOrderId());
        } else {
            wrapper.isNull(ChatSession::getOrderId).isNull(ChatSession::getTicketId);
        }
        return chatSessionMapper.selectOne(wrapper);
    }

    private void fillBusinessContext(ChatSession session, Long userId, CreateSessionRequest request) {
        if (request.getTicketId() != null) {
            AfterSalesTicket ticket = afterSalesTicketMapper.selectById(request.getTicketId());
            if (ticket == null || !userId.equals(ticket.getUserId())) {
                throw new BizException(404, "售后单不存在");
            }
            session.setTicketId(ticket.getId());
            session.setOrderId(ticket.getOrderId());
            session.setMerchantId(ticket.getMerchantId());
            session.setMerchantCode(ticket.getMerchantCode());
            return;
        }
        if (request.getOrderId() != null) {
            OrderInfo order = orderInfoMapper.selectById(request.getOrderId());
            if (order == null || !userId.equals(order.getUserId())) {
                throw new BizException(404, "订单不存在");
            }
            session.setOrderId(order.getId());
            session.setMerchantId(order.getMerchantId());
            session.setMerchantCode(order.getMerchantCode());
            return;
        }
        session.setMerchantCode(resolveMerchantCode(request));
    }

    private String resolveMerchantCode(CreateSessionRequest request) {
        if (request.getTicketId() != null) {
            AfterSalesTicket ticket = afterSalesTicketMapper.selectById(request.getTicketId());
            if (ticket != null && StringUtils.hasText(ticket.getMerchantCode())) {
                return ticket.getMerchantCode();
            }
        }
        if (request.getOrderId() != null) {
            OrderInfo order = orderInfoMapper.selectById(request.getOrderId());
            if (order != null && StringUtils.hasText(order.getMerchantCode())) {
                return order.getMerchantCode();
            }
        }
        return StringUtils.hasText(request.getMerchantCode()) ? request.getMerchantCode().trim() : DEFAULT_MERCHANT_CODE;
    }

    private Long resolveRelatedOrderId(CreateSessionRequest request) {
        if (request.getTicketId() != null) {
            AfterSalesTicket ticket = afterSalesTicketMapper.selectById(request.getTicketId());
            if (ticket != null) {
                return ticket.getOrderId();
            }
        }
        return request.getOrderId();
    }

    private String resolveUserQuery(CreateSessionRequest request) {
        if (StringUtils.hasText(request.getMessage())) {
            return request.getMessage();
        }
        if (request.getTicketId() != null) {
            AfterSalesTicket ticket = afterSalesTicketMapper.selectById(request.getTicketId());
            return ticket == null ? "售后咨询" : ticket.getProductName() + " 售后咨询";
        }
        return request.getOrderId() == null ? "在线咨询" : "订单咨询";
    }

    private void addMessage(Long sessionId, String role, String content, String messageType) {
        addMessage(sessionId, role, content, messageType, null);
    }

    private void addMessage(Long sessionId, String role, String content, String messageType, String fileUrl) {
        ChatMessage message = new ChatMessage();
        message.setSessionId(sessionId);
        message.setRole(role);
        String normalizedType = normalizeMessageType(messageType);
        String resolvedFileUrl = resolveMessageFileUrl(normalizedType, fileUrl);
        message.setContent(resolveMessageContent(normalizedType, content));
        message.setMessageType(normalizedType);
        message.setFileUrl(resolvedFileUrl);
        chatMessageMapper.insert(message);
        ChatSession session = chatSessionMapper.selectById(sessionId);
        if (session != null) {
            session.setUserHidden(0);
            session.setUpdateTime(message.getCreateTime() == null ? LocalDateTime.now() : message.getCreateTime());
            if ("USER".equalsIgnoreCase(role) && StringUtils.hasText(content)) {
                session.setUserQuery(shortText(content));
            }
            chatSessionMapper.updateById(session);
        }
        if ("USER".equalsIgnoreCase(role) && chatEmotionAnalysisService != null) {
            if (session != null) {
                chatEmotionAnalysisService.analyzeAndPersist(message, session);
            }
        }
    }

    private boolean shouldTransferToHuman(String message) {
        if (!StringUtils.hasText(message)) {
            return false;
        }
        return message.contains("人工")
                || message.contains("客服")
                || message.contains("转接")
                || message.contains("转人工")
                || message.contains("真人")
                || message.contains("投诉")
                || message.contains("协商");
    }

    private void notifyMerchant(ChatSession session, String message) {
        if (session.getMerchantId() == null) {
            return;
        }
        notificationService.createNotification(
                session.getMerchantId(),
                "新用户消息",
                "用户发来新消息：" + shortText(message),
                "CHAT",
                session.getId(),
                "CHAT_SESSION"
        );
    }

    private String shortText(String message) {
        if (message == null) {
            return "";
        }
        return message.length() > 50 ? message.substring(0, 50) + "..." : message;
    }

    private String welcomeMessage(ChatSession session) {
        if (session.getTicketId() != null) {
            return "您好，我是智能客服，已收到您的售后咨询。您可以先描述问题；如需人工处理，请发送“转人工”。";
        }
        if (session.getOrderId() != null) {
            return "您好，我是智能客服。您可以咨询订单、物流和售后问题；如需人工处理，请发送“转人工”。";
        }
        return "您好，我是智能客服，请问有什么可以帮您？如需人工处理，请发送“转人工”。";
    }

    private ChatSessionSummary toSessionSummary(ChatSession session, OrderInfo order,
                                                AfterSalesTicket ticket, ChatMessage lastMessage) {

        ChatSessionSummary summary = new ChatSessionSummary();
        summary.setSessionId(session.getId());
        summary.setOrderId(session.getOrderId());
        summary.setTicketId(session.getTicketId());
        summary.setMerchantCode(session.getMerchantCode());
        summary.setMerchantDisplayName(resolveMerchantDisplayName(session.getMerchantCode()));
        summary.setMode(session.getMode());
        summary.setStatus(session.getStatus());
        summary.setTitle(sessionTitle(session, order, ticket));
        summary.setLastMessage(lastMessage == null ? session.getUserQuery() : lastMessage.getContent());
        summary.setLastMessageTime(lastMessage == null
                ? formatTime(session.getUpdateTime())
                : formatTime(lastMessage.getCreateTime()));
        summary.setEvaluationStatus("AWAITING_EVALUATION".equals(session.getStatus()) ? "PENDING" : null);
        return summary;
    }

    private String sessionTitle(ChatSession session, OrderInfo order, AfterSalesTicket ticket) {
        if (ticket != null && StringUtils.hasText(ticket.getProductName())) {
            return ticket.getProductName();
        }
        if (order != null && StringUtils.hasText(order.getOrderNo())) {
            return "订单 " + order.getOrderNo();
        }
        return StringUtils.hasText(session.getUserQuery()) ? shortText(session.getUserQuery()) : "售后咨询";
    }

    private String formatTime(LocalDateTime time) {
        return time == null
                ? null
                : time.atZone(ZoneId.systemDefault()).format(DateTimeFormatter.ISO_OFFSET_DATE_TIME);
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

    private ChatMessageView toMessageView(ChatMessage message) {
        ChatMessageView view = new ChatMessageView();
        view.setMessageId(message.getId());
        view.setRole("USER".equals(message.getRole()) ? "user" : "service");
        view.setContent(message.getContent());
        view.setMessageType(normalizeMessageType(message.getMessageType()));
        view.setFileUrl(StringUtils.hasText(message.getFileUrl()) ? message.getFileUrl().trim() : null);
        view.setCreateTime(formatTime(message.getCreateTime()));
        return view;
    }

    private String resolveMerchantDisplayName(String merchantCode) {
        String code = StringUtils.hasText(merchantCode) ? merchantCode.trim() : DEFAULT_MERCHANT_CODE;
        if (DEFAULT_MERCHANT_CODE.equalsIgnoreCase(code)) {
            return "演示商家";
        }
        return "商家 " + code;
    }
}
