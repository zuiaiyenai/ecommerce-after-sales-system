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

function normalizeBaseUrl(url) {
  return url.replace(/\/+$/, '').replace(/\/api$/, '');
}

function buildUrl(path) {
  return `${BASE_URL}${path.startsWith('/') ? path : `/${path}`}`;
}

async function parseApiResponse(response) {
  const text = await response.text();
  if (!text) {
    return {
      success: response.ok,
      code: response.status,
      message: response.ok ? '' : `HTTP ${response.status}`,
      data: null
    };
  }
  try {
    return JSON.parse(text);
  } catch (error) {
    return {
      success: false,
      code: response.status,
      message: text || error.message || `HTTP ${response.status}`,
      data: null
    };
  }
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
  const payload = await parseApiResponse(response);
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
        { title: '待审核工单', value: tickets.filter(t => t.status === 'PENDING_REVIEW').length, trend: '+0', accent: 'slate' },
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
    if (!ticket) throw new Error('工单不存在');
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
      ticket.status = 'APPROVED';
      ticket.auditOpinion = auditOpinion || '审核通过';
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
  const payload = await parseApiResponse(response);
  if (!response.ok || payload.success === false) {
    throw new Error(payload.message || '图片上传失败');
  }
  return payload.data;
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
