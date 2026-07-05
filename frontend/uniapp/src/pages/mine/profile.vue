<template>
  <view class="page">
    <!-- 顶部导航 -->
    <view class="nav-bar">
      <view class="back-btn" @tap="goBack">
        <text class="back-icon">←</text>
      </view>
      <text class="nav-title">编辑资料</text>
      <view class="nav-right"></view>
    </view>

    <!-- 头像 -->
    <view class="card">
      <view class="avatar-section" @tap="changeAvatar">
        <text class="avatar-label">头像</text>
        <view class="avatar-wrapper">
          <view class="avatar">{{ initial }}</view>
          <text class="arrow">›</text>
        </view>
      </view>
    </view>

    <!-- 基本信息 -->
    <view class="card">
      <view class="form-item">
        <text class="form-label">昵称</text>
        <input v-model="form.nickname" class="form-input" placeholder="请输入昵称" />
      </view>
      <view class="divider"></view>
      <view class="form-item">
        <text class="form-label">手机号</text>
        <text class="form-value">{{ maskPhone(form.phone) }}</text>
      </view>
      <view class="divider"></view>
      <view class="form-item">
        <text class="form-label">账号</text>
        <text class="form-value">{{ form.userAccount }}</text>
      </view>
    </view>

    <!-- 保存按钮 -->
    <button class="save-btn" @tap="saveProfile">保存修改</button>
  </view>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'

const form = reactive({
  nickname: '',
  phone: '',
  userAccount: '',
  avatarUrl: ''
})

const initial = computed(() => {
  const name = form.nickname || '用户'
  return name.slice(0, 1)
})

onMounted(() => {
  const userInfo = uni.getStorageSync('userInfo') || {}
  form.nickname = userInfo.nickname || ''
  form.phone = userInfo.phone || ''
  form.userAccount = userInfo.userAccount || ''
  form.avatarUrl = userInfo.avatarUrl || ''
})

function goBack() {
  uni.navigateBack()
}

function maskPhone(phone) {
  if (!phone || phone.length < 7) return '未绑定'
  return `${phone.slice(0, 3)}****${phone.slice(-4)}`
}

function changeAvatar() {
  uni.chooseImage({
    count: 1,
    sizeType: ['compressed'],
    sourceType: ['album', 'camera'],
    success: (res) => {
      form.avatarUrl = res.tempFilePaths[0]
      uni.showToast({ title: '头像已更新', icon: 'success' })
    }
  })
}

function saveProfile() {
  if (!form.nickname.trim()) {
    uni.showToast({ title: '请输入昵称', icon: 'none' })
    return
  }

  const userInfo = uni.getStorageSync('userInfo') || {}
  userInfo.nickname = form.nickname
  userInfo.avatarUrl = form.avatarUrl
  uni.setStorageSync('userInfo', userInfo)

  uni.showToast({ title: '保存成功', icon: 'success' })
  setTimeout(() => {
    uni.navigateBack()
  }, 1500)
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

/* 头像区域 */
.avatar-section {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.avatar-label {
  font-size: 28rpx;
  font-weight: 600;
  color: #1a1a1a;
}

.avatar-wrapper {
  display: flex;
  align-items: center;
  gap: 12rpx;
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

.arrow {
  font-size: 32rpx;
  color: #ccc;
}

/* 表单项 */
.form-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 24rpx 0;
}

.form-label {
  font-size: 28rpx;
  font-weight: 600;
  color: #1a1a1a;
}

.form-input {
  flex: 1;
  text-align: right;
  font-size: 28rpx;
  color: #1a1a1a;
}

.form-value {
  font-size: 28rpx;
  color: #999;
}

.divider {
  height: 1rpx;
  background: linear-gradient(90deg, rgba(0,0,0,0.06), rgba(0,0,0,0.02), rgba(0,0,0,0.06));
}

/* 保存按钮 */
.save-btn {
  margin-top: 48rpx;
  height: 88rpx;
  line-height: 88rpx;
  background: linear-gradient(135deg, #c97b5a, #b86a4a);
  border-radius: 20rpx;
  color: #ffffff;
  font-size: 30rpx;
  font-weight: 700;
  border: none;
  box-shadow: 0 4rpx 16rpx rgba(244,90,11,0.3);
}
</style>
