# Ecommerce After-Sales System

电商售后客服与用户评价分析系统，包含 Spring Boot 后端、uni-app 用户端小程序和 Vue 3 商家客服端。

## 项目结构

```text
.
├─ src/                         # Spring Boot 后端
├─ sql/                         # MySQL / pgvector 建表与种子数据
├─ docs/                        # 接口与联调文档
├─ frontend/
│  ├─ uniapp/                   # 用户端小程序
│  └─ staff-auth-test-ui/       # 商家客服端
└─ image/                       # 商品图片素材
```

## 技术栈

- Java 17、Spring Boot 3.3、MyBatis-Plus
- MySQL、JWT
- Vue 3、Vite、uni-app

## 后端启动

1. 创建 MySQL 数据库并依次执行：

   ```text
   sql/schema.sql
   sql/seed_data.sql
   ```

2. 按需设置本地环境变量：

   ```powershell
   $env:DB_USERNAME = "root"
   $env:DB_PASSWORD = "你的数据库密码"
   $env:JWT_SECRET = "至少 32 字节的 JWT 密钥"
   ```

3. 启动服务：

   ```powershell
   mvn spring-boot:run
   ```

后端默认地址：`http://127.0.0.1:8080/api`。

## 用户端小程序

```powershell
cd frontend/uniapp
npm install
npm run build:mp-weixin
```

使用微信开发者工具导入 `frontend/uniapp/dist/build/mp-weixin`。

## 商家客服端

```powershell
cd frontend/staff-auth-test-ui
npm install
npm run dev:real
```

默认访问地址：`http://127.0.0.1:5173`。

默认演示账号：

```text
账号: cs_demo
密码: 123456
商家编码: MERCHANT_DEMO
```

## 核心联调链路

```text
商家端登录 -> sys_user.merchant_code
商家端上传商品 -> product_info.merchant_code
用户端购买商品 -> order_info / order_item 继承 merchant_code
用户端申请售后 -> after_sales_ticket 继承 merchant_code
用户端发起咨询 -> chat_session / chat_message 绑定订单与商家
商家端查询会话、工单、订单和商品 -> 按当前 merchant_code 隔离数据
```

## 文档入口

- [用户端 API 交互文档](docs/API-INTERACTION.md)
- [商家客服端接口文档](docs/merchant-customer-service-api.md)
- [用户端认证接口文档](docs/miniapp-user-auth-api.md)
- [客服端合并记录](docs/merge-customer-service-ui.md)
- [高德物流 API 集成说明](docs/amap-logistics-api-integration.md)

## 常用验证

```powershell
mvn -DskipTests compile

cd frontend/uniapp
npm run build:mp-weixin

cd ../staff-auth-test-ui
npm run build
```
