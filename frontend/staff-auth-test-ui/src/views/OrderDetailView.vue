<script setup>
import { computed } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import EmptyState from '../components/EmptyState.vue';
import { orderRecords } from '../data/staticData';

const route = useRoute();
const router = useRouter();
const order = computed(() => orderRecords.find((item) => item.id === route.params.orderId));
</script>

<template>
  <section class="work-page">
    <article v-if="order" class="wide-panel">
      <div class="panel-head">
        <div>
          <span class="eyebrow">订单详情</span>
          <h2>{{ order.id }}</h2>
        </div>
        <button type="button" class="ghost-mini" @click="router.push('/orders')">返回订单列表</button>
      </div>

      <div class="info-grid">
        <div><span>用户</span><strong>{{ order.user }}</strong></div>
        <div><span>手机号</span><strong>{{ order.phone }}</strong></div>
        <div><span>商品</span><strong>{{ order.product }}</strong></div>
        <div><span>金额</span><strong>{{ order.amount }}</strong></div>
        <div><span>订单状态</span><strong>{{ order.status }}</strong></div>
        <div><span>物流/售后</span><strong>{{ order.logistics }}</strong></div>
      </div>

      <div class="action-row">
        <button
          type="button"
          class="primary-action compact"
          :disabled="!order.relatedTicketId"
          @click="router.push(`/tickets/${order.relatedTicketId}`)"
        >
          查看关联工单
        </button>
        <button type="button" class="ghost-mini" @click="router.push('/sessions')">发起客服会话</button>
      </div>
    </article>

    <EmptyState
      v-else
      title="未找到订单"
      desc="当前订单仍是前端 mock 数据，后续会接入订单检索接口。"
      action="返回订单列表"
      @action="router.push('/orders')"
    />
  </section>
</template>
