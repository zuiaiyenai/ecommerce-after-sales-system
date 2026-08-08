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
