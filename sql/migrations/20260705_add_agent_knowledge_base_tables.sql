USE ecommerce_aftersales;

CREATE TABLE IF NOT EXISTS reply_template_knowledge
(
    id            BIGINT       NOT NULL COMMENT 'knowledge id',
    template_code VARCHAR(64)  NOT NULL COMMENT 'template code',
    scene_code    VARCHAR(64)  NULL     COMMENT 'scene code',
    intent_code   VARCHAR(64)  NULL     COMMENT 'intent code',
    tone          VARCHAR(32)  NULL     COMMENT 'tone',
    template_text TEXT         NOT NULL COMMENT 'template text',
    description   VARCHAR(500) NULL     COMMENT 'template description',
    status        TINYINT      NOT NULL DEFAULT 1 COMMENT 'enabled status',
    deleted       TINYINT      NOT NULL DEFAULT 0 COMMENT 'logical delete',
    create_time   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'create time',
    update_time   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'update time',
    PRIMARY KEY (id),
    UNIQUE KEY uk_reply_template_code (template_code),
    INDEX idx_reply_template_status (status)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COMMENT = 'Reply template knowledge';

CREATE TABLE IF NOT EXISTS review_interpretation_knowledge
(
    id                   BIGINT       NOT NULL COMMENT 'knowledge id',
    code                 VARCHAR(64)  NOT NULL COMMENT 'knowledge code',
    sentiment            VARCHAR(32)  NOT NULL COMMENT 'sentiment code',
    scene_code           VARCHAR(64)  NULL     COMMENT 'scene code',
    meaning              VARCHAR(500) NOT NULL COMMENT 'meaning',
    response_strategy    VARCHAR(500) NULL     COMMENT 'response strategy',
    example_phrases_json TEXT         NULL     COMMENT 'example phrases json',
    status               TINYINT      NOT NULL DEFAULT 1 COMMENT 'enabled status',
    deleted              TINYINT      NOT NULL DEFAULT 0 COMMENT 'logical delete',
    create_time          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'create time',
    update_time          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'update time',
    PRIMARY KEY (id),
    UNIQUE KEY uk_review_interpretation_code (code),
    INDEX idx_review_interpretation_status (status)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COMMENT = 'Review interpretation knowledge';

CREATE TABLE IF NOT EXISTS emotion_keyword_knowledge
(
    id           BIGINT       NOT NULL COMMENT 'knowledge id',
    group_code   VARCHAR(64)  NOT NULL COMMENT 'keyword group code',
    group_label  VARCHAR(100) NULL     COMMENT 'keyword group label',
    emotion_code VARCHAR(32)  NOT NULL COMMENT 'emotion code',
    source_scope VARCHAR(32)  NOT NULL DEFAULT 'conversation' COMMENT 'source scope',
    trigger_code VARCHAR(64)  NOT NULL COMMENT 'trigger code',
    keywords_json TEXT        NOT NULL COMMENT 'keywords json',
    hit_score    INT          NOT NULL DEFAULT 0 COMMENT 'hit score',
    status       TINYINT      NOT NULL DEFAULT 1 COMMENT 'enabled status',
    deleted      TINYINT      NOT NULL DEFAULT 0 COMMENT 'logical delete',
    create_time  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'create time',
    update_time  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'update time',
    PRIMARY KEY (id),
    UNIQUE KEY uk_emotion_keyword_group_code (group_code),
    INDEX idx_emotion_keyword_status (status)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COMMENT = 'Emotion keyword knowledge';

CREATE TABLE IF NOT EXISTS emotion_strategy_knowledge
(
    id                    BIGINT       NOT NULL COMMENT 'knowledge id',
    emotion_code          VARCHAR(32)  NOT NULL COMMENT 'emotion code',
    reply_tone            VARCHAR(64)  NOT NULL COMMENT 'reply tone',
    comfort_prefix        VARCHAR(500) NULL     COMMENT 'comfort prefix',
    comfort_examples_json TEXT         NULL     COMMENT 'comfort examples json',
    status                TINYINT      NOT NULL DEFAULT 1 COMMENT 'enabled status',
    deleted               TINYINT      NOT NULL DEFAULT 0 COMMENT 'logical delete',
    create_time           DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'create time',
    update_time           DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'update time',
    PRIMARY KEY (id),
    UNIQUE KEY uk_emotion_strategy_code (emotion_code),
    INDEX idx_emotion_strategy_status (status)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COMMENT = 'Emotion response strategy knowledge';

INSERT INTO faq (id, question, answer, tags, hit_count, chunk_count, vector_status, status, version, operator_id, deleted)
VALUES
    (4001, '退款多久到账？', '正常情况下，退款原路退回后会在 1 到 5 个工作日内到账；具体以支付渠道处理时效为准。', '["退款","到账时效"]', 0, 0, 0, 1, 1, NULL, 0),
    (4002, '退货运费谁承担？', '质量问题、错发少发通常由商家承担；非质量类退货是否承担运费，以商家售后政策和页面说明为准。', '["退货","运费"]', 0, 0, 0, 1, 1, NULL, 0),
    (4003, '平台审核多久？', '资料齐全的情况下，系统会优先自动审核；需要人工复核的工单一般会在 24 小时内给出处理结果。', '["审核","时效"]', 0, 0, 0, 1, 1, NULL, 0)
AS new
ON DUPLICATE KEY UPDATE
    question = new.question,
    answer = new.answer,
    tags = new.tags,
    status = new.status,
    deleted = new.deleted;

INSERT INTO product_knowledge (id, product_id, product_name, title, content, chunk_count, vector_status, status, version, operator_id, deleted)
VALUES
    (4101, 4, '蓝牙降噪耳机', '耳机无声排查与保修说明', '若耳机出现无声，可先确认是否已完成配对、音量是否被静音、左右耳是否都已充电。非人为损坏且在保修期内的功能故障可申请售后。', 0, 0, 1, 1, NULL, 0),
    (4102, 2, '手机', '手机功能故障售后说明', '手机出现无法开机、频繁重启、无法充电等问题时，建议先保留故障现象描述及必要图片或视频，再发起售后申请。', 0, 0, 1, 1, NULL, 0),
    (4103, NULL, '通用商品', '配件与包装清单说明', '涉及少发、错发、缺件的情况，建议同时提供实收商品图、外包装图和清单信息，便于快速判断补发或退款方案。', 0, 0, 1, 1, NULL, 0)
AS new
ON DUPLICATE KEY UPDATE
    product_name = new.product_name,
    title = new.title,
    content = new.content,
    status = new.status,
    deleted = new.deleted;

INSERT INTO after_sales_policy (id, policy_name, policy_code, product_category, content, summary, chunk_count, vector_status, effective_date, expire_date, status, version, operator_id, deleted)
VALUES
    (4201, '7天无理由退货政策', 'NO_REASON_7D', '通用', '签收后 7 天内，在商品完好且不影响二次销售的前提下，可申请退货退款；特殊类目以商品详情页说明为准。', '签收后 7 天内可申请无理由退货，需保持商品完好。', 0, 0, '2026-01-01', NULL, 1, 1, NULL, 0),
    (4202, '数码类功能故障政策', 'DIGITAL_FAULT_15D', '数码', '数码类商品若在签收后 15 天内出现非人为功能故障，可申请检测或售后处理；平台可能要求补充视频、序列号或故障描述。', '数码商品功能故障优先核验故障信息，必要时进入人工复核。', 0, 0, '2026-01-01', NULL, 1, 1, NULL, 0),
    (4203, '少发错发补发政策', 'MISS_ITEM_REISSUE', '通用', '若收到的商品与订单不一致，或存在少件漏件，经核实后可优先安排补发；若用户不接受补发，可按规则协商退款。', '少发错发经核实后优先补发。', 0, 0, '2026-01-01', NULL, 1, 1, NULL, 0)
AS new
ON DUPLICATE KEY UPDATE
    policy_name = new.policy_name,
    product_category = new.product_category,
    content = new.content,
    summary = new.summary,
    status = new.status,
    deleted = new.deleted;

INSERT INTO reply_template_knowledge (id, template_code, scene_code, intent_code, tone, template_text, description, status, deleted)
VALUES
    (4301, 'ask_quality_detail', 'quality_issue', 'apply_after_sales', 'empathetic', '这边先帮您处理。为了更快判断售后方案，麻烦补充一下具体异常表现；如果方便，也可以一起上传照片或视频。', '质量问题首轮补充说明模板', 1, 0),
    (4302, 'reissue_fast_track', 'wrong_or_missing_items', 'apply_after_sales', 'efficient', '已经了解是少发或错发问题了。您把收到的商品照片和问题说明发我，我这边优先帮您走补发核验。', '少发错发补发模板', 1, 0),
    (4303, 'policy_explain_review', NULL, 'refund_progress', 'neutral', '当前申请正在审核处理中，资料齐全时系统会优先处理；如果需要补充材料，我会第一时间告诉您。', '审核进度说明模板', 1, 0)
AS new
ON DUPLICATE KEY UPDATE
    scene_code = new.scene_code,
    intent_code = new.intent_code,
    tone = new.tone,
    template_text = new.template_text,
    description = new.description,
    status = new.status,
    deleted = new.deleted;

INSERT INTO review_interpretation_knowledge (id, code, sentiment, scene_code, meaning, response_strategy, example_phrases_json, status, deleted)
VALUES
    (4401, 'NEG_DELAY', 'negative', 'logistics_issue', '用户对物流时效或签收异常不满，关注点通常是进度不透明和承诺不明确。', '优先解释当前进度、给出下一步时点，必要时转人工跟进物流。', '["物流一直没更新","怎么还没到","显示签收但我没收到"]', 1, 0),
    (4402, 'NEG_QUALITY', 'negative', 'quality_issue', '用户对商品质量或功能异常表达负面反馈，关注点通常是是否能快速补救。', '优先确认问题现象和证据，再明确退货退款、补发或检测路径。', '["耳机没有声音","手机开不了机","收到就是坏的"]', 1, 0),
    (4403, 'NEG_SERVICE', 'negative', NULL, '用户对处理态度或流程拖延不满，后续容易演变为投诉或差评。', '先安抚情绪，再给出明确承诺和时间点；达到阈值时优先转人工。', '["一直没人处理","说了很多次了","你们效率太低"]', 1, 0)
AS new
ON DUPLICATE KEY UPDATE
    sentiment = new.sentiment,
    scene_code = new.scene_code,
    meaning = new.meaning,
    response_strategy = new.response_strategy,
    example_phrases_json = new.example_phrases_json,
    status = new.status,
    deleted = new.deleted;

INSERT INTO emotion_keyword_knowledge (id, group_code, group_label, emotion_code, source_scope, trigger_code, keywords_json, hit_score, status, deleted)
VALUES
    (4501, 'complaint_keywords', '投诉升级词', 'angry', 'conversation', 'complaint', '["投诉","举报","差评","骗人","黑猫","报警","诈骗"]', 55, 1, 0),
    (4502, 'anger_keywords', '强烈不满词', 'angry', 'conversation', 'anger', '["生气","气死","太过分","受不了","你们到底","不满意","离谱","火大"]', 45, 1, 0),
    (4503, 'anxious_keywords', '着急催促词', 'anxious', 'conversation', 'anxious', '["着急","有点着急","很着急","有些着急","尽快","快一点","快点","麻烦快点","抓紧","赶紧","催一下","帮我催","多久能处理好","多久处理好","多久能好","什么时候处理","什么时候能处理","什么时候能好","怎么还没处理","还没处理","一直没处理","一直没有处理"]', 20, 1, 0),
    (4504, 'waiting_progress_keywords', '进度追问词', 'anxious', 'conversation', 'waiting_progress', '["多久","什么时候","还没","一直没","还没有","尽快","进度","催"]', 6, 1, 0),
    (4505, 'order_delay_keywords', '订单延迟词', 'anxious', 'order_status', 'timeout', '["超时","未更新","停滞","延迟","异常","过久"]', 15, 1, 0)
AS new
ON DUPLICATE KEY UPDATE
    group_label = new.group_label,
    emotion_code = new.emotion_code,
    source_scope = new.source_scope,
    trigger_code = new.trigger_code,
    keywords_json = new.keywords_json,
    hit_score = new.hit_score,
    status = new.status,
    deleted = new.deleted;

INSERT INTO emotion_strategy_knowledge (id, emotion_code, reply_tone, comfort_prefix, comfort_examples_json, status, deleted)
VALUES
    (4601, 'calm', 'clear', '', '["我先帮您看当前状态。","这边按页面流程继续推进。"]', 1, 0),
    (4602, 'anxious', 'comfort_and_progress', '您好，理解您现在比较着急，', '["我先帮您确认当前进度。","状态一更新我会第一时间同步您。"]', 1, 0),
    (4603, 'dissatisfied', 'comfort_and_action', '您好，确实让您久等了，', '["这边我先帮您把流程往前推进。","我会继续帮您跟进处理结果。"]', 1, 0),
    (4604, 'angry', 'priority_human_support', '您好，很抱歉给您带来不好的体验，', '["我先帮您优先处理。","如有需要也可以继续转人工跟进。"]', 1, 0)
AS new
ON DUPLICATE KEY UPDATE
    reply_tone = new.reply_tone,
    comfort_prefix = new.comfort_prefix,
    comfort_examples_json = new.comfort_examples_json,
    status = new.status,
    deleted = new.deleted;
