<template>
  <view class="page">
    <view class="nav-bar">
      <view class="back-btn" @tap="goBack">
        <text class="back-icon">←</text>
      </view>
      <text class="nav-title">申请售后</text>
      <view class="nav-right"></view>
    </view>

    <view class="card">
      <text class="card-title">售后原因</text>
      <view class="divider"></view>
      <view class="reason-grid">
        <view
          v-for="item in reasons"
          :key="item.value"
          class="reason-item"
          :class="{ active: selectedReason === item.value }"
          @tap="selectReason(item.value)"
        >
          <view class="reason-icon">{{ item.icon }}</view>
          <text class="reason-label">{{ item.label }}</text>
          <view v-if="selectedReason === item.value" class="reason-check">✓</view>
        </view>
      </view>
    </view>

    <view class="card">
      <text class="card-title">问题描述</text>
      <view class="divider"></view>
      <textarea
        v-model="description"
        class="desc-input"
        placeholder="请详细描述您遇到的问题，例如：商品有破损、尺码不合适等..."
        maxlength="500"
      />
      <view class="desc-footer">
        <text class="char-count">{{ description.length }}/500</text>
      </view>
    </view>

    <view class="card">
      <text class="card-title">上传凭证</text>
      <view class="divider"></view>
      <view class="image-grid">
        <view v-for="(img, index) in images" :key="index" class="image-item">
          <image :src="img" mode="aspectFill" class="preview-img" @tap="previewImage(index)" />
          <view class="delete-btn" @tap.stop="removeImage(index)">×</view>
        </view>
        <view v-if="images.length < 5" class="add-image" @tap="chooseImage">
          <text class="add-icon">+</text>
          <text class="add-text">添加图片</text>
        </view>
      </view>
      <text class="image-tip">最多上传 5 张，支持 jpg/png 格式</text>
    </view>

    <button class="submit-btn" :disabled="!selectedReason || submitting" @tap="submit">
      {{ submitting ? '进入对话中...' : '提交申请' }}
    </button>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { request } from '../../utils/request'

const PENDING_APPLY_PREFIX = 'after_sales_pending_apply'

const selectedReason = ref('')
const description = ref('')
const images = ref([])
const submitting = ref(false)
const orderId = ref(null)
const orderData = ref(null)

const reasons = [
  { value: 'QUALITY', label: '质量问题', icon: '质' },
  { value: 'WRONG_ITEM', label: '发错货', icon: '错' },
  { value: 'SIZE_ISSUE', label: '尺码不合适', icon: '码' },
  { value: 'DAMAGE', label: '物流损坏', icon: '损' },
  { value: 'NOT_MATCH', label: '与描述不符', icon: '异' },
  { value: 'OTHER', label: '其他原因', icon: '…' }
]

function getPendingApplyKey(id) {
  return `${PENDING_APPLY_PREFIX}:${id || 'default'}`
}

onLoad(async (options) => {
  if (options.orderId) {
    orderId.value = Number(options.orderId)
    try {
      orderData.value = await request({ url: '/orders/' + orderId.value })
    } catch (error) {
      orderData.value = null
    }
  }
})

function goBack() {
  uni.navigateBack()
}

function selectReason(value) {
  selectedReason.value = value
}

function chooseImage() {
  uni.chooseImage({
    count: 5 - images.value.length,
    sizeType: ['compressed'],
    sourceType: ['album', 'camera'],
    success: (res) => {
      images.value = [...images.value, ...(res.tempFilePaths || [])].slice(0, 5)
    }
  })
}

function removeImage(index) {
  images.value.splice(index, 1)
}

function previewImage(index) {
  uni.previewImage({
    current: index,
    urls: images.value
  })
}

async function submit() {
  if (!selectedReason.value) {
    uni.showToast({ title: '请选择售后原因', icon: 'none' })
    return
  }
  if (!orderData.value || !orderId.value) {
    uni.showToast({ title: '订单信息加载失败', icon: 'none' })
    return
  }

  submitting.value = true
  try {
    const reasonLabel = reasons.find((item) => item.value === selectedReason.value)?.label || selectedReason.value
    const pendingPayload = {
      orderId: orderId.value,
      orderNo: orderData.value.orderNo || '',
      reasonValue: selectedReason.value,
      reasonLabel,
      description: description.value.trim() || reasonLabel,
      initialMessage: `我想申请售后，原因是${reasonLabel}`,
      imagePaths: [...images.value],
      createdAt: Date.now()
    }

    uni.setStorageSync(getPendingApplyKey(orderId.value), pendingPayload)
    uni.redirectTo({
      url: `/pages/chat/consult?orderId=${orderId.value}&fromApply=1`
    })
  } catch (error) {
    uni.showToast({ title: error.message || '进入对话失败，请重试', icon: 'none' })
    submitting.value = false
  }
}
</script>

<style scoped>
.page {
  min-height: 100vh;
  padding: 24rpx 28rpx;
  background: #f0eeea;
}

.nav-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 32rpx 0;
}

.back-btn {
  width: 64rpx;
  height: 64rpx;
  line-height: 64rpx;
  text-align: center;
  border-radius: 16rpx;
  background: #ffffff;
  border: 1rpx solid rgba(0, 0, 0, 0.04);
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

.card {
  margin-top: 24rpx;
  padding: 28rpx;
  background: #ffffff;
  border-radius: 24rpx;
  border: 1rpx solid rgba(0, 0, 0, 0.04);
  box-shadow: 0 2rpx 16rpx rgba(0, 0, 0, 0.03);
}

.card-title {
  display: block;
  font-size: 28rpx;
  font-weight: 700;
  color: #1a1a1a;
}

.divider {
  height: 1rpx;
  margin: 20rpx 0;
  background: linear-gradient(90deg, rgba(0, 0, 0, 0.06), rgba(0, 0, 0, 0.02), rgba(0, 0, 0, 0.06));
}

.reason-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16rpx;
}

.reason-item {
  position: relative;
  display: flex;
  align-items: center;
  padding: 24rpx 20rpx;
  background: #f5f3ef;
  border-radius: 16rpx;
  border: 2rpx solid transparent;
}

.reason-item.active {
  border-color: #c97b5a;
  background: #fff5f0;
}

.reason-icon {
  width: 52rpx;
  height: 52rpx;
  line-height: 52rpx;
  text-align: center;
  border-radius: 14rpx;
  background: #ffffff;
  color: #1a1a1a;
  font-size: 24rpx;
  font-weight: 800;
  box-shadow: 0 2rpx 8rpx rgba(0, 0, 0, 0.04);
}

.reason-label {
  flex: 1;
  margin-left: 14rpx;
  font-size: 26rpx;
  font-weight: 600;
  color: #1a1a1a;
}

.reason-check {
  position: absolute;
  top: 8rpx;
  right: 8rpx;
  width: 32rpx;
  height: 32rpx;
  line-height: 32rpx;
  text-align: center;
  border-radius: 50%;
  background: #c97b5a;
  color: #ffffff;
  font-size: 20rpx;
}

.desc-input {
  width: 100%;
  height: 240rpx;
  padding: 20rpx;
  background: #f5f3ef;
  border-radius: 16rpx;
  font-size: 26rpx;
  color: #1a1a1a;
  box-sizing: border-box;
  line-height: 1.6;
}

.desc-footer {
  display: flex;
  justify-content: flex-end;
  margin-top: 12rpx;
}

.char-count {
  font-size: 22rpx;
  color: #999;
}

.image-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 16rpx;
}

.image-item {
  position: relative;
  width: 160rpx;
  height: 160rpx;
}

.preview-img {
  width: 100%;
  height: 100%;
  border-radius: 14rpx;
  border: 1rpx solid rgba(0, 0, 0, 0.04);
}

.delete-btn {
  position: absolute;
  top: -10rpx;
  right: -10rpx;
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
  width: 160rpx;
  height: 160rpx;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: #f5f3ef;
  border-radius: 14rpx;
  border: 2rpx dashed rgba(0, 0, 0, 0.1);
}

.add-icon {
  font-size: 52rpx;
  color: #999;
  font-weight: 300;
}

.add-text {
  margin-top: 8rpx;
  font-size: 20rpx;
  color: #999;
}

.image-tip {
  display: block;
  margin-top: 16rpx;
  font-size: 22rpx;
  color: #999;
}

.submit-btn {
  margin-top: 32rpx;
  height: 88rpx;
  line-height: 88rpx;
  border-radius: 20rpx;
  background: linear-gradient(135deg, #c97b5a, #b86a4a);
  color: #ffffff;
  font-size: 30rpx;
  font-weight: 700;
  border: none;
  box-shadow: 0 4rpx 16rpx rgba(244, 90, 11, 0.3);
}

.submit-btn[disabled] {
  opacity: 0.5;
  box-shadow: none;
}
</style>
