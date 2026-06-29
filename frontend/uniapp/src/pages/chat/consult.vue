<template>
  <view class="page">
    <!-- 顶部导航 -->
    <view class="nav-bar">
      <view class="back-btn" @tap="goBack">
        <text class="back-icon">←</text>
      </view>
      <text class="nav-title">智能客服</text>
      <view class="nav-right"></view>
    </view>

    <!-- 订单信息卡片 - 仅在有订单时显示 -->
    <view v-if="hasOrder" class="order-card">
      <image class="order-product-img" :src="orderInfo.productIcon" mode="aspectFill" />
      <view class="order-product-info">
        <text class="order-product">{{ orderInfo.productName }}</text>
        <view class="order-row">
          <text class="order-no">订单号：{{ orderInfo.orderNo }}</text>
          <text class="copy-icon" @tap="copyOrderNo">📋</text>
          <text class="order-status">{{ orderInfo.statusText }}</text>
        </view>
      </view>
    </view>

    <!-- 在线客服提示 -->
    <view class="service-header">
      <view class="service-info">
        <text class="service-name">在线客服</text>
        <view class="online-dot">
          <view class="dot"></view>
          <text class="online-text">在线</text>
        </view>
      </view>
    </view>

    <!-- 对话区域 -->
    <scroll-view class="chat-area" scroll-y :scroll-top="scrollTop" scroll-with-animation>
      <view v-for="(msg, index) in messages" :key="index" class="msg-group">
        <text class="msg-time" v-if="msg.time">{{ msg.time }}</text>
        <view class="message" :class="msg.role">
          <view class="msg-bubble">
            <text class="msg-text">{{ msg.content }}</text>
          </view>
        </view>
        <text class="msg-read" v-if="msg.role === 'user'">已读</text>
      </view>
    </scroll-view>

    <!-- 快捷操作 - 根据是否有订单显示不同操作 -->
    <view class="quick-actions">
      <template v-if="hasOrder">
        <view class="action-btn" @tap="quickAction('refund')">
          <text class="action-icon">🔄</text>
          <text class="action-text">退款进度</text>
        </view>
        <view class="action-btn" @tap="quickAction('supplement')">
          <text class="action-icon">📎</text>
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

    <!-- 输入区域 -->
    <view class="input-area">
      <view class="voice-btn">
        <text class="voice-icon">🎤</text>
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
import { ref, nextTick } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { request } from '../../utils/request'

const messages = ref([])
const inputText = ref('')
const scrollTop = ref(0)
const hasOrder = ref(false)
const sessionId = ref(null)

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
  const numericOrderId = options.orderId && /^\d+$/.test(String(options.orderId)) ? Number(options.orderId) : null
  const numericAfterSaleId = options.afterSaleId && /^\d+$/.test(String(options.afterSaleId)) ? Number(options.afterSaleId) : null

  // 如果传了orderId，从API查找订单信息
  if (numericOrderId) {
    const data = await loadOrderById(numericOrderId)
    if (data) {
      hasOrder.value = true
      orderInfo.value = data
    }
  }

  // 如果传了其他参数（如从售后详情跳转）
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
    afterSaleId: numericAfterSaleId,
    orderId: numericOrderId
  })
})

function goBack() {
  uni.navigateBack()
}

function copyOrderNo() {
  uni.setClipboardData({
    data: orderInfo.value.orderNo,
    success: () => {
      uni.showToast({ title: '已复制', icon: 'success' })
    }
  })
}

function addServiceMessage(content) {
  const now = new Date()
  const time = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`
  messages.value.push({ role: 'service', content, time })
  scrollToBottom()
}

function addUserMessage(content) {
  const now = new Date()
  const time = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`
  messages.value.push({ role: 'user', content, time })
  scrollToBottom()
}

async function createOrLoadSession(payload) {
  try {
    const session = await request({
      url: '/chat/session',
      method: 'POST',
      data: payload
    })
    sessionId.value = session.sessionId
    const history = await request({
      url: '/chat/history?sessionId=' + session.sessionId
    })
    const list = history && history.list ? history.list : []
    messages.value = list.map(item => ({
      role: item.role,
      content: item.content,
      time: item.createTime ? item.createTime.slice(11, 16) : ''
    }))
    if (messages.value.length === 0 && session.welcomeMessage) {
      addServiceMessage(session.welcomeMessage)
    }
  } catch (e) {
    addServiceMessage('您好，我是智能客服，请问有什么可以帮您？您可以咨询订单问题、申请售后，或转接人工客服。')
  }
}

function scrollToBottom() {
  nextTick(() => {
    scrollTop.value = scrollTop.value + 1
  })
}

async function sendMessage() {
  const text = inputText.value.trim()
  if (!text) return

  addUserMessage(text)
  inputText.value = ''

  try {
    if (!sessionId.value) {
      await createOrLoadSession({})
    }
    const result = await request({
      url: '/chat/send',
      method: 'POST',
      data: {
        sessionId: sessionId.value,
        message: text,
        messageType: 'TEXT'
      }
    })
    if (result && result.reply) {
      addServiceMessage(result.reply)
    }
  } catch (e) {
    addServiceMessage('消息暂时发送失败，请稍后重试。')
  }
}

function quickAction(type) {
  const actionMap = {
    refund: '请帮我查看一下退款进度',
    supplement: '我需要补充一些凭证图片',
    human: '请帮我转接人工客服',
    query: '我想查询我的订单状态',
    aftersale: '我想申请售后'
  }
  const text = actionMap[type]
  inputText.value = text
  sendMessage()
}
</script>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: #f0eeea;
}

/* 顶部导航 */
.nav-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 32rpx 28rpx;
  background: #ffffff;
  border-bottom: 1rpx solid rgba(0,0,0,0.06);
}

.back-btn {
  width: 64rpx;
  height: 64rpx;
  line-height: 64rpx;
  text-align: center;
  border-radius: 16rpx;
  background: #f5f3ef;
}

.back-icon {
  font-size: 32rpx;
  color: #1a1a1a;
}

.nav-title {
  font-size: 32rpx;
  font-weight: 800;
  color: #1a1a1a;
}

.nav-right {
  width: 64rpx;
}

/* 订单信息卡片 */
.order-card {
  display: flex;
  align-items: center;
  margin: 20rpx 28rpx;
  padding: 24rpx;
  background: #ffffff;
  border-radius: 16rpx;
  border: 1rpx solid rgba(0,0,0,0.04);
}

.order-product-img {
  width: 80rpx;
  height: 80rpx;
  border-radius: 12rpx;
  flex-shrink: 0;
}

.order-product-info {
  flex: 1;
  margin-left: 20rpx;
}

.order-product {
  display: block;
  font-size: 26rpx;
  font-weight: 600;
  color: #1a1a1a;
}

.order-row {
  display: flex;
  align-items: center;
  margin-top: 10rpx;
}

.order-no {
  font-size: 22rpx;
  color: #999;
}

.copy-icon {
  margin-left: 8rpx;
  font-size: 20rpx;
}

.order-status {
  margin-left: auto;
  font-size: 22rpx;
  color: #c97b5a;
  font-weight: 600;
}

/* 客服头部 */
.service-header {
  display: flex;
  align-items: center;
  padding: 16rpx 28rpx;
}

.service-info {
  margin-left: 14rpx;
}

.service-name {
  display: block;
  font-size: 26rpx;
  font-weight: 600;
  color: #1a1a1a;
}

.online-dot {
  display: flex;
  align-items: center;
  margin-top: 4rpx;
}

.dot {
  width: 12rpx;
  height: 12rpx;
  border-radius: 50%;
  background: #52c41a;
}

.online-text {
  margin-left: 6rpx;
  font-size: 20rpx;
  color: #52c41a;
}

/* 对话区域 */
.chat-area {
  flex: 1;
  padding: 20rpx 28rpx;
  overflow-y: auto;
}

.msg-group {
  margin-bottom: 24rpx;
}

.msg-time {
  display: block;
  text-align: center;
  font-size: 20rpx;
  color: #bbb;
  margin-bottom: 16rpx;
}

.message {
  display: flex;
  align-items: flex-start;
}

.message.user {
  flex-direction: row-reverse;
}

.msg-bubble {
  max-width: 70%;
  padding: 20rpx 24rpx;
  border-radius: 20rpx;
}

.message.service .msg-bubble {
  background: #ffffff;
  border: 1rpx solid rgba(0,0,0,0.04);
}

.message.user .msg-bubble {
  background: #fff5f0;
  border: 1rpx solid rgba(244,90,11,0.1);
}

.msg-text {
  font-size: 26rpx;
  line-height: 1.6;
  color: #1a1a1a;
}

.msg-read {
  display: block;
  text-align: right;
  margin-top: 8rpx;
  font-size: 20rpx;
  color: #bbb;
}

/* 快捷操作 */
.quick-actions {
  display: flex;
  gap: 16rpx;
  padding: 16rpx 28rpx;
}

.action-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8rpx;
  height: 64rpx;
  background: #ffffff;
  border-radius: 32rpx;
  border: 1rpx solid rgba(0,0,0,0.06);
}

.action-icon {
  font-size: 24rpx;
}

.action-text {
  font-size: 22rpx;
  color: #1a1a1a;
  font-weight: 500;
}

/* 输入区域 */
.input-area {
  display: flex;
  align-items: center;
  gap: 16rpx;
  padding: 20rpx 28rpx;
  padding-bottom: calc(20rpx + env(safe-area-inset-bottom));
  background: #ffffff;
  border-top: 1rpx solid rgba(0,0,0,0.06);
}

.voice-btn {
  width: 64rpx;
  height: 64rpx;
  line-height: 64rpx;
  text-align: center;
  border-radius: 50%;
  background: #f5f3ef;
}

.voice-icon {
  font-size: 28rpx;
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
  width: 64rpx;
  height: 64rpx;
  line-height: 64rpx;
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
