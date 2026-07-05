# 客服端合并记录

## 已合入

- 将 `D:/develop/workspace/idea/ideaprojects/E_CommerceAfterSales/staff-auth-test-ui` 合入当前项目 `frontend/staff-auth-test-ui`。
- 保留 Vue3 + Vite 独立工程结构，和当前 `frontend/uniapp` 用户端分开运行。
- 保留客服端 mock 数据模式，默认不依赖后端接口。
- 将对方客服端接口清单合入 `docs/merchant-customer-service-api.md`，用于后续补齐真实接口。
- 更新 `.gitignore`，忽略 `frontend/staff-auth-test-ui/node_modules/` 和 `frontend/staff-auth-test-ui/dist/`。

## 当前项目为准的处理

- 未合入对方 `com.veriify` 后端代码。原因是当前项目后端为 `com.ecommerce.aftersales`、MyBatis-Plus、`application.yml`；对方后端为 `com.veriify`、Spring Data JPA、`application.properties`，直接合并会引入包名、持久层和配置冲突。
- 未覆盖当前 `pom.xml`、`sql/`、`src/main/java/com/ecommerce/aftersales`、`frontend/uniapp`。
- 对方 `database/schema.sql`、JPA 实体和 Repository 仅作为后续接口补齐参考，不作为本次合并内容。

## 待确认冲突点

- 客服端真实接口目前期望 `/api/merchant-cs/*`，当前后端主要提供用户端接口，如 `/miniapp/auth/*`、`/orders`、`/aftersales`。后续如果要关闭 mock，需要在当前后端补 `MerchantCsController` 或调整前端 API 映射。
- 当前统一响应为 `{ code, message, data }`，客服端 API 包装逻辑同时兼容 `success === false`，但真实接口接入时建议统一只按当前项目响应格式处理。
- 对方后端文档中包含客服账号、会话、工单、通知、知识库等接口设计，是否全部落地需要按当前数据库表和 MVP 范围拆分实现。
