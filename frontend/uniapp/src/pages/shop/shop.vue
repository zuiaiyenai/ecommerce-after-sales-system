<template>
  <view class="page">
    <view class="nav-bar">
      <view class="back-btn" @tap="goBack">
        <text class="back-icon">←</text>
      </view>
      <text class="nav-title">演示购买</text>
      <view class="nav-right"></view>
    </view>

    <scroll-view class="product-list" scroll-y>
      <view v-if="products.length === 0" class="empty">
        <text class="empty-icon">□</text>
        <text class="empty-text">暂无可购买商品</text>
      </view>

      <view v-for="product in products" :key="product.id" class="product-card">
        <image class="product-image" :src="normalizeImageUrl(product.mainImage)" mode="aspectFill" />
        <view class="product-info">
          <text class="product-name">{{ product.productName }}</text>
          <text class="merchant-line">商家：{{ product.merchantDisplayName || product.merchantCode || '演示商家' }}</text>
          <text class="product-desc">{{ product.description || product.category }}</text>
          <view class="product-bottom">
            <text class="product-price">¥{{ product.price }}</text>
            <button class="buy-btn" :disabled="buyingId === product.id" @tap="buy(product)">
              {{ buyingId === product.id ? '生成中' : '一键购买' }}
            </button>
          </view>
        </view>
      </view>
    </scroll-view>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { request, normalizeImageUrl } from '../../utils/request'

const products = ref([])
const buyingId = ref(null)

onLoad(() => {
  loadProducts()
})

async function loadProducts() {
  try {
    products.value = await request({ url: '/products' }) || []
  } catch (e) {
    uni.showToast({ title: '商品加载失败', icon: 'none' })
  }
}

function goBack() {
  uni.navigateBack()
}

async function buy(product) {
  buyingId.value = product.id
  try {
    await request({
      url: '/orders',
      method: 'POST',
      data: {
        productId: product.id,
        quantity: 1,
        receiverName: '演示用户',
        receiverPhone: '13800138000',
        receiverAddress: '北京市朝阳区演示小区 8 号楼'
      }
    })
    uni.showToast({ title: '购买成功', icon: 'success' })
    setTimeout(() => {
      uni.navigateTo({ url: '/pages/orders/list' })
    }, 800)
  } catch (e) {
    uni.showToast({ title: e.message || '购买失败', icon: 'none' })
  } finally {
    buyingId.value = null
  }
}
</script>

<style scoped>
.page {
  min-height: 100vh;
  background: #f0eeea;
}

.nav-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 32rpx 28rpx;
  background: #ffffff;
}

.back-btn {
  width: 64rpx;
  height: 64rpx;
  line-height: 64rpx;
  text-align: center;
  border-radius: 16rpx;
  background: #f5f3ef;
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

.product-list {
  height: calc(100vh - 128rpx);
  padding: 24rpx 28rpx;
  box-sizing: border-box;
}

.product-card {
  display: flex;
  gap: 20rpx;
  margin-bottom: 20rpx;
  padding: 24rpx;
  background: #ffffff;
  border-radius: 24rpx;
  border: 1rpx solid rgba(0,0,0,0.04);
}

.product-image {
  width: 150rpx;
  height: 150rpx;
  flex-shrink: 0;
  border-radius: 18rpx;
  background: #f5f3ef;
}

.product-info {
  flex: 1;
  min-width: 0;
}

.product-name {
  display: block;
  font-size: 30rpx;
  font-weight: 800;
  color: #1a1a1a;
}

.product-desc {
  display: -webkit-box;
  margin-top: 8rpx;
  font-size: 24rpx;
  line-height: 1.5;
  color: #888;
  overflow: hidden;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.merchant-line {
  display: block;
  margin-top: 8rpx;
  font-size: 22rpx;
  color: #8a776c;
}

.product-bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 18rpx;
}

.product-price {
  font-size: 32rpx;
  font-weight: 900;
  color: #b86a4a;
}

.buy-btn {
  height: 56rpx;
  line-height: 56rpx;
  padding: 0 24rpx;
  border-radius: 28rpx;
  background: linear-gradient(135deg, #c97b5a, #b86a4a);
  color: #ffffff;
  font-size: 22rpx;
  font-weight: 700;
  border: none;
}

.buy-btn[disabled] {
  opacity: 0.55;
}

.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 120rpx 0;
}

.empty-icon {
  font-size: 80rpx;
  color: #aaa;
}

.empty-text {
  margin-top: 20rpx;
  font-size: 28rpx;
  color: #999;
}
</style>
