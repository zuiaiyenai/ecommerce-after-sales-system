<script setup>
import { computed, inject, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { approveTicket, getTicket, getTicketLogs, rejectTicket } from '../api/merchantCs';

const route = useRoute();
const router = useRouter();
const shell = inject('merchantCsShell', null);
const ticket = ref(null);
const logs = ref([]);

const statusMap = {
  PENDING_REVIEW: '待审核',
  PROCESSING: '处理中',
  APPROVED: '已通过',
  REJECTED: '已驳回'
};

const statusDescMap = {
  PENDING_REVIEW: '等待客服核验凭证，可执行通过或驳回。',
  PROCESSING: '审核已进入售后处理，继续跟进退款、物流或补发。',
  APPROVED: '审核已通过，等待后续售后动作完成。',
  REJECTED: '审核已驳回，本次申请不再进入处理。'
};

const typeMap = {
  REFUND: '退款',
  EXCHANGE: '换货',
  RESEND: '补发'
};

const priorityMap = {
  HIGH: '高优先级',
  NORMAL: '普通优先级'
};

const reviewable = computed(() => ticket.value?.status === 'PENDING_REVIEW');

async function loadPage() {
  ticket.value = await getTicket(route.params.ticketId);
  logs.value = await getTicketLogs(route.params.ticketId);
}

async function handleApprove() {
  if (!reviewable.value) {
    return;
  }
  ticket.value = await approveTicket(route.params.ticketId, '客服前端审核通过');
  shell?.setAction('工单审核已通过');
  shell?.refreshShell();
}

async function handleReject() {
  if (!reviewable.value) {
    return;
  }
  ticket.value = await rejectTicket(route.params.ticketId, '客服前端驳回：资料不足');
  shell?.setAction('工单已驳回');
  shell?.refreshShell();
}

function statusLabel(status) {
  return statusMap[status] || status || '未知状态';
}

function statusDesc(status) {
  return statusDescMap[status] || '当前状态暂无说明。';
}

function typeLabel(type) {
  return typeMap[type] || type || '未分类';
}

function priorityLabel(priority) {
  return priorityMap[priority] || priority || '普通优先级';
}

function statusTone(status) {
  if (status === 'APPROVED') {
    return 'approved';
  }
  if (status === 'REJECTED') {
    return 'rejected';
  }
  if (status === 'PROCESSING') {
    return 'processing';
  }
  return 'pending';
}

onMounted(loadPage);
</script>

<template>
  <section class="detail-page two-column ticket-detail-page">
    <article class="wide-panel ticket-detail-panel">
      <div class="ticket-detail-head">
        <div>
          <span class="eyebrow">工单详情</span>
          <h2>{{ ticket?.ticketNo }} · {{ ticket?.title }}</h2>
        </div>
        <span :class="['ticket-status', statusTone(ticket?.status)]">{{ statusLabel(ticket?.status) }}</span>
        <button type="button" class="ghost-mini" @click="router.push('/tickets')">返回列表</button>
      </div>

      <div class="ticket-detail-grid">
        <div class="status-explain"><span>状态</span><strong>{{ statusLabel(ticket?.status) }}</strong><em>{{ statusDesc(ticket?.status) }}</em></div>
        <div><span>售后类型</span><strong>{{ typeLabel(ticket?.afterSalesType) }}</strong></div>
        <div class="money"><span>申请金额</span><strong>￥{{ ticket?.applyRefundAmount }}</strong></div>
        <div><span>优先级</span><strong>{{ priorityLabel(ticket?.priority) }}</strong></div>
      </div>

      <div class="action-row">
        <button type="button" class="primary-action compact" :disabled="!reviewable" @click="handleApprove">审核通过</button>
        <button type="button" class="ghost-mini danger" :disabled="!reviewable" @click="handleReject">驳回申请</button>
        <button type="button" class="ghost-mini" @click="router.push('/orders')">查看订单</button>
      </div>
    </article>

    <aside class="side-panel ticket-log-panel">
      <span class="eyebrow">处理日志</span>
      <div v-for="log in logs" :key="log.id" class="log-line">
        <strong>{{ log.actionType }}</strong>
        <span>{{ log.actionDesc }}</span>
      </div>
      <div v-if="logs.length === 0" class="log-line">
        <strong>暂无日志</strong>
        <span>审核操作后会同步展示处理记录。</span>
      </div>
    </aside>
  </section>
</template>
