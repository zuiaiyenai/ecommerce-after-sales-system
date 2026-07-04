<script setup>
import { computed, inject, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { closeSession, getSessions } from '../api/merchantCs';

const router = useRouter();
const shell = inject('merchantCsShell', null);
const loading = ref(true);
const sessions = ref([]);
const activeFilter = ref('ACTIVE');

const terminalStatuses = ['RESOLVED'];
const filterOptions = [
  { key: 'ACTIVE', label: '活跃会话' },
  { key: 'WAITING', label: '待接入' },
  { key: 'PROCESSING', label: '处理中' },
  { key: 'AWAITING_EVALUATION', label: '待评价' },
  { key: 'READY_TO_CLOSE', label: '待客服关闭' },
  { key: 'COMPLETED', label: '已完成' }
];

const visibleSessions = computed(() => {
  return sessions.value.filter((item) => item.status !== 'CLOSED').filter((item) => {
    if (activeFilter.value === 'ACTIVE') {
      return !terminalStatuses.includes(item.status);
    }
    if (activeFilter.value === 'COMPLETED') {
      return terminalStatuses.includes(item.status);
    }
    return item.status === activeFilter.value;
  });
});

const stats = computed(() => {
  const active = sessions.value.filter((item) => item.status !== 'CLOSED' && !terminalStatuses.includes(item.status)).length;
  const awaitingEvaluation = sessions.value.filter((item) => item.status === 'AWAITING_EVALUATION').length;
  const readyToClose = sessions.value.filter((item) => item.status === 'READY_TO_CLOSE').length;
  return [
    { label: '活跃会话', value: active, tone: 'blue', filter: 'ACTIVE' },
    { label: '待评价', value: awaitingEvaluation, tone: 'orange', filter: 'AWAITING_EVALUATION' },
    { label: '待客服关闭', value: readyToClose, tone: 'green', filter: 'READY_TO_CLOSE' }
  ];
});

async function loadPage() {
  loading.value = true;
  try {
    const page = await getSessions();
    sessions.value = page.records || [];
  } finally {
    loading.value = false;
  }
}

async function handleClose(sessionId) {
  try {
    const updated = await closeSession(sessionId);
    sessions.value = sessions.value.map((item) => (item.id === updated.id ? { ...item, ...updated } : item));
    shell?.setAction('会话已移除');
    shell?.refreshShell();
  } catch (error) {
    shell?.setAction(error.message || '移除失败');
  }
}

function canClose(item) {
  return item.status !== 'CLOSED';
}

function statusLabel(status) {
  const labels = {
    WAITING: '待接入',
    PROCESSING: '处理中',
    AWAITING_EVALUATION: '待用户评价',
    READY_TO_CLOSE: '待客服关闭',
    RESOLVED: '已完成',
    CLOSED: '已完成'
  };
  return labels[status] || '进行中';
}

function statusTone(status) {
  if (status === 'CLOSED' || status === 'RESOLVED') {
    return 'closed';
  }
  if (status === 'WAITING' || status === 'AWAITING_EVALUATION') {
    return 'waiting';
  }
  if (status === 'READY_TO_CLOSE') {
    return 'ready';
  }
  return 'processing';
}

function fieldValue(value, fallback = '暂无') {
  return value || fallback;
}

onMounted(loadPage);
</script>

<template>
  <section class="work-page session-workbench session-list-template">
    <article class="wide-panel session-queue-panel">
      <div class="session-queue-head">
        <div>
          <span class="eyebrow">会话队列</span>
          <h2>在线咨询处理</h2>
          <p>用户完成评价或客服关闭后，会话统一进入已完成。</p>
        </div>
        <button type="button" class="primary-action compact" :disabled="loading" @click="loadPage">
          {{ loading ? '同步中' : '同步会话' }}
        </button>
      </div>

      <div class="session-stat-grid" aria-label="会话统计">
        <button
          v-for="item in stats"
          :key="item.label"
          type="button"
          :class="['session-stat-card', item.tone]"
          @click="activeFilter = item.filter"
        >
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
        </button>
      </div>

      <div class="session-filter-row" aria-label="会话筛选">
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

      <div class="session-card-list">
        <div
          v-for="item in visibleSessions"
          :key="item.id"
          class="session-card"
          role="button"
          tabindex="0"
          @click="router.push(`/sessions/${item.id}`)"
          @keydown.enter="router.push(`/sessions/${item.id}`)"
        >
          <span class="session-avatar">{{ fieldValue(item.user, '访客').slice(0, 1) }}</span>
          <span class="session-main-copy">
            <strong>{{ fieldValue(item.user, '未知用户') }}</strong>
            <em>{{ fieldValue(item.sessionNo, `#${item.id}`) }} · {{ fieldValue(item.topic, '售后咨询') }}</em>
            <small>{{ fieldValue(item.lastMessageContent, '等待客服接入并核对上下文') }}</small>
          </span>
          <span class="session-meta">
            <span :class="['session-status', statusTone(item.status)]">{{ statusLabel(item.status) }}</span>
            <span>{{ fieldValue(item.wait, item.waitText || '等待中') }}</span>
          </span>
          <span class="session-meta compact">
            <span class="tag">{{ fieldValue(item.level, '普通优先级') }}</span>
            <span v-if="item.rating">评分 {{ item.rating }} 星</span>
            <span v-else>{{ fieldValue(item.evaluationStatus, item.emotion || '情绪稳定') }}</span>
            <span v-if="item.evaluationContent">{{ item.evaluationContent }}</span>
          </span>
          <span class="session-actions">
            <button
              type="button"
              class="ghost-mini danger"
              :disabled="!canClose(item)"
              :title="canClose(item) ? '从当前列表移除' : '已移除'"
              @click.stop="handleClose(item.id)"
            >
              ×
            </button>
          </span>
        </div>

        <div v-if="!loading && visibleSessions.length === 0" class="empty-state session-empty">
          <h2>当前筛选下没有会话</h2>
          <p>切换筛选条件或同步会话后再查看。</p>
        </div>
      </div>
    </article>
  </section>
</template>
