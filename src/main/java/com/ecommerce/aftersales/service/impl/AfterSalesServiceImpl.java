package com.ecommerce.aftersales.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ecommerce.aftersales.entity.AfterSalesTicket;
import com.ecommerce.aftersales.entity.OrderInfo;
import com.ecommerce.aftersales.entity.OrderItem;
import com.ecommerce.aftersales.entity.ProductInfo;
import com.ecommerce.aftersales.entity.TicketAttachment;
import com.ecommerce.aftersales.entity.TicketLog;
import com.ecommerce.aftersales.mapper.AfterSalesTicketMapper;
import com.ecommerce.aftersales.common.BizException;
import com.ecommerce.aftersales.mapper.OrderInfoMapper;
import com.ecommerce.aftersales.mapper.OrderItemMapper;
import com.ecommerce.aftersales.mapper.ProductInfoMapper;
import com.ecommerce.aftersales.mapper.TicketAttachmentMapper;
import com.ecommerce.aftersales.mapper.TicketLogMapper;
import com.ecommerce.aftersales.service.AfterSalesService;
import com.ecommerce.aftersales.util.BusinessNoGenerator;
import com.ecommerce.aftersales.vo.AfterSalesLogVO;
import com.ecommerce.aftersales.vo.AfterSalesVO;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.BeanUtils;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
public class AfterSalesServiceImpl implements AfterSalesService {

    private final AfterSalesTicketMapper afterSalesTicketMapper;
    private final TicketAttachmentMapper ticketAttachmentMapper;
    private final TicketLogMapper ticketLogMapper;
    private final OrderInfoMapper orderInfoMapper;
    private final OrderItemMapper orderItemMapper;
    private final ProductInfoMapper productInfoMapper;

    @Override
    public List<AfterSalesVO> listByUserId(Long userId) {
        LambdaQueryWrapper<AfterSalesTicket> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(AfterSalesTicket::getUserId, userId)
               .orderByDesc(AfterSalesTicket::getCreateTime);
        List<AfterSalesTicket> tickets = afterSalesTicketMapper.selectList(wrapper);
        return tickets.stream()
                .map(this::convertToVO)
                .collect(Collectors.toList());
    }

    @Override
    public AfterSalesVO getById(Long id, Long userId) {
        LambdaQueryWrapper<AfterSalesTicket> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(AfterSalesTicket::getId, id)
               .eq(AfterSalesTicket::getUserId, userId);
        AfterSalesTicket ticket = afterSalesTicketMapper.selectOne(wrapper);
        if (ticket == null) {
            return null;
        }
        return convertToVO(ticket);
    }

    @Override
    public AfterSalesVO getByTicketNo(String ticketNo) {
        LambdaQueryWrapper<AfterSalesTicket> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(AfterSalesTicket::getTicketNo, ticketNo);
        AfterSalesTicket ticket = afterSalesTicketMapper.selectOne(wrapper);
        if (ticket == null) {
            return null;
        }
        return convertToVO(ticket);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public AfterSalesVO create(Long userId, AfterSalesVO afterSalesVO) {
        OrderInfo order = orderInfoMapper.selectById(afterSalesVO.getOrderId());
        if (order == null) {
            throw new BizException(404, "订单不存在");
        }
        if (!userId.equals(order.getUserId())) {
            throw new BizException(404, "订单不存在");
        }
        if (!"RECEIVED".equals(order.getStatus()) && !"SHIPPED".equals(order.getStatus())) {
            throw new BizException("当前订单状态不可申请售后");
        }
        if (hasExistingAfterSale(order.getId())) {
            throw new BizException("该订单已申请售后，请进入售后咨询继续处理");
        }
        AfterSalesTicket ticket = new AfterSalesTicket();
        // 生成工单号
        ticket.setTicketNo(nextTicketNo());
        ticket.setOrderId(order.getId());
        ticket.setOrderNo(order.getOrderNo());
        ticket.setUserId(userId);
        ticket.setMerchantId(order.getMerchantId());
        ticket.setMerchantCode(order.getMerchantCode());
        ticket.setProductName(afterSalesVO.getProductName());
        ticket.setAfterSaleType(afterSalesVO.getAfterSaleType());
        ticket.setReason(afterSalesVO.getReason());
        ticket.setReasonDetail(afterSalesVO.getReasonDetail());
        ticket.setDescription(afterSalesVO.getDescription());
        ticket.setRefundAmount(resolveRefundAmount(afterSalesVO, order));
        ticket.setStatus("PENDING");
        ticket.setPriority(0);
        afterSalesTicketMapper.insert(ticket);
        order.setStatus("AFTERSALE");
        order.setUpdateTime(LocalDateTime.now());
        orderInfoMapper.updateById(order);

        // Save attachments
        if (afterSalesVO.getAttachmentUrls() != null && !afterSalesVO.getAttachmentUrls().isEmpty()) {
            int sortOrder = 0;
            for (String url : afterSalesVO.getAttachmentUrls()) {
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

        return convertToVO(ticket);
    }

    private boolean hasExistingAfterSale(Long orderId) {
        Long count = afterSalesTicketMapper.selectCount(new LambdaQueryWrapper<AfterSalesTicket>()
                .eq(AfterSalesTicket::getOrderId, orderId)
                .in(AfterSalesTicket::getStatus, List.of("PENDING", "PENDING_REVIEW", "PROCESSING", "COMPLETED")));
        return count != null && count > 0;
    }

    private BigDecimal resolveRefundAmount(AfterSalesVO afterSalesVO, OrderInfo order) {
        BigDecimal orderAmount = firstPositive(order.getPayAmount(), order.getTotalAmount(), BigDecimal.ZERO);
        BigDecimal refundAmount = afterSalesVO.getRefundAmount();
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
        return url.substring(url.lastIndexOf("/") + 1);
    }

    private AfterSalesVO convertToVO(AfterSalesTicket ticket) {
        AfterSalesVO vo = new AfterSalesVO();
        BeanUtils.copyProperties(ticket, vo);
        vo.setStatusText(getStatusText(ticket.getStatus()));

        // 通过订单关联查询商品图片
        if (ticket.getOrderId() != null) {
            OrderInfo orderInfo = orderInfoMapper.selectById(ticket.getOrderId());
            if (orderInfo != null) {
                vo.setOrderNo(orderInfo.getOrderNo());
                LambdaQueryWrapper<OrderItem> itemWrapper = new LambdaQueryWrapper<>();
                itemWrapper.eq(OrderItem::getOrderId, orderInfo.getId());
                List<OrderItem> items = orderItemMapper.selectList(itemWrapper);
                if (!items.isEmpty()) {
                    ProductInfo product = productInfoMapper.selectById(items.get(0).getProductId());
                    if (product != null) {
                        vo.setProductName(product.getProductName());
                        vo.setProductImage(product.getMainImage());
                    }
                }
            }
        }

        // 查询附件
        LambdaQueryWrapper<TicketAttachment> attachmentWrapper = new LambdaQueryWrapper<>();
        attachmentWrapper.eq(TicketAttachment::getTicketId, ticket.getId())
                        .orderByAsc(TicketAttachment::getSortOrder);
        List<TicketAttachment> attachments = ticketAttachmentMapper.selectList(attachmentWrapper);
        List<String> attachmentUrls = attachments.stream()
                .map(TicketAttachment::getFileUrl)
                .collect(Collectors.toList());
        vo.setAttachmentUrls(attachmentUrls);

        // 查询日志
        LambdaQueryWrapper<TicketLog> logWrapper = new LambdaQueryWrapper<>();
        logWrapper.eq(TicketLog::getTicketId, ticket.getId())
                 .orderByAsc(TicketLog::getCreateTime);
        List<TicketLog> logs = ticketLogMapper.selectList(logWrapper);
        List<AfterSalesLogVO> logVOs = logs.stream()
                .map(log -> {
                    AfterSalesLogVO logVO = new AfterSalesLogVO();
                    BeanUtils.copyProperties(log, logVO);
                    return logVO;
                })
                .collect(Collectors.toList());
        vo.setLogs(logVOs);

        return vo;
    }

    private String getStatusText(String status) {
        if (status == null) return "";
        switch (status) {
            case "PENDING": return "待审核";
            case "PROCESSING": return "处理中";
            case "REJECTED": return "已驳回";
            case "COMPLETED": return "已完成";
            default: return status;
        }
    }
}
