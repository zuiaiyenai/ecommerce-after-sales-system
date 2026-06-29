# 客户端与客服端 API 交互文档

> 本文档定义小程序客户端需要调用客服端（Spring Boot 后端）的所有接口。
> 前端本地可完成的功能（页面导航、本地缓存、UI 展示）不在此列。

---

## 目录

1. [通用约定](#1-通用约定)
2. [认证模块](#2-认证模块)
3. [用户信息模块](#3-用户信息模块)
4. [订单模块](#4-订单模块)
5. [售后模块](#5-售后模块)
6. [智能客服模块](#6-智能客服模块)
7. [收货地址模块](#7-收货地址模块)

---

## 1. 通用约定

### 基础信息

| 项目 | 值 |
|------|-----|
| 基础路径 | `http://127.0.0.1:8080/api` |
| 数据格式 | JSON |
| 认证方式 | JWT Token（Header: `Authorization: Bearer <token>`） |

### 统一响应格式

```json
{
  "code": 200,
  "message": "success",
  "data": { ... }
}
```

### 错误码

| code | 含义 |
|------|------|
| 200 | 成功 |
| 400 | 参数错误 |
| 401 | 未登录 / Token 过期 |
| 403 | 无权限 |
| 404 | 资源不存在 |
| 500 | 服务器内部错误 |

---

## 2. 认证模块

> 已实现，客户端已对接。

### 2.1 用户登录

```
POST /miniapp/auth/login
```

**请求：**
```json
{
  "phone": "13800138000",
  "password": "123456"
}
```

**响应：**
```json
{
  "code": 200,
  "data": {
    "token": "eyJhbGciOiJIUzI1NiJ9...",
    "userId": 1,
    "userAccount": "user001",
    "phone": "13800138000",
    "nickname": "张三",
    "avatarUrl": "",
    "bindStatus": 0
  }
}
```

### 2.2 用户注册

```
POST /miniapp/auth/register
```

### 2.3 发送验证码

```
POST /miniapp/auth/code
```

### 2.4 重置密码

```
POST /miniapp/auth/password/reset
```

---

## 3. 用户信息模块

### 3.1 获取用户资料

```
GET /miniapp/user/profile
```

**请求头：**
```
Authorization: Bearer <token>
```

**响应：**
```json
{
  "code": 200,
  "data": {
    "userId": 1,
    "nickname": "张三",
    "phone": "13800138000",
    "avatarUrl": "https://xxx/avatar.jpg",
    "userAccount": "user001",
    "bindStatus": 0
  }
}
```

**客户端调用场景：**
- 进入"我的"页面、"编辑资料"页面时刷新用户信息

### 3.2 更新用户资料

```
PUT /miniapp/user/profile
```

**请求：**
```json
{
  "nickname": "新昵称",
  "avatarUrl": "https://xxx/new-avatar.jpg"
}
```

**响应：**
```json
{
  "code": 200,
  "message": "更新成功"
}
```

**客户端调用场景：**
- "编辑资料"页面点击"保存修改"

### 3.3 上传头像

```
POST /miniapp/user/avatar
Content-Type: multipart/form-data
```

**请求：** `file` (图片文件)

**响应：**
```json
{
  "code": 200,
  "data": {
    "url": "https://xxx/avatar.jpg"
  }
}
```

### 3.4 修改密码

```
PUT /miniapp/user/password
```

**请求：**
```json
{
  "oldPassword": "123456",
  "newPassword": "654321"
}
```

---

## 4. 订单模块

### 4.1 获取订单列表

```
GET /miniapp/orders?status={status}&page={page}&size={size}
```

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| status | string | 否 | `all` / `pending` / `paid` / `shipped` / `received` |
| page | int | 否 | 页码，默认 1 |
| size | int | 否 | 每页条数，默认 10 |

**响应：**
```json
{
  "code": 200,
  "data": {
    "total": 50,
    "list": [
      {
        "id": 1,
        "orderNo": "ORD20240115001",
        "productName": "蓝色T恤",
        "productIcon": "衣",
        "spec": "M码 / 蓝色",
        "price": "35.00",
        "quantity": 1,
        "totalPrice": "35.00",
        "status": "received",
        "statusText": "已完成",
        "createTime": "2024-01-15 14:30:00"
      }
    ]
  }
}
```

**客户端调用场景：**
- "我的订单"页面加载和切换 Tab

### 4.1.1 演示下单

```
POST /orders
```

**请求：**
```json
{
  "productId": 1,
  "quantity": 1,
  "receiverName": "演示用户",
  "receiverPhone": "13800138000",
  "receiverAddress": "演示收货地址",
  "status": "RECEIVED"
}
```

**说明：** 用于演示购买闭环，让用户端不再只能依赖 SQL 手工插入订单。默认生成可申请售后的已收货订单。

### 4.2 获取订单详情

```
GET /miniapp/orders/{orderId}
```

**响应：**
```json
{
  "code": 200,
  "data": {
    "id": 1,
    "orderNo": "ORD20240115001",
    "productName": "蓝色T恤",
    "spec": "M码 / 蓝色",
    "price": "35.00",
    "quantity": 1,
    "totalPrice": "35.00",
    "status": "shipped",
    "statusText": "待收货",
    "trackingNo": "SF1234567890",
    "trackingCompany": "顺丰快递",
    "address": {
      "name": "张三",
      "phone": "13800138000",
      "detail": "北京市朝阳区三里屯路19号"
    },
    "createTime": "2024-01-15 14:30:00",
    "payTime": "2024-01-15 14:35:00",
    "shipTime": "2024-01-16 09:00:00"
  }
}
```

### 4.3 确认收货

```
POST /miniapp/orders/{orderId}/confirm
```

**响应：**
```json
{
  "code": 200,
  "message": "确认收货成功"
}
```

**客户端调用场景：**
- "我的订单"页面点击"确认收货"

### 4.4 获取订单统计

```
GET /miniapp/orders/stats
```

**响应：**
```json
{
  "code": 200,
  "data": {
    "pendingCount": 0,
    "shippedCount": 3,
    "afterSaleCount": 2,
    "unreadMessageCount": 6
  }
}
```

**客户端调用场景：**
- 首页"服务概览"数据展示

---

## 5. 售后模块

### 5.1 申请售后

```
POST /miniapp/after-sale/apply
```

**请求：**
```json
{
  "orderId": 1,
  "reason": "quality",
  "description": "商品有明显破损，包装也有问题",
  "imageUrls": [
    "https://xxx/evidence1.jpg",
    "https://xxx/evidence2.jpg"
  ]
}
```

**reason 取值：**

| 值 | 含义 |
|------|------|
| `quality` | 质量问题 |
| `wrong_item` | 发错货 |
| `size_issue` | 尺码不合适 |
| `damage` | 物流损坏 |
| `not_match` | 与描述不符 |
| `other` | 其他原因 |

**响应：**
```json
{
  "code": 200,
  "data": {
    "afterSaleId": 1,
    "afterSaleNo": "AS20240120001"
  },
  "message": "提交成功"
}
```

**客户端调用场景：**
- "申请售后"页面点击"提交申请"

> **注意：** 售后类型（仅退款/退货退款/换货/维修）由客服端 Agent 根据原因和描述自动评估推荐，客户端不需要传此字段。

### 5.2 获取售后列表

```
GET /miniapp/after-sale?status={status}&page={page}&size={size}
```

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| status | string | 否 | `all` / `processing` / `approved` / `rejected` / `completed` |
| page | int | 否 | 页码，默认 1 |
| size | int | 否 | 每页条数，默认 10 |

**响应：**
```json
{
  "code": 200,
  "data": {
    "total": 10,
    "list": [
      {
        "id": 1,
        "afterSaleNo": "AS20240120001",
        "orderId": 1,
        "productName": "蓝色T恤",
        "productIcon": "衣",
        "reason": "质量问题",
        "aiRecommendType": "退款退货",
        "status": "processing",
        "statusText": "处理中",
        "createTime": "2024-01-20"
      }
    ]
  }
}
```

**客户端调用场景：**
- "我的售后"页面加载和 Tab 切换

### 5.3 获取售后详情

```
GET /miniapp/after-sale/{afterSaleId}
```

**响应：**
```json
{
  "code": 200,
  "data": {
    "id": 1,
    "afterSaleNo": "AS20240120001",
    "orderNo": "ORD20240115001",
    "productName": "蓝色T恤",
    "spec": "M码 / 蓝色",
    "price": "35.00",
    "reason": "质量问题",
    "description": "商品有明显破损",
    "aiRecommendType": "退款退货",
    "status": "processing",
    "statusText": "处理中",
    "imageUrls": ["https://xxx/evidence1.jpg"],
    "timeline": [
      { "time": "2024-01-20 10:00", "title": "提交申请", "desc": "售后申请已提交" },
      { "time": "2024-01-20 10:01", "title": "AI 评估", "desc": "推荐售后类型：退款退货" },
      { "time": "2024-01-20 10:05", "title": "审核中", "desc": "客服正在审核您的申请" }
    ],
    "createTime": "2024-01-20 10:00:00"
  }
}
```

**客户端调用场景：**
- "售后详情"页面加载

### 5.4 上传售后凭证图片

```
POST /miniapp/after-sale/images
Content-Type: multipart/form-data
```

**请求：** `file` (图片文件，最多 5 张)

**响应：**
```json
{
  "code": 200,
  "data": {
    "url": "https://xxx/evidence1.jpg"
  }
}
```

---

## 6. 智能客服模块

### 6.1 创建会话

```
POST /chat/session
```

**请求：**
```json
{
  "afterSaleId": 1
}
```

**响应：**
```json
{
  "code": 200,
  "data": {
    "sessionId": "sess_abc123",
    "mode": "ai",
    "welcomeMessage": "您好，我是智能客服，请问有什么可以帮您？"
  }
}
```

**mode 取值：**

| 值 | 含义 |
|------|------|
| `ai` | AI 智能客服 |
| `human` | 人工客服 |

**客户端调用场景：**
- 进入"智能客服"页面时创建会话

### 6.2 发送消息

```
POST /chat/send
```

**请求：**
```json
{
  "sessionId": "sess_abc123",
  "message": "我的退款到哪了？",
  "messageType": "text"
}
```

**messageType 取值：**

| 值 | 含义 |
|------|------|
| `text` | 文本消息 |
| `image` | 图片消息 |

**响应（AI 模式）：**
```json
{
  "code": 200,
  "data": {
    "reply": "您的退款申请正在审核中，预计1-3个工作日内完成处理。",
    "mode": "ai",
    "toolCalls": [
      {
        "tool": "query_after_sale",
        "args": { "afterSaleId": 1 },
        "result": { "status": "processing" }
      }
    ]
  }
}
```

**响应（人工模式）：**
```json
{
  "code": 200,
  "data": {
    "reply": null,
    "mode": "human",
    "message": "消息已发送，等待人工客服回复"
  }
}
```

**客户端调用场景：**
- 用户在聊天输入框发送消息

### 6.3 流式消息（SSE）

```
GET /miniapp/chat/stream?sessionId={sessionId}&message={message}
Accept: text/event-stream
```

**SSE 事件格式：**
```
data: {"type": "token", "content": "您的"}
data: {"type": "token", "content": "退款"}
data: {"type": "token", "content": "正在审核中"}
data: {"type": "done", "fullReply": "您的退款正在审核中..."}
```

**客户端调用场景：**
- 实现打字机效果的流式输出（可选，优先级较低）

### 6.4 获取历史消息

```
GET /chat/history?sessionId={sessionId}
```

**响应：**
```json
{
  "code": 200,
  "data": {
    "total": 20,
    "list": [
      {
        "id": 1,
        "role": "user",
        "content": "我的退款到哪了？",
        "messageType": "text",
        "createTime": "2024-01-20 10:00:00"
      },
      {
        "id": 2,
        "role": "assistant",
        "content": "您的退款申请正在审核中。",
        "messageType": "text",
        "createTime": "2024-01-20 10:00:01"
      }
    ]
  }
}
```

### 6.5 转人工客服

```
POST /miniapp/chat/transfer
```

**请求：**
```json
{
  "sessionId": "sess_abc123",
  "reason": "用户主动要求转人工"
}
```

**响应：**
```json
{
  "code": 200,
  "data": {
    "status": "waiting",
    "queuePosition": 3,
    "message": "正在为您转接人工客服，当前排队第3位"
  }
}
```

**status 取值：**

| 值 | 含义 |
|------|------|
| `waiting` | 排队等待中 |
| `connected` | 已连接人工客服 |
| `offline` | 人工客服不在线 |

**客户端调用场景：**
- 快捷操作点击"人工帮助"
- 用户发送"转人工"等关键词时自动触发

### 6.6 获取会话状态

```
GET /miniapp/chat/session/{sessionId}/status
```

**响应：**
```json
{
  "code": 200,
  "data": {
    "sessionId": "sess_abc123",
    "mode": "human",
    "humanAgent": {
      "name": "客服小王",
      "avatar": "https://xxx/agent.jpg"
    },
    "online": true
  }
}
```

### 6.7 获取未读消息数

```
GET /miniapp/chat/unread
```

**响应：**
```json
{
  "code": 200,
  "data": {
    "unreadCount": 6
  }
}
```

**客户端调用场景：**
- 首页"服务概览"展示未读消息数

---

## 7. 收货地址模块

### 7.1 获取地址列表

```
GET /miniapp/address
```

**响应：**
```json
{
  "code": 200,
  "data": [
    {
      "id": 1,
      "name": "张三",
      "phone": "13800138000",
      "province": "北京市",
      "city": "北京市",
      "district": "朝阳区",
      "detail": "三里屯路19号院1号楼",
      "isDefault": true
    }
  ]
}
```

### 7.2 新增地址

```
POST /miniapp/address
```

**请求：**
```json
{
  "name": "张三",
  "phone": "13800138000",
  "province": "北京市",
  "city": "北京市",
  "district": "朝阳区",
  "detail": "三里屯路19号院1号楼",
  "isDefault": true
}
```

### 7.3 更新地址

```
PUT /miniapp/address/{addressId}
```

### 7.4 删除地址

```
DELETE /miniapp/address/{addressId}
```

### 7.5 设为默认地址

```
PUT /miniapp/address/{addressId}/default
```

---

## 8. Agent 工具接口（客服端内部调用）

> 以下接口由客服端 Agent 在对话过程中内部调用，客户端**不直接调用**。
> 仅作参考，明确 Agent 的能力边界。

### 8.1 查询订单（Agent Tool）

```
GET /internal/agent/order/{orderNo}
```

### 8.2 查询售后进度（Agent Tool）

```
GET /internal/agent/after-sale/{afterSaleId}
```

### 8.3 查询库存（Agent Tool）

```
GET /internal/agent/stock/{skuId}
```

### 8.4 RAG 知识库检索（Agent Tool）

```
POST /internal/agent/rag/query
{
  "question": "退货政策是什么？"
}
```

### 8.5 创建售后单（Agent Tool）

```
POST /internal/agent/after-sale/create
{
  "orderNo": "ORD20240115001",
  "reason": "quality",
  "aiRecommendType": "refund_return"
}
```

---

## 9. 客户端已实现 vs 待对接

| 模块 | 前端状态 | 需要后端接口 |
|------|----------|-------------|
| 登录/注册 | ✅ 已对接 | `/miniapp/auth/*` |
| 用户资料 | ⚡ 本地暂存 | `GET/PUT /miniapp/user/profile` |
| 订单列表 | ⚡ Mock 数据 | `GET /miniapp/orders` |
| 订单详情 | ⚡ Mock 数据 | `GET /miniapp/orders/{id}` |
| 确认收货 | ⚡ 本地状态 | `POST /miniapp/orders/{id}/confirm` |
| 售后申请 | ⚡ Mock 提交 | `POST /miniapp/after-sale/apply` |
| 售后列表 | ⚡ Mock 数据 | `GET /miniapp/after-sale` |
| 售后详情 | ⚡ Mock 数据 | `GET /miniapp/after-sale/{id}` |
| 智能客服 | ⚡ Mock 回复 | `POST /miniapp/chat/send` |
| 转人工 | ⚡ Mock | `POST /miniapp/chat/transfer` |
| 收货地址 | ⚡ 本地数据 | `GET/POST/PUT/DELETE /miniapp/address` |
| 修改密码 | 🔲 占位 | `PUT /miniapp/user/password` |
| 意见反馈 | 🔲 占位 | `POST /miniapp/feedback` |

**图例：**
- ✅ 已对接后端
- ⚡ 前端已有 UI 和交互，使用 Mock 数据，等待后端接口就绪后替换
- 🔲 仅占位，未实现 UI
