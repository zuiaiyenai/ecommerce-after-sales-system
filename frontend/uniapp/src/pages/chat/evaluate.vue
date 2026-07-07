<template>
  <view class="page">
    <view class="card aftersale-card">
      <text class="card-title">本次售后</text>
      <view class="aftersale-row">
        <image class="product-img" :src="normalizeImageUrl(productIcon)" mode="aspectFill" />
        <view class="aftersale-info">
          <view class="issue-row">
            <text class="issue-title">售后服务</text>
            <text class="status-pill">待评价</text>
          </view>
          <text class="info-line">关联商品：{{ productName || '售后商品' }}</text>
          <text class="info-line">处理时间：{{ handledAt }}</text>
          <view class="ticket-row">
            <text class="info-line ticket-no">售后单号：{{ displayNo }}</text>
            <text class="copy-btn" @tap="copyNo">复制</text>
          </view>
        </view>
      </view>
    </view>

    <view class="card">
      <text class="card-title">服务评价</text>
      <view class="divider"></view>
      <view v-for="item in scoreItems" :key="item.key" class="score-row">
        <text class="score-label">{{ item.label }}</text>
        <view class="stars">
          <text
            v-for="star in 5"
            :key="star"
            class="star"
            :class="{ active: scores[item.key] >= star }"
            @tap="setScore(item.key, star)"
          >★</text>
        </view>
        <text class="score-text">{{ scoreText(scores[item.key]) }}</text>
      </view>
    </view>

    <view class="card">
      <text class="card-title">补充评价</text>
      <textarea
        v-model="content"
        class="comment-input"
        maxlength="300"
        placeholder="请填写您对本次售后服务的评价，帮助我们持续改进服务。"
      />
      <text class="char-count">{{ content.length }}/300</text>
      <button class="submit-btn" :disabled="submitting || !sessionId" @tap="submit">
        {{ submitting ? '提交中...' : '提交评价' }}
      </button>
    </view>
  </view>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { submitChatEvaluation } from '../../utils/userChat'
import { normalizeImageUrl } from '../../utils/request'

const sessionId = ref('')
const orderNo = ref('')
const productName = ref('')
const productIcon = ref('')
const handledAt = ref('')
const content = ref('')
const submitting = ref(false)
const displayNo = ref('')

const scoreItems = [
  { key: 'overall', label: '综合评价' },
  { key: 'responseSpeed', label: '响应速度' },
  { key: 'serviceAttitude', label: '服务态度' },
  { key: 'professional', label: '专业程度' },
  { key: 'efficiency', label: '处理效率' }
]

const scores = reactive({
  overall: 5,
  responseSpeed: 5,
  serviceAttitude: 5,
  professional: 5,
  efficiency: 5
})

function pad(value) {
  return String(value).padStart(2, '0')
}

function nowText() {
  const now = new Date()
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}`
}

function setScore(key, value) {
  scores[key] = value
}

function scoreText(value) {
  if (value >= 5) return '非常满意'
  if (value === 4) return '满意'
  if (value === 3) return '一般'
  if (value === 2) return '不满意'
  return '很不满意'
}

function copyNo() {
  const text = displayNo.value || orderNo.value
  if (!text) return
  uni.setClipboardData({ data: text })
}

async function submit() {
  if (!sessionId.value || submitting.value) return
  submitting.value = true
  try {
    await submitChatEvaluation(sessionId.value, scores.overall, content.value.trim(), {
      responseSpeedScore: scores.responseSpeed,
      serviceAttitudeScore: scores.serviceAttitude,
      professionalScore: scores.professional,
      efficiencyScore: scores.efficiency
    })
    uni.showToast({ title: '评价成功', icon: 'success' })
    setTimeout(() => {
      uni.navigateBack()
    }, 800)
  } catch (error) {
    uni.showToast({ title: error.message || '评价失败', icon: 'none' })
  } finally {
    submitting.value = false
  }
}

onLoad((options) => {
  sessionId.value = String(options.sessionId || '')
  orderNo.value = decodeURIComponent(options.orderNo || '')
  productName.value = decodeURIComponent(options.productName || '')
  productIcon.value = decodeURIComponent(options.productIcon || '')
  displayNo.value = decodeURIComponent(options.afterSaleNo || '') || orderNo.value || sessionId.value
  handledAt.value = decodeURIComponent(options.handledAt || '') || nowText()
})
</script>

<style scoped>
.page {
  min-height: 100vh;
  padding: 0 28rpx 40rpx;
  background: #f4f2ef;
}

.card {
  position: relative;
  margin-bottom: 24rpx;
  padding: 30rpx;
  border-radius: 20rpx;
  background: #ffffff;
  box-shadow: 0 8rpx 24rpx rgba(0, 0, 0, 0.04);
}

.card-title {
  display: block;
  margin-bottom: 28rpx;
  font-size: 32rpx;
  font-weight: 900;
  color: #111111;
}

.aftersale-row {
  display: flex;
  gap: 28rpx;
}

.product-img {
  width: 168rpx;
  height: 168rpx;
  flex: none;
  border-radius: 12rpx;
  background: #f5f3ef;
}

.aftersale-info {
  flex: 1;
  min-width: 0;
}

.issue-row,
.ticket-row {
  display: flex;
  align-items: center;
  gap: 18rpx;
}

.issue-title {
  min-width: 0;
  font-size: 30rpx;
  font-weight: 800;
  color: #222222;
}

.status-pill {
  flex: none;
  padding: 6rpx 20rpx;
  border-radius: 12rpx;
  border: 1rpx solid #efd8cc;
  background: #fff5ef;
  color: #c97b5a;
  font-size: 24rpx;
}

.info-line {
  display: block;
  margin-top: 16rpx;
  font-size: 28rpx;
  color: #333333;
  overflow-wrap: anywhere;
}

.ticket-no {
  flex: 1;
  min-width: 0;
}

.copy-btn {
  flex: none;
  margin-top: 14rpx;
  padding: 6rpx 18rpx;
  border: 1rpx solid #d8d8d8;
  border-radius: 10rpx;
  color: #666666;
  font-size: 24rpx;
}

.divider {
  height: 1rpx;
  margin-bottom: 4rpx;
  background: rgba(0, 0, 0, 0.08);
}

.score-row {
  display: grid;
  grid-template-columns: 150rpx minmax(0, 1fr) 150rpx;
  align-items: center;
  min-height: 88rpx;
  border-bottom: 1rpx solid rgba(0, 0, 0, 0.08);
}

.score-row:last-child {
  border-bottom: none;
}

.score-label {
  font-size: 28rpx;
  font-weight: 800;
  color: #111111;
}

.stars {
  display: flex;
  justify-content: space-between;
  padding-right: 26rpx;
}

.star {
  font-size: 50rpx;
  color: #e4d8d2;
  line-height: 1;
}

.star.active {
  color: #c97b5a;
}

.score-text {
  text-align: right;
  font-size: 26rpx;
  color: #666666;
}

.comment-input {
  width: 100%;
  height: 180rpx;
  padding: 22rpx;
  box-sizing: border-box;
  border: 1rpx solid #dddddd;
  border-radius: 12rpx;
  color: #222222;
  font-size: 26rpx;
}

.char-count {
  display: block;
  margin-top: 10rpx;
  text-align: right;
  color: #999999;
  font-size: 24rpx;
}

.submit-btn {
  height: 84rpx;
  line-height: 84rpx;
  margin-top: 34rpx;
  border: none;
  border-radius: 16rpx;
  background: #c97b5a;
  color: #ffffff;
  font-size: 32rpx;
  font-weight: 900;
}
</style>
