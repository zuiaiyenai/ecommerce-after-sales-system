<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';
import { login, registerStaff, resetPassword, sendAuthCode } from '../api/merchantCs';
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
const mode = ref('login');
const WELCOME_DURATION_MS = 5000;
let welcomeFinished = false;
let previousThemeMode = '';
let dashboardEnterTimer = 0;
let routeTransitionTimer = 0;

const form = reactive({
  account: '',
  password: '',
  confirmPassword: '',
  realName: '',
  phone: '',
  code: '',
  newPassword: '',
  newPasswordConfirm: ''
});

const networkAvatars = [
  { className: 'node-one', src: avatarOne, alt: '用户头像' },
  { className: 'node-two', src: avatarTwo, alt: '用户头像' },
  { className: 'node-three', src: avatarThree, alt: '用户头像' },
  { className: 'node-four', src: avatarFour, alt: '用户头像' },
  { className: 'node-five', src: avatarFive, alt: '用户头像' },
  { className: 'node-six', src: avatarSix, alt: '用户头像' }
];

const isLoginMode = computed(() => mode.value === 'login');
const isRegisterMode = computed(() => mode.value === 'register');
const isResetMode = computed(() => mode.value === 'reset');
const panelTitle = computed(() => {
  if (isRegisterMode.value) return '客服注册';
  if (isResetMode.value) return '找回密码';
  return '客服登录';
});
const panelEyebrow = computed(() => {
  if (isRegisterMode.value) return 'Staff Register';
  if (isResetMode.value) return 'Password Reset';
  return 'Secure Login';
});
const submitButtonText = computed(() => {
  if (loading.value) {
    if (isRegisterMode.value) return '正在提交注册...';
    if (isResetMode.value) return '正在重置密码...';
    return '正在进入...';
  }
  if (isRegisterMode.value) return '提交注册';
  if (isResetMode.value) return '重置密码';
  return '登录进入工作台';
});

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
    return router.push('/dashboard').finally(clearRouteTransition);
  }
  try {
    const transition = document.startViewTransition(() => router.push('/dashboard'));
    return transition.finished.finally(clearRouteTransition);
  } catch {
    return router.push('/dashboard').finally(clearRouteTransition);
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
  }, 2600);
}

function clearStatus() {
  errorMessage.value = '';
  actionMessage.value = '';
}

function switchMode(nextMode) {
  clearStatus();
  mode.value = nextMode;
  form.password = '';
  form.confirmPassword = '';
  form.code = '';
  form.newPassword = '';
  form.newPasswordConfirm = '';
}

async function handleSubmit() {
  if (isRegisterMode.value) {
    await handleRegisterSubmit();
    return;
  }
  if (isResetMode.value) {
    await handleResetSubmit();
    return;
  }
  await handleLogin();
}

async function handleLogin() {
  loading.value = true;
  clearStatus();
  try {
    const result = await login({
      account: form.account,
      password: form.password
    });
    loginStaffName.value = result?.staff?.realName || form.account || '客服';
    welcomeFinished = false;
    showWelcome.value = true;
    scheduleDashboardEnterFallback();
  } catch (error) {
    errorMessage.value = error.message || '登录失败，请检查账号和密码';
    showWelcome.value = false;
    welcomeFinished = false;
  } finally {
    loading.value = false;
  }
}

async function handleSendCode() {
  if (!form.phone) {
    errorMessage.value = '请输入手机号';
    return;
  }
  if (isResetMode.value && !form.account) {
    errorMessage.value = '请输入登录账号';
    return;
  }
  loading.value = true;
  clearStatus();
  try {
    const result = await sendAuthCode({
      scene: isResetMode.value ? 'RESET_PASSWORD' : 'REGISTER',
      account: form.account,
      phone: form.phone
    });
    showAction(result?.code ? `验证码：${result.code}` : '验证码已发送');
  } catch (error) {
    errorMessage.value = error.message || '验证码发送失败';
  } finally {
    loading.value = false;
  }
}

async function handleRegisterSubmit() {
  if (!form.account || !form.password || !form.confirmPassword || !form.realName || !form.phone || !form.code) {
    errorMessage.value = '请填写账号、密码、确认密码、姓名、手机号和验证码';
    return;
  }
  if (form.password !== form.confirmPassword) {
    errorMessage.value = '两次输入的密码不一致';
    return;
  }
  loading.value = true;
  clearStatus();
  try {
    const result = await registerStaff({
      account: form.account,
      password: form.password,
      realName: form.realName,
      phone: form.phone,
      code: form.code
    });
    switchMode('login');
    showAction(result?.accountStatus === 'PENDING_APPROVAL'
      ? '注册申请已提交，请等待管理员审核通过后再登录'
      : '注册成功，请使用账号密码登录');
  } catch (error) {
    errorMessage.value = error.message || '注册失败';
  } finally {
    loading.value = false;
  }
}

async function handleResetSubmit() {
  if (!form.account || !form.phone || !form.code || !form.newPassword || !form.newPasswordConfirm) {
    errorMessage.value = '请填写账号、手机号、验证码和新密码';
    return;
  }
  if (form.newPassword !== form.newPasswordConfirm) {
    errorMessage.value = '两次输入的新密码不一致';
    return;
  }
  loading.value = true;
  clearStatus();
  try {
    await resetPassword({
      account: form.account,
      phone: form.phone,
      code: form.code,
      newPassword: form.newPassword,
      confirmPassword: form.newPasswordConfirm
    });
    switchMode('login');
    showAction('密码已重置，请重新登录');
  } catch (error) {
    errorMessage.value = error.message || '密码重置失败';
  } finally {
    loading.value = false;
  }
}

function handleAdminPortal() {
  router.push('/admin/login');
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

    <form class="login-box" @submit.prevent="handleSubmit">
      <div class="login-box-head">
        <span class="eyebrow">{{ panelEyebrow }}</span>
        <h2>{{ panelTitle }}</h2>
      </div>

      <label v-if="isRegisterMode" class="login-field">
        <span>姓名</span>
        <input v-model.trim="form.realName" placeholder="请输入姓名" />
      </label>

      <label class="login-field">
        <span>账号</span>
        <input v-model.trim="form.account" autocomplete="username" placeholder="请输入客服账号" />
      </label>

      <label v-if="isLoginMode || isRegisterMode" class="login-field">
        <span>{{ isRegisterMode ? '设置密码' : '密码' }}</span>
        <input
          v-model="form.password"
          type="password"
          :autocomplete="isRegisterMode ? 'new-password' : 'current-password'"
          :placeholder="isRegisterMode ? '请设置登录密码' : '请输入登录密码'"
        />
      </label>

      <label v-if="isRegisterMode" class="login-field">
        <span>确认密码</span>
        <input v-model="form.confirmPassword" type="password" autocomplete="new-password" placeholder="请再次输入密码" />
      </label>

      <label v-if="isRegisterMode || isResetMode" class="login-field">
        <span>手机号</span>
        <input v-model.trim="form.phone" placeholder="请输入绑定手机号" />
      </label>

      <template v-if="isRegisterMode || isResetMode">
        <label class="login-field">
          <span>验证码</span>
          <input v-model.trim="form.code" placeholder="请输入验证码" />
        </label>
        <div class="login-help-row">
          <button type="button" class="login-link" @click="handleSendCode">发送验证码</button>
        </div>
      </template>

      <template v-if="isResetMode">
        <label class="login-field">
          <span>新密码</span>
          <input v-model="form.newPassword" type="password" autocomplete="new-password" placeholder="请输入新密码" />
        </label>
        <label class="login-field">
          <span>确认新密码</span>
          <input v-model="form.newPasswordConfirm" type="password" autocomplete="new-password" placeholder="请再次输入新密码" />
        </label>
      </template>

      <div v-if="isLoginMode" class="login-help-row">
        <button type="button" class="login-link" @click="switchMode('reset')">忘记密码？</button>
      </div>

      <div v-if="errorMessage" class="status-banner error">{{ errorMessage }}</div>
      <div v-else-if="actionMessage" class="status-banner success">{{ actionMessage }}</div>

      <button type="submit" :class="['login-submit', { loading }]" :disabled="loading">
        <span>{{ submitButtonText }}</span>
      </button>

      <div class="login-register-row">
        <span v-if="isLoginMode">还没有客服账号？</span>
        <span v-else-if="isRegisterMode">已经有客服账号？</span>
        <span v-else>想起密码了？</span>
        <button v-if="isLoginMode" type="button" class="login-register-button" @click="switchMode('register')">注册</button>
        <button v-else type="button" class="login-register-button" @click="switchMode('login')">返回登录</button>
      </div>

      <div v-if="isLoginMode" class="login-register-row">
        <span>需要进入管理员端？</span>
        <button type="button" class="login-register-button" @click="handleAdminPortal">管理员入口</button>
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
