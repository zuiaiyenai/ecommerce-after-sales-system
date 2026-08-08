<script setup>
import { computed, inject, onBeforeUnmount, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { closeSession, getSessions } from '../api/merchantCs';

const router = useRouter();
const shell = inject('merchantCsShell', null);
const loading = ref(true);
const sessions = ref([]);
const activeFilter = ref('ACTIVE');
let refreshTimer = 0;
const SESSION_PAGE_SIZE = 100;

const terminalStatuses = ['RESOLVED'];
const hiddenFromActiveQueueStatuses = ['RESOLVED', 'CLOSED', 'READY_TO_CLOSE', 'AWAITING_EVALUATION'];
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
      return isActiveQueueSession(item);
    }
    if (activeFilter.value === 'COMPLETED') {
      return terminalStatuses.includes(item.status);
    }
    return item.status === activeFilter.value;
  });
});

const stats = computed(() => {
  const active = sessions.value.filter(isActiveQueueSession).length;
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
    const page = await getSessions({ size: SESSION_PAGE_SIZE });
    sessions.value = page.records || [];
  } finally {
    loading.value = false;
  }
}

async function refreshSessionsSilently() {
  try {
    const page = await getSessions({ size: SESSION_PAGE_SIZE });
    sessions.value = page.records || [];
    if (shell?.sessions) {
      shell.sessions.value = sessions.value;
    }
  } catch (error) {
    // Keep the current list during transient refresh failures.
  }
}

function isActiveQueueSession(item) {
  return !hiddenFromActiveQueueStatuses.includes(item?.status)
    && (Number(item?.serviceUnreadCount || 0) > 0 || !item?.serviceId);
}

function startRefreshPolling() {
  window.clearInterval(refreshTimer);
  refreshTimer = window.setInterval(() => {
    if (!document.hidden) {
      refreshSessionsSilently();
    }
  }, 5000);
}

async function handleClose(sessionId) {
  try {
    const updated = await closeSession(sessionId);
    sessions.value = sessions.value.map((item) => (item.sessionId === updated.sessionId ? { ...item, ...updated } : item));
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

function replyStatusText(item) {
  return item?.replyStatus === 'UNREPLIED' ? '未回复' : '已回复';
}

function emotionScoreText(item) {
  const raw = item?.emotionScore;
  if (raw == null || raw === '') return '0';
  const score = Number(raw);
  if (!Number.isFinite(score)) return String(raw);
  return String(score <= 1 ? Math.round(score * 100) : Math.round(score));
}

function trendText(trend) {
  return ({ UP: '持续升高', DOWN: '有所缓和', FLAT: '基本平稳' })[trend] || '基本平稳';
}

function riskText(level) {
  return ({ HIGH: '高', MEDIUM: '中', LOW: '低' })[level] || '低';
}

onMounted(() => {
  loadPage();
  startRefreshPolling();
});

onBeforeUnmount(() => {
  window.clearInterval(refreshTimer);
});
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
          :class="['session-stat-card', item.tone, { active: activeFilter === item.filter }]"
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
          :key="item.sessionId"
          class="session-card"
          role="button"
          tabindex="0"
          @click="router.push(`/sessions/${item.sessionId}`)"
          @keydown.enter="router.push(`/sessions/${item.sessionId}`)"
        >
          <span class="session-avatar">{{ fieldValue(item.user, '访客').slice(0, 1) }}</span>
          <span class="session-main-copy">
            <strong>{{ fieldValue(item.user, '未知用户') }}</strong>
            <em>{{ fieldValue(item.sessionNo, `#${item.sessionId}`) }} · {{ fieldValue(item.topic, '售后咨询') }}</em>
            <small>{{ fieldValue(item.lastMessageContent, '等待客服接入并核对上下文') }}</small>
          </span>
          <span class="session-meta">
            <span :class="['session-status', statusTone(item.status)]">{{ statusLabel(item.status) }}</span>
            <span>{{ replyStatusText(item) }}</span>
          </span>
          <span class="session-meta compact">
            <span class="tag">情绪指数 {{ emotionScoreText(item) }}</span>
            <span>趋势 {{ trendText(item.emotionTrend) }}</span>
            <span>风险 {{ riskText(item.riskLevel) }}</span>
            <span v-if="item.evaluationContent">{{ item.evaluationContent }}</span>
          </span>
          <span class="session-actions">
            <button
              type="button"
              class="ghost-mini danger"
              :disabled="!canClose(item)"
              :title="canClose(item) ? '从当前列表移除' : '已移除'"
              @click.stop="handleClose(item.sessionId)"
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
