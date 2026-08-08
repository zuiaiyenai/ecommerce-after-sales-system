import { getAgentBaseUrl, getAgentRequestTimeout } from './apiConfig'
import { uploadFile } from './request'
import { normalizeOrderStatus, resolveOrderAfterSalesSnapshot } from './orderStatus'

const STORAGE_PREFIX = 'after_sales_agent'

function agentRequest(options) {
  const requestOptions = options || {}
  const agentBaseUrl = getAgentBaseUrl()
  const token = uni.getStorageSync('token') || ''

  return new Promise((resolve, reject) => {
    uni.request({
      url: `${agentBaseUrl}${requestOptions.url}`,
      method: requestOptions.method || 'GET',
      data: requestOptions.data || {},
      timeout: getAgentRequestTimeout(),
      header: {
        'content-type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(requestOptions.header || {})
      },
      success: (res) => {
        const body = res.data || {}
        if (body.code !== undefined && body.code !== 200) {
          const error = new Error(body.message || '操作失败')
          error.code = body.code
          error.data = body.data
          reject(error)
          return
        }
        resolve(body.data !== undefined ? body.data : body)
      },
      fail: (error) => {
        reject(new Error(error?.errMsg || '当前售后服务暂时无法连接'))
      }
    })
  })
}

export function checkAgentHealth() {
  return agentRequest({ url: '/health' })
}

function getFileExtension(filePath = '') {
  const match = String(filePath).toLowerCase().match(/\.([a-z0-9]+)(?:\?|#|$)/)
  return match ? match[1] : 'jpg'
}

function getMimeType(filePath = '') {
  const ext = getFileExtension(filePath)
  const map = {
    jpg: 'image/jpeg',
    jpeg: 'image/jpeg',
    png: 'image/png',
    webp: 'image/webp',
    gif: 'image/gif'
  }
  return map[ext] || 'image/jpeg'
}

export function filePathToDataUrl(filePath) {
  return new Promise((resolve, reject) => {
    const fs = uni.getFileSystemManager && uni.getFileSystemManager()
    if (!fs || !fs.readFile) {
      reject(new Error('当前环境不支持读取本地图片'))
      return
    }
    fs.readFile({
      filePath,
      encoding: 'base64',
      success: (res) => {
        resolve(`data:${getMimeType(filePath)};base64,${res.data}`)
      },
      fail: () => {
        reject(new Error('图片读取失败'))
      }
    })
  })
}

export async function buildAttachments(imagePaths = []) {
  const attachments = []
  for (const filePath of imagePaths) {
    const [source, uploadResult] = await Promise.all([
      filePathToDataUrl(filePath),
      uploadFile({ url: '/upload/image', filePath, name: 'file' })
    ])
    attachments.push({
      kind: 'image',
      name: filePath.split(/[\\/]/).pop() || 'image.jpg',
      file_url: uploadResult?.fileUrl || '',
      source
    })
  }
  return attachments
}

export function buildOrderHint(selectedOrder = {}) {
  const orderId = selectedOrder.order_id || ''
  const productName = selectedOrder.product_name || '未知商品'
  return orderId ? `订单号：${orderId}；商品：${productName}` : `商品：${productName}`
}

function getCurrentUserId() {
  const userInfo = uni.getStorageSync('userInfo') || {}
  return String(userInfo.userId || 'u1001')
}

function hasLocalAfterSalesTicket(orderNo) {
  if (!orderNo) return false
  try {
    const ticket = uni.getStorageSync(`after_sales_ticket:${orderNo}`)
    return Boolean(ticket && ticket.ticket_id)
  } catch (error) {
    return false
  }
}

function resolveTicketId(order = {}, extra = {}) {
  const value = extra.ticketId
    || extra.ticket_id
    || order.ticketId
    || order.ticket_id
    || order.latestTicketId
  return value === undefined || value === null ? '' : String(value)
}

export function buildSelectedOrder(order = {}, extra = {}) {
  const item = Array.isArray(order.items) && order.items.length > 0 ? order.items[0] : {}
  const totalAmount = order.payAmount !== undefined && order.payAmount !== null
    ? order.payAmount
    : (order.totalAmount !== undefined && order.totalAmount !== null ? order.totalAmount : item.subtotal)
  const statusMap = {
    PAID: 'paid',
    SHIPPED: 'shipped',
    RECEIVED: 'delivered',
    COMPLETED: 'completed',
    CLOSED: 'closed',
    REFUNDED: 'refunded'
  }
  const orderId = String(order.orderId || extra.orderId || '')
  const orderNo = String(order.orderNo || extra.orderNo || '')
  const hasTicket = hasLocalAfterSalesTicket(orderNo)
  const orderStatus = normalizeOrderStatus(order.status)
  const afterSalesSnapshot = resolveOrderAfterSalesSnapshot({
    ...order,
    hasOpenAfterSales: extra.hasOpenAfterSales ?? order.hasOpenAfterSales,
    afterSalesStatus: extra.afterSalesStatus || order.afterSalesStatus,
    afterSalesStatusText: extra.afterSalesStatusText || order.afterSalesStatusText,
    latestTicketNo: order.latestTicketNo || (hasTicket ? orderNo : '')
  })
  const hasOpenAfterSales = Boolean(extra.hasOpenAfterSales ?? afterSalesSnapshot.hasOpenAfterSales)
  const afterSalesStatus = String(extra.afterSalesStatus || afterSalesSnapshot.afterSalesStatus || 'not_applied')
  const uploadedEvidence = Array.isArray(extra.uploadedEvidence)
    ? extra.uploadedEvidence
    : (extra.uploadedEvidence ? [extra.uploadedEvidence] : [])
  const ticketId = resolveTicketId(order, extra)

  return {
    order_id: orderId,
    user_id: String(extra.userId || getCurrentUserId()),
    merchant_code: String(order.merchantCode || extra.merchantCode || 'MERCHANT_DEMO'),
    merchant_display_name: String(order.merchantDisplayName || extra.merchantDisplayName || ''),
    product_name: String(item.productName || extra.productName || order.orderNo || '未知商品'),
    category: String(item.productSpec || extra.category || '综合'),
    status: statusMap[orderStatus] || String(extra.status || 'delivered'),
    after_sales_status: afterSalesStatus,
    amount: Number(totalAmount || item.price || 0),
    refund_status: String(extra.refundStatus || order.refundStatus || '未进入退款流程'),
    logistics_status: String(extra.logisticsStatus || order.statusText || '待更新'),
    has_open_after_sales: hasOpenAfterSales,
    uploaded_evidence: uploadedEvidence,
    existing_ticket_no: String(extra.existingTicketNo || order.latestTicketNo || ''),
    ticket_id: ticketId
  }
}

function normalizeSessionId(sessionId) {
  const value = String(sessionId || '').trim()
  return value || null
}

export function buildChatPayload({
  order,
  message,
  description = '',
  sessionId = null,
  humanRequestCount = 0,
  attachments = [],
  imageReview = null,
  skipImageReview = false,
  itemOpened = null,
  selectedOrderExtra = {},
  recentHistory = []
}) {
  const selectedOrder = order ? buildSelectedOrder(order, selectedOrderExtra) : null
  const ticketId = selectedOrder
    ? selectedOrder.ticket_id
    : resolveTicketId({}, selectedOrderExtra)
  const payload = {
    user_id: selectedOrder ? selectedOrder.user_id : String(selectedOrderExtra.userId || getCurrentUserId()),
    order_id: selectedOrder ? selectedOrder.order_id : (selectedOrderExtra.orderId || ''),
    ticket_id: ticketId || undefined,
    session_id: normalizeSessionId(sessionId),
    message,
    description,
    human_request_count: humanRequestCount,
    skip_image_review: skipImageReview,
    attachments,
    recent_history: recentHistory
  }
  if (selectedOrderExtra.forceAfterSalesApply) {
    payload.force_after_sales_apply = true
  }
  if (selectedOrder) {
    payload.selected_order = selectedOrder
  }
  if (itemOpened !== null && itemOpened !== undefined) {
    payload.item_opened = itemOpened
  }
  if (imageReview) {
    payload.image_review = imageReview
  }
  return payload
}

export function chat(payload) {
  return agentRequest({
    url: '/chat',
    method: 'POST',
    data: payload
  })
}

// POST SSE for WeChat/uni-app. Returns RequestTask so callers can abort on page unload.
export function streamChat(payload, handlers = {}) {
  const token = uni.getStorageSync('token') || ''
  let buffer = ''
  let currentEvent = 'message'
  const decoder = typeof TextDecoder !== 'undefined' ? new TextDecoder('utf-8') : null
  const task = uni.request({
    url: `${getAgentBaseUrl()}/chat/stream`,
    method: 'POST',
    data: payload,
    timeout: getAgentRequestTimeout(),
    enableChunked: true,
    header: {
      'content-type': 'application/json',
      Accept: 'text/event-stream',
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    },
    success: () => handlers.onComplete?.(),
    fail: (error) => {
      if (!String(error?.errMsg || '').includes('abort')) handlers.onError?.(error)
    }
  })
  task.onChunkReceived?.(({ data }) => {
    const text = decoder
      ? decoder.decode(data, { stream: true })
      : decodeURIComponent(escape(String.fromCharCode(...new Uint8Array(data))))
    buffer += text
    const lines = buffer.split(/\r?\n/)
    buffer = lines.pop() || ''
    for (const line of lines) {
      if (line.startsWith('event:')) currentEvent = line.slice(6).trim()
      if (!line.startsWith('data:')) continue
      try {
        handlers.onEvent?.(currentEvent, JSON.parse(line.slice(5).trim()))
      } catch (error) {
        handlers.onError?.(error)
      }
    }
  })
  return task
}

export function reviewImages(payload) {
  return agentRequest({
    url: '/review-images',
    method: 'POST',
    data: payload
  })
}

export function getConversationStorageKey(orderKey) {
  return `${STORAGE_PREFIX}:conversation:${orderKey || 'default'}`
}

export function loadConversationState(orderKey) {
  return uni.getStorageSync(getConversationStorageKey(orderKey)) || null
}

export function saveConversationState(orderKey, state) {
  uni.setStorageSync(getConversationStorageKey(orderKey), state)
}
