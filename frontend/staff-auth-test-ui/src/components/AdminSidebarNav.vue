<script setup>
import { computed } from 'vue';
import { useRoute } from 'vue-router';

const props = defineProps({
  admin: Object,
  accountTotal: {
    type: Number,
    default: 0
  },
  knowledgeTotal: {
    type: Number,
    default: 0
  }
});

defineEmits(['logout']);

const route = useRoute();

const navItems = computed(() => [
  { to: '/admin/dashboard', key: 'adminDashboard', label: '首页', icon: 'home' },
  { to: '/admin/accounts', key: 'adminAccounts', label: '客服账号管理', icon: 'users', count: props.accountTotal },
  { to: '/admin/knowledge', key: 'adminKnowledge', label: '知识库管理', icon: 'database', count: props.knowledgeTotal },
  { to: '/admin/agent-operations', key: 'adminAgentOperations', label: 'Agent 运行中心', icon: 'pulse' }
]);

const iconPaths = {
  home: ['M3 10.8 12 3l9 7.8', 'M5.5 9.2V20h13V9.2', 'M9.5 20v-6h5v6'],
  users: ['M9 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z', 'M17 12a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z', 'M3.8 20a5.2 5.2 0 0 1 10.4 0', 'M14.5 20a4 4 0 0 1 6.5-3.1'],
  database: ['M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3Z', 'M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3', 'M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6'],
  pulse: ['M3 12h4l2.2-6 4.1 12 2.2-6H21', 'M4 4v16', 'M20 4v16']
};

function isActive(item) {
  return route.path === item.to || route.path.startsWith(`${item.to}/`);
}
</script>

<template>
  <aside class="sidebar admin-sidebar">
    <div class="brand-block">
      <div class="brand-mark">A</div>
      <div>
        <strong>管理员端</strong>
        <p>Admin Console</p>
      </div>
    </div>

    <nav class="side-nav" aria-label="管理员端导航">
      <RouterLink
        v-for="item in navItems"
        :key="item.key"
        :to="item.to"
        :class="['nav-item', { active: isActive(item) }]"
      >
        <span class="nav-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" focusable="false">
            <path v-for="path in iconPaths[item.icon]" :key="path" :d="path" />
          </svg>
        </span>
        <span>{{ item.label }}</span>
        <em v-if="item.count">{{ item.count }}</em>
      </RouterLink>
    </nav>

    <section class="agent-card">
      <div class="avatar">{{ admin?.realName?.slice(0, 1) || '管' }}</div>
      <div>
        <strong>{{ admin?.realName || '管理员' }}</strong>
        <p>{{ admin?.account || '未登录' }}</p>
      </div>
      <span class="status-pill online">{{ admin?.role || 'ADMIN' }}</span>
    </section>

    <button type="button" class="ghost-action logout-btn" @click="$emit('logout')">
      退出登录
    </button>
  </aside>
</template>
