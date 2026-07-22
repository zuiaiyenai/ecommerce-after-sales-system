const BASE_URL = normalizeBaseUrl(import.meta.env.VITE_API_BASE_URL);
const TOKEN_KEY = 'merchant_cs_token';

let token = localStorage.getItem(TOKEN_KEY) || '';
let staffProfile = {};

function normalizeBaseUrl(url) {
  return String(url || '').replace(/\/+$/, '').replace(/\/api$/, '');
}

function buildUrl(path) {
  return `${BASE_URL}${path.startsWith('/') ? path : `/${path}`}`;
}

function saveToken(newToken) {
  token = newToken || '';
  if (token) {
    localStorage.setItem(TOKEN_KEY, token);
  } else {
    localStorage.removeItem(TOKEN_KEY);
  }
}

async function request(path, options = {}) {
  const hasBody = options.body != null || (options.method && options.method.toUpperCase() !== 'GET');
  const response = await fetch(buildUrl(path), {
    ...options,
    headers: {
      ...(hasBody ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {})
    }
  });
  const text = await response.text();
  let payload = {};
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      throw new Error(text || '接口响应格式错误');
    }
  }
  if (!response.ok || payload.success === false) {
    throw new Error(payload.message || `接口请求失败（HTTP ${response.status}）`);
  }
  return payload.data;
}

function toFiniteNumber(value, fallback = 0) {
  const numericValue = Number(value);
  return Number.isFinite(numericValue) ? numericValue : fallback;
}

function normalizePageData(page = {}) {
  const records = Array.isArray(page.records) ? page.records : [];
  return { ...page, records, total: toFiniteNumber(page.total, records.length) };
}

function formatStaffNo(profile = {}) {
  const current = profile.staffNo ? String(profile.staffNo) : '';
  if (/^CS\d{1,6}$/.test(current)) return current;
  const source = current.match(/^CS(\d+)$/)?.[1] || (profile.staffId == null ? '' : String(profile.staffId));
  return /^\d+$/.test(source) ? `CS${source.slice(-4).padStart(4, '0')}` : current;
}

function normalizeStaffProfile(profile = {}) {
  return { ...profile, staffNo: formatStaffNo(profile) };
}

function buildPageQuery(params = {}, extraFields = []) {
  const query = new URLSearchParams();
  ['status', 'keyword', ...extraFields].forEach((field) => {
    if (params[field] != null && params[field] !== '') query.set(field, params[field]);
  });
  query.set('page', params.page || 1);
  query.set('size', params.size || 20);
  return query.toString();
}

export function resolveAssetUrl(url) {
  if (!url) return '';
  if (/^(https?:)?\/\//.test(url) || url.startsWith('data:') || url.startsWith('blob:')) return url;
  if (url.startsWith('/uploads/') || url.startsWith('/static/')) return buildUrl(`/api${url}`);
  return buildUrl(url);
}

export async function login(credentials) {
  const data = await request('/api/merchant-cs/auth/login', { method: 'POST', body: JSON.stringify(credentials) });
  saveToken(data.token);
  staffProfile = normalizeStaffProfile(data.staff);
  return { ...data, staff: staffProfile };
}

export async function registerStaff(payload) {
  return request('/api/merchant-cs/auth/register', { method: 'POST', body: JSON.stringify(payload) });
}

export async function sendAuthCode(payload) {
  return request('/api/merchant-cs/auth/code', { method: 'POST', body: JSON.stringify(payload) });
}

export async function resetPassword(payload) {
  return request('/api/merchant-cs/auth/password/reset', { method: 'POST', body: JSON.stringify(payload) });
}

export async function logout() {
  try {
    await request('/api/merchant-cs/auth/logout', { method: 'POST' });
  } finally {
    saveToken('');
    staffProfile = {};
  }
}

export async function getCurrentStaff() {
  staffProfile = normalizeStaffProfile({ ...staffProfile, ...(await request('/api/merchant-cs/auth/me')) });
  return staffProfile;
}

export async function updateWorkStatus(onlineStatus) {
  const updated = await request('/api/merchant-cs/work-status', {
    method: 'PUT',
    body: JSON.stringify({ onlineStatus })
  });
  staffProfile = normalizeStaffProfile({ ...staffProfile, ...updated });
  return staffProfile;
}

export const getDashboardOverview = () => request('/api/merchant-cs/dashboard/overview');
export const getDashboardTodos = () => request('/api/merchant-cs/dashboard/todos');
export const getDashboardPerformance = () => request('/api/merchant-cs/dashboard/performance');

export async function getSessions(params = {}) {
  return normalizePageData(await request(`/api/merchant-cs/sessions?${buildPageQuery(params)}`));
}

export const getSession = (sessionId) => request(`/api/merchant-cs/sessions/${sessionId}`);
export const getSessionMessages = (sessionId) => request(`/api/merchant-cs/sessions/${sessionId}/messages`);
export const getSessionAiAssist = (sessionId) => request(`/api/merchant-cs/sessions/${sessionId}/ai-assist`);

export function sendSessionMessage(sessionId, content) {
  return request(`/api/merchant-cs/sessions/${sessionId}/messages`, {
    method: 'POST',
    body: JSON.stringify({ messageType: 'TEXT', content })
  });
}

export const requestSessionEvaluation = (sessionId) => request(`/api/merchant-cs/sessions/${sessionId}/evaluation-request`, { method: 'POST' });

export function submitSessionEvaluation(sessionId, rating, content) {
  return request(`/api/merchant-cs/sessions/${sessionId}/evaluation`, {
    method: 'POST',
    body: JSON.stringify({ rating, content })
  });
}

export const closeSession = (sessionId) => request(`/api/merchant-cs/sessions/${sessionId}/close`, { method: 'POST' });

export async function getTickets(params = {}) {
  return normalizePageData(await request(`/api/merchant-cs/tickets?${buildPageQuery(params, ['type'])}`));
}

export const getTicket = (ticketId) => request(`/api/merchant-cs/tickets/${ticketId}`);
export const getTicketLogs = (ticketId) => request(`/api/merchant-cs/tickets/${ticketId}/logs`);

export function approveTicket(ticketId, auditOpinion) {
  return request(`/api/merchant-cs/tickets/${ticketId}/approve`, { method: 'POST', body: JSON.stringify({ auditOpinion }) });
}

export function rejectTicket(ticketId, rejectReason) {
  return request(`/api/merchant-cs/tickets/${ticketId}/reject`, { method: 'POST', body: JSON.stringify({ rejectReason }) });
}

export function completeTicket(ticketId, completeNote) {
  return request(`/api/merchant-cs/tickets/${ticketId}/complete`, { method: 'POST', body: JSON.stringify({ completeNote }) });
}

export async function getOrders(params = {}) {
  return normalizePageData(await request(`/api/merchant-cs/orders?${buildPageQuery(params)}`));
}

export const getOrder = (orderId) => request(`/api/merchant-cs/orders/${orderId}`);
export const shipOrder = (orderId) => request(`/api/merchant-cs/orders/${orderId}/ship`, { method: 'POST' });

export async function getReviews(params = {}) {
  return normalizePageData(await request(`/api/merchant-cs/reviews?${buildPageQuery(params, ['score'])}`));
}

export async function getProducts(params = {}) {
  return normalizePageData(await request(`/api/merchant-cs/products?${buildPageQuery(params)}`));
}

export const getProduct = (productId) => request(`/api/merchant-cs/products/${productId}`);

export function createProduct(productData) {
  return request('/api/merchant-cs/products', { method: 'POST', body: JSON.stringify(productData) });
}

export async function uploadProductImage(file) {
  const formData = new FormData();
  formData.append('file', file);
  const response = await fetch(buildUrl('/api/upload/image'), {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: formData
  });
  const text = await response.text();
  const payload = text ? JSON.parse(text) : {};
  if (!response.ok || payload.success === false) throw new Error(payload.message || `图片上传失败（HTTP ${response.status}）`);
  const data = payload.data || {};
  if (!data.fileUrl) throw new Error('图片上传成功，但响应中没有图片地址');
  return data;
}

export function updateProduct(productId, productData) {
  return request(`/api/merchant-cs/products/${productId}`, { method: 'PUT', body: JSON.stringify(productData) });
}

export function updateProductStatus(productId, status) {
  return request(`/api/merchant-cs/products/${productId}/status`, { method: 'PUT', body: JSON.stringify({ status }) });
}
