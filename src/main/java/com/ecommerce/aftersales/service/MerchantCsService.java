package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.common.PageResult;
import com.ecommerce.aftersales.dto.MerchantCsDtos.*;

import java.util.List;

public interface MerchantCsService {

    LoginResponse login(LoginRequest request);

    void logout();

    StaffProfile getCurrentStaff();

    StaffProfile updateWorkStatus(String onlineStatus);

    DashboardOverview getDashboardOverview();

    List<TodoItem> getDashboardTodos();

    DashboardPerformance getDashboardPerformance();

    PageResult<SessionView> listSessions(long page, long size, String status, String keyword);

    SessionView getSession(Long sessionId);

    List<MessageView> listSessionMessages(Long sessionId);

    MessageView sendSessionMessage(Long sessionId, SendMessageRequest request);

    SessionView requestSessionEvaluation(Long sessionId);

    SessionView submitSessionEvaluation(Long sessionId, EvaluationRequest request);

    SessionView closeSession(Long sessionId);

    PageResult<TicketView> listTickets(long page, long size, String status, String type, String keyword);

    TicketView getTicket(Long ticketId);

    List<TicketLogView> listTicketLogs(Long ticketId);

    TicketView approveTicket(Long ticketId, String auditOpinion);

    TicketView rejectTicket(Long ticketId, String rejectReason);

    TicketView completeTicket(Long ticketId, String completeNote);

    PageResult<OrderView> listOrders(long page, long size, String status, String keyword);

    OrderDetail getOrder(Long orderId);

    OrderDetail shipOrder(Long orderId);

    PageResult<NoticeView> listNotices(long page, long size, String readStatus, String level);

    NoticeView markNoticeRead(Long noticeId);

    PageResult<ProductView> listProducts(long page, long size, String status, String keyword);

    ProductView getProduct(Long productId);

    ProductView createProduct(ProductUpsertRequest request);

    ProductView updateProduct(Long productId, ProductUpsertRequest request);

    ProductView updateProductStatus(Long productId, String status);
}
