<template>
  <view class="page">
    <view class="brand-card">
      <view class="app-icon">
        <view class="bag-handle"></view>
        <view class="bag-body"><view class="bag-check"></view></view>
      </view>
      <view class="brand-copy">
        <text class="app-name">电商售后智能客服系统</text>
        <text class="app-version">Version 1.1.0</text>
        <text class="app-positioning">Java 后端与 AI 应用工程求职展示项目</text>
      </view>
    </view>

    <view class="content-card">
      <text class="section-title">项目介绍</text>
      <text class="paragraph">面向电商售后场景，覆盖订单、售后申请、智能客服、人工接管、评价分析和运营观测。业务最终状态由 Spring Boot 服务维护，Python Agent 负责 AI 编排与知识检索。</text>
    </view>

    <view class="content-card">
      <text class="section-title">技术栈</text>
      <view class="tag-list">
        <text v-for="item in techStack" :key="item" class="tag">{{ item }}</text>
      </view>
    </view>

    <view class="content-card">
      <text class="section-title">核心能力</text>
      <view v-for="item in capabilities" :key="item" class="bullet-row">
        <text class="bullet">•</text>
        <text class="bullet-text">{{ item }}</text>
      </view>
    </view>

    <view class="content-card">
      <text class="section-title">服务条款</text>
      <text class="paragraph">本项目用于本地教学、功能演示和技术交流。演示账号与演示数据仅用于验证业务流程；使用者应遵守适用法律法规，不得利用本项目处理违法内容或攻击第三方系统。</text>
    </view>

    <view class="content-card">
      <text class="section-title">隐私说明</text>
      <text class="paragraph">登录手机号、收货地址、反馈联系方式和业务记录仅写入当前配置的本地服务与数据库，用于完成对应功能。请勿在公开演示环境填写真实密码、验证码、身份证件或支付信息。</text>
    </view>

    <view class="footer">源代码、启动说明、架构与测试证据见仓库文档</view>
  </view>
</template>

<script setup>
const techStack = [
  'Spring Boot 3', 'Java 21', 'MyBatis-Plus', 'MySQL', 'Redis',
  'Kafka', 'Python Agent', 'Ollama', 'pgvector', 'Prometheus', 'Grafana', 'uni-app'
]

const capabilities = [
  '订单到售后工单的完整业务闭环',
  'AI 客服、RAG 检索、情绪分析与人工降级',
  'Transactional Outbox、重试与幂等控制',
  'JWT 鉴权、用户数据隔离与服务端持久化',
  'Prometheus 指标、Grafana 面板与自动化测试'
]
</script>

<style scoped>
.page {
  min-height: 100vh;
  padding: 28rpx 28rpx 64rpx;
  box-sizing: border-box;
  background: #f0eeea;
  color: #1f1f1f;
}

.brand-card,
.content-card {
  padding: 30rpx;
  border-radius: 24rpx;
  background: #ffffff;
  box-shadow: 0 2rpx 16rpx rgba(0, 0, 0, 0.04);
}

.brand-card {
  display: flex;
  align-items: center;
}

.app-icon {
  position: relative;
  flex-shrink: 0;
  width: 112rpx;
  height: 112rpx;
  border-radius: 26rpx;
  background: linear-gradient(180deg, #d79a72 0%, #b86a4a 100%);
  box-shadow: 0 10rpx 24rpx rgba(184, 106, 74, 0.22);
}

.bag-handle {
  position: absolute;
  left: 37rpx;
  top: 26rpx;
  width: 38rpx;
  height: 28rpx;
  border: 7rpx solid rgba(255, 255, 255, 0.92);
  border-bottom: 0;
  border-radius: 22rpx 22rpx 0 0;
  box-sizing: border-box;
}

.bag-body {
  position: absolute;
  left: 26rpx;
  top: 46rpx;
  width: 60rpx;
  height: 48rpx;
  border-radius: 10rpx;
  background: #ffffff;
}

.bag-check {
  position: absolute;
  left: 19rpx;
  top: 15rpx;
  width: 23rpx;
  height: 12rpx;
  border-left: 6rpx solid #b86a4a;
  border-bottom: 6rpx solid #b86a4a;
  transform: rotate(-45deg);
}

.brand-copy {
  min-width: 0;
  margin-left: 26rpx;
}

.app-name,
.app-version,
.app-positioning {
  display: block;
}

.app-name {
  font-size: 31rpx;
  font-weight: 800;
}

.app-version {
  margin-top: 8rpx;
  color: #b86a4a;
  font-size: 23rpx;
  font-weight: 700;
}

.app-positioning {
  margin-top: 10rpx;
  color: #888;
  font-size: 21rpx;
  line-height: 1.5;
}

.content-card {
  margin-top: 22rpx;
}

.section-title {
  display: block;
  margin-bottom: 18rpx;
  font-size: 29rpx;
  font-weight: 800;
}

.paragraph,
.bullet-text {
  color: #666;
  font-size: 24rpx;
  line-height: 1.75;
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 12rpx;
}

.tag {
  padding: 8rpx 16rpx;
  border-radius: 10rpx;
  background: #fff5f0;
  color: #a85f42;
  font-size: 21rpx;
}

.bullet-row {
  display: flex;
  align-items: flex-start;
  margin-top: 10rpx;
}

.bullet {
  margin-right: 12rpx;
  color: #c97b5a;
  line-height: 1.75;
}

.bullet-text {
  flex: 1;
}

.footer {
  padding: 44rpx 20rpx 0;
  text-align: center;
  color: #999;
  font-size: 21rpx;
}
</style>
