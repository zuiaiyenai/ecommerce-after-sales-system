<script setup>
import { computed, onBeforeUnmount, onMounted, provide, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import {
  getAdminOverview,
  getAgentAccounts,
  getCurrentAdmin,
  getKnowledgeLibraries,
  logoutAdmin
} from '../api/adminConsole';
import AdminSidebarNav from './AdminSidebarNav.vue';
import TopBar from './TopBar.vue';
import WelcomeAnimation from './WelcomeAnimation.vue';

const router = useRouter();
const route = useRoute();
const loading = ref(false);
const errorMessage = ref('');
const actionMessage = ref('');
const admin = ref(null);
const overview = ref(null);
const accountTotal = ref(0);
const knowledgeTotal = ref(0);
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

const isDarkTheme = computed(() => themeMode.value === 'dark');
const fullHeightRoutes = ['adminDashboard', 'adminAccounts', 'adminKnowledge'];

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
    const [profile, overviewData, accountPage, knowledgePage] = await Promise.all([
      getCurrentAdmin(),
      getAdminOverview(),
      getAgentAccounts(),
      getKnowledgeLibraries()
    ]);
    admin.value = profile;
    overview.value = overviewData;
    accountTotal.value = accountPage.total ?? accountPage.records?.length ?? 0;
    knowledgeTotal.value = knowledgePage.total ?? knowledgePage.records?.length ?? 0;
  } catch (error) {
    errorMessage.value = error.message || '管理员基础数据加载失败';
  } finally {
    loading.value = false;
  }
}

async function handleLogout() {
  if (showLogoutAnimation.value) {
    return;
  }

  errorMessage.value = '';
  actionMessage.value = '';
  await logoutAdmin();
  logoutFinished = false;
  showLogoutAnimation.value = true;
  scheduleLoginEnterFallback();
  setAction('已退出管理员端');
}

function pushLogin() {
  const root = document.documentElement;

  root.classList.add('welcome-route-transition');

  const clearRouteTransition = () => {
    window.clearTimeout(routeTransitionTimer);
    root.classList.remove('welcome-route-transition');
  };
  routeTransitionTimer = window.setTimeout(clearRouteTransition, 1200);

  return router.replace('/admin/login').finally(clearRouteTransition);
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

provide('adminShell', {
  admin,
  overview,
  setAction,
  refreshShell: loadShellData,
  themeMode,
  toggleTheme
});

onMounted(loadShellData);

onBeforeUnmount(() => {
  window.clearTimeout(themeAnimationTimer);
  window.clearTimeout(logoutEnterTimer);
  window.clearTimeout(routeTransitionTimer);
});
</script>

<template>
  <main :class="['app-shell', 'admin-shell', { 'logout-active': showLogoutAnimation }]">
    <AdminSidebarNav
      :admin="admin"
      :account-total="accountTotal"
      :knowledge-total="knowledgeTotal"
      @logout="handleLogout"
    />

    <section :class="['page-area', { 'page-area-full': fullHeightRoutes.includes(route.name) }]">
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
