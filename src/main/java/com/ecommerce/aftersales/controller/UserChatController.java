package com.ecommerce.aftersales.controller;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ecommerce.aftersales.common.ApiResponse;
import com.ecommerce.aftersales.common.BizException;
import com.ecommerce.aftersales.dto.UserChatDtos.*;
import com.ecommerce.aftersales.entity.AfterSalesTicket;
import com.ecommerce.aftersales.entity.ChatMessage;
import com.ecommerce.aftersales.entity.ChatSession;
import com.ecommerce.aftersales.entity.OrderInfo;
import com.ecommerce.aftersales.mapper.AfterSalesTicketMapper;
import com.ecommerce.aftersales.mapper.ChatMessageMapper;
import com.ecommerce.aftersales.mapper.ChatSessionMapper;
import com.ecommerce.aftersales.mapper.OrderInfoMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.List;

@RestController
@RequiredArgsConstructor
@RequestMapping("/chat")
public class UserChatController {

    private static final Long DEFAULT_USER_ID = 1L;
    private static final DateTimeFormatter DATE_TIME_FORMATTER = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    private final ChatSessionMapper chatSessionMapper;
    private final ChatMessageMapper chatMessageMapper;
    private final AfterSalesTicketMapper afterSalesTicketMapper;
    private final OrderInfoMapper orderInfoMapper;

    @PostMapping("/session")
    @Transactional(rollbackFor = Exception.class)
    public ApiResponse<CreateSessionResponse> createSession(@RequestBody CreateSessionRequest request) {
        ChatSession session = findExistingSession(request);
        boolean created = false;
        if (session == null) {
            session = new ChatSession();
            session.setSessionNo("CS" + System.currentTimeMillis());
            session.setUserId(DEFAULT_USER_ID);
            session.setMode("HUMAN");
            session.setStatus("WAITING");
            session.setResolved(0);
            fillBusinessContext(session, request);
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
        response.setMode(session.getMode());
        response.setStatus(session.getStatus());
        response.setWelcomeMessage(welcomeMessage(session));
        return ApiResponse.success("会话创建成功", response);
    }

    @PostMapping("/send")
    @Transactional(rollbackFor = Exception.class)
    public ApiResponse<SendMessageResponse> send(@RequestBody SendMessageRequest request) {
        if (request.getSessionId() == null) {
            throw new BizException("会话ID不能为空");
        }
        if (!StringUtils.hasText(request.getMessage())) {
            throw new BizException("消息内容不能为空");
        }
        ChatSession session = chatSessionMapper.selectById(request.getSessionId());
        if (session == null) {
            throw new BizException(404, "会话不存在");
        }
        addMessage(session.getId(), "USER", request.getMessage(), StringUtils.hasText(request.getMessageType()) ? request.getMessageType() : "TEXT");
        if (request.getMessage().contains("人工") || request.getMessage().contains("客服")) {
            session.setMode("HUMAN");
            session.setStatus("WAITING");
            chatSessionMapper.updateById(session);
        }

        SendMessageResponse response = new SendMessageResponse();
        response.setSessionId(session.getId());
        response.setMode(session.getMode());
        response.setStatus(session.getStatus());
        response.setReply(replyFor(request.getMessage(), session));
        response.setMessage("消息已发送，客服端可在在线会话中查看");
        return ApiResponse.success("发送成功", response);
    }

    @GetMapping("/history")
    public ApiResponse<ChatHistoryResponse> history(@RequestParam Long sessionId) {
        ChatSession session = chatSessionMapper.selectById(sessionId);
        if (session == null) {
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

    private ChatSession findExistingSession(CreateSessionRequest request) {
        LambdaQueryWrapper<ChatSession> wrapper = new LambdaQueryWrapper<ChatSession>()
                .eq(ChatSession::getUserId, DEFAULT_USER_ID)
                .ne(ChatSession::getStatus, "CLOSED")
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

    private void fillBusinessContext(ChatSession session, CreateSessionRequest request) {
        if (request.getAfterSaleId() != null) {
            AfterSalesTicket ticket = afterSalesTicketMapper.selectById(request.getAfterSaleId());
            if (ticket == null) {
                throw new BizException(404, "售后单不存在");
            }
            session.setTicketId(ticket.getId());
            session.setOrderId(ticket.getOrderId());
            return;
        }
        if (request.getOrderId() != null) {
            OrderInfo order = orderInfoMapper.selectById(request.getOrderId());
            if (order == null) {
                throw new BizException(404, "订单不存在");
            }
            session.setOrderId(order.getId());
        }
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

    private String welcomeMessage(ChatSession session) {
        if (session.getTicketId() != null) {
            return "您好，已收到您的售后咨询，客服会尽快处理。";
        }
        if (session.getOrderId() != null) {
            return "您好，已收到您的订单咨询，请描述您遇到的问题。";
        }
        return "您好，我是智能客服，请问有什么可以帮您？";
    }

    private String replyFor(String message, ChatSession session) {
        if (message.contains("人工") || message.contains("客服")) {
            return "已为您转接人工客服，请稍候。";
        }
        if (message.contains("退款")) {
            return "您的问题已提交给客服端，客服会结合售后单进度为您处理。";
        }
        return "问题已记录，客服端可以看到您的消息。";
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
