<template>
  <view class="page">
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
      <view class="title-row">
        <text class="card-title">问题描述</text>
        <text class="required-badge">必填</text>
      </view>
      <view class="divider"></view>
      <textarea
        v-model="description"
        class="desc-input"
        placeholder="请尽量描述清楚异常情况，例如：耳机没有声音、收到商品破损、少发了一件配件。"
        maxlength="500"
      />
      <view class="desc-footer">
        <text class="desc-tip">请描述至少20字，以便AI客服准确判断</text>
        <text class="char-count">{{ description.length }}/500</text>
      </view>
    </view>

    <view class="card">
      <view class="title-row">
        <text class="card-title">上传凭证</text>
        <text class="required-badge">建议上传</text>
      </view>
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
      <text class="image-tip">建议上传商品照片、破损照片或包装照片，最多 5 张。AI客服会根据图片快速判断。</text>
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
import { resolveOrderAfterSalesSnapshot } from '../../utils/orderStatus'

const PENDING_APPLY_PREFIX = 'after_sales_pending_apply'

const selectedReason = ref('')
const description = ref('')
const images = ref([])
const submitting = ref(false)
const orderId = ref('')
const orderData = ref(null)

const reasons = [
  { value: 'QUALITY', label: '质量问题', icon: '质' },
  { value: 'WRONG_ITEM', label: '发错货', icon: '错' },
  { value: 'SIZE_ISSUE', label: '尺码不合适', icon: '码' },
  { value: 'DAMAGE', label: '物流损坏', icon: '损' },
  { value: 'NOT_MATCH', label: '与描述不符', icon: '差' },
  { value: 'OTHER', label: '其他原因', icon: '其' }
]

function getPendingApplyKey(id) {
  return `${PENDING_APPLY_PREFIX}:${id || 'default'}`
}

onLoad(async (options) => {
  if (!options.orderId) return
  orderId.value = String(options.orderId)
  try {
    orderData.value = await request({ url: '/orders/' + orderId.value })
    if (orderData.value && resolveOrderAfterSalesSnapshot(orderData.value).hasAnyAfterSales) {
      uni.showToast({ title: '该订单已有售后记录', icon: 'none' })
      setTimeout(() => {
        uni.redirectTo({ url: '/pages/after-sale/detail?orderId=' + orderId.value })
      }, 800)
    }
  } catch (error) {
    orderData.value = null
  }
})

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
  if (!description.value.trim() || description.value.trim().length < 20) {
    uni.showToast({ title: '问题描述至少需要20字，以便AI客服准确判断', icon: 'none' })
    return
  }
  if (!orderData.value || !orderId.value) {
    uni.showToast({ title: '订单信息加载失败', icon: 'none' })
    return
  }

  submitting.value = true
  try {
    const reasonLabel = reasons.find((item) => item.value === selectedReason.value)?.label || selectedReason.value

    // 直接调用后端创建售后申请（状态=PENDING）
    const afterSalesData = {
      orderId: orderId.value,
      afterSaleType: 'RETURN_REFUND',
      reason: selectedReason.value,
      reasonDetail: reasonLabel,
      description: description.value.trim(),
      refundAmount: null,
      attachmentUrls: []
    }

    const result = await request({
      url: '/aftersales',
      method: 'POST',
      data: afterSalesData
    })
    const ticketId = result?.ticketId || result?.ticket_id || ''
    const ticketNo = result?.ticketNo || result?.ticket_no || ''

    // 创建成功后，跳转到对话页面，带上图片信息
    const pendingPayload = {
      orderId: orderId.value,
      ticketId,
      orderNo: orderData.value.orderNo || '',
      reasonValue: selectedReason.value,
      reasonLabel,
      description: description.value.trim(),
      initialMessage: `我的售后申请已提交，原因是${reasonLabel}。${description.value.trim()}`,
      imagePaths: [...images.value],
      createdAt: Date.now(),
      ticketNo
    }

    uni.setStorageSync(getPendingApplyKey(orderId.value), pendingPayload)
    const params = [
      `orderId=${encodeURIComponent(orderId.value)}`,
      'fromApply=1',
      ticketId ? `ticketId=${encodeURIComponent(ticketId)}` : '',
      ticketNo ? `ticketNo=${encodeURIComponent(ticketNo)}` : ''
    ].filter(Boolean).join('&')
    uni.redirectTo({
      url: `/pages/chat/consult?${params}`
    })
  } catch (error) {
    const errorMsg = error.message || error.msg || '创建售后申请失败'
    if (errorMsg.includes('已有进行中的售后申请')) {
      uni.showToast({ title: '该订单已有售后申请，正在跳转...', icon: 'none' })
      setTimeout(() => {
        uni.redirectTo({
          url: `/pages/chat/consult?orderId=${orderId.value}`
        })
      }, 1500)
    } else {
      uni.showToast({ title: errorMsg, icon: 'none' })
    }
    submitting.value = false
  }
}
</script>

<style scoped>
.page {
  min-height: 100vh;
  padding: 24rpx 28rpx 60rpx;
  background: #f0eeea;
}

.card {
  margin-top: 24rpx;
  padding: 28rpx;
  background: #ffffff;
  border-radius: 24rpx;
  border: 1rpx solid rgba(0, 0, 0, 0.04);
  box-shadow: 0 2rpx 16rpx rgba(0, 0, 0, 0.03);
}

.card:first-child {
  margin-top: 0;
}

.card-title {
  font-size: 30rpx;
  font-weight: 700;
  color: #1a1a1a;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 12rpx;
}

.required-badge {
  padding: 4rpx 12rpx;
  background: #fff4e8;
  border-radius: 8rpx;
  font-size: 20rpx;
  color: #c97b5a;
  font-weight: 600;
}

.divider {
  height: 1rpx;
  background: rgba(0, 0, 0, 0.06);
  margin: 24rpx 0;
}

.reason-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20rpx;
}

.reason-item {
  position: relative;
  padding: 24rpx 20rpx;
  border-radius: 20rpx;
  background: #f8f6f2;
  border: 2rpx solid transparent;
  display: flex;
  flex-direction: column;
  gap: 12rpx;
}

.reason-item.active {
  border-color: #c97b5a;
  background: #fff4ef;
}

.reason-icon {
  width: 56rpx;
  height: 56rpx;
  border-radius: 16rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(201, 123, 90, 0.12);
  color: #c97b5a;
  font-weight: 700;
}

.reason-label {
  font-size: 26rpx;
  color: #1a1a1a;
  font-weight: 600;
}

.reason-check {
  position: absolute;
  top: 18rpx;
  right: 18rpx;
  color: #c97b5a;
  font-size: 28rpx;
}

.desc-input {
  width: 100%;
  min-height: 220rpx;
  font-size: 26rpx;
  line-height: 1.7;
  color: #1a1a1a;
}

.desc-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 12rpx;
}

.desc-tip {
  font-size: 22rpx;
  color: #c97b5a;
}

.char-count,
.image-tip {
  font-size: 22rpx;
  color: #999;
}

.image-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 16rpx;
}

.image-item,
.add-image {
  width: 180rpx;
  height: 180rpx;
  border-radius: 20rpx;
  overflow: hidden;
  position: relative;
}

.preview-img {
  width: 100%;
  height: 100%;
}

.delete-btn {
  position: absolute;
  top: 10rpx;
  right: 10rpx;
  width: 36rpx;
  height: 36rpx;
  border-radius: 18rpx;
  background: rgba(0, 0, 0, 0.6);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24rpx;
}

.add-image {
  background: #f8f6f2;
  border: 2rpx dashed rgba(201, 123, 90, 0.35);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10rpx;
}

.add-icon {
  font-size: 44rpx;
  color: #c97b5a;
}

.add-text {
  font-size: 24rpx;
  color: #8a776c;
}

.submit-btn {
  margin-top: 36rpx;
  border-radius: 999rpx;
  background: #c97b5a;
  color: #fff;
  font-size: 28rpx;
  font-weight: 700;
}

.submit-btn[disabled] {
  opacity: 0.45;
}
</style>
