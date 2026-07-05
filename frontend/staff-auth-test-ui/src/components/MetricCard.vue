<script setup>
defineProps({
  title: String,
  value: [String, Number],
  trend: String,
  accent: {
    type: String,
    default: 'orange'
  }
});
</script>

<template>
  <article :class="['metric-card', accent]">
    <p>{{ title }}</p>
    <strong>{{ value }}</strong>
    <span>{{ trend }} 较上一小时</span>
  </article>
</template>
