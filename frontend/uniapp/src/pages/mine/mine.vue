<template>
  <view class="page">
    <!-- 顶部用户信息 -->
    <view class="header">
      <view class="user-row" @tap="editProfile">
        <view class="avatar">{{ initial }}</view>
        <view class="user-info">
          <text class="user-name">{{ userInfo.nickname || '用户' }}</text>
          <text class="user-phone">{{ maskPhone(userInfo.phone) }}</text>
        </view>
        <text class="arrow">›</text>
      </view>
    </view>

    <!-- 我的订单 -->
    <view class="card">
      <view class="card-header">
        <text class="card-title">我的订单</text>
        <button class="link-btn" @tap="goOrders('all')">查看全部</button>
      </view>
      <view class="divider"></view>
      <view class="order-grid">
        <view class="order-grid-item" v-for="item in orderTabs" :key="item.key" @tap="goOrders(item.key)">
          <view class="grid-icon">{{ item.icon }}</view>
          <text class="grid-label">{{ item.label }}</text>
          <view v-if="item.badge > 0" class="badge">{{ item.badge }}</view>
        </view>
      </view>
    </view>

    <!-- 售后服务 -->
    <view class="card">
      <view class="card-header">
        <text class="card-title">售后服务</text>
      </view>
      <view class="divider"></view>
      <view class="menu-list">
        <view class="menu-item" @tap="goAfterSaleList">
          <text class="menu-icon">◆</text>
          <text class="menu-label">我的售后</text>
          <text class="menu-desc">查看售后进度</text>
          <text class="arrow">›</text>
        </view>
        <view class="menu-item" @tap="applyAfterSale">
          <text class="menu-icon">+</text>
          <text class="menu-label">申请售后</text>
          <text class="menu-desc">退款、换货、维修</text>
          <text class="arrow">›</text>
        </view>
        <view class="menu-item" @tap="goChat">
          <text class="menu-icon">◇</text>
          <text class="menu-label">联系客服</text>
          <text class="menu-desc">在线智能客服</text>
          <text class="arrow">›</text>
        </view>
      </view>
    </view>

    <!-- 其他服务 -->
    <view class="card">
      <view class="card-header">
        <text class="card-title">其他服务</text>
      </view>
      <view class="divider"></view>
      <view class="menu-list">
        <view class="menu-item" @tap="goAddress">
          <text class="menu-icon">◎</text>
          <text class="menu-label">收货地址</text>
          <text class="menu-desc">管理收货地址</text>
          <text class="arrow">›</text>
        </view>
        <view class="menu-item" @tap="goSettings">
          <text class="menu-icon">⚙</text>
          <text class="menu-label">账号设置</text>
          <text class="menu-desc">修改密码、个人信息</text>
          <text class="arrow">›</text>
        </view>
        <view class="menu-item" @tap="goAbout">
          <text class="menu-icon">i</text>
          <text class="menu-label">关于我们</text>
          <text class="menu-desc">版本信息</text>
          <text class="arrow">›</text>
        </view>
      </view>
    </view>

    <!-- 退出登录 -->
    <button class="logout-btn" @tap="logout">退出登录</button>

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
const activeTab = ref('mine')

const navItems = [
  { key: 'home', label: '首页', icon: '⌂' },
  { key: 'chat', label: '咨询', icon: '◇' },
  { key: 'mine', label: '我的', icon: '◒' }
]

const orderTabs = ref([
  { key: 'shipped', label: '已发货', icon: '□', badge: 0 },
  { key: 'received', label: '已收货', icon: '▷', badge: 0 },
  { key: 'aftersale', label: '售后中', icon: '◆', badge: 0 }
])

const initial = computed(() => {
  const name = userInfo.value.nickname || '用户'
  return name.slice(0, 1)
})

async function loadBadges() {
  try {
    const [orders, afterSales] = await Promise.all([
      request({ url: '/orders' }),
      request({ url: '/aftersales' })
    ])
    const shipped = (orders || []).filter(o => o.status === 'SHIPPED').length
    const received = (orders || []).filter(o => o.status === 'RECEIVED').length
    const aftersale = (afterSales || []).filter(a => a.status === 'PROCESSING').length

    // 读取已读记录
    const seen = uni.getStorageSync('badgeSeen') || {}

    orderTabs.value[0].badge = (seen.shipped === shipped) ? 0 : shipped
    orderTabs.value[1].badge = (seen.received === received) ? 0 : received
    orderTabs.value[2].badge = (seen.aftersale === aftersale) ? 0 : aftersale
  } catch (e) {
    console.error('加载角标失败', e)
  }
}

function markSeen(key) {
  const orders = orderTabs.value
  const tab = orders.find(t => t.key === key)
  if (tab && tab.badge > 0) {
    const seen = uni.getStorageSync('badgeSeen') || {}
    seen[key] = tab.badge
    uni.setStorageSync('badgeSeen', seen)
    tab.badge = 0
  }
}

onLoad(() => {
  userInfo.value = uni.getStorageSync('userInfo') || {}
  uni.setNavigationBarColor({
    frontColor: '#000000',
    backgroundColor: '#ffffff'
  })
  loadBadges()
})

function maskPhone(phone) {
  if (!phone || phone.length < 7) return '未绑定手机号'
  return `${phone.slice(0, 3)}****${phone.slice(-4)}`
}

function editProfile() {
  uni.navigateTo({ url: '/pages/mine/profile' })
}

function goOrders(type) {
  markSeen(type)
  uni.navigateTo({ url: '/pages/orders/list?tab=' + type })
}

function goAfterSaleList() {
  uni.navigateTo({ url: '/pages/after-sale/list' })
}

function applyAfterSale() {
  uni.navigateTo({ url: '/pages/after-sale/apply' })
}

function goChat() {
  uni.navigateTo({ url: '/pages/chat/consult' })
}

function goAddress() {
  uni.navigateTo({ url: '/pages/mine/address' })
}

function goSettings() {
  uni.navigateTo({ url: '/pages/mine/settings' })
}

function goAbout() {
  uni.navigateTo({ url: '/pages/mine/about' })
}

function switchTab(key) {
  if (key === 'home') {
    uni.navigateBack()
    return
  }
  if (key === 'chat') {
    uni.navigateTo({ url: '/pages/chat/consult' })
    return
  }
  activeTab.value = key
}

function logout() {
  uni.showModal({
    title: '提示',
    content: '确定退出登录吗？',
    success: (res) => {
      if (res.confirm) {
        uni.removeStorageSync('token')
        uni.removeStorageSync('userInfo')
        uni.redirectTo({ url: '/pages/auth/auth' })
      }
    }
  })
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
  padding: 32rpx;
  background: linear-gradient(135deg, #c97b5a, #b86a4a);
  border-radius: 24rpx;
  margin-bottom: 24rpx;
}

.user-row {
  display: flex;
  align-items: center;
}

.avatar {
  width: 100rpx;
  height: 100rpx;
  line-height: 100rpx;
  text-align: center;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.25);
  color: #ffffff;
  font-weight: 900;
  font-size: 40rpx;
}

.user-info {
  flex: 1;
  margin-left: 24rpx;
}

.user-name {
  display: block;
  font-size: 34rpx;
  font-weight: 800;
  color: #ffffff;
}

.user-phone {
  display: block;
  margin-top: 6rpx;
  font-size: 24rpx;
  color: rgba(255, 255, 255, 0.75);
}

.header .arrow {
  font-size: 40rpx;
  color: rgba(255, 255, 255, 0.6);
}

/* 通用卡片 */
.card {
  margin-bottom: 24rpx;
  padding: 28rpx;
  background: #ffffff;
  border-radius: 24rpx;
  border: 1rpx solid rgba(0, 0, 0, 0.04);
  box-shadow: 0 2rpx 16rpx rgba(0, 0, 0, 0.03);
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
  border: 1rpx solid rgba(0, 0, 0, 0.08);
  border-radius: 12rpx;
  background: transparent;
  color: #888;
  font-size: 22rpx;
}

.divider {
  height: 1rpx;
  margin: 20rpx 0;
  background: linear-gradient(90deg, rgba(0, 0, 0, 0.06), rgba(0, 0, 0, 0.02), rgba(0, 0, 0, 0.06));
}

/* 订单宫格 */
.order-grid {
  display: flex;
  justify-content: space-between;
}

.order-grid-item {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  position: relative;
  padding: 16rpx 0;
}

.grid-icon {
  width: 64rpx;
  height: 64rpx;
  line-height: 64rpx;
  text-align: center;
  border-radius: 50%;
  background: #f5f3ef;
  color: #1a1a1a;
  font-size: 28rpx;
  font-weight: 800;
}

.grid-label {
  margin-top: 12rpx;
  font-size: 22rpx;
  color: #666;
}

.badge {
  position: absolute;
  top: 8rpx;
  right: 20rpx;
  min-width: 32rpx;
  height: 32rpx;
  line-height: 32rpx;
  text-align: center;
  padding: 0 8rpx;
  border-radius: 32rpx;
  background: #e74c3c;
  color: #ffffff;
  font-size: 18rpx;
  font-weight: 700;
}

.badge:empty,
.badge[data-zero="true"] {
  display: none;
}

/* 菜单列表 */
.menu-list {
  margin-top: 4rpx;
}

.menu-item {
  display: flex;
  align-items: center;
  padding: 24rpx 0;
  border-bottom: 1rpx solid rgba(0, 0, 0, 0.04);
}

.menu-item:last-child {
  border-bottom: none;
}

.menu-icon {
  width: 48rpx;
  height: 48rpx;
  line-height: 48rpx;
  text-align: center;
  border-radius: 12rpx;
  background: #f5f3ef;
  color: #c97b5a;
  font-size: 24rpx;
  font-weight: 800;
}

.menu-label {
  flex: 1;
  margin-left: 20rpx;
  font-size: 28rpx;
  font-weight: 700;
  color: #1a1a1a;
}

.menu-desc {
  font-size: 22rpx;
  color: #999;
  margin-right: 12rpx;
}

.menu-item .arrow {
  font-size: 32rpx;
  color: #ccc;
}

/* 退出登录按钮 */
.logout-btn {
  margin-top: 16rpx;
  height: 88rpx;
  line-height: 88rpx;
  background: #ffffff;
  border-radius: 24rpx;
  color: #c97b5a;
  font-size: 30rpx;
  font-weight: 700;
  border: 1rpx solid rgba(244, 90, 11, 0.2);
  box-shadow: 0 2rpx 16rpx rgba(0, 0, 0, 0.03);
}

/* 底部导航 */
.bottom-nav {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  background: #ffffff;
  border-top: 1rpx solid rgba(0, 0, 0, 0.06);
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
