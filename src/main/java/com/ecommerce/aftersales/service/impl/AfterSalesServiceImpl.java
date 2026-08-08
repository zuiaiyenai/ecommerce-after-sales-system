package com.ecommerce.aftersales.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ecommerce.aftersales.common.BizException;
import com.ecommerce.aftersales.entity.AfterSalesTicket;
import com.ecommerce.aftersales.entity.OrderInfo;
import com.ecommerce.aftersales.entity.OrderItem;
import com.ecommerce.aftersales.entity.ProductInfo;
import com.ecommerce.aftersales.entity.TicketAttachment;
import com.ecommerce.aftersales.entity.TicketLog;
import com.ecommerce.aftersales.mapper.AfterSalesTicketMapper;
import com.ecommerce.aftersales.mapper.OrderInfoMapper;
import com.ecommerce.aftersales.mapper.OrderItemMapper;
import com.ecommerce.aftersales.mapper.ProductInfoMapper;
import com.ecommerce.aftersales.mapper.TicketAttachmentMapper;
import com.ecommerce.aftersales.mapper.TicketLogMapper;
import com.ecommerce.aftersales.request.CreateAfterSalesRequest;
import com.ecommerce.aftersales.response.AfterSalesLogResponse;
import com.ecommerce.aftersales.response.AfterSalesResponse;
import com.ecommerce.aftersales.service.AfterSalesService;
import com.ecommerce.aftersales.service.AfterSalesReviewEventService;
import com.ecommerce.aftersales.service.AiReviewStatusCacheService;
import com.ecommerce.aftersales.service.KnowledgeMetadataPolicy;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.BeanUtils;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.util.List;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
public class AfterSalesServiceImpl implements AfterSalesService {

    private static final String DEFAULT_MERCHANT_CODE = "MERCHANT_DEMO";

    private final AfterSalesTicketMapper afterSalesTicketMapper;
    private final TicketAttachmentMapper ticketAttachmentMapper;
    private final TicketLogMapper ticketLogMapper;
    private final OrderInfoMapper orderInfoMapper;
    private final OrderItemMapper orderItemMapper;
    private final ProductInfoMapper productInfoMapper;
    private final AfterSalesReviewEventService afterSalesReviewEventService;
    private final AiReviewStatusCacheService aiReviewStatusCacheService;
    private final KnowledgeMetadataPolicy knowledgeMetadataPolicy;

    @Override
    public List<AfterSalesResponse> listByUserId(Long userId) {
        LambdaQueryWrapper<AfterSalesTicket> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(AfterSalesTicket::getUserId, userId)
                .orderByDesc(AfterSalesTicket::getCreateTime);
        return afterSalesTicketMapper.selectList(wrapper).stream()
                .map(this::convertToResponse)
                .collect(Collectors.toList());
    }

    @Override
    public AfterSalesResponse getById(Long id, Long userId) {
        LambdaQueryWrapper<AfterSalesTicket> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(AfterSalesTicket::getId, id)
                .eq(AfterSalesTicket::getUserId, userId);
        AfterSalesTicket ticket = afterSalesTicketMapper.selectOne(wrapper);
        return ticket == null ? null : convertToResponse(ticket);
    }

    @Override
    public AfterSalesResponse getByTicketNo(String ticketNo) {
        LambdaQueryWrapper<AfterSalesTicket> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(AfterSalesTicket::getTicketNo, ticketNo);
        AfterSalesTicket ticket = afterSalesTicketMapper.selectOne(wrapper);
        return ticket == null ? null : convertToResponse(ticket);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public AfterSalesResponse create(Long userId, CreateAfterSalesRequest request) {
        OrderInfo order = orderInfoMapper.selectById(request.getOrderId());
        if (order == null) {
            throw new BizException(404, "订单不存在");
        }

        AfterSalesTicket existingTicket = findOpenTicket(userId, order.getId());
        if (existingTicket != null) {
            return convertToResponse(existingTicket);
        }

        AfterSalesTicket ticket = new AfterSalesTicket();
        ticket.setTicketNo("AS" + System.currentTimeMillis());
        ticket.setOrderId(order.getId());
        ticket.setOrderNo(order.getOrderNo());
        ticket.setUserId(userId);
        ticket.setMerchantId(order.getMerchantId());
        ticket.setMerchantCode(order.getMerchantCode());
        KnowledgeMetadataPolicy.PolicySnapshot policySnapshot =
                knowledgeMetadataPolicy.resolvePolicySnapshot(order.getMerchantCode());
        ticket.setPolicyCode(policySnapshot.policyCode());
        ticket.setPolicyVersion(policySnapshot.policyVersion());
        ticket.setProductName(resolveOrderProductName(order.getId()));
        ticket.setAfterSaleType(request.getAfterSaleType());
        ticket.setReason(request.getReason());
        ticket.setReasonDetail(request.getReasonDetail());
        ticket.setDescription(request.getDescription());
        ticket.setRefundAmount(resolveRefundAmount(request, order));
        ticket.setStatus("PENDING_REVIEW");
        ticket.setPriority(0);
        ticket.setAuditOpinion("售后申请已提交，AI正在进行初步审核。");

        try {
            afterSalesTicketMapper.insert(ticket);
        } catch (DuplicateKeyException duplicateKeyException) {
            AfterSalesTicket reusableTicket = findOpenTicket(userId, order.getId());
            if (reusableTicket != null) {
                return convertToResponse(reusableTicket);
            }
            throw duplicateKeyException;
        }

        TicketLog log = new TicketLog();
        log.setTicketId(ticket.getId());
        log.setOperatorId(userId);
        log.setOperatorType("USER");
        log.setAction("CREATE");
        log.setFromStatus(null);
        log.setToStatus("PENDING_REVIEW");
        log.setContent("用户提交售后申请，进入待审核，AI初审事件已入队。");
        ticketLogMapper.insert(log);

        if (request.getAttachmentUrls() != null && !request.getAttachmentUrls().isEmpty()) {
            int sortOrder = 0;
            for (String url : request.getAttachmentUrls()) {
                TicketAttachment attachment = new TicketAttachment();
                attachment.setTicketId(ticket.getId());
                attachment.setFileUrl(url);
                attachment.setFileType("IMAGE");
                attachment.setFileName(extractFilename(url));
                attachment.setFileSize(0L);
                attachment.setSortOrder(sortOrder++);
                ticketAttachmentMapper.insert(attachment);
            }
        }

        afterSalesReviewEventService.enqueueReviewRequested(ticket, null);
        runAfterCommit(() -> aiReviewStatusCacheService.cacheStatus(ticket.getId(), "AI_REVIEWING"));
        return convertToResponse(ticket);
    }

    private AfterSalesTicket findOpenTicket(Long userId, Long orderId) {
        LambdaQueryWrapper<AfterSalesTicket> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(AfterSalesTicket::getUserId, userId)
                .eq(AfterSalesTicket::getOrderId, orderId)
                .in(AfterSalesTicket::getStatus, "PENDING", "PENDING_REVIEW", "PROCESSING")
                .orderByDesc(AfterSalesTicket::getUpdateTime)
                .last("limit 1");
        return afterSalesTicketMapper.selectOne(wrapper);
    }

    private BigDecimal resolveRefundAmount(CreateAfterSalesRequest request, OrderInfo order) {
        BigDecimal orderAmount = firstPositive(order.getPayAmount(), order.getTotalAmount(), BigDecimal.ZERO);
        BigDecimal refundAmount = request.getRefundAmount();
        if (refundAmount == null || refundAmount.compareTo(BigDecimal.ZERO) <= 0) {
            return orderAmount;
        }
        if (orderAmount.compareTo(BigDecimal.ZERO) > 0 && refundAmount.compareTo(orderAmount) > 0) {
            return orderAmount;
        }
        return refundAmount;
    }

    private BigDecimal firstPositive(BigDecimal... values) {
        for (BigDecimal value : values) {
            if (value != null && value.compareTo(BigDecimal.ZERO) > 0) {
                return value;
            }
        }
        return BigDecimal.ZERO;
    }

    private String extractFilename(String url) {
        if (url == null || !url.contains("/")) {
            return url;
        }
        return url.substring(url.lastIndexOf('/') + 1);
    }

    private String resolveOrderProductName(Long orderId) {
        if (orderId == null) {
            return "";
        }
        LambdaQueryWrapper<OrderItem> itemWrapper = new LambdaQueryWrapper<>();
        itemWrapper.eq(OrderItem::getOrderId, orderId).last("limit 1");
        OrderItem item = orderItemMapper.selectOne(itemWrapper);
        if (item == null) {
            return "";
        }
        ProductInfo product = productInfoMapper.selectById(item.getProductId());
        return product == null ? "" : product.getProductName();
    }

    private AfterSalesResponse convertToResponse(AfterSalesTicket ticket) {
        AfterSalesResponse response = new AfterSalesResponse();
        BeanUtils.copyProperties(ticket, response);
        response.setTicketId(ticket.getId());
        response.setMerchantDisplayName(resolveMerchantDisplayName(ticket.getMerchantCode()));
        response.setStatusText(getStatusText(ticket.getStatus()));
        response.setAiReviewResult(ticket.getAiReviewResult());
        response.setAiReviewStatus(aiReviewStatusCacheService.resolveStatus(ticket));
        response.setManualReviewRequired(ticket.getManualReviewRequired() != null && ticket.getManualReviewRequired() == 1);

        if (ticket.getOrderId() != null) {
            OrderInfo orderInfo = orderInfoMapper.selectById(ticket.getOrderId());
            if (orderInfo != null) {
                response.setOrderNo(orderInfo.getOrderNo());
                LambdaQueryWrapper<OrderItem> itemWrapper = new LambdaQueryWrapper<>();
                itemWrapper.eq(OrderItem::getOrderId, orderInfo.getId());
                List<OrderItem> items = orderItemMapper.selectList(itemWrapper);
                if (!items.isEmpty()) {
                    ProductInfo product = productInfoMapper.selectById(items.get(0).getProductId());
                    if (product != null) {
                        response.setProductName(product.getProductName());
                        response.setProductImage(product.getMainImage());
                    }
                }
            }
        }

        LambdaQueryWrapper<TicketAttachment> attachmentWrapper = new LambdaQueryWrapper<>();
        attachmentWrapper.eq(TicketAttachment::getTicketId, ticket.getId())
                .orderByAsc(TicketAttachment::getSortOrder);
        List<String> attachmentUrls = ticketAttachmentMapper.selectList(attachmentWrapper).stream()
                .map(TicketAttachment::getFileUrl)
                .collect(Collectors.toList());
        response.setAttachmentUrls(attachmentUrls);

        LambdaQueryWrapper<TicketLog> logWrapper = new LambdaQueryWrapper<>();
        logWrapper.eq(TicketLog::getTicketId, ticket.getId())
                .orderByAsc(TicketLog::getCreateTime);
        List<AfterSalesLogResponse> logResponses = ticketLogMapper.selectList(logWrapper).stream()
                .map(log -> {
                    AfterSalesLogResponse logResponse = new AfterSalesLogResponse();
                    BeanUtils.copyProperties(log, logResponse);
                    return logResponse;
                })
                .collect(Collectors.toList());
        response.setLogs(logResponses);

        return response;
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

    private String resolveMerchantDisplayName(String merchantCode) {
        String code = StringUtils.hasText(merchantCode) ? merchantCode.trim() : DEFAULT_MERCHANT_CODE;
        if (DEFAULT_MERCHANT_CODE.equalsIgnoreCase(code)) {
            return "演示商家";
        }
        return "商家 " + code;
    }

    private String getStatusText(String status) {
        if (status == null) {
            return "";
        }
        return switch (status) {
            case "PENDING", "PENDING_REVIEW" -> "待审核";
            case "PROCESSING" -> "处理中";
            case "REJECTED" -> "已驳回";
            case "COMPLETED" -> "已完成";
            case "CLOSED" -> "已关闭";
            default -> status;
        };
    }
}
