-- 售后知识库种子数据
-- 用于向量检索的RAG知识库

-- 清空现有数据（可选）
-- TRUNCATE TABLE knowledge_document CASCADE;

-- 1. 商品破损/质量问题政策
INSERT INTO knowledge_document (source_type, source_code, merchant_code, title, content, product_category, scene, intent, policy_version, status) VALUES
('after_sales_policy', 'damage_policy_001', 'MERCHANT_DEMO', '商品破损售后政策',
'商品破损售后处理规则：
1. 适用范围：收到商品后发现外观破损、裂纹、碎裂、断裂等物理损坏
2. 时效要求：签收后7天内提出申请，超过7天不予受理
3. 证据要求：必须提供清晰的商品破损照片，能看清破损位置和细节
4. 处理方式：经核实确认为破损的，支持退货退款或换货
5. 特别说明：
   - 耳机外壳破裂：支持退换
   - 音箱外壳破损：支持退换
   - 屏幕碎裂：支持退换
   - 充电口损坏：支持退换
6. 不支持情况：人为损坏、使用后出现的破损',
'digital', 'damage', 'refund', 'v1.0', 1),

('after_sales_policy', 'quality_issue_001', 'MERCHANT_DEMO', '质量问题售后政策',
'质量问题售后处理规则：
1. 适用范围：商品存在功能缺陷、性能不达标、电流声、异响、无法正常使用等问题
2. 时效要求：收到商品后15天内提出申请
3. 证据要求：
   - 描述具体故障现象
   - 提供商品整体照片
   - 如有异响等问题，建议提供视频
4. 常见质量问题：
   - 耳机有电流声、杂音、破音
   - 蓝牙连接不稳定、频繁断连
   - 充电无法充满、电池续航严重不足
   - 按键失灵、触控不灵敏
   - 音量异常、单边无声
5. 处理方式：经核实确认为质量问题的，支持退货退款或换货',
'digital', 'quality_issue', 'refund', 'v1.0', 1),

('after_sales_policy', 'return_policy_001', 'MERCHANT_DEMO', '退货退款基本政策',
'退货退款基本规则：
1. 7天无理由退货：
   - 商品未使用、包装完好
   - 不影响二次销售
   - 签收后7天内申请
2. 破损/质量问题退货：
   - 签收后7-15天内申请
   - 需提供照片/视频证据
   - 经审核确认后支持退款
3. 退款金额：商品实付金额（不含运费）
4. 退款时效：退货到仓后3-5个工作日原路退回
5. 注意事项：
   - 退货需保留完整包装和配件
   - 退货运费：质量问题由商家承担，其他情况由买家承担',
'general', 'return', 'refund', 'v1.0', 1),

('after_sales_policy', 'exchange_policy_001', 'MERCHANT_DEMO', '换货政策',
'换货处理规则：
1. 适用情况：
   - 商品破损/质量问题
   - 收到错误商品
   - 商品缺件/漏发配件
2. 时效要求：签收后7天内提出申请
3. 换货流程：
   - 提交换货申请并上传照片
   - 审核通过后寄回商品
   - 收到旧品后3个工作日内发出新品
4. 运费说明：
   - 质量问题：往返运费商家承担
   - 个人原因：往返运费买家承担
5. 换货次数：同一商品最多换货1次，二次质量问题支持退款',
'general', 'exchange', 'exchange', 'v1.0', 1);

-- 2. 常见问题FAQ
INSERT INTO knowledge_document (source_type, source_code, merchant_code, title, content, product_category, scene, intent, policy_version, status) VALUES
('faq', 'faq_damage_evidence', 'MERCHANT_DEMO', '破损商品需要提供什么证据？',
'Q: 商品破损需要提供什么证据？
A: 为了快速处理您的售后申请，请提供以下照片：
1. 商品破损位置的清晰特写照片（能看清裂纹、破损细节）
2. 商品整体照片（显示破损在商品哪个部位）
3. 外包装照片（如外包装也有破损，建议一并拍摄）
4. 物流面单照片（证明是刚收到的商品）

拍摄建议：
- 光线充足、对焦清晰
- 多角度拍摄破损位置
- 如破损较小，建议标注位置

常见场景：
- 耳机外壳破裂：拍摄裂纹位置特写
- 音箱外壳碰损：拍摄碰损凹陷处
- 屏幕碎裂：拍摄整个屏幕和破裂位置',
'digital', 'damage', 'evidence_requirement', 'v1.0', 1),

('faq', 'faq_quality_evidence', 'MERCHANT_DEMO', '质量问题需要提供什么证据？',
'Q: 质量问题需要提供什么证据？
A: 根据不同质量问题，证据要求如下：

1. 有电流声、异响、杂音：
   - 商品整体照片
   - 详细描述故障现象（什么情况下出现、持续时间）
   - 建议提供录音/视频（可选但有助于快速审核）

2. 蓝牙连接问题：
   - 商品照片
   - 描述具体现象（连接失败、频繁断连、配对不上等）
   - 手机型号和系统版本

3. 充电/续航问题：
   - 商品照片
   - 描述充电表现（充不满、掉电快、充电指示灯异常等）

4. 功能失灵：
   - 商品照片
   - 描述哪个功能失效（按键、触控、开关等）

核心原则：照片 + 详细描述，让客服能理解您遇到的具体问题',
'digital', 'quality_issue', 'evidence_requirement', 'v1.0', 1);

-- 3. 商品知识（用于辅助判断）
INSERT INTO knowledge_document (source_type, source_code, merchant_code, title, content, product_category, scene, intent, policy_version, status) VALUES
('product_knowledge', 'product_headphone_common', 'MERCHANT_DEMO', '蓝牙耳机常见问题',
'蓝牙降噪耳机常见质量问题判定：
1. 外壳破裂/开裂：
   - 明显物理损伤，一般为运输或包装问题
   - 支持售后退换

2. 电流声/底噪：
   - 开机后持续存在的底噪属于质量问题
   - 音量调大后明显杂音属于质量问题
   - 特定歌曲特定片段的电流声可能是音源问题，不属于质量问题

3. 蓝牙连接：
   - 10米内频繁断连属于质量问题
   - 无法搜索到设备、配对失败属于质量问题

4. 续航/充电：
   - 新品充满电后使用时间明显低于标称时间（如标称20小时，实际仅2-3小时）
   - 充不满电、充电过程中发热严重

5. 降噪功能：
   - 开启降噪后无明显效果
   - 降噪模式下严重电流声',
'headphone', 'quality_issue', 'quality_standard', 'v1.0', 1);

-- 4. 注意事项和提示
INSERT INTO knowledge_document (source_type, source_code, merchant_code, title, content, product_category, scene, intent, policy_version, status) VALUES
('guideline', 'guideline_photo_tips', 'MERCHANT_DEMO', '售后照片拍摄指南',
'售后申请照片拍摄要求：

一、必须拍摄的内容：
1. 商品问题位置特写（破损、故障部位）
2. 商品整体照片（显示商品全貌）

二、建议拍摄的内容：
1. 外包装照片（证明包装状态）
2. 物流面单照片（证明签收时间）
3. 配件照片（如涉及配件问题）

三、拍摄技巧：
1. 确保光线充足，避免模糊
2. 对焦清晰，问题位置要清楚可见
3. 多角度拍摄，至少2-3张
4. 如破损很小，可用笔或手指指示位置

四、常见错误：
× 照片模糊看不清
× 光线太暗看不清细节
× 只拍局部看不出是什么商品
× 角度不对看不到问题位置

提示：照片越清晰完整，审核越快！',
'general', 'evidence_requirement', 'guideline', 'v1.0', 1);

-- 5. 细分售后规则：让 Agent 对具体场景能命中可审计政策
INSERT INTO knowledge_document (source_type, source_code, merchant_code, title, content, product_category, scene, intent, policy_version, status) VALUES
('after_sales_policy', 'damage_phone_shell_refund_001', 'MERCHANT_DEMO', '手机外壳破裂退款规则',
'适用场景：用户反馈手机外壳破裂、机身裂纹、边框碎裂、后盖破损，并要求退款或退货退款。
处理规则：
1. 用户提交售后申请后先进入待审核状态。
2. 必须至少提供清晰商品破损照片，能看清破裂位置、破损范围和商品主体。
3. 若描述为刚收货、未使用、拆箱即破损，建议补充外包装照片和物流面单照片，用于判断运输破损责任。
4. 清晰照片能证明外壳破裂且订单在售后时效内时，AI 可给出“建议通过”的初审意见，并进入处理中等待人工最终处理。
5. 图片模糊、只拍局部无法确认商品、描述与图片不一致、疑似人为损坏时，不应自动建议通过，应转人工复核。
6. 最终退款、拒绝或补充处理仍由人工客服确认。',
'digital', 'damage', 'refund', 'v1.0', 1),

('after_sales_policy', 'damage_headphone_shell_refund_001', 'MERCHANT_DEMO', '耳机外壳破裂退款规则',
'适用场景：蓝牙耳机、降噪耳机、耳机充电盒存在外壳裂缝、破裂、碎裂、明显开裂，用户要求退款或退货退款。
处理规则：
1. 售后申请创建后状态为待审核。
2. 用户需要提供能清楚显示耳机或充电盒破损位置的商品照片。
3. 若用户称刚打开包装、未使用即破损，应引导补充外包装照片、物流面单照片；缺少这些材料时不直接判定物流责任。
4. 商品破损照片清晰、描述与图片一致、订单状态允许售后时，AI 可建议通过并进入处理中；建议原因要写明“图片显示外壳破裂，符合破损售后规则”。
5. 若图片无法确认破损、只看到正常外观、疑似使用导致损坏，转人工处理。',
'headphone', 'damage', 'refund', 'v1.0', 1),

('scene_evidence', 'damage_evidence_minimum_001', 'MERCHANT_DEMO', '破损售后证据最低要求',
'破损类售后证据要求：
必需证据：
1. 商品破损位置清晰照片。
2. 用户问题描述，说明破损现象和发现时间。
建议补充：
1. 外包装照片，用于判断运输或包装异常。
2. 物流面单照片，用于确认包裹和订单匹配。
判断原则：
1. 缺商品破损照片时，应引导用户上传图片，不能直接建议通过。
2. 有清晰破损照片但缺外包装或面单时，可以先创建待审核申请；是否建议通过取决于政策、订单时效和图片一致性。
3. 描述与图片不一致、图片模糊、无法确认商品主体时，转人工复核。',
'digital', 'damage', 'evidence_requirement', 'v1.0', 1),

('after_sales_policy', 'quality_headphone_current_noise_001', 'MERCHANT_DEMO', '耳机电流声质量问题售后规则',
'适用场景：用户反馈耳机存在电流声、底噪、杂音、异响、单边无声、蓝牙连接异常等质量问题。
处理规则：
1. 用户提交售后申请后先进入待审核状态。
2. 必需信息包括故障描述，例如出现条件、持续时间、是否双耳都有、是否更换设备后仍存在。
3. 建议用户上传商品照片；电流声、异响类问题可补充录音或视频，但不是创建售后申请的唯一前置条件。
4. 描述清楚且订单状态允许售后时，可创建待审核售后单；AI 不应仅凭文字直接建议通过，除非规则和证据都充分。
5. 描述不足时先引导补充描述；无法判断时转人工。',
'headphone', 'quality_issue', 'refund', 'v1.0', 1),

('guideline', 'ai_review_boundary_001', 'MERCHANT_DEMO', 'AI售后初审边界',
'AI售后初审边界：
1. AI 必须先命中知识库政策或证据规则，再给出初审建议；未命中知识库时不能自动建议通过。
2. 用户提交售后申请后，Java 业务层创建的售后单初始状态必须是待审核。
3. 证据充分、政策命中、订单允许售后时，AI 只能给出建议通过及原因，并推动状态进入处理中等待人工最终处理。
4. 证据不足时，AI 应说明缺少的材料，例如商品照片、外包装照片、物流面单照片或故障描述。
5. 图片和描述不一致、无法判断责任、疑似人为损坏、模型无法判断时，必须转人工。
6. 售后处理完成后，系统应自动发送评价邀请。',
'general', 'review', 'guardrail', 'v1.0', 1)
ON CONFLICT (source_type, source_code, merchant_code) DO UPDATE SET
    title = EXCLUDED.title,
    content = EXCLUDED.content,
    product_category = EXCLUDED.product_category,
    scene = EXCLUDED.scene,
    intent = EXCLUDED.intent,
    policy_version = EXCLUDED.policy_version,
    status = EXCLUDED.status,
    updated_at = NOW();
