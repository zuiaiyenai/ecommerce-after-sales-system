<script setup>
import { computed, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';
import { loginAdmin } from '../api/adminConsole';

const router = useRouter();
const loading = ref(false);
const errorMessage = ref('');
const actionMessage = ref('');

const form = reactive({
  account: '',
  password: ''
});

const loginButtonText = computed(() => (loading.value ? '正在进入...' : '登录进入管理员端'));

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
    router.push('/admin/dashboard');
  } catch (error) {
    errorMessage.value = error.message || '管理员登录失败';
  } finally {
    loading.value = false;
  }
}

function jumpToStaffLogin() {
  showAction('已切换到客服登录入口');
  router.push('/login');
}
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
  </main>
</template>
