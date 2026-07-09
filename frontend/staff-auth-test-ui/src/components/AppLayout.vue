<script setup>
import { computed, onBeforeUnmount, onMounted, provide, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import {
  getCurrentStaff,
  getDashboardTodos,
  getOrders,
  getSessions,
  getTickets,
  logout,
  updateWorkStatus
} from '../api/merchantCs';
import SidebarNav from './SidebarNav.vue';
import TopBar from './TopBar.vue';
import WelcomeAnimation from './WelcomeAnimation.vue';

const router = useRouter();
const route = useRoute();
const loading = ref(false);
const errorMessage = ref('');
const actionMessage = ref('');
const staff = ref(null);
const todos = ref([]);
const sessions = ref([]);
const tickets = ref([]);
const ticketTotal = ref(0);
const pendingShipmentCount = ref(0);
const showLogoutAnimation = ref(false);
const THEME_KEY = 'merchant_cs_theme';
const LOGOUT_DURATION_MS = 3000;
const savedTheme = localStorage.getItem(THEME_KEY);
const themeMode = ref(
  savedTheme || (window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
);
let themeAnimationTimer = 0;
let logoutFinished = false;
let logoutEnterTimer = 0;
let routeTransitionTimer = 0;

const isOnline = computed(() => staff.value?.onlineStatus === 'ONLINE');
const isDarkTheme = computed(() => themeMode.value === 'dark');
const fullHeightRoutes = ['dashboard', 'tickets', 'sessions', 'orders', 'reviews', 'notices'];
const isFullHeightPage = computed(() => fullHeightRoutes.includes(route.name));
const showLogout = computed(() => true);

function toFiniteNumber(value, fallback = 0) {
  const numericValue = Number(value);
  return Number.isFinite(numericValue) ? numericValue : fallback;
}

const safeTicketTotal = computed(() => toFiniteNumber(ticketTotal.value));
const safePendingShipmentCount = computed(() => toFiniteNumber(pendingShipmentCount.value));

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
    const [profile, todoData, sessionPage, ticketPage, pendingShipmentPage] = await Promise.all([
      getCurrentStaff(),
      getDashboardTodos(),
      getSessions({ size: 100 }),
      getTickets({ size: 100 }),
      getOrders({ status: 'PAID', size: 1 })
    ]);
    staff.value = profile;
    todos.value = todoData;
    sessions.value = sessionPage.records || [];
    tickets.value = ticketPage.records || [];
    ticketTotal.value = toFiniteNumber(ticketPage.total, tickets.value.length);
    pendingShipmentCount.value = toFiniteNumber(pendingShipmentPage.total, pendingShipmentPage.records?.length || 0);
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
  if (!showLogout.value || showLogoutAnimation.value) {
    return;
  }

  errorMessage.value = '';
  actionMessage.value = '';
  try {
    await logout();
    logoutFinished = false;
    showLogoutAnimation.value = true;
    scheduleLoginEnterFallback();
  } catch (error) {
    errorMessage.value = error.message || '退出登录失败，请稍后重试';
  }
}

function pushLogin() {
  const root = document.documentElement;

  root.classList.add('welcome-route-transition');

  const clearRouteTransition = () => {
    window.clearTimeout(routeTransitionTimer);
    root.classList.remove('welcome-route-transition');
  };
  routeTransitionTimer = window.setTimeout(clearRouteTransition, 1200);

  return router.replace('/login').finally(clearRouteTransition);
}

function enterLogin() {
  if (logoutFinished) {
    return;
  }

  logoutFinished = true;
  window.clearTimeout(logoutEnterTimer);
  showLogoutAnimation.value = false;
  pushLogin().catch(() => {
    showLogoutAnimation.value = false;
  });
}

function skipLogoutAnimation() {
  enterLogin();
}

function finishLogoutAnimation() {
  enterLogin();
}

function scheduleLoginEnterFallback() {
  window.clearTimeout(logoutEnterTimer);
  logoutEnterTimer = window.setTimeout(() => {
    enterLogin();
  }, LOGOUT_DURATION_MS + 300);
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
  ticketTotal,
  themeMode,
  toggleTheme,
  setAction,
  refreshShell: loadShellData
});

onMounted(loadShellData);

onBeforeUnmount(() => {
  window.clearTimeout(themeAnimationTimer);
  window.clearTimeout(logoutEnterTimer);
  window.clearTimeout(routeTransitionTimer);
});
</script>

<template>
  <main :class="['app-shell', { 'logout-active': showLogoutAnimation }]">
    <SidebarNav
      :staff="staff"
      :sessions="sessions"
      :tickets="tickets"
      :ticket-total="safeTicketTotal"
      :pending-shipment-count="safePendingShipmentCount"
      :todos="todos"
      :show-logout="showLogout"
      @toggle-status="handleToggleStatus"
      @logout="handleLogout"
    />

    <section :class="['page-area', { 'page-area-full': isFullHeightPage }]">
      <TopBar
        :loading="loading"
        :theme-mode="themeMode"
        :show-logout="route.name === 'dashboard'"
        @refresh="loadShellData"
        @logout="handleLogout"
        @toggle-theme="toggleTheme"
      />
      <div v-if="errorMessage" class="status-banner error">{{ errorMessage }}</div>
      <div v-else-if="actionMessage" class="status-banner success">{{ actionMessage }}</div>
      <RouterView />
    </section>

    <WelcomeAnimation
      v-if="showLogoutAnimation"
      :duration-ms="LOGOUT_DURATION_MS"
      title="Goodbye"
      :show-skip="false"
      @skip="skipLogoutAnimation"
      @finished="finishLogoutAnimation"
    />
  </main>
</template>
