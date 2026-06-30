<template>
  <view class="page">
    <view class="nav-bar">
      <view class="back-btn" @tap="goBack">
        <text class="back-icon">←</text>
      </view>
      <text class="nav-title">智能售后助手</text>
      <view class="nav-right"></view>
    </view>

    <view v-if="hasOrder" class="order-card">
      <image class="order-product-img" :src="orderInfo.productIcon" mode="aspectFill" />
      <view class="order-product-info">
        <text class="order-product">{{ orderInfo.productName }}</text>
        <view class="order-row">
          <text class="order-no">订单号：{{ orderInfo.orderNo }}</text>
          <text class="copy-icon" @tap="copyOrderNo">复制</text>
          <text class="order-status">{{ orderInfo.statusText }}</text>
        </view>
      </view>
    </view>

    <view class="service-header">
      <view class="service-info">
        <text class="service-name">售后 Agent 在线</text>
        <view class="online-dot">
          <view class="dot"></view>
          <text class="online-text">{{ agentStatusText }}</text>
        </view>
      </view>
    </view>

    <scroll-view class="chat-area" scroll-y :scroll-top="scrollTop" scroll-with-animation>
      <view v-for="(msg, index) in messages" :key="index" class="msg-group">
        <text v-if="msg.time" class="msg-time">{{ msg.time }}</text>
        <view class="message" :class="msg.role">
          <view class="msg-bubble">
            <text class="msg-text">{{ msg.content }}</text>
            <text v-if="msg.meta" class="msg-meta">{{ msg.meta }}</text>
          </view>
        </view>
      </view>
    </scroll-view>

    <view class="quick-actions">
      <view class="action-btn" @tap="quickAction('refund')">
        <text class="action-text">退款进度</text>
      </view>
      <view class="action-btn" @tap="quickAction('supplement')">
        <text class="action-text">补充凭证</text>
      </view>
      <view class="action-btn" @tap="quickAction('human')">
        <text class="action-text">人工帮助</text>
      </view>
    </view>

    <view class="upload-area">
      <view class="upload-header">
        <text class="upload-title">凭证图片</text>
        <text class="upload-tip">最多 3 张，优先做快速分析</text>
      </view>
      <view class="image-grid">
        <view v-for="(img, index) in attachments" :key="img" class="image-item">
          <image :src="img" mode="aspectFill" class="preview-img" @tap="previewImage(index)" />
          <view class="delete-btn" @tap.stop="removeImage(index)">×</view>
        </view>
        <view v-if="attachments.length < 3" class="add-image" @tap="chooseImage">
          <text class="add-icon">+</text>
        </view>
      </view>
    </view>

    <view class="input-area">
      <input
        v-model="inputText"
        class="chat-input"
        placeholder="请输入您的售后问题"
        confirm-type="send"
        @confirm="sendMessage"
      />
      <view class="send-btn" :class="{ active: canSend }" @tap="sendMessage">
        <text class="send-icon">{{ sending ? '...' : '发送' }}</text>
      </view>
    </view>
  </view>
</template>

<script setup>
import { computed, nextTick, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { request } from '../../utils/request'
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
const processingPendingApply = ref(false)
const deferredReviewRunning = ref(false)

const orderInfo = ref({
  productName: '',
  orderNo: '',
  productIcon: '',
  statusText: ''
})

const canSend = computed(() => inputText.value.trim() && !sending.value)

function getNowTime() {
  const now = new Date()
  return `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`
}

function getConversationKey() {
  if (orderData.value && orderData.value.orderNo) return orderData.value.orderNo
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

function addMessage(role, content, meta = '') {
  messages.value.push({
    role,
    content,
    meta,
    time: getNowTime()
  })
  scrollToBottom()
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

async function loadOrderById(orderId) {
  const order = await request({ url: '/orders/' + orderId })
  const item = order && order.items && order.items[0] ? order.items[0] : {}
  orderData.value = order
  orderInfo.value = {
    productName: item.productName || '',
    orderNo: order.orderNo || '',
    productIcon: item.productImage || '',
    statusText: order.statusText || ''
  }
  hasOrder.value = Boolean(order)
}

async function initAgentStatus() {
  try {
    const result = await checkAgentHealth()
    agentStatusText.value = result && result.ok ? '服务正常' : '服务异常'
  } catch (error) {
    agentStatusText.value = '未连接'
  }
}

function restoreConversation() {
  const saved = loadConversationState(getConversationKey())
  if (!saved) return false
  sessionId.value = saved.sessionId || null
  humanRequestCount.value = saved.humanRequestCount || 0
  messages.value = Array.isArray(saved.messages) ? saved.messages : []
  attachments.value = Array.isArray(saved.attachments) ? saved.attachments : []
  scrollToBottom()
  return messages.value.length > 0
}

function persistConversation() {
  saveConversationState(getConversationKey(), {
    sessionId: sessionId.value,
    humanRequestCount: humanRequestCount.value,
    messages: messages.value,
    attachments: attachments.value
  })
}

function buildReplyMeta(result) {
  const parts = []
  if (result.suggested_action) parts.push(`建议：${result.suggested_action}`)
  if (Array.isArray(result.evidence_needed) && result.evidence_needed.length > 0) {
    parts.push(`还需：${result.evidence_needed.join('、')}`)
  }
  if (result.ticket && result.ticket.ticket_id) {
    parts.push(`工单：${result.ticket.ticket_id}`)
  }
  if (result.fallback_need_human) {
    parts.push('已建议人工介入')
  }
  return parts.join(' | ')
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
    urls: attachments.value
  })
}

async function reviewSelectedImages(order, imagePaths = attachments.value) {
  if (!imagePaths.length) return null
  const attachmentPayload = await buildAttachments(imagePaths)
  const result = await reviewImages({
    attachments: attachmentPayload,
    order_hint: buildOrderHint({
      order_id: order.orderNo,
      product_name: order.items && order.items[0] ? order.items[0].productName : ''
    })
  })
  return {
    attachments: attachmentPayload,
    imageReview: result.image_review || null
  }
}

function hasSuccessfulImageReview(imageReview) {
  return Boolean(imageReview && imageReview.success)
}

function applyChatResult(result) {
  if (result && result.persistence && result.persistence.session_id) {
    sessionId.value = result.persistence.session_id
  }
  if (result && result.ticket && result.ticket.ticket_id && orderData.value && orderData.value.orderNo) {
    uni.setStorageSync(`after_sales_ticket:${orderData.value.orderNo}`, result.ticket)
  }
  addMessage('service', result.assistant_reply || '已收到您的问题', buildReplyMeta(result))
  if (result && result.fallback_need_human) {
    humanRequestCount.value = Math.max(humanRequestCount.value, 2)
  }
  persistConversation()
}

async function runDeferredImageReview(imagePaths) {
  if (!orderData.value || !imagePaths.length || deferredReviewRunning.value) return

  deferredReviewRunning.value = true
  try {
    const reviewResult = await reviewSelectedImages(orderData.value, imagePaths)
    if (reviewResult && hasSuccessfulImageReview(reviewResult.imageReview) && reviewResult.imageReview.summary) {
      addMessage('service', `图片补充分析：${reviewResult.imageReview.summary}`)
    } else if (reviewResult && hasSuccessfulImageReview(reviewResult.imageReview)) {
      addMessage('service', '图片补充分析已完成，当前没有额外风险提示。')
    }
    persistConversation()
  } catch (error) {
    persistConversation()
  } finally {
    deferredReviewRunning.value = false
  }
}

async function sendAgentMessage({
  text,
  description = text,
  imagePaths = attachments.value,
  selectedOrderExtra = {},
  allowFallbackToDeferredReview = true
}) {
  const hasImages = Array.isArray(imagePaths) && imagePaths.length > 0
  let attachmentPayload = []
  let imageReview = null
  let skipImageReview = !hasImages

  if (hasImages && orderData.value) {
    const reviewResult = await reviewSelectedImages(orderData.value, imagePaths)
    attachmentPayload = reviewResult ? reviewResult.attachments : []
    imageReview = reviewResult ? reviewResult.imageReview : null
    if (hasSuccessfulImageReview(imageReview) && imageReview.summary) {
      addMessage('service', `快速分析：${imageReview.summary}`)
    } else if (hasSuccessfulImageReview(imageReview)) {
      addMessage('service', '图片分析已完成，当前没有额外风险提示。')
    } else {
      addMessage('service', '已收到图片，我先结合您的描述继续处理。')
    }
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
        selectedOrderExtra
      })
    )

    applyChatResult(result)
    attachments.value = []
    persistConversation()
    return result
  } catch (error) {
    if (hasImages && allowFallbackToDeferredReview) {
      addMessage('service', '已收到图片，我先结合您的描述开始处理。')
      skipImageReview = true
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
          selectedOrderExtra
        })
      )
      applyChatResult(fallbackResult)
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

  if (messages.value.length === 0) {
    addMessage('service', '已收到您的售后申请，我先帮您进入对话并开始处理。')
  }

  addMessage('user', pending.initialMessage)
  if (pending.description && pending.description !== pending.initialMessage) {
    addMessage('user', `补充说明：${pending.description}`)
  }
  if (Array.isArray(pending.imagePaths) && pending.imagePaths.length > 0) {
    addMessage('service', '图片已收到，我正在快速分析凭证内容，马上给您回复。')
  } else {
    addMessage('service', '我先根据您提交的描述开始处理，有新的分析结果会继续补充。')
  }

  try {
    const result = await sendAgentMessage({
      text: pending.initialMessage,
      description: pending.description,
      imagePaths: pending.imagePaths || [],
      selectedOrderExtra: {
        hasOpenAfterSales: false,
        uploadedEvidence: (pending.imagePaths || []).length > 0 ? ['商品照片'] : []
      }
    })

    if (pending.orderId) {
      await request({ url: `/orders/${pending.orderId}/status?status=AFTERSALE`, method: 'PUT' })
    }

    if (result && result.ticket && result.ticket.ticket_id) {
      uni.showToast({ title: '已进入售后对话', icon: 'success' })
    }
  } catch (error) {
    addMessage('service', error.message || 'Agent 调用异常，但我已经保留了您的申请，请继续发送消息。')
    persistConversation()
  } finally {
    processingPendingApply.value = false
  }
}

async function sendMessage() {
  const text = inputText.value.trim()
  if (!text || sending.value) return

  const wantsHuman = /人工|客服|真人/.test(text)
  if (wantsHuman) {
    humanRequestCount.value += 1
  }

  const imagePaths = [...attachments.value]
  addMessage('user', text)
  inputText.value = ''
  sending.value = true

  if (imagePaths.length > 0) {
    addMessage('service', '图片已收到，我正在快速分析凭证内容，马上给您回复。')
  }

  try {
    await sendAgentMessage({
      text,
      description: text,
      imagePaths
    })
  } catch (error) {
    addMessage('service', error.message || '消息发送失败，请稍后重试')
  } finally {
    sending.value = false
  }
}

function quickAction(type) {
  const map = {
    refund: '请帮我查看退款进度',
    supplement: '我想补充售后凭证图片',
    human: '请帮我转人工客服'
  }
  inputText.value = map[type] || ''
  sendMessage()
}

onLoad(async (options) => {
  await initAgentStatus()

  if (options.orderId) {
    await loadOrderById(Number(options.orderId))
  }

  const hasSavedConversation = restoreConversation()
  if (!hasSavedConversation) {
    addMessage('service', '您好，我是售后 Agent。您可以先描述问题，我会优先结合图片做快速分析，再给您正式回复。')
  }

  if (options.fromApply === '1' && options.orderId) {
    await consumePendingApply(Number(options.orderId))
  }
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

.order-card {
  display: flex;
  align-items: center;
  margin: 20rpx 28rpx 12rpx;
  padding: 24rpx;
  background: #ffffff;
  border-radius: 16rpx;
}

.order-product-img {
  width: 80rpx;
  height: 80rpx;
  border-radius: 12rpx;
}

.order-product-info {
  flex: 1;
  margin-left: 20rpx;
}

.order-product {
  display: block;
  font-size: 28rpx;
  font-weight: 700;
  color: #1a1a1a;
}

.order-row {
  display: flex;
  align-items: center;
  margin-top: 10rpx;
  gap: 10rpx;
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

.order-no,
.copy-icon,
.upload-tip {
  color: #999;
}

.order-status {
  margin-left: auto;
  color: #c97b5a;
  font-weight: 600;
}

.service-header {
  padding: 8rpx 28rpx 16rpx;
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
  padding: 0 28rpx;
}

.msg-group {
  margin-bottom: 24rpx;
}

.msg-time {
  display: block;
  text-align: center;
  color: #bbb;
  margin-bottom: 12rpx;
}

.message {
  display: flex;
}

.message.user {
  justify-content: flex-end;
}

.msg-bubble {
  max-width: 76%;
  padding: 20rpx 24rpx;
  border-radius: 20rpx;
}

.message.service .msg-bubble {
  background: #ffffff;
}

.message.user .msg-bubble {
  background: #fff5f0;
}

.msg-text {
  display: block;
  font-size: 26rpx;
  line-height: 1.6;
  color: #1a1a1a;
}

.msg-meta {
  display: block;
  margin-top: 12rpx;
  color: #8d6e63;
  line-height: 1.5;
}

.quick-actions {
  display: flex;
  gap: 16rpx;
  padding: 12rpx 28rpx;
}

.action-btn {
  flex: 1;
  height: 64rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #ffffff;
  border-radius: 32rpx;
}

.action-text {
  font-size: 22rpx;
  color: #1a1a1a;
  font-weight: 600;
}

.upload-area {
  margin: 0 28rpx 16rpx;
  padding: 20rpx 24rpx;
  background: #ffffff;
  border-radius: 18rpx;
}

.upload-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16rpx;
}

.upload-title {
  font-size: 24rpx;
  font-weight: 700;
  color: #1a1a1a;
}

.image-grid {
  display: flex;
  gap: 16rpx;
  flex-wrap: wrap;
}

.image-item,
.add-image {
  width: 120rpx;
  height: 120rpx;
  position: relative;
}

.preview-img,
.add-image {
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

.add-image {
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f5f3ef;
  border: 2rpx dashed rgba(0, 0, 0, 0.1);
}

.add-icon {
  font-size: 42rpx;
  color: #999;
}

.input-area {
  display: flex;
  align-items: center;
  gap: 16rpx;
  padding: 20rpx 28rpx;
  padding-bottom: calc(20rpx + env(safe-area-inset-bottom));
  background: #ffffff;
  border-top: 1rpx solid rgba(0, 0, 0, 0.06);
}

.chat-input {
  flex: 1;
  height: 72rpx;
  padding: 0 24rpx;
  background: #f5f3ef;
  border-radius: 36rpx;
  font-size: 26rpx;
}

.send-btn {
  min-width: 120rpx;
  height: 72rpx;
  padding: 0 24rpx;
  border-radius: 36rpx;
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
  font-size: 24rpx;
  font-weight: 700;
}
</style>
