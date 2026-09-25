<template>
  <view class="page">
    <view v-if="submitted" class="success-card">
      <view class="success-icon">✓</view>
      <text class="success-title">感谢你的反馈</text>
      <text class="success-text">反馈已保存，工作人员会在后台跟进处理。</text>
      <text class="feedback-no">反馈编号：{{ feedbackId }}</text>
      <button class="secondary-btn" @tap="resetForm">继续反馈</button>
      <button class="primary-btn" @tap="goBack">返回设置</button>
    </view>

    <template v-else>
      <view class="intro-card">
        <text class="intro-title">告诉我们哪里可以做得更好</text>
        <text class="intro-text">你的反馈会进入后台待处理列表。请勿填写密码、验证码等敏感信息。</text>
      </view>

      <view class="form-card">
        <text class="field-label">反馈类型</text>
        <view class="type-grid">
          <view
            v-for="item in feedbackTypes"
            :key="item.value"
            class="type-item"
            :class="{ active: form.type === item.value }"
            @tap="form.type = item.value"
          >
            {{ item.label }}
          </view>
        </view>

        <text class="field-label content-label">反馈内容</text>
        <textarea
          v-model="form.content"
          class="content-input"
          maxlength="1000"
          placeholder="请描述遇到的问题或建议（至少5个字符）"
        />
        <text class="counter">{{ form.content.length }}/1000</text>

        <text class="field-label">联系方式（选填）</text>
        <input
          v-model="form.contact"
          class="contact-input"
          maxlength="100"
          placeholder="手机号、邮箱或微信号"
        />
      </view>

      <button class="primary-btn submit-btn" :disabled="submitting" @tap="submitFeedback">
        {{ submitting ? '提交中...' : '提交反馈' }}
      </button>
    </template>
  </view>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { request } from '../../utils/request'

const feedbackTypes = [
  { value: 'FUNCTION', label: '功能建议' },
  { value: 'EXPERIENCE', label: '体验问题' },
  { value: 'BUG', label: '故障反馈' },
  { value: 'OTHER', label: '其他' }
]

const form = reactive({
  type: 'FUNCTION',
  content: '',
  contact: ''
})
const submitting = ref(false)
const submitted = ref(false)
const feedbackId = ref('')

async function submitFeedback() {
  const content = form.content.trim()
  if (content.length < 5) {
    uni.showToast({ title: '请至少填写5个字符', icon: 'none' })
    return
  }
  submitting.value = true
  try {
    const result = await request({
      url: '/miniapp/user/feedback',
      method: 'POST',
      data: {
        type: form.type,
        content,
        contact: form.contact.trim() || null
      }
    })
    feedbackId.value = result.id
    submitted.value = true
  } catch (error) {
    uni.showToast({ title: error.message || '提交失败，请稍后重试', icon: 'none' })
  } finally {
    submitting.value = false
  }
}

function resetForm() {
  form.type = 'FUNCTION'
  form.content = ''
  form.contact = ''
  feedbackId.value = ''
  submitted.value = false
}

function goBack() {
  uni.navigateBack()
}
</script>

<style scoped>
.page {
  min-height: 100vh;
  padding: 28rpx;
  box-sizing: border-box;
  background: #f0eeea;
  color: #1a1a1a;
}

.intro-card,
.form-card,
.success-card {
  padding: 32rpx;
  border-radius: 24rpx;
  background: #ffffff;
  box-shadow: 0 2rpx 16rpx rgba(0, 0, 0, 0.04);
}

.intro-title,
.success-title {
  display: block;
  font-size: 32rpx;
  font-weight: 800;
}

.intro-text,
.success-text {
  display: block;
  margin-top: 14rpx;
  color: #777;
  font-size: 24rpx;
  line-height: 1.65;
}

.form-card {
  margin-top: 24rpx;
}

.field-label {
  display: block;
  margin-bottom: 18rpx;
  font-size: 27rpx;
  font-weight: 700;
}

.content-label {
  margin-top: 34rpx;
}

.type-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16rpx;
}

.type-item {
  height: 68rpx;
  line-height: 68rpx;
  text-align: center;
  border: 1rpx solid #e6e2de;
  border-radius: 14rpx;
  color: #666;
  font-size: 25rpx;
}

.type-item.active {
  border-color: #c97b5a;
  background: #fff5f0;
  color: #b86a4a;
  font-weight: 700;
}

.content-input {
  width: 100%;
  height: 260rpx;
  padding: 22rpx;
  box-sizing: border-box;
  border-radius: 16rpx;
  background: #f7f6f4;
  font-size: 26rpx;
  line-height: 1.6;
}

.counter {
  display: block;
  margin: 10rpx 0 32rpx;
  text-align: right;
  color: #aaa;
  font-size: 21rpx;
}

.contact-input {
  height: 76rpx;
  padding: 0 22rpx;
  border-radius: 14rpx;
  background: #f7f6f4;
  font-size: 26rpx;
}

.primary-btn,
.secondary-btn {
  height: 88rpx;
  line-height: 88rpx;
  border-radius: 20rpx;
  font-size: 28rpx;
  font-weight: 700;
}

.primary-btn {
  background: linear-gradient(135deg, #c97b5a, #b86a4a);
  color: #ffffff;
}

.primary-btn[disabled] {
  opacity: 0.65;
}

.submit-btn {
  margin-top: 32rpx;
}

.success-card {
  margin-top: 120rpx;
  text-align: center;
}

.success-icon {
  width: 112rpx;
  height: 112rpx;
  line-height: 112rpx;
  margin: 0 auto 30rpx;
  border-radius: 50%;
  background: #e9f7ef;
  color: #36a269;
  font-size: 56rpx;
  font-weight: 800;
}

.feedback-no {
  display: block;
  margin-top: 24rpx;
  color: #999;
  font-size: 22rpx;
}

.secondary-btn {
  margin-top: 48rpx;
  border: 1rpx solid #d8d2cc;
  background: #ffffff;
  color: #666;
}

.success-card .primary-btn {
  margin-top: 20rpx;
}
</style>
