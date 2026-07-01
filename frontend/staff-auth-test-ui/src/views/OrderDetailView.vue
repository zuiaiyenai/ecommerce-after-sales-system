<script setup>
import { computed, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import EmptyState from '../components/EmptyState.vue';
import { getOrder, shipOrder } from '../api/merchantCs';

const route = useRoute();
const router = useRouter();
const order = ref(null);
const loading = ref(false);
const error = ref('');
const productSummary = computed(() => order.value?.productItems?.map((item) => `${item.productName} x${item.quantity}`).join('、') || '--');

async function loadOrder() {
  loading.value = true;
  error.value = '';
  try {
    order.value = await getOrder(route.params.orderId);
  } catch (err) {
    error.value = err.message || '订单加载失败';
    order.value = null;
  } finally {
    loading.value = false;
  }
}

async function handleShip() {
  if (!order.value) return;
  loading.value = true;
  error.value = '';
  try {
    order.value = await shipOrder(order.value.id);
  } catch (err) {
    error.value = err.message || '发货失败';
  } finally {
    loading.value = false;
  }
}

onMounted(loadOrder);
</script>

<template>
  <section class="work-page">
    <article v-if="order" class="wide-panel">
      <div class="panel-head">
        <div>
          <span class="eyebrow">订单详情</span>
          <h2>{{ order.orderNo }}</h2>
        </div>
        <button type="button" class="ghost-mini" @click="router.push('/orders')">返回订单列表</button>
      </div>

      <div class="info-grid">
        <div><span>用户</span><strong>{{ order.user }}</strong></div>
        <div><span>手机号</span><strong>{{ order.phone }}</strong></div>
        <div><span>商品</span><strong>{{ productSummary }}</strong></div>
        <div><span>金额</span><strong>¥{{ order.payAmount }}</strong></div>
        <div><span>订单状态</span><strong>{{ order.status }}</strong></div>
        <div><span>物流/售后</span><strong>{{ order.logistics?.status || '--' }}</strong></div>
        <div><span>快递公司</span><strong>{{ order.logistics?.company || '--' }}</strong></div>
        <div><span>运单号</span><strong>{{ order.logistics?.trackingNo || '--' }}</strong></div>
      </div>

      <div class="action-row">
        <button
          v-if="order.status === 'PAID'"
          type="button"
          class="primary-action compact"
          :disabled="loading"
          @click="handleShip"
        >
          商家发货
        </button>
        <button
          type="button"
          class="primary-action compact"
          :disabled="!order.relatedTicketId"
          @click="router.push(`/tickets/${order.relatedTicketId}`)"
        >
          查看关联申请
        </button>
        <button type="button" class="ghost-mini" @click="router.push('/sessions')">发起客服会话</button>
      </div>
    </article>

    <EmptyState
      v-else
      :title="loading ? '订单加载中' : '未找到订单'"
      :desc="error || '请返回订单列表重新选择订单。'"
      :action="error ? '重新加载' : '返回订单列表'"
      @action="error ? loadOrder() : router.push('/orders')"
    />
  </section>
</template>
