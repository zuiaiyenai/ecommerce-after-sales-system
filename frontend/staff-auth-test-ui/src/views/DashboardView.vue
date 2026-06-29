<script setup>
import { computed, inject, onMounted, ref } from 'vue';
import {
  getDashboardOverview,
  getDashboardPerformance,
  getDashboardTodos,
  getSessions,
  getTickets
} from '../api/merchantCs';

const shell = inject('merchantCsShell', null);
const loading = ref(true);
const overview = ref(null);
const todos = ref([]);
const performance = ref({ metrics: [] });
const sessions = ref([]);
const tickets = ref([]);

const activeSessions = computed(() => sessions.value.filter((item) => !['RESOLVED', 'CLOSED'].includes(item.status)));
const pendingTickets = computed(() => tickets.value.filter((item) => item.status === 'PENDING_REVIEW'));
const performanceBars = computed(() => performance.value?.metrics ?? []);

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
          <span>{{ pendingTickets.length }} 个待审核工单</span>
        </div>
      </div>
      <div class="hero-number">
        <span>待处理汇总</span>
        <strong>{{ overview?.todayTodoCount ?? '--' }}</strong>
      </div>
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
        <div class="performance-chart">
          <div v-for="item in performanceBars" :key="item.label" class="performance-bar-row">
            <span class="performance-label">{{ item.label }}</span>
            <div class="performance-bar-track" aria-hidden="true">
              <i
                class="performance-bar-target"
                :style="{ left: `${Math.min(item.targetPercent ?? 0, 100)}%` }"
              ></i>
              <i
                class="performance-bar-current"
                :style="{ width: `${Math.min(item.currentPercent ?? 0, 100)}%` }"
              ></i>
            </div>
            <strong>{{ item.value }}</strong>
            <em>{{ item.desc }}</em>
          </div>
        </div>
      </article>
    </section>
  </section>
</template>
