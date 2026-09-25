<template>
  <view class="page">
    <view class="list-head">
      <text class="head-title">最近咨询</text>
      <button class="new-btn" @tap="startNewChat">新咨询</button>
    </view>

    <view class="session-list">
      <view v-for="item in sessions" :key="item.sessionId" class="session-card" @tap="openSession(item)">
        <view class="avatar">{{ sessionInitial(item) }}</view>
        <view class="session-main">
          <view class="session-title-row">
            <text class="session-title">{{ item.title || '售后咨询' }}</text>
            <text class="session-time">{{ formatShortTime(item.lastMessageTime) }}</text>
          </view>
          <text class="session-last">{{ item.lastMessage || '暂无消息' }}</text>
          <view class="session-tags">
            <text class="tag">{{ statusText(item.status) }}</text>
            <text v-if="item.evaluationStatus === 'PENDING'" class="tag review">待评价</text>
          </view>
        </view>
        <button class="archive-btn" @tap.stop="archiveSession(item)">×</button>
      </view>

      <view v-if="!loading && sessions.length === 0" class="empty">
        <text class="empty-title">暂无咨询会话</text>
        <text class="empty-text">有问题时可以发起新的售后咨询。</text>
        <button class="empty-btn" @tap="startNewChat">开始咨询</button>
      </view>
    </view>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { hideChatSession, listChatSessions } from '../../utils/userChat'

const sessions = ref([])
const loading = ref(false)

async function loadSessions() {
  loading.value = true
  try {
    const result = await listChatSessions()
    sessions.value = result && Array.isArray(result.list) ? result.list : []
  } catch (error) {
    sessions.value = []
  } finally {
    loading.value = false
  }
}

function startNewChat() {
  uni.navigateTo({ url: '/pages/chat/consult?fresh=1' })
}

function openSession(item) {
  const params = [
    `sessionId=${item.sessionId}`,
    `status=${encodeURIComponent(item.status || '')}`
  ]
  if (item.orderId) params.push(`orderId=${item.orderId}`)
  const ticketId = item.ticketId
  if (ticketId) params.push(`ticketId=${ticketId}`)
  uni.navigateTo({
    url: `/pages/chat/consult?${params.join('&')}`
  })
}

async function archiveSession(item) {
  try {
    await hideChatSession(item.sessionId)
    sessions.value = sessions.value.filter(session => session.sessionId !== item.sessionId)
    uni.showToast({ title: '已移除', icon: 'success' })
  } catch (error) {
    uni.showToast({ title: error.message || '操作失败', icon: 'none' })
  }
}

function sessionInitial(item) {
  return (item.title || '售后').slice(0, 1)
}

function statusText(status) {
  const map = {
    AI_ACTIVE: '智能客服',
    WAITING: '待接入',
    ACTIVE: '处理中',
    PROCESSING: '处理中',
    AWAITING_EVALUATION: '待评价',
    READY_TO_CLOSE: '已评价',
    CLOSED: '已移除'
  }
  return map[status] || '进行中'
}

function formatShortTime(value) {
  if (!value) return ''
  return String(value).slice(5, 16)
}

onShow(loadSessions)
</script>

<style scoped>
.page {
  min-height: 100vh;
  padding-bottom: 40rpx;
  background: #f0eeea;
}

.list-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 32rpx 28rpx 8rpx;
}

.head-title {
  font-size: 34rpx;
  font-weight: 900;
  color: #1a1a1a;
}

.new-btn,
.empty-btn {
  height: 56rpx;
  line-height: 56rpx;
  padding: 0 24rpx;
  border: none;
  border-radius: 28rpx;
  background: #c97b5a;
  color: #ffffff;
  font-size: 24rpx;
}

.session-list {
  padding: 12rpx 28rpx;
}

.session-card {
  display: flex;
  align-items: center;
  gap: 18rpx;
  margin-bottom: 18rpx;
  padding: 22rpx;
  border-radius: 18rpx;
  background: #ffffff;
}

.avatar {
  width: 72rpx;
  height: 72rpx;
  line-height: 72rpx;
  text-align: center;
  border-radius: 50%;
  background: #c97b5a;
  color: #ffffff;
  font-weight: 800;
  font-size: 28rpx;
}

.session-main {
  flex: 1;
  min-width: 0;
}

.session-title-row {
  display: flex;
  justify-content: space-between;
  gap: 16rpx;
}

.session-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 28rpx;
  font-weight: 800;
  color: #1a1a1a;
}

.session-time,
.session-last,
.tag {
  font-size: 22rpx;
}

.session-time {
  color: #aaa;
}

.session-last {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-top: 8rpx;
  color: #888;
}

.session-tags {
  display: flex;
  gap: 10rpx;
  margin-top: 12rpx;
}

.tag {
  padding: 4rpx 12rpx;
  border-radius: 999rpx;
  background: #f5f3ef;
  color: #8d6e63;
}

.tag.review {
  background: #fff4e8;
  color: #c97b5a;
}

.archive-btn {
  width: 88rpx;
  height: 52rpx;
  line-height: 52rpx;
  padding: 0;
  border: none;
  border-radius: 26rpx;
  background: #f5f3ef;
  color: #777;
  font-size: 22rpx;
}

.empty {
  margin-top: 140rpx;
  text-align: center;
}

.empty-title,
.empty-text {
  display: block;
}

.empty-title {
  font-size: 30rpx;
  font-weight: 800;
  color: #1a1a1a;
}

.empty-text {
  margin: 12rpx 0 28rpx;
  font-size: 24rpx;
  color: #999;
}
</style>
