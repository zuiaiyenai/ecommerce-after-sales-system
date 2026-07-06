-- ============================================================
-- 种子数据 —— 商品目录 + 默认商家客服账号
-- 执行顺序：先执行 schema.sql，再执行本文件
-- ============================================================

USE ecommerce_aftersales;

-- ============================================================
-- 默认商家客服账号
-- 登录账号：cs_demo
-- 登录密码：123456
-- 商家编码：MERCHANT_DEMO
-- ============================================================

INSERT INTO sys_user (id, username, password, real_name, phone, email, role_type, status, online_status, max_sessions, merchant_code) VALUES
(1, 'cs_demo', '$2a$10$N.zmdr9k7uOCQb376NoUnuTJ8iAt6Z5EHsM8lE9lBOsl7iKTVKIUi', '林真', '13800000001', 'cs_demo@example.com', 'AGENT', 1, 1, 8, 'MERCHANT_DEMO');

-- ============================================================
-- 商品数据（5 个商品，供小程序商城使用）
-- ============================================================

INSERT INTO product_info (id, product_name, product_code, category, description, main_image, images, price, status, merchant_code) VALUES
(1, '纯棉圆领T恤', 'TSHIRT-001', '服装',
 '100%新疆长绒棉，亲肤透气，经典圆领设计，适合日常穿搭。支持机洗，不易变形褪色。',
 '/static/images/product-tshirt.png',
 '["/static/images/product-tshirt.png"]',
 35.00, 1, 'MERCHANT_DEMO'),

(2, '手机', 'PHONE-001', '数码',
 '高性能智能手机，大容量电池，高清屏幕，流畅运行。',
 '/static/images/product-phone.png',
 '["/static/images/product-phone.png"]',
 2999.00, 1, 'MERCHANT_DEMO'),

(3, '相纸', 'PHOTO-001', '日用',
 '高清相纸，6寸规格，40张装，打印效果清晰鲜艳。',
 '/static/images/product-photo-paper.png',
 '["/static/images/product-photo-paper.png"]',
 35.90, 1, 'MERCHANT_DEMO'),

(4, '蓝牙降噪耳机', 'EARPHONE-001', '数码',
 '主动降噪，蓝牙5.3，续航30小时，Type-C快充。支持多设备连接，触控操作。',
 '/static/images/product-earphone.png',
 '["/static/images/product-earphone.png"]',
 129.00, 1, 'MERCHANT_DEMO'),

(5, '运动鞋', 'SHOE-001', '鞋靴',
 '飞织鞋面，轻盈透气，EVA缓震鞋底，适合日常跑步和健身。防滑耐磨橡胶外底。',
 '/static/images/product-shoes.png',
 '["/static/images/product-shoes.png"]',
 199.00, 1, 'MERCHANT_DEMO');

INSERT INTO emotion_level_knowledge (id, code, label, rank_order, meaning, handling_advice, status, deleted) VALUES
(1001, 'satisfied', '满意', 0, '用户情绪正向，可继续常规处理。', '保持简洁确认与正常推进。', 1, 0),
(1002, 'calm', '平静', 1, '用户表达平稳，可按标准流程处理。', '继续正常收集信息和推进售后。', 1, 0),
(1003, 'anxious', '焦虑', 2, '用户有明显催促或担忧。', '优先给进度和明确下一步。', 1, 0),
(1004, 'dissatisfied', '不满', 3, '用户已经表达负面体验。', '加强安抚并谨慎说明处理方案。', 1, 0),
(1005, 'angry', '愤怒', 4, '用户处于高风险负面情绪。', '优先考虑人工介入。', 1, 0);

INSERT INTO after_sales_scheme_knowledge (id, scheme_code, scheme_label, description, requires_return, typical_scenes_json, status, deleted) VALUES
(2001, 'REFUND_ONLY', '仅退款', '无需退回商品，直接进入退款流程。', 0, '["minor_issue","price_compensation"]', 1, 0),
(2002, 'RETURN_REFUND', '退货退款', '需要退回商品，再进入退款流程。', 1, '["quality_issue","product_damage"]', 1, 0),
(2003, 'REISSUE', '补发', '适用于少发、错发、缺件等问题。', 0, '["wrong_or_missing_items"]', 1, 0),
(2004, 'PARTIAL_REFUND', '部分退款', '以差价补偿或局部补偿解决问题。', 0, '["price_diff","minor_defect"]', 1, 0);

INSERT INTO scene_evidence_knowledge (id, scene_code, scene_label, description, default_evidence_json, extra_evidence_json, example_phrases_json, status, deleted) VALUES
(3001, 'quality_issue', '质量问题', '商品功能或质量异常，例如无声音、不开机、漏液、异味。', '["问题描述"]', '["故障照片","故障视频"]', '["耳机没有声音","手机开不了机","充不进电"]', 1, 0),
(3002, 'product_damage', '商品破损', '商品本体破裂、裂痕、变形、损伤。', '["破损照片","问题描述"]', '["开箱视频"]', '["杯子裂了","屏幕碎了","收到就是坏的"]', 1, 0),
(3003, 'package_damage', '包装破损', '外包装或包裹出现明显破损。', '["外包装照片","问题描述"]', '["签收照片"]', '["盒子压坏了","快递外箱破了"]', 1, 0),
(3004, 'wrong_or_missing_items', '少发错发', '收到商品与订单不一致，或少件漏件。', '["商品照片","问题描述"]', '["包裹清单照片"]', '["少发了一个配件","收到的颜色不对"]', 1, 0),
(3005, 'logistics_issue', '物流问题', '延迟、停滞、签收异常等物流场景。', '["问题描述"]', '["物流截图"]', '["物流一直没更新","显示签收但我没收到"]', 1, 0);
