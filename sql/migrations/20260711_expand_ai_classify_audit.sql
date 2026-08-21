ALTER TABLE after_sales_ticket
    MODIFY COLUMN ai_classify_result TEXT NULL COMMENT 'AI分类、视觉证据与策略审计结果(JSON)';
