<script setup>
import { computed, inject, onMounted, ref } from 'vue';
import {
  getDashboardOverview,
  getDashboardPerformance,
  getDashboardTodos,
  getSessions,
  getTickets
} from '../api/merchantCs';
import ServicePerformanceCard from '../components/ServicePerformanceCard.vue';

const shell = inject('merchantCsShell', null);
const loading = ref(true);
const overview = ref(null);
const todos = ref([]);
const performance = ref({ metrics: [] });
const sessions = ref([]);
const tickets = ref([]);

const activeSessions = computed(() => sessions.value.filter((item) => !['RESOLVED', 'CLOSED'].includes(item.status)));
const pendingTickets = computed(() => tickets.value.filter((item) => item.status === 'PENDING_REVIEW'));
const pendingWorkTotal = computed(() => activeSessions.value.length + pendingTickets.value.length);
const pendingWorkLink = computed(() => (activeSessions.value.length > 0 ? '/sessions' : '/tickets'));
const pendingWorkTitle = computed(() => (
  `${activeSessions.value.length} 个活跃会话，${pendingTickets.value.length} 个待审核申请`
));

function toFiniteNumber(value, fallback = 0) {
  const numericValue = Number(value);
  return Number.isFinite(numericValue) ? numericValue : fallback;
}

function syncShellSnapshot(todoData, sessionPage, ticketPage) {
  if (!shell) {
    return;
  }
  if (shell.todos) {
    shell.todos.value = todoData || [];
  }
  if (shell.sessions) {
    shell.sessions.value = sessionPage?.records || [];
  }
  if (shell.tickets) {
    shell.tickets.value = ticketPage?.records || [];
  }
  if (shell.ticketTotal) {
    shell.ticketTotal.value = toFiniteNumber(ticketPage?.total, shell.tickets?.value?.length ?? 0);
  }
}

async function loadPage() {
  loading.value = true;
  try {
    const [overviewData, todoData, performanceData, sessionPage, ticketPage] = await Promise.all([
      getDashboardOverview(),
      getDashboardTodos(),
      getDashboardPerformance(),
      getSessions(),
      getTickets()
    ]);
    overview.value = overviewData;
    todos.value = todoData;
    performance.value = performanceData;
    sessions.value = sessionPage.records;
    tickets.value = ticketPage.records;
    syncShellSnapshot(todoData, sessionPage, ticketPage);
  } finally {
    loading.value = false;
  }
}

onMounted(loadPage);
</script>

<template>
  <section class="home-page dashboard-simple" :aria-busy="loading">
    <article class="hero-panel">
      <div class="hero-copy">
        <span class="eyebrow">商家客服端主页</span>
        <h2>{{ overview?.greeting || '商家客服工作台' }}</h2>
        <div class="hero-status-row">
          <span class="status-chip online">当前在线</span>
          <span>{{ activeSessions.length }} 个活跃会话</span>
          <span>{{ pendingTickets.length }} 个待审核申请</span>
        </div>
      </div>
      <RouterLink class="hero-number" :to="pendingWorkLink" :title="pendingWorkTitle" :aria-label="pendingWorkTitle">
        <span>待处理汇总</span>
        <strong>{{ pendingWorkTotal }}</strong>
        <em>{{ activeSessions.length }} 会话 + {{ pendingTickets.length }} 申请</em>
      </RouterLink>
    </article>

    <section class="dashboard-workbench">
      <article class="panel-card queue-panel">
        <div class="panel-head compact">
          <div>
            <span class="eyebrow">Work Queue</span>
            <h2>待办事项</h2>
          </div>
        </div>
        <div class="todo-list">
          <RouterLink
            v-for="item in todos"
            :key="item.id"
            class="todo-line"
            :to="item.target || '/notices'"
          >
            <span class="todo-dot" aria-hidden="true"></span>
            <span :class="['priority-tag', item.priorityTone || 'normal']">{{ item.priority || '普通' }}</span>
            <span class="todo-main">
              <strong>{{ item.title }}</strong>
              <em>{{ item.tag }} · {{ item.amount }}</em>
            </span>
            <span class="todo-arrow" aria-hidden="true">›</span>
          </RouterLink>
        </div>
      </article>

      <article class="panel-card performance-panel">
        <div class="panel-head compact">
          <div class="performance-head-copy">
            <span class="eyebrow">Service</span>
            <h2>服务表现</h2>
            <span class="performance-legend">
              <i class="current"></i> 当前
              <i class="target"></i> 目标
            </span>
          </div>
        </div>
        <ServicePerformanceCard :performance="performance" />
      </article>
    </section>
  </section>
</template>
