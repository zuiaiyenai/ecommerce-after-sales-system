<template>
  <view class="page">
    <!-- 头像 -->
    <view class="card">
      <view class="avatar-section" @tap="changeAvatar">
        <text class="avatar-label">头像</text>
        <view class="avatar-wrapper">
          <image v-if="avatarDisplayUrl" class="avatar avatar-image" :src="avatarDisplayUrl" mode="aspectFill" />
          <view v-else class="avatar">{{ initial }}</view>
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
import { reactive, computed } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { normalizeImageUrl, request, uploadFile } from '../../utils/request'

const form = reactive({
  nickname: '',
  phone: '',
  userAccount: '',
  avatarUrl: ''
})

const avatarDisplayUrl = computed(() => normalizeImageUrl(form.avatarUrl))

const initial = computed(() => {
  const name = form.nickname || '用户'
  return name.slice(0, 1)
})

onLoad(() => {
  loadProfile()
})

async function loadProfile() {
  const cached = uni.getStorageSync('userInfo') || {}
  fillForm(cached)
  try {
    const profile = await request({ url: '/miniapp/user/profile' })
    persistUserInfo(profile)
    fillForm(profile)
  } catch (e) {
    console.error('加载用户资料失败', e)
  }
}

function fillForm(userInfo) {
  form.nickname = userInfo.nickname || ''
  form.phone = userInfo.phone || ''
  form.userAccount = userInfo.userAccount || ''
  form.avatarUrl = userInfo.avatarUrl || ''
}

function persistUserInfo(profile) {
  const userInfo = {
    ...(uni.getStorageSync('userInfo') || {}),
    ...(profile || {})
  }
  uni.setStorageSync('userInfo', userInfo)
  return userInfo
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
    success: async (res) => {
      const filePath = res.tempFilePaths[0]
      const previousAvatarUrl = form.avatarUrl
      form.avatarUrl = filePath
      uni.showLoading({ title: '上传中' })
      try {
        const result = await uploadFile({
          url: '/miniapp/user/avatar',
          filePath,
          name: 'file'
        })
        if (!result || !result.url) {
          throw new Error('头像上传失败')
        }
        form.avatarUrl = result.url
        persistUserInfo({ avatarUrl: result.url })
        uni.hideLoading()
        uni.showToast({ title: '头像已更新', icon: 'success' })
      } catch (e) {
        form.avatarUrl = previousAvatarUrl
        uni.hideLoading()
        uni.showToast({ title: e.message || '头像上传失败', icon: 'none' })
      }
    }
  })
}

async function saveProfile() {
  if (!form.nickname.trim()) {
    uni.showToast({ title: '请输入昵称', icon: 'none' })
    return
  }

  try {
    const profile = await request({
      url: '/miniapp/user/profile',
      method: 'PUT',
      data: {
        nickname: form.nickname.trim(),
        avatarUrl: form.avatarUrl
      }
    })
    persistUserInfo(profile)
    fillForm(profile)
    uni.showToast({ title: '保存成功', icon: 'success' })
    setTimeout(() => {
      uni.navigateBack()
    }, 800)
  } catch (e) {
    uni.showToast({ title: e.message || '保存失败', icon: 'none' })
  }
}
</script>

<style scoped>
.page {
  min-height: 100vh;
  padding: 24rpx 28rpx;
  background: #f0eeea;
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

.avatar-image {
  display: block;
  line-height: 1;
  background: #f5f3ef;
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
