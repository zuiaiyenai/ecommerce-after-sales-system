<script setup>
import { computed, ref } from 'vue';
import { useRouter } from 'vue-router';
import { orderRecords } from '../data/staticData';

const router = useRouter();
const keyword = ref('');
const activeStatus = ref('ALL');

const processingLogistics = ['退款审核中', '物流节点异常'];

const statusOptions = [
  { key: 'ALL', label: '全部订单' },
  { key: 'PAID', label: '已支付' },
  { key: 'PROCESSING', label: '处理中' }
];

function verificationStatus(order) {
  return order.relatedTicketId || processingLogistics.includes(order.logistics) ? 'PROCESSING' : 'PAID';
}

function statusLabel(order) {
  return verificationStatus(order) === 'PROCESSING' ? '处理中' : '已支付';
}

const stats = computed(() => [
  { label: '全部订单', value: orderRecords.length, tone: 'blue', filter: 'ALL' },
  {
    label: '售后处理中',
    value: orderRecords.filter((item) => verificationStatus(item) === 'PROCESSING').length,
    tone: 'orange',
    filter: 'PROCESSING'
  },
  {
    label: '已支付',
    value: orderRecords.filter((item) => verificationStatus(item) === 'PAID').length,
    tone: 'green',
    filter: 'PAID'
  }
]);

const filteredOrders = computed(() => {
  const text = keyword.value.trim().toLowerCase();
  return orderRecords.filter((item) => {
    const matchesStatus = activeStatus.value === 'ALL' || verificationStatus(item) === activeStatus.value;
    const matchesKeyword =
      !text || [item.id, item.user, item.phone, item.product].some((value) => value.toLowerCase().includes(text));
    return matchesStatus && matchesKeyword;
  });
});

function clearSearch() {
  keyword.value = '';
  activeStatus.value = 'ALL';
}

function statusTone(status) {
  return status === 'PROCESSING' ? 'processing' : 'paid';
}
</script>

<template>
  <section class="work-page order-workbench">
    <article class="wide-panel order-query-panel">
      <div class="order-query-head">
        <div>
          <span class="eyebrow">订单核验</span>
          <h2>订单查询工作台</h2>
          <p>按订单号、用户、手机号或商品快速定位订单，并核对售后进度与关联工单。</p>
        </div>
        <button type="button" class="ghost-mini" @click="clearSearch">重置查询</button>
      </div>

      <div class="order-search-row">
        <label class="order-search-box">
          <span>搜索订单</span>
          <input v-model.trim="keyword" placeholder="订单号 / 用户 / 手机号 / 商品" />
        </label>
        <span class="order-result-count">匹配 {{ filteredOrders.length }} 条</span>
      </div>

      <div class="order-stat-grid" aria-label="订单统计">
        <button
          v-for="item in stats"
          :key="item.label"
          type="button"
          :class="['order-stat-card', item.tone]"
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
        <div v-for="order in filteredOrders" :key="order.id" class="order-card">
          <button type="button" class="ticket-mark order" @click="router.push(`/orders/${order.id}`)">OR</button>
          <button type="button" class="order-main-copy" @click="router.push(`/orders/${order.id}`)">
            <strong>{{ order.id }}</strong>
            <em>{{ order.user }} · {{ order.phone }}</em>
            <small>{{ order.product }}</small>
          </button>
          <span class="order-amount">{{ order.amount }}</span>
          <span class="order-progress">
            <span :class="['order-status', statusTone(verificationStatus(order))]">{{ statusLabel(order) }}</span>
            <em>{{ order.logistics }}</em>
          </span>
          <button
            v-if="order.relatedTicketId"
            type="button"
            class="ghost-mini"
            @click="router.push(`/tickets/${order.relatedTicketId}`)"
          >
            关联工单
          </button>
        </div>

        <div v-if="filteredOrders.length === 0" class="empty-state order-empty">
          <h2>没有匹配的订单</h2>
          <p>换一个关键词，或清空状态筛选后再查询。</p>
          <button type="button" class="ghost-mini" @click="clearSearch">清空条件</button>
        </div>
      </div>
    </article>
  </section>
</template>
