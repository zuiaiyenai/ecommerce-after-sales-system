<template>
  <view class="page">
    <view class="brand">
      <view class="app-icon">
        <view class="bag-handle"></view>
        <view class="bag-body">
          <view class="bag-check"></view>
        </view>
      </view>
      <text class="app-name">电商售后客服</text>
      <text class="app-version">Version 1.0.0</text>
    </view>

    <view class="menu">
      <view class="menu-item" @tap="showComingSoon('去评分')">
        <text class="menu-label">去评分</text>
        <text class="menu-arrow">›</text>
      </view>
      <view class="menu-item" @tap="showComingSoon('功能介绍')">
        <text class="menu-label">功能介绍</text>
        <text class="menu-arrow">›</text>
      </view>
      <view class="menu-item" @tap="showComingSoon('投诉')">
        <text class="menu-label">投诉</text>
        <text class="menu-arrow">›</text>
      </view>
      <view class="menu-item" @tap="showComingSoon('版本更新')">
        <text class="menu-label">版本更新</text>
        <text class="menu-arrow">›</text>
      </view>
    </view>

    <view class="footer">
      <text class="footer-text">本地教学与功能演示项目</text>
      <text class="footer-text">技术说明、运行证据与许可状态见仓库 README</text>
    </view>
  </view>
</template>

<script setup>
function showComingSoon(title) {
  uni.showToast({
    title: `${title}暂未开放`,
    icon: 'none'
  })
}
</script>

<style scoped>
.page {
  min-height: 100vh;
  padding: 0 60rpx 64rpx;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  background: #ffffff;
  color: #1f1f1f;
}

.brand {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: 206rpx;
  padding-bottom: 94rpx;
}

.app-icon {
  position: relative;
  width: 128rpx;
  height: 128rpx;
  border-radius: 30rpx;
  background: linear-gradient(180deg, #d79a72 0%, #b86a4a 100%);
  box-shadow: 0 12rpx 28rpx rgba(184, 106, 74, 0.24);
}

.bag-handle {
  position: absolute;
  left: 42rpx;
  top: 30rpx;
  width: 44rpx;
  height: 32rpx;
  border: 8rpx solid rgba(255, 255, 255, 0.92);
  border-bottom: 0;
  border-radius: 26rpx 26rpx 0 0;
  box-sizing: border-box;
}

.bag-body {
  position: absolute;
  left: 30rpx;
  top: 52rpx;
  width: 68rpx;
  height: 54rpx;
  border-radius: 12rpx;
  background: #ffffff;
}

.bag-check {
  position: absolute;
  left: 22rpx;
  top: 18rpx;
  width: 26rpx;
  height: 14rpx;
  border-left: 7rpx solid #b86a4a;
  border-bottom: 7rpx solid #b86a4a;
  transform: rotate(-45deg);
  box-sizing: border-box;
}

.app-name {
  margin-top: 66rpx;
  font-size: 42rpx;
  font-weight: 500;
  line-height: 1.2;
  color: #222222;
}

.app-version {
  margin-top: 22rpx;
  font-size: 34rpx;
  line-height: 1.2;
  color: #6d6d6d;
}

.menu {
  border-top: 1rpx solid #eeeeee;
}

.menu-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 116rpx;
  border-bottom: 1rpx solid #eeeeee;
}

.menu-label {
  font-size: 34rpx;
  color: #222222;
}

.menu-arrow {
  font-size: 60rpx;
  font-weight: 200;
  color: #b8b8b8;
  line-height: 1;
}

.footer {
  margin-top: auto;
  padding-top: 160rpx;
  padding-bottom: env(safe-area-inset-bottom);
  display: flex;
  flex-direction: column;
  align-items: center;
}

.footer-text {
  font-size: 25rpx;
  line-height: 1.45;
  color: #9a9a9a;
  text-align: center;
}

.footer-text + .footer-text {
  margin-top: 12rpx;
}
</style>
