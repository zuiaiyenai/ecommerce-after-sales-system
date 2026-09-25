<template>
  <view class="page">
    <!-- 地址列表 -->
    <scroll-view class="list-area" scroll-y>
      <view v-if="loading" class="empty">
        <text class="empty-text">地址加载中...</text>
      </view>
      <view v-else-if="loadError" class="empty">
        <text class="empty-text">{{ loadError }}</text>
        <button class="retry-btn" @tap="loadAddresses">重新加载</button>
      </view>
      <view v-else-if="addresses.length === 0" class="empty">
        <text class="empty-icon">📍</text>
        <text class="empty-text">暂无收货地址</text>
      </view>

      <view v-for="addr in addresses" :key="addr.id" class="address-card">
        <view class="addr-header">
          <text class="addr-name">{{ addr.name }}</text>
          <text class="addr-phone">{{ addr.phone }}</text>
          <view v-if="addr.isDefault" class="default-tag">默认</view>
        </view>
        <text class="addr-detail">{{ addressText(addr) }}</text>
        <view class="addr-footer">
          <view class="addr-action" @tap="setDefault(addr.id)">
            <text class="radio" :class="{ checked: addr.isDefault }">{{ addr.isDefault ? '◉' : '○' }}</text>
            <text class="radio-label">默认地址</text>
          </view>
          <view class="addr-btns">
            <view class="addr-btn" @tap="editAddress(addr)">编辑</view>
            <view class="addr-btn danger" @tap="deleteAddress(addr.id)">删除</view>
          </view>
        </view>
      </view>
    </scroll-view>

    <!-- 新增按钮 -->
    <view class="bottom-bar">
      <button class="add-btn" @tap="openCreate">+ 新增收货地址</button>
    </view>

    <!-- 新增/编辑弹窗 -->
    <view v-if="showForm" class="modal-mask" @tap.self="closeForm">
      <view class="modal-content" @tap.stop>
        <text class="modal-title">{{ editingId ? '编辑地址' : '新增地址' }}</text>
        <view class="divider"></view>
        <view class="form-item">
          <text class="form-label">收货人</text>
          <input v-model="form.name" class="form-input" placeholder="请输入收货人姓名" />
        </view>
        <view class="form-item">
          <text class="form-label">手机号</text>
          <input v-model="form.phone" class="form-input" placeholder="请输入手机号" type="number" maxlength="11" />
        </view>
        <view class="form-item">
          <text class="form-label">所在地区</text>
          <picker mode="region" :value="regionValue" @change="onRegionChange">
            <view class="form-input picker-text" :class="{ placeholder: !regionText }">
              {{ regionText || '请选择省/市/区' }}
            </view>
          </picker>
        </view>
        <view class="form-item">
          <text class="form-label">详细地址</text>
          <input v-model="form.detail" class="form-input" placeholder="街道、楼栋、门牌号" />
        </view>
        <view class="form-check">
          <text class="radio" :class="{ checked: form.isDefault }" @tap="form.isDefault = !form.isDefault">{{ form.isDefault ? '◉' : '○' }}</text>
          <text class="radio-label" @tap="form.isDefault = !form.isDefault">设为默认地址</text>
        </view>
        <view class="form-actions">
          <button class="cancel-btn" @tap="closeForm">取消</button>
          <button class="save-btn" :disabled="saving" @tap="saveAddress">{{ saving ? '保存中...' : '保存' }}</button>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup>
import { computed, ref, reactive } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { request } from '../../utils/request'

const addresses = ref([])
const loading = ref(false)
const loadError = ref('')
const saving = ref(false)

const showForm = ref(false)
const editingId = ref(null)
const form = reactive({
  name: '',
  phone: '',
  province: '',
  city: '',
  district: '',
  detail: '',
  isDefault: false
})
const regionValue = computed(() => [form.province, form.city, form.district])
const regionText = computed(() => [form.province, form.city, form.district].filter(Boolean).join(' / '))

onLoad(() => {
  loadAddresses()
})

async function loadAddresses() {
  loading.value = true
  loadError.value = ''
  try {
    addresses.value = await request({ url: '/miniapp/user/addresses' })
  } catch (error) {
    loadError.value = error.message || '地址加载失败'
  } finally {
    loading.value = false
  }
}

function addressText(addr) {
  return `${addr.province || ''}${addr.city || ''}${addr.district || ''} ${addr.detail || ''}`.trim()
}

function openCreate() {
  editingId.value = null
  resetForm()
  showForm.value = true
}

function closeForm() {
  showForm.value = false
  editingId.value = null
  resetForm()
}

function resetForm() {
  form.name = ''
  form.phone = ''
  form.province = ''
  form.city = ''
  form.district = ''
  form.detail = ''
  form.isDefault = false
}

function editAddress(addr) {
  editingId.value = addr.id
  form.name = addr.name
  form.phone = addr.phone
  form.province = addr.province || ''
  form.city = addr.city || ''
  form.district = addr.district || ''
  form.detail = addr.detail
  form.isDefault = addr.isDefault
  showForm.value = true
}

function onRegionChange(event) {
  const [province = '', city = '', district = ''] = event.detail.value || []
  form.province = province
  form.city = city
  form.district = district
}

async function saveAddress() {
  if (!form.name.trim()) {
    uni.showToast({ title: '请输入收货人姓名', icon: 'none' })
    return
  }
  if (!form.phone.trim() || form.phone.length !== 11) {
    uni.showToast({ title: '请输入正确手机号', icon: 'none' })
    return
  }
  if (!form.province || !form.city || !form.district) {
    uni.showToast({ title: '请选择所在地区', icon: 'none' })
    return
  }
  if (!form.detail.trim()) {
    uni.showToast({ title: '请输入详细地址', icon: 'none' })
    return
  }

  const data = {
    name: form.name.trim(),
    phone: form.phone.trim(),
    province: form.province,
    city: form.city,
    district: form.district,
    detail: form.detail.trim(),
    isDefault: form.isDefault
  }
  saving.value = true
  try {
    await request({
      url: editingId.value ? `/miniapp/user/addresses/${editingId.value}` : '/miniapp/user/addresses',
      method: editingId.value ? 'PUT' : 'POST',
      data
    })
    await loadAddresses()
    closeForm()
    uni.showToast({ title: '保存成功', icon: 'success' })
  } catch (error) {
    uni.showToast({ title: error.message || '保存失败', icon: 'none' })
  } finally {
    saving.value = false
  }
}

function deleteAddress(id) {
  uni.showModal({
    title: '提示',
    content: '确定删除该地址吗？',
    success: async (res) => {
      if (res.confirm) {
        try {
          await request({ url: `/miniapp/user/addresses/${id}`, method: 'DELETE' })
          await loadAddresses()
          uni.showToast({ title: '已删除', icon: 'success' })
        } catch (error) {
          uni.showToast({ title: error.message || '删除失败', icon: 'none' })
        }
      }
    }
  })
}

async function setDefault(id) {
  if (addresses.value.find(address => address.id === id)?.isDefault) return
  try {
    await request({ url: `/miniapp/user/addresses/${id}/default`, method: 'PUT' })
    await loadAddresses()
    uni.showToast({ title: '已设为默认', icon: 'success' })
  } catch (error) {
    uni.showToast({ title: error.message || '设置失败', icon: 'none' })
  }
}
</script>

<style scoped>
.page {
  height: 100vh;
  min-height: 100vh;
  background: #f0eeea;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* 列表 */
.list-area {
  flex: 1;
  min-height: 0;
  width: 100%;
  padding: 20rpx 28rpx;
  box-sizing: border-box;
  overflow: hidden;
}

.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 120rpx 0;
}

.empty-icon {
  font-size: 80rpx;
}

.empty-text {
  margin-top: 20rpx;
  font-size: 28rpx;
  color: #999;
}

.retry-btn {
  margin-top: 24rpx;
  height: 64rpx;
  line-height: 64rpx;
  padding: 0 28rpx;
  border-radius: 14rpx;
  background: #ffffff;
  color: #b86a4a;
  font-size: 24rpx;
}

/* 地址卡片 */
.address-card {
  width: 100%;
  margin-bottom: 20rpx;
  padding: 24rpx;
  box-sizing: border-box;
  background: #ffffff;
  border-radius: 24rpx;
  border: 1rpx solid rgba(0,0,0,0.04);
  box-shadow: 0 2rpx 16rpx rgba(0,0,0,0.03);
  overflow: hidden;
}

.addr-header {
  display: flex;
  align-items: center;
  gap: 16rpx;
  min-width: 0;
}

.addr-name {
  flex-shrink: 0;
  max-width: 160rpx;
  font-size: 30rpx;
  font-weight: 700;
  color: #1a1a1a;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.addr-phone {
  min-width: 0;
  font-size: 26rpx;
  color: #666;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.default-tag {
  flex-shrink: 0;
  padding: 2rpx 12rpx;
  border-radius: 8rpx;
  background: #fff5f0;
  color: #c97b5a;
  font-size: 20rpx;
  font-weight: 600;
}

.addr-detail {
  display: block;
  margin-top: 12rpx;
  font-size: 26rpx;
  color: #666;
  line-height: 1.5;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.addr-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16rpx;
  min-width: 0;
  margin-top: 20rpx;
  padding-top: 20rpx;
  border-top: 1rpx solid rgba(0,0,0,0.04);
}

.addr-action {
  display: flex;
  align-items: center;
  flex: 1;
  min-width: 0;
  gap: 8rpx;
}

.radio {
  font-size: 28rpx;
  color: #ccc;
}

.radio.checked {
  color: #c97b5a;
}

.radio-label {
  min-width: 0;
  font-size: 24rpx;
  color: #666;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.addr-btns {
  display: flex;
  flex-shrink: 0;
  gap: 20rpx;
}

.addr-btn {
  font-size: 24rpx;
  color: #666;
}

.addr-btn.danger {
  color: #ff4d4f;
}

/* 底部 */
.bottom-bar {
  padding: 20rpx 28rpx;
  padding-bottom: calc(20rpx + env(safe-area-inset-bottom));
  box-sizing: border-box;
  background: #ffffff;
  border-top: 1rpx solid rgba(0,0,0,0.06);
  flex-shrink: 0;
}

.add-btn {
  height: 88rpx;
  line-height: 88rpx;
  margin: 0;
  background: linear-gradient(135deg, #c97b5a, #b86a4a);
  border-radius: 20rpx;
  color: #ffffff;
  font-size: 30rpx;
  font-weight: 700;
  border: none;
  box-shadow: 0 4rpx 16rpx rgba(244,90,11,0.3);
}

.add-btn::after,
.cancel-btn::after,
.save-btn::after {
  border: none;
}

/* 弹窗 */
.modal-mask {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0,0,0,0.5);
  display: flex;
  align-items: flex-end;
  z-index: 999;
}

.modal-content {
  width: 100%;
  padding: 32rpx;
  box-sizing: border-box;
  background: #ffffff;
  border-radius: 24rpx 24rpx 0 0;
}

.modal-title {
  display: block;
  font-size: 32rpx;
  font-weight: 800;
  color: #1a1a1a;
  text-align: center;
}

.divider {
  height: 1rpx;
  margin: 24rpx 0;
  background: linear-gradient(90deg, rgba(0,0,0,0.06), rgba(0,0,0,0.02), rgba(0,0,0,0.06));
}

.form-item {
  margin-bottom: 24rpx;
}

.form-label {
  display: block;
  font-size: 26rpx;
  font-weight: 600;
  color: #1a1a1a;
  margin-bottom: 12rpx;
}

.form-input {
  height: 80rpx;
  padding: 0 24rpx;
  box-sizing: border-box;
  background: #f5f3ef;
  border-radius: 16rpx;
  font-size: 28rpx;
}

.picker-text {
  line-height: 72rpx;
}

.picker-text.placeholder {
  color: #999999;
}

.form-check {
  display: flex;
  align-items: center;
  gap: 8rpx;
  margin-bottom: 32rpx;
}

.form-actions {
  display: flex;
  gap: 20rpx;
}

.cancel-btn {
  flex: 1;
  height: 80rpx;
  line-height: 80rpx;
  margin: 0;
  background: #f5f3ef;
  border-radius: 16rpx;
  color: #666;
  font-size: 28rpx;
  font-weight: 600;
  border: none;
}

.save-btn {
  flex: 2;
  height: 80rpx;
  line-height: 80rpx;
  margin: 0;
  background: linear-gradient(135deg, #c97b5a, #b86a4a);
  border-radius: 16rpx;
  color: #ffffff;
  font-size: 28rpx;
  font-weight: 700;
  border: none;
}

.save-btn[disabled] {
  opacity: 0.65;
}
</style>
