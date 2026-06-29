<template>
  <view class="page">
    <!-- 顶部导航 -->
    <view class="nav-bar">
      <view class="back-btn" @tap="goBack">
        <text class="back-icon">←</text>
      </view>
      <text class="nav-title">账号设置</text>
      <view class="nav-right"></view>
    </view>

    <!-- 账号信息 -->
    <view class="card">
      <view class="card-header">
        <text class="card-title">账号信息</text>
      </view>
      <view class="divider"></view>
      <view class="setting-item" @tap="goProfile">
        <text class="setting-label">编辑资料</text>
        <text class="setting-value">昵称、头像</text>
        <text class="arrow">›</text>
      </view>
      <view class="setting-item" @tap="changePassword">
        <text class="setting-label">修改密码</text>
        <text class="setting-value"></text>
        <text class="arrow">›</text>
      </view>
    </view>

    <!-- 通用设置 -->
    <view class="card">
      <view class="card-header">
        <text class="card-title">通用设置</text>
      </view>
      <view class="divider"></view>
      <view class="setting-item">
        <text class="setting-label">消息通知</text>
        <switch :checked="notifyEnabled" color="#c97b5a" @change="notifyEnabled = !notifyEnabled" />
      </view>
      <view class="setting-item" @tap="clearCache">
        <text class="setting-label">清除缓存</text>
        <text class="setting-value">{{ cacheSize }}</text>
        <text class="arrow">›</text>
      </view>
    </view>

    <!-- 关于 -->
    <view class="card">
      <view class="card-header">
        <text class="card-title">其他</text>
      </view>
      <view class="divider"></view>
      <view class="setting-item" @tap="goAbout">
        <text class="setting-label">关于我们</text>
        <text class="setting-value">v1.0.0</text>
        <text class="arrow">›</text>
      </view>
      <view class="setting-item" @tap="goFeedback">
        <text class="setting-label">意见反馈</text>
        <text class="setting-value"></text>
        <text class="arrow">›</text>
      </view>
    </view>

    <!-- 退出登录 -->
    <button class="logout-btn" @tap="logout">退出登录</button>
  </view>
</template>

<script setup>
import { ref } from 'vue'

const notifyEnabled = ref(true)
const cacheSize = ref('2.3MB')

function goBack() {
  uni.navigateBack()
}

function goProfile() {
  uni.navigateTo({ url: '/pages/mine/profile' })
}

function changePassword() {
  uni.showToast({ title: '修改密码功能开发中', icon: 'none' })
}

function clearCache() {
  uni.showModal({
    title: '提示',
    content: '确定清除缓存吗？',
    success: (res) => {
      if (res.confirm) {
        cacheSize.value = '0B'
        uni.showToast({ title: '缓存已清除', icon: 'success' })
      }
    }
  })
}

function goAbout() {
  uni.navigateTo({ url: '/pages/mine/about' })
}

function goFeedback() {
  uni.showToast({ title: '意见反馈功能开发中', icon: 'none' })
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
  border: 1rpx solid rgba(0,0,0,0.04);
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

/* 卡片 */
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

.divider {
  height: 1rpx;
  margin: 20rpx 0;
  background: linear-gradient(90deg, rgba(0,0,0,0.06), rgba(0,0,0,0.02), rgba(0,0,0,0.06));
}

/* 设置项 */
.setting-item {
  display: flex;
  align-items: center;
  padding: 24rpx 0;
  border-bottom: 1rpx solid rgba(0,0,0,0.04);
}

.setting-item:last-child {
  border-bottom: none;
}

.setting-label {
  flex: 1;
  font-size: 28rpx;
  font-weight: 600;
  color: #1a1a1a;
}

.setting-value {
  font-size: 24rpx;
  color: #999;
  margin-right: 12rpx;
}

.arrow {
  font-size: 32rpx;
  color: #ccc;
}

/* 退出按钮 */
.logout-btn {
  margin-top: 48rpx;
  height: 88rpx;
  line-height: 88rpx;
  background: #ffffff;
  border-radius: 24rpx;
  color: #c97b5a;
  font-size: 30rpx;
  font-weight: 700;
  border: 1rpx solid rgba(244,90,11,0.2);
  box-shadow: 0 2rpx 16rpx rgba(0,0,0,0.03);
}
</style>
