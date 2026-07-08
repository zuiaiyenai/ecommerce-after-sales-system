<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';
import { login } from '../api/merchantCs';
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
const loginStaffName = ref('');
const WELCOME_DURATION_MS = 5000;
let welcomeFinished = false;
let previousThemeMode = '';
let dashboardEnterTimer = 0;
let routeTransitionTimer = 0;

const form = reactive({
  account: '',
  password: '',
  merchantCode: ''
});

const networkAvatars = [
  { className: 'node-one', src: avatarOne, alt: '用户头像' },
  { className: 'node-two', src: avatarTwo, alt: '用户头像' },
  { className: 'node-three', src: avatarThree, alt: '用户头像' },
  { className: 'node-four', src: avatarFour, alt: '用户头像' },
  { className: 'node-five', src: avatarFive, alt: '用户头像' },
  { className: 'node-six', src: avatarSix, alt: '用户头像' }
];

const loginButtonText = computed(() => (loading.value ? '正在进入...' : '登录进入工作台'));

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

  root.classList.add('welcome-route-transition');

  const clearRouteTransition = () => {
    window.clearTimeout(routeTransitionTimer);
    root.classList.remove('welcome-route-transition');
  };
  routeTransitionTimer = window.setTimeout(clearRouteTransition, 1200);

  router.push('/dashboard').finally(clearRouteTransition);
}

function enterDashboard() {
  if (welcomeFinished) {
    return;
  }

  welcomeFinished = true;
  clearScheduledDashboardEnter();
  showWelcome.value = false;
  pushDashboard();
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
  actionMessage.value = '';
  try {
    const result = await login(form);
    clearScheduledDashboardEnter();
    loginStaffName.value = result?.staff?.realName || form.account || '客服';
    welcomeFinished = false;
    showWelcome.value = true;
    scheduleDashboardEnterFallback();
  } catch (error) {
    errorMessage.value = error.message || '登录失败，请检查账号或密码';
    showWelcome.value = false;
    welcomeFinished = false;
  } finally {
    loading.value = false;
  }
}

function handleForgotPassword() {
  errorMessage.value = '';
  showAction('忘记密码流程后续接入账号安全接口');
}

function handleRegister() {
  errorMessage.value = '';
  showAction('注册申请入口已保留，后续接入商家客服开户注册流程');
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
  <main :class="['login-view', { 'welcome-active': showWelcome }]">
    <section class="login-stage" aria-label="商家客服端欢迎区">
      <div class="support-network" aria-hidden="true">
        <div class="network-glow glow-one"></div>
        <div class="network-glow glow-two"></div>
        <div class="network-orbit orbit-outer"></div>
        <div class="network-orbit orbit-middle"></div>
        <div class="network-orbit orbit-inner"></div>

        <div class="network-avatar center-avatar">CS</div>
        <div
          v-for="avatar in networkAvatars"
          :key="avatar.className"
          :class="['network-avatar', 'node', avatar.className]"
        >
          <img :src="avatar.src" :alt="avatar.alt" />
        </div>

        <span class="network-dot dot-one"></span>
        <span class="network-dot dot-two"></span>
        <span class="network-dot dot-three"></span>

        <div class="network-copy">
          <h1>商家客服工作台</h1>
          <p>集中处理用户咨询、售后工单与服务记录</p>
        </div>
      </div>
    </section>

    <form class="login-box" @submit.prevent="handleLogin">
      <div class="login-box-head">
        <span class="eyebrow">Secure Login</span>
        <h2>客服登录</h2>
      </div>

      <label class="login-field">
        <span>账号</span>
        <input v-model.trim="form.account" autocomplete="username" placeholder="请输入客服账号" />
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
      <label class="login-field">
        <span>商家编码</span>
        <input v-model.trim="form.merchantCode" placeholder="请输入商家编码" />
      </label>

      <div class="login-help-row">
        <button type="button" class="login-link" @click="handleForgotPassword">忘记密码？</button>
      </div>

      <div v-if="errorMessage" class="status-banner error">{{ errorMessage }}</div>
      <div v-else-if="actionMessage" class="status-banner success">{{ actionMessage }}</div>

      <button type="submit" :class="['login-submit', { loading }]" :disabled="loading">
        <span>{{ loginButtonText }}</span>
      </button>

      <div class="login-register-row">
        <span>还没有客服账号？</span>
        <button type="button" class="login-register-button" @click="handleRegister">注册</button>
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
