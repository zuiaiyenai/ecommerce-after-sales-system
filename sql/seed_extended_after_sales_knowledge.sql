-- Extended PostgreSQL/pgvector knowledge seed for after-sales Agent.
-- Execute against ecommerce_rag. Rebuild knowledge_chunk after this file is applied.

INSERT INTO knowledge_document
    (source_type, source_code, merchant_code, title, content, product_category, scene, intent, policy_version, status)
VALUES
('after_sales_policy', 'damage_phone_shell_refund_001', 'MERCHANT_DEMO', '手机外壳破裂退款规则',
$$适用场景：用户反馈手机外壳破裂、机身裂纹、边框磕碰、后盖破损，并要求退款或退货退款。
处理规则：
1. 售后申请创建后状态应为待审核。
2. 必须提供清晰商品破损照片，能看清破裂位置、破损范围和商品主体。
3. 如果用户称刚收到即破损，应补充外包装照片和物流面单。
4. 照片清晰、描述一致、订单在售后时效内时，AI可以给出建议通过的初审意见。
5. 图片模糊、疑似人为损坏、描述和图片不一致时，应转人工。$$,
'digital', 'damage', 'refund', 'v1.0', 1),

('after_sales_policy', 'damage_headphone_shell_refund_001', 'MERCHANT_DEMO', '耳机外壳破裂退款规则',
$$适用场景：蓝牙耳机、降噪耳机、充电盒存在外壳裂缝、破裂、明显开裂，用户要求退款或退货退款。
处理规则：
1. 需要提供清晰显示耳机或充电盒破损位置的照片。
2. 刚开箱即破损时，建议补充外包装和物流面单照片。
3. 商品破损照片清晰、描述一致、订单允许售后时，可以建议通过并进入处理中。
4. 图片无法确认破损或只看到正常外观时，转人工处理。$$,
'headphone', 'damage', 'refund', 'v1.0', 1),

('scene_evidence', 'damage_evidence_minimum_001', 'MERCHANT_DEMO', '破损售后证据最低要求',
$$破损类售后最低证据：
1. 商品破损位置清晰照片。
2. 用户问题描述，说明破损现象和发现时间。
建议补充：
1. 外包装照片，用于判断运输或包装异常。
2. 物流面单照片，用于确认包裹和订单匹配。
判断原则：缺少破损照片时不能建议通过；图片模糊或无法确认商品主体时应补充材料或转人工。$$,
'digital', 'damage', 'evidence_requirement', 'v1.0', 1),

('after_sales_policy', 'quality_headphone_current_noise_001', 'MERCHANT_DEMO', '耳机电流声质量问题售后规则',
$$适用场景：用户反馈耳机存在电流声、底噪、杂音、异响、单边无声、蓝牙连接异常。
处理规则：
1. 用户需要说明出现条件、持续时间、是否双耳都有、是否更换设备后仍存在。
2. 建议上传商品照片；声音类问题建议补充录音或视频。
3. 描述清楚且订单允许售后时，可以创建待审核售后单。
4. 不能仅凭文字直接承诺审核通过；证据不足时先引导补充材料或转人工。$$,
'headphone', 'quality_issue', 'refund', 'v1.0', 1),

('after_sales_policy', 'quality_phone_charging_slow_001', 'MERCHANT_DEMO', '手机充电慢质量问题售后规则',
$$适用场景：用户反馈手机充电很慢、充不进电、充电发热、充电断断续续，并要求退款、换货或检测。
处理规则：
1. 需要说明充电器和数据线是否原装、充电时长、电量变化、是否发热、是否更换充电器后仍存在。
2. 商品照片通常只能证明外观，不能直接证明充电慢。
3. 只有电量截图或商品照片时，AI不应自动建议通过，应引导补充视频或转人工。
4. 描述清楚且订单允许售后时，可以创建待审核售后单，由人工结合检测或证据确认。$$,
'phone', 'quality_issue', 'refund', 'v1.0', 1),

('after_sales_policy', 'quality_phone_power_reboot_001', 'MERCHANT_DEMO', '手机无法开机或频繁重启售后规则',
$$适用场景：手机无法开机、频繁重启、死机、黑屏、闪屏、系统严重卡顿。
处理规则：
1. 用户应描述异常出现时间、是否充电后仍无法开机、是否摔落进水、是否系统更新后出现。
2. 可要求补充故障视频或开机失败画面。
3. 静态照片通常无法确认功能异常。
4. 符合售后时效且描述具体时，可以创建待审核售后单；无法判断时转人工。$$,
'phone', 'quality_issue', 'refund', 'v1.0', 1),

('after_sales_policy', 'quality_battery_life_001', 'MERCHANT_DEMO', '电池续航异常售后规则',
$$适用场景：手机、耳机、数码设备续航明显不足、掉电快、耗电异常、电池充不满。
处理规则：
1. 用户需要提供使用时长、耗电速度、充满电比例、是否开启高耗电功能等描述。
2. 建议补充电量变化截图或视频。
3. 图片不能直接证明电池质量问题。
4. 新品在售后时效内且描述具体，可以创建待审核申请；是否通过需人工或检测确认。$$,
'digital', 'quality_issue', 'refund', 'v1.0', 1),

('scene_evidence', 'quality_function_evidence_001', 'MERCHANT_DEMO', '功能类质量问题证据要求',
$$功能类质量问题包括充电慢、无法开机、电流声、蓝牙断连、按键失灵、触控异常、续航差等。
必要信息：
1. 具体故障描述，说明何时出现、出现频率、持续时间。
2. 商品整体照片，用于确认商品主体和外观状态。
建议补充：
1. 故障视频、录音、截图或检测结果。
2. 充电、连接、开机类问题可补充操作过程视频。
判断边界：静态图片无法证明功能异常时，不进入自动建议通过；图片与描述无法核验时转人工。$$,
'digital', 'quality_issue', 'evidence_requirement', 'v1.0', 1),

('after_sales_policy', 'wrong_item_policy_001', 'MERCHANT_DEMO', '错发商品售后规则',
$$适用场景：用户收到的商品型号、颜色、规格、数量与订单不一致。
处理规则：
1. 用户应提供实收商品照片、订单商品信息截图或描述、外包装和物流面单照片。
2. 确认错发后优先支持换货或补发正确商品；用户不接受时可协商退货退款。
3. 仅凭文字描述无法确认错发时，应引导上传实收商品照片和订单商品对比信息。
4. 图片无法确认商品或与订单不匹配时，转人工复核。$$,
'general', 'wrong_item', 'exchange', 'v1.0', 1),

('after_sales_policy', 'missing_item_reissue_001', 'MERCHANT_DEMO', '少发漏发补发规则',
$$适用场景：用户反馈少发、漏发、缺少配件、包装内没有某个商品或配件。
处理规则：
1. 用户需要提供实收商品整体照片、包装内物品照片、外包装照片。
2. 涉及配件缺失时，需要说明缺少的配件名称和数量。
3. 核实少发漏发后优先补发；补发不可行时可按缺失部分协商退款。
4. 无照片或无法确认缺件时，先引导补充材料或转人工。$$,
'general', 'missing_item', 'reissue', 'v1.0', 1),

('scene_evidence', 'wrong_missing_evidence_001', 'MERCHANT_DEMO', '错发少发证据要求',
$$错发少发类证据要求：
1. 实收商品照片，能看清商品、颜色、规格和数量。
2. 外包装照片和物流面单照片，用于确认包裹来源。
3. 订单中应收到的商品或配件说明。
4. 如果是缺配件，需要拍摄包装盒内所有物品。
材料齐全后可以创建待审核售后单；图片不能确认数量或规格时转人工。$$,
'general', 'wrong_or_missing_items', 'evidence_requirement', 'v1.0', 1),

('after_sales_policy', 'logistics_signed_not_received_001', 'MERCHANT_DEMO', '显示签收但未收到处理规则',
$$适用场景：物流显示已签收，但用户表示没有收到商品。
处理规则：
1. 先查询订单物流状态和签收时间。
2. 引导用户确认收件地址、门卫、驿站、家人代收情况。
3. 需要物流面单或物流轨迹作为核验依据。
4. 此类责任需要物流侧核实，AI不应直接建议退款通过，应转人工或发起物流核查。
5. 确认丢件后，可按商家规则补发或退款。$$,
'general', 'logistics_issue', 'refund_or_reissue', 'v1.0', 1),

('after_sales_policy', 'package_damage_only_001', 'MERCHANT_DEMO', '外包装破损但商品完好规则',
$$适用场景：用户反馈外包装破损、盒子压坏、包装变形，但商品本体暂时无明显问题。
处理规则：
1. 需要外包装照片和商品本体照片。
2. 商品本体完好且不影响使用时，通常不直接支持退货退款，可根据政策补偿或人工协商。
3. 外包装破损伴随商品破损时，按商品破损规则处理。
4. 仅凭外包装破损无法自动建议退款通过，需要人工确认影响程度。$$,
'general', 'package_damage', 'compensation_or_review', 'v1.0', 1),

('after_sales_policy', 'refund_only_boundary_001', 'MERCHANT_DEMO', '仅退款适用边界',
$$仅退款适用场景：
1. 商品未发货或订单取消。
2. 物流丢件、长时间未收到且核实无法送达。
3. 少发漏发且只退缺失部分金额。
4. 商品无需退回且商家确认可退款的特殊场景。
不适用场景：已收到完整商品且要求全额退款，通常应走退货退款；证据不足时不自动建议仅退款通过。$$,
'general', 'refund_only', 'refund', 'v1.0', 1),

('after_sales_policy', 'return_shipping_fee_001', 'MERCHANT_DEMO', '退货运费承担规则',
$$退货运费承担规则：
1. 质量问题、错发、少发、商品破损且经核实属商家或物流责任的，退货运费通常由商家承担。
2. 7天无理由、个人不喜欢、拍错规格等非质量原因，运费通常由买家承担。
3. 争议场景需人工结合订单、商品类目、物流证据判断。
4. AI回复时应说明以最终审核结果为准，不承诺具体赔付金额。$$,
'general', 'return_shipping', 'policy_explanation', 'v1.0', 1),

('faq', 'faq_refund_arrival_time_001', 'MERCHANT_DEMO', '退款多久到账',
$$退款到账时效说明：
1. 审核通过后，退款通常原路返回。
2. 支付渠道处理一般需要1到5个工作日。
3. 退货退款通常需要商家收到退回商品并确认无误后再退款。
4. 超过预计时效仍未到账，可转人工查询支付渠道或订单退款状态。$$,
'general', 'refund_progress', 'policy_explanation', 'v1.0', 1),

('faq', 'faq_after_sales_progress_001', 'MERCHANT_DEMO', '售后审核多久有结果',
$$售后审核进度说明：
1. 资料齐全的售后申请通常会优先处理。
2. 需要人工复核的场景，例如功能异常、图片无法判断、物流争议、责任不清，通常需要客服进一步核实。
3. 用户可在售后进度入口查看当前状态。
4. 用户多次催促、情绪强烈或超过承诺时效时，应转人工跟进。$$,
'general', 'progress_query', 'policy_explanation', 'v1.0', 1),

('reply_template', 'template_request_function_detail_001', 'MERCHANT_DEMO', '功能异常补充描述话术',
$$当用户只说质量问题、充电慢、电流声、无法开机等但描述不足时，可回复：
为了继续判断售后规则，请补充具体异常现象，例如出现时间、持续多久、是否更换充电器或设备后仍存在。如果方便，也可以上传一段故障视频或截图。$$,
'general', 'quality_issue', 'ask_missing_evidence', 'v1.0', 1),

('reply_template', 'template_request_damage_photo_001', 'MERCHANT_DEMO', '破损照片补充话术',
$$当用户描述商品破损但未上传清晰破损照片时，可回复：
已了解您的问题。为了继续判断售后规则，请上传一张能清楚看到破损位置和商品主体的照片；如果是刚签收发现破损，也建议补充外包装照片和物流面单照片。$$,
'general', 'damage', 'ask_missing_evidence', 'v1.0', 1),

('guideline', 'human_handoff_boundary_002', 'MERCHANT_DEMO', '售后自动转人工边界',
$$以下情况应自动转人工：
1. 功能类质量问题上传的图片无法核验问题现象。
2. 图片与用户描述不一致。
3. 图片模糊、只拍局部、无法确认商品主体。
4. 涉及物流丢件、签收争议、运费争议、赔付金额争议。
5. 用户明确要求转人工，或多轮补充后仍无法判断。
6. 知识库没有命中明确政策或证据规则。$$,
'general', 'human_handoff', 'guardrail', 'v1.0', 1),

('guideline', 'completion_review_invite_001', 'MERCHANT_DEMO', '售后完成后评价邀请规则',
$$售后单最终完成后，系统应自动发送评价邀请。
触发条件：
1. 售后状态进入已完成。
2. 人工最终处理完成退款、换货、补发或拒绝。
3. 同一售后单不重复发送评价邀请。
话术应简短，不影响用户继续查看售后进度。$$,
'general', 'completion', 'review_invitation', 'v1.0', 1),

('guideline', 'ai_review_boundary_001', 'MERCHANT_DEMO', 'AI售后初审边界',
$$AI售后初审边界：
1. AI必须先命中知识库政策或证据规则，再给出初审建议。
2. 用户提交售后申请后，Java业务层创建的售后单初始状态必须是待审核。
3. 证据充分、政策命中、订单允许售后时，AI只能给出建议通过及原因，并推动状态进入处理中等待人工最终处理。
4. 证据不足时，AI应说明缺少的材料。
5. 图片和描述不一致、无法判断责任、疑似人为损坏、模型无法判断时，必须转人工。$$,
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
