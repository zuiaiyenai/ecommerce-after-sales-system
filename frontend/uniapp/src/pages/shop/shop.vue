<template>
  <view class="page">
    <scroll-view class="product-list" scroll-y>
      <view v-if="viewState === 'loading'" class="status-panel">
        <text class="status-title">正在加载商品</text>
        <text class="status-text">请稍候...</text>
      </view>

      <view v-else-if="viewState === 'error'" class="status-panel">
        <text class="status-title">商品加载失败</text>
        <text class="status-text">{{ errorMessage }}</text>
        <button class="retry-btn" @tap="loadProducts">重新加载</button>
      </view>

      <view v-else-if="viewState === 'empty'" class="empty">
        <text class="empty-icon">□</text>
        <text class="empty-text">暂无可购买商品</text>
      </view>

      <view v-else v-for="product in products" :key="product.id" class="product-card">
        <image class="product-image" :src="normalizeImageUrl(product.mainImage)" mode="aspectFill" />
        <view class="product-info">
          <text class="product-name">{{ product.productName }}</text>
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
import { computed, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { normalizeImageUrl, request } from '../../utils/request'
import { normalizeProductList, resolveShopViewState } from '../../utils/shopPageState.mjs'

const products = ref([])
const buyingId = ref(null)
const loading = ref(true)
const errorMessage = ref('')
const viewState = computed(() => resolveShopViewState({
  loading: loading.value,
  errorMessage: errorMessage.value,
  products: products.value
}))

onShow(() => {
  loadProducts()
})

async function loadProducts() {
  loading.value = true
  errorMessage.value = ''
  try {
    const data = await request({ url: '/products' })
    products.value = normalizeProductList(data)
  } catch (e) {
    products.value = []
    errorMessage.value = e.message || '请检查后端服务后重试'
    console.error('商品加载失败', e)
  } finally {
    loading.value = false
  }
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

.product-list {
  height: 100vh;
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
  margin-top: 10rpx;
  font-size: 24rpx;
  line-height: 1.5;
  color: #888;
  overflow: hidden;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
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
  min-width: 128rpx;
  height: 56rpx;
  line-height: 56rpx;
  margin: 0;
  padding: 0 24rpx;
  box-sizing: border-box;
  border-radius: 28rpx;
  background: linear-gradient(135deg, #c97b5a, #b86a4a);
  color: #ffffff;
  font-size: 22rpx;
  font-weight: 700;
  border: none;
  white-space: nowrap;
}

.buy-btn::after {
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

.status-panel {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-top: 48rpx;
  padding: 72rpx 32rpx;
  border-radius: 24rpx;
  background: #ffffff;
}

.status-title {
  font-size: 30rpx;
  font-weight: 700;
  color: #333333;
}

.status-text {
  margin-top: 14rpx;
  font-size: 24rpx;
  color: #999999;
}

.retry-btn {
  height: 64rpx;
  line-height: 64rpx;
  margin-top: 28rpx;
  padding: 0 36rpx;
  border: none;
  border-radius: 32rpx;
  background: #b86a4a;
  color: #ffffff;
  font-size: 24rpx;
}

.retry-btn::after {
  border: none;
}
</style>
