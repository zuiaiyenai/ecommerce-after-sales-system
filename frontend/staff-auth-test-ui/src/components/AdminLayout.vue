<script setup>
import { computed, onMounted, provide, ref, watch } from 'vue';
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

const router = useRouter();
const route = useRoute();
const loading = ref(false);
const errorMessage = ref('');
const actionMessage = ref('');
const admin = ref(null);
const overview = ref(null);
const accountTotal = ref(0);
const knowledgeTotal = ref(0);
const THEME_KEY = 'merchant_cs_theme';
const savedTheme = localStorage.getItem(THEME_KEY);
const themeMode = ref(
  savedTheme || (window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
);
let themeAnimationTimer = 0;

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
  await logoutAdmin();
  setAction('已退出管理员端');
  router.push('/admin/login');
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
</script>

<template>
  <main class="app-shell">
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
  </main>
</template>
