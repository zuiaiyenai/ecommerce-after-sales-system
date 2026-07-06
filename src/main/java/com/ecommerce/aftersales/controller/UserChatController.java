package com.ecommerce.aftersales.controller;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ecommerce.aftersales.common.ApiResponse;
import com.ecommerce.aftersales.common.BizException;
import com.ecommerce.aftersales.common.annotation.CurrentUserId;
import com.ecommerce.aftersales.config.ChatWebSocketHandler;
import com.ecommerce.aftersales.dto.UserChatDtos.ChatHistoryResponse;
import com.ecommerce.aftersales.dto.UserChatDtos.ChatMessageView;
import com.ecommerce.aftersales.dto.UserChatDtos.CreateSessionRequest;
import com.ecommerce.aftersales.dto.UserChatDtos.CreateSessionResponse;
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
import com.ecommerce.aftersales.service.NotificationService;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.List;

@RestController
@RequestMapping("/chat")
public class UserChatController {

    private static final String DEFAULT_MERCHANT_CODE = "MERCHANT_DEMO";
    private static final String MODE_AI = "AI";
    private static final String MODE_HUMAN = "HUMAN";
    private static final String STATUS_AI_ACTIVE = "AI_ACTIVE";
    private static final String STATUS_WAITING = "WAITING";
    private static final String STATUS_CLOSED = "CLOSED";
    private static final DateTimeFormatter DATE_TIME_FORMATTER = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    private final ChatSessionMapper chatSessionMapper;
    private final ChatMessageMapper chatMessageMapper;
    private final AfterSalesTicketMapper afterSalesTicketMapper;
    private final OrderInfoMapper orderInfoMapper;
    private final ChatWebSocketHandler chatWebSocketHandler;
    private final NotificationService notificationService;

    public UserChatController(ChatSessionMapper chatSessionMapper,
                              ChatMessageMapper chatMessageMapper,
                              AfterSalesTicketMapper afterSalesTicketMapper,
                              OrderInfoMapper orderInfoMapper,
                              ChatWebSocketHandler chatWebSocketHandler,
                              NotificationService notificationService) {
        this.chatSessionMapper = chatSessionMapper;
        this.chatMessageMapper = chatMessageMapper;
        this.afterSalesTicketMapper = afterSalesTicketMapper;
        this.orderInfoMapper = orderInfoMapper;
        this.chatWebSocketHandler = chatWebSocketHandler;
        this.notificationService = notificationService;
    }

    @PostMapping("/session")
    @Transactional(rollbackFor = Exception.class)
    public ApiResponse<CreateSessionResponse> createSession(@CurrentUserId Long userId,
                                                            @RequestBody CreateSessionRequest request) {
        ChatSession session = findExistingSession(userId, request);
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
            chatSessionMapper.insert(session);
            created = true;
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
        response.setMode(session.getMode());
        response.setStatus(session.getStatus());
        response.setWelcomeMessage(welcomeMessage(session));
        return ApiResponse.success("会话创建成功", response);
    }

    @PostMapping("/send")
    @Transactional(rollbackFor = Exception.class)
    public ApiResponse<SendMessageResponse> send(@CurrentUserId Long userId, @RequestBody SendMessageRequest request) {
        if (request.getSessionId() == null) {
            throw new BizException("会话ID不能为空");
        }
        if (!StringUtils.hasText(request.getMessage())) {
            throw new BizException("消息内容不能为空");
        }
        ChatSession session = chatSessionMapper.selectById(request.getSessionId());
        if (session == null || !userId.equals(session.getUserId())) {
            throw new BizException(404, "会话不存在");
        }

        String messageType = StringUtils.hasText(request.getMessageType()) ? request.getMessageType() : "TEXT";
        addMessage(session.getId(), "USER", request.getMessage(), messageType);

        boolean humanSession = MODE_HUMAN.equals(session.getMode());
        boolean transferToHuman = !humanSession && shouldTransferToHuman(request.getMessage());
        String reply = null;

        if (transferToHuman) {
            session.setMode(MODE_HUMAN);
            session.setStatus(STATUS_WAITING);
            chatSessionMapper.updateById(session);
            reply = "已为您转接人工客服，请稍候。人工客服接入后可以看到您前面和智能客服的对话内容。";
            addMessage(session.getId(), "ASSISTANT", reply, "TEXT");
            notifyMerchant(session, request.getMessage());
        } else if (humanSession) {
            broadcastToSession(session.getId(), "USER", request.getMessage(), messageType);
            notifyMerchant(session, request.getMessage());
        } else {
            reply = mockAiReply(request.getMessage(), session);
            addMessage(session.getId(), "ASSISTANT", reply, "TEXT");
        }

        SendMessageResponse response = new SendMessageResponse();
        response.setSessionId(session.getId());
        response.setMode(session.getMode());
        response.setStatus(session.getStatus());
        response.setReply(reply);
        response.setMessage(transferToHuman || humanSession ? "消息已发送，人工客服端可查看" : "智能客服已回复");
        return ApiResponse.success("发送成功", response);
    }

    @GetMapping("/history")
    public ApiResponse<ChatHistoryResponse> history(@CurrentUserId Long userId, @RequestParam Long sessionId) {
        ChatSession session = chatSessionMapper.selectById(sessionId);
        if (session == null || !userId.equals(session.getUserId())) {
            throw new BizException(404, "会话不存在");
        }
        List<ChatMessageView> messages = chatMessageMapper.selectList(new LambdaQueryWrapper<ChatMessage>()
                        .eq(ChatMessage::getSessionId, sessionId)
                        .orderByAsc(ChatMessage::getCreateTime))
                .stream()
                .map(this::toMessageView)
                .toList();
        ChatHistoryResponse response = new ChatHistoryResponse();
        response.setSessionId(sessionId);
        response.setList(messages);
        return ApiResponse.success("获取成功", response);
    }

    private void broadcastToSession(Long sessionId, String role, String content, String messageType) {
        try {
            chatWebSocketHandler.broadcastToSession(sessionId, WsChatMessage.builder()
                    .action("message")
                    .sessionId(sessionId)
                    .role(role)
                    .content(content)
                    .messageType(messageType)
                    .createdAt(LocalDateTime.now().format(DATE_TIME_FORMATTER))
                    .build());
        } catch (Exception ignored) {
            // WebSocket broadcast failure should not break the HTTP response.
        }
    }

    private ChatSession findExistingSession(Long userId, CreateSessionRequest request) {
        LambdaQueryWrapper<ChatSession> wrapper = new LambdaQueryWrapper<ChatSession>()
                .eq(ChatSession::getUserId, userId)
                .eq(ChatSession::getMerchantCode, resolveMerchantCode(request))
                .ne(ChatSession::getStatus, STATUS_CLOSED)
                .orderByDesc(ChatSession::getCreateTime)
                .last("limit 1");
        if (request.getAfterSaleId() != null) {
            wrapper.eq(ChatSession::getTicketId, request.getAfterSaleId());
        } else if (request.getOrderId() != null) {
            wrapper.eq(ChatSession::getOrderId, request.getOrderId());
        } else {
            wrapper.isNull(ChatSession::getOrderId).isNull(ChatSession::getTicketId);
        }
        return chatSessionMapper.selectOne(wrapper);
    }

    private void fillBusinessContext(ChatSession session, Long userId, CreateSessionRequest request) {
        if (request.getAfterSaleId() != null) {
            AfterSalesTicket ticket = afterSalesTicketMapper.selectById(request.getAfterSaleId());
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
        if (request.getAfterSaleId() != null) {
            AfterSalesTicket ticket = afterSalesTicketMapper.selectById(request.getAfterSaleId());
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

    private String resolveUserQuery(CreateSessionRequest request) {
        if (StringUtils.hasText(request.getMessage())) {
            return request.getMessage();
        }
        if (request.getAfterSaleId() != null) {
            AfterSalesTicket ticket = afterSalesTicketMapper.selectById(request.getAfterSaleId());
            return ticket == null ? "售后咨询" : ticket.getProductName() + " 售后咨询";
        }
        return request.getOrderId() == null ? "在线咨询" : "订单咨询";
    }

    private void addMessage(Long sessionId, String role, String content, String messageType) {
        ChatMessage message = new ChatMessage();
        message.setSessionId(sessionId);
        message.setRole(role);
        message.setContent(content);
        message.setMessageType(messageType);
        chatMessageMapper.insert(message);
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

    private String mockAiReply(String message, ChatSession session) {
        if (message.contains("退款") || message.contains("进度")) {
            return "我先为您记录退款/售后进度问题。当前为智能客服预接待，如需人工继续处理，请发送“转人工”。";
        }
        if (message.contains("物流") || message.contains("快递")) {
            return "我先为您记录物流相关问题。若需要商家人工核实物流，请发送“转人工”。";
        }
        if (message.contains("售后") || session.getTicketId() != null) {
            return "我已记录您的售后问题。当前暂未接入真实 AI，复杂处理请发送“转人工”。";
        }
        return "我已收到您的问题。当前为智能客服预接待，暂未接入真实 AI；需要人工客服时请发送“转人工”。";
    }

    private ChatMessageView toMessageView(ChatMessage message) {
        ChatMessageView view = new ChatMessageView();
        view.setId(message.getId());
        view.setRole("USER".equals(message.getRole()) ? "user" : "service");
        view.setContent(message.getContent());
        view.setMessageType(message.getMessageType());
        view.setCreateTime(message.getCreateTime() == null ? null : DATE_TIME_FORMATTER.format(message.getCreateTime()));
        return view;
    }
}
