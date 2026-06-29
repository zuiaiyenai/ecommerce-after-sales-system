# 商家客服端接口文档

本文档是当前项目最终采用的商家客服端接口约定。Spring Boot 已配置统一上下文路径 `/api`，因此下面接口均按完整访问路径书写。

## 1. 通用约定

基础地址：

```text
http://127.0.0.1:8080
```

统一响应：

```json
{
  "success": true,
  "code": 200,
  "message": "操作成功",
  "data": {}
}
```

分页数据：

```json
{
  "records": [],
  "total": 0,
  "page": 1,
  "size": 10
}
```

登录后请求头：

```text
Authorization: Bearer <token>
Content-Type: application/json
```

当前后端已实现以下模块：

- 客服登录与工作状态
- 工作台首页
- 在线会话与消息
- 售后工单审核
- 订单核验
- 消息通知
- 商品上传与维护

## 2. 客服登录与信息

### 2.1 客服登录

```http
POST /api/merchant-cs/auth/login
```

请求：

```json
{
  "account": "cs_demo",
  "password": "123456",
  "merchantCode": "MERCHANT_DEMO",
  "clientType": "WEB",
  "deviceId": "browser-device-id"
}
```

响应 `data`：

```json
{
  "token": "jwt-token",
  "staff": {
    "staffId": 1,
    "staffNo": "CS0001",
    "merchantCode": "MERCHANT_DEMO",
    "account": "cs_demo",
    "realName": "林真",
    "phone": "13800000001",
    "role": "CUSTOMER_SERVICE",
    "onlineStatus": "ONLINE",
    "accountStatus": "ENABLED",
    "maxSessionCount": 8
  }
}
```

### 2.2 退出登录

```http
POST /api/merchant-cs/auth/logout
```

### 2.3 当前客服信息

```http
GET /api/merchant-cs/auth/me
```

响应 `data`：`StaffProfile`

### 2.4 修改在线状态

```http
PUT /api/merchant-cs/work-status
```

请求：

```json
{
  "onlineStatus": "BUSY"
}
```

`onlineStatus`：

| 值 | 说明 |
|---|---|
| `ONLINE` | 在线 |
| `BUSY` | 忙碌 |
| `OFFLINE` | 离线 |

## 3. 工作台首页

### 3.1 首页概览

```http
GET /api/merchant-cs/dashboard/overview
```

响应 `data`：

```json
{
  "greeting": "您好，林真",
  "subtitle": "当前还有 3 项任务待处理",
  "todayTodoCount": 3,
  "aiEnabled": true,
  "metrics": [
    {
      "title": "待接入会话",
      "value": 2,
      "trend": "+0",
      "accent": "orange"
    }
  ],
  "timeline": [
    {
      "time": "2026-06-29 10:00:00",
      "title": "工单 AS20240120001 当前状态：PROCESSING",
      "type": "warn"
    }
  ]
}
```

### 3.2 待办列表

```http
GET /api/merchant-cs/dashboard/todos
```

### 3.3 客服绩效

```http
GET /api/merchant-cs/dashboard/performance
```

## 4. 在线会话

### 4.1 会话列表

```http
GET /api/merchant-cs/sessions?page=1&size=10&status=PROCESSING&keyword=退款
```

响应 `data.records[]`：

```json
{
  "id": 101,
  "sessionNo": "CS20260625007",
  "userId": 1,
  "orderId": 1,
  "ticketId": 1,
  "serviceId": 1,
  "user": "yyx",
  "topic": "退款进度咨询",
  "level": "高优先级",
  "wait": "等待 02:13",
  "emotion": "焦虑",
  "sourceChannel": "小程序咨询",
  "serviceUnreadCount": 0,
  "orderNo": "ORD20240115001",
  "productName": "纯棉圆领T恤",
  "ticketNo": "AS20240120001",
  "lastMessageContent": "您好，我已经帮您核对退款进度，目前工单正在处理中。",
  "lastMessageTime": "2026-06-29 10:00:00",
  "aiSummary": "退款进度咨询",
  "status": "PROCESSING",
  "rating": null,
  "evaluationStatus": null
}
```

会话状态：

| 值 | 说明 |
|---|---|
| `WAITING` | 等待接入 |
| `PROCESSING` | 处理中 |
| `RESOLVED` | 已解决 |
| `CLOSED` | 已关闭 |

### 4.2 会话详情

```http
GET /api/merchant-cs/sessions/{sessionId}
```

### 4.3 会话消息

```http
GET /api/merchant-cs/sessions/{sessionId}/messages
```

### 4.4 发送客服消息

```http
POST /api/merchant-cs/sessions/{sessionId}/messages
```

请求：

```json
{
  "messageType": "TEXT",
  "content": "您好，我已经帮您核对退款进度。"
}
```

### 4.5 发起服务评价

```http
POST /api/merchant-cs/sessions/{sessionId}/evaluation-request
```

### 4.6 提交服务评价

```http
POST /api/merchant-cs/sessions/{sessionId}/evaluation
```

请求：

```json
{
  "rating": 5,
  "content": "客服处理很及时"
}
```

### 4.7 关闭会话

```http
POST /api/merchant-cs/sessions/{sessionId}/close
```

## 5. 售后工单

### 5.1 工单列表

```http
GET /api/merchant-cs/tickets?page=1&size=10&status=PENDING_REVIEW&type=REFUND&keyword=退款
```

响应 `data.records[]`：

```json
{
  "id": 1,
  "ticketNo": "AS20240120001",
  "orderId": 1,
  "orderNo": "ORD20240115001",
  "userId": 1,
  "title": "纯棉圆领T恤",
  "status": "PROCESSING",
  "afterSalesType": "RETURN",
  "reasonType": "QUALITY",
  "applyRefundAmount": "0.00",
  "approvedRefundAmount": null,
  "refundStatus": "PENDING",
  "priority": "HIGH",
  "responsibility": "MERCHANT",
  "assignedServiceId": null
}
```

工单状态：

| 值 | 说明 |
|---|---|
| `PENDING_REVIEW` | 待审核 |
| `PROCESSING` | 处理中 |
| `APPROVED` | 已通过 |
| `REJECTED` | 已驳回 |
| `COMPLETED` | 已完成 |
| `CLOSED` | 已关闭 |

售后类型：

| 值 | 说明 |
|---|---|
| `REFUND` | 仅退款 |
| `RETURN` | 退货退款 |
| `EXCHANGE` | 换货 |
| `RESEND` | 补发 |
| `REPAIR` | 维修 |

### 5.2 工单详情

```http
GET /api/merchant-cs/tickets/{ticketId}
```

### 5.3 工单日志

```http
GET /api/merchant-cs/tickets/{ticketId}/logs
```

### 5.4 审核通过

```http
POST /api/merchant-cs/tickets/{ticketId}/approve
```

请求：

```json
{
  "auditOpinion": "符合退款条件，同意退款"
}
```

### 5.5 驳回工单

```http
POST /api/merchant-cs/tickets/{ticketId}/reject
```

请求：

```json
{
  "rejectReason": "凭证不足，请补充商品问题照片"
}
```

## 6. 订单核验

### 6.1 订单列表

```http
GET /api/merchant-cs/orders?page=1&size=10&status=RECEIVED&keyword=ORD20240115001
```

### 6.2 订单详情

```http
GET /api/merchant-cs/orders/{orderId}
```

响应 `data`：

```json
{
  "id": 1,
  "orderNo": "ORD20240115001",
  "user": "yyx",
  "phone": "133****7740",
  "address": "北京市朝阳区三里屯路19号院",
  "status": "RECEIVED",
  "payAmount": "35.00",
  "payTime": "2024-01-15 14:30:00",
  "productItems": [
    {
      "productId": 1,
      "productName": "纯棉圆领T恤",
      "quantity": 1,
      "price": "35.00"
    }
  ],
  "logistics": {
    "company": "顺丰快递",
    "trackingNo": "SF1234567890",
    "status": "已签收"
  },
  "relatedTicketId": 1
}
```

## 7. 消息通知

### 7.1 通知列表

```http
GET /api/merchant-cs/notices?page=1&size=10&readStatus=UNREAD&level=HIGH
```

### 7.2 标记已读

```http
PUT /api/merchant-cs/notices/{noticeId}/read
```

## 8. 商品上传与维护

该模块用于商家在客服端维护商品信息，避免只能通过 MySQL 手工插入固定商品。

### 8.1 商品列表

```http
GET /api/merchant-cs/products?page=1&size=10&status=ON_SALE&keyword=耳机
```

商品状态：

| 值 | 说明 |
|---|---|
| `ON_SALE` | 上架 |
| `OFF_SALE` | 下架 |

### 8.2 商品详情

```http
GET /api/merchant-cs/products/{productId}
```

### 8.3 上传/新增商品

```http
POST /api/merchant-cs/products
```

请求：

```json
{
  "productName": "蓝牙音箱",
  "productCode": "SPEAKER-001",
  "category": "数码",
  "description": "便携蓝牙音箱，支持长续航。",
  "mainImage": "/static/images/product-speaker.png",
  "images": [
    "/static/images/product-speaker.png"
  ],
  "price": 189.00,
  "status": "ON_SALE"
}
```

响应 `data`：

```json
{
  "id": 10,
  "productName": "蓝牙音箱",
  "productCode": "SPEAKER-001",
  "category": "数码",
  "description": "便携蓝牙音箱，支持长续航。",
  "mainImage": "/static/images/product-speaker.png",
  "images": [
    "/static/images/product-speaker.png"
  ],
  "price": 189.00,
  "status": "ON_SALE",
  "createdAt": "2026-06-29 14:00:00",
  "updatedAt": "2026-06-29 14:00:00"
}
```

### 8.4 更新商品

```http
PUT /api/merchant-cs/products/{productId}
```

请求字段同新增商品。

### 8.5 上架/下架商品

```http
PUT /api/merchant-cs/products/{productId}/status
```

请求：

```json
{
  "status": "OFF_SALE"
}
```

## 9. AI 辅助接口规划

以下接口建议保留为后续 AI 模块对接，不作为当前已实现后端范围：

```http
POST /api/merchant-cs/ai/reply-suggestions
GET  /api/merchant-cs/knowledge/search?keyword=退款到账
```

前端可以先用 mock 展示 AI 建议，后续由 AI/RAG 服务接入真实模型与知识库。

## 10. 联调优先级

P0：

- `POST /api/merchant-cs/auth/login`
- `GET /api/merchant-cs/auth/me`
- `GET /api/merchant-cs/dashboard/*`
- `GET /api/merchant-cs/sessions`
- `GET /api/merchant-cs/tickets`
- `GET /api/merchant-cs/orders`
- `POST /api/merchant-cs/products`

P1：

- 会话消息发送、评价、关闭
- 工单审核通过/驳回
- 通知已读
- 商品更新和上下架

P2：

- AI 回复建议
- 知识库搜索
- 商品图片文件上传到对象存储
