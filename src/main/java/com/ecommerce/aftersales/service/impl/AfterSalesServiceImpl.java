package com.ecommerce.aftersales.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
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
import com.ecommerce.aftersales.service.AfterSalesService;
import com.ecommerce.aftersales.vo.AfterSalesLogVO;
import com.ecommerce.aftersales.vo.AfterSalesVO;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.BeanUtils;
import org.springframework.stereotype.Service;

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

    private static final Long DEFAULT_USER_ID = 1L;

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
    public AfterSalesVO create(AfterSalesVO afterSalesVO) {
        AfterSalesTicket ticket = new AfterSalesTicket();
        // 生成工单号
        ticket.setTicketNo("AS" + System.currentTimeMillis());
        ticket.setOrderId(afterSalesVO.getOrderId());
        ticket.setOrderNo(afterSalesVO.getOrderNo());
        ticket.setUserId(DEFAULT_USER_ID);
        ticket.setProductName(afterSalesVO.getProductName());
        ticket.setAfterSaleType(afterSalesVO.getAfterSaleType());
        ticket.setReason(afterSalesVO.getReason());
        ticket.setReasonDetail(afterSalesVO.getReasonDetail());
        ticket.setDescription(afterSalesVO.getDescription());
        ticket.setStatus("PROCESSING");
        ticket.setPriority(0);
        afterSalesTicketMapper.insert(ticket);
        return convertToVO(ticket);
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
            case "PROCESSING": return "处理中";
            case "APPROVED": return "已通过";
            case "REJECTED": return "已拒绝";
            case "COMPLETED": return "已完成";
            default: return status;
        }
    }
}
