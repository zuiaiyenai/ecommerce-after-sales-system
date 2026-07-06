const USE_REAL_API = import.meta.env.VITE_USE_REAL_API === 'true';
const BASE_URL = normalizeBaseUrl(import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8080');
const TOKEN_KEY = 'merchant_cs_token';
const EVALUATION_TIMEOUT_MS = 30 * 60 * 1000;

let token = localStorage.getItem(TOKEN_KEY) || '';

let staffProfile = {
  staffId: null,
  staffNo: '',
  merchantCode: '',
  account: '',
  realName: '',
  role: 'CUSTOMER_SERVICE',
  onlineStatus: 'OFFLINE',
  maxSessionCount: 8
};

let sessions = [
  {
    id: 101,
    sessionNo: 'CS20260705001',
    merchantCode: 'MERCHANT_DEMO',
    userId: 1001,
    orderId: 1,
    ticketId: 201,
    serviceId: 1,
    user: '王晓雪',
    topic: '耳机没有声音，想申请售后',
    level: '高优先级',
    wait: '等待 00:18',
    emotion: '着急',
    emotionLabel: 'ANXIOUS',
    emotionScore: 0.62,
    emotionConfidence: 0.86,
    sourceChannel: '小程序咨询',
    serviceUnreadCount: 0,
    orderNo: 'ORD20260705001',
    product: '蓝牙降噪耳机',
    productName: '蓝牙降噪耳机',
    productImage: '/static/images/product-earphone.png',
    ticketNo: 'TK20260705001',
    lastMessageContent: '这个商品有点问题，我很着急',
    lastMessageTime: minutesAgo(2),
    aiSummary: '用户因质量问题申请售后，情绪偏着急',
    status: 'PROCESSING',
    rating: null,
    evaluationStatus: null
  },
  {
    id: 102,
    sessionNo: 'CS20260705002',
    merchantCode: 'MERCHANT_DEMO',
    userId: 1002,
    orderId: 2,
    ticketId: 202,
    serviceId: 1,
    user: '陈志远',
    topic: '少发了一件，要求补发',
    level: '普通优先级',
    wait: '等待 00:09',
    emotion: '平静',
    emotionLabel: 'CALM',
    emotionScore: 0.22,
    emotionConfidence: 0.81,
    sourceChannel: '小程序咨询',
    serviceUnreadCount: 0,
    orderNo: 'ORD20260705002',
    product: '运动手环',
    productName: '运动手环',
    productImage: '/static/images/product-phone.png',
    ticketNo: 'TK20260705002',
    lastMessageContent: '少发了一件，麻烦补发',
    lastMessageTime: minutesAgo(8),
    aiSummary: '用户因少发问题咨询补发',
    status: 'WAITING',
    rating: null,
    evaluationStatus: null
  }
];

let messagesBySession = {
  101: [
    {
      id: 10001,
      sessionId: 101,
      senderRole: 'USER',
      messageType: 'TEXT',
      content: '你好，我收到耳机后发现没有声音',
      emotionLabel: 'CALM',
      emotionScore: 0.18,
      emotionConfidence: 0.8,
      createdAt: minutesAgo(14)
    },
    {
      id: 10002,
      sessionId: 101,
      senderRole: 'SERVICE',
      messageType: 'TEXT',
      content: '您好，我先帮您确认一下情况，麻烦描述下具体异常表现。',
      emotionLabel: 'CALM',
      emotionScore: 0.18,
      emotionConfidence: 0.8,
      createdAt: minutesAgo(13)
    },
    {
      id: 10003,
      sessionId: 101,
      senderRole: 'USER',
      messageType: 'TEXT',
      content: '我试了几次都没有声音，有点着急',
      emotionLabel: 'ANXIOUS',
      emotionScore: 0.45,
      emotionConfidence: 0.84,
      createdAt: minutesAgo(9)
    },
    {
      id: 10004,
      sessionId: 101,
      senderRole: 'USER',
      messageType: 'TEXT',
      content: '这个商品有点问题，我很着急',
      emotionLabel: 'ANXIOUS',
      emotionScore: 0.62,
      emotionConfidence: 0.86,
      createdAt: minutesAgo(2)
    }
  ],
  102: [
    {
      id: 10005,
      sessionId: 102,
      senderRole: 'USER',
      messageType: 'TEXT',
      content: '少发了一件配件，麻烦帮我补发',
      emotionLabel: 'CALM',
      emotionScore: 0.22,
      emotionConfidence: 0.81,
      createdAt: minutesAgo(8)
    }
  ]
};

let tickets = [
  {
    id: 201,
    ticketNo: 'TK20260705001',
    title: '蓝牙降噪耳机售后申请',
    status: 'PENDING_REVIEW',
    afterSalesType: 'RETURN_REFUND',
    applyRefundAmount: '129.00',
    priority: 'HIGH'
  },
  {
    id: 202,
    ticketNo: 'TK20260705002',
    title: '运动手环少发补发申请',
    status: 'PROCESSING',
    afterSalesType: 'REISSUE',
    applyRefundAmount: '0.00',
    priority: 'NORMAL'
  }
];

const overview = {
  greeting: '早上好，客服',
  subtitle: '当前还有 3 项任务待处理',
  todayTodoCount: 3,
  aiEnabled: true,
  metrics: [],
  timeline: []
};

const todos = [];

const performance = {
  metrics: []
};

function normalizeBaseUrl(url) {
  return url.replace(/\/+$/, '').replace(/\/api$/, '');
}

function buildUrl(path) {
  return `${BASE_URL}${path.startsWith('/') ? path : `/${path}`}`;
}

export function resolveAssetUrl(url) {
  if (!url) {
    return '';
  }
  if (/^(https?:)?\/\//.test(url) || url.startsWith('data:') || url.startsWith('blob:')) {
    return url;
  }
  // Paths returned by the backend's static resource handlers (context-path: /api)
  // need the /api prefix to resolve correctly
  if (url.startsWith('/uploads/') || url.startsWith('/static/')) {
    return buildUrl(`/api${url}`);
  }
  return buildUrl(url);
}

function resolveUploadUrl(payload) {
  const data = payload?.data ?? payload;
  if (typeof data === 'string') {
    return data;
  }
  return data?.url || data?.fileUrl || data?.path || data?.src || '';
}

function saveToken(newToken) {
  token = newToken;
  if (newToken) {
    localStorage.setItem(TOKEN_KEY, newToken);
  } else {
    localStorage.removeItem(TOKEN_KEY);
  }
}

async function request(path, options = {}) {
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {})
  };
  const response = await fetch(buildUrl(path), {
    headers,
    ...options
  });
  const payload = await response.json();
  if (!response.ok || payload.success === false) {
    throw new Error(payload.message || '接口请求失败');
  }
  return payload.data;
}

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
  let changed = false;
  sessions = sessions.map(item => {
    const current = normalizeEvaluationTimeout(item);
    if (current !== item) {
      changed = true;
    }
    return current;
  });
  if (changed) {
    sessionMap = new Map(sessions.map(s => [s.id, s]));
  }
}

// ==================== Auth ====================

export async function login(credentials) {
  if (!USE_REAL_API) {
    if (credentials.account !== 'cs_demo' || credentials.password !== '123456' || credentials.merchantCode !== 'MERCHANT_DEMO') {
      throw new Error('账号或密码错误');
    }
    staffProfile = {
      staffId: 1,
      staffNo: 'CS0001',
      merchantCode: credentials.merchantCode,
      account: credentials.account,
      realName: '林真',
      role: 'CUSTOMER_SERVICE',
      onlineStatus: 'ONLINE',
      maxSessionCount: 8
    };
    saveToken('demo-token');
    return delay({ token: 'demo-token', staff: staffProfile });
  }
  const data = await request('/api/merchant-cs/auth/login', {
    method: 'POST',
    body: JSON.stringify(credentials)
  });
  saveToken(data.token);
  staffProfile = data.staff;
  return data;
}

export async function logout() {
  if (USE_REAL_API) {
    await request('/api/merchant-cs/auth/logout', { method: 'POST' });
  }
  token = '';
  staffProfile = {
    staffId: null,
    staffNo: '',
    merchantCode: '',
    account: '',
    realName: '',
    role: 'CUSTOMER_SERVICE',
    onlineStatus: 'OFFLINE',
    maxSessionCount: 8
  };
  localStorage.removeItem(TOKEN_KEY);
}

export async function getCurrentStaff() {
  if (!USE_REAL_API) {
    return delay(staffProfile);
  }
  const data = await request('/api/merchant-cs/auth/me');
  staffProfile = { ...staffProfile, ...data };
  return data;
}

export async function updateWorkStatus(onlineStatus) {
  if (!USE_REAL_API) {
    staffProfile.onlineStatus = onlineStatus;
    return delay(staffProfile);
  }
  const data = await request('/api/merchant-cs/work-status', {
    method: 'PUT',
    body: JSON.stringify({ onlineStatus })
  });
  staffProfile.onlineStatus = data.onlineStatus;
  return data;
}

// ==================== Dashboard ====================

export async function getDashboardOverview() {
  if (!USE_REAL_API) {
    return delay({
      ...overview,
      greeting: `早上好，${staffProfile.realName || '客服'}`,
      metrics: [
        { title: '待接入会话', value: sessions.filter(s => !['RESOLVED', 'CLOSED'].includes(s.status)).length, trend: '+0', accent: 'orange' },
        { title: '待审核申请', value: tickets.filter(t => t.status === 'PENDING_REVIEW').length, trend: '+0', accent: 'slate' },
        { title: '待处理', value: 0, trend: '+0', accent: 'green' }
      ]
    });
  }
  return request('/api/merchant-cs/dashboard/overview');
}

export async function getDashboardTodos() {
  if (!USE_REAL_API) {
    return delay(todos);
  }
  return request('/api/merchant-cs/dashboard/todos');
}

export async function getDashboardPerformance() {
  if (!USE_REAL_API) {
    return delay(performance);
  }
  return request('/api/merchant-cs/dashboard/performance');
}

// ==================== Sessions ====================

export async function getSessions(params = {}) {
  if (!USE_REAL_API) {
    const current = sessions;
    const filtered = !params.status
      ? current
      : current.filter(s => s.status === params.status);
    const records = filtered.slice(((params.page || 1) - 1) * (params.size || 20), (params.page || 1) * (params.size || 20));
    return delay({ records, total: filtered.length });
  }
  const query = new URLSearchParams();
  if (params.status) query.set('status', params.status);
  if (params.keyword) query.set('keyword', params.keyword);
  query.set('page', params.page || 1);
  query.set('size', params.size || 20);
  return request(`/api/merchant-cs/sessions?${query.toString()}`);
}

export async function getSession(sessionId) {
  if (!USE_REAL_API) {
    const session = sessions.find(s => s.id === sessionId);
    if (!session) throw new Error('会话不存在');
    return delay(session);
  }
  return request(`/api/merchant-cs/sessions/${sessionId}`);
}

export async function getSessionMessages(sessionId) {
  if (!USE_REAL_API) {
    return delay(messagesBySession[sessionId] || []);
  }
  return request(`/api/merchant-cs/sessions/${sessionId}/messages`);
}

let sessionMap = new Map();

export async function sendSessionMessage(sessionId, content) {
  if (!USE_REAL_API) {
    if (!content?.trim()) throw new Error('消息内容不能为空');
    const messages = messagesBySession[sessionId] || [];
    const newMsg = {
      id: Date.now(),
      sessionId,
      senderRole: 'SERVICE',
      messageType: 'TEXT',
      content,
      createdAt: formatTime(new Date())
    };
    messagesBySession[sessionId] = [...messages, newMsg];
    const current = sessions.find(s => s.id === sessionId);
    if (current) {
      current.status = current.status === 'WAITING' ? 'PROCESSING' : current.status;
      current.lastMessageContent = content;
      current.lastMessageTime = newMsg.createdAt;
      if (!sessionMap.has(sessionId)) {
        sessionMap.set(sessionId, { ...current });
      }
    }
    return delay(newMsg);
  }
  return request(`/api/merchant-cs/sessions/${sessionId}/messages`, {
    method: 'POST',
    body: JSON.stringify({ messageType: 'TEXT', content })
  });
}

export async function requestSessionEvaluation(sessionId) {
  if (!USE_REAL_API) {
    const current = sessions.find(s => s.id === sessionId);
    if (current) {
      current.status = 'AWAITING_EVALUATION';
      current.evaluationRequestedAt = formatTime(new Date());
      current.lastMessageContent = '已发送服务评价邀请，等待用户评价。';
      current.lastMessageTime = current.evaluationRequestedAt;
      sessionMap.set(sessionId, { ...current });
    }
    return delay(current || null);
  }
  return request(`/api/merchant-cs/sessions/${sessionId}/evaluation-request`, { method: 'POST' });
}

export async function submitSessionEvaluation(sessionId, rating, content) {
  if (!USE_REAL_API) {
    const current = sessions.find(s => s.id === sessionId);
    if (current) {
      current.status = 'RESOLVED';
      current.rating = rating || 5;
      current.evaluatedAt = formatTime(new Date());
      current.lastMessageContent = content || '用户已完成服务评价';
      current.lastMessageTime = current.evaluatedAt;
      sessionMap.set(sessionId, { ...current });
    }
    return delay(current || null);
  }
  return request(`/api/merchant-cs/sessions/${sessionId}/evaluation`, {
    method: 'POST',
    body: JSON.stringify({ rating, content })
  });
}

export async function closeSession(sessionId) {
  if (!USE_REAL_API) {
    const current = sessions.find(s => s.id === sessionId);
    if (current) {
      current.status = 'CLOSED';
      current.lastMessageContent = '会话已由客服关闭。';
      current.lastMessageTime = formatTime(new Date());
      sessionMap.set(sessionId, { ...current });
    }
    return delay(current || null);
  }
  return request(`/api/merchant-cs/sessions/${sessionId}/close`, { method: 'POST' });
}

// ==================== Tickets ====================

export async function getTickets(params = {}) {
  if (!USE_REAL_API) {
    const current = tickets;
    const filtered = !params.status
      ? current
      : current.filter(t => t.status === params.status);
    const records = filtered.slice(((params.page || 1) - 1) * (params.size || 20), (params.page || 1) * (params.size || 20));
    return delay({ records, total: filtered.length });
  }
  const query = new URLSearchParams();
  if (params.status) query.set('status', params.status);
  if (params.type) query.set('type', params.type);
  if (params.keyword) query.set('keyword', params.keyword);
  query.set('page', params.page || 1);
  query.set('size', params.size || 20);
  return request(`/api/merchant-cs/tickets?${query.toString()}`);
}

export async function getTicket(ticketId) {
  if (!USE_REAL_API) {
    const ticket = tickets.find(t => t.id === ticketId);
    if (!ticket) throw new Error('售后申请不存在');
    return delay(ticket);
  }
  return request(`/api/merchant-cs/tickets/${ticketId}`);
}

export async function getTicketLogs(ticketId) {
  if (!USE_REAL_API) {
    return delay(ticketLogs[ticketId] || []);
  }
  return request(`/api/merchant-cs/tickets/${ticketId}/logs`);
}

export async function approveTicket(ticketId, auditOpinion) {
  if (!USE_REAL_API) {
    const ticket = tickets.find(t => t.id === ticketId);
    if (ticket) {
      ticket.status = 'PROCESSING';
      ticket.auditOpinion = auditOpinion || '审核通过，进入处理中';
    }
    return delay(ticket || null);
  }
  return request(`/api/merchant-cs/tickets/${ticketId}/approve`, {
    method: 'POST',
    body: JSON.stringify({ auditOpinion })
  });
}

export async function rejectTicket(ticketId, rejectReason) {
  if (!USE_REAL_API) {
    const ticket = tickets.find(t => t.id === ticketId);
    if (ticket) {
      ticket.status = 'REJECTED';
      ticket.rejectReason = rejectReason || '资料不足，请补充凭证';
    }
    return delay(ticket || null);
  }
  return request(`/api/merchant-cs/tickets/${ticketId}/reject`, {
    method: 'POST',
    body: JSON.stringify({ rejectReason })
  });
}

export async function completeTicket(ticketId, completeNote) {
  if (!USE_REAL_API) {
    const ticket = tickets.find(t => t.id === ticketId);
    if (ticket) {
      ticket.status = 'COMPLETED';
      ticket.auditOpinion = completeNote || '处理完成';
      ticket.completeTime = formatTime(new Date());
    }
    return delay(ticket || null);
  }
  return request(`/api/merchant-cs/tickets/${ticketId}/complete`, {
    method: 'POST',
    body: JSON.stringify({ completeNote })
  });
}

// ==================== Orders ====================

export async function getOrders(params = {}) {
  if (!USE_REAL_API) {
    return delay({ records: [], total: 0 });
  }
  const query = new URLSearchParams();
  if (params.status) query.set('status', params.status);
  if (params.keyword) query.set('keyword', params.keyword);
  query.set('page', params.page || 1);
  query.set('size', params.size || 20);
  return request(`/api/merchant-cs/orders?${query.toString()}`);
}

export async function getOrder(orderId) {
  if (!USE_REAL_API) {
    return delay({});
  }
  return request(`/api/merchant-cs/orders/${orderId}`);
}

export async function shipOrder(orderId) {
  if (!USE_REAL_API) {
    return delay({});
  }
  return request(`/api/merchant-cs/orders/${orderId}/ship`, { method: 'POST' });
}

// ==================== Notices ====================

export async function getNotices(params = {}) {
  if (!USE_REAL_API) {
    return delay({ records: [], total: 0 });
  }
  const query = new URLSearchParams();
  if (params.readStatus) query.set('readStatus', params.readStatus);
  if (params.level) query.set('level', params.level);
  query.set('page', params.page || 1);
  query.set('size', params.size || 20);
  return request(`/api/merchant-cs/notices?${query.toString()}`);
}

export async function markNoticeRead(noticeId) {
  if (!USE_REAL_API) {
    return delay({ id: noticeId, readStatus: 'READ' });
  }
  return request(`/api/merchant-cs/notices/${noticeId}/read`, { method: 'PUT' });
}

// ==================== Reviews ====================

export async function getReviews(params = {}) {
  if (!USE_REAL_API) {
    return delay({ records: [], total: 0 });
  }
  const query = new URLSearchParams();
  if (params.score) query.set('score', params.score);
  if (params.keyword) query.set('keyword', params.keyword);
  query.set('page', params.page || 1);
  query.set('size', params.size || 20);
  return request(`/api/merchant-cs/reviews?${query.toString()}`);
}

// ==================== Products ====================

export async function getProducts(params = {}) {
  if (!USE_REAL_API) {
    return delay({ records: [], total: 0 });
  }
  const query = new URLSearchParams();
  if (params.status) query.set('status', params.status);
  if (params.keyword) query.set('keyword', params.keyword);
  query.set('page', params.page || 1);
  query.set('size', params.size || 20);
  return request(`/api/merchant-cs/products?${query.toString()}`);
}

export async function getProduct(productId) {
  if (!USE_REAL_API) {
    return delay({});
  }
  return request(`/api/merchant-cs/products/${productId}`);
}

export async function createProduct(productData) {
  if (!USE_REAL_API) {
    const newProduct = {
      id: Date.now(),
      ...productData,
      status: 'ON_SALE',
      createdAt: formatTime(new Date()),
      updatedAt: formatTime(new Date())
    };
    return delay(newProduct);
  }
  return request('/api/merchant-cs/products', {
    method: 'POST',
    body: JSON.stringify(productData)
  });
}

export async function uploadProductImage(file) {
  if (!USE_REAL_API) {
    return delay({ url: URL.createObjectURL(file) });
  }
  const formData = new FormData();
  formData.append('file', file);
  const response = await fetch(buildUrl('/api/upload/image'), {
    method: 'POST',
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    },
    body: formData
  });
  const text = await response.text();
  let payload = {};
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      throw new Error(text || '图片上传接口返回格式错误');
    }
  }
  if (!response.ok || payload.success === false) {
    throw new Error(payload.message || `图片上传失败（HTTP ${response.status}）`);
  }
  const url = resolveUploadUrl(payload);
  if (!url) {
    throw new Error('图片上传成功，但响应中没有图片地址');
  }
  return { ...(payload.data || {}), url };
}

export async function updateProduct(productId, productData) {
  if (!USE_REAL_API) {
    return delay({ ...productData, id: productId, updatedAt: formatTime(new Date()) });
  }
  return request(`/api/merchant-cs/products/${productId}`, {
    method: 'PUT',
    body: JSON.stringify(productData)
  });
}

export async function updateProductStatus(productId, status) {
  if (!USE_REAL_API) {
    return delay({ id: productId, status });
  }
  return request(`/api/merchant-cs/products/${productId}/status`, {
    method: 'PUT',
    body: JSON.stringify({ status })
  });
}
