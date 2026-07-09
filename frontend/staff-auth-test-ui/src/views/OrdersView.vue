<script setup>
import { computed, inject, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { getOrders, shipOrder } from '../api/merchantCs';

const router = useRouter();
const shell = inject('merchantCsShell', null);
const keyword = ref('');
const activeStatus = ref('ALL');
const orders = ref([]);
const loading = ref(false);
const error = ref('');
const errorTitle = ref('订单加载失败');

const statusOptions = [
  { key: 'ALL', label: '全部订单' },
  { key: 'PAID', label: '未发货' },
  { key: 'SHIPPED', label: '配送中' },
  { key: 'RECEIVED', label: '已收货' },
  { key: 'AFTERSALE', label: '售后中' }
];

const statusLabels = {
  PAID: '未发货',
  SHIPPED: '配送中',
  RECEIVED: '已收货',
  AFTERSALE: '售后中'
};

const stats = computed(() => [
  { label: '未发货', value: orders.value.filter((item) => item.status === 'PAID').length, tone: 'orange', filter: 'PAID' },
  { label: '配送中', value: orders.value.filter((item) => item.status === 'SHIPPED').length, tone: 'blue', filter: 'SHIPPED' },
  { label: '售后中', value: orders.value.filter((item) => item.status === 'AFTERSALE').length, tone: 'green', filter: 'AFTERSALE' }
]);

const filteredOrders = computed(() => {
  const text = keyword.value.trim().toLowerCase();
  return orders.value.filter((item) => {
    const matchesStatus = activeStatus.value === 'ALL' || item.status === activeStatus.value;
    const matchesKeyword =
      !text || [item.orderNo, item.user, item.phone, item.product].some((value) => String(value || '').toLowerCase().includes(text));
    return matchesStatus && matchesKeyword;
  });
});

async function loadOrders() {
  loading.value = true;
  error.value = '';
  errorTitle.value = '订单加载失败';
  try {
    const result = await getOrders({ page: 1, size: 200 });
    orders.value = result?.records || [];
  } catch (err) {
    error.value = err.message || '订单加载失败';
    orders.value = [];
  } finally {
    loading.value = false;
  }
}

async function clearSearch() {
  keyword.value = '';
  activeStatus.value = 'ALL';
  await loadOrders();
}

function statusLabel(status) {
  return statusLabels[status] || status || '--';
}

function statusTone(status) {
  if (status === 'PAID') return 'processing';
  if (status === 'SHIPPED') return 'paid';
  return 'done';
}

async function handleShip(orderId) {
  loading.value = true;
  error.value = '';
  errorTitle.value = '发货失败';
  try {
    await shipOrder(orderId);
    await loadOrders();
    shell?.refreshShell();
  } catch (err) {
    error.value = err.message || '发货失败';
  } finally {
    loading.value = false;
  }
}

function openOrder(orderId) {
  router.push(`/orders/${orderId}`);
}

function openTicket(ticketId) {
  router.push(`/tickets/${ticketId}`);
}

onMounted(loadOrders);
</script>

<template>
  <section class="work-page order-workbench">
    <article class="wide-panel order-query-panel">
      <div class="order-query-head">
        <div>
          <span class="eyebrow">订单管理</span>
          <h2>订单发货工作台</h2>
          <p>用户购买后生成未发货订单，商家在这里执行发货，用户端再查看配送地图和物流状态。</p>
        </div>
        <button type="button" class="ghost-mini" :disabled="loading" @click="clearSearch">重置查询</button>
      </div>

      <div class="order-search-row">
        <label class="order-search-box">
          <span>搜索订单</span>
          <input v-model.trim="keyword" placeholder="订单号 / 用户 / 手机号 / 商品" />
        </label>
        <span class="order-result-count">{{ loading ? '加载中' : `匹配 ${filteredOrders.length} 条` }}</span>
      </div>

      <div class="order-stat-grid" aria-label="订单统计">
        <button
          v-for="item in stats"
          :key="item.label"
          type="button"
          :class="['order-stat-card', item.tone, { active: activeStatus === item.filter }]"
          @click="activeStatus = item.filter"
        >
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
        </button>
      </div>

      <div class="order-filter-row" aria-label="订单状态筛选">
        <button
          v-for="option in statusOptions"
          :key="option.key"
          type="button"
          :class="['filter-chip', { active: activeStatus === option.key }]"
          @click="activeStatus = option.key"
        >
          {{ option.label }}
        </button>
      </div>

      <div class="order-card-list">
        <div v-if="error" class="empty-state order-empty">
          <h2>{{ errorTitle }}</h2>
          <p>{{ error }}</p>
          <button type="button" class="ghost-mini" @click="loadOrders">重新加载</button>
        </div>

        <div
          v-for="order in filteredOrders"
          v-else
          :key="order.id"
          class="order-card"
          role="button"
          tabindex="0"
          @click="openOrder(order.id)"
          @keydown.enter="openOrder(order.id)"
          @keydown.space.prevent="openOrder(order.id)"
        >
          <span class="ticket-mark order">OR</span>
          <span class="order-main-copy">
            <strong>{{ order.orderNo }}</strong>
            <em>{{ order.user }} · {{ order.phone }}</em>
            <small>{{ order.product }}</small>
          </span>
          <span class="order-amount">¥{{ order.amount }}</span>
          <span class="order-progress">
            <span :class="['order-status', statusTone(order.status)]">{{ statusLabel(order.status) }}</span>
            <em>{{ order.logistics }}</em>
          </span>
          <span class="order-actions">
            <button v-if="order.status === 'PAID'" type="button" class="ghost-mini" :disabled="loading" @click.stop="handleShip(order.id)">发货</button>
            <button
              v-if="order.relatedTicketId"
              type="button"
              class="ghost-mini"
              @click.stop="openTicket(order.relatedTicketId)"
            >
              关联申请
            </button>
          </span>
        </div>

        <div v-if="!loading && !error && filteredOrders.length === 0" class="empty-state order-empty">
          <h2>没有匹配的订单</h2>
          <p>换一个关键词，或清空状态筛选后再查询。</p>
          <button type="button" class="ghost-mini" @click="clearSearch">清空条件</button>
        </div>
      </div>
    </article>
  </section>
</template>
