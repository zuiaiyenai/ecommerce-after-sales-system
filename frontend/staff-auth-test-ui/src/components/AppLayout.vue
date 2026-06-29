<script setup>
import { computed, onMounted, provide, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import {
  getCurrentStaff,
  getDashboardTodos,
  getSessions,
  getTickets,
  logout,
  updateWorkStatus
} from '../api/merchantCs';
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

const isOnline = computed(() => staff.value?.onlineStatus === 'ONLINE');
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
    const [profile, todoData, sessionPage, ticketPage] = await Promise.all([
      getCurrentStaff(),
      getDashboardTodos(),
      getSessions(),
      getTickets()
    ]);
    staff.value = profile;
    todos.value = todoData;
    sessions.value = sessionPage.records;
    tickets.value = ticketPage.records;
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

provide('merchantCsShell', {
  staff,
  todos,
  sessions,
  tickets,
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
      @toggle-status="handleToggleStatus"
    />

    <section :class="['page-area', { 'page-area-full': isFullHeightPage }]">
      <TopBar :loading="loading" @refresh="loadShellData" @logout="handleLogout" />
      <div v-if="errorMessage" class="status-banner error">{{ errorMessage }}</div>
      <div v-else-if="actionMessage" class="status-banner success">{{ actionMessage }}</div>
      <RouterView />
    </section>
  </main>
</template>
