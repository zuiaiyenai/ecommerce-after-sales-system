<template>
  <view class="page">
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

  </view>
</template>

<script setup>
import { ref } from 'vue'

const notifyEnabled = ref(true)
const cacheSize = ref('2.3MB')

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

</script>

<style scoped>
.page {
  width: 100%;
  min-height: 100vh;
  padding: 24rpx 28rpx;
  background: #f0eeea;
  box-sizing: border-box;
}

/* 卡片 */
.card {
  width: 100%;
  margin-top: 24rpx;
  padding: 28rpx;
  background: #ffffff;
  border-radius: 24rpx;
  border: 1rpx solid rgba(0,0,0,0.04);
  box-shadow: 0 2rpx 16rpx rgba(0,0,0,0.03);
  box-sizing: border-box;
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

</style>
