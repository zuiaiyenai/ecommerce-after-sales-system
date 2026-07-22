package com.ecommerce.aftersales.service.impl;

import com.ecommerce.aftersales.entity.AfterSalesTicket;
import com.ecommerce.aftersales.entity.OrderInfo;
import com.ecommerce.aftersales.mapper.AfterSalesTicketMapper;
import com.ecommerce.aftersales.mapper.OrderInfoMapper;
import com.ecommerce.aftersales.mapper.OrderItemMapper;
import com.ecommerce.aftersales.mapper.ProductInfoMapper;
import com.ecommerce.aftersales.mapper.TicketAttachmentMapper;
import com.ecommerce.aftersales.mapper.TicketLogMapper;
import com.ecommerce.aftersales.request.CreateAfterSalesRequest;
import com.ecommerce.aftersales.service.AfterSalesReviewEventService;
import com.ecommerce.aftersales.service.AiReviewStatusCacheService;
import com.ecommerce.aftersales.service.KnowledgeMetadataPolicy;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class AfterSalesServicePolicySnapshotTest {

    @Test
    void createSnapshotsJavaOwnedMerchantPolicyVersionOnTicket() {
        AfterSalesTicketMapper ticketMapper = mock(AfterSalesTicketMapper.class);
        TicketAttachmentMapper attachmentMapper = mock(TicketAttachmentMapper.class);
        TicketLogMapper logMapper = mock(TicketLogMapper.class);
        OrderInfoMapper orderMapper = mock(OrderInfoMapper.class);
        OrderItemMapper itemMapper = mock(OrderItemMapper.class);
        ProductInfoMapper productMapper = mock(ProductInfoMapper.class);
        AfterSalesReviewEventService eventService = mock(AfterSalesReviewEventService.class);
        AiReviewStatusCacheService statusCache = mock(AiReviewStatusCacheService.class);
        KnowledgeMetadataPolicy metadataPolicy = mock(KnowledgeMetadataPolicy.class);
        AfterSalesServiceImpl service = new AfterSalesServiceImpl(
                ticketMapper,
                attachmentMapper,
                logMapper,
                orderMapper,
                itemMapper,
                productMapper,
                eventService,
                statusCache,
                metadataPolicy
        );
        OrderInfo order = new OrderInfo();
        order.setId(1001L);
        order.setOrderNo("ORDER-1001");
        order.setUserId(2001L);
        order.setMerchantId(3001L);
        order.setMerchantCode("MERCHANT_DEMO");
        order.setPayAmount(new BigDecimal("99.00"));
        when(orderMapper.selectById(1001L)).thenReturn(order);
        when(ticketMapper.selectOne(any())).thenReturn(null);
        when(itemMapper.selectOne(any())).thenReturn(null);
        when(itemMapper.selectList(any())).thenReturn(List.of());
        when(attachmentMapper.selectList(any())).thenReturn(List.of());
        when(metadataPolicy.resolvePolicySnapshot("MERCHANT_DEMO"))
                .thenReturn(new KnowledgeMetadataPolicy.PolicySnapshot(
                        "DEFAULT_POLICY",
                        "2026-07-02-v3"
                ));
        doAnswer(invocation -> {
            AfterSalesTicket ticket = invocation.getArgument(0);
            ticket.setId(4001L);
            ticket.setCreateTime(LocalDateTime.of(2026, 7, 20, 9, 0));
            return 1;
        }).when(ticketMapper).insert(any(AfterSalesTicket.class));

        CreateAfterSalesRequest request = new CreateAfterSalesRequest();
        request.setOrderId(1001L);
        request.setAfterSaleType("RETURN_REFUND");
        request.setReason("QUALITY");
        request.setDescription("功能异常");
        request.setAttachmentUrls(List.of());

        service.create(2001L, request);

        ArgumentCaptor<AfterSalesTicket> ticketCaptor = ArgumentCaptor.forClass(AfterSalesTicket.class);
        verify(ticketMapper).insert(ticketCaptor.capture());
        assertThat(ticketCaptor.getValue().getPolicyCode()).isEqualTo("DEFAULT_POLICY");
        assertThat(ticketCaptor.getValue().getPolicyVersion()).isEqualTo("2026-07-02-v3");
    }
}
