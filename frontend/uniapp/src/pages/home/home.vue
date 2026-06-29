<template>
  <view class="page">
    <!-- 顶部：头像和用户名 -->
    <view class="header" @tap="editProfile">
      <view class="user-row">
        <view class="avatar">{{ initial }}</view>
        <view class="user-info">
          <text class="user-name">{{ userInfo.nickname || '用户' }}</text>
          <text class="user-phone">{{ maskPhone(userInfo.phone) }}</text>
        </view>
      </view>
    </view>

    <!-- 服务概览 -->
    <view class="card overview-card">
      <view class="card-header">
        <text class="card-title">服务概览</text>
      </view>
      <view class="divider"></view>
      <view class="overview-grid">
        <view v-for="item in overview" :key="item.label" class="overview-item">
          <text class="overview-value">{{ item.value }}</text>
          <text class="overview-label">{{ item.label }}</text>
          <view class="bar-track">
            <view class="bar-fill" :style="{ width: item.percent + '%' }"></view>
          </view>
        </view>
      </view>
    </view>

    <!-- 最近订单 -->
    <view class="card orders-card">
      <view class="card-header">
        <text class="card-title">最近订单</text>
        <button class="link-btn" @tap="goOrders">查看全部</button>
      </view>
      <view class="divider"></view>
      <view class="order-list">
        <view v-for="item in orders" :key="item.id" class="order-item">
          <image class="order-icon" :src="item.icon" mode="aspectFill" />
          <view class="order-content">
            <text class="order-title">{{ item.title }}</text>
            <text class="order-desc">{{ item.desc }}</text>
          </view>
          <text class="order-status" :class="item.statusClass">{{ item.status }}</text>
        </view>
      </view>
    </view>

    <button class="apply-btn" @tap="goShop">
      <text class="apply-icon">＋</text>
      <text>演示购买商品</text>
    </button>

    <!-- 底部导航 -->
    <view class="bottom-nav">
      <view v-for="item in navItems" :key="item.key" class="nav-item" :class="{ active: activeTab === item.key }" @tap="switchTab(item.key)">
        <text class="nav-icon">{{ item.icon }}</text>
        <text class="nav-label">{{ item.label }}</text>
      </view>
    </view>
  </view>
</template>

<script setup>
import { computed, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { request } from '../../utils/request'

const userInfo = ref({})
const activeTab = ref('home')
const allOrders = ref([])
const allAfterSales = ref([])

const navItems = [
  { key: 'home', label: '首页', icon: '⌂' },
  { key: 'chat', label: '咨询', icon: '◇' },
  { key: 'mine', label: '我的', icon: '◒' }
]

function getStatusClass(status) {
  const map = { PAID: 'paid', SHIPPED: 'pending', RECEIVED: 'done', AFTERSALE: 'waiting', PROCESSING: 'processing', APPROVED: 'approved', REJECTED: 'rejected', COMPLETED: 'completed' }
  return map[status] || ''
}

// 从API数据计算概览
const overview = computed(() => {
  const orders = allOrders.value
  const aftersales = allAfterSales.value
  const received = orders.filter(o => o.status === 'RECEIVED').length
  const shipped = orders.filter(o => o.status === 'SHIPPED').length
  const aftersale = aftersales.filter(a => a.status === 'PROCESSING').length
  const total = orders.length
  return [
    { label: '已收货订单', value: received, percent: total ? Math.round(received / total * 100) : 0 },
    { label: '待收货', value: shipped, percent: total ? Math.round(shipped / total * 100) : 0 },
    { label: '售后处理中', value: aftersale, percent: total ? Math.round(aftersale / total * 100) : 0 }
  ]
})

// 从API数据渲染最近订单（取前3条）
const orders = computed(() => {
  return allOrders.value.slice(0, 3).map(o => {
    const item = o.items && o.items[0]
    return {
      id: o.id,
      icon: item ? item.productImage : '',
      title: item ? item.productName : o.orderNo,
      desc: `${o.createTime.slice(0, 10)} | ¥${o.payAmount}`,
      status: o.statusText,
      statusClass: getStatusClass(o.status)
    }
  })
})

const initial = computed(() => {
  const name = userInfo.value.nickname || '用户'
  return name.slice(0, 1)
})

async function loadData() {
  try {
    const [ordersData, afterSalesData] = await Promise.all([
      request({ url: '/orders' }),
      request({ url: '/aftersales' })
    ])
    allOrders.value = ordersData || []
    allAfterSales.value = afterSalesData || []
  } catch (e) {
    console.error('加载数据失败', e)
  }
}

onLoad(() => {
  userInfo.value = uni.getStorageSync('userInfo') || {}
  loadData()
})

function maskPhone(phone) {
  if (!phone || phone.length < 7) return '未绑定手机号'
  return `${phone.slice(0, 3)}****${phone.slice(-4)}`
}

function editProfile() {
  uni.navigateTo({ url: '/pages/mine/mine' })
}

function goOrders() {
  uni.navigateTo({ url: '/pages/orders/list' })
}

function goShop() {
  uni.navigateTo({ url: '/pages/shop/shop' })
}

function viewOrderDetail(id) {
  uni.navigateTo({
    url: '/pages/after-sale/detail?id=' + id
  })
}

function applyAfterSale() {
  // 跳转到售后申请页面（选择原因、填写信息）
  uni.navigateTo({
    url: '/pages/after-sale/apply'
  })
}

function switchTab(key) {
  if (key === 'chat') {
    uni.navigateTo({
      url: '/pages/chat/consult'
    })
    return
  }
  if (key === 'mine') {
    uni.navigateTo({
      url: '/pages/mine/mine'
    })
    return
  }
  activeTab.value = key
}

function logout() {
  uni.removeStorageSync('token')
  uni.removeStorageSync('userInfo')
  uni.redirectTo({ url: '/pages/auth/auth' })
}
</script>

<style scoped>
.page {
  min-height: 100vh;
  padding: 24rpx 28rpx 140rpx;
  background: #f0eeea;
}

/* 顶部用户区域 */
.header {
  padding: 32rpx 0 24rpx;
}

.user-row {
  display: flex;
  align-items: center;
}

.avatar {
  width: 80rpx;
  height: 80rpx;
  line-height: 80rpx;
  text-align: center;
  border-radius: 50%;
  background: linear-gradient(135deg, #c97b5a, #b86a4a);
  color: #ffffff;
  font-weight: 900;
  font-size: 32rpx;
}

.user-info {
  margin-left: 20rpx;
}

.user-name {
  display: block;
  font-size: 30rpx;
  font-weight: 800;
  color: #1a1a1a;
}

.user-phone {
  display: block;
  margin-top: 4rpx;
  font-size: 24rpx;
  color: #999;
}

/* 通用卡片 */
.card {
  margin-top: 24rpx;
  padding: 28rpx;
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

.card-title {
  font-size: 30rpx;
  font-weight: 800;
  color: #1a1a1a;
}

.link-btn {
  height: 48rpx;
  line-height: 48rpx;
  padding: 0 20rpx;
  border: 1rpx solid rgba(0,0,0,0.08);
  border-radius: 12rpx;
  background: transparent;
  color: #888;
  font-size: 22rpx;
}

.divider {
  height: 1rpx;
  margin: 20rpx 0;
  background: linear-gradient(90deg, rgba(0,0,0,0.06), rgba(0,0,0,0.02), rgba(0,0,0,0.06));
}

/* 服务概览 */
.overview-grid {
  display: flex;
  gap: 20rpx;
}

.overview-item {
  flex: 1;
}

.overview-value {
  display: block;
  font-size: 52rpx;
  font-weight: 900;
  color: #1a1a1a;
  line-height: 1.1;
}

.overview-label {
  display: block;
  margin-top: 8rpx;
  font-size: 22rpx;
  color: #999;
}

.bar-track {
  height: 8rpx;
  margin-top: 16rpx;
  border-radius: 8rpx;
  background: #f0eeea;
}

.bar-fill {
  height: 100%;
  border-radius: 8rpx;
  background: linear-gradient(90deg, #c97b5a, #d99070);
}

/* 订单列表 */
.order-list {
  margin-top: 8rpx;
}

.order-item {
  display: flex;
  align-items: center;
  padding: 20rpx 0;
  border-bottom: 1rpx solid rgba(0,0,0,0.04);
}

.order-item:last-child {
  border-bottom: none;
}

.order-icon {
  width: 56rpx;
  height: 56rpx;
  line-height: 56rpx;
  text-align: center;
  border-radius: 14rpx;
  background: #f5f3ef;
  color: #1a1a1a;
  font-size: 24rpx;
  font-weight: 800;
}

.order-content {
  flex: 1;
  margin-left: 16rpx;
}

.order-title {
  display: block;
  font-size: 26rpx;
  font-weight: 700;
  color: #1a1a1a;
}

.order-desc {
  display: block;
  margin-top: 4rpx;
  font-size: 22rpx;
  color: #999;
}

.order-status {
  font-size: 22rpx;
  font-weight: 600;
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

/* 申请售后按钮 */
.apply-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8rpx;
  margin-top: 24rpx;
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

/* 底部导航 */
.bottom-nav {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  background: #ffffff;
  border-top: 1rpx solid rgba(0,0,0,0.06);
  padding: 16rpx 0;
  padding-bottom: calc(16rpx + env(safe-area-inset-bottom));
}

.nav-item {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.nav-icon {
  font-size: 36rpx;
  color: #999;
}

.nav-item.active .nav-icon {
  color: #c97b5a;
}

.nav-label {
  margin-top: 4rpx;
  font-size: 20rpx;
  color: #999;
}

.nav-item.active .nav-label {
  color: #c97b5a;
  font-weight: 700;
}
</style>
