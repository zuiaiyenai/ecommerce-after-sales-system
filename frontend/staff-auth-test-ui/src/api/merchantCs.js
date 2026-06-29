const USE_REAL_API = import.meta.env.VITE_USE_REAL_API === 'true';
const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8080';
const TOKEN_KEY = 'merchant_cs_token';
const EVALUATION_TIMEOUT_MS = 30 * 60 * 1000;

let token = localStorage.getItem(TOKEN_KEY) || '';

let staffProfile = {
  staffId: 1,
  staffNo: 'CS0001',
  merchantCode: 'MERCHANT_DEMO',
  account: 'cs_demo',
  realName: '林真',
  role: 'CUSTOMER_SERVICE',
  onlineStatus: 'ONLINE',
  maxSessionCount: 8
};

const overview = {
  greeting: '早上好，林真',
  todayTodoCount: 35,
  aiEnabled: true,
  metrics: [
    { title: '待接入会话', value: 18, trend: '+6', accent: 'orange' },
    { title: '待审核工单', value: 12, trend: '+2', accent: 'slate' },
    { title: '超时预警', value: 5, trend: '-1', accent: 'green' }
  ],
  timeline: [
    { time: '09:20', title: '系统分配新会话 6 个', type: 'normal' },
    { time: '09:35', title: '工单 TK20260625011 触发 SLA 预警', type: 'warn' },
    { time: '09:50', title: '退款审核队列已完成自动优先级排序', type: 'normal' }
  ]
};

const todos = [
  { id: 1, target: '/tickets/201', title: '售后工单 #TK20260625018', tag: '退款审核', amount: '128.00 元', priority: '高', priorityTone: 'high', action: '审核' },
  { id: 2, target: '/sessions/101', title: '会话 #CS20260625007', tag: '人工介入', amount: '情绪升级', priority: '高', priorityTone: 'high', action: '接入' },
  { id: 3, target: '/notices', title: '评价复核 #RV20260625003', tag: '差评申诉', amount: '1 条', priority: '中', priorityTone: 'medium', action: '复核' },
  { id: 4, target: '/notices', title: '服务预警确认', tag: '系统提醒', amount: '4 条', priority: '低', priorityTone: 'normal', action: '确认' }
];

const performance = {
  metrics: [
    { label: '30 秒响应率', value: '92%', desc: '目标 90%', currentPercent: 92, targetPercent: 90 },
    { label: '一次解决率', value: '68%', desc: '目标 70%', currentPercent: 68, targetPercent: 70 },
    { label: '平均处理时长', value: '06:24', desc: '目标 08:00', currentPercent: 80, targetPercent: 100 }
  ]
};

let sessions = [
  {
    id: 101,
    sessionNo: 'CS20260625007',
    user: '王晓雪',
    topic: '退款进度咨询',
    level: '高优先级',
    wait: '等待 02:13',
    emotion: '情绪预警',
    sourceChannel: '小程序咨询',
    status: 'PROCESSING',
    orderNo: 'ORD202606250018',
    product: '便携榨汁杯',
    productName: '便携榨汁杯',
    ticketNo: 'TK20260625018',
    lastMessageContent: '我的退款什么时候能到账？',
    aiSummary: '用户关注退款到账时间，情绪偏急，需要先核对退款审核状态并给出明确时效。',
    evaluationStatus: null
  },
  {
    id: 102,
    sessionNo: 'CS20260625008',
    user: '陈志远',
    topic: '换货物流异常',
    level: '待用户评价',
    wait: '等待评价',
    emotion: '可安抚',
    sourceChannel: '网页客服',
    status: 'AWAITING_EVALUATION',
    orderNo: 'ORD202606240033',
    product: '智能恒温杯',
    productName: '智能恒温杯',
    ticketNo: 'TK20260625019',
    lastMessageContent: '已发送服务评价邀请，等待用户评价。',
    aiSummary: '用户反馈换货物流停滞，建议核对物流轨迹并承诺同步处理结果。',
    evaluationRequestedAt: minutesAgo(10),
    evaluationStatus: 'REQUESTED'
  },
  {
    id: 103,
    sessionNo: 'CS20260625009',
    user: '李倩',
    topic: '商品质量咨询',
    level: '待用户评价',
    wait: '等待评价',
    emotion: 'AI 可接管',
    sourceChannel: '公众号',
    status: 'AWAITING_EVALUATION',
    orderNo: 'ORD202606230071',
    product: '无线耳机',
    productName: '无线耳机',
    ticketNo: '',
    lastMessageContent: '已发送服务评价邀请，等待用户评价。',
    aiSummary: '用户询问质保范围，建议先确认购买时间和故障表现，再引用售后政策。',
    evaluationRequestedAt: minutesAgo(35),
    evaluationStatus: 'REQUESTED'
  },
  {
    id: 104,
    sessionNo: 'CS20260625010',
    user: '周语',
    topic: '优惠券使用说明',
    level: '已完成',
    wait: '已完成评价',
    emotion: '评价完成',
    sourceChannel: 'APP',
    status: 'RESOLVED',
    orderNo: 'ORD202606220018',
    product: '轻音降噪耳机 Pro',
    productName: '轻音降噪耳机 Pro',
    ticketNo: '',
    lastMessageContent: '用户已完成服务评价',
    aiSummary: '用户问题已解决并完成评价。',
    evaluationRequestedAt: minutesAgo(50),
    evaluatedAt: minutesAgo(45),
    rating: 5,
    evaluationStatus: 'SUBMITTED'
  },
  {
    id: 105,
    sessionNo: 'CS20260625011',
    user: '周航',
    topic: '空气炸锅退款资料确认',
    level: '高优先级',
    wait: '等待 04:18',
    emotion: '焦虑',
    sourceChannel: '小程序咨询',
    status: 'WAITING',
    orderNo: 'ORD202606230088',
    product: '空气炸锅',
    productName: '空气炸锅',
    ticketNo: 'TK20260625021',
    lastMessageContent: '我已经上传照片了，还需要补什么？',
    aiSummary: '用户询问退款凭证要求，建议核对照片是否覆盖商品外观、故障点和订单信息。',
    evaluationStatus: null
  },
  {
    id: 106,
    sessionNo: 'CS20260625012',
    user: '林雨晴',
    topic: '音箱退货物流',
    level: '普通优先级',
    wait: '等待 01:46',
    emotion: '可安抚',
    sourceChannel: '网页客服',
    status: 'PROCESSING',
    orderNo: 'ORD202606220114',
    product: '蓝牙音箱',
    productName: '蓝牙音箱',
    ticketNo: 'TK20260625022',
    lastMessageContent: '退回件已经签收，退款什么时候处理？',
    aiSummary: '用户关注仓库验收后的退款时效，需要同步售后状态。',
    evaluationStatus: null
  },
  {
    id: 107,
    sessionNo: 'CS20260625013',
    user: '孙浩',
    topic: '手环换货进度',
    level: '高优先级',
    wait: '等待 06:02',
    emotion: '不满',
    sourceChannel: 'APP',
    status: 'PROCESSING',
    orderNo: 'ORD202606220126',
    product: '运动手环',
    productName: '运动手环',
    ticketNo: 'TK20260625023',
    lastMessageContent: '已经等了两天，换货单还没更新。',
    aiSummary: '用户等待时间较长，建议先说明当前节点并承诺跟进时点。',
    evaluationStatus: null
  },
  {
    id: 108,
    sessionNo: 'CS20260625014',
    user: '吴越',
    topic: '智能台灯少件',
    level: '待补充',
    wait: '等待资料',
    emotion: '中性',
    sourceChannel: '公众号',
    status: 'AWAITING_EVALUATION',
    orderNo: 'ORD202606210079',
    product: '智能台灯',
    productName: '智能台灯',
    ticketNo: 'TK20260625024',
    lastMessageContent: '已发送服务评价邀请，等待用户评价。',
    aiSummary: '已告知用户补充配件照片和外包装照片。',
    evaluationRequestedAt: minutesAgo(12),
    evaluationStatus: 'REQUESTED'
  },
  {
    id: 109,
    sessionNo: 'CS20260625015',
    user: '郑楠',
    topic: '机械键盘按键异常',
    level: '待客服关闭',
    wait: '评价超时',
    emotion: '中性',
    sourceChannel: '小程序咨询',
    status: 'READY_TO_CLOSE',
    orderNo: 'ORD202606200156',
    product: '机械键盘',
    productName: '机械键盘',
    ticketNo: 'TK20260625025',
    lastMessageContent: '用户 30 分钟内未完成评价，客服可关闭该会话。',
    aiSummary: '客服已完成换货说明，用户未评价。',
    evaluationRequestedAt: minutesAgo(50),
    evaluationStatus: 'TIMEOUT'
  },
  {
    id: 110,
    sessionNo: 'CS20260625016',
    user: '冯乐',
    topic: '投影仪退款申诉',
    level: '高优先级',
    wait: '等待 07:35',
    emotion: '情绪预警',
    sourceChannel: '网页客服',
    status: 'WAITING',
    orderNo: 'ORD202606200178',
    product: '便携投影仪',
    productName: '便携投影仪',
    ticketNo: 'TK20260625026',
    lastMessageContent: '为什么我的退款申请被驳回？',
    aiSummary: '用户对驳回原因不满，需要解释售后时效和证据要求。',
    evaluationStatus: null
  },
  {
    id: 111,
    sessionNo: 'CS20260625017',
    user: '罗晨',
    topic: '无线充电器未发货退款',
    level: '普通优先级',
    wait: '等待 00:52',
    emotion: '中性',
    sourceChannel: 'APP',
    status: 'PROCESSING',
    orderNo: 'ORD202606190096',
    product: '无线充电器',
    productName: '无线充电器',
    ticketNo: 'TK20260625027',
    lastMessageContent: '订单还没发货，我想直接退款。',
    aiSummary: '未发货退款诉求，可核对发货状态后引导提交仅退款。',
    evaluationStatus: null
  },
  {
    id: 112,
    sessionNo: 'CS20260625018',
    user: '许诺',
    topic: '扫地机器人换货',
    level: '高优先级',
    wait: '等待 03:24',
    emotion: '可安抚',
    sourceChannel: '小程序咨询',
    status: 'PROCESSING',
    orderNo: 'ORD202606180137',
    product: '扫地机器人',
    productName: '扫地机器人',
    ticketNo: 'TK20260625028',
    lastMessageContent: '检测件什么时候补发？',
    aiSummary: '用户关注换货补发时间，需要同步仓库处理计划。',
    evaluationStatus: null
  },
  {
    id: 113,
    sessionNo: 'CS20260625019',
    user: '高琳',
    topic: '咖啡机退货说明',
    level: '待用户评价',
    wait: '等待评价',
    emotion: '评价邀请',
    sourceChannel: '公众号',
    status: 'AWAITING_EVALUATION',
    orderNo: 'ORD202606180152',
    product: '咖啡机',
    productName: '咖啡机',
    ticketNo: 'TK20260625029',
    lastMessageContent: '已发送服务评价邀请，等待用户评价。',
    aiSummary: '已说明退货包装要求和退款预计时效。',
    evaluationRequestedAt: minutesAgo(5),
    evaluationStatus: 'REQUESTED'
  },
  {
    id: 114,
    sessionNo: 'CS20260625020',
    user: '唐敏',
    topic: '显示器质保咨询',
    level: '已完成',
    wait: '已完成评价',
    emotion: '评价完成',
    sourceChannel: 'APP',
    status: 'RESOLVED',
    orderNo: 'ORD202606190063',
    product: '护眼显示器',
    productName: '护眼显示器',
    ticketNo: '',
    lastMessageContent: '用户已完成服务评价',
    aiSummary: '用户确认质保范围后完成评价。',
    evaluationRequestedAt: minutesAgo(80),
    evaluatedAt: minutesAgo(76),
    rating: 5,
    evaluationStatus: 'SUBMITTED'
  }
];

const messagesBySession = {
  101: [
    { id: 1, sessionId: 101, senderRole: 'USER', messageType: 'TEXT', content: '我的退款什么时候能到账？' },
    { id: 2, sessionId: 101, senderRole: 'SERVICE', messageType: 'TEXT', content: '您好，我已经帮您核对退款进度。' }
  ],
  102: [
    { id: 3, sessionId: 102, senderRole: 'USER', messageType: 'TEXT', content: '换货包裹三天没有更新了。' },
    { id: 4, sessionId: 102, senderRole: 'SERVICE', messageType: 'TEXT', content: '我会帮您联系物流核实，并同步处理结果。' }
  ],
  103: [
    { id: 5, sessionId: 103, senderRole: 'USER', messageType: 'TEXT', content: '这个问题属于质保范围吗？' }
  ],
  104: [
    { id: 6, sessionId: 104, senderRole: 'USER', messageType: 'TEXT', content: '优惠券为什么不能使用？' },
    { id: 7, sessionId: 104, senderRole: 'SERVICE', messageType: 'TEXT', content: '这张券仅限满 299 元订单使用，当前订单金额不足。' }
  ]
};

let tickets = [
  { id: 201, ticketNo: 'TK20260625018', title: '退款审核', status: 'PENDING_REVIEW', afterSalesType: 'REFUND', applyRefundAmount: '128.00', priority: 'HIGH' },
  { id: 202, ticketNo: 'TK20260625019', title: '换货物流异常', status: 'PROCESSING', afterSalesType: 'EXCHANGE', applyRefundAmount: '0.00', priority: 'NORMAL' },
  { id: 203, ticketNo: 'TK20260625020', title: '少件补发申请', status: 'PENDING_REVIEW', afterSalesType: 'RESEND', applyRefundAmount: '0.00', priority: 'NORMAL' },
  { id: 204, ticketNo: 'TK20260625021', title: '空气炸锅仅退款审核', status: 'PENDING_REVIEW', afterSalesType: 'REFUND', applyRefundAmount: '329.00', priority: 'HIGH' },
  { id: 205, ticketNo: 'TK20260625022', title: '蓝牙音箱退货退款', status: 'PROCESSING', afterSalesType: 'REFUND', applyRefundAmount: '189.00', priority: 'NORMAL' },
  { id: 206, ticketNo: 'TK20260625023', title: '运动手环换货审核', status: 'PENDING_REVIEW', afterSalesType: 'EXCHANGE', applyRefundAmount: '0.00', priority: 'NORMAL' },
  { id: 207, ticketNo: 'TK20260625024', title: '智能台灯补充资料', status: 'PROCESSING', afterSalesType: 'RESEND', applyRefundAmount: '0.00', priority: 'HIGH' },
  { id: 208, ticketNo: 'TK20260625025', title: '机械键盘换货处理', status: 'PROCESSING', afterSalesType: 'EXCHANGE', applyRefundAmount: '0.00', priority: 'HIGH' },
  { id: 209, ticketNo: 'TK20260625026', title: '投影仪退款驳回', status: 'REJECTED', afterSalesType: 'REFUND', applyRefundAmount: '1299.00', priority: 'NORMAL' },
  { id: 210, ticketNo: 'TK20260625027', title: '无线充电器退款审核', status: 'PENDING_REVIEW', afterSalesType: 'REFUND', applyRefundAmount: '99.00', priority: 'NORMAL' },
  { id: 211, ticketNo: 'TK20260625028', title: '扫地机器人换货处理', status: 'PROCESSING', afterSalesType: 'EXCHANGE', applyRefundAmount: '0.00', priority: 'HIGH' },
  { id: 212, ticketNo: 'TK20260625029', title: '咖啡机退货退款审核', status: 'PENDING_REVIEW', afterSalesType: 'REFUND', applyRefundAmount: '699.00', priority: 'HIGH' },
  { id: 213, ticketNo: 'TK20260625030', title: '显示器售后复核驳回', status: 'REJECTED', afterSalesType: 'REFUND', applyRefundAmount: '899.00', priority: 'NORMAL' }
];

const ticketLogs = {
  201: [
    { id: 1, ticketId: 201, actionType: 'CREATE', actionDesc: '用户提交售后申请' },
    { id: 2, ticketId: 201, actionType: 'ASSIGN', actionDesc: '系统分配至客服林真' }
  ],
  202: [
    { id: 3, ticketId: 202, actionType: 'CREATE', actionDesc: '用户提交换货申请' },
    { id: 4, ticketId: 202, actionType: 'LOGISTICS_CHECK', actionDesc: '等待物流节点更新' }
  ]
};

function delay(data, ms = 140) {
  return new Promise((resolve) => {
    window.setTimeout(() => resolve(structuredClone(data)), ms);
  });
}

function formatTime(date) {
  const pad = (value) => String(value).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function minutesAgo(minutes) {
  return formatTime(new Date(Date.now() - minutes * 60 * 1000));
}

function normalizeEvaluationTimeout(session) {
  if (
    session?.status !== 'AWAITING_EVALUATION' ||
    !session.evaluationRequestedAt ||
    session.evaluatedAt
  ) {
    return session;
  }
  const requestedAt = new Date(session.evaluationRequestedAt.replace(' ', 'T')).getTime();
  if (!Number.isFinite(requestedAt) || Date.now() - requestedAt < EVALUATION_TIMEOUT_MS) {
    return session;
  }
  return {
    ...session,
    status: 'READY_TO_CLOSE',
    level: '待客服关闭',
    wait: '评价超时',
    lastMessageContent: '用户 30 分钟内未完成评价，客服可关闭该会话。',
    lastMessageTime: formatTime(new Date()),
    evaluationStatus: 'TIMEOUT'
  };
}

function normalizeSessions() {
  sessions = sessions.map(normalizeEvaluationTimeout);
}

async function request(path, options = {}) {
  const response = await fetch(`${BASE_URL}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    },
    ...options
  });
  const payload = await response.json();
  if (!response.ok || payload.success === false) {
    throw new Error(payload.message || '接口请求失败');
  }
  return payload.data;
}

function saveToken(nextToken) {
  token = nextToken;
  localStorage.setItem(TOKEN_KEY, nextToken);
}

export function hasToken() {
  return Boolean(token);
}

export async function login(credentials) {
  if (USE_REAL_API) {
    const data = await request('/api/merchant-cs/auth/login', {
      method: 'POST',
      body: JSON.stringify(credentials)
    });
    saveToken(data.token);
    staffProfile = data.staff;
    return data;
  }

  if (credentials.account !== 'cs_demo' || credentials.password !== '123456') {
    throw new Error('账号或密码错误，测试账号为 cs_demo / 123456');
  }

  const data = {
    token: `mock-token-${Date.now()}`,
    staff: staffProfile
  };
  saveToken(data.token);
  return delay(data);
}

export async function logout() {
  if (USE_REAL_API) {
    await request('/api/merchant-cs/auth/logout', { method: 'POST' });
  }
  token = '';
  localStorage.removeItem(TOKEN_KEY);
}

export async function getCurrentStaff() {
  if (USE_REAL_API) {
    return request('/api/merchant-cs/auth/me');
  }
  return delay(staffProfile);
}

export async function updateWorkStatus(onlineStatus) {
  if (USE_REAL_API) {
    const data = await request('/api/merchant-cs/work-status', {
      method: 'PUT',
      body: JSON.stringify({ onlineStatus })
    });
    staffProfile = data;
    return data;
  }
  staffProfile = { ...staffProfile, onlineStatus };
  return delay(staffProfile);
}

export function getDashboardOverview() {
  return USE_REAL_API ? request('/api/merchant-cs/dashboard/overview') : delay(overview);
}

export function getDashboardTodos() {
  return USE_REAL_API ? request('/api/merchant-cs/dashboard/todos') : delay(todos);
}

export function getDashboardPerformance() {
  return USE_REAL_API ? request('/api/merchant-cs/dashboard/performance') : delay(performance);
}

export function getSessions() {
  if (USE_REAL_API) {
    return request('/api/merchant-cs/sessions');
  }
  normalizeSessions();
  return delay({ records: sessions, total: sessions.length });
}

export async function getSession(sessionId) {
  if (USE_REAL_API) {
    return request(`/api/merchant-cs/sessions/${sessionId}`);
  }
  normalizeSessions();
  return delay(sessions.find((item) => item.id === Number(sessionId)));
}

export function getSessionMessages(sessionId) {
  if (USE_REAL_API) {
    return request(`/api/merchant-cs/sessions/${sessionId}/messages`);
  }
  return delay(messagesBySession[Number(sessionId)] || []);
}

export async function sendSessionMessage(sessionId, content) {
  if (USE_REAL_API) {
    return request(`/api/merchant-cs/sessions/${sessionId}/messages`, {
      method: 'POST',
      body: JSON.stringify({ messageType: 'TEXT', content })
    });
  }
  const message = { id: Date.now(), sessionId: Number(sessionId), senderRole: 'SERVICE', messageType: 'TEXT', content };
  messagesBySession[Number(sessionId)] = [...(messagesBySession[Number(sessionId)] || []), message];
  sessions = sessions.map((item) => (
    item.id === Number(sessionId)
      ? { ...item, lastMessageContent: content, status: item.status === 'WAITING' ? 'PROCESSING' : item.status }
      : item
  ));
  return delay(message);
}

export async function requestSessionEvaluation(sessionId) {
  if (USE_REAL_API) {
    return request(`/api/merchant-cs/sessions/${sessionId}/evaluation-request`, { method: 'POST' });
  }
  const now = formatTime(new Date());
  sessions = sessions.map((item) => (
    item.id === Number(sessionId)
      ? {
          ...item,
          status: 'AWAITING_EVALUATION',
          level: '待用户评价',
          wait: '等待评价',
          lastMessageContent: '已发送服务评价邀请，等待用户在 30 分钟内完成评价。',
          lastMessageTime: now,
          evaluationRequestedAt: now,
          evaluatedAt: null,
          rating: null,
          evaluationStatus: 'REQUESTED'
        }
      : item
  ));
  return delay(sessions.find((item) => item.id === Number(sessionId)));
}

export async function submitSessionEvaluation(sessionId, rating = 5, content = '用户已完成服务评价') {
  if (USE_REAL_API) {
    return request(`/api/merchant-cs/sessions/${sessionId}/evaluation`, {
      method: 'POST',
      body: JSON.stringify({ rating, content })
    });
  }
  const now = formatTime(new Date());
  sessions = sessions.map((item) => (
    item.id === Number(sessionId)
      ? {
          ...item,
          status: 'RESOLVED',
          level: '已完成',
          wait: '已完成评价',
          emotion: '评价完成',
          lastMessageContent: content,
          lastMessageTime: now,
          evaluatedAt: now,
          rating,
          evaluationStatus: 'SUBMITTED'
        }
      : item
  ));
  return delay(sessions.find((item) => item.id === Number(sessionId)));
}

export async function closeSession(sessionId) {
  if (USE_REAL_API) {
    return request(`/api/merchant-cs/sessions/${sessionId}/close`, { method: 'POST' });
  }
  normalizeSessions();
  const target = sessions.find((item) => item.id === Number(sessionId));
  if (target?.status !== 'READY_TO_CLOSE') {
    throw new Error('只有待客服关闭状态的会话可以关闭');
  }
  sessions = sessions.map((item) => (item.id === Number(sessionId) ? { ...item, status: 'CLOSED', level: '已完成', evaluationStatus: 'CLOSED' } : item));
  return delay(sessions.find((item) => item.id === Number(sessionId)));
}

export function getTickets() {
  return USE_REAL_API ? request('/api/merchant-cs/tickets') : delay({ records: tickets, total: tickets.length });
}

export async function getTicket(ticketId) {
  if (USE_REAL_API) {
    return request(`/api/merchant-cs/tickets/${ticketId}`);
  }
  return delay(tickets.find((item) => item.id === Number(ticketId)));
}

export function getTicketLogs(ticketId) {
  if (USE_REAL_API) {
    return request(`/api/merchant-cs/tickets/${ticketId}/logs`);
  }
  return delay(ticketLogs[Number(ticketId)] || []);
}

export async function approveTicket(ticketId, auditOpinion = '审核通过') {
  if (USE_REAL_API) {
    return request(`/api/merchant-cs/tickets/${ticketId}/approve`, {
      method: 'POST',
      body: JSON.stringify({ auditOpinion })
    });
  }
  tickets = tickets.map((item) => (item.id === Number(ticketId) ? { ...item, status: 'APPROVED' } : item));
  return delay(tickets.find((item) => item.id === Number(ticketId)));
}

export async function rejectTicket(ticketId, rejectReason = '资料不足') {
  if (USE_REAL_API) {
    return request(`/api/merchant-cs/tickets/${ticketId}/reject`, {
      method: 'POST',
      body: JSON.stringify({ rejectReason })
    });
  }
  tickets = tickets.map((item) => (item.id === Number(ticketId) ? { ...item, status: 'REJECTED' } : item));
  return delay(tickets.find((item) => item.id === Number(ticketId)));
}
