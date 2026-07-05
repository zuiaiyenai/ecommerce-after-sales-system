<template>
  <view class="page">
    <!-- 顶部导航 -->
    <view class="nav-bar">
      <view class="back-btn" @tap="goBack">
        <text class="back-icon">←</text>
      </view>
      <text class="nav-title">关于我们</text>
      <view class="nav-right"></view>
    </view>

    <!-- Logo 区域 -->
    <view class="logo-area">
      <view class="logo">🛒</view>
      <text class="app-name">电商售后客服</text>
      <text class="app-version">v1.0.0</text>
    </view>

    <!-- 介绍 -->
    <view class="card">
      <text class="card-title">应用介绍</text>
      <view class="divider"></view>
      <text class="intro-text">
        本应用是一款电商售后客服系统，为用户提供便捷的售后服务体验。
        通过智能客服与人工客服相结合的方式，快速解决您的售后问题。
      </text>
    </view>

    <!-- 功能特性 -->
    <view class="card">
      <text class="card-title">核心功能</text>
      <view class="divider"></view>
      <view class="feature-list">
        <view class="feature-item">
          <text class="feature-icon">🤖</text>
          <view class="feature-info">
            <text class="feature-name">智能客服</text>
            <text class="feature-desc">AI 驱动的智能问答，快速解答常见问题</text>
          </view>
        </view>
        <view class="feature-item">
          <text class="feature-icon">🔄</text>
          <view class="feature-info">
            <text class="feature-name">售后申请</text>
            <text class="feature-desc">在线提交退款、换货、维修等售后申请</text>
          </view>
        </view>
        <view class="feature-item">
          <text class="feature-icon">📦</text>
          <view class="feature-info">
            <text class="feature-name">订单管理</text>
            <text class="feature-desc">查看订单状态、物流信息、售后进度</text>
          </view>
        </view>
        <view class="feature-item">
          <text class="feature-icon">👤</text>
          <view class="feature-info">
            <text class="feature-name">人工客服</text>
            <text class="feature-desc">一键转接人工客服，获得专业帮助</text>
          </view>
        </view>
      </view>
    </view>

    <!-- 联系方式 -->
    <view class="card">
      <text class="card-title">联系我们</text>
      <view class="divider"></view>
      <view class="contact-item">
        <text class="contact-label">客服电话</text>
        <text class="contact-value">400-123-4567</text>
      </view>
      <view class="contact-item">
        <text class="contact-label">工作时间</text>
        <text class="contact-value">周一至周五 9:00-18:00</text>
      </view>
      <view class="contact-item">
        <text class="contact-label">客服邮箱</text>
        <text class="contact-value">support@ecommerce.com</text>
      </view>
    </view>

    <!-- 版权 -->
    <text class="copyright">© 2024 电商售后客服系统 版权所有</text>
  </view>
</template>

<script setup>
function goBack() {
  uni.navigateBack()
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

/* Logo */
.logo-area {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 48rpx 0 32rpx;
}

.logo {
  width: 120rpx;
  height: 120rpx;
  line-height: 120rpx;
  text-align: center;
  border-radius: 30rpx;
  background: linear-gradient(135deg, #c97b5a, #b86a4a);
  font-size: 56rpx;
}

.app-name {
  margin-top: 20rpx;
  font-size: 34rpx;
  font-weight: 800;
  color: #1a1a1a;
}

.app-version {
  margin-top: 8rpx;
  font-size: 24rpx;
  color: #999;
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

.card-title {
  display: block;
  font-size: 30rpx;
  font-weight: 800;
  color: #1a1a1a;
}

.divider {
  height: 1rpx;
  margin: 20rpx 0;
  background: linear-gradient(90deg, rgba(0,0,0,0.06), rgba(0,0,0,0.02), rgba(0,0,0,0.06));
}

.intro-text {
  font-size: 26rpx;
  color: #666;
  line-height: 1.8;
}

/* 功能特性 */
.feature-list {
  margin-top: 4rpx;
}

.feature-item {
  display: flex;
  align-items: flex-start;
  padding: 20rpx 0;
  border-bottom: 1rpx solid rgba(0,0,0,0.04);
}

.feature-item:last-child {
  border-bottom: none;
}

.feature-icon {
  font-size: 36rpx;
  margin-right: 20rpx;
}

.feature-info {
  flex: 1;
}

.feature-name {
  display: block;
  font-size: 28rpx;
  font-weight: 700;
  color: #1a1a1a;
}

.feature-desc {
  display: block;
  margin-top: 6rpx;
  font-size: 24rpx;
  color: #999;
}

/* 联系方式 */
.contact-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20rpx 0;
  border-bottom: 1rpx solid rgba(0,0,0,0.04);
}

.contact-item:last-child {
  border-bottom: none;
}

.contact-label {
  font-size: 26rpx;
  color: #666;
}

.contact-value {
  font-size: 26rpx;
  font-weight: 600;
  color: #1a1a1a;
}

/* 版权 */
.copyright {
  display: block;
  text-align: center;
  margin-top: 48rpx;
  padding-bottom: 48rpx;
  font-size: 22rpx;
  color: #bbb;
}
</style>
