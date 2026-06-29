# ecommerce-after-sales-system

电商售后客服与用户评价分析系统，包含 Spring Boot 后端、UniApp 用户端小程序、Vue3 商家客服端网页。

## 项目结构

```text
.
├── src                         # Spring Boot 后端
├── sql                         # MySQL / pgvector 建表与种子数据
├── docs                        # 接口与合并说明文档
├── frontend
│   ├── uniapp                  # 用户端小程序
│   └── staff-auth-test-ui      # 商家客服端网页
└── image                       # 原始商品图片素材
```

## 后端

技术栈：

- Java 17
- Spring Boot 3.3
- MyBatis-Plus
- MySQL
- JWT

启动前先执行：

```sql
sql/schema.sql
sql/seed_data.sql
```

本地环境变量可选：

```bash
DB_USERNAME=root
DB_PASSWORD=你的数据库密码
JWT_SECRET=至少32字节的JWT密钥
```

启动：

```bash
mvn.cmd spring-boot:run
```

默认地址：

```text
http://127.0.0.1:8080/api
```

## 用户端小程序

位置：

```text
frontend/uniapp
```

安装依赖：

```bash
cd frontend/uniapp
npm.cmd install
```

编译微信小程序：

```bash
npm.cmd run build:mp-weixin
```

微信开发者工具导入：

```text
frontend/uniapp/dist/build/mp-weixin
```

已支持：

- 登录/注册/找回密码
- 商品演示购买并生成订单
- 订单列表
- 售后申请、售后列表、售后详情
- 用户咨询，消息写入后端会话表

## 商家客服端

位置：

```text
frontend/staff-auth-test-ui
```

安装依赖：

```bash
cd frontend/staff-auth-test-ui
npm.cmd install
```

默认 mock 模式：

```bash
npm.cmd run dev
```

真实接口联调模式：

```bash
npm.cmd run dev:real
```

访问：

```text
http://127.0.0.1:5173
```

默认客服账号：

```text
账号: cs_demo
密码: 123456
商家编码: MERCHANT_DEMO
```

## 联调链路

当前已打通的核心链路：

```text
商家端上传商品 -> product_info
用户端演示购买 -> order_info / order_item
用户端申请售后 -> after_sales_ticket
商家端售后工单 -> 读取 after_sales_ticket
用户端开启/发送对话 -> chat_session / chat_message
商家端在线会话 -> 读取 chat_session / chat_message
```

说明：当前客服端消息接收是接口刷新式联调，不是 WebSocket 实时推送。

## 主要文档

- [用户端 API 交互文档](docs/API-INTERACTION.md)
- [商家客服端接口文档](docs/merchant-customer-service-api.md)
- [用户端认证接口文档](docs/miniapp-user-auth-api.md)
- [客服端合并记录](docs/merge-customer-service-ui.md)

## 验证命令

```bash
mvn.cmd -q -DskipTests compile
cd frontend/uniapp && npm.cmd run build:mp-weixin
cd frontend/staff-auth-test-ui && npm.cmd run build
```
