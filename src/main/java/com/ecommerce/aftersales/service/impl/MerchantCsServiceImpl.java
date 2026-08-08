package com.ecommerce.aftersales.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ecommerce.aftersales.common.BizException;
import com.ecommerce.aftersales.common.PageResult;
import com.ecommerce.aftersales.config.ChatWebSocketHandler;
import com.ecommerce.aftersales.dto.MerchantCsDtos.*;
import com.ecommerce.aftersales.dto.WsChatMessage;
import com.ecommerce.aftersales.entity.*;
import com.ecommerce.aftersales.mapper.*;
import com.ecommerce.aftersales.service.AgentGatewayService;
import com.ecommerce.aftersales.service.AgentGatewayMetrics;
import com.ecommerce.aftersales.service.ChatEmotionAnalysisService;
import com.ecommerce.aftersales.service.KnowledgeRetrievalService;
import com.ecommerce.aftersales.service.MerchantCsService;
import com.ecommerce.aftersales.service.NotificationService;
import com.ecommerce.aftersales.service.VerificationCodeService;
import com.ecommerce.aftersales.util.JwtTokenUtil;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

import java.math.BigDecimal;
import java.time.Duration;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;
import java.util.function.Function;
import java.util.stream.Collectors;

@Slf4j
@Service
@RequiredArgsConstructor
public class MerchantCsServiceImpl implements MerchantCsService {

    private static final String DEFAULT_MERCHANT_CODE = "MERCHANT_DEMO";
    private static final String REGISTER_SCENE = "REGISTER";
    private static final String RESET_PASSWORD_SCENE = "RESET_PASSWORD";
    private static final int STATUS_ACTIVE = 1;
    private static final int STATUS_PENDING_APPROVAL = 2;
    private static final Duration EVALUATION_TIMEOUT = Duration.ofMinutes(30);
    private static final Duration PERFORMANCE_TARGET_HANDLE_TIME = Duration.ofMinutes(8);
    private static final Duration PERFORMANCE_TARGET_RESPONSE_TIME = Duration.ofMinutes(5);
    private static final int PERFORMANCE_WINDOW_DAYS = 7;
    private static final DateTimeFormatter INPUT_DATE_TIME_FORMATTER = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");
    private static final String EVALUATION_INVITE_MESSAGE = "售后处理已完成，请对本次客服服务进行评价。";

    private final SysUserMapper sysUserMapper;
    private final ChatSessionMapper chatSessionMapper;
    private final ChatMessageMapper chatMessageMapper;
    private final AfterSalesTicketMapper afterSalesTicketMapper;
    private final TicketLogMapper ticketLogMapper;
    private final OrderInfoMapper orderInfoMapper;
    private final OrderItemMapper orderItemMapper;
    private final ProductInfoMapper productInfoMapper;
    private final UserMapper userMapper;
    private final MessageNoticeMapper messageNoticeMapper;
    private final AgentGatewayService agentGatewayService;
    private final AgentGatewayMetrics metrics;
    private final PasswordEncoder passwordEncoder;
    private final JwtTokenUtil jwtTokenUtil;
    private final ObjectMapper objectMapper;
    private final ChatWebSocketHandler chatWebSocketHandler;
    private final NotificationService notificationService;
    private final VerificationCodeService verificationCodeService;
    private final KnowledgeRetrievalService knowledgeRetrievalService;
    private final ChatEmotionAnalysisService chatEmotionAnalysisService;
    private final ReviewInfoMapper reviewInfoMapper;

    @Override
    @Transactional(rollbackFor = Exception.class)
    public LoginResponse login(LoginRequest request) {
        if (!StringUtils.hasText(request.getAccount()) || !StringUtils.hasText(request.getPassword())) {
            throw new BizException("账号和密码不能为空");
        }
        SysUser staff = findStaffByAccountAnyMerchant(request.getAccount().trim());
        if (staff == null || !passwordEncoder.matches(request.getPassword(), staff.getPassword())) {
            throw new BizException("账号或密码错误");
        }
        if (Integer.valueOf(STATUS_PENDING_APPROVAL).equals(staff.getStatus())) {
            throw new BizException(403, "注册申请已提交，请等待管理员审核通过后再登录");
        }
        if (!Integer.valueOf(STATUS_ACTIVE).equals(staff.getStatus())) {
            throw new BizException(403, "客服账号已被停用，请联系管理员处理");
        }
        staff.setOnlineStatus(1);
        staff.setLastLoginTime(LocalDateTime.now());
        sysUserMapper.updateById(staff);

        LoginResponse response = new LoginResponse();
        response.setToken(jwtTokenUtil.generateToken(staff.getId(), Optional.ofNullable(staff.getPhone()).orElse(staff.getUsername())));
        response.setStaff(toStaffProfile(staff));
        return response;
    }

    @Override
    public String sendAuthCode(AuthCodeRequest request) {
        String scene = normalizeAuthScene(request == null ? null : request.getScene());
        String phone = normalizePhone(request == null ? null : request.getPhone());
        if (!StringUtils.hasText(phone)) {
            throw new BizException("请输入手机号");
        }
        if (REGISTER_SCENE.equals(scene)) {
            if (request != null && StringUtils.hasText(request.getAccount()) && accountExistsAnywhere(request.getAccount().trim())) {
                throw new BizException("账号已存在，请更换其他账号");
            }
            return verificationCodeService.sendCode(phone, REGISTER_SCENE);
        }

        String account = request == null ? null : request.getAccount();
        if (!StringUtils.hasText(account)) {
            throw new BizException("请输入登录账号");
        }
        SysUser staff = findStaffByAccountAnyMerchant(account.trim());
        if (staff == null) {
            throw new BizException("账号不存在");
        }
        String boundPhone = normalizePhone(staff.getPhone());
        if (!StringUtils.hasText(boundPhone)) {
            throw new BizException("该账号未绑定手机号，请联系管理员处理");
        }
        if (!boundPhone.equals(phone)) {
            throw new BizException("账号与手机号不匹配");
        }
        return verificationCodeService.sendCode(phone, RESET_PASSWORD_SCENE);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public StaffProfile register(RegisterRequest request) {
        if (!StringUtils.hasText(request.getAccount())
                || !StringUtils.hasText(request.getPassword())
                || !StringUtils.hasText(request.getRealName())
                || !StringUtils.hasText(request.getPhone())
                || !StringUtils.hasText(request.getCode())) {
            throw new BizException("请填写账号、密码、姓名、手机号和验证码");
        }
        verificationCodeService.verifyCode(normalizePhone(request.getPhone()), REGISTER_SCENE, request.getCode());
        if (accountExistsAnywhere(request.getAccount().trim())) {
            throw new BizException("该账号已存在");
        }

        SysUser staff = new SysUser();
        staff.setUsername(request.getAccount().trim());
        staff.setPassword(passwordEncoder.encode(request.getPassword()));
        staff.setMerchantCode(DEFAULT_MERCHANT_CODE);
        staff.setRealName(request.getRealName().trim());
        staff.setPhone(normalizePhone(request.getPhone()));
        staff.setRoleType("AGENT");
        staff.setStatus(STATUS_PENDING_APPROVAL);
        staff.setOnlineStatus(0);
        staff.setMaxSessions(8);
        staff.setDeleted(0);
        sysUserMapper.insert(staff);
        return toStaffProfile(staff);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void resetPassword(ResetPasswordRequest request) {
        if (request == null
                || !StringUtils.hasText(request.getAccount())
                || !StringUtils.hasText(request.getPhone())
                || !StringUtils.hasText(request.getCode())
                || !StringUtils.hasText(request.getNewPassword())
                || !StringUtils.hasText(request.getConfirmPassword())) {
            throw new BizException("请填写账号、手机号、验证码和新密码");
        }
        if (!request.getNewPassword().equals(request.getConfirmPassword())) {
            throw new BizException("两次输入的密码不一致");
        }
        SysUser staff = findStaffByAccountAnyMerchant(request.getAccount().trim());
        if (staff == null) {
            throw new BizException("账号不存在");
        }
        String phone = normalizePhone(request.getPhone());
        if (!phone.equals(normalizePhone(staff.getPhone()))) {
            throw new BizException("账号与手机号不匹配");
        }
        verificationCodeService.verifyCode(phone, RESET_PASSWORD_SCENE, request.getCode());
        staff.setPassword(passwordEncoder.encode(request.getNewPassword()));
        sysUserMapper.updateById(staff);
    }

    @Override
    public void logout() {
    }

    @Override
    public StaffProfile getCurrentStaff() {
        return toStaffProfile(ensureStaff());
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public StaffProfile updateWorkStatus(String onlineStatus) {
        SysUser staff = ensureStaff();
        staff.setOnlineStatus(toOnlineStatusValue(onlineStatus));
        sysUserMapper.updateById(staff);
        return toStaffProfile(staff);
    }

    @Override
    public DashboardOverview getDashboardOverview() {
        StaffProfile staff = getCurrentStaff();
        List<SessionView> sessions = allSessions();
        List<TicketView> tickets = allTickets();
        long waitingSessions = sessions.stream().filter(item -> List.of("WAITING", "PROCESSING").contains(item.getStatus())).count();
        long pendingTickets = tickets.stream().filter(item -> "PENDING_REVIEW".equals(item.getStatus())).count();
        long warningTickets = tickets.stream().filter(item -> "HIGH".equals(item.getPriority())).count();

        DashboardOverview overview = new DashboardOverview();
        overview.setGreeting("您好，" + staff.getRealName());
        overview.setTodayTodoCount((int) (waitingSessions + pendingTickets + warningTickets));
        overview.setSubtitle("当前还有 " + overview.getTodayTodoCount() + " 项任务待处理");
        overview.setAiEnabled(true);
        overview.setMetrics(List.of(
                metric("待接入会话", waitingSessions, "+0", "orange"),
                metric("待审核申请", pendingTickets, "+0", "slate"),
                metric("超时预警", warningTickets, "+0", "green")
        ));
        overview.setTimeline(buildTimeline());
        return overview;
    }

    @Override
    public List<TodoItem> getDashboardTodos() {
        List<TodoItem> todos = new ArrayList<>();
        for (TicketView ticket : allTickets().stream().filter(item -> "PENDING_REVIEW".equals(item.getStatus())).limit(5).toList()) {
            TodoItem item = new TodoItem();
            item.setId(ticket.getTicketId());
            item.setTitle("售后申请 #" + ticket.getTicketNo());
            item.setTag(ticket.getAfterSalesType());
            item.setAmount(Optional.ofNullable(ticket.getApplyRefundAmount()).orElse("0.00") + " 元");
            item.setPriority(ticket.getPriority());
            item.setPriorityTone("HIGH".equals(ticket.getPriority()) ? "high" : "normal");
            item.setAction("审核");
            item.setTarget("/tickets/" + ticket.getTicketId());
            todos.add(item);
        }
        for (SessionView session : allSessions().stream().filter(item -> "WAITING".equals(item.getStatus())).limit(5).toList()) {
            TodoItem item = new TodoItem();
            item.setId(session.getSessionId());
            item.setTitle("会话 #" + session.getSessionNo());
            item.setTag("人工介入");
            item.setAmount(Optional.ofNullable(session.getEmotion()).orElse("待处理"));
            item.setPriority("HIGH".equals(session.getLevel()) ? "HIGH" : "NORMAL");
            item.setPriorityTone("high");
            item.setAction("接入");
            item.setTarget("/sessions/" + session.getSessionId());
            todos.add(item);
        }
        return todos;
    }

    @Override
    public DashboardPerformance getDashboardPerformance() {
        List<ChatSession> sessions = allHumanSessionEntities();
        LocalDate today = LocalDate.now();
        LocalDate startDate = today.minusDays(PERFORMANCE_WINDOW_DAYS - 1L);
        List<ChatSession> recentSessions = sessions.stream()
                .filter(session -> sessionActivityDate(session)
                        .map(date -> !date.isBefore(startDate) && !date.isAfter(today))
                        .orElse(false))
                .toList();

        // 平均响应时长：基于 chat_message 中 USER→SERVICE 的时间差
        MetricSnapshot avgResponseTimeMetric = buildAvgResponseTimeMetric(recentSessions);
        // 满意度/好评率：切换到 review_info（真实评价表）
        MetricSnapshot satisfactionMetric = withFallback(buildReviewSatisfactionMetric(), buildSatisfactionMetric(recentSessions));
        MetricSnapshot goodRateMetric = withFallback(buildReviewGoodRateMetric(), buildGoodRateMetric(recentSessions));
        // 综合分：满意度 40% + 好评率 40% + 响应时长 20%
        int serviceScore = calculateWeightedServiceScore(avgResponseTimeMetric, satisfactionMetric, goodRateMetric);

        DashboardPerformance performance = new DashboardPerformance();
        performance.setServiceScore(serviceScore);
        performance.setScoreStatus(resolveScoreStatus(serviceScore));
        performance.setTrend(buildReviewBasedTrend(startDate, today));
        performance.setTrendSummary(buildTrendSummary(performance.getTrend()));
        performance.setTags(buildPerformanceTags(serviceScore, avgResponseTimeMetric, satisfactionMetric, goodRateMetric));
        performance.setMetrics(List.of(
                performanceMetric("平均响应时长", avgResponseTimeMetric.value(), "目标 ≤ 5分钟",
                        avgResponseTimeMetric.currentPercent(), 100, avgResponseTimeMetric.sampleSize(), true),
                performanceMetric("用户满意度", satisfactionMetric.value(), "目标 ≥ 4.5 / 5（基于真实评价）",
                        satisfactionMetric.currentPercent(), 90, satisfactionMetric.sampleSize(), false),
                performanceMetric("好评率", goodRateMetric.value(), "目标 ≥ 90%（基于真实评价）",
                        goodRateMetric.currentPercent(), 90, goodRateMetric.sampleSize(), false)
        ));
        return performance;
    }

    @Override
    public PageResult<SessionView> listSessions(long page, long size, String status, String keyword) {
        List<SessionView> sessions = allSessions();
        metrics.setMerchantQueueUnrepliedCount(sessions.stream()
                .filter(item -> MerchantSessionPriorityPolicy.REPLY_STATUS_UNREPLIED.equals(item.getReplyStatus()))
                .count());
        List<SessionView> records = sessions.stream()
                .filter(item -> !StringUtils.hasText(status) || status.equals(item.getStatus()))
                .filter(item -> !StringUtils.hasText(keyword) || containsAny(keyword, item.getSessionNo(), item.getUser(), item.getTopic(), item.getLastMessageContent()))
                .toList();
        return PageResult.of(records, page, size);
    }

    @Override
    public SessionView getSession(Long sessionId) {
        ChatSession session = findSession(sessionId);
        backfillSessionEmotionIfMissing(session);
        return toSessionView(session);
    }

    @Override
    public List<MessageView> listSessionMessages(Long sessionId) {
        findSession(sessionId);
        List<ChatMessage> messages = chatMessageMapper.selectList(new LambdaQueryWrapper<ChatMessage>()
                        .eq(ChatMessage::getSessionId, sessionId)
                        .orderByAsc(ChatMessage::getCreateTime));
        chatEmotionAnalysisService.backfillMissingEmotions(sessionId, messages);
        return messages.stream()
                .map(this::toMessageView)
                .toList();
    }

    @Override
    public SessionAiAssistView getSessionAiAssist(Long sessionId) {
        ChatSession session = findSession(sessionId);
        List<ChatMessage> messages = chatMessageMapper.selectList(new LambdaQueryWrapper<ChatMessage>()
                .eq(ChatMessage::getSessionId, sessionId)
                .orderByAsc(ChatMessage::getCreateTime)
                .last("limit 20"));
        ChatMessage latestUserMessage = messages.stream()
                .filter(message -> "USER".equalsIgnoreCase(message.getRole()))
                .reduce((first, second) -> second)
                .orElse(null);
        ChatMessage latestServiceMessage = messages.stream()
                .filter(message -> !"USER".equalsIgnoreCase(message.getRole()))
                .filter(message -> StringUtils.hasText(message.getContent()))
                .reduce((first, second) -> second)
                .orElse(null);

        SessionAiAssistView view = new SessionAiAssistView();
        view.setSessionId(sessionId);
        view.setLatestUserMessage(latestUserMessage == null ? null : latestUserMessage.getContent());
        view.setSceneCode("after_sales");
        view.setIntentCode("general");
        view.setKnowledgeQuery(latestServiceMessage == null ? null : latestServiceMessage.getKnowledgeQuery());
        view.setKnowledgeRetrievalMode(latestServiceMessage == null ? null : latestServiceMessage.getKnowledgeRetrievalMode());
        view.setKnowledgeHits(latestServiceMessage == null ? List.of() : parseKnowledgeHits(latestServiceMessage.getKnowledgeHitsJson()));
        view.setHandoffSummaryText(Optional.ofNullable(session.getUserQuery()).orElse(""));
        view.setConversationDigest(buildConversationDigest(session, latestUserMessage));

        if (latestServiceMessage != null && StringUtils.hasText(latestServiceMessage.getContent())) {
            RecommendationView recommendation = new RecommendationView();
            recommendation.setText(latestServiceMessage.getContent());
            recommendation.setConfidence(latestServiceMessage.getConfidence());
            recommendation.setSource("latest_service_reply");
            recommendation.setReason("基于最近一条客服回复生成");
            recommendation.setIntentCode(view.getIntentCode());
            recommendation.setSceneCode(view.getSceneCode());
            recommendation.setTone("neutral");
            view.setRecommendation(recommendation);

            QuickReplyView suggestion = new QuickReplyView();
            suggestion.setCode("latest_reply");
            suggestion.setLabel("最近回复");
            suggestion.setText(latestServiceMessage.getContent());
            suggestion.setSceneCode(view.getSceneCode());
            suggestion.setIntentCode(view.getIntentCode());
            suggestion.setTone("neutral");
            suggestion.setScore(latestServiceMessage.getConfidence());
            view.setStaffSuggestion(suggestion);
        }

        view.setQuickReplySource("session_context");
        view.setQuickReplies(buildQuickReplies(session));
        view.setTrace(Map.of("source", "merchant_cs_session"));
        return view;
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public MessageView sendSessionMessage(Long sessionId, SendMessageRequest request) {
        ChatSession session = findSession(sessionId);
        String messageType = normalizeMessageType(request.getMessageType());
        String fileUrl = resolveMessageFileUrl(messageType, request.getFileUrl());
        if (!StringUtils.hasText(request.getContent()) && !StringUtils.hasText(fileUrl)) {
            throw new BizException("消息内容不能为空");
        }
        SysUser staff = ensureStaff();
        ChatMessage message = new ChatMessage();
        message.setSessionId(sessionId);
        message.setRole("SERVICE");
        message.setMessageType(messageType);
        message.setContent(resolveMessageContent(messageType, request.getContent()));
        message.setFileUrl(fileUrl);
        chatMessageMapper.insert(message);
        if ("WAITING".equals(session.getStatus())) {
            session.setStatus("ACTIVE");
            session.setHumanAgentId(staff.getId());
        }
        session.setUpdateTime(message.getCreateTime() == null ? LocalDateTime.now() : message.getCreateTime());
        chatSessionMapper.updateById(session);
        // Broadcast staff message via WebSocket
        broadcastToSession(sessionId, "SERVICE", message.getContent(), messageType, fileUrl);

        // Notify user about merchant reply
        notificationService.createNotification(
                session.getUserId(),
                "客服已回复",
                "客服回复了您的咨询：" + (message.getContent().length() > 50
                        ? message.getContent().substring(0, 50) + "..."
                        : message.getContent()),
                "CHAT",
                sessionId,
                "CHAT_SESSION"
        );

        return toMessageView(message);
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
                    .createdAt(format(LocalDateTime.now()))
                    .build());
        } catch (Exception ignored) {
            // WebSocket broadcast failure should not break the HTTP response
        }
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public SessionView requestSessionEvaluation(Long sessionId) {
        ChatSession session = findSession(sessionId);
        if (!"PROCESSING".equals(toMerchantSessionStatus(session))) {
            throw new BizException("只有处理中会话才能发送评价请求");
        }
        LocalDateTime now = LocalDateTime.now();
        session.setStatus("AWAITING_EVALUATION");
        session.setResolved(0);
        session.setUpdateTime(now);
        chatSessionMapper.updateById(session);
        addSystemMessage(sessionId, "已发送服务评价邀请，等待用户评价。");
        notificationService.createNotification(
                session.getUserId(),
                "请评价本次客服服务",
                "您的售后问题已处理完成，请对本次客服服务进行评价。",
                "CHAT",
                sessionId,
                "CHAT_SESSION"
        );
        return toSessionView(session);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public SessionView submitSessionEvaluation(Long sessionId, EvaluationRequest request) {
        ChatSession session = findSession(sessionId);
        if (!"AWAITING_EVALUATION".equals(session.getStatus())) {
            throw new BizException("当前会话不在待评价状态");
        }
        LocalDateTime now = LocalDateTime.now();
        session.setResolved(1);
        session.setSatisfaction(request.getRating() == null ? 5 : request.getRating());
        session.setStatus("READY_TO_CLOSE");
        session.setCloseTime(now);
        session.setUpdateTime(now);
        chatSessionMapper.updateById(session);
        upsertReviewInfoFromSession(session, request);
        addSystemMessage(sessionId, StringUtils.hasText(request.getContent()) ? request.getContent() : "用户已完成服务评价");
        return toSessionView(session);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public SessionView closeSession(Long sessionId) {
        ChatSession session = findSession(sessionId);
        if (!canCloseSession(session)) {
            throw new BizException("只有用户已评价或评价已超时的会话才能关闭");
        }
        LocalDateTime now = LocalDateTime.now();
        session.setStatus("CLOSED");
        session.setCloseTime(now);
        session.setUpdateTime(now);
        chatSessionMapper.updateById(session);
        addSystemMessage(sessionId, "会话已由客服关闭。");
        return toSessionView(session);
    }

    @Override
    public PageResult<TicketView> listTickets(long page, long size, String status, String type, String keyword) {
        List<TicketView> records = allTickets().stream()
                .filter(item -> !StringUtils.hasText(status) || status.equals(item.getStatus()))
                .filter(item -> !StringUtils.hasText(type) || type.equals(item.getAfterSalesType()))
                .filter(item -> !StringUtils.hasText(keyword) || containsAny(keyword, item.getTicketNo(), item.getOrderNo(), item.getTitle(), item.getReasonType()))
                .toList();
        return PageResult.of(records, page, size);
    }

    @Override
    public TicketView getTicket(Long ticketId) {
        return toTicketView(findTicket(ticketId));
    }

    @Override
    public List<TicketLogView> listTicketLogs(Long ticketId) {
        findTicket(ticketId);
        return ticketLogMapper.selectList(new LambdaQueryWrapper<TicketLog>()
                        .eq(TicketLog::getTicketId, ticketId)
                        .orderByAsc(TicketLog::getCreateTime))
                .stream()
                .map(this::toTicketLogView)
                .toList();
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public TicketView approveTicket(Long ticketId, String auditOpinion) {
        AfterSalesTicket ticket = findTicket(ticketId);
        if (!"PENDING".equals(ticket.getStatus()) && !"PENDING_REVIEW".equals(ticket.getStatus())) {
            throw new BizException("只有待审核状态的申请才能审核通过");
        }
        String oldStatus = ticket.getStatus();
        ticket.setStatus("PROCESSING");
        ticket.setAuditOpinion(StringUtils.hasText(auditOpinion) ? auditOpinion : "审核通过，进入处理中");
        ticket.setAuditTime(LocalDateTime.now());
        ticket.setAssigneeId(ensureStaff().getId());
        afterSalesTicketMapper.updateById(ticket);
        addTicketLog(ticket, oldStatus, "PROCESSING", "APPROVE", ticket.getAuditOpinion());
        // Notify user about approval
        notificationService.createNotification(
                ticket.getUserId(),
                "售后申请审核通过",
                "您的售后申请 " + ticket.getTicketNo() + " 已审核通过，当前处理中",
                "AFTER_SALE",
                ticket.getId(),
                "TICKET"
        );
        return toTicketView(ticket);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public TicketView rejectTicket(Long ticketId, String rejectReason) {
        AfterSalesTicket ticket = findTicket(ticketId);
        if (!"PENDING".equals(ticket.getStatus()) && !"PENDING_REVIEW".equals(ticket.getStatus())) {
            throw new BizException("只有待审核状态的申请才能驳回");
        }
        String oldStatus = ticket.getStatus();
        ticket.setStatus("REJECTED");
        ticket.setAuditOpinion(StringUtils.hasText(rejectReason) ? rejectReason : "资料不足，请补充凭证");
        ticket.setAuditTime(LocalDateTime.now());
        ticket.setAssigneeId(ensureStaff().getId());
        afterSalesTicketMapper.updateById(ticket);
        addTicketLog(ticket, oldStatus, "REJECTED", "REJECT", ticket.getAuditOpinion());
        // Notify user about rejection
        notificationService.createNotification(
                ticket.getUserId(),
                "售后申请已驳回",
                "您的售后申请 " + ticket.getTicketNo() + " 已被驳回，原因：" + ticket.getAuditOpinion(),
                "AFTER_SALE",
                ticket.getId(),
                "TICKET"
        );
        return toTicketView(ticket);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public TicketView completeTicket(Long ticketId, String completeNote) {
        AfterSalesTicket ticket = findTicket(ticketId);
        if (!"PROCESSING".equals(ticket.getStatus())) {
            throw new BizException("只有处理中状态的申请才能标记为已完成");
        }
        String oldStatus = ticket.getStatus();
        ticket.setStatus("COMPLETED");
        ticket.setCompleteTime(LocalDateTime.now());
        ticket.setAuditOpinion(StringUtils.hasText(completeNote) ? completeNote : "处理完成");
        ticket.setAssigneeId(ensureStaff().getId());
        afterSalesTicketMapper.updateById(ticket);
        addTicketLog(ticket, oldStatus, "COMPLETED", "COMPLETE", ticket.getAuditOpinion());
        markRelatedSessionsReadyForEvaluation(ticket);
        // Notify user about completion
        notificationService.createNotification(
                ticket.getUserId(),
                "售后申请已处理完成",
                "您的售后申请 " + ticket.getTicketNo() + " 已处理完成",
                "AFTER_SALE",
                ticket.getId(),
                "TICKET"
        );
        return toTicketView(ticket);
    }

    @Override
    public PageResult<OrderView> listOrders(long page, long size, String status, String keyword) {
        List<OrderView> records = orderInfoMapper.selectList(new LambdaQueryWrapper<OrderInfo>()
                        .eq(OrderInfo::getMerchantCode, currentMerchantCode())
                        .orderByDesc(OrderInfo::getCreateTime))
                .stream()
                .map(this::toOrderView)
                .filter(item -> !StringUtils.hasText(status) || status.equals(item.getStatus()))
                .filter(item -> !StringUtils.hasText(keyword) || containsAny(keyword, item.getOrderNo(), item.getUser(), item.getProduct()))
                .toList();
        return PageResult.of(records, page, size);
    }

    @Override
    public OrderDetail getOrder(Long orderId) {
        OrderInfo order = findOrder(orderId);
        OrderDetail detail = new OrderDetail();
        User user = userMapper.selectById(order.getUserId());
        detail.setOrderId(order.getId());
        detail.setOrderNo(order.getOrderNo());
        detail.setMerchantCode(order.getMerchantCode());
        detail.setUser(userDisplayName(user));
        detail.setPhone(maskPhone(order.getReceiverPhone()));
        detail.setAddress(order.getReceiverAddress());
        detail.setStatus(order.getStatus());
        detail.setPayAmount(money(order.getPayAmount()));
        detail.setPayTime(format(order.getPayTime()));
        detail.setProductItems(orderItems(order.getId()));
        LogisticsInfo logistics = new LogisticsInfo();
        logistics.setCompany(order.getTrackingCompany());
        logistics.setTrackingNo(order.getTrackingNo());
        logistics.setStatus(logisticsStatus(order));
        detail.setLogistics(logistics);
        detail.setRelatedTicketId(findTicketByOrderId(order.getId()).map(AfterSalesTicket::getId).orElse(null));
        return detail;
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public OrderDetail shipOrder(Long orderId) {
        OrderInfo order = findOrder(orderId);
        if (!"PAID".equals(order.getStatus())) {
            throw new BizException("只有未发货订单可以执行发货");
        }
        order.setStatus("SHIPPED");
        order.setShipTime(LocalDateTime.now());
        if (!StringUtils.hasText(order.getTrackingCompany())) {
            order.setTrackingCompany("演示快递");
        }
        if (!StringUtils.hasText(order.getTrackingNo())) {
            order.setTrackingNo("DEMO" + System.currentTimeMillis());
        }
        orderInfoMapper.updateById(order);
        notificationService.createNotification(
                order.getUserId(),
                "订单已发货",
                "您的订单 " + order.getOrderNo() + " 已由商家发货，正在配送中",
                "ORDER",
                order.getId(),
                "ORDER"
        );
        return getOrder(orderId);
    }

    @Override
    public PageResult<NoticeView> listNotices(long page, long size, String readStatus, String level) {
        List<NoticeView> records = messageNoticeMapper.selectList(new LambdaQueryWrapper<MessageNotice>().orderByDesc(MessageNotice::getCreateTime))
                .stream()
                .map(this::toNoticeView)
                .filter(item -> !StringUtils.hasText(readStatus) || readStatus.equals(item.getReadStatus()))
                .filter(item -> !StringUtils.hasText(level) || level.equals(item.getLevel()))
                .toList();
        return PageResult.of(records, page, size);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public NoticeView markNoticeRead(Long noticeId) {
        MessageNotice notice = messageNoticeMapper.selectById(noticeId);
        if (notice == null) {
            throw new BizException(404, "通知不存在");
        }
        notice.setIsRead(1);
        notice.setReadTime(LocalDateTime.now());
        messageNoticeMapper.updateById(notice);
        return toNoticeView(notice);
    }

    @Override
    public PageResult<ReviewView> getReviews(long page, long size, String score, String keyword) {
        String merchantCode = currentMerchantCode();
        List<Long> orderIds = findOrderIdsByMerchant(merchantCode);
        if (orderIds.isEmpty()) {
            return PageResult.of(List.of(), page, size);
        }

        // 1. 从 review_info 表读取（历史遗留数据）
        LambdaQueryWrapper<ReviewInfo> reviewWrapper = new LambdaQueryWrapper<ReviewInfo>()
                .in(ReviewInfo::getOrderId, orderIds)
                .eq(ReviewInfo::getDeleted, 0)
                .orderByDesc(ReviewInfo::getCreateTime);
        List<ReviewInfo> reviewInfos = reviewInfoMapper.selectList(reviewWrapper);
        List<ReviewView> records = new ArrayList<>(reviewInfos.stream()
                .map(this::toReviewViewFromReviewInfo)
                .filter(item -> !StringUtils.hasText(score) || matchesScoreFilter(item, score))
                .filter(item -> !StringUtils.hasText(keyword) || containsAny(keyword,
                        item.getOrderNo(), item.getUser(), item.getProductName(), item.getTicketNo(), item.getContent()))
                .toList());

        // 2. 从 chat_session 读取已评价的会话（用户评价入口的实际数据源）
        LambdaQueryWrapper<ChatSession> sessionWrapper = new LambdaQueryWrapper<ChatSession>()
                .eq(ChatSession::getMerchantCode, merchantCode)
                .isNotNull(ChatSession::getSatisfaction)
                .ne(ChatSession::getSatisfaction, 0)
                .orderByDesc(ChatSession::getUpdateTime);
        List<ChatSession> sessions = chatSessionMapper.selectList(sessionWrapper);
        for (ChatSession session : sessions) {
            // 去重：避免同一会话在 review_info 中也有记录
            boolean exists = records.stream()
                    .anyMatch(r -> r.getOrderId() != null && r.getOrderId().equals(session.getOrderId()));
            if (!exists) {
                ReviewView view = toReviewView(session);
                if ((!StringUtils.hasText(score) || matchesScoreFilter(view, score))
                        && (!StringUtils.hasText(keyword) || containsAny(keyword,
                        view.getOrderNo(), view.getUser(), view.getProductName(), view.getTicketNo(), view.getContent()))) {
                    records.add(view);
                }
            }
        }

        // 3. 按时间倒序排列
        records.sort((a, b) -> {
            if (a.getCreatedAt() == null && b.getCreatedAt() == null) return 0;
            if (a.getCreatedAt() == null) return 1;
            if (b.getCreatedAt() == null) return -1;
            return b.getCreatedAt().compareTo(a.getCreatedAt());
        });

        return PageResult.of(records, page, size);
    }

    private ReviewView toReviewViewFromReviewInfo(ReviewInfo review) {
        OrderInfo order = review.getOrderId() == null ? null : orderInfoMapper.selectById(review.getOrderId());
        User user = review.getUserId() == null ? null : userMapper.selectById(review.getUserId());

        ReviewView view = new ReviewView();
        view.setId(review.getId());
        view.setOrderId(review.getOrderId());
        view.setOverallScore(review.getOverallScore());
        view.setOrderNo(order == null ? null : order.getOrderNo());
        view.setUser(userDisplayName(user));
        view.setContent(review.getContent());
        view.setCreatedAt(format(review.getCreateTime()));
        view.setResponseSpeedScore(review.getServiceScore());
        view.setServiceAttitudeScore(review.getServiceScore());
        view.setProfessionalScore(review.getProductScore());
        view.setEfficiencyScore(review.getLogisticsScore());
        return view;
    }

    private ReviewView toReviewView(ChatSession session) {
        User user = userMapper.selectById(session.getUserId());
        OrderInfo order = session.getOrderId() == null ? null : orderInfoMapper.selectById(session.getOrderId());
        AfterSalesTicket ticket = session.getTicketId() == null ? null : afterSalesTicketMapper.selectById(session.getTicketId());

        ReviewView view = new ReviewView();
        view.setId(session.getId());
        view.setOrderId(session.getOrderId());
        view.setOverallScore(session.getSatisfaction());
        view.setOrderNo(order == null ? null : order.getOrderNo());
        view.setUser(userDisplayName(user));
        view.setProductName(ticket == null ? null : ticket.getProductName());
        view.setTicketNo(ticket == null ? null : ticket.getTicketNo());
        view.setContent(resolveEvaluationContent(session));
        view.setProductImage(resolveProductImage(session));
        view.setCreatedAt(format(session.getCloseTime() != null ? session.getCloseTime() : session.getUpdateTime()));
        view.setResponseSpeedScore(session.getSatisfaction());
        view.setServiceAttitudeScore(session.getSatisfaction());
        view.setProfessionalScore(session.getSatisfaction());
        view.setEfficiencyScore(session.getSatisfaction());
        return view;
    }

    private String resolveProductImage(ChatSession session) {
        if (session.getOrderId() == null) {
            return null;
        }
        try {
            OrderProductItem firstItem = orderItems(session.getOrderId()).stream().findFirst().orElse(null);
            if (firstItem != null && firstItem.getProductId() != null) {
                ProductInfo product = productInfoMapper.selectById(firstItem.getProductId());
                if (product != null && StringUtils.hasText(product.getMainImage())) {
                    return product.getMainImage();
                }
            }
        } catch (Exception ignored) {
            // fallback to null
        }
        return null;
    }

    private String resolveEvaluationContent(ChatSession session) {
        try {
            ChatMessage latestSystemMsg = chatMessageMapper.selectOne(new LambdaQueryWrapper<ChatMessage>()
                    .eq(ChatMessage::getSessionId, session.getId())
                    .eq(ChatMessage::getRole, "SYSTEM")
                    .orderByDesc(ChatMessage::getCreateTime)
                    .last("limit 1"));
            if (latestSystemMsg != null && StringUtils.hasText(latestSystemMsg.getContent())) {
                String content = latestSystemMsg.getContent();
                if (!content.contains("请对本次客服服务进行评价") && !content.contains("已发送服务评价邀请")) {
                    return content;
                }
            }
        } catch (Exception ignored) {
        }
        return null;
    }

    private boolean matchesScoreFilter(ReviewView item, String score) {
        if (item.getOverallScore() == null) {
            return false;
        }
        int value = item.getOverallScore();
        return switch (score) {
            case "GOOD" -> value >= 5;
            case "NORMAL" -> value == 3 || value == 4;
            case "BAD" -> value > 0 && value <= 2;
            default -> true;
        };
    }

    @Override
    public PageResult<ProductView> listProducts(long page, long size, String status, String keyword) {
        List<ProductView> records = productInfoMapper.selectList(new LambdaQueryWrapper<ProductInfo>()
                        .eq(ProductInfo::getMerchantCode, currentMerchantCode())
                        .orderByDesc(ProductInfo::getCreateTime))
                .stream()
                .map(this::toProductView)
                .filter(item -> !StringUtils.hasText(status) || status.equals(item.getStatus()))
                .filter(item -> !StringUtils.hasText(keyword) || containsAny(keyword, item.getProductName(), item.getProductCode(), item.getCategory()))
                .toList();
        return PageResult.of(records, page, size);
    }

    @Override
    public ProductView getProduct(Long productId) {
        return toProductView(findProduct(productId));
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public ProductView createProduct(ProductUpsertRequest request) {
        ProductInfo product = new ProductInfo();
        applyProductRequest(product, request);
        SysUser staff = ensureStaff();
        product.setMerchantId(staff.getId());
        product.setMerchantCode(merchantCodeOf(staff));
        product.setDeleted(0);
        productInfoMapper.insert(product);
        return toProductView(product);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public ProductView updateProduct(Long productId, ProductUpsertRequest request) {
        ProductInfo product = findProduct(productId);
        applyProductRequest(product, request);
        productInfoMapper.updateById(product);
        return toProductView(product);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public ProductView updateProductStatus(Long productId, String status) {
        ProductInfo product = findProduct(productId);
        product.setStatus(toProductStatusValue(status));
        productInfoMapper.updateById(product);
        return toProductView(product);
    }

    private SysUser findStaffByAccountAnyMerchant(String account) {
        return sysUserMapper.selectOne(new LambdaQueryWrapper<SysUser>()
                .eq(SysUser::getUsername, account)
                .eq(SysUser::getRoleType, "AGENT")
                .last("limit 1"));
    }

    private boolean accountExistsAnywhere(String account) {
        return findStaffByAccountAnyMerchant(account) != null;
    }

    private SysUser ensureStaff() {
        Long currentStaffId = currentStaffId();
        if (currentStaffId == null) {
            throw new BizException(401, "未登录，请先登录");
        }
        SysUser staff = sysUserMapper.selectById(currentStaffId);
        if (staff == null) {
            throw new BizException(401, "客服账号不存在或已禁用");
        }
        if (!Integer.valueOf(1).equals(staff.getStatus())) {
            throw new BizException(403, "客服账号已被禁用");
        }
        return staff;
    }

    private SysUser createDemoStaff(String merchantCode) {
        SysUser staff = new SysUser();
        staff.setUsername("cs_demo");
        staff.setPassword(passwordEncoder.encode("123456"));
        staff.setMerchantCode(merchantCode);
        staff.setRealName("林真");
        staff.setPhone("13800000001");
        staff.setEmail("cs_demo@example.com");
        staff.setRoleType("AGENT");
        staff.setStatus(1);
        staff.setOnlineStatus(1);
        staff.setMaxSessions(8);
        staff.setDeleted(0);
        sysUserMapper.insert(staff);
        return staff;
    }

    private StaffProfile toStaffProfile(SysUser staff) {
        StaffProfile profile = new StaffProfile();
        profile.setStaffId(staff.getId());
        profile.setStaffNo("CS" + String.format("%04d", staff.getId()));
        profile.setMerchantCode(merchantCodeOf(staff));
        profile.setAccount(staff.getUsername());
        profile.setRealName(staff.getRealName());
        profile.setPhone(staff.getPhone());
        profile.setRole("AGENT".equals(staff.getRoleType()) ? "CUSTOMER_SERVICE" : staff.getRoleType());
        profile.setOnlineStatus(toOnlineStatusText(staff.getOnlineStatus()));
        profile.setAccountStatus(toAccountStatusText(staff.getStatus()));
        profile.setMaxSessionCount(staff.getMaxSessions());
        return profile;
    }

    private List<ChatSession> allHumanSessionEntities() {
        return chatSessionMapper.selectList(new LambdaQueryWrapper<ChatSession>()
                .eq(ChatSession::getMerchantCode, currentMerchantCode())
                .eq(ChatSession::getMode, "HUMAN")
                .orderByDesc(ChatSession::getUpdateTime));
    }

    private List<SessionView> allSessions() {
        return toSessionViews(allHumanSessionEntities()).stream()
                .sorted(sessionPriorityComparator())
                .toList();
    }

    private Comparator<SessionView> sessionPriorityComparator() {
        return MerchantSessionPriorityPolicy.sessionComparator();
    }

    private SessionView toSessionView(ChatSession session) {
        return toSessionViews(List.of(session)).get(0);
    }

    private List<SessionView> toSessionViews(List<ChatSession> sessions) {
        if (sessions == null || sessions.isEmpty()) {
            return List.of();
        }
        Set<Long> sessionIds = sessions.stream()
                .map(ChatSession::getId)
                .filter(Objects::nonNull)
                .collect(Collectors.toSet());
        Set<Long> userIds = sessions.stream()
                .map(ChatSession::getUserId)
                .filter(Objects::nonNull)
                .collect(Collectors.toSet());
        Set<Long> orderIds = sessions.stream()
                .map(ChatSession::getOrderId)
                .filter(Objects::nonNull)
                .collect(Collectors.toSet());
        Set<Long> ticketIds = sessions.stream()
                .map(ChatSession::getTicketId)
                .filter(Objects::nonNull)
                .collect(Collectors.toSet());

        Map<Long, User> usersById = indexById(
                userIds.isEmpty() ? List.of() : userMapper.selectBatchIds(userIds),
                User::getId);
        Map<Long, OrderInfo> ordersById = indexById(
                orderIds.isEmpty() ? List.of() : orderInfoMapper.selectBatchIds(orderIds),
                OrderInfo::getId);
        Map<Long, AfterSalesTicket> ticketsById = indexById(
                ticketIds.isEmpty() ? List.of() : afterSalesTicketMapper.selectBatchIds(ticketIds),
                AfterSalesTicket::getId);
        Map<Long, ChatMessage> lastMessagesBySession = sessionIds.isEmpty()
                ? Map.of()
                : chatMessageMapper.selectLatestBySessionIds(sessionIds).stream()
                        .collect(Collectors.toMap(
                                ChatMessage::getSessionId,
                                Function.identity(),
                                (left, right) -> left,
                                LinkedHashMap::new));
        Map<Long, List<BigDecimal>> emotionScoresBySession = sessionIds.isEmpty()
                ? Map.of()
                : chatMessageMapper.selectRecentUserEmotionsBySessionIds(sessionIds).stream()
                        .filter(message -> message.getSessionId() != null && message.getEmotionScore() != null)
                        .collect(Collectors.groupingBy(
                                ChatMessage::getSessionId,
                                LinkedHashMap::new,
                                Collectors.mapping(ChatMessage::getEmotionScore, Collectors.toList())));
        LocalDateTime now = LocalDateTime.now();
        return sessions.stream()
                .map(session -> toSessionView(
                        session,
                        valueById(usersById, session.getUserId()),
                        valueById(ordersById, session.getOrderId()),
                        valueById(ticketsById, session.getTicketId()),
                        valueById(lastMessagesBySession, session.getId()),
                        session.getId() == null
                                ? List.of()
                                : emotionScoresBySession.getOrDefault(session.getId(), List.of()),
                        now))
                .toList();
    }

    private static <T> T valueById(Map<Long, T> values, Long id) {
        return id == null || values == null || values.isEmpty() ? null : values.get(id);
    }

    private static <T> Map<Long, T> indexById(List<T> values, Function<T, Long> idExtractor) {
        if (values == null || values.isEmpty()) {
            return Map.of();
        }
        return values.stream()
                .filter(Objects::nonNull)
                .filter(value -> idExtractor.apply(value) != null)
                .collect(Collectors.toMap(
                        idExtractor,
                        Function.identity(),
                        (left, right) -> left,
                        LinkedHashMap::new));
    }

    private SessionView toSessionView(
            ChatSession session,
            User user,
            OrderInfo order,
            AfterSalesTicket ticket,
            ChatMessage lastMessage,
            List<BigDecimal> emotionScores,
            LocalDateTime now) {
        LocalDateTime lastActivityTime = lastMessage == null
                ? Optional.ofNullable(session.getUpdateTime()).orElse(session.getCreateTime())
                : lastMessage.getCreateTime();
        String lastMessageRole = lastMessage == null ? null : lastMessage.getRole();
        String lastMessageSender = lastMessageRole == null ? null : MerchantSessionPriorityPolicy.normalizeSender(lastMessageRole);
        String replyStatus = MerchantSessionPriorityPolicy.replyStatus(lastMessageRole);
        BigDecimal effectiveEmotionScore = Optional.ofNullable(session.getEmotionScore())
                .orElseGet(() -> emotionScores.isEmpty() ? BigDecimal.ZERO : emotionScores.get(emotionScores.size() - 1));
        String emotionTrend = MerchantSessionPriorityPolicy.emotionTrend(emotionScores);
        int priorityScore = MerchantSessionPriorityPolicy.priorityScore(replyStatus, effectiveEmotionScore, lastActivityTime, now);

        SessionView view = new SessionView();
        view.setSessionId(session.getId());
        view.setSessionNo(session.getSessionNo());
        view.setMerchantCode(session.getMerchantCode());
        view.setUserId(session.getUserId());
        view.setOrderId(session.getOrderId());
        view.setTicketId(session.getTicketId());
        view.setServiceId(session.getHumanAgentId());
        view.setUser(userDisplayName(user));
        view.setTopic(Optional.ofNullable(session.getUserQuery()).orElse("在线咨询"));
        view.setLevel(priorityLabel(ticket, session));
        view.setWait(MerchantSessionPriorityPolicy.REPLY_STATUS_UNREPLIED.equals(replyStatus)
                ? waitText(lastActivityTime, now)
                : "已回复");
        view.setEmotion(emotionText(session.getEmotionLabel()));
        view.setEmotionLabel(session.getEmotionLabel());
        view.setEmotionScore(effectiveEmotionScore);
        view.setEmotionConfidence(session.getEmotionConfidence());
        view.setSourceChannel("小程序咨询");
        view.setServiceUnreadCount(MerchantSessionPriorityPolicy.REPLY_STATUS_UNREPLIED.equals(replyStatus) ? 1 : 0);
        view.setOrderNo(order == null ? null : order.getOrderNo());
        view.setProduct(ticket == null ? null : ticket.getProductName());
        view.setProductName(ticket == null ? null : ticket.getProductName());
        view.setTicketNo(ticket == null ? null : ticket.getTicketNo());
        view.setLastMessageContent(lastMessage == null ? null : lastMessage.getContent());
        view.setLastMessageSender(lastMessageSender);
        view.setLastMessageTime(format(lastActivityTime));
        view.setReplyStatus(replyStatus);
        view.setEmotionTrend(emotionTrend);
        view.setRiskLevel(MerchantSessionPriorityPolicy.riskLevel(effectiveEmotionScore));
        view.setPriorityScore(priorityScore);
        view.setAiSummary(session.getUserQuery());
        view.setStatus(toMerchantSessionStatus(session));
        view.setRating(session.getSatisfaction());
        view.setEvaluationRequestedAt("AWAITING_EVALUATION".equals(session.getStatus()) ? format(session.getUpdateTime()) : null);
        view.setEvaluationStatus(evaluationStatus(session));
        view.setEvaluatedAt(session.getSatisfaction() == null ? null : format(session.getCloseTime()));
        return view;
    }

    private boolean isWaitingForStaffReply(ChatSession session, ChatMessage latestUserMessage, ChatMessage latestServiceMessage) {
        if (session == null) {
            return false;
        }
        String status = Optional.ofNullable(session.getStatus()).orElse("");
        if (List.of("CLOSED", "READY_TO_CLOSE", "AWAITING_EVALUATION").contains(status)) {
            return false;
        }
        if (latestUserMessage == null) {
            return false;
        }
        if (latestServiceMessage == null) {
            return true;
        }
        LocalDateTime userTime = latestUserMessage.getCreateTime();
        LocalDateTime serviceTime = latestServiceMessage.getCreateTime();
        if (userTime == null) {
            return false;
        }
        return serviceTime == null || userTime.isAfter(serviceTime);
    }

    private void backfillSessionEmotionIfMissing(ChatSession session) {
        if (session == null || StringUtils.hasText(session.getEmotionLabel())) {
            return;
        }
        List<ChatMessage> messages = chatMessageMapper.selectList(new LambdaQueryWrapper<ChatMessage>()
                .eq(ChatMessage::getSessionId, session.getId())
                .orderByAsc(ChatMessage::getCreateTime)
                .last("limit 12"));
        if (messages.isEmpty()) {
            return;
        }
        chatEmotionAnalysisService.backfillMissingEmotions(session.getId(), messages);
        ChatSession refreshed = chatSessionMapper.selectById(session.getId());
        if (refreshed != null) {
            session.setEmotionLabel(refreshed.getEmotionLabel());
            session.setEmotionScore(refreshed.getEmotionScore());
            session.setEmotionConfidence(refreshed.getEmotionConfidence());
        }
    }

    private Optional<ChatMessage> lastMessage(Long sessionId) {
        return Optional.ofNullable(chatMessageMapper.selectOne(new LambdaQueryWrapper<ChatMessage>()
                .eq(ChatMessage::getSessionId, sessionId)
                .orderByDesc(ChatMessage::getCreateTime)
                .last("limit 1")));
    }

    private Optional<ChatMessage> latestRoleMessage(Long sessionId, String role) {
        return Optional.ofNullable(chatMessageMapper.selectOne(new LambdaQueryWrapper<ChatMessage>()
                .eq(ChatMessage::getSessionId, sessionId)
                .eq(ChatMessage::getRole, role)
                .orderByDesc(ChatMessage::getCreateTime)
                .last("limit 1")));
    }

    private Optional<ChatMessage> latestServiceMessage(Long sessionId) {
        return Optional.ofNullable(chatMessageMapper.selectOne(new LambdaQueryWrapper<ChatMessage>()
                .eq(ChatMessage::getSessionId, sessionId)
                .eq(ChatMessage::getRole, "SERVICE")
                .orderByDesc(ChatMessage::getCreateTime)
                .last("limit 1")));
    }

    private LocalDateTime parseDateTime(String value) {
        if (!StringUtils.hasText(value)) {
            return LocalDateTime.MIN;
        }
        try {
            return LocalDateTime.parse(value, INPUT_DATE_TIME_FORMATTER);
        } catch (RuntimeException ignored) {
            try {
                return LocalDateTime.parse(value.replace(' ', 'T'));
            } catch (RuntimeException ignoredAgain) {
                return LocalDateTime.MIN;
            }
        }
    }

    private String normalizeMessageType(String messageType) {
        String normalized = Optional.ofNullable(messageType).orElse("TEXT").trim().toUpperCase();
        if (List.of("TEXT", "IMAGE", "FILE").contains(normalized)) {
            return normalized;
        }
        return "TEXT";
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
        if ("IMAGE".equals(normalizeMessageType(messageType))) {
            return StringUtils.hasText(content) ? content : "[图片]";
        }
        if ("FILE".equals(normalizeMessageType(messageType))) {
            return StringUtils.hasText(content) ? content : "文件";
        }
        return Optional.ofNullable(content).orElse("");
    }

    private MessageView toMessageView(ChatMessage message) {
        MessageView view = new MessageView();
        view.setMessageId(message.getId());
        view.setSessionId(message.getSessionId());
        String sender = MerchantSessionPriorityPolicy.normalizeSender(message.getRole());
        view.setSender(sender);
        view.setSenderRole(sender);
        view.setMessageType(normalizeMessageType(message.getMessageType()));
        view.setContent(message.getContent());
        view.setFileUrl(StringUtils.hasText(message.getFileUrl()) ? message.getFileUrl().trim() : null);
        view.setAiReplyConfidence(message.getConfidence());
        view.setEmotionLabel(message.getEmotionLabel());
        view.setEmotionScore(message.getEmotionScore());
        view.setEmotionConfidence(message.getEmotionConfidence());
        view.setKnowledgeQuery(message.getKnowledgeQuery());
        view.setKnowledgeRetrievalMode(message.getKnowledgeRetrievalMode());
        view.setKnowledgeHitCount(message.getKnowledgeHitCount());
        view.setKnowledgeHits(parseKnowledgeHits(message.getKnowledgeHitsJson()));
        view.setKnowledgeTrace(parseKnowledgeTrace(message.getKnowledgeTraceJson()));
        view.setCreatedAt(format(message.getCreateTime()));
        return view;
    }

    private List<KnowledgeHitView> parseKnowledgeHits(String knowledgeHitsJson) {
        if (!StringUtils.hasText(knowledgeHitsJson)) {
            return List.of();
        }
        try {
            List<Map<String, Object>> items = objectMapper.readValue(
                    knowledgeHitsJson,
                    new TypeReference<List<Map<String, Object>>>() {}
            );
            return items.stream().map(this::toKnowledgeHitView).toList();
        } catch (Exception ignored) {
            return List.of();
        }
    }

    private KnowledgeHitView toKnowledgeHitView(Map<String, Object> item) {
        KnowledgeHitView view = new KnowledgeHitView();
        view.setSourceType(stringValue(item.get("source_type")));
        view.setSourceCode(stringValue(item.get("source_code")));
        view.setTitle(stringValue(item.get("title")));
        view.setSummary(stringValue(item.get("summary")));
        view.setSnippet(stringValue(item.get("snippet")));
        view.setScore(decimalValue(item.get("score")));
        view.setTags(stringList(item.get("tags")));
        Object metadata = item.get("metadata");
        if (metadata instanceof Map<?, ?> map) {
            java.util.LinkedHashMap<String, Object> normalized = new java.util.LinkedHashMap<>();
            for (Map.Entry<?, ?> entry : map.entrySet()) {
                normalized.put(String.valueOf(entry.getKey()), entry.getValue());
            }
            view.setMetadata(normalized);
        }
        return view;
    }

    private Map<String, Object> parseKnowledgeTrace(String knowledgeTraceJson) {
        if (!StringUtils.hasText(knowledgeTraceJson)) {
            return null;
        }
        try {
            return objectMapper.readValue(knowledgeTraceJson, new TypeReference<Map<String, Object>>() {});
        } catch (Exception ignored) {
            return null;
        }
    }

    private Map<String, String> buildConversationDigest(ChatSession session, ChatMessage latestUserMessage) {
        Map<String, String> digest = new LinkedHashMap<>();
        digest.put("用户诉求", latestUserMessage == null ? Optional.ofNullable(session.getUserQuery()).orElse("待补充") : latestUserMessage.getContent());
        digest.put("会话模式", Optional.ofNullable(session.getMode()).orElse("AI"));
        digest.put("当前状态", Optional.ofNullable(session.getStatus()).orElse("ACTIVE"));
        if (StringUtils.hasText(session.getEmotionLabel())) {
            digest.put("当前情绪", emotionText(session.getEmotionLabel()));
        }
        return digest;
    }

    private List<QuickReplyView> buildQuickReplies(ChatSession session) {
        List<QuickReplyView> replies = new ArrayList<>();
        replies.add(quickReply("progress", "处理进度", "您好，我先帮您核对当前处理进度，有结果后会尽快同步给您。"));
        replies.add(quickReply("evidence", "补充凭证", "为了更快帮您处理，麻烦补充当前最关键的凭证或问题照片。"));
        if ("HUMAN".equalsIgnoreCase(session.getMode())) {
            replies.add(quickReply("handoff", "人工接待", "您好，当前已由人工客服接入，我会继续为您跟进处理。"));
        }
        return replies;
    }

    private QuickReplyView quickReply(String code, String label, String text) {
        QuickReplyView view = new QuickReplyView();
        view.setCode(code);
        view.setLabel(label);
        view.setText(text);
        view.setSceneCode("after_sales");
        view.setIntentCode("general");
        view.setTone("neutral");
        view.setScore(BigDecimal.valueOf(0.8));
        return view;
    }

    private BigDecimal decimalValue(Object value) {
        if (value == null) {
            return null;
        }
        try {
            return new BigDecimal(String.valueOf(value));
        } catch (NumberFormatException exception) {
            return null;
        }
    }

    private String stringValue(Object value) {
        return value == null ? null : String.valueOf(value);
    }

    private List<String> stringList(Object value) {
        if (!(value instanceof List<?> list)) {
            return List.of();
        }
        return list.stream().map(String::valueOf).toList();
    }

    private List<TicketView> allTickets() {
        return afterSalesTicketMapper.selectList(new LambdaQueryWrapper<AfterSalesTicket>()
                        .eq(AfterSalesTicket::getMerchantCode, currentMerchantCode())
                        .orderByDesc(AfterSalesTicket::getPriority)
                        .orderByDesc(AfterSalesTicket::getCreateTime))
                .stream()
                .map(this::toTicketView)
                .toList();
    }

    private TicketView toTicketView(AfterSalesTicket ticket) {
        TicketView view = new TicketView();
        view.setTicketId(ticket.getId());
        view.setTicketNo(ticket.getTicketNo());
        view.setMerchantCode(ticket.getMerchantCode());
        view.setOrderId(ticket.getOrderId());
        view.setOrderNo(ticket.getOrderNo());
        view.setUserId(ticket.getUserId());
        view.setTitle(Optional.ofNullable(ticket.getProductName()).orElse("售后申请"));
        view.setStatus(toMerchantTicketStatus(ticket.getStatus()));
        view.setAfterSalesType(toMerchantAfterSalesType(Optional.ofNullable(ticket.getAfterSaleType()).orElse(ticket.getAiSuggestedAfterSaleType())));
        view.setReasonType(ticket.getReason());
        view.setApplyRefundAmount(money(ticket.getRefundAmount()));
        view.setApprovedRefundAmount("PROCESSING".equals(ticket.getStatus()) || "COMPLETED".equals(ticket.getStatus()) ? money(ticket.getRefundAmount()) : null);
        view.setRefundStatus("COMPLETED".equals(ticket.getStatus()) ? "SUCCESS" : "PENDING");
        view.setAiReviewConfidence(ticket.getAiReviewConfidence());
        view.setPriority(toPriorityText(ticket.getPriority()));
        view.setResponsibility("MERCHANT");
        view.setAssignedServiceId(ticket.getAssigneeId());
        view.setAuditOpinion(ticket.getAuditOpinion());
        view.setRejectReason("REJECTED".equals(ticket.getStatus()) ? ticket.getAuditOpinion() : null);
        view.setExpectedFinishTime(format(ticket.getExpectedCompleteTime()));
        view.setAuditTime(format(ticket.getAuditTime()));
        view.setCompleteTime(format(ticket.getCompleteTime()));
        return view;
    }

    private TicketLogView toTicketLogView(TicketLog log) {
        TicketLogView view = new TicketLogView();
        view.setId(log.getId());
        view.setTicketId(log.getTicketId());
        view.setOperatorId(log.getOperatorId());
        view.setOperatorRole(log.getOperatorType());
        view.setOldStatus(toMerchantTicketStatus(log.getFromStatus()));
        view.setNewStatus(toMerchantTicketStatus(log.getToStatus()));
        view.setActionType(log.getAction());
        view.setActionDesc(log.getContent());
        view.setCreatedAt(format(log.getCreateTime()));
        return view;
    }

    private OrderView toOrderView(OrderInfo order) {
        User user = userMapper.selectById(order.getUserId());
        OrderView view = new OrderView();
        view.setOrderId(order.getId());
        view.setOrderNo(order.getOrderNo());
        view.setMerchantCode(order.getMerchantCode());
        view.setUserId(order.getUserId());
        view.setUser(userDisplayName(user));
        view.setPhone(maskPhone(order.getReceiverPhone()));
        view.setProduct(orderItems(order.getId()).stream().map(OrderProductItem::getProductName).collect(Collectors.joining("、")));
        view.setAmount(money(order.getPayAmount()));
        view.setStatus(order.getStatus());
        view.setLogistics(logisticsStatus(order));
        view.setRelatedTicketId(findTicketByOrderId(order.getId()).map(AfterSalesTicket::getId).orElse(null));
        view.setCreatedAt(format(order.getCreateTime()));
        return view;
    }

    private List<OrderProductItem> orderItems(Long orderId) {
        return orderItemMapper.selectList(new LambdaQueryWrapper<OrderItem>().eq(OrderItem::getOrderId, orderId))
                .stream()
                .map(item -> {
                    ProductInfo product = productInfoMapper.selectById(item.getProductId());
                    OrderProductItem view = new OrderProductItem();
                    view.setProductId(item.getProductId());
                    view.setProductName(product == null ? "未知商品" : product.getProductName());
                    view.setQuantity(item.getQuantity());
                    view.setPrice(money(item.getPrice()));
                    return view;
                })
                .toList();
    }

    private NoticeView toNoticeView(MessageNotice notice) {
        NoticeView view = new NoticeView();
        view.setId(notice.getId());
        view.setLevel(noticeLevel(notice.getNoticeType()));
        view.setTitle(notice.getTitle());
        view.setContent(notice.getContent());
        view.setTarget(noticeTarget(notice));
        view.setReadStatus(Integer.valueOf(1).equals(notice.getIsRead()) ? "READ" : "UNREAD");
        view.setCreatedAt(format(notice.getCreateTime()));
        return view;
    }

    private ProductView toProductView(ProductInfo product) {
        ProductView view = new ProductView();
        view.setId(product.getId());
        view.setMerchantCode(product.getMerchantCode());
        view.setProductName(product.getProductName());
        view.setProductCode(product.getProductCode());
        view.setCategory(product.getCategory());
        view.setDescription(product.getDescription());
        view.setMainImage(product.getMainImage());
        view.setImages(parseImages(product.getImages()));
        view.setPrice(product.getPrice());
        view.setStatus(Integer.valueOf(1).equals(product.getStatus()) ? "ON_SALE" : "OFF_SALE");
        view.setCreatedAt(format(product.getCreateTime()));
        view.setUpdatedAt(format(product.getUpdateTime()));
        return view;
    }

    private void applyProductRequest(ProductInfo product, ProductUpsertRequest request) {
        if (!StringUtils.hasText(request.getProductName())) {
            throw new BizException("商品名称不能为空");
        }
        if (request.getPrice() == null || request.getPrice().compareTo(BigDecimal.ZERO) < 0) {
            throw new BizException("商品价格不能小于 0");
        }
        product.setProductName(request.getProductName());
        product.setProductCode(request.getProductCode());
        product.setCategory(request.getCategory());
        product.setDescription(request.getDescription());
        product.setMainImage(request.getMainImage());
        product.setImages(writeImages(request.getImages()));
        product.setPrice(request.getPrice());
        product.setStatus(toProductStatusValue(request.getStatus()));
    }

    private ChatMessage addSystemMessage(Long sessionId, String content) {
        ChatMessage message = new ChatMessage();
        message.setSessionId(sessionId);
        message.setRole("SYSTEM");
        message.setMessageType("TEXT");
        message.setContent(content);
        chatMessageMapper.insert(message);
        broadcastToSession(sessionId, "SYSTEM", content, "TEXT", null);
        return message;
    }

    private void markRelatedSessionsReadyForEvaluation(AfterSalesTicket ticket) {
        List<ChatSession> sessions = relatedEvaluationSessions(ticket);
        Long staffId = ensureStaff().getId();
        for (ChatSession session : sessions) {
            boolean alreadyInvited = hasEvaluationInviteMessage(session.getId());
            session.setStatus("AWAITING_EVALUATION");
            session.setResolved(0);
            session.setHumanAgentId(staffId);
            if (session.getTicketId() == null) {
                session.setTicketId(ticket.getId());
            }
            if (session.getOrderId() == null) {
                session.setOrderId(ticket.getOrderId());
            }
            session.setUpdateTime(LocalDateTime.now());
            chatSessionMapper.updateById(session);
            if (!alreadyInvited) {
                addSystemMessage(session.getId(), EVALUATION_INVITE_MESSAGE);
                notificationService.createNotification(
                        session.getUserId(),
                        "请评价本次客服服务",
                        "您的售后问题已处理完成，请对本次客服服务进行评价。",
                        "CHAT",
                        session.getId(),
                        "CHAT_SESSION"
                );
            }
        }
    }

    private List<ChatSession> relatedEvaluationSessions(AfterSalesTicket ticket) {
        List<ChatSession> result = new ArrayList<>();
        addUniqueSessions(result, chatSessionMapper.selectList(new LambdaQueryWrapper<ChatSession>()
                .eq(ChatSession::getMerchantCode, ticket.getMerchantCode())
                .eq(ChatSession::getTicketId, ticket.getId())
                .ne(ChatSession::getStatus, "CLOSED")));
        if (ticket.getOrderId() != null) {
            addUniqueSessions(result, chatSessionMapper.selectList(new LambdaQueryWrapper<ChatSession>()
                    .eq(ChatSession::getMerchantCode, ticket.getMerchantCode())
                    .eq(ChatSession::getUserId, ticket.getUserId())
                    .eq(ChatSession::getOrderId, ticket.getOrderId())
                    .ne(ChatSession::getStatus, "CLOSED")));
        }
        return result;
    }

    private void addUniqueSessions(List<ChatSession> target, List<ChatSession> candidates) {
        for (ChatSession candidate : candidates) {
            boolean exists = target.stream().anyMatch(item -> Objects.equals(item.getId(), candidate.getId()));
            if (!exists) {
                target.add(candidate);
            }
        }
    }

    private boolean hasEvaluationInviteMessage(Long sessionId) {
        return chatMessageMapper.selectCount(new LambdaQueryWrapper<ChatMessage>()
                .eq(ChatMessage::getSessionId, sessionId)
                .eq(ChatMessage::getRole, "SYSTEM")
                .like(ChatMessage::getContent, "评价")) > 0;
    }

    private void addTicketLog(AfterSalesTicket ticket, String oldStatus, String newStatus, String action, String content) {
        TicketLog log = new TicketLog();
        log.setTicketId(ticket.getId());
        log.setOperatorId(ensureStaff().getId());
        log.setOperatorType("AGENT");
        log.setFromStatus(oldStatus);
        log.setToStatus(newStatus);
        log.setAction(action);
        log.setContent(content);
        ticketLogMapper.insert(log);
    }

    private ChatSession findSession(Long sessionId) {
        ChatSession session = chatSessionMapper.selectById(sessionId);
        if (session == null) {
            throw new BizException(404, "会话不存在");
        }
        assertCurrentMerchant(session.getMerchantCode(), "会话不存在");
        if (!"HUMAN".equals(session.getMode())) {
            throw new BizException(404, "会话不存在");
        }
        return session;
    }

    private AfterSalesTicket findTicket(Long ticketId) {
        AfterSalesTicket ticket = afterSalesTicketMapper.selectById(ticketId);
        if (ticket == null) {
            throw new BizException(404, "售后申请不存在");
        }
        assertCurrentMerchant(ticket.getMerchantCode(), "售后申请不存在");
        return ticket;
    }

    private OrderInfo findOrder(Long orderId) {
        OrderInfo order = orderInfoMapper.selectById(orderId);
        if (order == null) {
            throw new BizException(404, "订单不存在");
        }
        assertCurrentMerchant(order.getMerchantCode(), "订单不存在");
        return order;
    }

    private ProductInfo findProduct(Long productId) {
        ProductInfo product = productInfoMapper.selectById(productId);
        if (product == null) {
            throw new BizException(404, "商品不存在");
        }
        assertCurrentMerchant(product.getMerchantCode(), "商品不存在");
        return product;
    }

    private Optional<AfterSalesTicket> findTicketByOrderId(Long orderId) {
        return Optional.ofNullable(afterSalesTicketMapper.selectOne(new LambdaQueryWrapper<AfterSalesTicket>()
                .eq(AfterSalesTicket::getOrderId, orderId)
                .eq(AfterSalesTicket::getMerchantCode, currentMerchantCode())
                .orderByDesc(AfterSalesTicket::getCreateTime)
                .last("limit 1")));
    }

    private Long currentStaffId() {
        ServletRequestAttributes attributes = (ServletRequestAttributes) RequestContextHolder.getRequestAttributes();
        if (attributes == null) {
            return null;
        }
        String authorization = attributes.getRequest().getHeader("Authorization");
        if (!StringUtils.hasText(authorization) || !authorization.startsWith("Bearer ")) {
            return null;
        }
        return jwtTokenUtil.parseUserIdOrNull(authorization.substring("Bearer ".length()));
    }

    private String currentMerchantCode() {
        return merchantCodeOf(ensureStaff());
    }

    private String merchantCodeOf(SysUser staff) {
        return normalizeMerchantCode(staff == null ? null : staff.getMerchantCode());
    }

    private String normalizeMerchantCode(String merchantCode) {
        return StringUtils.hasText(merchantCode) ? merchantCode.trim() : DEFAULT_MERCHANT_CODE;
    }

    private String normalizePhone(String phone) {
        if (!StringUtils.hasText(phone)) {
            return "";
        }
        return phone.replaceAll("\\s+", "").trim();
    }

    private String normalizeAuthScene(String scene) {
        return RESET_PASSWORD_SCENE.equalsIgnoreCase(scene) ? RESET_PASSWORD_SCENE : REGISTER_SCENE;
    }

    private void assertCurrentMerchant(String merchantCode, String notFoundMessage) {
        if (!currentMerchantCode().equals(normalizeMerchantCode(merchantCode))) {
            throw new BizException(404, notFoundMessage);
        }
    }

    private String toAccountStatusText(Integer status) {
        return switch (Optional.ofNullable(status).orElse(0)) {
            case STATUS_ACTIVE -> "ENABLED";
            case STATUS_PENDING_APPROVAL -> "PENDING_APPROVAL";
            default -> "DISABLED";
        };
    }

    private List<TimelineItem> buildTimeline() {
        List<TimelineItem> items = new ArrayList<>();
        allTickets().stream().limit(3).forEach(ticket -> {
            TimelineItem item = new TimelineItem();
            item.setTime(Optional.ofNullable(ticket.getAuditTime()).orElse(""));
            item.setTitle("申请 " + ticket.getTicketNo() + " 当前状态：" + ticket.getStatus());
            item.setType("HIGH".equals(ticket.getPriority()) ? "warn" : "normal");
            items.add(item);
        });
        if (items.isEmpty()) {
            TimelineItem item = new TimelineItem();
            item.setTime(LocalDateTime.now().format(DateTimeFormatter.ofPattern("HH:mm")));
            item.setTitle("暂无新的客服任务");
            item.setType("normal");
            items.add(item);
        }
        return items;
    }

    private MetricItem metric(String title, Object value, String trend, String accent) {
        MetricItem metric = new MetricItem();
        metric.setTitle(title);
        metric.setValue(value);
        metric.setTrend(trend);
        metric.setAccent(accent);
        return metric;
    }

    private PerformanceMetric performanceMetric(String label, String value, String desc, Integer current, Integer target,
                                                Integer sampleSize, Boolean lowerIsBetter) {
        PerformanceMetric metric = new PerformanceMetric();
        metric.setLabel(label);
        metric.setValue(value);
        metric.setDesc(desc);
        metric.setCurrentPercent(current);
        metric.setTargetPercent(target);
        metric.setSampleSize(sampleSize);
        metric.setLowerIsBetter(lowerIsBetter);
        return metric;
    }

    /**
     * 平均响应时长：基于 chat_message 中 USER 消息到紧接其后第一条 SERVICE/SYSTEM 回复的时间差。
     */
    private MetricSnapshot buildAvgResponseTimeMetric(List<ChatSession> sessions) {
        List<Long> responseSeconds = new ArrayList<>();
        for (ChatSession session : sessions) {
            responseSeconds.addAll(sessionResponseDurations(session));
        }
        if (responseSeconds.isEmpty()) {
            return new MetricSnapshot("--", 0, 0, true);
        }
        long averageSeconds = Math.round(responseSeconds.stream().mapToLong(Long::longValue).average().orElse(0));
        long targetSeconds = PERFORMANCE_TARGET_RESPONSE_TIME.toSeconds();
        int currentPercent = clampPercent((int) Math.round(targetSeconds * 100D / Math.max(averageSeconds, 1L)));
        return new MetricSnapshot(formatDurationCn(averageSeconds), currentPercent, responseSeconds.size(), true);
    }

    /**
     * 计算单个会话中 USER→SERVICE 的响应时长列表（秒）。
     */
    private List<Long> sessionResponseDurations(ChatSession session) {
        List<ChatMessage> messages = chatMessageMapper.selectList(new LambdaQueryWrapper<ChatMessage>()
                .eq(ChatMessage::getSessionId, session.getId())
                .orderByAsc(ChatMessage::getCreateTime));
        List<Long> durations = new ArrayList<>();
        for (int i = 0; i < messages.size(); i++) {
            ChatMessage current = messages.get(i);
            if (!"USER".equalsIgnoreCase(current.getRole())) {
                continue;
            }
            // 从当前 USER 消息往后找第一条非 USER 消息
            for (int j = i + 1; j < messages.size(); j++) {
                ChatMessage next = messages.get(j);
                if (!"USER".equalsIgnoreCase(next.getRole()) && next.getCreateTime() != null) {
                    long diffSeconds = Duration.between(current.getCreateTime(), next.getCreateTime()).getSeconds();
                    if (diffSeconds >= 0) {
                        durations.add(diffSeconds);
                    }
                    break;
                }
            }
        }
        return durations;
    }

    private MetricSnapshot buildSatisfactionMetric(List<ChatSession> sessions) {
        List<Integer> ratings = sessions.stream()
                .map(ChatSession::getSatisfaction)
                .filter(Objects::nonNull)
                .filter(score -> score > 0)
                .toList();
        if (ratings.isEmpty()) {
            return new MetricSnapshot("--", 0, 0, false);
        }
        double average = ratings.stream().mapToInt(Integer::intValue).average().orElse(0);
        int currentPercent = clampPercent((int) Math.round(average / 5D * 100));
        return new MetricSnapshot(String.format("%.1f / 5", average), currentPercent, ratings.size(), false);
    }

    /**
     * 基于 review_info 的真实评价表计算满意度（近 7 天整体均分）。
     */
    private MetricSnapshot buildReviewSatisfactionMetric() {
        String merchantCode = currentMerchantCode();
        List<Long> orderIds = findOrderIdsByMerchant(merchantCode);
        if (orderIds.isEmpty()) {
            return new MetricSnapshot("--", 0, 0, false);
        }
        LocalDate endDate = LocalDate.now();
        LocalDate startDate = endDate.minusDays(6);

        List<ReviewInfo> reviews = reviewInfoMapper.selectList(
                new LambdaQueryWrapper<ReviewInfo>()
                        .in(ReviewInfo::getOrderId, orderIds)
                        .ge(ReviewInfo::getCreateTime, startDate.atStartOfDay())
                        .le(ReviewInfo::getCreateTime, endDate.atTime(23, 59, 59))
                        .isNotNull(ReviewInfo::getOverallScore)
                        .eq(ReviewInfo::getDeleted, 0)
                        .and(wrapper -> wrapper.isNull(ReviewInfo::getStatus).or().eq(ReviewInfo::getStatus, 1))
        );
        if (reviews.isEmpty()) {
            return new MetricSnapshot("--", 0, 0, false);
        }

        List<Integer> scores = reviews.stream()
                .map(ReviewInfo::getOverallScore)
                .filter(s -> s != null && s > 0)
                .toList();
        if (scores.isEmpty()) {
            return new MetricSnapshot("--", 0, 0, false);
        }

        double average = scores.stream().mapToInt(Integer::intValue).average().orElse(0);
        int currentPercent = clampPercent((int) Math.round(average / 5D * 100));
        return new MetricSnapshot(String.format("%.1f / 5", average), currentPercent, scores.size(), false);
    }

    /**
     * 基于 review_info 的真实评价表计算好评率（近 7 天，overall_score >= 4 记为好评）。
     */
    private MetricSnapshot buildReviewGoodRateMetric() {
        String merchantCode = currentMerchantCode();
        List<Long> orderIds = findOrderIdsByMerchant(merchantCode);
        if (orderIds.isEmpty()) {
            return new MetricSnapshot("--", 0, 0, false);
        }
        LocalDate endDate = LocalDate.now();
        LocalDate startDate = endDate.minusDays(6);

        List<ReviewInfo> reviews = reviewInfoMapper.selectList(
                new LambdaQueryWrapper<ReviewInfo>()
                        .in(ReviewInfo::getOrderId, orderIds)
                        .ge(ReviewInfo::getCreateTime, startDate.atStartOfDay())
                        .le(ReviewInfo::getCreateTime, endDate.atTime(23, 59, 59))
                        .isNotNull(ReviewInfo::getOverallScore)
                        .eq(ReviewInfo::getDeleted, 0)
                        .and(wrapper -> wrapper.isNull(ReviewInfo::getStatus).or().eq(ReviewInfo::getStatus, 1))
        );
        if (reviews.isEmpty()) {
            return new MetricSnapshot("--", 0, 0, false);
        }

        List<Integer> scores = reviews.stream()
                .map(ReviewInfo::getOverallScore)
                .filter(s -> s != null && s > 0)
                .toList();
        if (scores.isEmpty()) {
            return new MetricSnapshot("--", 0, 0, false);
        }

        long positiveCount = scores.stream().filter(s -> s >= 4).count();
        int percent = clampPercent((int) Math.round(positiveCount * 100D / scores.size()));
        return new MetricSnapshot(percent + "%", percent, scores.size(), false);
    }

    /**
     * 查询指定商家在最近 7 天的有效评价列表（用于趋势计算）。
     */
    private List<ReviewInfo> findRecentReviewsByDate(LocalDate targetDate) {
        String merchantCode = currentMerchantCode();
        List<Long> orderIds = findOrderIdsByMerchant(merchantCode);
        if (orderIds.isEmpty()) {
            return List.of();
        }
        return reviewInfoMapper.selectList(
                new LambdaQueryWrapper<ReviewInfo>()
                        .in(ReviewInfo::getOrderId, orderIds)
                        .ge(ReviewInfo::getCreateTime, targetDate.atStartOfDay())
                        .le(ReviewInfo::getCreateTime, targetDate.atTime(23, 59, 59))
                        .isNotNull(ReviewInfo::getOverallScore)
                        .eq(ReviewInfo::getDeleted, 0)
                        .and(wrapper -> wrapper.isNull(ReviewInfo::getStatus).or().eq(ReviewInfo::getStatus, 1))
        );
    }

    /**
     * 查询指定商家的所有 order_id 列表。
     */
    private List<Long> findOrderIdsByMerchant(String merchantCode) {
        return orderInfoMapper.selectList(
                new LambdaQueryWrapper<OrderInfo>()
                        .eq(OrderInfo::getMerchantCode, merchantCode)
                        .select(OrderInfo::getId)
        ).stream()
                .map(OrderInfo::getId)
                .toList();
    }

    private MetricSnapshot buildGoodRateMetric(List<ChatSession> sessions) {
        List<Integer> ratings = sessions.stream()
                .map(ChatSession::getSatisfaction)
                .filter(Objects::nonNull)
                .filter(score -> score > 0)
                .toList();
        if (ratings.isEmpty()) {
            return new MetricSnapshot("--", 0, 0, false);
        }
        long positiveCount = ratings.stream().filter(score -> score >= 4).count();
        int percent = clampPercent((int) Math.round(positiveCount * 100D / ratings.size()));
        return new MetricSnapshot(percent + "%", percent, ratings.size(), false);
    }

    /**
     * 基于 review_info 的近 7 日趋势（按 create_time 分组）。
     * 某天无评价样本时，沿用前一日的综合分做平滑，tooltip 中标注样本数为 0。
     */
    private List<PerformanceTrendPoint> buildReviewBasedTrend(LocalDate startDate, LocalDate endDate) {
        List<PerformanceTrendPoint> trend = new ArrayList<>();
        LocalDate cursor = startDate;
        Integer previousScore = null;

        while (!cursor.isAfter(endDate)) {
            LocalDate currentDate = cursor;
            List<ReviewInfo> dayReviews = findRecentReviewsByDate(currentDate);
            List<ChatSession> daySessions = allHumanSessionEntities().stream()
                    .filter(session -> sessionActivityDate(session).map(currentDate::equals).orElse(false))
                    .toList();
            if (dayReviews.isEmpty()) {
                dayReviews = synthesizeReviewInfos(daySessions);
            }

            MetricSnapshot handleTime = buildAvgResponseTimeMetric(daySessions);
            int dayScore;

            if (dayReviews.isEmpty()) {
                // 无评价样本：平滑到前一日分数
                dayScore = previousScore != null ? previousScore : 0;
            } else {
                MetricSnapshot sat = buildReviewSatisfactionMetricFromReviews(dayReviews);
                MetricSnapshot gr = buildReviewGoodRateMetricFromReviews(dayReviews);
                dayScore = calculateWeightedServiceScore(handleTime, sat, gr);
                previousScore = dayScore;
            }

            PerformanceTrendPoint point = new PerformanceTrendPoint();
            point.setDay(weekdayLabel(cursor));
            point.setScore(dayScore);
            trend.add(point);
            cursor = cursor.plusDays(1);
        }
        return trend;
    }

    /**
     * 从已有的 review 列表计算满意度快照（避免重复查询）。
     */
    private MetricSnapshot buildReviewSatisfactionMetricFromReviews(List<ReviewInfo> reviews) {
        List<Integer> scores = reviews.stream()
                .map(ReviewInfo::getOverallScore)
                .filter(Objects::nonNull)
                .filter(s -> s > 0)
                .toList();
        if (scores.isEmpty()) {
            return new MetricSnapshot("--", 0, 0, false);
        }
        double average = scores.stream().mapToInt(Integer::intValue).average().orElse(0);
        int currentPercent = clampPercent((int) Math.round(average / 5D * 100));
        return new MetricSnapshot(String.format("%.1f / 5", average), currentPercent, scores.size(), false);
    }

    /**
     * 从已有的 review 列表计算好评率快照（避免重复查询）。
     */
    private MetricSnapshot buildReviewGoodRateMetricFromReviews(List<ReviewInfo> reviews) {
        List<Integer> scores = reviews.stream()
                .map(ReviewInfo::getOverallScore)
                .filter(Objects::nonNull)
                .filter(s -> s > 0)
                .toList();
        if (scores.isEmpty()) {
            return new MetricSnapshot("--", 0, 0, false);
        }
        long positiveCount = scores.stream().filter(s -> s >= 4).count();
        int percent = clampPercent((int) Math.round(positiveCount * 100D / scores.size()));
        return new MetricSnapshot(percent + "%", percent, scores.size(), false);
    }

    private MetricSnapshot withFallback(MetricSnapshot primary, MetricSnapshot fallback) {
        return primary != null && primary.hasData() ? primary : fallback;
    }

    private List<ReviewInfo> synthesizeReviewInfos(List<ChatSession> sessions) {
        return sessions.stream()
                .map(ChatSession::getSatisfaction)
                .filter(Objects::nonNull)
                .filter(score -> score > 0)
                .map(score -> {
                    ReviewInfo review = new ReviewInfo();
                    review.setOverallScore(score);
                    return review;
                })
                .toList();
    }

    private void upsertReviewInfoFromSession(ChatSession session, EvaluationRequest request) {
        if (session == null || session.getOrderId() == null || session.getUserId() == null || session.getSatisfaction() == null) {
            return;
        }
        ReviewInfo existing = reviewInfoMapper.selectOne(new LambdaQueryWrapper<ReviewInfo>()
                .eq(ReviewInfo::getOrderId, session.getOrderId())
                .eq(ReviewInfo::getUserId, session.getUserId())
                .orderByDesc(ReviewInfo::getCreateTime)
                .last("limit 1"));
        if (existing != null && Objects.equals(existing.getOverallScore(), session.getSatisfaction())) {
            if (!StringUtils.hasText(existing.getContent()) && StringUtils.hasText(request.getContent())) {
                existing.setContent(request.getContent());
                existing.setStatus(1);
                reviewInfoMapper.updateById(existing);
            }
            return;
        }

        ReviewInfo review = new ReviewInfo();
        review.setOrderId(session.getOrderId());
        review.setUserId(session.getUserId());
        review.setServiceScore(session.getSatisfaction());
        review.setAfterSaleScore(session.getSatisfaction());
        review.setOverallScore(session.getSatisfaction());
        review.setContent(request.getContent());
        review.setStatus(1);
        review.setDeleted(0);
        reviewInfoMapper.insert(review);
    }

    private List<String> buildPerformanceTags(int serviceScore, MetricSnapshot avgResponseTimeMetric,
                                              MetricSnapshot satisfactionMetric, MetricSnapshot goodRateMetric) {
        List<String> tags = new ArrayList<>();
        if (serviceScore >= 90) {
            tags.add("优秀");
        } else if (serviceScore >= 75) {
            tags.add("稳定");
        } else {
            tags.add("需关注");
        }
        if (avgResponseTimeMetric.hasData() && avgResponseTimeMetric.currentPercent() >= 100
                && satisfactionMetric.hasData() && satisfactionMetric.currentPercent() >= 90
                && goodRateMetric.hasData() && goodRateMetric.currentPercent() >= 90) {
            tags.add("达成目标");
        } else {
            tags.add("持续优化");
        }
        return tags;
    }

    private String buildTrendSummary(List<PerformanceTrendPoint> trend) {
        if (trend == null || trend.size() < 2) {
            return "近7日暂无明显波动";
        }
        int lift = Optional.ofNullable(trend.get(trend.size() - 1).getScore()).orElse(0)
                - Optional.ofNullable(trend.get(0).getScore()).orElse(0);
        if (lift > 0) {
            return "本周提升 +" + lift;
        }
        if (lift < 0) {
            return "本周下降 " + lift;
        }
        return "本周持平";
    }

    /**
     * 新口径的综合分：满意度 40% + 好评率 40% + 响应时长 20%
     */
    private int calculateWeightedServiceScore(MetricSnapshot avgResponseTimeMetric, MetricSnapshot satisfactionMetric, MetricSnapshot goodRateMetric) {
        double weightedSum = 0;
        int totalWeight = 0;

        if (satisfactionMetric.hasData()) {
            weightedSum += satisfactionMetric.currentPercent() * 0.4;
            totalWeight += 4;
        }
        if (goodRateMetric.hasData()) {
            weightedSum += goodRateMetric.currentPercent() * 0.4;
            totalWeight += 4;
        }
        if (avgResponseTimeMetric.hasData()) {
            weightedSum += avgResponseTimeMetric.currentPercent() * 0.2;
            totalWeight += 2;
        }

        if (totalWeight == 0) {
            return 0;
        }
        return clampPercent((int) Math.round(weightedSum));
    }

    /**
     * 旧口径（保留以防其他地方引用）：简单平均。
     */
    private int calculateServiceScore(MetricSnapshot avgResponseTimeMetric, MetricSnapshot satisfactionMetric, MetricSnapshot goodRateMetric) {
        List<Integer> scores = new ArrayList<>();
        if (avgResponseTimeMetric.hasData()) {
            scores.add(avgResponseTimeMetric.currentPercent());
        }
        if (satisfactionMetric.hasData()) {
            scores.add(satisfactionMetric.currentPercent());
        }
        if (goodRateMetric.hasData()) {
            scores.add(goodRateMetric.currentPercent());
        }
        if (scores.isEmpty()) {
            return 0;
        }
        return clampPercent((int) Math.round(scores.stream().mapToInt(Integer::intValue).average().orElse(0)));
    }

    private String resolveScoreStatus(int serviceScore) {
        if (serviceScore >= 90) {
            return "今日服务表现优秀";
        }
        if (serviceScore >= 75) {
            return "今日服务表现稳定";
        }
        if (serviceScore > 0) {
            return "今日服务表现待提升";
        }
        return "暂无服务表现数据";
    }

    private Optional<LocalDate> sessionActivityDate(ChatSession session) {
        if (session == null) {
            return Optional.empty();
        }
        return Optional.ofNullable(session.getCloseTime())
                .or(() -> Optional.ofNullable(session.getUpdateTime()))
                .or(() -> Optional.ofNullable(session.getCreateTime()))
                .map(LocalDateTime::toLocalDate);
    }

    private String weekdayLabel(LocalDate date) {
        return switch (date.getDayOfWeek()) {
            case MONDAY -> "周一";
            case TUESDAY -> "周二";
            case WEDNESDAY -> "周三";
            case THURSDAY -> "周四";
            case FRIDAY -> "周五";
            case SATURDAY -> "周六";
            case SUNDAY -> "周日";
        };
    }

    private int clampPercent(int percent) {
        return Math.max(0, Math.min(percent, 100));
    }

    private String formatDurationCn(long totalSeconds) {
        long safeSeconds = Math.max(totalSeconds, 0);
        long minutes = safeSeconds / 60;
        long seconds = safeSeconds % 60;
        if (minutes <= 0) {
            return seconds + "秒";
        }
        return minutes + "分" + seconds + "秒";
    }

    private static final class MetricSnapshot {
        private final String value;
        private final int currentPercent;
        private final int sampleSize;
        private final boolean lowerIsBetter;

        private MetricSnapshot(String value, int currentPercent, int sampleSize, boolean lowerIsBetter) {
            this.value = value;
            this.currentPercent = currentPercent;
            this.sampleSize = sampleSize;
            this.lowerIsBetter = lowerIsBetter;
        }

        private String value() {
            return value;
        }

        private int currentPercent() {
            return currentPercent;
        }

        private int sampleSize() {
            return sampleSize;
        }

        private boolean lowerIsBetter() {
            return lowerIsBetter;
        }

        private boolean hasData() {
            return sampleSize > 0 && StringUtils.hasText(value) && !"--".equals(value);
        }
    }

    private boolean containsAny(String keyword, String... values) {
        return Arrays.stream(values).filter(Objects::nonNull).anyMatch(value -> value.contains(keyword));
    }

    private String format(LocalDateTime value) {
        return value == null
                ? null
                : value.atZone(ZoneId.systemDefault()).format(DateTimeFormatter.ISO_OFFSET_DATE_TIME);
    }

    private String money(BigDecimal value) {
        return value == null ? "0.00" : value.setScale(2).toPlainString();
    }

    private String userDisplayName(User user) {
        if (user == null) {
            return "未知用户";
        }
        return StringUtils.hasText(user.getNickname()) ? user.getNickname() : user.getUserAccount();
    }

    private String maskPhone(String phone) {
        if (!StringUtils.hasText(phone) || phone.length() < 7) {
            return phone;
        }
        return phone.substring(0, 3) + "****" + phone.substring(phone.length() - 4);
    }

    private String waitText(LocalDateTime startTime, LocalDateTime now) {
        if (startTime == null || now == null) {
            return "等待中";
        }
        long minutes = Math.max(Duration.between(startTime, now).toMinutes(), 0);
        return "等待 " + String.format("%02d:%02d", minutes / 60, minutes % 60);
    }

    private String emotionText(String emotionLabel) {
        return switch (Optional.ofNullable(emotionLabel).orElse("NORMAL")) {
            case "SATISFIED" -> "满意";
            case "CALM", "NORMAL", "NEUTRAL" -> "中性";
            case "ANGRY" -> "情绪预警";
            case "ANXIOUS", "ANXIETY" -> "焦急";
            case "DISSATISFIED" -> "不满";
            default -> "中性";
        };
    }
    private String priorityLabel(AfterSalesTicket ticket) {
        if (ticket == null) {
            return "普通优先级";
        }
        return ticket.getPriority() != null && ticket.getPriority() > 0 ? "高优先级" : "普通优先级";
    }

    private String priorityLabel(AfterSalesTicket ticket, ChatSession session) {
        if (ticket != null && ticket.getPriority() != null && ticket.getPriority() > 0) {
            return "高优先级";
        }
        String label = Optional.ofNullable(session.getEmotionLabel()).orElse("").toUpperCase();
        BigDecimal score = session.getEmotionScore();
        if (List.of("DISSATISFIED", "ANGRY").contains(label)
                || (score != null && score.compareTo(new BigDecimal("0.50")) >= 0)) {
            return "高优先级";
        }
        return "普通优先级";
    }

    private String toPriorityText(Integer priority) {
        return priority != null && priority > 0 ? "HIGH" : "NORMAL";
    }

    private String logisticsStatus(OrderInfo order) {
        if (StringUtils.hasText(order.getTrackingNo())) {
            return order.getReceiveTime() == null ? "运输中" : "已签收";
        }
        return "待发货";
    }

    private String toMerchantSessionStatus(ChatSession session) {
        if ("CLOSED".equals(session.getStatus())) {
            return "CLOSED";
        }
        if ("AWAITING_EVALUATION".equals(session.getStatus()) && isEvaluationExpired(session)) {
            return "READY_TO_CLOSE";
        }
        if ("READY_TO_CLOSE".equals(session.getStatus())) {
            return "READY_TO_CLOSE";
        }
        if (Integer.valueOf(1).equals(session.getResolved())) {
            return "READY_TO_CLOSE";
        }
        return switch (Optional.ofNullable(session.getStatus()).orElse("ACTIVE")) {
            case "WAITING" -> "WAITING";
            case "AWAITING_EVALUATION" -> "AWAITING_EVALUATION";
            case "CLOSED" -> "CLOSED";
            default -> "PROCESSING";
        };
    }

    private boolean canCloseSession(ChatSession session) {
        return "READY_TO_CLOSE".equals(session.getStatus())
                || Integer.valueOf(1).equals(session.getResolved())
                || ("AWAITING_EVALUATION".equals(session.getStatus()) && isEvaluationExpired(session));
    }

    private boolean isEvaluationExpired(ChatSession session) {
        return session.getUpdateTime() != null
                && Duration.between(session.getUpdateTime(), LocalDateTime.now()).compareTo(EVALUATION_TIMEOUT) >= 0;
    }

    private String evaluationStatus(ChatSession session) {
        if (session.getSatisfaction() != null) {
            return "SUBMITTED";
        }
        if ("AWAITING_EVALUATION".equals(session.getStatus()) && isEvaluationExpired(session)) {
            return "TIMEOUT";
        }
        if ("AWAITING_EVALUATION".equals(session.getStatus())) {
            return "PENDING";
        }
        return null;
    }

    private String toMerchantTicketStatus(String status) {
        if (status == null) {
            return null;
        }
        return switch (status) {
            case "PENDING" -> "PENDING_REVIEW";
            default -> status;
        };
    }

    private String toMerchantAfterSalesType(String type) {
        if (type == null) {
            return "REFUND_ONLY";
        }
        return switch (type) {
            case "REFUND", "REFUND_ONLY" -> "REFUND_ONLY";
            case "RETURN", "REFUND_RETURN", "RETURN_REFUND", "REPAIR" -> "RETURN_REFUND";
            case "RESEND", "REISSUE", "EXCHANGE" -> "REISSUE";
            case "PARTIAL_REFUND" -> "PARTIAL_REFUND";
            default -> type;
        };
    }

    private Integer toOnlineStatusValue(String status) {
        return switch (Optional.ofNullable(status).orElse("ONLINE")) {
            case "OFFLINE" -> 0;
            case "BUSY" -> 2;
            default -> 1;
        };
    }

    private String toOnlineStatusText(Integer status) {
        return switch (Optional.ofNullable(status).orElse(0)) {
            case 1 -> "ONLINE";
            case 2 -> "BUSY";
            default -> "OFFLINE";
        };
    }

    private Integer toProductStatusValue(String status) {
        return "OFF_SALE".equals(status) ? 0 : 1;
    }

    private String noticeLevel(String noticeType) {
        return "AFTER_SALE".equals(noticeType) || "CHAT".equals(noticeType) ? "HIGH" : "NORMAL";
    }

    private String noticeTarget(MessageNotice notice) {
        if ("TICKET".equals(notice.getRefType())) {
            return "/tickets/" + notice.getRefId();
        }
        if ("ORDER".equals(notice.getRefType())) {
            return "/orders/" + notice.getRefId();
        }
        return "/notices";
    }

    private List<String> parseImages(String images) {
        if (!StringUtils.hasText(images)) {
            return Collections.emptyList();
        }
        try {
            return objectMapper.readValue(images, new TypeReference<>() {
            });
        } catch (Exception exception) {
            return List.of(images);
        }
    }

    private String writeImages(List<String> images) {
        if (images == null || images.isEmpty()) {
            return "[]";
        }
        try {
            return objectMapper.writeValueAsString(images);
        } catch (Exception exception) {
            throw new BizException("商品图片格式错误");
        }
    }
}
