<template>
  <view class="page">
    <view class="brand">
      <view class="app-icon">
        <image class="app-icon-img" src="/static/images/mine/about.png" mode="aspectFit" />
      </view>
      <text class="app-name">电商售后客服</text>
      <text class="app-version">Version 1.0.0</text>
    </view>

    <view class="menu-list">
      <view class="menu-item" v-for="item in menuItems" :key="item.label" @tap="handleMenu(item.action)">
        <text class="menu-label">{{ item.label }}</text>
        <text class="arrow">›</text>
      </view>
    </view>

    <view class="footer">
      <view class="agreement-row">
        <text class="agreement" @tap="showAgreement('服务协议')">《软件许可及服务协议》</text>
      </view>
      <view class="agreement-row">
        <text class="agreement" @tap="showAgreement('隐私保护指引摘要')">《隐私保护指引摘要》</text>
        <text class="agreement gap" @tap="showAgreement('隐私保护指引')">《隐私保护指引》</text>
      </view>
      <text class="footer-text">客服电话：400-123-4567</text>
      <text class="footer-text">ICP备案信息：粤 B2-20260001</text>
      <text class="footer-text">电商售后客服系统 版权所有</text>
      <text class="copyright">Copyright © 2024-2026 Ecommerce. All Rights Reserved.</text>
    </view>
  </view>
</template>

<script setup>
import { onLoad, onUnload } from '@dcloudio/uni-app'

const menuItems = [
  { label: '去评分', action: 'rate' },
  { label: '功能介绍', action: 'features' },
  { label: '投诉', action: 'complaint' },
  { label: '版本更新', action: 'update' }
]

onLoad(() => {
  uni.setNavigationBarColor({
    frontColor: '#000000',
    backgroundColor: '#ffffff'
  })
})

onUnload(() => {
  uni.setNavigationBarColor({
    frontColor: '#000000',
    backgroundColor: '#ffffff'
  })
})

function handleMenu(action) {
  const messages = {
    rate: '感谢支持，评分功能开发中',
    features: '支持智能客服、售后申请、订单追踪与人工客服',
    complaint: '投诉反馈功能开发中',
    update: '当前已是最新版本'
  }

  uni.showToast({
    title: messages[action],
    icon: 'none'
  })
}

function showAgreement(title) {
  uni.showToast({
    title,
    icon: 'none'
  })
}
</script>

<style scoped>
.page {
  position: relative;
  width: 100%;
  min-height: 100vh;
  padding: 1rpx 60rpx 360rpx;
  background: #ffffff;
  box-sizing: border-box;
}

.brand {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: 210rpx;
  padding-bottom: 78rpx;
}

.app-icon {
  position: relative;
  width: 128rpx;
  height: 128rpx;
  overflow: hidden;
  border-radius: 28rpx;
  background: linear-gradient(135deg, #f4dfcc, #c97b5a);
}

.app-icon-img {
  position: absolute;
  left: -42rpx;
  top: -42rpx;
  width: 212rpx;
  height: 212rpx;
}

.app-name {
  margin-top: 58rpx;
  font-size: 42rpx;
  font-weight: 700;
  color: #222222;
  line-height: 1.2;
}

.app-version {
  margin-top: 22rpx;
  font-size: 34rpx;
  color: #8a8a8a;
  line-height: 1.2;
}

.menu-list {
  width: 100%;
  border-top: 1rpx solid #ededed;
}

.menu-item {
  display: flex;
  align-items: center;
  height: 108rpx;
  border-bottom: 1rpx solid #ededed;
}

.menu-label {
  flex: 1;
  font-size: 34rpx;
  color: #333333;
}

.arrow {
  font-size: 50rpx;
  line-height: 1;
  color: #b8b8b8;
}

.footer {
  position: absolute;
  left: 28rpx;
  right: 28rpx;
  bottom: calc(46rpx + env(safe-area-inset-bottom));
  display: flex;
  flex-direction: column;
  align-items: center;
}

.agreement-row {
  display: flex;
  justify-content: center;
  flex-wrap: wrap;
  margin-top: 18rpx;
}

.agreement {
  font-size: 24rpx;
  color: #667899;
  line-height: 1.45;
}

.gap {
  margin-left: 16rpx;
}

.footer-text,
.copyright {
  margin-top: 18rpx;
  font-size: 24rpx;
  color: #9a9a9a;
  line-height: 1.35;
  text-align: center;
}

.copyright {
  margin-top: 14rpx;
}
</style>
