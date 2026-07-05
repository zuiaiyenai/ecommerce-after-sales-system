import { getAgentBaseUrl, getAgentRequestTimeout } from './apiConfig'

const STORAGE_PREFIX = 'after_sales_agent'

function agentRequest(options) {
  const requestOptions = options || {}
  const agentBaseUrl = getAgentBaseUrl()

  return new Promise((resolve, reject) => {
    uni.request({
      url: `${agentBaseUrl}${requestOptions.url}`,
      method: requestOptions.method || 'GET',
      data: requestOptions.data || {},
      timeout: getAgentRequestTimeout(),
      header: {
        'content-type': 'application/json',
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
    const source = await filePathToDataUrl(filePath)
    attachments.push({
      kind: 'image',
      name: filePath.split(/[\\/]/).pop() || 'image.jpg',
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
  return String(userInfo.id || userInfo.userId || 'u1001')
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
    AFTERSALE: 'after_sales',
    REFUNDED: 'refunded'
  }
  const orderNo = String(order.orderNo || order.id || extra.orderId || '')
  const hasTicket = hasLocalAfterSalesTicket(orderNo)
  const hasOpenAfterSales = Boolean(extra.hasOpenAfterSales ?? (order.status === 'AFTERSALE' && hasTicket))
  const afterSalesStatus = extra.afterSalesStatus || (hasOpenAfterSales ? 'submitted' : 'not_applied')
  const uploadedEvidence = Array.isArray(extra.uploadedEvidence)
    ? extra.uploadedEvidence
    : (extra.uploadedEvidence ? [extra.uploadedEvidence] : [])

  return {
    order_id: orderNo,
    user_id: String(extra.userId || getCurrentUserId()),
    merchant_code: String(order.merchantCode || extra.merchantCode || 'MERCHANT_DEMO'),
    product_name: String(item.productName || extra.productName || order.orderNo || '未知商品'),
    category: String(item.productSpec || extra.category || '综合'),
    status: statusMap[order.status] || String(extra.status || 'delivered'),
    after_sales_status: afterSalesStatus,
    amount: Number(totalAmount || item.price || 0),
    refund_status: String(extra.refundStatus || order.refundStatus || '未进入退款流程'),
    logistics_status: String(extra.logisticsStatus || order.statusText || '待更新'),
    has_open_after_sales: hasOpenAfterSales,
    uploaded_evidence: uploadedEvidence
  }
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
  const payload = {
    order_id: selectedOrder ? selectedOrder.order_id : (selectedOrderExtra.orderId || ''),
    session_id: sessionId,
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
