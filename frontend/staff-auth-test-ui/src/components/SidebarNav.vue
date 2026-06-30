<script setup>
import { computed } from 'vue';
import { useRoute } from 'vue-router';

const props = defineProps({
  staff: Object,
  sessions: {
    type: Array,
    default: () => []
  },
  tickets: {
    type: Array,
    default: () => []
  },
  todos: {
    type: Array,
    default: () => []
  }
});

const emit = defineEmits(['toggleStatus', 'logout']);

const route = useRoute();
const terminalSessionStatuses = ['RESOLVED', 'CLOSED'];

const navItems = computed(() => [
  { to: '/dashboard', key: 'dashboard', label: '首页', icon: 'home' },
  {
    to: '/sessions',
    key: 'sessions',
    label: '在线会话',
    icon: 'message',
    count: props.sessions.filter((item) => !terminalSessionStatuses.includes(item.status)).length
  },
  { to: '/tickets', key: 'tickets', label: '售后工单', icon: 'clipboard', count: props.tickets.length },
  { to: '/orders', key: 'orders', label: '订单核验', icon: 'verify' },
  { to: '/products', key: 'products', label: '商品管理', icon: 'package' },
  { to: '/notices', key: 'notices', label: '消息通知', icon: 'bell', count: props.todos.length },
  { to: '/profile', key: 'profile', label: '个人中心', icon: 'user' }
]);

const iconPaths = {
  home: ['M3 10.8 12 3l9 7.8', 'M5.5 9.2V20h13V9.2', 'M9.5 20v-6h5v6'],
  message: ['M5 6.5h14v9H9l-4 3v-12Z', 'M8.5 10.5h.01', 'M12 10.5h.01', 'M15.5 10.5h.01'],
  clipboard: ['M9 4h6l1 2h3v15H5V6h3l1-2Z', 'M9 11h6', 'M9 15h6', 'M8 11h.01', 'M8 15h.01'],
  verify: ['M9 4h6l1 2h3v15H5V6h3l1-2Z', 'M8.5 12.5h4', 'M8.5 16h2.5', 'm13.5 15.5 2 2 4-4'],
  bell: ['M18 10a6 6 0 0 0-12 0c0 4-2 5-2 6h16c0-1-2-2-2-6Z', 'M9.5 19a2.5 2.5 0 0 0 5 0'],
  user: ['M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z', 'M4.5 20a7.5 7.5 0 0 1 15 0'],
  package: ['M15 3h4l2 5H3l2-5h4', 'M15 3v5h4l-2 12H7L5 8h4V3', 'M9 3h6', 'M9 12h6', 'M9 16h6']
};

const isOnline = computed(() => props.staff?.onlineStatus === 'ONLINE');

function isActive(item) {
  return route.path === item.to || route.path.startsWith(`${item.to}/`);
}
</script>

<template>
  <aside class="sidebar">
    <div class="brand-block">
      <div class="brand-mark">V</div>
      <div>
        <strong>商家客服端</strong>
        <p>After-sales Console</p>
      </div>
    </div>

    <nav class="side-nav" aria-label="商家客服端导航">
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
      <div class="avatar">{{ staff?.realName?.slice(0, 1) || '客' }}</div>
      <div>
        <strong>{{ staff?.realName || '未登录客服' }}</strong>
        <p>{{ staff?.staffNo || '请先登录' }}</p>
      </div>
      <span :class="['status-pill', isOnline ? 'online' : 'offline']">
        {{ staff?.onlineStatus || 'OFFLINE' }}
      </span>
    </section>

    <button type="button" class="ghost-action" @click="$emit('toggleStatus')">
      {{ isOnline ? '切换为离线' : '切换为在线' }}
    </button>

    <button type="button" class="ghost-action logout-btn" @click="$emit('logout')">
      退出登录
    </button>
  </aside>
</template>
