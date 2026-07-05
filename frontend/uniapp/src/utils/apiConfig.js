const DEFAULT_API_BASE_URL = 'http://127.0.0.1:8080/api'
const DEFAULT_TIMEOUT = 15000
const DEFAULT_AGENT_TIMEOUT = 90000

function trimTrailingSlash(value = '') {
  return String(value || '').replace(/\/+$/, '')
}

function readStoredValue(key) {
  try {
    return uni.getStorageSync(key)
  } catch (error) {
    return ''
  }
}

export function getApiBaseUrl() {
  const stored = trimTrailingSlash(readStoredValue('apiBaseUrl'))
  return stored || DEFAULT_API_BASE_URL
}

export function getAgentBaseUrl() {
  const stored = trimTrailingSlash(readStoredValue('agentBaseUrl'))
  if (stored) return stored
  return `${getApiBaseUrl()}/agent`
}

export function getRequestTimeout() {
  const stored = Number(readStoredValue('requestTimeout'))
  return Number.isFinite(stored) && stored > 0 ? stored : DEFAULT_TIMEOUT
}

export function getAgentRequestTimeout() {
  const stored = Number(readStoredValue('agentRequestTimeout'))
  return Number.isFinite(stored) && stored > 0 ? stored : DEFAULT_AGENT_TIMEOUT
}
