import { request } from './request'

export function listChatSessions() {
  return request({ url: '/chat/sessions' })
}

export function createChatSession(data = {}) {
  return request({
    url: '/chat/session',
    method: 'POST',
    data
  })
}

export function getChatHistory(sessionId) {
  return request({ url: `/chat/history?sessionId=${sessionId}` })
}

export function sendChatMessage(data = {}) {
  return request({
    url: '/chat/send',
    method: 'POST',
    data
  })
}

export function hideChatSession(sessionId) {
  return request({
    url: '/chat/session/hide',
    method: 'PUT',
    data: { sessionId }
  })
}

export function submitChatEvaluation(sessionId, rating = 5, content = '', extra = {}) {
  return request({
    url: '/chat/evaluation',
    method: 'POST',
    data: { sessionId, rating, content, ...extra }
  })
}
