<script setup>
import { computed, onMounted, provide, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import {
  getCurrentStaff,
  getDashboardTodos,
  getSessions,
  getTickets,
  logout,
  updateWorkStatus
} from '../api/merchantCs';
import { noticeRules } from '../data/staticData';
import SidebarNav from './SidebarNav.vue';
import TopBar from './TopBar.vue';

const router = useRouter();
const route = useRoute();
const loading = ref(false);
const errorMessage = ref('');
const actionMessage = ref('');
const staff = ref(null);
const todos = ref([]);
const sessions = ref([]);
const tickets = ref([]);
const pendingTicketCount = ref(0);
const THEME_KEY = 'merchant_cs_theme';
const savedTheme = localStorage.getItem(THEME_KEY);
const themeMode = ref(
  savedTheme || (window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
);
let themeAnimationTimer = 0;

const isOnline = computed(() => staff.value?.onlineStatus === 'ONLINE');
const isDarkTheme = computed(() => themeMode.value === 'dark');
const noticeCount = computed(() => noticeRules.length + todos.value.length);
const fullHeightRoutes = ['dashboard', 'tickets', 'sessions', 'orders', 'notices'];
const isFullHeightPage = computed(() => fullHeightRoutes.includes(route.name));

function setAction(message) {
  actionMessage.value = message;
  window.setTimeout(() => {
    if (actionMessage.value === message) {
      actionMessage.value = '';
    }
  }, 2200);
}

async function loadShellData() {
  loading.value = true;
  errorMessage.value = '';
  try {
    const [profile, todoData, sessionPage, ticketPage, pendingTicketPage] = await Promise.all([
      getCurrentStaff(),
      getDashboardTodos(),
      getSessions(),
      getTickets(),
      getTickets({ status: 'PENDING_REVIEW', size: 1 })
    ]);
    staff.value = profile;
    todos.value = todoData;
    sessions.value = sessionPage.records;
    tickets.value = ticketPage.records;
    pendingTicketCount.value = pendingTicketPage.total ?? pendingTicketPage.records?.length ?? 0;
  } catch (error) {
    errorMessage.value = error.message || '基础数据加载失败';
  } finally {
    loading.value = false;
  }
}

async function handleToggleStatus() {
  if (!staff.value) {
    errorMessage.value = '请先登录客服账号';
    return;
  }
  const nextStatus = isOnline.value ? 'OFFLINE' : 'ONLINE';
  staff.value = await updateWorkStatus(nextStatus);
  setAction(`当前状态已切换为 ${nextStatus}`);
}

async function handleLogout() {
  if (route.name === 'sessionDetail') {
    router.push('/sessions');
    return;
  }
  await logout();
  setAction('已退出登录');
  router.push('/login');
}

function toggleTheme() {
  themeMode.value = isDarkTheme.value ? 'light' : 'dark';
}

watch(
  themeMode,
  (mode) => {
    const root = document.documentElement;
    window.clearTimeout(themeAnimationTimer);
    root.classList.add('theme-changing');
    root.dataset.theme = mode;
    localStorage.setItem(THEME_KEY, mode);
    themeAnimationTimer = window.setTimeout(() => {
      root.classList.remove('theme-changing');
    }, 520);
  },
  { immediate: true }
);

provide('merchantCsShell', {
  staff,
  todos,
  sessions,
  tickets,
  themeMode,
  toggleTheme,
  setAction,
  refreshShell: loadShellData
});

onMounted(loadShellData);
</script>

<template>
  <main class="app-shell">
    <SidebarNav
      :staff="staff"
      :sessions="sessions"
      :tickets="tickets"
      :todos="todos"
      :ticket-count="pendingTicketCount"
      :notice-count="noticeCount"
      @toggle-status="handleToggleStatus"
    />

    <section :class="['page-area', { 'page-area-full': isFullHeightPage }]">
      <TopBar
        :loading="loading"
        :theme-mode="themeMode"
        @refresh="loadShellData"
        @logout="handleLogout"
        @toggle-theme="toggleTheme"
      />
      <div v-if="errorMessage" class="status-banner error">{{ errorMessage }}</div>
      <div v-else-if="actionMessage" class="status-banner success">{{ actionMessage }}</div>
      <RouterView />
    </section>
  </main>
</template>
