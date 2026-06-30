<template>
  <view class="page">
    <!-- 顶部导航 -->
    <view class="nav-bar">
      <view class="back-btn" @tap="goBack">
        <text class="back-icon">←</text>
      </view>
      <text class="nav-title">{{ pageTitle }}</text>
      <view class="nav-right"></view>
    </view>

    <!-- 商品信息 -->
    <view class="card">
      <text class="card-title">商品信息</text>
      <view class="divider"></view>
      <view class="product-row">
        <image class="product-img" :src="normalizeImageUrl(orderInfo.productImage)" mode="aspectFill" />
        <view class="product-info">
          <text class="product-name">{{ orderInfo.productName }}</text>
          <text class="product-spec">{{ orderInfo.spec }}</text>
          <view class="price-row">
            <text class="product-price">¥{{ orderInfo.price }}</text>
            <text class="product-count">x{{ orderInfo.count }}</text>
          </view>
        </view>
      </view>
      <view class="divider"></view>
      <view class="info-row">
        <text class="info-label">订单编号</text>
        <view class="info-value-row">
          <text class="info-value">{{ orderInfo.orderNo }}</text>
          <text class="copy-btn" @tap="copyOrderNo">复制</text>
        </view>
      </view>
      <view class="info-row">
        <text class="info-label">下单时间</text>
        <text class="info-value">{{ orderInfo.orderTime }}</text>
      </view>
      <view class="info-row">
        <text class="info-label">实付款</text>
        <text class="info-value price">¥{{ orderInfo.totalPrice }}</text>
      </view>
    </view>

    <!-- 物流模拟（正常订单，无售后） -->
    <view class="card" v-if="!hasAfterSale">
      <view class="map-title-row">
        <text class="card-title">物流模拟</text>
        <text class="map-status">{{ logisticsMap.statusText }}</text>
      </view>
      <view class="divider"></view>
      <map
        class="logistics-map"
        :latitude="logisticsMap.latitude"
        :longitude="logisticsMap.longitude"
        :scale="logisticsMap.scale"
        :markers="logisticsMap.markers"
        :polyline="logisticsMap.polyline"
      />
      <view class="map-info-row">
        <text>{{ logisticsMap.fromText }}</text>
        <text>{{ logisticsMap.toText }}</text>
      </view>
      <view class="divider"></view>
      <view v-if="orderInfo.trackingCompany" class="info-row">
        <text class="info-label">快递公司</text>
        <text class="info-value">{{ orderInfo.trackingCompany }}</text>
      </view>
      <view v-if="orderInfo.trackingNo" class="info-row">
        <text class="info-label">运单号</text>
        <view class="info-value-row">
          <text class="info-value">{{ orderInfo.trackingNo }}</text>
          <text class="copy-btn" @tap="copyTracking">复制</text>
        </view>
      </view>
      <view class="divider" v-if="orderInfo.trackingCompany"></view>
      <view class="timeline">
        <view v-for="(step, index) in logisticsSteps" :key="index" class="step-item" :class="{ active: step.active, done: step.done }">
          <view class="step-dot">
            <text v-if="step.done" class="step-check">✓</text>
            <text v-else-if="step.active" class="step-active-dot"></text>
          </view>
          <view class="step-line" v-if="index < logisticsSteps.length - 1"></view>
          <view class="step-content">
            <text class="step-title">{{ step.title }}</text>
            <text class="step-desc">{{ step.desc }}</text>
            <text class="step-time" v-if="step.time">{{ step.time }}</text>
          </view>
        </view>
      </view>
    </view>

    <!-- 售后进度（有售后时显示） -->
    <view class="card" v-if="hasAfterSale">
      <text class="card-title">售后进度</text>
      <view class="divider"></view>
      <view class="timeline">
        <view v-for="(step, index) in afterSaleSteps" :key="index" class="step-item" :class="{ active: step.active, done: step.done }">
          <view class="step-dot">
            <text v-if="step.done" class="step-check">✓</text>
            <text v-else-if="step.active" class="step-active-dot"></text>
          </view>
          <view class="step-line" v-if="index < afterSaleSteps.length - 1"></view>
          <view class="step-content">
            <text class="step-title">{{ step.title }}</text>
            <text class="step-desc">{{ step.desc }}</text>
            <text class="step-time" v-if="step.time">{{ step.time }}</text>
          </view>
        </view>
      </view>
    </view>

    <!-- 问题信息（有售后时显示） -->
    <view class="card" v-if="hasAfterSale">
      <text class="card-title">问题信息</text>
      <view class="divider"></view>
      <view class="info-row">
        <text class="info-label">问题类型</text>
        <text class="info-value">{{ afterSaleInfo.reasonText }}</text>
      </view>
      <view class="info-row">
        <text class="info-label">问题描述</text>
        <text class="info-value">{{ afterSaleInfo.description }}</text>
      </view>
      <view v-if="afterSaleInfo.images && afterSaleInfo.images.length > 0" class="info-row images-row">
        <text class="info-label">凭证图片</text>
        <view class="images-grid">
          <image v-for="(img, index) in afterSaleInfo.images" :key="index" class="evidence-img" :src="normalizeImageUrl(img)" mode="aspectFill" @tap="previewImage(index)" />
        </view>
      </view>
    </view>

    <!-- 底部按钮 -->
    <view class="bottom-bar">
      <button v-if="hasAfterSale" class="btn-primary" @tap="contactService">联系售后客服</button>
      <button v-else-if="orderInfo.status !== 'PAID'" class="btn-primary" @tap="applyAfterSale">申请售后</button>
      <button v-else class="btn-primary disabled" disabled>未发货暂不可申请售后</button>
    </view>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { request, normalizeImageUrl } from '../../utils/request'

const pageTitle = ref('订单详情')
const hasAfterSale = ref(false)

const orderInfo = ref({
  id: '',
  productImage: '',
  productName: '',
  spec: '',
  price: '0.00',
  count: 1,
  orderNo: '',
  orderTime: '',
  totalPrice: '0.00',
  status: '',
  statusText: '',
  trackingCompany: '',
  trackingNo: '',
  payTime: '',
  shipTime: '',
  receiveTime: '',
  receiverAddress: ''
})

const afterSaleInfo = ref({
  id: '',
  ticketNo: '',
  orderId: '',
  reasonText: '',
  description: '',
  status: '',
  statusText: '',
  auditOpinion: '',
  auditTime: '',
  completeTime: '',
  createTime: '',
  refundAmount: null,
  images: []
})

const logisticsSteps = ref([])
const afterSaleSteps = ref([])
const logisticsMap = ref({
  latitude: 39.935,
  longitude: 116.395,
  scale: 10,
  statusText: '商家备货中',
  fromText: '商品发货地：商家仓库',
  toText: '收货地址：演示地址',
  markers: [],
  polyline: []
})

const reasonMap = {
  'QUALITY': '质量问题',
  'WRONG_ITEM': '发错货',
  'SIZE_ISSUE': '尺码不合适',
  'DAMAGE': '物流损坏',
  'NOT_MATCH': '与描述不符',
  'OTHER': '其他原因'
}

onLoad(async (options) => {
  if (options.ticketNo) {
    // 从售后列表进入
    await loadFromAfterSale(options.ticketNo)
  } else if (options.orderId) {
    // 从订单列表进入
    await loadFromOrder(options.orderId)
  } else if (options.id) {
    // 兼容旧入口：历史版本首页传的是 id，实际含义是订单ID
    await loadFromOrder(options.id)
  }
})

// 从订单进入
async function loadFromOrder(orderId) {
  try {
    const order = await request({ url: '/orders/' + orderId })
    if (!order) return
    fillOrderInfo(order)

    // 查找该订单的售后工单
    let ticket = null
    try {
      const allTickets = await request({ url: '/aftersales' })
      if (allTickets) {
        // 用字符串比较，避免JS大数精度丢失
        ticket = allTickets.find(t => String(t.orderId) === String(orderId))
      }
    } catch (e) {}

    if (ticket) {
      // 有售后
      hasAfterSale.value = true
      pageTitle.value = '售后详情'
      fillAfterSaleInfo(ticket)
    } else {
      // 无售后，显示物流
      hasAfterSale.value = false
      pageTitle.value = '订单详情'
      buildLogisticsSteps(order)
      buildLogisticsMap(order)
    }
  } catch (e) {
    console.error('加载订单详情失败', e)
  }
}

// 从售后列表进入
async function loadFromAfterSale(ticketNo) {
  try {
    const ticket = await request({ url: '/aftersales/byTicketNo/' + ticketNo })
    if (!ticket) return

    hasAfterSale.value = true
    pageTitle.value = '售后详情'
    fillAfterSaleInfo(ticket)

    // 加载关联订单信息
    if (ticket.orderId) {
      try {
        const order = await request({ url: '/orders/' + ticket.orderId })
        if (order) fillOrderInfo(order)
      } catch (e) {}
    }
  } catch (e) {
    console.error('加载售后详情失败', e)
  }
}

function fillOrderInfo(order) {
  const item = order.items && order.items[0]
  orderInfo.value = {
    id: order.id || '',
    productImage: (item && item.productImage) || '',
    productName: (item && item.productName) || '',
    spec: (item && item.productSpec) || '',
    price: (item && item.price) || '0.00',
    count: item ? item.quantity : 1,
    orderNo: order.orderNo || '',
    orderTime: order.createTime || '',
    totalPrice: order.payAmount || '0.00',
    status: order.status || '',
    statusText: order.statusText || '',
    trackingCompany: order.trackingCompany || '',
    trackingNo: order.trackingNo || '',
    payTime: order.payTime || '',
    shipTime: order.shipTime || '',
    receiveTime: order.receiveTime || '',
    receiverAddress: order.receiverAddress || ''
  }
}

function fillAfterSaleInfo(ticket) {
  afterSaleInfo.value = {
    id: ticket.id || '',
    ticketNo: ticket.ticketNo || '',
    orderId: ticket.orderId || '',
    reasonText: reasonMap[ticket.reason] || ticket.reason || '',
    description: ticket.description || '',
    status: ticket.status || '',
    statusText: ticket.statusText || '',
    auditOpinion: ticket.auditOpinion || '',
    auditTime: ticket.auditTime || '',
    completeTime: ticket.completeTime || '',
    createTime: ticket.createTime || '',
    refundAmount: ticket.refundAmount,
    images: ticket.attachmentUrls || []
  }
  buildAfterSaleSteps(ticket)
}

function buildLogisticsSteps(order) {
  const payTime = order.payTime ? order.payTime.slice(5, 16) : ''
  const shipTime = order.shipTime ? order.shipTime.slice(5, 16) : ''
  const receiveTime = order.receiveTime ? order.receiveTime.slice(5, 16) : ''
  const trackingInfo = order.trackingCompany ? (order.trackingCompany + ' ' + order.trackingNo) : ''

  if (order.status === 'PAID') {
    logisticsSteps.value = [
      { title: '已付款', desc: '等待卖家发货', time: payTime, done: true, active: false },
      { title: '待发货', desc: '卖家准备商品中', time: '', done: false, active: true },
      { title: '已发货', desc: '等待物流配送', time: '', done: false, active: false },
      { title: '待签收', desc: '等待确认收货', time: '', done: false, active: false }
    ]
  } else if (order.status === 'SHIPPED') {
    logisticsSteps.value = [
      { title: '已付款', desc: '订单已付款', time: payTime, done: true, active: false },
      { title: '已发货', desc: trackingInfo, time: shipTime, done: true, active: false },
      { title: '运输中', desc: '包裹正在配送', time: '', done: false, active: true },
      { title: '待签收', desc: '等待确认收货', time: '', done: false, active: false }
    ]
  } else if (order.status === 'RECEIVED') {
    logisticsSteps.value = [
      { title: '已付款', desc: '订单已付款', time: payTime, done: true, active: false },
      { title: '已发货', desc: trackingInfo, time: shipTime, done: true, active: false },
      { title: '已签收', desc: '包裹已签收', time: receiveTime, done: true, active: false },
      { title: '已完成', desc: '交易完成', time: receiveTime, done: true, active: false }
    ]
  } else {
    logisticsSteps.value = [
      { title: '已付款', desc: '订单已付款', time: payTime, done: true, active: false },
      { title: '待发货', desc: '等待卖家发货', time: '', done: false, active: true },
      { title: '已发货', desc: '等待物流配送', time: '', done: false, active: false },
      { title: '待签收', desc: '等待确认收货', time: '', done: false, active: false }
    ]
  }
}

function buildLogisticsMap(order) {
  const item = order.items && order.items[0]
  const seedText = `${order.orderNo || ''}${item ? item.productName : ''}`
  const seed = Array.from(seedText).reduce((sum, char) => sum + char.charCodeAt(0), 0)
  const offset = (seed % 12) / 1000
  const warehouse = {
    latitude: 39.982 + offset,
    longitude: 116.305 + offset,
    title: '商品发货地'
  }
  const receiver = {
    latitude: 39.905 - offset,
    longitude: 116.455 - offset,
    title: '收货地址'
  }
  const status = order.status || 'PAID'
  const progress = status === 'PAID' ? 0 : status === 'SHIPPED' ? 0.58 : 1
  const courier = {
    latitude: warehouse.latitude + (receiver.latitude - warehouse.latitude) * progress,
    longitude: warehouse.longitude + (receiver.longitude - warehouse.longitude) * progress,
    title: status === 'RECEIVED' ? '已签收' : '配送车辆'
  }
  const markers = [
    { id: 1, latitude: warehouse.latitude, longitude: warehouse.longitude, title: '商品发货地', width: 28, height: 28 },
    { id: 2, latitude: receiver.latitude, longitude: receiver.longitude, title: '收货地址', width: 28, height: 28 }
  ]
  if (status !== 'PAID') {
    markers.push({ id: 3, latitude: courier.latitude, longitude: courier.longitude, title: courier.title, width: 30, height: 30 })
  }
  const statusMap = {
    PAID: '商家备货中',
    SHIPPED: '配送中',
    RECEIVED: '已签收',
    AFTERSALE: '售后处理中'
  }
  logisticsMap.value = {
    latitude: courier.latitude,
    longitude: courier.longitude,
    scale: 11,
    statusText: statusMap[status] || order.statusText || '物流模拟',
    fromText: `商品发货地：${item ? item.productName : '商家仓库'}`,
    toText: `收货地址：${order.receiverAddress || '演示收货地址'}`,
    markers,
    polyline: [{
      points: status === 'PAID' ? [warehouse, receiver] : [warehouse, courier, receiver],
      color: '#c97b5a',
      width: 5,
      dottedLine: status === 'PAID'
    }]
  }
}

function buildAfterSaleSteps(ticket) {
  const createTime = ticket.createTime ? ticket.createTime.slice(5, 16) : ''
  const auditTime = ticket.auditTime ? ticket.auditTime.slice(5, 16) : ''
  const completeTime = ticket.completeTime ? ticket.completeTime.slice(5, 16) : ''

  const statusSteps = {
    PROCESSING: [
      { title: '已提交', desc: '售后申请已提交', time: createTime, done: true, active: false },
      { title: '审核中', desc: ticket.auditOpinion || '预计1-3个工作日审核', time: '', done: false, active: true },
      { title: '处理中', desc: '等待处理结果', time: '', done: false, active: false },
      { title: '已完成', desc: '售后已完结', time: '', done: false, active: false }
    ],
    APPROVED: [
      { title: '已提交', desc: '售后申请已提交', time: createTime, done: true, active: false },
      { title: '审核通过', desc: ticket.auditOpinion || '已通过审核', time: auditTime, done: true, active: false },
      { title: '处理中', desc: '退款/换货处理中', time: '', done: false, active: true },
      { title: '已完成', desc: '售后已完结', time: '', done: false, active: false }
    ],
    REJECTED: [
      { title: '已提交', desc: '售后申请已提交', time: createTime, done: true, active: false },
      { title: '已拒绝', desc: ticket.auditOpinion || '审核未通过', time: auditTime, done: true, active: false },
      { title: '已关闭', desc: '售后已关闭', time: '', done: true, active: false }
    ],
    COMPLETED: [
      { title: '已提交', desc: '售后申请已提交', time: createTime, done: true, active: false },
      { title: '审核通过', desc: ticket.auditOpinion || '已通过审核', time: auditTime, done: true, active: false },
      { title: '已处理', desc: '退款/换货已完成', time: '', done: true, active: false },
      { title: '已完成', desc: ticket.refundAmount ? '退款¥' + ticket.refundAmount + '已到账' : '售后已完结', time: completeTime, done: true, active: false }
    ]
  }
  afterSaleSteps.value = statusSteps[ticket.status] || statusSteps.PROCESSING
}

function goBack() {
  uni.navigateBack()
}

function copyOrderNo() {
  uni.setClipboardData({
    data: orderInfo.value.orderNo,
    success: () => uni.showToast({ title: '已复制', icon: 'success' })
  })
}

function copyTracking() {
  uni.setClipboardData({
    data: orderInfo.value.trackingNo,
    success: () => uni.showToast({ title: '已复制', icon: 'success' })
  })
}

function previewImage(index) {
  uni.previewImage({ current: index, urls: afterSaleInfo.value.images.map(normalizeImageUrl) })
}

function contactService() {
  const info = orderInfo.value
  const afterSaleId = afterSaleInfo.value.id
  const orderId = afterSaleInfo.value.orderId || info.id
  const params = [
    afterSaleId ? 'afterSaleId=' + encodeURIComponent(afterSaleId) : '',
    orderId ? 'orderId=' + encodeURIComponent(orderId) : '',
    'productName=' + encodeURIComponent(info.productName || ''),
    'productIcon=' + encodeURIComponent(info.productImage || ''),
    'statusText=' + encodeURIComponent(afterSaleInfo.value.statusText || '售后处理中')
  ].filter(Boolean).join('&')
  uni.navigateTo({
    url: `/pages/chat/consult?${params}`
  })
}

function applyAfterSale() {
  uni.navigateTo({ url: '/pages/after-sale/apply?orderId=' + orderInfo.value.id })
}
</script>

<style scoped>
.page {
  min-height: 100vh;
  padding: 24rpx 28rpx 160rpx;
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

.back-icon { font-size: 32rpx; color: #1a1a1a; }
.nav-title { font-size: 32rpx; font-weight: 800; color: #1a1a1a; }
.nav-right { width: 64rpx; }

.card {
  margin-top: 24rpx;
  padding: 28rpx;
  background: #ffffff;
  border-radius: 24rpx;
  border: 1rpx solid rgba(0,0,0,0.04);
  box-shadow: 0 2rpx 16rpx rgba(0,0,0,0.03);
}

.card-title { display: block; font-size: 28rpx; font-weight: 700; color: #1a1a1a; }

.map-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.map-status {
  padding: 6rpx 14rpx;
  border-radius: 999rpx;
  background: #fff5ef;
  color: #b86a4a;
  font-size: 22rpx;
  font-weight: 700;
}

.logistics-map {
  width: 100%;
  height: 360rpx;
  border-radius: 18rpx;
  overflow: hidden;
}

.map-info-row {
  display: flex;
  justify-content: space-between;
  gap: 20rpx;
  margin-top: 16rpx;
}

.map-info-row text {
  flex: 1;
  min-width: 0;
  font-size: 22rpx;
  color: #666;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.divider {
  height: 1rpx;
  margin: 20rpx 0;
  background: linear-gradient(90deg, rgba(0,0,0,0.06), rgba(0,0,0,0.02), rgba(0,0,0,0.06));
}

.product-row { display: flex; gap: 20rpx; }

.product-img {
  width: 140rpx;
  height: 140rpx;
  border-radius: 16rpx;
  background: #f5f3ef;
}

.product-info { flex: 1; display: flex; flex-direction: column; justify-content: space-between; }
.product-name { font-size: 28rpx; font-weight: 700; color: #1a1a1a; }
.product-spec { font-size: 24rpx; color: #999; }
.price-row { display: flex; align-items: center; justify-content: space-between; }
.product-price { font-size: 30rpx; font-weight: 800; color: #1a1a1a; }
.product-count { font-size: 24rpx; color: #999; }

.info-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12rpx 0;
}

.info-label { font-size: 26rpx; color: #999; }
.info-value { font-size: 26rpx; color: #1a1a1a; }
.info-value.price { color: #c97b5a; font-weight: 700; }

.info-value-row { display: flex; align-items: center; gap: 12rpx; }

.copy-btn {
  padding: 4rpx 12rpx;
  border: 1rpx solid rgba(0,0,0,0.1);
  border-radius: 8rpx;
  font-size: 20rpx;
  color: #999;
}

.timeline { display: flex; justify-content: space-between; padding: 20rpx 0; }

.step-item {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  position: relative;
}

.step-dot {
  width: 48rpx;
  height: 48rpx;
  line-height: 48rpx;
  text-align: center;
  border-radius: 50%;
  background: #e0e0e0;
  margin-bottom: 12rpx;
}

.step-item.done .step-dot { background: #c97b5a; }

.step-item.active .step-dot {
  background: #c97b5a;
  box-shadow: 0 0 0 8rpx rgba(201,123,90,0.2);
}

.step-check { color: #ffffff; font-size: 24rpx; font-weight: 700; }

.step-active-dot {
  display: block;
  width: 16rpx;
  height: 16rpx;
  border-radius: 50%;
  background: #ffffff;
  margin: 16rpx auto;
}

.step-line {
  position: absolute;
  top: 24rpx;
  left: 60%;
  right: -40%;
  height: 4rpx;
  background: #e0e0e0;
}

.step-item.done .step-line { background: #c97b5a; }

.step-content { text-align: center; }
.step-title { display: block; font-size: 22rpx; font-weight: 600; color: #1a1a1a; }
.step-item.active .step-title { color: #c97b5a; }
.step-desc { display: block; margin-top: 4rpx; font-size: 18rpx; color: #999; max-width: 140rpx; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.step-time { display: block; margin-top: 4rpx; font-size: 16rpx; color: #bbb; }

.images-row { flex-direction: column; align-items: flex-start; gap: 16rpx; }
.images-grid { display: flex; gap: 12rpx; }
.evidence-img { width: 120rpx; height: 120rpx; border-radius: 12rpx; border: 1rpx solid rgba(0,0,0,0.04); }

.bottom-bar {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  gap: 20rpx;
  padding: 24rpx 28rpx;
  padding-bottom: calc(24rpx + env(safe-area-inset-bottom));
  background: #ffffff;
  border-top: 1rpx solid rgba(0,0,0,0.06);
}

.btn-primary {
  flex: 1;
  height: 88rpx;
  line-height: 88rpx;
  border-radius: 20rpx;
  background: linear-gradient(135deg, #c97b5a, #b86a4a);
  color: #ffffff;
  font-size: 28rpx;
  font-weight: 600;
  border: none;
  box-shadow: 0 4rpx 16rpx rgba(201,123,90,0.3);
}

.btn-primary.disabled {
  background: #d6d1ca;
  box-shadow: none;
  color: #ffffff;
}
</style>
