<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';
import { loginAdmin } from '../api/adminConsole';
import WelcomeAnimation from '../components/WelcomeAnimation.vue';
import avatarOne from '../assets/support-avatar-1.png';
import avatarTwo from '../assets/support-avatar-2.png';
import avatarThree from '../assets/support-avatar-3.png';
import avatarFour from '../assets/support-avatar-4.png';
import avatarFive from '../assets/support-avatar-5.png';
import avatarSix from '../assets/support-avatar-6.png';

const router = useRouter();
const loading = ref(false);
const errorMessage = ref('');
const actionMessage = ref('');
const showWelcome = ref(false);
const WELCOME_DURATION_MS = 5000;
let welcomeFinished = false;
let previousThemeMode = '';
let dashboardEnterTimer = 0;
let routeTransitionTimer = 0;

const form = reactive({
  account: '',
  password: ''
});

const networkAvatars = [
  { className: 'node-one', src: avatarOne, alt: '用户头像' },
  { className: 'node-two', src: avatarTwo, alt: '用户头像' },
  { className: 'node-three', src: avatarThree, alt: '用户头像' },
  { className: 'node-four', src: avatarFour, alt: '用户头像' },
  { className: 'node-five', src: avatarFive, alt: '用户头像' },
  { className: 'node-six', src: avatarSix, alt: '用户头像' }
];

const loginButtonText = computed(() => (loading.value ? '正在进入...' : '登录进入管理员端'));

function clearScheduledDashboardEnter() {
  window.clearTimeout(dashboardEnterTimer);
  dashboardEnterTimer = 0;
}

function scheduleDashboardEnterFallback() {
  clearScheduledDashboardEnter();
  dashboardEnterTimer = window.setTimeout(() => {
    enterDashboard();
  }, WELCOME_DURATION_MS + 300);
}

function pushDashboard() {
  const root = document.documentElement;
  const supportsViewTransition = typeof document.startViewTransition === 'function';
  root.classList.add('welcome-route-transition');
  const clearRouteTransition = () => {
    window.clearTimeout(routeTransitionTimer);
    root.classList.remove('welcome-route-transition');
  };
  routeTransitionTimer = window.setTimeout(clearRouteTransition, 1200);
  if (!supportsViewTransition) {
    return router.push('/admin/dashboard').finally(clearRouteTransition);
  }
  try {
    const transition = document.startViewTransition(() => router.push('/admin/dashboard'));
    return transition.finished.finally(clearRouteTransition);
  } catch {
    return router.push('/admin/dashboard').finally(clearRouteTransition);
  }
}

function enterDashboard() {
  if (welcomeFinished) return;
  welcomeFinished = true;
  clearScheduledDashboardEnter();
  pushDashboard().catch(() => {
    showWelcome.value = false;
    welcomeFinished = false;
  });
}

function skipWelcome() {
  enterDashboard();
}

function finishWelcome() {
  enterDashboard();
}

function showAction(message) {
  actionMessage.value = message;
  window.setTimeout(() => {
    if (actionMessage.value === message) {
      actionMessage.value = '';
    }
  }, 2200);
}

async function handleLogin() {
  loading.value = true;
  errorMessage.value = '';
  try {
    await loginAdmin(form);
    welcomeFinished = false;
    showWelcome.value = true;
    scheduleDashboardEnterFallback();
  } catch (error) {
    errorMessage.value = error.message || '管理员登录失败';
    showWelcome.value = false;
    welcomeFinished = false;
  } finally {
    loading.value = false;
  }
}

function jumpToStaffLogin() {
  showAction('已切换到客服登录入口');
  router.push('/login');
}

onMounted(() => {
  const root = document.documentElement;
  previousThemeMode = root.dataset.theme || '';
  root.dataset.theme = 'light';
});

onBeforeUnmount(() => {
  clearScheduledDashboardEnter();
  window.clearTimeout(routeTransitionTimer);
  const root = document.documentElement;
  if (previousThemeMode) {
    root.dataset.theme = previousThemeMode;
  } else {
    root.removeAttribute('data-theme');
  }
});
</script>

<template>
  <main class="login-view admin-login-view">
    <section class="login-stage" aria-label="管理员端欢迎区">
      <div class="support-network" aria-hidden="true">
        <div class="network-glow glow-one"></div>
        <div class="network-glow glow-two"></div>
        <div class="network-orbit orbit-outer"></div>
        <div class="network-orbit orbit-middle"></div>
        <div class="network-orbit orbit-inner"></div>

        <div class="network-avatar center-avatar">AD</div>
        <div
          v-for="avatar in networkAvatars"
          :key="avatar.className"
          :class="['network-avatar', 'node', avatar.className]"
        >
          <img :src="avatar.src" :alt="avatar.alt" />
        </div>

        <div class="network-copy">
          <h1>管理员治理台</h1>
          <p>统一管理客服账号、知识库建设状态与后续治理接口</p>
        </div>
      </div>
    </section>

    <form class="login-box" @submit.prevent="handleLogin">
      <div class="login-box-head">
        <span class="eyebrow">Admin Portal</span>
        <h2>管理员登录</h2>
      </div>

      <label class="login-field">
        <span>管理员账号</span>
        <input v-model.trim="form.account" autocomplete="username" placeholder="请输入管理员账号" />
      </label>
      <label class="login-field">
        <span>密码</span>
        <input
          v-model="form.password"
          type="password"
          autocomplete="current-password"
          placeholder="请输入登录密码"
        />
      </label>

      <div v-if="errorMessage" class="status-banner error">{{ errorMessage }}</div>
      <div v-else-if="actionMessage" class="status-banner success">{{ actionMessage }}</div>

      <button type="submit" :class="['login-submit', { loading }]" :disabled="loading">
        <span>{{ loginButtonText }}</span>
      </button>

      <div class="login-register-row">
        <span>需要进入客服工作台？</span>
        <button type="button" class="login-register-button" @click="jumpToStaffLogin">客服入口</button>
      </div>
    </form>

    <WelcomeAnimation
      v-if="showWelcome"
      :duration-ms="WELCOME_DURATION_MS"
      @skip="skipWelcome"
      @finished="finishWelcome"
    />
  </main>
</template>
