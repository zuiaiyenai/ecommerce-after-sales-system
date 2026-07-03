<script setup>
import { computed } from 'vue';
import { useRoute, useRouter } from 'vue-router';

const props = defineProps({
  loading: Boolean,
  themeMode: {
    type: String,
    default: 'light'
  }
});

defineEmits(['refresh', 'toggleTheme']);

const route = useRoute();
const router = useRouter();

const title = computed(() => route.meta.title || '商家客服端');
const showBack = computed(() => route.name === 'sessionDetail' || route.name === 'ticketDetail' || route.name === 'orderDetail');
const themeLabel = computed(() => (props.themeMode === 'dark' ? '夜间模式' : '日间模式'));
const themeIcon = computed(() => (props.themeMode === 'dark' ? 'moon' : 'sun'));

function handleBack() {
  if (window.history.length > 1) {
    router.back();
    return;
  }
  router.push('/sessions');
}
</script>

<template>
  <header class="topbar">
    <div>
      <span class="eyebrow">当前页面</span>
      <h1>{{ title }}</h1>
    </div>
    <div class="topbar-actions">
      <button v-if="showBack" type="button" class="ghost-mini" @click="handleBack">返回上一页</button>
      <button
        type="button"
        :class="['theme-toggle', `theme-toggle-${themeMode}`]"
        :aria-label="themeLabel"
        @click="$emit('toggleTheme')"
      >
        <template v-if="themeIcon === 'moon'">
          <span>{{ themeLabel }}</span>
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M20 15.8A8.3 8.3 0 0 1 8.2 4 8.7 8.7 0 1 0 20 15.8Z" />
          </svg>
        </template>
        <template v-else>
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 4V2" />
            <path d="M12 22v-2" />
            <path d="m4.9 4.9 1.4 1.4" />
            <path d="m17.7 17.7 1.4 1.4" />
            <path d="M4 12H2" />
            <path d="M22 12h-2" />
            <path d="m4.9 19.1 1.4-1.4" />
            <path d="m17.7 6.3 1.4-1.4" />
            <path d="M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10Z" />
          </svg>
          <span>{{ themeLabel }}</span>
        </template>
      </button>
    </div>
  </header>
</template>
