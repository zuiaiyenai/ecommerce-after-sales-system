<template>
  <view class="page">
    <view class="nav-bar">
      <view class="back-btn" @tap="goBack">
        <text class="back-icon">←</text>
      </view>
      <text class="nav-title">{{ sessionMode === 'HUMAN' ? '人工客服' : '智能售后助手' }}</text>
      <view class="nav-right"></view>
    </view>

    <view class="fixed-context">
      <view v-if="hasOrder" class="order-card">
        <image class="order-product-img" :src="normalizeImageUrl(orderInfo.productIcon)" mode="aspectFill" />
        <view class="order-product-info">
          <text class="order-product">{{ orderInfo.productName || '售后商品' }}</text>
          <text class="merchant-text">商家：{{ orderInfo.merchantDisplayName || orderInfo.merchantCode || '演示商家' }}</text>
          <view class="order-row">
            <text class="order-no">订单号：{{ orderInfo.orderNo || '--' }}</text>
            <text class="copy-icon" @tap="copyOrderNo">复制</text>
            <text class="order-status">{{ orderInfo.statusText || '售后咨询' }}</text>
          </view>
        </view>
      </view>

      <view class="service-header">
        <view class="service-info">
          <text class="service-name">{{ sessionMode === 'HUMAN' ? '人工客服' : '售后助手在线' }}</text>
          <view class="online-dot">
            <view class="dot"></view>
            <text class="online-text">{{ agentStatusText }}</text>
          </view>
        </view>
      </view>
    </view>

    <scroll-view class="chat-area" scroll-y :scroll-top="scrollTop" scroll-with-animation>
      <view v-for="msg in messages" :key="msg.key || `${msg.role}-${msg.time}-${msg.sequence}`" class="msg-group">
        <text v-if="msg.time" class="msg-time">{{ msg.time }}</text>
        <view class="message" :class="msg.role">
          <view class="msg-bubble" :class="{ 'image-bubble': msg.type === 'IMAGE', 'ai-suggestion-bubble': msg.isAiSuggestion }">
            <image
              v-if="msg.type === 'IMAGE' && msg.fileUrl"
              class="msg-image"
              :src="normalizeImageUrl(msg.fileUrl)"
              mode="aspectFill"
              @tap="previewMessageImage(msg.fileUrl)"
            />
            <view v-else-if="msg.isAiSuggestion" class="ai-suggestion-content">
              <view class="suggestion-header">
                <text class="suggestion-icon">🤖</text>
                <text class="suggestion-title">AI评估结果</text>
              </view>
              <text class="msg-text">{{ msg.content }}</text>
              <text class="suggestion-note">※ 最终处理仍需人工审核确认</text>
            </view>
            <text v-else class="msg-text">{{ msg.content }}</text>
            <text v-if="msg.meta" class="msg-meta">{{ msg.meta }}</text>
          </view>
        </view>
      </view>
    </scroll-view>

    <view class="quick-actions">
      <view v-if="evaluationPending" class="action-btn review-action" @tap="submitEvaluation">
        <text class="action-icon">★</text>
        <text class="action-text">评价服务</text>
      </view>
      <view v-if="sessionMode !== 'HUMAN'" class="action-btn" @tap="quickAction('refund')">
        <text class="action-icon">🔄</text>
        <text class="action-text">退款进度</text>
      </view>
      <view v-if="sessionMode !== 'HUMAN'" class="action-btn" @tap="quickAction('supplement')">
        <image class="action-image-icon" src="/static/images/icon-supplement-voucher.png" mode="aspectFit" />
        <text class="action-text">补充凭证</text>
      </view>
      <view v-if="sessionMode !== 'HUMAN'" class="action-btn" @tap="quickAction('human')">
        <text class="action-icon">👤</text>
        <text class="action-text">人工帮助</text>
      </view>
    </view>

    <view v-if="attachments.length" class="attachment-preview">
      <view class="image-grid">
        <view v-for="(img, index) in attachments" :key="img" class="image-item">
          <image :src="normalizeImageUrl(img)" mode="aspectFill" class="preview-img" @tap="previewImage(index)" />
          <view class="delete-btn" @tap.stop="removeImage(index)">×</view>
        </view>
      </view>
      <text class="upload-tip">最多 3 张，随问题一并提交</text>
    </view>

    <view class="input-area">
      <view v-if="attachments.length < 3" class="attach-btn" @tap="chooseImage">
        <text class="attach-icon">+</text>
      </view>
      <input
        v-model="inputText"
        class="chat-input"
        placeholder="请输入您的售后问题"
        confirm-type="send"
        @confirm="sendMessage"
      />
      <view class="send-btn" :class="{ active: canSend }" @tap="sendMessage">
        <text class="send-icon">{{ sending ? '…' : '➤' }}</text>
      </view>
    </view>
  </view>
</template>

<script setup>
import { computed, nextTick, ref } from 'vue'
import { onLoad, onUnload } from '@dcloudio/uni-app'
import { normalizeImageUrl, request } from '../../utils/request'
import { mergePersistedChatHistory } from '../../utils/chatMessageMerge.mjs'
import { getChatWebSocketUrl } from '../../utils/apiConfig'
import { resolveAfterSalesTicketDisplay } from '../../utils/orderStatus'
import {
  buildAttachments,
  buildChatPayload,
  buildOrderHint,
  chat,
  checkAgentHealth,
  loadConversationState,
  reviewImages,
  saveConversationState
} from '../../utils/afterSalesAgent'
import { createChatSession, getChatHistory, sendChatMessage } from '../../utils/userChat'

const PENDING_APPLY_PREFIX = 'after_sales_pending_apply'

const messages = ref([])
const inputText = ref('')
const scrollTop = ref(0)
const hasOrder = ref(false)
const orderData = ref(null)
const attachments = ref([])
const sending = ref(false)
const agentStatusText = ref('连接中')
const sessionId = ref(null)
const humanRequestCount = ref(0)
const sessionMode = ref('AI')
const processingPendingApply = ref(false)
const deferredReviewRunning = ref(false)
const lastImageReview = ref(null)
const evaluationPending = ref(false)

const orderInfo = ref({
  productName: '',
  orderNo: '',
  productIcon: '',
  merchantCode: '',
  merchantDisplayName: '',
  statusText: ''
})

const canSend = computed(() => (inputText.value.trim() || attachments.value.length > 0) && !sending.value)

let messageSequence = 0  // 添加消息序号计数器

let chatSocketTask = null
let chatSocketSessionId = ''
let historyRefreshGeneration = 0

function getNowTime() {
  const now = new Date()
  return `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`
}

function getNowDateTime() {
  const now = new Date()
  const date = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
  const time = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}`
  return `${date} ${time}.${String(now.getMilliseconds()).padStart(3, '0')}`
}

function getConversationKey() {
  if (orderData.value?.orderNo) return orderData.value.orderNo
  if (orderInfo.value.orderNo) return orderInfo.value.orderNo
  return 'default'
}

function getPendingApplyKey(orderId) {
  return `${PENDING_APPLY_PREFIX}:${orderId || 'default'}`
}

function scrollToBottom() {
  nextTick(() => {
    scrollTop.value += 9999
  })
}

function addMessage(role, content, meta = '', isAiSuggestion = false, sendGroupId = '') {
  messages.value.push({
    key: `local-text-${Date.now()}-${messageSequence}`,
    role,
    content,
    type: 'TEXT',
    meta,
    createdAt: getNowDateTime(),
    time: getNowTime(),
    isAiSuggestion,
    sendGroupId,
    sequence: messageSequence++  // 添加序号
  })
  scrollToBottom()
}

function addImageMessage(role, imagePath, sendGroupId = '') {
  messages.value.push({
    key: `local-image-${Date.now()}-${messageSequence}`,
    role,
    content: '[图片]',
    fileUrl: imagePath,
    type: 'IMAGE',
    meta: '',
    createdAt: getNowDateTime(),
    time: getNowTime(),
    sendGroupId,
    sequence: messageSequence++  // 添加序号
  })
  scrollToBottom()
}

function collectLocalImageMessages() {
  const saved = loadConversationState(getConversationKey())
  const candidates = [
    ...messages.value,
    ...(Array.isArray(saved?.messages) ? saved.messages : [])
  ]
  const seen = new Set()
  return candidates.filter((message) => {
    if (message?.type !== 'IMAGE' || !message.fileUrl) return false
    const key = `${message.role || 'user'}:${message.fileUrl}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

function goBack() {
  uni.navigateBack()
}

function copyOrderNo() {
  if (!orderInfo.value.orderNo) return
  uni.setClipboardData({
    data: orderInfo.value.orderNo,
    success: () => uni.showToast({ title: '已复制', icon: 'success' })
  })
}

function buildFallbackOrder(options = {}) {
  const item = {
    productName: decodeURIComponent(options.productName || ''),
    productImage: decodeURIComponent(options.productIcon || ''),
    productSpec: decodeURIComponent(options.productSpec || ''),
    price: options.amount || '0.00',
    quantity: 1
  }
  const orderNo = decodeURIComponent(options.orderNo || '')
  if (!orderNo && !item.productName) return null
  return {
    orderId: options.orderId || '',
    ticketId: options.ticketId || '',
    orderNo,
    merchantCode: decodeURIComponent(options.merchantCode || ''),
    merchantDisplayName: decodeURIComponent(options.merchantDisplayName || ''),
    payAmount: options.amount || item.price || '0.00',
    status: decodeURIComponent(options.status || 'RECEIVED'),
    statusText: decodeURIComponent(options.statusText || '售后中'),
    items: [item]
  }
}

function applyOrderToView(order) {
  const item = order?.items?.[0] || {}
  orderData.value = order
  orderInfo.value = {
    productName: item.productName || '',
    orderNo: order?.orderNo || '',
    productIcon: item.productImage || '',
    merchantCode: order?.merchantCode || '',
    merchantDisplayName: order?.merchantDisplayName || '',
    statusText: order?.statusText || ''
  }
  hasOrder.value = Boolean(order)
}

function attachAfterSaleContext(order, options = {}) {
  if (!order) return order
  const ticketId = options.ticketId || order.ticketId || ''
  if (!ticketId) return order
  return {
    ...order,
    ticketId: String(ticketId),
    hasOpenAfterSales: true,
    afterSalesStatus: order.afterSalesStatus || options.afterSalesStatus || 'PENDING_REVIEW'
  }
}

async function loadOrderById(orderId, fallbackOptions = {}) {
  const expectedOrderNo = decodeURIComponent(fallbackOptions.orderNo || '')
  try {
    const order = await request({ url: '/orders/' + orderId })
    if (expectedOrderNo && order?.orderNo && String(order.orderNo) !== expectedOrderNo) {
      const fallbackOrder = buildFallbackOrder({ ...fallbackOptions, orderId })
      if (fallbackOrder) {
        applyOrderToView(fallbackOrder)
        return
      }
    }
    applyOrderToView(attachAfterSaleContext(order, fallbackOptions))
  } catch (error) {
    const fallbackOrder = buildFallbackOrder({ ...fallbackOptions, orderId })
    if (fallbackOrder) {
      applyOrderToView(fallbackOrder)
      return
    }
    throw error
  }
}

async function initAgentStatus() {
  try {
    const result = await checkAgentHealth()
    agentStatusText.value = result?.ok ? '服务正常' : '服务异常'
  } catch (error) {
    agentStatusText.value = '未连接'
  }
}

function updateAgentStatusForMode() {
  if (sessionMode.value === 'HUMAN') {
    agentStatusText.value = '人工客服接入中'
  }
}

function syncSessionMode(mode, status) {
  const normalizedMode = String(mode || '').toUpperCase()
  const normalizedStatus = String(status || '').toUpperCase()
  if (
    normalizedMode === 'HUMAN' ||
    ['WAITING', 'PROCESSING', 'AWAITING_EVALUATION', 'READY_TO_CLOSE'].includes(normalizedStatus)
  ) {
    sessionMode.value = 'HUMAN'
    updateAgentStatusForMode()
  }
}

function restoreConversation() {
  const saved = loadConversationState(getConversationKey())
  if (!saved) return false
  sessionId.value = saved.sessionId || null
  humanRequestCount.value = saved.humanRequestCount || 0
  sessionMode.value = saved.sessionMode || 'AI'
  messages.value = Array.isArray(saved.messages) ? saved.messages : []
  attachments.value = Array.isArray(saved.attachments) ? saved.attachments : []
  lastImageReview.value = saved.lastImageReview || null

  // 初始化messageSequence为已有消息数量
  messageSequence = messages.value.length

  scrollToBottom()
  updateAgentStatusForMode()
  return messages.value.length > 0
}

function persistConversation() {
  saveConversationState(getConversationKey(), {
    sessionId: sessionId.value,
    humanRequestCount: humanRequestCount.value,
    sessionMode: sessionMode.value,
    messages: messages.value,
    attachments: attachments.value,
    lastImageReview: lastImageReview.value
  })
}

async function loadSessionHistory(id) {
  if (!id) return false
  try {
    const localImages = collectLocalImageMessages()
    const result = await getChatHistory(id)
    sessionId.value = String(id)
    syncSessionMode(result?.mode, result?.status)
    const remoteMessages = (result.list || []).map((item, index) => ({
        key: `remote-${item.messageId || index}`,
        messageId: item.messageId,
        role: item.role === 'user' || item.role === 'USER' ? 'user' : 'service',
        content: item.content,
        fileUrl: item.fileUrl || '',
        type: item.messageType === 'IMAGE' || item.type === 'IMAGE' ? 'IMAGE' : 'TEXT',
        meta: '',
        createdAt: item.createTime || '',
        time: item.createTime ? String(item.createTime).slice(11, 16) : '',
        sequence: index
      }))
    messages.value = mergePersistedChatHistory(remoteMessages, localImages)
    scrollToBottom()
    connectChatSocket()
    return true
  } catch (error) {
    return false
  }
}

function collectRemoteServiceMessageIds() {
  return new Set(
    messages.value
      .filter((message) => message.role === 'service' && message.messageId)
      .map((message) => String(message.messageId))
  )
}

function waitFor(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds))
}

async function waitForPersistedServiceReply(targetSessionId, knownMessageIds, maxAttempts = 15) {
  const generation = ++historyRefreshGeneration
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    if (generation !== historyRefreshGeneration) return false
    if (attempt > 0) {
      await waitFor(1000)
    }
    const loaded = await loadSessionHistory(targetSessionId)
    if (!loaded) continue
    const hasNewReply = messages.value.some(
      (message) =>
        message.role === 'service' &&
        message.messageId &&
        !knownMessageIds.has(String(message.messageId))
    )
    if (hasNewReply) return true
  }
  return false
}

function readAuthToken() {
  try {
    return uni.getStorageSync('token') || ''
  } catch (error) {
    return ''
  }
}

function connectChatSocket() {
  if (!sessionId.value) return
  const targetSessionId = String(sessionId.value)
  if (chatSocketTask && chatSocketSessionId === targetSessionId) return
  closeChatSocket()
  const token = readAuthToken()
  if (!token) return
  chatSocketSessionId = targetSessionId
  chatSocketTask = uni.connectSocket({
    url: `${getChatWebSocketUrl()}?token=${encodeURIComponent(token)}`,
    complete: () => {}
  })
  chatSocketTask.onOpen(() => {
    chatSocketTask?.send({
      data: JSON.stringify({ action: 'subscribe', sessionId: targetSessionId })
    })
  })
  chatSocketTask.onMessage(async (event) => {
    let payload = {}
    try {
      payload = JSON.parse(event.data || '{}')
    } catch (error) {
      return
    }
    if (String(payload.action || '') !== 'message') return
    await loadSessionHistory(targetSessionId)
    await refreshAfterSalesSnapshot()
  })
  chatSocketTask.onClose(() => {
    chatSocketTask = null
    chatSocketSessionId = ''
  })
  chatSocketTask.onError(() => {
    closeChatSocket()
  })
}

function closeChatSocket() {
  const task = chatSocketTask
  chatSocketTask = null
  chatSocketSessionId = ''
  if (task) {
    try {
      task.close()
    } catch (error) {}
  }
}

async function refreshAfterSalesSnapshot() {
  const ticketId = orderData.value?.ticketId
  if (!ticketId) return
  try {
    const ticket = await request({ url: `/aftersales/${ticketId}` })
    if (!ticket) return
    const display = resolveAfterSalesTicketDisplay(ticket)
    orderData.value = {
      ...(orderData.value || {}),
      ticketId: String(ticket.ticketId || ticketId),
      afterSalesStatus: ticket.status,
      statusText: display.statusText
    }
    orderInfo.value = {
      ...orderInfo.value,
      statusText: display.statusText
    }
  } catch (error) {}
}

async function resolveRemoteSession(options) {
  if (options.sessionId) {
    return await loadSessionHistory(options.sessionId)
  }
  const ticketId = options.ticketId
  if (!options.orderId && !ticketId) {
    return false
  }
  try {
    const result = await createChatSession({
      orderId: options.orderId ? String(options.orderId) : null,
      ticketId: ticketId ? String(ticketId) : null,
      merchantCode: options.merchantCode ? decodeURIComponent(options.merchantCode) : ''
    })
    if (!result?.sessionId) return false
    sessionId.value = String(result.sessionId)
    evaluationPending.value = result.status === 'AWAITING_EVALUATION'
    syncSessionMode(result.mode, result.status)
    return await loadSessionHistory(result.sessionId)
  } catch (error) {
    return false
  }
}

function emotionLabelText(label) {
  const normalized = String(label || '').trim().toUpperCase()
  const labelMap = {
    SATISFIED: '满意',
    CALM: '平稳',
    NEUTRAL: '中性',
    ANXIOUS: '着急',
    DISSATISFIED: '不满',
    ANGRY: '愤怒'
  }
  return labelMap[normalized] || ''
}

function buildReplyMeta(result) {
  const tags = []
  const emotionLabel = emotionLabelText(result?.emotion?.label)
  if (emotionLabel) {
    tags.push(`情绪:${emotionLabel}`)
  }
  if (result?.fallback_need_human || result?.emotion?.need_human_priority) {
    tags.push('优先处理')
  }
  return tags.join(' · ')
}

async function chooseImage() {
  uni.chooseImage({
    count: 3 - attachments.value.length,
    sizeType: ['compressed'],
    sourceType: ['album', 'camera'],
    success: (res) => {
      attachments.value = [...attachments.value, ...(res.tempFilePaths || [])].slice(0, 3)
      persistConversation()
    }
  })
}

function removeImage(index) {
  attachments.value.splice(index, 1)
  persistConversation()
}

function previewImage(index) {
  uni.previewImage({
    current: index,
    urls: attachments.value.map(normalizeImageUrl)
  })
}

function previewMessageImage(imagePath) {
  uni.previewImage({
    current: normalizeImageUrl(imagePath),
    urls: [normalizeImageUrl(imagePath)]
  })
}

async function reviewSelectedImages(order, imagePaths = attachments.value) {
  if (!imagePaths.length) return null
  const attachmentPayload = await buildAttachments(imagePaths)
  const result = await reviewImages({
    attachments: attachmentPayload,
    order_hint: buildOrderHint({
      order_id: order.orderId,
      product_name: order.items?.[0]?.productName || ''
    })
  })
  return {
    attachments: attachmentPayload,
    imageReview: result.image_review || null
  }
}

function hasSuccessfulImageReview(imageReview) {
  return Boolean(imageReview?.success)
}

function evidenceFromImageReview(imageReview) {
  if (!imageReview?.success) return []
  const evidence = []
  if (imageReview.has_damage_area) evidence.push('破损照片')
  if (imageReview.has_outer_package) evidence.push('外包装照片')
  if (imageReview.has_logistics_label) evidence.push('物流面单照片')
  return evidence
}

function mergeUploadedEvidence(extraEvidence, imageReview) {
  const provided = Array.isArray(extraEvidence)
    ? extraEvidence
    : (extraEvidence ? [extraEvidence] : [])
  return [...new Set([...provided, ...evidenceFromImageReview(imageReview)])]
}

function buildRecentHistoryPayload() {
  return messages.value.filter((message) => message.type !== 'IMAGE').slice(-8).map((message) => ({
    role: message.role === 'service' ? 'assistant' : message.role,
    content: message.content || ''
  })).filter((message) => message.role && message.content)
}

async function applyChatResult(result) {
  if (result?.persistence?.session_id) {
    sessionId.value = String(result.persistence.session_id)
  }
  if (result?.ticket?.ticket_id && orderData.value?.orderNo) {
    uni.setStorageSync(`after_sales_ticket:${orderData.value.orderNo}`, result.ticket)
  }
  if (result?.fallback_need_human) {
    humanRequestCount.value = Math.max(humanRequestCount.value, 2)
    sessionMode.value = 'HUMAN'
    updateAgentStatusForMode()
  }
  if (result?.session_mode === 'HUMAN') {
    sessionMode.value = 'HUMAN'
    updateAgentStatusForMode()
  }
  if (sessionId.value) {
    const loaded = await loadSessionHistory(sessionId.value)
    if (loaded) {
      persistConversation()
      return
    }
  }
  if (sessionMode.value === 'HUMAN') {
    if (result?.assistant_reply) {
      addMessage('service', result.assistant_reply)
    }
  } else {
    const assistantReply = result?.assistant_reply || '已收到您的问题'
    addMessage('service', assistantReply, buildReplyMeta(result))

    // 如果有ticket且状态为PROCESSING，展示AI建议
    if (result?.ticket && result.ticket.status === 'PROCESSING' && result.ticket.audit_opinion) {
      addMessage('service', result.ticket.audit_opinion, '', true)
    }
  }
  persistConversation()
}

async function runDeferredImageReview(imagePaths) {
  if (!orderData.value || !imagePaths.length || deferredReviewRunning.value) return
  deferredReviewRunning.value = true
  try {
    const reviewResult = await reviewSelectedImages(orderData.value, imagePaths)
    if (hasSuccessfulImageReview(reviewResult?.imageReview)) {
      lastImageReview.value = reviewResult.imageReview
    }
    persistConversation()
  } catch (error) {
    persistConversation()
  } finally {
    deferredReviewRunning.value = false
  }
}

function createSupplementRequestId() {
  return `supp-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

async function submitTicketSupplement({
  text,
  imagePaths = attachments.value,
  renderLocal = true
}) {
  const ticketId = String(orderData.value?.ticketId || '').trim()
  if (!ticketId) {
    throw new Error('售后工单尚未建立，请稍后重试')
  }
  if (!sessionId.value) {
    const session = await createChatSession({
      orderId: orderData.value?.orderId ? String(orderData.value.orderId) : null,
      ticketId,
      merchantCode: orderData.value?.merchantCode || orderInfo.value?.merchantCode || ''
    })
    if (session?.sessionId) {
      sessionId.value = String(session.sessionId)
      syncSessionMode(session.mode, session.status)
    }
  }
  if (!sessionId.value) {
    throw new Error('售后会话尚未建立，请稍后重试')
  }

  const normalizedText = text === '[图片]' ? '' : String(text || '').trim()
  if (renderLocal) {
    const sendGroupId = `supplement-${Date.now()}-${messageSequence}`
    imagePaths.forEach((imagePath) => addImageMessage('user', imagePath, sendGroupId))
    if (normalizedText) {
      addMessage('user', normalizedText, '', false, sendGroupId)
    }
    persistConversation()
  }

  const uploadedAttachments = imagePaths.length > 0
    ? await buildAttachments(imagePaths)
    : []
  const result = await request({
    url: `/aftersales/${ticketId}/supplements`,
    method: 'POST',
    data: {
      requestId: createSupplementRequestId(),
      sessionId: String(sessionId.value),
      message: normalizedText,
      attachmentUrls: uploadedAttachments
        .map((attachment) => attachment.file_url)
        .filter(Boolean)
    }
  })

  attachments.value = []
  await loadSessionHistory(sessionId.value)
  await refreshAfterSalesSnapshot()
  persistConversation()
  return result
}

async function sendAgentMessage({
  text,
  description = text,
  imagePaths = attachments.value,
  selectedOrderExtra = {},
  allowFallbackToDeferredReview = true,
  renderLocal = true
}) {
  const hasImages = Array.isArray(imagePaths) && imagePaths.length > 0
  if (renderLocal) {
    const sendGroupId = `send-${Date.now()}-${messageSequence}`
    // 图文同时发送时先展示图片，再展示文字描述，避免历史回填后顺序错乱
    imagePaths.forEach((imagePath) => addImageMessage('user', imagePath, sendGroupId))
    // 如果text是占位符[图片]，不渲染
    if (text && text !== '[图片]') {
      addMessage('user', text, '', false, sendGroupId)
    }
    persistConversation()
  }
  if (sessionMode.value === 'HUMAN') {
    if (!sessionId.value) {
      const session = await createChatSession({
        orderId: orderData.value?.orderId ? String(orderData.value.orderId) : null,
        ticketId: orderData.value?.ticketId
          ? String(orderData.value.ticketId)
          : null,
        merchantCode: orderData.value?.merchantCode || orderInfo.value?.merchantCode || ''
      })
      if (session?.sessionId) {
        sessionId.value = String(session.sessionId)
        syncSessionMode(session.mode, session.status)
      }
    }
    if (!sessionId.value) {
      throw new Error('人工会话尚未建立，请稍后再试')
    }
    if (hasImages) {
      const humanAttachments = await buildAttachments(imagePaths)
      await chat(
        buildChatPayload({
          order: orderData.value,
          message: text,
          description,
          sessionId: sessionId.value,
          humanRequestCount: humanRequestCount.value,
          attachments: humanAttachments,
          imageReview: null,
          skipImageReview: true,
          recentHistory: buildRecentHistoryPayload(),
          selectedOrderExtra
        })
      )
    } else if (text) {
      await sendChatMessage({
        sessionId: sessionId.value,
        message: text,
        messageType: 'TEXT'
      })
    }
    await loadSessionHistory(sessionId.value)
    attachments.value = []
    persistConversation()
    return { session_mode: 'HUMAN', assistant_reply: '' }
  }
  let attachmentPayload = []
  let imageReview = null
  let skipImageReview = !hasImages || sessionMode.value === 'HUMAN'

  if (hasImages && orderData.value && sessionMode.value !== 'HUMAN') {
    const reviewResult = await reviewSelectedImages(orderData.value, imagePaths)
    attachmentPayload = reviewResult ? reviewResult.attachments : []
    imageReview = reviewResult ? reviewResult.imageReview : null
    if (hasSuccessfulImageReview(imageReview)) {
      lastImageReview.value = imageReview
    }
  } else if (hasImages && attachmentPayload.length === 0) {
    attachmentPayload = await buildAttachments(imagePaths)
  } else if (lastImageReview.value) {
    imageReview = lastImageReview.value
  }

  try {
    const result = await chat(
      buildChatPayload({
        order: orderData.value,
        message: text,
        description,
        sessionId: sessionId.value,
        humanRequestCount: humanRequestCount.value,
        attachments: skipImageReview ? [] : attachmentPayload,
        imageReview,
        skipImageReview,
        recentHistory: buildRecentHistoryPayload(),
        selectedOrderExtra: {
          ...selectedOrderExtra,
          uploadedEvidence: mergeUploadedEvidence(selectedOrderExtra.uploadedEvidence, imageReview)
        }
      })
    )

    await applyChatResult(result)
    attachments.value = []
    persistConversation()
    return result
  } catch (error) {
    if (hasImages && allowFallbackToDeferredReview) {
      const fallbackResult = await chat(
        buildChatPayload({
          order: orderData.value,
          message: text,
          description,
          sessionId: sessionId.value,
          humanRequestCount: humanRequestCount.value,
          attachments: [],
          imageReview: null,
          skipImageReview: true,
          recentHistory: buildRecentHistoryPayload(),
          selectedOrderExtra: {
            ...selectedOrderExtra,
            uploadedEvidence: mergeUploadedEvidence(selectedOrderExtra.uploadedEvidence, lastImageReview.value)
          }
        })
      )
      await applyChatResult(fallbackResult)
      attachments.value = []
      persistConversation()
      void runDeferredImageReview(imagePaths)
      return fallbackResult
    }
    throw error
  }
}

async function consumePendingApply(orderId) {
  const key = getPendingApplyKey(orderId)
  const pending = uni.getStorageSync(key)
  if (!pending || processingPendingApply.value) return

  processingPendingApply.value = true
  uni.removeStorageSync(key)

  const imagePaths = Array.isArray(pending.imagePaths) ? pending.imagePaths : []
  const userProblem = String(pending.description || pending.initialMessage || pending.reasonLabel || '').trim()

  try {
    // 工单中的图片属于补充材料，提交 Java 事务后由 Kafka -> LangGraph 正式复审。
    if (imagePaths.length > 0) {
      await submitTicketSupplement({
        text: userProblem || pending.initialMessage || '我已上传售后凭证，请AI客服分析。',
        imagePaths,
        renderLocal: true
      })
    } else {
      // 售后审核由 Kafka -> LangGraph 正式审核链路处理。这里仅把用户提交的
      // 原因写入 Java/MySQL 会话，避免同时触发普通咨询 RAG 抢先转人工。
      if (!sessionId.value) {
        throw new Error('售后会话尚未建立，请稍后重试')
      }
      const knownServiceMessageIds = collectRemoteServiceMessageIds()
      await sendChatMessage({
        sessionId: sessionId.value,
        message: userProblem || pending.initialMessage || '我的售后申请已提交',
        messageType: 'TEXT'
      })
      await waitForPersistedServiceReply(sessionId.value, knownServiceMessageIds)
      persistConversation()
    }
  } catch (error) {
    addMessage('service', error.message || '当前暂时无法获取处理结果，请稍后再试。')
    persistConversation()
  } finally {
    processingPendingApply.value = false
  }
}

async function sendMessage() {
  const typedText = inputText.value.trim()
  if ((!typedText && attachments.value.length === 0) || sending.value) return

  // 完全不自动添加文字，用户没输入就不发送文本消息
  const text = typedText

  if (text && /人工|客服|真人/.test(text)) {
    humanRequestCount.value += 1
  }

  const imagePaths = [...attachments.value]
  inputText.value = ''
  sending.value = true

  try {
    // 如果用户没输入文字但上传了图片，传给后端一个占位符（后端要求message非空）
    // 但本地不渲染这个占位符
    const messageText = text || (imagePaths.length > 0 ? '[图片]' : '')

    if (orderData.value?.ticketId) {
      await submitTicketSupplement({
        text: messageText,
        imagePaths,
        renderLocal: true
      })
    } else {
      await sendAgentMessage({
        text: messageText,
        description: text || '用户上传了图片',
        imagePaths,
        selectedOrderExtra: {
          existingTicketNo: orderData.value?.latestTicketNo || '',
          hasOpenAfterSales: orderData.value?.hasOpenAfterSales || false,
          afterSalesStatus: orderData.value?.afterSalesStatus || ''
        },
        renderLocal: true
      })
    }
  } catch (error) {
    addMessage('service', error.message || '消息发送失败，请稍后重试')
  } finally {
    sending.value = false
  }
}

function quickAction(type) {
  if (type === 'supplement') {
    chooseImage()
    return
  }

  const map = {
    refund: '请帮我查看退款进度',
    human: '请帮我转人工客服'
  }
  inputText.value = map[type] || ''
  sendMessage()
}

function submitEvaluation() {
  if (!sessionId.value) return
  const params = [
    'sessionId=' + encodeURIComponent(sessionId.value || ''),
    'orderId=' + encodeURIComponent(orderData.value?.orderId || ''),
    'ticketId=' + encodeURIComponent(orderData.value?.ticketId || ''),
    'orderNo=' + encodeURIComponent(orderInfo.value.orderNo || ''),
    'productName=' + encodeURIComponent(orderInfo.value.productName || ''),
    'productIcon=' + encodeURIComponent(orderInfo.value.productIcon || '')
  ].join('&')
  uni.navigateTo({ url: `/pages/chat/evaluate?${params}` })
}

onLoad(async (options) => {
  await initAgentStatus()

  if (options.orderId) {
    await loadOrderById(options.orderId, options)
  }

  evaluationPending.value = options.status === 'AWAITING_EVALUATION'
  const hasRemoteConversation = await resolveRemoteSession(options)
  const hasSavedConversation = hasRemoteConversation ? true : restoreConversation()
  if (!hasSavedConversation) {
    addMessage('service', '您可以描述具体问题并补充图片，我会结合订单和材料给您回复。')
  }

  if (options.fromApply === '1' && options.orderId) {
    await consumePendingApply(options.orderId)
  }
})

onUnload(() => {
  historyRefreshGeneration += 1
  closeChatSocket()
})
</script>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: #f0eeea;
}

.nav-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 32rpx 28rpx;
  background: #ffffff;
  border-bottom: 1rpx solid rgba(0, 0, 0, 0.06);
}

.back-btn,
.nav-right {
  width: 64rpx;
  height: 64rpx;
}

.back-btn {
  line-height: 64rpx;
  text-align: center;
  border-radius: 16rpx;
  background: #f5f3ef;
}

.back-icon,
.nav-title {
  color: #1a1a1a;
}

.back-icon {
  font-size: 32rpx;
}

.nav-title {
  font-size: 32rpx;
  font-weight: 800;
}

.fixed-context {
  flex: none;
  background: #f0eeea;
  z-index: 2;
}

.order-card {
  display: flex;
  align-items: center;
  margin: 20rpx 24rpx 12rpx;
  padding: 20rpx;
  background: #ffffff;
  border-radius: 16rpx;
  border: 1rpx solid rgba(0, 0, 0, 0.04);
}

.order-product-img {
  width: 80rpx;
  height: 80rpx;
  flex: none;
  border-radius: 12rpx;
  background: #f5f3ef;
}

.order-product-info {
  flex: 1;
  min-width: 0;
  margin-left: 18rpx;
}

.order-product {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 28rpx;
  font-weight: 700;
  color: #1a1a1a;
}

.merchant-text {
  display: block;
  margin-top: 6rpx;
  font-size: 22rpx;
  color: #8a776c;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.order-row {
  display: flex;
  align-items: center;
  min-width: 0;
  margin-top: 8rpx;
  gap: 8rpx;
}

.order-no,
.copy-icon,
.order-status,
.online-text,
.msg-time,
.msg-meta,
.upload-tip {
  font-size: 22rpx;
}

.order-no {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.order-no,
.copy-icon,
.upload-tip {
  color: #999;
}

.order-status {
  flex: none;
  color: #c97b5a;
  font-weight: 600;
}

.service-header {
  display: flex;
  align-items: center;
  padding: 16rpx 28rpx;
}

.service-name {
  display: block;
  font-size: 26rpx;
  font-weight: 700;
  color: #1a1a1a;
}

.online-dot {
  display: flex;
  align-items: center;
  margin-top: 8rpx;
}

.dot {
  width: 12rpx;
  height: 12rpx;
  border-radius: 50%;
  background: #52c41a;
}

.online-text {
  margin-left: 8rpx;
  color: #52c41a;
}

.chat-area {
  flex: 1;
  min-height: 0;
  padding: 8rpx 0 20rpx;
  overflow-y: auto;
}

.msg-group {
  margin-bottom: 18rpx;
  padding: 0 24rpx;
  box-sizing: border-box;
}

.msg-time {
  display: block;
  text-align: center;
  color: #bbb;
  font-size: 22rpx;
  margin: 12rpx 0 14rpx;
}

.message {
  display: flex;
  margin-bottom: 10rpx;
}

.message.user {
  justify-content: flex-end;
}

.msg-bubble {
  max-width: 76%;
  padding: 18rpx 22rpx;
  border-radius: 18rpx;
  word-break: break-all;
}

.ai-suggestion-bubble {
  background: linear-gradient(135deg, #fff9f0 0%, #fff4e8 100%);
  border: 2rpx solid #f4d9b8;
  padding: 24rpx;
}

.ai-suggestion-content {
  display: flex;
  flex-direction: column;
  gap: 16rpx;
}

.suggestion-header {
  display: flex;
  align-items: center;
  gap: 12rpx;
  padding-bottom: 12rpx;
  border-bottom: 1rpx solid rgba(201, 123, 90, 0.2);
}

.suggestion-icon {
  font-size: 32rpx;
}

.suggestion-title {
  font-size: 26rpx;
  font-weight: 700;
  color: #c97b5a;
}

.suggestion-note {
  font-size: 22rpx;
  color: #999;
  font-style: italic;
  padding-top: 8rpx;
  border-top: 1rpx solid rgba(0, 0, 0, 0.06);
}

.message.service .msg-bubble {
  background: #ffffff;
}

.message.user .msg-bubble {
  background: #fff5f0;
}

.msg-image {
  display: block;
  width: 200rpx;
  height: 200rpx;
  border-radius: 16rpx;
  background: #f5f3ef;
}

.image-bubble {
  padding: 8rpx;
  max-width: 60%;
  background: transparent;
}

.msg-text {
  display: block;
  font-size: 28rpx;
  line-height: 1.7;
  color: #1a1a1a;
  overflow-wrap: anywhere;
}

.msg-meta {
  display: block;
  margin-top: 10rpx;
  font-size: 22rpx;
  color: #8d6e63;
  line-height: 1.5;
}

.quick-actions {
  display: flex;
  gap: 14rpx;
  padding: 12rpx 24rpx;
  background: rgba(240, 238, 234, 0.96);
}

.action-btn {
  flex: 1;
  min-width: 0;
  height: 64rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8rpx;
  background: #ffffff;
  border-radius: 32rpx;
  border: 1rpx solid rgba(0, 0, 0, 0.06);
}

.review-action {
  background: #fff4e8;
}

.action-text {
  font-size: 22rpx;
  color: #1a1a1a;
  font-weight: 500;
}

.action-icon {
  font-size: 24rpx;
  color: #c97b5a;
  font-weight: 800;
}

.action-image-icon {
  width: 24rpx;
  height: 24rpx;
  flex-shrink: 0;
}

.attachment-preview {
  display: flex;
  align-items: center;
  gap: 16rpx;
  padding: 12rpx 24rpx 6rpx;
  background: rgba(240, 238, 234, 0.96);
}

.upload-tip {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.image-grid {
  display: flex;
  gap: 16rpx;
  flex-wrap: wrap;
}

.image-item {
  width: 72rpx;
  height: 72rpx;
  position: relative;
}

.preview-img {
  border-radius: 14rpx;
}

.preview-img {
  width: 100%;
  height: 100%;
}

.delete-btn {
  position: absolute;
  top: -12rpx;
  right: -12rpx;
  width: 36rpx;
  height: 36rpx;
  line-height: 36rpx;
  text-align: center;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.6);
  color: #ffffff;
  font-size: 24rpx;
}

.input-area {
  display: flex;
  align-items: center;
  gap: 14rpx;
  padding: 16rpx 24rpx;
  padding-bottom: calc(16rpx + env(safe-area-inset-bottom));
  background: #ffffff;
  border-top: 1rpx solid rgba(0, 0, 0, 0.06);
}

.attach-btn {
  width: 64rpx;
  height: 64rpx;
  line-height: 60rpx;
  text-align: center;
  border-radius: 50%;
  background: #f5f3ef;
  border: 1rpx solid rgba(0, 0, 0, 0.06);
  flex: none;
}

.attach-icon {
  color: #c97b5a;
  font-size: 38rpx;
  font-weight: 300;
}

.chat-input {
  flex: 1;
  height: 68rpx;
  padding: 0 24rpx;
  background: #f5f3ef;
  border-radius: 36rpx;
  font-size: 26rpx;
}

.send-btn {
  width: 64rpx;
  height: 64rpx;
  line-height: 64rpx;
  text-align: center;
  border-radius: 50%;
  background: #e0e0e0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.send-btn.active {
  background: linear-gradient(135deg, #c97b5a, #b86a4a);
}

.send-icon {
  color: #ffffff;
  font-size: 28rpx;
  font-weight: 700;
}
</style>
