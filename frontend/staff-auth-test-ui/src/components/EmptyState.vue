<script setup>
defineProps({
  title: String,
  desc: String,
  action: String
});

defineEmits(['action']);
</script>

<template>
  <section class="empty-state">
    <span class="eyebrow">Coming Next</span>
    <h2>{{ title }}</h2>
    <p>{{ desc }}</p>
    <button v-if="action" type="button" class="primary-action compact" @click="$emit('action')">
      {{ action }}
    </button>
  </section>
</template>
