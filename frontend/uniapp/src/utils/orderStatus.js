const ORDER_STATUS_TEXT_MAP = {
  PAID: '未发货',
  SHIPPED: '配送中',
  RECEIVED: '已收货',
  AWAITING_EVALUATION: '待评价',
  COMPLETED: '已完成',
  CLOSED: '已关闭',
  REFUNDED: '已退款'
}

const ORDER_STATUS_CLASS_MAP = {
  PAID: 'paid',
  SHIPPED: 'pending',
  RECEIVED: 'done',
  AWAITING_EVALUATION: 'review',
  COMPLETED: 'completed',
  CLOSED: 'completed',
  REFUNDED: 'completed'
}

const AFTER_SALES_STATUS_TEXT_MAP = {
  NOT_APPLIED: '未发起售后',
  SUBMITTED: '已提交',
  PENDING: '待审核',
  PENDING_REVIEW: '待审核',
  WAITING_EVIDENCE: '待补充材料',
  MERCHANT_REVIEW: '商家审核中',
  PLATFORM_REVIEW: '平台复核中',
  APPROVED: '审核通过',
  WAITING_RETURN: '待填写退货物流',
  REFUND_PROCESSING: '退款处理中',
  EXCHANGE_PROCESSING: '处理中',
  PROCESSING: '处理中',
  HUMAN_PROCESSING: '人工处理中',
  REJECTED: '已驳回',
  COMPLETED: '已完成',
  CLOSED: '已关闭'
}

const AFTER_SALES_STATUS_CLASS_MAP = {
  submitted: 'waiting',
  pending: 'waiting',
  pending_review: 'waiting',
  waiting_evidence: 'waiting',
  merchant_review: 'processing',
  platform_review: 'processing',
  approved: 'approved',
  waiting_return: 'processing',
  refund_processing: 'processing',
  exchange_processing: 'processing',
  processing: 'processing',
  human_processing: 'processing',
  rejected: 'rejected',
  completed: 'completed',
  closed: 'completed'
}

const OPEN_AFTER_SALES_STATUSES = new Set([
  'submitted',
  'pending',
  'pending_review',
  'waiting_evidence',
  'merchant_review',
  'platform_review',
  'approved',
  'waiting_return',
  'refund_processing',
  'exchange_processing',
  'processing',
  'human_processing'
])

const AFTER_SALES_HISTORY_STATUSES = new Set([
  ...OPEN_AFTER_SALES_STATUSES,
  'rejected',
  'completed',
  'closed'
])

export function normalizeOrderStatus(status) {
  return String(status || '').trim().toUpperCase()
}

export function normalizeAfterSalesStatus(status) {
  const normalized = String(status || '').trim()
  if (!normalized) return 'not_applied'
  const upper = normalized.toUpperCase()
  if (upper === 'NOT_APPLIED') return 'not_applied'
  return upper.toLowerCase()
}

export function isOpenAfterSalesStatus(status) {
  return OPEN_AFTER_SALES_STATUSES.has(normalizeAfterSalesStatus(status))
}

export function hasAfterSalesHistoryStatus(status) {
  return AFTER_SALES_HISTORY_STATUSES.has(normalizeAfterSalesStatus(status))
}

export function getOrderStatusText(status, fallbackText = '') {
  const normalized = normalizeOrderStatus(status)
  return ORDER_STATUS_TEXT_MAP[normalized] || fallbackText || normalized || ''
}

export function getOrderStatusClass(status) {
  return ORDER_STATUS_CLASS_MAP[normalizeOrderStatus(status)] || ''
}

export function getAfterSalesStatusText(status, fallbackText = '') {
  const raw = String(status || '').trim()
  const upper = raw.toUpperCase()
  const fallback = String(fallbackText || '').trim()
  if (fallback && fallback.toUpperCase() !== upper) return fallback
  return AFTER_SALES_STATUS_TEXT_MAP[upper] || fallback || raw || '未发起售后'
}

export function getAfterSalesStatusClass(status) {
  return AFTER_SALES_STATUS_CLASS_MAP[normalizeAfterSalesStatus(status)] || ''
}

export function getAfterSalesTabKey(status) {
  const normalized = normalizeAfterSalesStatus(status)
  if (normalized === 'rejected') return 'rejected'
  if (normalized === 'completed' || normalized === 'closed') return 'completed'
  if (normalized === 'submitted' || normalized === 'pending' || normalized === 'pending_review') return 'pending'
  return 'processing'
}

export function resolveOrderAfterSalesSnapshot(order = {}) {
  const explicitStatus = order.afterSalesStatus ?? order.after_sales_status ?? ''
  const explicitStatusText = order.afterSalesStatusText ?? order.after_sales_status_text ?? ''
  const explicitHasOpen = order.hasOpenAfterSales ?? order.has_open_after_sales
  const latestTicketNo = order.latestAfterSalesTicketNo ?? order.latest_after_sales_ticket_no ?? ''

  const hasOpenAfterSales = typeof explicitHasOpen === 'boolean'
    ? explicitHasOpen
    : isOpenAfterSalesStatus(explicitStatus)
  const hasHistory = Boolean(latestTicketNo) || hasAfterSalesHistoryStatus(explicitStatus)
  const hasAnyAfterSales = hasOpenAfterSales || hasHistory

  return {
    hasOpenAfterSales,
    hasAnyAfterSales,
    afterSalesStatus: normalizeAfterSalesStatus(explicitStatus),
    afterSalesStatusText: hasAnyAfterSales
      ? getAfterSalesStatusText(explicitStatus, explicitStatusText || (hasOpenAfterSales ? '售后处理中' : '已有售后记录'))
      : '未发起售后',
    latestAfterSalesTicketNo: String(latestTicketNo || '')
  }
}

export function resolveOrderDisplay(order = {}) {
  const orderStatus = normalizeOrderStatus(order.status)
  const afterSales = resolveOrderAfterSalesSnapshot(order)
  if (afterSales.hasOpenAfterSales) {
    return {
      statusKey: 'aftersale',
      statusText: afterSales.afterSalesStatusText,
      statusClass: getAfterSalesStatusClass(afterSales.afterSalesStatus),
      canApplyAfterSales: false,
      canContactService: true
    }
  }

  return {
    statusKey: orderStatus.toLowerCase(),
    statusText: getOrderStatusText(orderStatus, order.statusText || ''),
    statusClass: getOrderStatusClass(orderStatus),
    canApplyAfterSales: !afterSales.hasAnyAfterSales && (orderStatus === 'SHIPPED' || orderStatus === 'RECEIVED'),
    canContactService: afterSales.hasAnyAfterSales
  }
}

export function resolveAfterSalesTicketDisplay(ticket = {}) {
  const status = ticket.status || ticket.afterSalesStatus || ''
  return {
    statusKey: getAfterSalesTabKey(status),
    statusText: getAfterSalesStatusText(status, ticket.statusText || ''),
    statusClass: getAfterSalesStatusClass(status)
  }
}
