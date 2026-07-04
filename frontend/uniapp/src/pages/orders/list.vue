<template>
  <view class="page">
    <!-- 顶部导航 -->
    <view class="nav-bar">
      <view class="back-btn" @tap="goBack">
        <text class="back-icon">←</text>
      </view>
      <text class="nav-title">我的订单</text>
      <view class="nav-right"></view>
    </view>

    <!-- Tab 筛选 -->
    <view class="tabs">
      <view v-for="tab in tabs" :key="tab.key" class="tab-item" :class="{ active: activeTab === tab.key }" @tap="switchTab(tab.key)">
        <text class="tab-text">{{ tab.label }}</text>
        <view v-if="tab.badge > 0" class="tab-badge">{{ tab.badge }}</view>
      </view>
    </view>

    <!-- 订单列表 -->
    <scroll-view class="order-list" scroll-y>
      <view v-if="filteredOrders.length === 0" class="empty">
        <text class="empty-icon">📦</text>
        <text class="empty-text">暂无订单</text>
      </view>

      <view v-for="order in filteredOrders" :key="order.id" class="order-card" @tap="goDetail(order.id)">
        <view class="order-header">
          <text class="order-no">订单号：{{ order.orderNo }}</text>
          <text class="order-status" :class="order.statusClass">{{ order.statusText }}</text>
        </view>
        <view class="divider"></view>
        <view class="order-body">
          <image class="product-icon" :src="normalizeImageUrl(order.productIcon)" mode="aspectFill" />
          <view class="product-info">
            <text class="product-name">{{ order.productName }}</text>
            <text class="product-spec">{{ order.spec }}</text>
          </view>
          <view class="price-info">
            <text class="product-price">¥{{ order.price }}</text>
            <text class="product-qty">x{{ order.quantity }}</text>
          </view>
        </view>
        <view class="divider"></view>
        <view class="order-footer">
          <text class="order-total">共{{ order.quantity }}件 合计：<text class="total-price">¥{{ order.totalPrice }}</text></text>
          <view class="order-actions">
            <button v-if="order.status === 'SHIPPED'" class="action-btn" @tap.stop="confirmReceive(order.id)">确认收货</button>
            <button v-if="order.status === 'RECEIVED' || order.status === 'SHIPPED'" class="action-btn primary" @tap.stop="applyAfterSale(order.id)">申请售后</button>
            <button v-if="order.status === 'AFTERSALE'" class="action-btn primary" @tap.stop="contactService(order)">联系客服</button>
          </view>
        </view>
      </view>
    </scroll-view>
  </view>
</template>

<script setup>
import { ref, computed } from 'vue'
import { onLoad, onShow } from '@dcloudio/uni-app'
import { normalizeImageUrl, request } from '../../utils/request'

const activeTab = ref('all')
const allOrders = ref([])

function getStatusClass(status) {
  const map = { PAID: 'paid', SHIPPED: 'pending', RECEIVED: 'done', AFTERSALE: 'waiting', PROCESSING: 'processing', APPROVED: 'approved', REJECTED: 'rejected', COMPLETED: 'completed' }
  return map[status] || ''
}

const tabs = computed(() => {
  const paid = allOrders.value.filter(o => o.status === 'PAID').length
  const shipped = allOrders.value.filter(o => o.status === 'SHIPPED').length
  const received = allOrders.value.filter(o => o.status === 'RECEIVED').length
  const aftersale = allOrders.value.filter(o => o.status === 'AFTERSALE').length
  return [
    { key: 'all', label: '全部', badge: 0 },
    { key: 'paid', label: '未发货', badge: paid },
    { key: 'shipped', label: '配送中', badge: shipped },
    { key: 'received', label: '已收货', badge: received },
    { key: 'aftersale', label: '售后中', badge: aftersale }
  ]
})

// 将API数据转换为页面需要的格式
const orders = computed(() => {
  return allOrders.value.map(o => {
    const item = o.items && o.items[0]
    return {
      id: o.id,
      orderNo: o.orderNo,
      productName: item ? item.productName : o.orderNo,
      productIcon: item ? item.productImage : '',
      spec: item ? item.productSpec : '',
      price: item ? item.price : '0.00',
      quantity: o.items ? o.items.reduce((sum, i) => sum + i.quantity, 0) : 1,
      totalPrice: o.payAmount,
      status: o.status,
      statusText: o.statusText,
      statusClass: getStatusClass(o.status),
      createTime: o.createTime ? o.createTime.slice(0, 10) : ''
    }
  })
})

const filteredOrders = computed(() => {
  if (activeTab.value === 'all') return orders.value
  if (activeTab.value === 'aftersale') return orders.value.filter(o => o.status === 'AFTERSALE')
  return orders.value.filter(o => o.status.toLowerCase() === activeTab.value)
})

async function loadOrders() {
  try {
    const data = await request({ url: '/orders' })
    allOrders.value = data || []
  } catch (e) {
    console.error('加载订单失败', e)
  }
}

onLoad((options) => {
  if (options.tab) {
    activeTab.value = options.tab
  }
})

onShow(() => {
  loadOrders()
})

function goBack() {
  uni.navigateBack()
}

function switchTab(key) {
  activeTab.value = key
}

function goDetail(id) {
  uni.navigateTo({ url: '/pages/after-sale/detail?orderId=' + id })
}

function applyAfterSale(id) {
  uni.navigateTo({ url: '/pages/after-sale/apply?orderId=' + id })
}

function contactService(order) {
  const params = [
    'orderId=' + encodeURIComponent(order.id || ''),
    'orderNo=' + encodeURIComponent(order.orderNo || ''),
    'productName=' + encodeURIComponent(order.productName || ''),
    'productIcon=' + encodeURIComponent(order.productIcon || ''),
    'productSpec=' + encodeURIComponent(order.spec || ''),
    'amount=' + encodeURIComponent(order.totalPrice || order.price || ''),
    'status=' + encodeURIComponent(order.status || ''),
    'statusText=' + encodeURIComponent(order.statusText || '')
  ].join('&')
  uni.navigateTo({ url: `/pages/chat/consult?${params}` })
}

async function confirmReceive(id) {
  try {
    await request({ url: '/orders/' + id + '/status?status=RECEIVED', method: 'PUT' })
    await loadOrders()
    uni.showToast({ title: '已确认收货', icon: 'success' })
  } catch (e) {
    uni.showToast({ title: '操作失败，请重试', icon: 'none' })
  }
}
</script>

<style scoped>
.page {
  min-height: 100vh;
  background: #f0eeea;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.nav-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: calc(var(--status-bar-height) + 24rpx) 28rpx 24rpx;
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
  overflow: hidden;
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
  left: 30%;
  right: 30%;
  height: 4rpx;
  border-radius: 4rpx;
  background: #c97b5a;
}

.tab-badge {
  position: absolute;
  top: 12rpx;
  right: 10%;
  min-width: 28rpx;
  height: 28rpx;
  line-height: 28rpx;
  text-align: center;
  padding: 0 6rpx;
  border-radius: 28rpx;
  background: #e74c3c;
  color: #ffffff;
  font-size: 16rpx;
  font-weight: 700;
}

/* 订单列表 */
.order-list {
  flex: 1;
  padding: 20rpx 28rpx 20rpx 28rpx;
  box-sizing: border-box;
  overflow: hidden;
}

/* 空状态 */
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

/* 订单卡片 */
.order-card {
  margin-bottom: 20rpx;
  padding: 24rpx;
  background: #ffffff;
  border-radius: 24rpx;
  border: 1rpx solid rgba(0,0,0,0.04);
  box-shadow: 0 2rpx 16rpx rgba(0,0,0,0.03);
  overflow: hidden;
  box-sizing: border-box;
}

.order-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-width: 0;
}

.order-no {
  font-size: 22rpx;
  color: #999;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.order-status {
  font-size: 24rpx;
  font-weight: 600;
  flex-shrink: 0;
  margin-left: 16rpx;
}

.order-status.done {
  color: #52c41a;
}

.order-status.pending {
  color: #c97b5a;
}

.order-status.waiting {
  color: #999;
}

.divider {
  height: 1rpx;
  margin: 20rpx 0;
  background: linear-gradient(90deg, rgba(0,0,0,0.06), rgba(0,0,0,0.02), rgba(0,0,0,0.06));
}

.order-body {
  display: flex;
  align-items: center;
  min-width: 0;
}

.product-icon {
  width: 80rpx;
  height: 80rpx;
  line-height: 80rpx;
  text-align: center;
  border-radius: 16rpx;
  background: #f5f3ef;
  color: #1a1a1a;
  font-size: 28rpx;
  font-weight: 800;
}

.product-info {
  flex: 1;
  margin-left: 20rpx;
  min-width: 0;
  overflow: hidden;
}

.product-name {
  display: block;
  font-size: 28rpx;
  font-weight: 700;
  color: #1a1a1a;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.product-spec {
  display: block;
  margin-top: 6rpx;
  font-size: 22rpx;
  color: #999;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.price-info {
  text-align: right;
  flex-shrink: 0;
  margin-left: 16rpx;
}

.product-price {
  display: block;
  font-size: 28rpx;
  font-weight: 700;
  color: #1a1a1a;
}

.product-qty {
  display: block;
  margin-top: 6rpx;
  font-size: 22rpx;
  color: #999;
}

.order-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-width: 0;
}

.order-total {
  font-size: 24rpx;
  color: #666;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.total-price {
  font-weight: 800;
  color: #1a1a1a;
}

.order-actions {
  display: flex;
  gap: 12rpx;
  flex-shrink: 0;
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
</style>
