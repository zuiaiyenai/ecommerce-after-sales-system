<template>
  <view class="page">
    <!-- 地址列表 -->
    <scroll-view class="list-area" scroll-y>
      <view v-if="addresses.length === 0" class="empty">
        <text class="empty-icon">📍</text>
        <text class="empty-text">暂无收货地址</text>
      </view>

      <view v-for="addr in addresses" :key="addr.id" class="address-card">
        <view class="addr-header">
          <text class="addr-name">{{ addr.name }}</text>
          <text class="addr-phone">{{ addr.phone }}</text>
          <view v-if="addr.isDefault" class="default-tag">默认</view>
        </view>
        <text class="addr-detail">{{ addr.province }}{{ addr.city }}{{ addr.district }}{{ addr.detail }}</text>
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
      <button class="add-btn" @tap="showForm = true">+ 新增收货地址</button>
    </view>

    <!-- 新增/编辑弹窗 -->
    <view v-if="showForm" class="modal-mask" @tap.self="closeForm">
      <view class="modal-content">
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
          <input v-model="form.region" class="form-input" placeholder="省/市/区" />
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
          <button class="save-btn" @tap="saveAddress">保存</button>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup>
import { ref, reactive } from 'vue'

const addresses = ref([
  { id: 1, name: '张三', phone: '13800138001', province: '北京市', city: '北京市', district: '朝阳区', detail: '三里屯路19号院1号楼', isDefault: true },
  { id: 2, name: '李四', phone: '13900139002', province: '上海市', city: '上海市', district: '浦东新区', detail: '陆家嘴环路1000号', isDefault: false }
])

const showForm = ref(false)
const editingId = ref(null)
const form = reactive({
  name: '',
  phone: '',
  region: '',
  detail: '',
  isDefault: false
})

function closeForm() {
  showForm.value = false
  editingId.value = null
  resetForm()
}

function resetForm() {
  form.name = ''
  form.phone = ''
  form.region = ''
  form.detail = ''
  form.isDefault = false
}

function editAddress(addr) {
  editingId.value = addr.id
  form.name = addr.name
  form.phone = addr.phone
  form.region = addr.province + addr.city + addr.district
  form.detail = addr.detail
  form.isDefault = addr.isDefault
  showForm.value = true
}

function saveAddress() {
  if (!form.name.trim()) {
    uni.showToast({ title: '请输入收货人姓名', icon: 'none' })
    return
  }
  if (!form.phone.trim() || form.phone.length !== 11) {
    uni.showToast({ title: '请输入正确手机号', icon: 'none' })
    return
  }
  if (!form.detail.trim()) {
    uni.showToast({ title: '请输入详细地址', icon: 'none' })
    return
  }

  if (form.isDefault) {
    addresses.value.forEach(a => a.isDefault = false)
  }

  if (editingId.value) {
    const addr = addresses.value.find(a => a.id === editingId.value)
    if (addr) {
      addr.name = form.name
      addr.phone = form.phone
      addr.detail = form.detail
      addr.isDefault = form.isDefault
    }
  } else {
    addresses.value.push({
      id: Date.now(),
      name: form.name,
      phone: form.phone,
      province: '',
      city: '',
      district: '',
      detail: form.detail,
      isDefault: form.isDefault
    })
  }

  uni.showToast({ title: '保存成功', icon: 'success' })
  closeForm()
}

function deleteAddress(id) {
  uni.showModal({
    title: '提示',
    content: '确定删除该地址吗？',
    success: (res) => {
      if (res.confirm) {
        addresses.value = addresses.value.filter(a => a.id !== id)
        uni.showToast({ title: '已删除', icon: 'success' })
      }
    }
  })
}

function setDefault(id) {
  addresses.value.forEach(a => a.isDefault = a.id === id)
  uni.showToast({ title: '已设为默认', icon: 'success' })
}
</script>

<style scoped>
.page {
  width: 100%;
  min-height: 100vh;
  background: #f0eeea;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

/* 列表 */
.list-area {
  width: 100%;
  flex: 1;
  padding: 20rpx 28rpx;
  box-sizing: border-box;
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

/* 地址卡片 */
.address-card {
  width: 100%;
  margin-bottom: 20rpx;
  padding: 24rpx;
  background: #ffffff;
  border-radius: 24rpx;
  border: 1rpx solid rgba(0,0,0,0.04);
  box-shadow: 0 2rpx 16rpx rgba(0,0,0,0.03);
  box-sizing: border-box;
}

.addr-header {
  display: flex;
  align-items: center;
  gap: 16rpx;
}

.addr-name {
  font-size: 30rpx;
  font-weight: 700;
  color: #1a1a1a;
}

.addr-phone {
  font-size: 26rpx;
  color: #666;
}

.default-tag {
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
}

.addr-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 20rpx;
  padding-top: 20rpx;
  border-top: 1rpx solid rgba(0,0,0,0.04);
}

.addr-action {
  display: flex;
  align-items: center;
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
  font-size: 24rpx;
  color: #666;
}

.addr-btns {
  display: flex;
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
  width: 100%;
  padding: 20rpx 28rpx;
  padding-bottom: calc(20rpx + env(safe-area-inset-bottom));
  background: #ffffff;
  border-top: 1rpx solid rgba(0,0,0,0.06);
  box-sizing: border-box;
}

.add-btn {
  width: 100%;
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
  background: #ffffff;
  border-radius: 24rpx 24rpx 0 0;
  box-sizing: border-box;
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
  background: #f5f3ef;
  border-radius: 16rpx;
  font-size: 28rpx;
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
  background: linear-gradient(135deg, #c97b5a, #b86a4a);
  border-radius: 16rpx;
  color: #ffffff;
  font-size: 28rpx;
  font-weight: 700;
  border: none;
}
</style>
