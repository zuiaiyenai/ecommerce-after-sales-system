-- ============================================================
-- 电商售后客服与用户评价分析系统 - 完整数据库脚本
-- 严格对齐概要设计文档 E-R 实体设计，MySQL 18 张表 + pgvector 1 张表
-- ============================================================

CREATE DATABASE IF NOT EXISTS ecommerce_aftersales
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_unicode_ci;

USE ecommerce_aftersales;

-- ============================================================
-- 第一组：用户与权限
-- ============================================================

-- 1. 终端用户表（已有，保持不变）
CREATE TABLE IF NOT EXISTS user_info
(
    id              BIGINT       NOT NULL COMMENT '用户ID',
    user_account    VARCHAR(50)  NOT NULL COMMENT '用户账号，默认使用手机号',
    phone           VARCHAR(20)  NOT NULL COMMENT '手机号',
    password        VARCHAR(100) NOT NULL COMMENT 'BCrypt加密密码',
    openid          VARCHAR(64)  NULL     COMMENT '微信小程序openid',
    nickname        VARCHAR(50)  NULL     COMMENT '昵称',
    avatar_url      VARCHAR(255) NULL     COMMENT '头像地址',
    bind_status     TINYINT      NOT NULL DEFAULT 0 COMMENT '账号绑定状态：0未绑定，1已绑定',
    role_type       VARCHAR(20)  NOT NULL DEFAULT 'USER' COMMENT '角色类型：USER普通用户',
    status          TINYINT      NOT NULL DEFAULT 1 COMMENT '状态：1正常，0禁用',
    last_login_time DATETIME     NULL     COMMENT '最后登录时间',
    deleted         TINYINT      NOT NULL DEFAULT 0 COMMENT '逻辑删除：0未删除，1已删除',
    create_time     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    update_time     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_user_info_account (user_account),
    UNIQUE KEY uk_user_info_phone (phone),
    UNIQUE KEY uk_user_info_openid (openid)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COMMENT = '终端用户表';

-- 2. 后台人员表（客服/管理员）
CREATE TABLE IF NOT EXISTS sys_user
(
    id              BIGINT       NOT NULL COMMENT '人员ID',
    username        VARCHAR(50)  NOT NULL COMMENT '登录账号',
    password        VARCHAR(100) NOT NULL COMMENT 'BCrypt加密密码',
    merchant_code   VARCHAR(50)  NOT NULL DEFAULT 'MERCHANT_DEMO' COMMENT '所属商家编码',
    real_name       VARCHAR(50)  NOT NULL COMMENT '真实姓名',
    phone           VARCHAR(20)  NULL     COMMENT '联系电话',
    email           VARCHAR(100) NULL     COMMENT '邮箱',
    avatar_url      VARCHAR(255) NULL     COMMENT '头像',
    role_type       VARCHAR(20)  NOT NULL DEFAULT 'AGENT' COMMENT '角色：AGENT客服/SUPERVISOR主管/ADMIN管理员',
    status          TINYINT      NOT NULL DEFAULT 1 COMMENT '状态：1在职，0离职，2禁用',
    online_status   TINYINT      NOT NULL DEFAULT 0 COMMENT '在线状态：0离线，1在线，2忙碌',
    max_sessions    INT          NOT NULL DEFAULT 5 COMMENT '最大同时会话数',
    last_login_time DATETIME     NULL     COMMENT '最后登录时间',
    deleted         TINYINT      NOT NULL DEFAULT 0 COMMENT '逻辑删除：0未删除，1已删除',
    create_time     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    update_time     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_sys_user_merchant_username (merchant_code, username),
    INDEX idx_sys_user_merchant (merchant_code)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COMMENT = '后台人员表(客服/管理员)';

-- 3. 收货地址表
CREATE TABLE IF NOT EXISTS shipping_address
(
    id          BIGINT       NOT NULL COMMENT '地址ID',
    user_id     BIGINT       NOT NULL COMMENT '用户ID',
    name        VARCHAR(50)  NOT NULL COMMENT '收货人姓名',
    phone       VARCHAR(20)  NOT NULL COMMENT '收货人电话',
    province    VARCHAR(50)  NOT NULL COMMENT '省',
    city        VARCHAR(50)  NOT NULL COMMENT '市',
    district    VARCHAR(50)  NOT NULL COMMENT '区/县',
    detail      VARCHAR(255) NOT NULL COMMENT '详细地址',
    is_default  TINYINT      NOT NULL DEFAULT 0 COMMENT '是否默认：0否，1是',
    deleted     TINYINT      NOT NULL DEFAULT 0 COMMENT '逻辑删除：0未删除，1已删除',
    create_time DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    update_time DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (id),
    INDEX idx_shipping_address_user (user_id)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COMMENT = '收货地址表';

-- ============================================================
-- 第二组：商品与订单
-- ============================================================

-- 4. 商品信息表
CREATE TABLE IF NOT EXISTS product_info
(
    id           BIGINT        NOT NULL COMMENT '商品ID',
    product_name VARCHAR(200)  NOT NULL COMMENT '商品名称',
    product_code VARCHAR(50)   NULL     COMMENT '商品编码',
    merchant_id  BIGINT        NULL     COMMENT '所属商家/客服主体ID(sys_user)',
    merchant_code VARCHAR(50)  NOT NULL DEFAULT 'MERCHANT_DEMO' COMMENT '所属商家编码',
    category     VARCHAR(100)  NULL     COMMENT '商品分类',
    description  TEXT          NULL     COMMENT '商品描述',
    main_image   VARCHAR(255)  NULL     COMMENT '主图地址',
    images       TEXT          NULL     COMMENT '图片列表(JSON数组)',
    price        DECIMAL(10,2) NOT NULL COMMENT '售价',
    status       TINYINT       NOT NULL DEFAULT 1 COMMENT '状态：1上架，0下架',
    deleted      TINYINT       NOT NULL DEFAULT 0 COMMENT '逻辑删除：0未删除，1已删除',
    create_time  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    update_time  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (id),
    INDEX idx_product_info_merchant (merchant_code),
    INDEX idx_product_info_category (category)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COMMENT = '商品信息表';

-- 5. 订单主表
CREATE TABLE IF NOT EXISTS order_info
(
    id               BIGINT        NOT NULL COMMENT '订单ID',
    order_no         VARCHAR(32)   NOT NULL COMMENT '订单编号',
    user_id          BIGINT        NOT NULL COMMENT '用户ID',
    merchant_id      BIGINT        NULL     COMMENT '所属商家/客服主体ID(sys_user)',
    merchant_code    VARCHAR(50)   NOT NULL DEFAULT 'MERCHANT_DEMO' COMMENT '所属商家编码',
    total_amount     DECIMAL(10,2) NOT NULL COMMENT '订单总金额',
    pay_amount       DECIMAL(10,2) NOT NULL COMMENT '实付金额',
    status           VARCHAR(20)   NOT NULL DEFAULT 'PAID' COMMENT '状态：PAID已付款/SHIPPED已发货/RECEIVED已收货/AFTERSALE售后中/COMPLETED售后完成/CLOSED已关闭',
    receiver_name    VARCHAR(50)   NULL     COMMENT '收货人姓名',
    receiver_phone   VARCHAR(20)   NULL     COMMENT '收货人电话',
    receiver_address VARCHAR(500)  NULL     COMMENT '收货地址',
    tracking_company VARCHAR(50)   NULL     COMMENT '快递公司',
    tracking_no      VARCHAR(50)   NULL     COMMENT '快递单号',
    pay_time         DATETIME      NULL     COMMENT '支付时间',
    ship_time        DATETIME      NULL     COMMENT '发货时间',
    receive_time     DATETIME      NULL     COMMENT '收货时间',
    close_time       DATETIME      NULL     COMMENT '关闭时间',
    remark           VARCHAR(500)  NULL     COMMENT '订单备注',
    deleted          TINYINT       NOT NULL DEFAULT 0 COMMENT '逻辑删除：0未删除，1已删除',
    create_time      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    update_time      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_order_info_no (order_no),
    INDEX idx_order_info_user (user_id),
    INDEX idx_order_info_merchant (merchant_code),
    INDEX idx_order_info_status (status)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COMMENT = '订单主表';

-- 6. 订单明细表
CREATE TABLE IF NOT EXISTS order_item
(
    id           BIGINT        NOT NULL COMMENT '明细ID',
    order_id     BIGINT        NOT NULL COMMENT '订单ID',
    product_id   BIGINT        NOT NULL COMMENT '商品ID',
    price        DECIMAL(10,2) NOT NULL COMMENT '单价',
    quantity     INT           NOT NULL COMMENT '购买数量',
    subtotal     DECIMAL(10,2) NOT NULL COMMENT '小计金额',
    create_time  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    PRIMARY KEY (id),
    INDEX idx_order_item_order (order_id)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COMMENT = '订单明细表';

-- ============================================================
-- 第三组：售后服务
-- ============================================================

-- 7. 售后工单表
CREATE TABLE IF NOT EXISTS after_sales_ticket
(
    id                     BIGINT        NOT NULL COMMENT '工单ID',
    ticket_no              VARCHAR(32)   NOT NULL COMMENT '工单编号',
    order_id               BIGINT        NOT NULL COMMENT '订单ID',
    order_no               VARCHAR(32)   NOT NULL COMMENT '订单编号',
    user_id                BIGINT        NOT NULL COMMENT '用户ID',
    merchant_id            BIGINT        NULL     COMMENT '所属商家/客服主体ID(sys_user)',
    merchant_code          VARCHAR(50)   NOT NULL DEFAULT 'MERCHANT_DEMO' COMMENT '所属商家编码',
    policy_code            VARCHAR(64)   NULL     COMMENT '命中的商家策略编码',
    policy_version         VARCHAR(32)   NULL     COMMENT '命中的商家策略版本',
    product_name           VARCHAR(200)  NULL     COMMENT '商品名称(快照)',
    after_sale_type        VARCHAR(30)   NULL     COMMENT '售后类型：REFUND_ONLY仅退款/REFUND_RETURN退货退款/EXCHANGE换货/REPAIR维修(由AI推荐或客服确认)',
    reason                 VARCHAR(50)   NOT NULL COMMENT '售后原因：QUALITY质量问题/WRONG_ITEM发错货/SIZE_ISSUE尺码不合适/DAMAGE物流损坏/NOT_MATCH与描述不符/OTHER其他',
    reason_detail          VARCHAR(500)  NULL     COMMENT '原因补充说明',
    description            TEXT          NULL     COMMENT '用户问题描述',
    refund_amount          DECIMAL(10,2) NULL     COMMENT '退款金额',
    ai_review_audit_json   TEXT          NULL     COMMENT 'AI初审审计JSON，包含视觉证据、RAG命中、风险原因与策略引用',
    ai_review_confidence   DECIMAL(3,2)  NULL     COMMENT 'AI初审置信度(0~1，表示本次审核结论把握度)',
    ai_suggested_after_sale_type VARCHAR(30) NULL COMMENT 'AI建议售后类型：REFUND_ONLY/REFUND_RETURN/EXCHANGE/REPAIR',
    ai_review_request_id   VARCHAR(64)   NULL     COMMENT 'AI审批实例ID，创建工单时固定，兼作LangGraph thread_id',
    ai_review_status       VARCHAR(32)   NOT NULL DEFAULT 'RUNNING' COMMENT 'AI审批运行阶段：RUNNING/WAITING_EVIDENCE/RESUME_PENDING/COMPLETED/MANUAL_REQUIRED',
    evidence_revision      INT           NOT NULL DEFAULT 0 COMMENT '审核上下文凭证版本，每次有效补充原子递增',
    ai_review_result       VARCHAR(30)   NULL     COMMENT 'AI初审结论：APPROVE/MANUAL_REVIEW_REQUIRED',
    ai_review_reason       VARCHAR(500)  NULL     COMMENT 'AI初审原因',
    ai_review_time         DATETIME      NULL     COMMENT 'AI初审时间',
    manual_review_required TINYINT       NOT NULL DEFAULT 0 COMMENT 'AI初审是否要求人工复核：0否，1是',
    status                 VARCHAR(20)   NOT NULL DEFAULT 'PENDING' COMMENT '状态：PENDING/PENDING_REVIEW待审核，PROCESSING处理中，MANUAL_REVIEW_REQUIRED待人工复核，APPROVED/REJECTED/COMPLETED/CLOSED终态',
    priority               TINYINT       NOT NULL DEFAULT 0 COMMENT '优先级：0普通，1紧急，2非常紧急',
    assignee_id            BIGINT        NULL     COMMENT '处理人ID(sys_user)',
    audit_opinion          VARCHAR(500)  NULL     COMMENT '审核意见',
    audit_time             DATETIME      NULL     COMMENT '审核时间',
    expected_complete_time DATETIME      NULL     COMMENT '预计完成时间',
    complete_time          DATETIME      NULL     COMMENT '完成时间',
    deleted                TINYINT       NOT NULL DEFAULT 0 COMMENT '逻辑删除：0未删除，1已删除',
    active_scope_key       VARCHAR(128)
        GENERATED ALWAYS AS (
            CASE
                WHEN deleted = 0 AND status IN ('PENDING', 'PENDING_REVIEW', 'PROCESSING')
                    THEN CONCAT(user_id, ':', order_id)
                ELSE NULL
            END
        ) STORED COMMENT '活动工单幂等作用域键：同一用户同一订单仅允许一张打开中的售后单',
    create_time            DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    update_time            DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_after_sales_ticket_no (ticket_no),
    UNIQUE KEY uk_after_sales_ai_review_request (ai_review_request_id),
    UNIQUE KEY uk_after_sales_ticket_active_scope (active_scope_key),
    INDEX idx_after_sales_ticket_order (order_id),
    INDEX idx_after_sales_ticket_user (user_id),
    INDEX idx_after_sales_ticket_merchant (merchant_code),
    INDEX idx_after_sales_ticket_status (status),
    INDEX idx_after_sales_ticket_assignee (assignee_id),
    INDEX idx_after_sales_ticket_reuse_lookup (user_id, order_id, status, update_time)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COMMENT = '售后工单表';

-- 8. 工单流转日志表
CREATE TABLE IF NOT EXISTS ticket_log
(
    id            BIGINT       NOT NULL COMMENT '日志ID',
    ticket_id     BIGINT       NOT NULL COMMENT '工单ID',
    operator_id   BIGINT       NULL     COMMENT '操作人ID',
    operator_type VARCHAR(20)  NOT NULL COMMENT '操作人类型：USER用户/AGENT客服/SYSTEM系统/AI智能',
    from_status   VARCHAR(20)  NULL     COMMENT '原状态',
    to_status     VARCHAR(20)  NOT NULL COMMENT '新状态',
    action        VARCHAR(50)  NOT NULL COMMENT '操作动作(如: SUBMIT/AUDIT/APPROVE/REJECT/TRANSFER)',
    content       VARCHAR(500) NULL     COMMENT '操作内容/审核意见',
    create_time   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    PRIMARY KEY (id),
    INDEX idx_ticket_log_ticket (ticket_id)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COMMENT = '工单流转日志表';

-- 9. 售后凭证表
CREATE TABLE IF NOT EXISTS ticket_attachment
(
    id          BIGINT       NOT NULL COMMENT '附件ID',
    ticket_id   BIGINT       NOT NULL COMMENT '工单ID',
    file_url    VARCHAR(255) NOT NULL COMMENT '文件地址',
    file_type   VARCHAR(20)  NOT NULL DEFAULT 'IMAGE' COMMENT '类型：IMAGE图片/VIDEO视频/FILE文件',
    file_name   VARCHAR(100) NULL     COMMENT '原始文件名',
    file_size   BIGINT       NULL     COMMENT '文件大小(字节)',
    sort_order  INT          NOT NULL DEFAULT 0 COMMENT '排序序号',
    create_time DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    PRIMARY KEY (id),
    INDEX idx_ticket_attachment_ticket (ticket_id)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COMMENT = '售后凭证表';

-- 10. 售后事件 Outbox 表
CREATE TABLE IF NOT EXISTS after_sales_event_outbox
(
    id               BIGINT       NOT NULL COMMENT 'Outbox事件ID',
    event_id         VARCHAR(64)  NOT NULL COMMENT '业务事件唯一ID',
    event_type       VARCHAR(64)  NOT NULL COMMENT '事件类型',
    topic            VARCHAR(128) NOT NULL COMMENT 'Kafka Topic',
    aggregate_type   VARCHAR(64)  NOT NULL COMMENT '聚合类型',
    aggregate_id     BIGINT       NOT NULL COMMENT '聚合ID',
    payload          TEXT         NOT NULL COMMENT '事件载荷JSON',
    status           VARCHAR(20)  NOT NULL DEFAULT 'NEW' COMMENT 'NEW/PUBLISHED/FAILED/DEAD',
    retry_count      INT          NOT NULL DEFAULT 0 COMMENT '发布重试次数',
    last_error       VARCHAR(500) NULL COMMENT '最后一次发布错误',
    next_retry_time  DATETIME     NULL COMMENT '下次重试时间',
    published_time   DATETIME     NULL COMMENT '发布时间',
    create_time      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    update_time      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_after_sales_outbox_event_id (event_id),
    INDEX idx_after_sales_outbox_publish (status, next_retry_time, create_time),
    INDEX idx_after_sales_outbox_aggregate (aggregate_type, aggregate_id)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COMMENT = '售后领域事件Outbox表';

-- ============================================================
-- 第四组：在线客服与会话
-- ============================================================

-- 10. 客服会话表
CREATE TABLE IF NOT EXISTS chat_session
(
    id              BIGINT       NOT NULL COMMENT '会话ID',
    session_no      VARCHAR(32)  NOT NULL COMMENT '会话编号',
    user_id         BIGINT       NOT NULL COMMENT '用户ID',
    merchant_id     BIGINT       NULL     COMMENT '所属商家/客服主体ID(sys_user)',
    merchant_code   VARCHAR(50)  NOT NULL DEFAULT 'MERCHANT_DEMO' COMMENT '所属商家编码',
    policy_code     VARCHAR(64)  NULL     COMMENT '命中的商家策略编码',
    policy_version  VARCHAR(32)  NULL     COMMENT '命中的商家策略版本',
    order_id        BIGINT       NULL     COMMENT '关联订单ID',
    ticket_id       BIGINT       NULL     COMMENT '关联工单ID',
    human_agent_id  BIGINT       NULL     COMMENT '人工客服ID(sys_user)',
    mode            VARCHAR(10)  NOT NULL DEFAULT 'AI' COMMENT '当前模式：AI智能客服/HUMAN人工客服',
    status          VARCHAR(20)  NOT NULL DEFAULT 'ACTIVE' COMMENT '状态：ACTIVE进行中/WAITING等待人工/CLOSED已关闭',
    emotion_score   DECIMAL(3,2) NULL     COMMENT '用户情绪负面强度分值(0~1，越高越负面)',
    emotion_confidence DECIMAL(3,2) NULL  COMMENT '用户情绪判断置信度(0~1)',
    emotion_label   VARCHAR(20)  NULL     COMMENT '情绪标签：NORMAL正常/ANXIETY焦虑/ANGRY愤怒',
    user_query      VARCHAR(500) NULL     COMMENT '用户初始问题摘要',
    resolved        TINYINT      NOT NULL DEFAULT 0 COMMENT '是否已解决：0未解决，1已解决',
    satisfaction    TINYINT      NULL     COMMENT '用户满意度评分(1~5)',
    close_time      DATETIME     NULL     COMMENT '会话关闭时间',
    deleted         TINYINT      NOT NULL DEFAULT 0 COMMENT '逻辑删除：0未删除，1已删除',
    create_time     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    update_time     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    user_hidden     TINYINT      NOT NULL DEFAULT 0 COMMENT 'user-side hidden from recent list',
    active_scope_key VARCHAR(255) GENERATED ALWAYS AS (
        CASE
            WHEN deleted = 0 AND status <> 'CLOSED' THEN CONCAT(
                user_id, ':', merchant_code, ':', COALESCE(order_id, 0), ':', COALESCE(ticket_id, 0)
            )
            ELSE NULL
        END
    ) STORED COMMENT 'active-session idempotency scope',
    PRIMARY KEY (id),
    UNIQUE KEY uk_chat_session_no (session_no),
    UNIQUE KEY uk_chat_session_active_scope (active_scope_key),
    INDEX idx_chat_session_user (user_id),
    INDEX idx_chat_session_merchant (merchant_code),
    INDEX idx_chat_session_agent (human_agent_id),
    INDEX idx_chat_session_status (status),
    INDEX idx_chat_session_reuse_lookup (user_id, merchant_code, order_id, ticket_id, status, update_time)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COMMENT = '客服会话表';

-- 11. 聊天消息表
CREATE TABLE IF NOT EXISTS chat_message
(
    id            BIGINT       NOT NULL COMMENT '消息ID',
    session_id    BIGINT       NOT NULL COMMENT '会话ID',
    role          VARCHAR(20)  NOT NULL COMMENT '角色：USER用户/ASSISTANT客服(AI或人工)/SYSTEM系统/TOOL工具',
    content       TEXT         NOT NULL COMMENT '消息内容',
    message_type  VARCHAR(20)  NOT NULL DEFAULT 'TEXT' COMMENT '消息类型：TEXT文本/IMAGE图片/TOOL_CALL工具调用/TOOL_RESULT工具结果',
    file_url      VARCHAR(500) NULL     COMMENT '图片/文件消息访问地址',
    business_key  VARCHAR(191) NULL     COMMENT '重要业务通知幂等键',
    tool_call_id  VARCHAR(100) NULL     COMMENT '工具调用ID(关联agent_tool_call)',
    confidence    DECIMAL(3,2) NULL     COMMENT 'AI回复置信度(0~1，表示回复生成/选用把握度)',
    emotion_label VARCHAR(20)  NULL     COMMENT '该条消息情绪标签',
    emotion_score DECIMAL(3,2) NULL     COMMENT '该条消息情绪负面强度分值(0~1，越高越负面)',
    emotion_confidence DECIMAL(3,2) NULL COMMENT '该条消息情绪判断置信度(0~1)',
    knowledge_query VARCHAR(255) NULL COMMENT '本条AI回复触发的知识检索查询词',
    knowledge_retrieval_mode VARCHAR(64) NULL COMMENT '知识检索模式，例如 lexical_hybrid_v1',
    knowledge_hit_count INT NULL COMMENT '本条AI回复命中的知识条数',
    knowledge_hits_json JSON NULL COMMENT '命中的知识列表(JSON)',
    knowledge_trace_json JSON NULL COMMENT '知识检索trace(JSON)',
    token_usage   INT          NULL     COMMENT '本次回复Token消耗量',
    create_time   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_chat_message_business_key (business_key),
    INDEX idx_chat_message_session (session_id),
    INDEX idx_chat_message_session_time (session_id, create_time),
    INDEX idx_chat_message_session_id (session_id, id),
    INDEX idx_chat_message_time (create_time)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COMMENT = '聊天消息表';

-- ============================================================
-- 第五组：评价与反馈
-- ============================================================

-- 12. 用户评价表
CREATE TABLE IF NOT EXISTS review_info
(
    id               BIGINT       NOT NULL COMMENT '评价ID',
    order_id         BIGINT       NOT NULL COMMENT '订单ID',
    user_id          BIGINT       NOT NULL COMMENT '用户ID',
    product_score    TINYINT      NULL     COMMENT '商品评分(1~5)',
    logistics_score  TINYINT      NULL     COMMENT '物流评分(1~5)',
    service_score    TINYINT      NULL     COMMENT '客服评分(1~5)',
    after_sale_score TINYINT      NULL     COMMENT '售后体验评分(1~5)',
    overall_score    TINYINT      NOT NULL COMMENT '综合评分(1~5)',
    content          TEXT         NULL     COMMENT '文字评价',
    images           TEXT         NULL     COMMENT '评价图片(JSON数组)',
    is_anonymous     TINYINT      NOT NULL DEFAULT 0 COMMENT '是否匿名：0否，1是',
    sentiment        VARCHAR(20)  NULL     COMMENT '情感标签：POSITIVE正面/NEUTRAL中性/NEGATIVE负面',
    sentiment_score  DECIMAL(3,2) NULL     COMMENT '情感分值(0~1)',
    topics           VARCHAR(500) NULL     COMMENT '问题主题标签(JSON数组，如:["商品质量","物流慢"])',
    status           TINYINT      NOT NULL DEFAULT 1 COMMENT '状态：1正常，0隐藏',
    deleted          TINYINT      NOT NULL DEFAULT 0 COMMENT '逻辑删除：0未删除，1已删除',
    create_time      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    update_time      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (id),
    INDEX idx_review_info_order (order_id),
    INDEX idx_review_info_user (user_id),
    INDEX idx_review_info_sentiment (sentiment)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COMMENT = '用户评价表';

-- ============================================================
-- 第六组：AI 知识库已迁移至 PostgreSQL/pgvector。
-- pgvector 建表语句见: sql/pgvector_schema.sql
-- document_type 区分来源表: PRODUCT_KNOWLEDGE / FAQ / AFTER_SALES_POLICY

-- ============================================================
-- 第七组：规则与配置
-- ============================================================

-- ============================================================
-- 第八组：消息与系统
-- ============================================================

-- 18. 消息通知表
CREATE TABLE IF NOT EXISTS message_notice
(
    id          BIGINT       NOT NULL COMMENT '通知ID',
    user_id     BIGINT       NOT NULL COMMENT '接收用户ID',
    title       VARCHAR(200) NOT NULL COMMENT '通知标题',
    content     TEXT         NOT NULL COMMENT '通知内容',
    notice_type VARCHAR(30)  NOT NULL COMMENT '类型：SYSTEM系统通知/AFTER_SALE售后通知/ORDER订单通知/CHAT消息通知/ANNOUNCEMENT平台公告',
    ref_id      BIGINT       NULL     COMMENT '关联业务ID(如工单ID、订单ID)',
    ref_type    VARCHAR(30)  NULL     COMMENT '关联业务类型(如TICKET、ORDER)',
    is_read     TINYINT      NOT NULL DEFAULT 0 COMMENT '是否已读：0未读，1已读',
    read_time   DATETIME     NULL     COMMENT '阅读时间',
    create_time DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    PRIMARY KEY (id),
    INDEX idx_message_notice_user (user_id),
    INDEX idx_message_notice_read (is_read),
    INDEX idx_message_notice_type (notice_type)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COMMENT = '消息通知表';

-- 19. Agent工具调用日志表
CREATE TABLE IF NOT EXISTS agent_tool_call
(
    id          BIGINT       NOT NULL COMMENT '调用ID',
    session_id  BIGINT       NOT NULL COMMENT '会话ID',
    message_id  BIGINT       NULL     COMMENT '触发消息ID(chat_message)',
    tool_name   VARCHAR(50)  NOT NULL COMMENT '工具名称：query_order查订单/query_stock查库存/query_policy查政策/create_after_sale创工单/transfer_human转人工',
    tool_input  TEXT         NOT NULL COMMENT '工具入参(JSON)',
    tool_output TEXT         NULL     COMMENT '工具返回结果(JSON)',
    status      VARCHAR(20)  NOT NULL DEFAULT 'PENDING' COMMENT '状态：PENDING执行中/SUCCESS成功/FAILED失败',
    error_msg   VARCHAR(500) NULL     COMMENT '错误信息(失败时)',
    duration_ms INT          NULL     COMMENT '执行耗时(毫秒)',
    create_time DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    PRIMARY KEY (id),
    INDEX idx_agent_tool_call_session (session_id),
    INDEX idx_agent_tool_call_tool (tool_name)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COMMENT = 'Agent工具调用日志表';
