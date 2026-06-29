<script setup>
import { computed } from 'vue';
import { useRoute, useRouter } from 'vue-router';

defineProps({
  loading: Boolean
});

defineEmits(['refresh', 'logout']);

const route = useRoute();
const router = useRouter();

const title = computed(() => route.meta.title || '商家客服端');
const showLogout = computed(() => route.name === 'dashboard');
const showBack = computed(() => route.name === 'sessionDetail');

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
    <div v-if="showLogout || showBack" class="topbar-actions">
      <button v-if="showBack" type="button" class="ghost-mini" @click="handleBack">返回上一页</button>
      <button v-if="showLogout" type="button" class="ghost-mini" @click="$emit('logout')">log out</button>
    </div>
  </header>
</template>
