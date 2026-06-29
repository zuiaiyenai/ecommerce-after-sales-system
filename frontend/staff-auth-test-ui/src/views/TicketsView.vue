<script setup>
import { computed, inject, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { approveTicket, getTickets, rejectTicket } from '../api/merchantCs';

const router = useRouter();
const shell = inject('merchantCsShell', null);
const tickets = ref([]);
const activeFilter = ref('ALL');

const filterOptions = [
  { key: 'ALL', label: '全部' },
  { key: 'PENDING_REVIEW', label: '待审核' },
  { key: 'PROCESSING', label: '处理中' },
  { key: 'APPROVED', label: '已通过' },
  { key: 'REJECTED', label: '已驳回' }
];

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

const visibleTickets = computed(() => {
  if (activeFilter.value === 'ALL') {
    return tickets.value;
  }
  return tickets.value.filter((ticket) => ticket.status === activeFilter.value);
});

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
    label: '高优先级',
    value: tickets.value.filter((ticket) => ticket.priority === 'HIGH').length,
    tone: 'green',
    filter: 'ALL'
  }
]);

async function loadPage() {
  const page = await getTickets();
  tickets.value = page.records;
}

async function handleApprove(ticketId) {
  if (!isReviewable(tickets.value.find((item) => item.id === ticketId))) {
    return;
  }
  const updated = await approveTicket(ticketId);
  tickets.value = tickets.value.map((item) => (item.id === updated.id ? updated : item));
  shell?.setAction('工单审核已通过');
  shell?.refreshShell();
}

async function handleReject(ticketId) {
  if (!isReviewable(tickets.value.find((item) => item.id === ticketId))) {
    return;
  }
  const updated = await rejectTicket(ticketId);
  tickets.value = tickets.value.map((item) => (item.id === updated.id ? updated : item));
  shell?.setAction('工单已驳回');
  shell?.refreshShell();
}

function isReviewable(ticket) {
  return ticket?.status === 'PENDING_REVIEW';
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
  <section class="work-page ticket-workbench">
    <article class="wide-panel ticket-queue-panel">
      <div class="ticket-queue-head">
        <div>
          <span class="eyebrow">售后审核</span>
          <h2>工单审核工作台</h2>
          <p>按审核状态、退款金额和优先级快速处理售后申请。</p>
        </div>
        <button type="button" class="primary-action compact" @click="loadPage">刷新工单</button>
      </div>

      <div class="ticket-stat-grid" aria-label="工单统计">
        <button
          v-for="item in stats"
          :key="item.label"
          type="button"
          :class="['ticket-stat-card', item.tone]"
          @click="activeFilter = item.filter"
        >
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
        </button>
      </div>

      <div class="ticket-filter-row" aria-label="工单筛选">
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
              ? '待审核表示等待客服判断；处理中表示已进入退款、物流或补发跟进。'
              : statusDesc(activeFilter)
          }}
        </p>
      </div>

      <div class="ticket-card-list">
        <div
          v-for="ticket in visibleTickets"
          :key="ticket.id"
          class="ticket-card"
          role="button"
          tabindex="0"
          @click="router.push(`/tickets/${ticket.id}`)"
          @keydown.enter="router.push(`/tickets/${ticket.id}`)"
          @keydown.space.prevent="router.push(`/tickets/${ticket.id}`)"
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
            <button type="button" class="ghost-mini" @click.stop="handleApprove(ticket.id)">通过</button>
            <button type="button" class="ghost-mini danger" @click.stop="handleReject(ticket.id)">驳回</button>
          </span>
        </div>

        <div v-if="visibleTickets.length === 0" class="empty-state ticket-empty">
          <h2>当前筛选下没有工单</h2>
          <p>切换筛选条件或刷新工单后再查看。</p>
        </div>
      </div>
    </article>
  </section>
</template>
