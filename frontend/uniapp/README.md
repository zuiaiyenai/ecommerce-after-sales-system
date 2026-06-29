# 电商售后小程序端（Vue3 + UniApp）

本目录是用户端小程序工程。当前采用 UniApp Vite 的 `src` 源码结构，避免重复配置：

```text
frontend/uniapp
├── package.json
└── src
    ├── App.vue
    ├── main.js
    ├── manifest.json
    ├── pages.json
    ├── pages
    ├── static
    │   └── images
    └── utils
```

维护规则：

- 页面注册只改 `src/pages.json`。
- 应用入口只改 `src/App.vue`、`src/main.js`、`src/manifest.json`。
- 页面源码放在 `src/pages`。
- 工具函数放在 `src/utils`。
- 图片资源放在 `src/static/images`，页面里使用 `/static/images/...`。

## 后端地址

接口地址配置在：

```text
src/utils/request.js
```

默认值：

```js
const BASE_URL = 'http://127.0.0.1:8080/api'
```

本地调试前，确保 Spring Boot 后端已启动，并且看到：

```text
Tomcat started on port 8080 with context path '/api'
```

## HBuilderX 运行方式

1. 用 HBuilderX 打开 `frontend/uniapp` 目录。
2. 点击 `运行 -> 运行到小程序模拟器 -> 微信开发者工具`。
3. 如果请求本地后端失败，在微信开发者工具里勾选：

```text
详情 -> 本地设置 -> 不校验合法域名、web-view、TLS版本以及HTTPS证书
```

## 命令行运行方式

首次安装依赖：

```bash
npm.cmd install
```

编译微信小程序：

```bash
npm.cmd run dev:mp-weixin
```

然后用微信开发者工具打开：

```text
frontend/uniapp/dist/build/mp-weixin
```

## 当前已实现功能

- 用户登录/注册/验证码/找回密码
- 用户中心与订单列表
- 演示购买商品并生成订单
- 售后申请、售后列表、售后详情
- 用户咨询，消息写入后端会话表，客服端可查看
