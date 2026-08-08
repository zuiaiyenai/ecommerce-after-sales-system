# 电商售后客服端（Vue3 + Vite）

本目录是合并进当前项目的网页客服端，定位为商家客服工作台。它与 `frontend/uniapp` 用户端分开维护，默认开发和生产构建均使用真实后端 API；mock 仅用于显式 demo/test。

## 启动

```bash
npm.cmd install
npm.cmd run dev
```

默认访问地址：

```text
http://127.0.0.1:5173
```

如果 PowerShell 拦截 `npm.ps1`，请使用 `npm.cmd`。

## 默认账号

```text
账号: cs_demo
密码: 123456
商家编码: MERCHANT_DEMO
```

## 接口模式

默认走真实 API：

```bash
npm.cmd run dev
```

需要使用 mock 数据做纯前端演示时，必须显式执行：

```bash
npm.cmd run dev:mock
```

`src/api/merchantCs.real.js` 和 `src/api/merchantCs.mock.js` 是独立 adapter，`src/api/merchantCs.js` 只提供稳定导出入口。`npm.cmd run build` 固定使用真实 adapter，缺少 `VITE_API_BASE_URL` 时会明确失败；仅 `npm.cmd run build:mock` 会构建 mock 演示版本。

## 当前页面

- 客服登录
- 工作台首页
- 在线会话
- 会话详情与发送消息
- 售后工单列表/详情/审核
- 订单核验
- 消息通知
- 个人中心
