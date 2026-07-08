<template>
  <view class="page">
    <!-- 顶部导航 -->
    <view class="nav-bar">
      <view class="back-btn" @tap="goBack">
        <text class="back-icon">←</text>
      </view>
      <text class="nav-title">我的售后</text>
      <view class="nav-right"></view>
    </view>

    <!-- Tab 筛选 -->
    <view class="tabs">
      <view v-for="tab in tabs" :key="tab.key" class="tab-item" :class="{ active: activeTab === tab.key }" @tap="activeTab = tab.key">
        <text class="tab-text">{{ tab.label }}</text>
      </view>
    </view>

    <!-- 售后列表 -->
    <scroll-view class="list-area" scroll-y>
      <view v-if="filteredList.length === 0" class="empty">
        <text class="empty-icon">📋</text>
        <text class="empty-text">暂无售后记录</text>
      </view>

      <view v-for="item in filteredList" :key="item.id" class="card" @tap="goDetail(item.afterSaleNo)">
        <view class="card-header">
          <text class="card-no">售后单号：{{ item.afterSaleNo }}</text>
          <text class="card-status" :class="item.statusClass">{{ item.statusText }}</text>
        </view>
        <view class="divider"></view>
        <view class="card-body">
          <image class="product-icon" :src="normalizeImageUrl(item.productIcon)" mode="aspectFill" />
          <view class="product-info">
            <text class="product-name">{{ item.productName }}</text>
            <text class="merchant-name">商家：{{ item.merchantDisplayName || item.merchantCode || '演示商家' }}</text>
            <text class="product-reason">原因：{{ item.reason }}</text>
          </view>
        </view>
        <view class="divider"></view>
        <view class="card-footer">
          <text class="card-time">{{ item.createTime }}</text>
          <view class="card-actions">
            <button v-if="item.status === 'pending' || item.status === 'processing'" class="action-btn primary" @tap.stop="goChat(item.id)">联系客服</button>
            <button class="action-btn" @tap.stop="goDetail(item.afterSaleNo)">查看详情</button>
          </view>
        </view>
      </view>
    </scroll-view>

    <!-- 底部申请按钮 -->
    <view class="bottom-bar">
      <button class="apply-btn" @tap="applyAfterSale">
        <text class="apply-icon">+</text>
        <text>申请售后</text>
      </button>
    </view>
  </view>
</template>

<script setup>
import { ref, computed } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { normalizeImageUrl, request } from '../../utils/request'
import { resolveAfterSalesTicketDisplay } from '../../utils/orderStatus'

const activeTab = ref('all')
const allAfterSales = ref([])

const tabs = [
  { key: 'all', label: '全部' },
  { key: 'pending', label: '待审核' },
  { key: 'processing', label: '处理中' },
  { key: 'rejected', label: '已驳回' },
  { key: 'completed', label: '已完成' }
]

// 将API数据转换为页面需要的格式
const afterSaleList = computed(() => {
  return allAfterSales.value.map(a => {
    const display = resolveAfterSalesTicketDisplay(a)
    return {
      id: a.id,
      afterSaleNo: a.ticketNo,
      productName: a.productName,
      productIcon: a.productImage || '',
      reason: a.reason,
      merchantCode: a.merchantCode || '',
      merchantDisplayName: a.merchantDisplayName || '',
      status: display.statusKey,
      statusText: display.statusText,
      statusClass: display.statusClass,
      createTime: a.createTime ? a.createTime.slice(0, 10) : ''
    }
  })
})

const filteredList = computed(() => {
  if (activeTab.value === 'all') return afterSaleList.value
  return afterSaleList.value.filter(item => item.status === activeTab.value)
})

async function loadAfterSales() {
  try {
    const data = await request({ url: '/aftersales' })
    allAfterSales.value = data || []
  } catch (e) {
    console.error('加载售后列表失败', e)
  }
}

onLoad(() => {
  loadAfterSales()
})

function goBack() {
  uni.navigateBack()
}

function goDetail(ticketNo) {
  uni.navigateTo({ url: '/pages/after-sale/detail?ticketNo=' + ticketNo })
}

function goChat(id) {
  uni.navigateTo({ url: '/pages/chat/consult?afterSaleId=' + id })
}

function applyAfterSale() {
  uni.navigateTo({ url: '/pages/after-sale/apply' })
}
</script>

<style scoped>
.page {
  min-height: 100vh;
  background: #f0eeea;
  display: flex;
  flex-direction: column;
}

.nav-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 32rpx 28rpx;
  background: #ffffff;
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

/* Tabs */
.tabs {
  display: flex;
  background: #ffffff;
  padding: 0 28rpx;
  border-bottom: 1rpx solid rgba(0,0,0,0.04);
}

.tab-item {
  flex: 1;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24rpx 0;
}

.tab-text {
  font-size: 26rpx;
  color: #666;
}

.tab-item.active .tab-text {
  color: #c97b5a;
  font-weight: 700;
}

.tab-item.active::after {
  content: '';
  position: absolute;
  bottom: 0;
  left: 25%;
  right: 25%;
  height: 4rpx;
  border-radius: 4rpx;
  background: #c97b5a;
}

/* 列表 */
.list-area {
  flex: 1;
  padding: 20rpx 28rpx;
}

.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 120rpx 0;
}

.empty-icon {
  font-size: 80rpx;
}

.empty-text {
  margin-top: 20rpx;
  font-size: 28rpx;
  color: #999;
}

/* 卡片 */
.card {
  margin-bottom: 20rpx;
  padding: 24rpx;
  background: #ffffff;
  border-radius: 24rpx;
  border: 1rpx solid rgba(0,0,0,0.04);
  box-shadow: 0 2rpx 16rpx rgba(0,0,0,0.03);
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.card-no {
  font-size: 22rpx;
  color: #999;
}

.card-status {
  font-size: 24rpx;
  font-weight: 600;
}

.card-status.processing {
  color: #c97b5a;
}

.card-status.approved {
  color: #52c41a;
}

.card-status.rejected {
  color: #ff4d4f;
}

.card-status.completed {
  color: #999;
}

.divider {
  height: 1rpx;
  margin: 20rpx 0;
  background: linear-gradient(90deg, rgba(0,0,0,0.06), rgba(0,0,0,0.02), rgba(0,0,0,0.06));
}

.card-body {
  display: flex;
  align-items: center;
}

.product-icon {
  width: 64rpx;
  height: 64rpx;
  line-height: 64rpx;
  text-align: center;
  border-radius: 14rpx;
  background: #f5f3ef;
  color: #1a1a1a;
  font-size: 24rpx;
  font-weight: 800;
}

.product-info {
  flex: 1;
  margin-left: 16rpx;
}

.product-name {
  display: block;
  font-size: 28rpx;
  font-weight: 700;
  color: #1a1a1a;
}

.product-reason {
  display: block;
  margin-top: 6rpx;
  font-size: 22rpx;
  color: #999;
}

.merchant-name {
  display: block;
  margin-top: 6rpx;
  font-size: 22rpx;
  color: #8a776c;
}

.card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.card-time {
  font-size: 22rpx;
  color: #999;
}

.card-actions {
  display: flex;
  gap: 12rpx;
}

.action-btn {
  height: 56rpx;
  line-height: 56rpx;
  padding: 0 24rpx;
  border-radius: 28rpx;
  background: #f5f3ef;
  color: #666;
  font-size: 22rpx;
  font-weight: 600;
  border: none;
}

.action-btn.primary {
  background: linear-gradient(135deg, #c97b5a, #b86a4a);
  color: #ffffff;
}

/* 底部 */
.bottom-bar {
  padding: 20rpx 28rpx;
  padding-bottom: calc(20rpx + env(safe-area-inset-bottom));
  background: #ffffff;
  border-top: 1rpx solid rgba(0,0,0,0.06);
}

.apply-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8rpx;
  height: 88rpx;
  background: linear-gradient(135deg, #c97b5a, #b86a4a);
  border-radius: 20rpx;
  color: #ffffff;
  font-size: 30rpx;
  font-weight: 700;
  border: none;
  box-shadow: 0 4rpx 16rpx rgba(244,90,11,0.3);
}

.apply-icon {
  font-size: 36rpx;
}
</style>
