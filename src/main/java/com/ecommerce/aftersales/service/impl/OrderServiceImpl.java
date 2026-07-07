package com.ecommerce.aftersales.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ecommerce.aftersales.common.BizException;
import com.ecommerce.aftersales.dto.CreateOrderRequest;
import com.ecommerce.aftersales.entity.AfterSalesTicket;
import com.ecommerce.aftersales.entity.OrderInfo;
import com.ecommerce.aftersales.entity.OrderItem;
import com.ecommerce.aftersales.entity.ProductInfo;
import com.ecommerce.aftersales.mapper.AfterSalesTicketMapper;
import com.ecommerce.aftersales.mapper.OrderInfoMapper;
import com.ecommerce.aftersales.mapper.OrderItemMapper;
import com.ecommerce.aftersales.mapper.ProductInfoMapper;
import com.ecommerce.aftersales.service.OrderService;
import com.ecommerce.aftersales.vo.OrderItemVO;
import com.ecommerce.aftersales.vo.OrderVO;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.BeanUtils;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
public class OrderServiceImpl implements OrderService {

    private final AfterSalesTicketMapper afterSalesTicketMapper;
    private final OrderInfoMapper orderInfoMapper;
    private final OrderItemMapper orderItemMapper;
    private final ProductInfoMapper productInfoMapper;

    @Override
    public List<OrderVO> listByUserId(Long userId) {
        LambdaQueryWrapper<OrderInfo> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(OrderInfo::getUserId, userId)
               .orderByDesc(OrderInfo::getCreateTime);
        List<OrderInfo> orders = orderInfoMapper.selectList(wrapper);
        return orders.stream()
                .map(this::convertToVO)
                .collect(Collectors.toList());
    }

    @Override
    public OrderVO getById(Long id, Long userId) {
        LambdaQueryWrapper<OrderInfo> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(OrderInfo::getId, id)
               .eq(OrderInfo::getUserId, userId);
        OrderInfo orderInfo = orderInfoMapper.selectOne(wrapper);
        if (orderInfo == null) {
            return null;
        }
        return convertToVO(orderInfo);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public OrderVO create(Long userId, CreateOrderRequest request) {
        if (request.getProductId() == null) {
            throw new BizException("商品ID不能为空");
        }
        int quantity = request.getQuantity() == null || request.getQuantity() <= 0 ? 1 : request.getQuantity();
        ProductInfo product = productInfoMapper.selectById(request.getProductId());
        if (product == null || !Integer.valueOf(1).equals(product.getStatus())) {
            throw new BizException(404, "商品不存在或已下架");
        }

        OrderInfo order = new OrderInfo();
        order.setOrderNo("ORD" + System.currentTimeMillis());
        order.setUserId(userId);
        order.setMerchantId(product.getMerchantId());
        order.setMerchantCode(product.getMerchantCode());
        order.setTotalAmount(product.getPrice().multiply(java.math.BigDecimal.valueOf(quantity)));
        order.setPayAmount(order.getTotalAmount());
        order.setStatus("PAID");
        order.setReceiverName(request.getReceiverName() == null ? "演示用户" : request.getReceiverName());
        order.setReceiverPhone(request.getReceiverPhone() == null ? "13800138000" : request.getReceiverPhone());
        order.setReceiverAddress(request.getReceiverAddress() == null ? "演示收货地址" : request.getReceiverAddress());
        order.setPayTime(LocalDateTime.now());
        orderInfoMapper.insert(order);

        OrderItem item = new OrderItem();
        item.setOrderId(order.getId());
        item.setProductId(product.getId());
        item.setPrice(product.getPrice());
        item.setQuantity(quantity);
        item.setSubtotal(order.getTotalAmount());
        orderItemMapper.insert(item);
        return convertToVO(order);
    }

    @Override
    public void updateStatus(Long id, Long userId, String status) {
        if (!"RECEIVED".equals(status)) {
            throw new BizException(403, "用户端不能执行该订单状态操作");
        }
        OrderInfo orderInfo = orderInfoMapper.selectOne(new LambdaQueryWrapper<OrderInfo>()
                .eq(OrderInfo::getId, id)
                .eq(OrderInfo::getUserId, userId)
                .last("limit 1"));
        if (orderInfo == null) {
            throw new BizException(404, "订单不存在");
        }
        if ("RECEIVED".equals(status) && !"SHIPPED".equals(orderInfo.getStatus())) {
            throw new BizException("只有配送中的订单可以确认收货");
        }
        orderInfo.setStatus(status);
        if ("RECEIVED".equals(status)) {
            if (orderInfo.getShipTime() == null) {
                orderInfo.setShipTime(LocalDateTime.now().minusHours(2));
            }
            if (orderInfo.getTrackingCompany() == null) {
                orderInfo.setTrackingCompany("演示快递");
            }
            if (orderInfo.getTrackingNo() == null) {
                orderInfo.setTrackingNo("DEMO" + System.currentTimeMillis());
            }
            orderInfo.setReceiveTime(LocalDateTime.now());
        }
        orderInfoMapper.updateById(orderInfo);
    }

    private OrderVO convertToVO(OrderInfo orderInfo) {
        OrderVO vo = new OrderVO();
        BeanUtils.copyProperties(orderInfo, vo);
        vo.setStatusText(getStatusText(orderInfo.getStatus()));
        applyAfterSalesSnapshot(vo, orderInfo);

        // 查询订单项
        LambdaQueryWrapper<OrderItem> itemWrapper = new LambdaQueryWrapper<>();
        itemWrapper.eq(OrderItem::getOrderId, orderInfo.getId());
        List<OrderItem> items = orderItemMapper.selectList(itemWrapper);

        // 批量查询商品信息
        List<Long> productIds = items.stream()
                .map(OrderItem::getProductId)
                .collect(Collectors.toList());
        Map<Long, ProductInfo> finalProductMap = new java.util.HashMap<>();
        if (!productIds.isEmpty()) {
            List<ProductInfo> products = productInfoMapper.selectBatchIds(productIds);
            finalProductMap.putAll(products.stream()
                    .collect(Collectors.toMap(ProductInfo::getId, p -> p)));
        }
        Map<Long, ProductInfo> productMap = finalProductMap;

        // 转换订单项
        List<OrderItemVO> itemVOs = items.stream()
                .map(item -> {
                    OrderItemVO itemVO = new OrderItemVO();
                    BeanUtils.copyProperties(item, itemVO);
                    ProductInfo product = productMap.get(item.getProductId());
                    if (product != null) {
                        itemVO.setProductName(product.getProductName());
                        itemVO.setProductImage(product.getMainImage());
                        itemVO.setProductSpec(product.getDescription());
                    }
                    return itemVO;
                })
                .collect(Collectors.toList());
        vo.setItems(itemVOs);

        return vo;
    }

    private void applyAfterSalesSnapshot(OrderVO vo, OrderInfo orderInfo) {
        AfterSalesTicket ticket = afterSalesTicketMapper.selectOne(new LambdaQueryWrapper<AfterSalesTicket>()
                .eq(AfterSalesTicket::getOrderId, orderInfo.getId())
                .orderByDesc(AfterSalesTicket::getCreateTime)
                .last("limit 1"));
        if (ticket == null) {
            vo.setHasOpenAfterSales(false);
            vo.setHasAnyAfterSales(false);
            vo.setAfterSalesStatus(null);
            vo.setAfterSalesStatusText(null);
            vo.setLatestAfterSalesTicketNo(null);
            return;
        }

        boolean hasOpenAfterSales = !isClosedAfterSalesStatus(ticket.getStatus());
        vo.setHasOpenAfterSales(hasOpenAfterSales);
        vo.setHasAnyAfterSales(true);
        vo.setAfterSalesStatus(ticket.getStatus());
        vo.setAfterSalesStatusText(getAfterSalesStatusText(ticket.getStatus()));
        vo.setLatestAfterSalesTicketNo(ticket.getTicketNo());
        if (hasOpenAfterSales) {
            vo.setStatus("AFTERSALE");
            vo.setStatusText("售后中");
            return;
        }
        if ("COMPLETED".equals(ticket.getStatus())) {
            vo.setStatus("AWAITING_EVALUATION");
            vo.setStatusText("待评价");
        }
    }

    private boolean isClosedAfterSalesStatus(String status) {
        return "REJECTED".equals(status) || "COMPLETED".equals(status) || "CLOSED".equals(status);
    }

    private String getAfterSalesStatusText(String status) {
        if (status == null) return "";
        if ("CLOSED".equals(status)) return "已关闭";
        switch (status) {
            case "PENDING": return "待审核";
            case "PROCESSING": return "处理中";
            case "REJECTED": return "已驳回";
            case "COMPLETED": return "已完成";
            default: return status;
        }
    }

    private String getStatusText(String status) {
        if (status == null) return "";
        switch (status) {
            case "PAID": return "未发货";
            case "SHIPPED": return "配送中";
            case "RECEIVED": return "已收货";
            case "AFTERSALE": return "售后中";
            case "AWAITING_EVALUATION": return "待评价";
            case "CLOSED": return "已关闭";
            default: return status;
        }
    }
}
