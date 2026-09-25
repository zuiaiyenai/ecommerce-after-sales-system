CREATE TABLE IF NOT EXISTS user_feedback
(
    id          BIGINT       NOT NULL COMMENT '反馈ID',
    user_id     BIGINT       NOT NULL COMMENT '用户ID',
    type        VARCHAR(30)  NOT NULL COMMENT '反馈类型：FUNCTION功能建议/EXPERIENCE体验问题/BUG故障反馈/OTHER其他',
    content     VARCHAR(1000) NOT NULL COMMENT '反馈内容',
    contact     VARCHAR(100) NULL COMMENT '可选联系方式',
    status      VARCHAR(20)  NOT NULL DEFAULT 'PENDING' COMMENT '处理状态：PENDING待处理/PROCESSING处理中/RESOLVED已处理/CLOSED已关闭',
    deleted     TINYINT      NOT NULL DEFAULT 0 COMMENT '逻辑删除：0未删除，1已删除',
    create_time DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    update_time DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (id),
    INDEX idx_user_feedback_user_time (user_id, create_time),
    INDEX idx_user_feedback_status_time (status, create_time)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COMMENT = '用户意见反馈表';
