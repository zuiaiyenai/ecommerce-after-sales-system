const BASE_URL = normalizeBaseUrl(import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8080');
const TOKEN_KEY = 'admin_console_token';

let token = localStorage.getItem(TOKEN_KEY) || '';

function normalizeBaseUrl(url) {
  return url.replace(/\/+$/, '').replace(/\/api$/, '');
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
  const hasFormData = options.body instanceof FormData;
  const headers = {
    ...(hasFormData ? {} : { 'Content-Type': 'application/json' }),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers || {})
  };
  const response = await fetch(buildUrl(path), {
    ...options,
    headers
  });
  const text = await response.text();
  let payload = {};
  if (text) {
    payload = JSON.parse(text);
  }
  if (!response.ok || payload.success === false) {
    throw new Error(payload.message || `管理员接口请求失败（HTTP ${response.status}）`);
  }
  return payload.data;
}

function mapKnowledgeRecord(item) {
  return {
    id: item.id,
    code: item.sourceCode,
    name: item.title,
    type: item.sourceType,
    status: item.status === 1 ? 'ENABLED' : 'DISABLED',
    description: item.content || '',
    merchantCode: item.merchantCode || '',
    productCategory: item.productCategory || '',
    scene: item.scene || '',
    intent: item.intent || '',
    policyVersion: item.policyVersion || 'v1.0',
    tags: Array.isArray(item.tags) ? item.tags.join(', ') : '',
    updatedAt: item.updatedAt,
    createdAt: item.createdAt,
    chunkCount: item.chunkCount || 0,
    ingestionStatus: item.ingestionStatus || 'SUCCESS',
    ingestionSourceType: item.ingestionSourceType || 'TEXT',
    fileName: item.fileName || '',
    fileUrl: item.fileUrl || '',
    errorMessage: item.errorMessage || '',
    scope: item.scope || 'MERCHANT',
    metadata: item.metadata || {}
  };
}

export async function loginAdmin(credentials) {
  const data = await request('/api/admin/auth/login', {
    method: 'POST',
    body: JSON.stringify(credentials)
  });
  saveToken(data.token);
  return data;
}

export async function logoutAdmin() {
  try {
    await request('/api/admin/auth/logout', { method: 'POST' });
  } finally {
    saveToken('');
  }
}

export async function getCurrentAdmin() {
  return request('/api/admin/auth/me');
}

export async function getAdminOverview() {
  return request('/api/admin/overview');
}

export async function getAgentAccounts(page = 1, size = 100) {
  return request(`/api/admin/service-accounts?page=${page}&size=${size}`);
}

export async function createAgentAccount(payload) {
  return request('/api/admin/service-accounts', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}

export async function updateAgentAccount(accountId, payload) {
  return request(`/api/admin/service-accounts/${accountId}`, {
    method: 'PUT',
    body: JSON.stringify(payload)
  });
}

export async function resetAgentPassword(accountId) {
  return request(`/api/admin/service-accounts/${accountId}/reset-password`, {
    method: 'POST'
  });
}

export async function getKnowledgeLibraries() {
  const data = await request('/api/admin/knowledge/list?page=1&pageSize=100');
  const records = (data || []).map(mapKnowledgeRecord);
  return {
    records,
    total: records.length
  };
}

export async function getKnowledgeLibrary(libraryId) {
  const item = await request(`/api/admin/knowledge/${libraryId}`);
  return mapKnowledgeRecord(item);
}

export async function createKnowledgeTextImport(payload) {
  return request('/api/admin/knowledge/import/text', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}

export async function createKnowledgeFileImport(formData) {
  return request('/api/admin/knowledge/import/file', {
    method: 'POST',
    body: formData
  });
}

export async function updateKnowledgeLibrary(libraryId, payload) {
  return request(`/api/admin/knowledge/${libraryId}`, {
    method: 'PUT',
    body: JSON.stringify(payload)
  });
}

export async function syncKnowledgeLibrary(libraryId) {
  return request(`/api/admin/knowledge/${libraryId}/sync`, {
    method: 'POST'
  });
}

export async function deleteKnowledgeLibrary(libraryId) {
  return request(`/api/admin/knowledge/${libraryId}`, {
    method: 'DELETE'
  });
}
