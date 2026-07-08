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
  const headers = {
    'Content-Type': 'application/json',
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
  const records = (data || []).map((item) => {
    const tagsList = item.tags || [];
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
      tags: Array.isArray(tagsList) ? tagsList.join(', ') : '',
      updatedAt: item.updatedAt,
      chunkCount: item.chunkCount || 0
    };
  });
  return {
    records,
    total: records.length
  };
}

export async function getKnowledgeLibrary(libraryId) {
  const item = await request(`/api/admin/knowledge/${libraryId}`);
  const tagsList = item.tags || [];
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
    tags: Array.isArray(tagsList) ? tagsList.join(', ') : '',
    updatedAt: item.updatedAt,
    chunkCount: item.chunkCount || 0
  };
}

export async function updateKnowledgeLibrary(libraryId, payload) {
  return request(`/api/admin/knowledge/${libraryId}`, {
    method: 'PUT',
    body: JSON.stringify({
      title: payload.name,
      content: payload.description,
      productCategory: payload.productCategory || null,
      scene: payload.scene || null,
      intent: payload.intent || null,
      policyVersion: payload.policyVersion || null,
      tags: payload.tags ? payload.tags.split(',').map(t => t.trim()).filter(Boolean) : null,
      status: payload.status === 'ENABLED' ? 1 : 0
    })
  });
}

export async function createKnowledgeLibrary(payload) {
  return request('/api/admin/knowledge/upload', {
    method: 'POST',
    body: JSON.stringify({
      sourceType: payload.type,
      sourceCode: payload.code,
      merchantCode: payload.merchantCode || 'MERCHANT_DEMO',
      title: payload.name,
      content: payload.description || payload.name,
      productCategory: payload.productCategory || null,
      scene: payload.scene || null,
      intent: payload.intent || null,
      policyVersion: payload.policyVersion || 'v1.0',
      tags: payload.tags ? payload.tags.split(',').map(t => t.trim()).filter(Boolean) : null
    })
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
