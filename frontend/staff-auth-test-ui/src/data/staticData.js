export const orderRecords = [
  {
    id: 'ORD202606250018',
    user: '王晓雪',
    phone: '138****2218',
    product: '便携榨汁杯',
    amount: '¥128.00',
    status: '已支付',
    logistics: '退款审核中',
    relatedTicketId: 201
  },
  {
    id: 'ORD202606240033',
    user: '陈志远',
    phone: '136****8012',
    product: '智能恒温杯',
    amount: '¥239.00',
    status: '换货中',
    logistics: '物流节点异常',
    relatedTicketId: 202
  },
  {
    id: 'ORD202606230071',
    user: '李倩',
    phone: '137****4421',
    product: '无线耳机',
    amount: '¥399.00',
    status: '已完成',
    logistics: '已签收',
    relatedTicketId: null
  },
  {
    id: 'ORD202606230088',
    user: '周航',
    phone: '135****9001',
    product: '空气炸锅',
    amount: '¥329.00',
    status: '已支付',
    logistics: '退款审核中',
    relatedTicketId: 4
  },
  {
    id: 'ORD202606220114',
    user: '林雨晴',
    phone: '139****6720',
    product: '蓝牙音箱',
    amount: '¥189.00',
    status: '已完成',
    logistics: '物流节点异常',
    relatedTicketId: 5
  },
  {
    id: 'ORD202606220126',
    user: '孙浩',
    phone: '132****5088',
    product: '运动手环',
    amount: '¥259.00',
    status: '换货中',
    logistics: '换货寄回待签收',
    relatedTicketId: 6
  },
  {
    id: 'ORD202606210042',
    user: '何静',
    phone: '150****3176',
    product: '电动牙刷',
    amount: '¥169.00',
    status: '已完成',
    logistics: '已签收',
    relatedTicketId: null
  },
  {
    id: 'ORD202606210079',
    user: '吴越',
    phone: '188****2465',
    product: '智能台灯',
    amount: '¥219.00',
    status: '已支付',
    logistics: '退款审核中',
    relatedTicketId: 7
  },
  {
    id: 'ORD202606200156',
    user: '郑楠',
    phone: '186****7342',
    product: '机械键盘',
    amount: '¥459.00',
    status: '换货中',
    logistics: '物流节点异常',
    relatedTicketId: 8
  },
  {
    id: 'ORD202606200178',
    user: '冯乐',
    phone: '131****8840',
    product: '便携投影仪',
    amount: '¥1299.00',
    status: '已支付',
    logistics: '退款审核中',
    relatedTicketId: 9
  },
  {
    id: 'ORD202606190063',
    user: '唐敏',
    phone: '177****5209',
    product: '护眼显示器',
    amount: '¥899.00',
    status: '已完成',
    logistics: '已签收',
    relatedTicketId: null
  },
  {
    id: 'ORD202606190096',
    user: '罗晨',
    phone: '133****6541',
    product: '无线充电器',
    amount: '¥99.00',
    status: '已支付',
    logistics: '退款审核中',
    relatedTicketId: 10
  },
  {
    id: 'ORD202606180137',
    user: '许诺',
    phone: '180****4096',
    product: '扫地机器人',
    amount: '¥1599.00',
    status: '换货中',
    logistics: '物流节点异常',
    relatedTicketId: 11
  },
  {
    id: 'ORD202606180152',
    user: '高琳',
    phone: '158****7733',
    product: '咖啡机',
    amount: '¥699.00',
    status: '已完成',
    logistics: '已签收',
    relatedTicketId: null
  }
];

export const noticeRules = [
  { id: 1, level: '高', title: '退款申请即将超时', desc: 'TK20260625018 距离 SLA 截止还有 15 分钟', target: '/tickets/201' },
  { id: 2, level: '中', title: '会话情绪升级', desc: 'CS20260625007 出现连续负向表达', target: '/sessions/101' },
  { id: 3, level: '低', title: '评价复核待处理', desc: '差评申诉 RV20260625003 需要客服确认', target: '/notices' }
];
