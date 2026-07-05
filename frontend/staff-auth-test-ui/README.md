# 电商售后客服端（Vue3 + Vite）

本目录是合并进当前项目的网页客服端，定位为商家客服工作台。它与 `frontend/uniapp` 用户端分开维护，默认使用本地 mock 数据，可以在后端接口完成后切换到真实接口。

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

默认走 mock 数据，不依赖后端：

```bash
npm.cmd run dev
```

需要尝试真实接口时，启动前设置：

```bash
npm.cmd run dev:real
```

真实接口路径集中在 `src/api/merchantCs.js`，当前约定为 `/api/merchant-cs/*`。

## 当前页面

- 客服登录
- 工作台首页
- 在线会话
- 会话详情与发送消息
- 售后工单列表/详情/审核
- 订单核验
- 消息通知
- 个人中心
