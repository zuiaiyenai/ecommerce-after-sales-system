<script setup>
import { computed, inject, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { approveTicket, completeTicket, getTickets, rejectTicket } from '../api/merchantCs';

const router = useRouter();
const shell = inject('merchantCsShell', null);
const tickets = ref([]);
const activeFilter = ref('ALL');
const actionLoading = ref('');

const filterOptions = [
  { key: 'ALL', label: '全部' },
  { key: 'PENDING_REVIEW', label: '待审核' },
  { key: 'PROCESSING', label: '处理中' },
  { key: 'COMPLETED', label: '已完成' },
  { key: 'REJECTED', label: '已驳回' }
];

const statusMap = {
  PENDING_REVIEW: '待审核',
  PROCESSING: '处理中',
  COMPLETED: '已完成',
  REJECTED: '已驳回'
};

const statusDescMap = {
  PENDING_REVIEW: '等待客服审核售后申请，可通过或驳回。',
  PROCESSING: '已审核通过，正在处理退款/换货/补发等售后操作。',
  COMPLETED: '售后处理已完成，退款已到账或商品已发出。',
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

const visibleTickets = computed(() => {
  if (activeFilter.value === 'ALL') {
    return tickets.value;
  }
  return tickets.value.filter((ticket) => ticket.status === activeFilter.value);
});

function toFiniteNumber(value, fallback = 0) {
  const numericValue = Number(value);
  return Number.isFinite(numericValue) ? numericValue : fallback;
}

const stats = computed(() => [
  {
    label: '待审核',
    value: tickets.value.filter((ticket) => ticket.status === 'PENDING_REVIEW').length,
    tone: 'orange',
    filter: 'PENDING_REVIEW'
  },
  {
    label: '处理中',
    value: tickets.value.filter((ticket) => ticket.status === 'PROCESSING').length,
    tone: 'blue',
    filter: 'PROCESSING'
  },
  {
    label: '已完成',
    value: tickets.value.filter((ticket) => ticket.status === 'COMPLETED').length,
    tone: 'green',
    filter: 'COMPLETED'
  }
]);

async function loadPage() {
  const page = await getTickets();
  tickets.value = page.records;
  if (shell?.tickets && 'value' in shell.tickets) {
    shell.tickets.value = page.records;
  }
  if (shell?.ticketTotal && 'value' in shell.ticketTotal) {
    shell.ticketTotal.value = toFiniteNumber(page.total, page.records.length);
  }
}

async function handleApprove(ticketId) {
  if (actionLoading.value || !isReviewable(tickets.value.find((item) => item.ticketId === ticketId))) {
    return;
  }
  actionLoading.value = `approve:${ticketId}`;
  try {
    const updated = await approveTicket(ticketId);
    tickets.value = tickets.value.map((item) => (item.ticketId === updated.ticketId ? updated : item));
    shell?.setAction('售后申请审核已通过，进入处理中');
    shell?.refreshShell();
  } catch (error) {
    shell?.setAction(error.message || '审核通过失败');
  } finally {
    actionLoading.value = '';
  }
}

async function handleReject(ticketId) {
  if (actionLoading.value || !isReviewable(tickets.value.find((item) => item.ticketId === ticketId))) {
    return;
  }
  actionLoading.value = `reject:${ticketId}`;
  try {
    const updated = await rejectTicket(ticketId);
    tickets.value = tickets.value.map((item) => (item.ticketId === updated.ticketId ? updated : item));
    shell?.setAction('售后申请已驳回');
    shell?.refreshShell();
  } catch (error) {
    shell?.setAction(error.message || '驳回申请失败');
  } finally {
    actionLoading.value = '';
  }
}

async function handleComplete(ticketId) {
  const ticket = tickets.value.find((item) => item.ticketId === ticketId);
  if (actionLoading.value || ticket?.status !== 'PROCESSING') {
    return;
  }
  actionLoading.value = `complete:${ticketId}`;
  try {
    const updated = await completeTicket(ticketId);
    tickets.value = tickets.value.map((item) => (item.ticketId === updated.ticketId ? updated : item));
    shell?.setAction('售后处理已完成');
    shell?.refreshShell();
  } catch (error) {
    shell?.setAction(error.message || '处理完成失败');
  } finally {
    actionLoading.value = '';
  }
}

function isReviewable(ticket) {
  return ticket?.status === 'PENDING_REVIEW';
}

function isCompletable(ticket) {
  return ticket?.status === 'PROCESSING';
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
  if (status === 'COMPLETED') {
    return 'completed';
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
  <section class="work-page ticket-workbench">
    <article class="wide-panel ticket-queue-panel">
      <div class="ticket-queue-head">
        <div>
          <span class="eyebrow">售后审核</span>
          <h2>审核工作台</h2>
          <p>按审核状态、退款金额和优先级快速处理售后申请。</p>
        </div>
        <button type="button" class="primary-action compact" @click="loadPage">刷新列表</button>
      </div>

      <div class="ticket-stat-grid" aria-label="申请统计">
        <button
          v-for="item in stats"
          :key="item.label"
          type="button"
          :class="['ticket-stat-card', item.tone, { active: activeFilter === item.filter }]"
          @click="activeFilter = item.filter"
        >
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
        </button>
      </div>

      <div class="ticket-filter-row" aria-label="申请筛选">
        <button
          v-for="option in filterOptions"
          :key="option.key"
          type="button"
          :class="['filter-chip', { active: activeFilter === option.key }]"
          @click="activeFilter = option.key"
        >
          {{ option.label }}
        </button>
      </div>

      <div class="ticket-status-note">
        <span :class="['ticket-status', statusTone(activeFilter === 'ALL' ? 'PENDING_REVIEW' : activeFilter)]">
          {{ activeFilter === 'ALL' ? '状态说明' : statusLabel(activeFilter) }}
        </span>
        <p>
          {{
            activeFilter === 'ALL'
              ? '待审核表示等待客服判断；处理中表示已进入退款、物流或补发跟进；已完成表示售后已完结。'
              : statusDesc(activeFilter)
          }}
        </p>
      </div>

      <div class="ticket-card-list">
        <div
          v-for="ticket in visibleTickets"
          :key="ticket.ticketId"
          class="ticket-card"
          role="button"
          tabindex="0"
          @click="router.push(`/tickets/${ticket.ticketId}`)"
          @keydown.enter="router.push(`/tickets/${ticket.ticketId}`)"
          @keydown.space.prevent="router.push(`/tickets/${ticket.ticketId}`)"
        >
          <span class="ticket-mark">TK</span>
          <span class="ticket-main-copy">
            <strong>{{ ticket.ticketNo }}</strong>
            <em>{{ ticket.title }}</em>
            <small>{{ typeLabel(ticket.afterSalesType) }} · 申请金额 ￥{{ ticket.applyRefundAmount }}</small>
          </span>
          <span class="ticket-meta">
            <span :class="['ticket-status', statusTone(ticket.status)]">{{ statusLabel(ticket.status) }}</span>
            <span>{{ priorityLabel(ticket.priority) }}</span>
          </span>
          <span v-if="isReviewable(ticket)" class="ticket-actions">
            <button type="button" class="ghost-mini" :disabled="Boolean(actionLoading)" @click.stop="handleApprove(ticket.ticketId)">
              {{ actionLoading === `approve:${ticket.ticketId}` ? '处理中' : '通过' }}
            </button>
            <button type="button" class="ghost-mini danger" :disabled="Boolean(actionLoading)" @click.stop="handleReject(ticket.ticketId)">
              {{ actionLoading === `reject:${ticket.ticketId}` ? '处理中' : '驳回' }}
            </button>
          </span>
          <span v-if="isCompletable(ticket)" class="ticket-actions">
            <button type="button" class="ghost-mini complete" :disabled="Boolean(actionLoading)" @click.stop="handleComplete(ticket.ticketId)">
              {{ actionLoading === `complete:${ticket.ticketId}` ? '处理中' : '处理完成' }}
            </button>
          </span>
        </div>

        <div v-if="visibleTickets.length === 0" class="empty-state ticket-empty">
          <h2>当前筛选下没有售后申请</h2>
          <p>切换筛选条件或刷新列表后再查看。</p>
        </div>
      </div>
    </article>
  </section>
</template>
