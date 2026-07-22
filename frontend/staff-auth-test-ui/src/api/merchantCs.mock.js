const TOKEN_KEY = 'merchant_cs_token';

let staff = {
  staffId: '1',
  staffNo: 'CS0001',
  merchantCode: 'MERCHANT_DEMO',
  account: 'cs_demo',
  realName: '林真',
  role: 'CUSTOMER_SERVICE',
  onlineStatus: 'ONLINE',
  maxSessionCount: 8
};

let sessions = [
  {
    sessionId: '101',
    sessionNo: 'CS20260705001',
    userId: '1001',
    orderId: '2001',
    ticketId: '3001',
    user: '演示用户',
    topic: '商品功能异常',
    lastMessageContent: '问题仍未解决，请协助处理',
    lastMessageSender: 'ASSISTANT',
    lastMessageTime: new Date().toISOString(),
    replyStatus: 'UNREPLIED',
    emotionLabel: 'ANXIOUS',
    emotionScore: 0.86,
    emotionTrend: 'UP',
    riskLevel: 'HIGH',
    priorityScore: 292,
    status: 'PROCESSING'
  },
  {
    sessionId: '102',
    sessionNo: 'CS20260705002',
    userId: '1002',
    orderId: '2002',
    ticketId: '3002',
    user: '演示用户乙',
    topic: '少发商品',
    lastMessageContent: '已经为您登记处理',
    lastMessageSender: 'SERVICE',
    lastMessageTime: new Date(Date.now() - 60_000).toISOString(),
    replyStatus: 'REPLIED',
    emotionLabel: 'CALM',
    emotionScore: 0.2,
    emotionTrend: 'FLAT',
    riskLevel: 'LOW',
    priorityScore: 40,
    status: 'PROCESSING'
  }
];

const messagesBySession = {
  101: [
    {
      messageId: '9007199254740993',
      sessionId: '101',
      senderRole: 'USER',
      messageType: 'IMAGE',
      content: '[图片]',
      fileUrl: '/static/images/product-earphone.png',
      emotionLabel: 'ANXIOUS',
      emotionScore: 0.86,
      createdAt: new Date(Date.now() - 120_000).toISOString()
    },
    {
      messageId: '9007199254740994',
      sessionId: '101',
      senderRole: 'ASSISTANT',
      messageType: 'TEXT',
      content: '已收到凭证，仍需人工客服确认。',
      createdAt: new Date().toISOString()
    }
  ],
  102: []
};

const tickets = [
  { ticketId: '3001', ticketNo: 'TK20260705001', title: '商品功能异常', status: 'PENDING_REVIEW' },
  { ticketId: '3002', ticketNo: 'TK20260705002', title: '少发商品', status: 'PROCESSING' }
];

function clone(value) {
  return structuredClone(value);
}

function delay(value) {
  return new Promise((resolve) => window.setTimeout(() => resolve(clone(value)), 60));
}

function page(records, params = {}) {
  const pageNo = Number(params.page || 1);
  const size = Number(params.size || 20);
  const start = (pageNo - 1) * size;
  return { records: records.slice(start, start + size), total: records.length };
}

function updateSession(sessionId, updates) {
  const index = sessions.findIndex((item) => String(item.sessionId) === String(sessionId));
  if (index < 0) throw new Error('会话不存在');
  sessions[index] = { ...sessions[index], ...updates };
  return sessions[index];
}

export function resolveAssetUrl(url) {
  return url || '';
}

export async function login(credentials) {
  if (credentials.account !== 'cs_demo' || credentials.password !== '123456') throw new Error('账号或密码错误');
  localStorage.setItem(TOKEN_KEY, 'demo-token');
  return delay({ token: 'demo-token', staff });
}

export const registerStaff = (payload) => delay({ ...staff, ...payload, staffId: String(Date.now()), accountStatus: 'PENDING_APPROVAL' });
export const sendAuthCode = () => delay({ code: '123456' });
export const resetPassword = () => delay(null);

export async function logout() {
  localStorage.removeItem(TOKEN_KEY);
}

export const getCurrentStaff = () => delay(staff);

export async function updateWorkStatus(onlineStatus) {
  staff = { ...staff, onlineStatus };
  return delay(staff);
}

export const getDashboardOverview = () => delay({
  greeting: `早上好，${staff.realName}`,
  subtitle: '当前为显式 mock 演示模式',
  todayTodoCount: 1,
  aiEnabled: true,
  metrics: [],
  timeline: []
});
export const getDashboardTodos = () => delay([]);
export const getDashboardPerformance = () => delay({ serviceScore: 92, trend: [], metrics: [], tags: ['演示数据'] });

export async function getSessions(params = {}) {
  const filtered = sessions.filter((item) => !params.status || item.status === params.status);
  return delay(page(filtered, params));
}

export async function getSession(sessionId) {
  const session = sessions.find((item) => String(item.sessionId) === String(sessionId));
  if (!session) throw new Error('会话不存在');
  return delay(session);
}

export const getSessionMessages = (sessionId) => delay(messagesBySession[sessionId] || []);
export const getSessionAiAssist = (sessionId) => delay({ sessionId, quickReplies: [], knowledgeHits: [], quickReplySource: 'mock' });

export async function sendSessionMessage(sessionId, content) {
  const message = {
    messageId: String(Date.now()),
    sessionId: String(sessionId),
    senderRole: 'SERVICE',
    messageType: 'TEXT',
    content,
    createdAt: new Date().toISOString()
  };
  messagesBySession[sessionId] = [...(messagesBySession[sessionId] || []), message];
  updateSession(sessionId, {
    lastMessageContent: content,
    lastMessageSender: 'SERVICE',
    lastMessageTime: message.createdAt,
    replyStatus: 'REPLIED'
  });
  return delay(message);
}

export const requestSessionEvaluation = (sessionId) => delay(updateSession(sessionId, { status: 'AWAITING_EVALUATION' }));
export const submitSessionEvaluation = (sessionId, rating) => delay(updateSession(sessionId, { status: 'READY_TO_CLOSE', rating }));
export const closeSession = (sessionId) => delay(updateSession(sessionId, { status: 'CLOSED' }));

export async function getTickets(params = {}) {
  const filtered = tickets.filter((item) => !params.status || item.status === params.status);
  return delay(page(filtered, params));
}

export async function getTicket(ticketId) {
  const ticket = tickets.find((item) => String(item.ticketId) === String(ticketId));
  if (!ticket) throw new Error('售后申请不存在');
  return delay(ticket);
}

export const getTicketLogs = () => delay([]);

function updateTicket(ticketId, updates) {
  const ticket = tickets.find((item) => String(item.ticketId) === String(ticketId));
  if (!ticket) throw new Error('售后申请不存在');
  Object.assign(ticket, updates);
  return delay(ticket);
}

export const approveTicket = (ticketId, auditOpinion) => updateTicket(ticketId, { status: 'PROCESSING', auditOpinion });
export const rejectTicket = (ticketId, rejectReason) => updateTicket(ticketId, { status: 'REJECTED', rejectReason });
export const completeTicket = (ticketId, completeNote) => updateTicket(ticketId, { status: 'COMPLETED', completeNote });

export const getOrders = (params = {}) => delay(page([], params));
export const getOrder = () => delay({});
export const shipOrder = () => delay({});
export const getReviews = (params = {}) => delay(page([], params));
export const getProducts = (params = {}) => delay(page([], params));
export const getProduct = () => delay({});
export const createProduct = (productData) => delay({ ...productData, productId: String(Date.now()) });
export const uploadProductImage = (file) => delay({ fileUrl: URL.createObjectURL(file) });
export const updateProduct = (productId, productData) => delay({ ...productData, productId });
export const updateProductStatus = (productId, status) => delay({ productId, status });
