<template>
  <view class="page">
    <!-- order info card - only when order exists -->
    <view v-if="hasOrder" class="order-card">
      <image class="order-product-img" :src="normalizeImageUrl(orderInfo.productIcon)" mode="aspectFill" />
      <view class="order-product-info">
        <text class="order-product">{{ orderInfo.productName }}</text>
        <view class="order-row">
          <text class="order-no">订单号：{{ orderInfo.orderNo }}</text>
          <text class="copy-icon" @tap="copyOrderNo">📋</text>
          <text class="order-status">{{ orderInfo.statusText }}</text>
        </view>
      </view>
    </view>

    <view v-if="chatMode === 'HUMAN'" class="human-status">
      <view :class="['status-dot', humanServiceStatus === 'ONLINE' ? 'online' : 'offline']"></view>
      <text :class="['status-text', humanServiceStatus === 'ONLINE' ? 'online' : 'offline']">
        人工{{ humanServiceStatusText }}
      </text>
    </view>

    <!-- chat area -->
    <scroll-view class="chat-area" scroll-y :scroll-top="scrollTop" scroll-with-animation>
      <view v-for="(msg, index) in messages" :key="index" class="msg-group">
        <text class="msg-time" v-if="msg.time">{{ msg.time }}</text>
        <view class="message" :class="msg.role">
          <view class="msg-bubble">
            <image
              v-if="msg.messageType === 'IMAGE'"
              class="msg-image"
              :src="normalizeImageUrl(msg.content)"
              mode="aspectFill"
              @tap="previewMessageImage(msg.content)"
            />
            <text v-else class="msg-text">{{ msg.content }}</text>
          </view>
        </view>
        <text class="msg-read" :class="{ unread: !msg.read }" v-if="msg.role === 'user'">
          {{ msg.read ? '已读' : '未读' }}
        </text>
      </view>
    </scroll-view>

    <!-- quick actions -->
    <view class="quick-actions">
      <template v-if="hasOrder">
        <view class="action-btn" @tap="quickAction('refund')">
          <text class="action-icon">🔄</text>
          <text class="action-text">退款进度</text>
        </view>
        <view class="action-btn" @tap="quickAction('supplement')">
          <image class="action-image-icon" src="/static/images/icon-supplement-voucher.png" mode="aspectFit" />
          <text class="action-text">补充凭证</text>
        </view>
        <view class="action-btn" @tap="quickAction('human')">
          <text class="action-icon">👤</text>
          <text class="action-text">人工帮助</text>
        </view>
      </template>
      <template v-else>
        <view class="action-btn" @tap="quickAction('query')">
          <text class="action-icon">🔍</text>
          <text class="action-text">查询订单</text>
        </view>
        <view class="action-btn" @tap="quickAction('aftersale')">
          <text class="action-icon">🔄</text>
          <text class="action-text">申请售后</text>
        </view>
        <view class="action-btn" @tap="quickAction('human')">
          <text class="action-icon">👤</text>
          <text class="action-text">人工帮助</text>
        </view>
      </template>
    </view>

    <!-- input area -->
    <view class="input-area">
      <view class="attach-btn" :class="{ uploading: attachmentUploading }" @tap="chooseAttachment">
        <text class="attach-icon">{{ attachmentUploading ? '…' : '+' }}</text>
      </view>
      <input
        v-model="inputText"
        class="chat-input"
        placeholder="请输入内容"
        confirm-type="send"
        @confirm="sendMessage"
      />
      <view class="send-btn" :class="{ active: inputText.trim() }" @tap="sendMessage">
        <text class="send-icon">➤</text>
      </view>
    </view>
  </view>
</template>

<script setup>
import { ref, nextTick, onUnmounted } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { BASE_URL, request, normalizeImageUrl } from '../../utils/request'

const messages = ref([])
const inputText = ref('')
const attachmentUploading = ref(false)
const scrollTop = ref(0)
const hasOrder = ref(false)
const sessionId = ref(null)
const chatMode = ref('AI')
const humanServiceStatus = ref('OFFLINE')
const humanServiceStatusText = ref('离线')
let socketTask = null

const orderInfo = ref({
  productName: '',
  spec: '',
  orderNo: '',
  productIcon: '',
  statusText: ''
})

async function loadOrderById(orderId) {
  try {
    const order = await request({ url: '/orders/' + orderId })
    if (!order) return null
    const item = order.items && order.items[0]
    return {
      productName: item ? item.productName : '',
      spec: item ? item.productSpec : '',
      orderNo: order.orderNo || '',
      productIcon: item ? item.productImage : '',
      statusText: order.statusText || ''
    }
  } catch (e) {
    return null
  }
}

onLoad(async (options) => {
  uni.setNavigationBarTitle({ title: '智能客服' })

  // 用字符串存储ID，避免JS大数精度丢失
  const orderId = options.orderId && /^\d+$/.test(String(options.orderId)) ? String(options.orderId) : null
  const afterSaleId = options.afterSaleId && /^\d+$/.test(String(options.afterSaleId)) ? String(options.afterSaleId) : null

  if (orderId) {
    const data = await loadOrderById(orderId)
    if (data) {
      hasOrder.value = true
      orderInfo.value = data
    }
  }

  if (!hasOrder.value && options.productName) {
    hasOrder.value = true
    orderInfo.value = {
      productName: options.productName,
      spec: options.spec || '',
      orderNo: options.orderId || '',
      productIcon: options.productIcon || '',
      statusText: options.statusText || '售后处理中'
    }
  }

  await createOrLoadSession({
    afterSaleId: afterSaleId,
    orderId: orderId
  })
})

function copyOrderNo() {
  uni.setClipboardData({
    data: orderInfo.value.orderNo,
    success: () => {
      uni.showToast({ title: '已复制', icon: 'success' })
    }
  })
}

function addServiceMessage(content, messageType = 'TEXT') {
  const now = new Date()
  const time = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`
  messages.value.push({ role: 'service', content, messageType, time })
  scrollToBottom()
}

function addUserMessage(content, messageType = 'TEXT') {
  const now = new Date()
  const time = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`
  const clientId = `local-${Date.now()}-${Math.random().toString(36).slice(2)}`
  messages.value.push({ clientId, role: 'user', content, messageType, time, read: false })
  scrollToBottom()
  return clientId
}

async function createOrLoadSession(payload) {
  try {
    const session = await request({
      url: '/chat/session',
      method: 'POST',
      data: payload
    })
    sessionId.value = session.sessionId
    applyServiceStatus(session)
    const history = await request({
      url: '/chat/history?sessionId=' + session.sessionId
    })
    const list = history && history.list ? history.list : []
    messages.value = list.map(item => ({
      id: item.id,
      role: item.role,
      content: item.content,
      messageType: item.messageType || 'TEXT',
      read: Boolean(item.read),
      time: item.createTime ? item.createTime.slice(11, 16) : ''
    }))
    if (messages.value.length === 0 && session.welcomeMessage) {
      addServiceMessage(session.welcomeMessage)
    } else {
      scrollToBottom()
    }
    wsConnect(session.sessionId)
  } catch (e) {
    addServiceMessage('您好，我是智能客服，请问有什么可以帮您？您可以咨询订单问题、申请售后，或转接人工客服。')
  }
}

function applyServiceStatus(data) {
  chatMode.value = data && data.mode ? data.mode : (chatMode.value || 'AI')
  if (chatMode.value !== 'HUMAN') {
    return
  }
  const status = data && data.humanStatus ? data.humanStatus : (data && data.humanOnline ? 'ONLINE' : 'OFFLINE')
  humanServiceStatus.value = status === 'ONLINE' ? 'ONLINE' : 'OFFLINE'
  humanServiceStatusText.value = humanServiceStatus.value === 'ONLINE' ? '在线' : '离线'
}

function wsConnect(sid) {
  if (socketTask) {
    socketTask.close()
    socketTask = null
  }
  socketTask = uni.connectSocket({
    url: getChatWsUrl(),
    complete: () => {}
  })
  socketTask.onOpen(() => {
    socketTask.send({
      data: JSON.stringify({ action: 'subscribe', sessionId: sid })
    })
  })
  socketTask.onMessage((res) => {
    try {
      const msg = JSON.parse(res.data)
      if (msg.action === 'message' && msg.role !== 'USER') {
        addServiceMessage(msg.content, msg.messageType || 'TEXT')
        markMessagesRead(msg.lastReadMessageId)
      } else if (msg.action === 'read') {
        markMessagesRead(msg.lastReadMessageId)
      }
    } catch (e) {
      // ignore parse errors
    }
  })
  socketTask.onError((err) => {
    console.error('WebSocket error', err)
  })
  socketTask.onClose(() => {
    // ignore
  })
}

function getChatWsUrl() {
  return BASE_URL.replace(/^http/, 'ws').replace(/\/api\/?$/, '/api/ws/chat')
}

function markMessagesRead(lastReadMessageId) {
  messages.value = messages.value.map(item => {
    if (item.role !== 'user') {
      return item
    }
    if (!item.id || !lastReadMessageId || Number(item.id) <= Number(lastReadMessageId)) {
      return { ...item, read: true }
    }
    return item
  })
}

onUnmounted(() => {
  if (socketTask) {
    socketTask.close()
    socketTask = null
  }
})

function scrollToBottom() {
  nextTick(() => {
    scrollTop.value = 1000000 + messages.value.length * 1000
  })
}

async function sendMessage() {
  const text = inputText.value.trim()
  if (!text) return

  inputText.value = ''
  await sendChatMessage(text, 'TEXT')
}

async function sendChatMessage(content, messageType = 'TEXT') {
  const clientId = addUserMessage(content, messageType)
  try {
    if (!sessionId.value) {
      await createOrLoadSession({})
    }
    const result = await request({
      url: '/chat/send',
      method: 'POST',
      data: {
        sessionId: sessionId.value,
        message: content,
        messageType
      }
    })
    bindLocalMessageId(clientId, result && result.messageId)
    applyServiceStatus(result)
    if (result && result.reply) {
      addServiceMessage(result.reply)
    }
  } catch (e) {
    addServiceMessage('消息暂时发送失败，请稍后重试。')
  }
}

function bindLocalMessageId(clientId, messageId) {
  if (!messageId) return
  messages.value = messages.value.map(item => (
    item.clientId === clientId ? { ...item, id: messageId } : item
  ))
}

function quickAction(type) {
  if (type === 'supplement') {
    chooseAttachment()
    return
  }

  const actionMap = {
    refund: '请帮我查看一下退款进度',
    human: '请帮我转接人工客服',
    query: '我想查询我的订单状态',
    aftersale: '我想申请售后'
  }
  const text = actionMap[type]
  inputText.value = text
  sendMessage()
}

function chooseAttachment() {
  if (attachmentUploading.value) return

  uni.chooseImage({
    count: 1,
    sizeType: ['compressed'],
    sourceType: ['album', 'camera'],
    success: async (res) => {
      const filePath = res.tempFilePaths && res.tempFilePaths[0]
      if (!filePath) return
      await sendAttachmentMessage(filePath)
    }
  })
}

async function sendAttachmentMessage(filePath) {
  attachmentUploading.value = true
  try {
    const url = await uploadAttachment(filePath)
    await sendChatMessage(url, 'IMAGE')
  } catch (e) {
    uni.showToast({
      title: e.message || '附件上传失败',
      icon: 'none'
    })
  } finally {
    attachmentUploading.value = false
  }
}

function uploadAttachment(filePath) {
  return new Promise((resolve, reject) => {
    const token = uni.getStorageSync('token') || ''
    uni.uploadFile({
      url: `${BASE_URL}/upload/image`,
      filePath,
      name: 'file',
      header: {
        ...(token ? { 'Authorization': 'Bearer ' + token } : {})
      },
      success: (res) => {
        try {
          const body = JSON.parse(res.data)
          if (body.code === 200 && body.data && body.data.url) {
            resolve(body.data.url)
            return
          }
          reject(new Error(body.message || '上传失败'))
        } catch (e) {
          reject(new Error('上传响应解析失败'))
        }
      },
      fail: () => {
        reject(new Error('上传失败，请稍后重试'))
      }
    })
  })
}

function previewMessageImage(src) {
  const current = normalizeImageUrl(src)
  const urls = messages.value
    .filter(item => item.messageType === 'IMAGE')
    .map(item => normalizeImageUrl(item.content))
    .filter(Boolean)

  if (!current) return
  uni.previewImage({
    current,
    urls: urls.length ? urls : [current]
  })
}
</script>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: #f0eeea;
}

.order-card {
  display: flex;
  align-items: center;
  margin: 20rpx 24rpx 12rpx;
  padding: 20rpx;
  background: #ffffff;
  border-radius: 16rpx;
  border: 1rpx solid rgba(0,0,0,0.04);
}

.order-product-img {
  width: 76rpx;
  height: 76rpx;
  border-radius: 12rpx;
  flex-shrink: 0;
}

.order-product-info {
  flex: 1;
  min-width: 0;
  margin-left: 18rpx;
}

.order-product {
  display: block;
  font-size: 28rpx;
  font-weight: 600;
  color: #1a1a1a;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.order-row {
  display: flex;
  align-items: center;
  gap: 8rpx;
  margin-top: 8rpx;
}

.order-no {
  flex: 1;
  min-width: 0;
  font-size: 22rpx;
  color: #999;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.copy-icon {
  font-size: 20rpx;
  flex-shrink: 0;
}

.order-status {
  flex-shrink: 0;
  font-size: 22rpx;
  color: #c97b5a;
  font-weight: 600;
}

.human-status {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6rpx;
  margin: 0 28rpx 6rpx;
  min-height: 28rpx;
}

.status-dot {
  width: 12rpx;
  height: 12rpx;
  border-radius: 50%;
  background: #b7b7b7;
}

.status-dot.online {
  background: #52c41a;
}

.status-dot.offline {
  background: #b7b7b7;
}

.status-text {
  font-size: 20rpx;
  color: #8c8c8c;
}

.status-text.online {
  color: #52c41a;
}

.status-text.offline {
  color: #8c8c8c;
}

.chat-area {
  flex: 1;
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
  font-size: 20rpx;
  color: #bbb;
  margin: 4rpx 0 10rpx;
}

.message {
  display: flex;
  align-items: flex-start;
  width: 100%;
  box-sizing: border-box;
}

.message.user {
  flex-direction: row-reverse;
}

.msg-bubble {
  max-width: 76%;
  padding: 18rpx 22rpx;
  border-radius: 18rpx;
}

.message.service .msg-bubble {
  background: #ffffff;
  border: 1rpx solid rgba(0,0,0,0.04);
  border-top-left-radius: 6rpx;
}

.message.user .msg-bubble {
  background: #fff5f0;
  border: 1rpx solid rgba(244,90,11,0.1);
  border-top-right-radius: 6rpx;
}

.msg-text {
  font-size: 26rpx;
  line-height: 1.55;
  color: #1a1a1a;
}

.msg-image {
  display: block;
  width: 240rpx;
  height: 240rpx;
  border-radius: 12rpx;
  background: #f5f3ef;
}

.msg-read {
  display: block;
  text-align: right;
  margin-top: 4rpx;
  padding-right: 4rpx;
  font-size: 20rpx;
  color: #bbb;
}

.msg-read.unread {
  color: #c97b5a;
}

.quick-actions {
  display: flex;
  gap: 14rpx;
  padding: 12rpx 24rpx;
  background: rgba(240,238,234,0.96);
}

.action-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8rpx;
  height: 58rpx;
  background: #ffffff;
  border-radius: 30rpx;
  border: 1rpx solid rgba(0,0,0,0.06);
}

.action-icon {
  font-size: 24rpx;
}

.action-image-icon {
  width: 24rpx;
  height: 24rpx;
  flex-shrink: 0;
}

.action-text {
  font-size: 22rpx;
  color: #1a1a1a;
  font-weight: 500;
}

.input-area {
  display: flex;
  align-items: center;
  gap: 14rpx;
  padding: 16rpx 24rpx;
  padding-bottom: calc(16rpx + env(safe-area-inset-bottom));
  background: #ffffff;
  border-top: 1rpx solid rgba(0,0,0,0.06);
}

.attach-btn {
  width: 60rpx;
  height: 60rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  border-radius: 50%;
  background: transparent;
}

.attach-btn.uploading {
  background: #f5f3ef;
}

.attach-icon {
  font-size: 44rpx;
  font-weight: 300;
  color: #666666;
  line-height: 1;
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
  width: 60rpx;
  height: 60rpx;
  line-height: 60rpx;
  text-align: center;
  border-radius: 50%;
  background: #e0e0e0;
  transition: background 0.2s;
}

.send-btn.active {
  background: linear-gradient(135deg, #c97b5a, #b86a4a);
}

.send-icon {
  color: #ffffff;
  font-size: 28rpx;
}
</style>
