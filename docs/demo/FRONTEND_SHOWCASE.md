# 微信小程序前端展示总览

> 开发基线：`b784af9a49037e0683c9af5762d042c4f4a259a4`
> 运行方式：微信开发者工具真实模拟器、`touristappid`、本地真实 Java/Python/数据库服务
> 正式路由：16 个；截图：31 张；最终自动化 Console 错误：0；页面异常：0

## 页面树

```text
App
├── 账号认证 pages/auth/auth
│   ├── 登录
│   ├── 注册（验证码）
│   └── 找回/修改密码（验证码）
├── 首页 pages/home/home
│   ├── 服务概览与最近订单
│   ├── 演示购买入口
│   ├── 全部订单入口
│   ├── 咨询入口
│   └── 我的入口
├── 商品 pages/shop/shop
│   └── 商品列表 → 一键购买 → 订单列表
├── 订单与售后
│   ├── 订单列表 pages/orders/list
│   │   ├── 状态筛选
│   │   ├── 确认收货
│   │   ├── 申请售后
│   │   └── 联系客服
│   ├── 订单/售后详情 pages/after-sale/detail
│   │   ├── 商品与订单信息
│   │   ├── 物流地图与轨迹
│   │   ├── 售后进度与问题信息
│   │   └── 进入客服咨询
│   ├── 售后申请 pages/after-sale/apply
│   │   ├── 原因选择
│   │   ├── 问题描述
│   │   ├── 凭证图片入口
│   │   └── 提交后进入客服
│   └── 我的售后 pages/after-sale/list
│       └── 状态筛选 → 售后详情/客服
├── 客服
│   ├── 会话列表 pages/chat/list
│   │   ├── 历史会话
│   │   └── 新咨询
│   ├── 智能客服 pages/chat/consult
│   │   ├── 历史消息
│   │   ├── AI/人工状态
│   │   ├── 图片与补充凭证
│   │   └── 结束会话/评价
│   └── 售后评价 pages/chat/evaluate
│       ├── 多维评分
│       └── 补充评价
└── 我的 pages/mine/mine
    ├── 编辑资料 pages/mine/profile
    ├── 收货地址 pages/mine/address
    ├── 账号设置 pages/mine/settings
    │   ├── 编辑资料
    │   ├── 修改密码 → pages/auth/auth?mode=reset
    │   ├── 缓存与通知
    │   ├── 关于项目
    │   └── 意见反馈 pages/mine/feedback
    │       └── 分类、内容、联系方式 → 服务端保存 → 成功编号
    └── 关于项目 pages/mine/about
        ├── 项目介绍与核心能力
        ├── 技术栈
        ├── 服务条款
        └── 隐私说明
```

`pages.json` 未配置原生 `tabBar`。首页和“我的”使用项目内自定义底部导航，保持统一视觉样式。

## 页面与截图索引

| # | 页面 | Route | 进入方式 | 主要功能 | 截图 |
|---|---|---|---|---|---|
| 01 | 登录/注册/找回密码 | `pages/auth/auth` | 小程序启动；设置页修改密码 | 手机号登录、验证码注册、验证码重置密码 | [登录](screenshots/01-auth-login.png) · [注册](screenshots/01-auth-register.png) · [重置](screenshots/01-auth-reset.png) |
| 02 | 首页 | `pages/home/home` | 登录成功 | 服务概览、最近订单、购买入口、自定义底部导航 | [截图](screenshots/02-home.png) |
| 03 | 申请售后 | `pages/after-sale/apply?orderId=...` | 订单列表/详情 | 原因、描述、凭证入口、提交 | [顶部](screenshots/03-after-sale-apply.png) · [底部](screenshots/03-after-sale-apply-bottom.png) · [填写态](screenshots/03-after-sale-apply-filled.png) |
| 04 | 咨询会话 | `pages/chat/list` | 首页“咨询”/“我的”联系客服 | 会话列表、新咨询、删除/归档 | [截图](screenshots/04-chat-list.png) |
| 05 | 智能客服 | `pages/chat/consult?sessionId=...` | 会话列表、订单、售后 | AI 对话、转人工、补充凭证、消息持久化 | [截图](screenshots/05-chat-consult.png) |
| 06 | 售后评价 | `pages/chat/evaluate?sessionId=...` | 待评价会话 | 五维评分、补充评价 | [顶部](screenshots/06-chat-evaluate.png) · [底部](screenshots/06-chat-evaluate-bottom.png) |
| 07 | 订单/售后详情 | `pages/after-sale/detail?orderId=...` | 订单/售后列表 | 订单信息、物流地图、售后进度、客服入口 | [售后态](screenshots/07-after-sale-detail.png) · [物流态](screenshots/07-order-detail-logistics.png) · [物流底部](screenshots/07-order-detail-logistics-bottom.png) |
| 08 | 我的 | `pages/mine/mine` | 自定义底部导航 | 用户资料、订单统计、售后服务、设置入口 | [顶部](screenshots/08-mine.png) · [底部](screenshots/08-mine-bottom.png) |
| 09 | 我的订单 | `pages/orders/list` | 首页/我的 | 状态筛选、详情、确认收货、售后、客服 | [截图](screenshots/09-orders-list.png) |
| 10 | 演示购买 | `pages/shop/shop` | 首页按钮 | 真实商品列表、一键创建订单 | [截图](screenshots/10-shop.png) |
| 11 | 我的售后 | `pages/after-sale/list` | 我的 | 售后列表、状态筛选、详情/客服 | [截图](screenshots/11-after-sale-list.png) |
| 12 | 收货地址 | `pages/mine/address` | 我的 | 列表、新增、编辑、默认、删除 | [列表](screenshots/12-address.png) · [新增表单](screenshots/12-address-new-form.png) |
| 13 | 账号设置 | `pages/mine/settings` | 我的 | 资料、密码、通知、缓存、关于、反馈、退出 | [截图](screenshots/13-settings.png) |
| 14 | 意见反馈 | `pages/mine/feedback` | 设置 | 分类、内容、联系方式、服务端持久化、成功编号 | [提交成功](screenshots/14-feedback-success.png) |
| 15 | 关于项目 | `pages/mine/about` | 我的/设置 | 项目介绍、技术栈、核心能力、条款与隐私说明 | [顶部](screenshots/15-about.png) · [底部](screenshots/15-about-bottom.png) |
| 16 | 编辑资料 | `pages/mine/profile` | 我的/设置 | 头像入口、昵称保存、账号信息 | [截图](screenshots/16-profile.png) |

总览图：[16 个正式页面联系表](screenshots/00-showcase-contact-sheet.png)

## 核心业务流程

### 用户

```text
登录 → 首页 → 我的 → 编辑资料 → 保存 → 设置 → 修改密码 → 验证码重置
```

### 地址

```text
我的 → 收货地址 → 新增 → 编辑 → 设置默认 → 删除
```

地址以 Spring Boot + MyBatis-Plus + MySQL 为唯一业务数据源。用户身份来自 JWT；新增、编辑、设默认和删除后重新加载服务端数据。

### 订单

```text
首页 → 演示购买 → 一键购买 → 我的订单 → 订单详情 → 物流地图/轨迹
```

### 售后

```text
已收货订单 → 申请售后 → 选择原因 → 填写描述 → 凭证图片入口 → 提交 → 售后详情/客服
```

### 客服

```text
咨询会话 → 新咨询 → 独立服务端会话 → AI 客服 → AI 异常捕获 → 转人工 → 消息持久化 → 评价
```

## 当前实现状态

- 16 个正式路由均能在微信开发者工具模拟器打开。
- 登录、订单、商品、售后、客服和资料页面均使用真实本地 API 数据。
- 地址已移除业务层 Storage 依赖；默认地址由事务和数据库唯一索引共同约束。
- 意见反馈已接入真实 POST API、MySQL 持久化、重复提交保护和管理员查询。
- 关于页已替换占位入口，展示真实项目介绍、技术栈、条款和隐私说明。
- Java、Python Agent、Review Consumer、MySQL、Redis、Kafka、PostgreSQL/pgvector、Ollama、Reranker、Prometheus、Grafana 均已接入本地完整运行栈。
- 本轮自动化采集到的 JavaScript Console 错误和页面异常均为 0。

## 当前限制

1. 头像选择需要操作系统原生文件选择器，自动化协议只能验证入口被唤起。
2. 售后凭证图片同样依赖原生文件选择器。
3. `touristappid` 环境不能完整验证腾讯地图在线瓦片与正式 AppID 能力。
4. 本地 Ollama 不可用时，系统会降级人工客服；前端保持可用且消息继续持久化。

## 未实现入口分类

| 能力 | 分类 | 本轮处理 |
| --- | --- | --- |
| 意见反馈 | SHOULD_IMPLEMENT | 已完成小程序表单、MySQL、后台查询与防重复提交 |
| 项目介绍、技术栈、服务条款、隐私说明 | SHOULD_IMPLEMENT | 已在关于页提供正式静态内容 |
| 独立“去评分”入口 | OPTIONAL | 已有客服会话评价页，未新增重复入口 |
| 专用投诉工单 | OUT_OF_SCOPE | 当前售后申请与人工客服已覆盖问题升级，本轮不扩展新工单类型 |
| 应用商店版本更新检查 | OUT_OF_SCOPE | 依赖正式 AppID 与发布渠道，本地求职展示不实现 |

## Final Verification

- 开发基线：`b784af9a49037e0683c9af5762d042c4f4a259a4`
- 正式路由：16
- PASS：12
- PASS_WITH_WARNINGS：4（头像文件选择、售后凭证文件选择、`touristappid` 地图、外部 AI 降级演示）
- FAIL：0
- BLOCKED：0
- 微信自动化：登录、16 路由访问、地址校验不关弹窗、设置到反馈跳转、反馈提交成功
- Console：0 条
- 页面异常：0 条
- API：地址 CRUD/编辑/单默认/删除 PASS；反馈提交/409 防重复/管理员查询 PASS
- Flyway：MySQL 3308 基线版本 0，V1/V2 成功执行，当前版本 2
- 服务：Java、Agent、Consumer、MySQL、Redis、PostgreSQL、Kafka、Ollama、Reranker、Prometheus、Grafana 均 UP；三个 Prometheus Targets UP
- Network 证据：页面真实数据加载与 API 闭环均成功；自动化 SDK 未提供完整 Network 面板导出
- Java 全量测试：163 tests，0 failures，0 errors，28 skipped
- Python 确定性测试：609 passed，8 deselected，81 warnings
- Agent 安全评测：16/16 passed，`handoff_recall=1.0`，`auto_review_safety_violations=0`
- 管理端契约测试：17/17 passed
- 生产构建：管理端 Vue PASS；`mp-weixin` PASS
- Git：`git diff --check` PASS；高置信度密钥、Token、私钥扫描未发现命中
- 并发反馈验证：相同用户同时提交相同内容得到 HTTP 200 + 409，成功记录仅一条
- 临时验证实例：18080 已清理；外部 8080 Java 和 MySQL 3308 未停止、未重置、未强制终止
- 剩余 warning：头像与售后凭证依赖原生文件选择器；`touristappid` 限制地图能力；Ollama 异常时按设计降级人工并保持消息持久化
- 最终结论：`APPLICATION ACCEPTANCE: PASS_WITH_WARNINGS`

## 推荐演示顺序

1. 登录并展示首页服务概览。
2. 打开商品页创建订单，再进入订单列表和物流详情。
3. 从已收货订单发起售后，展示原因、描述和凭证入口。
4. 进入客服会话，说明 AI、RAG、转人工和持久化链路。
5. 展示售后进度和多维评价。
6. 进入“我的”，展示资料、地址、设置和关于页。
7. 最后切到 Prometheus/Grafana 和 GitHub Actions，说明可观测性与测试基线。
