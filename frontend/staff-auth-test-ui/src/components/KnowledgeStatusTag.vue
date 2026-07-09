<script setup>
defineProps({
  status: {
    type: String,
    default: 'ENABLED'
  },
  label: {
    type: String,
    default: ''
  }
});
</script>

<template>
  <span :class="['knowledge-status-tag', status.toLowerCase()]">
    {{ label }}
  </span>
</template>

<style scoped>
.knowledge-status-tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 26px;
  padding: 0 10px;
  border: 1px solid transparent;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 800;
  line-height: 1;
  white-space: nowrap;
}

.knowledge-status-tag.enabled {
  color: #278553;
  border-color: rgba(55, 166, 103, 0.2);
  background: rgba(55, 166, 103, 0.13);
}

.knowledge-status-tag.pending {
  color: #256db4;
  border-color: rgba(49, 120, 198, 0.2);
  background: rgba(49, 120, 198, 0.12);
}

.knowledge-status-tag.failed {
  color: #ba3b2e;
  border-color: rgba(201, 66, 50, 0.2);
  background: rgba(201, 66, 50, 0.1);
}

.knowledge-status-tag.disabled {
  color: #687384;
  border-color: rgba(104, 115, 132, 0.2);
  background: rgba(104, 115, 132, 0.12);
}

html[data-theme="dark"] .knowledge-status-tag.enabled {
  color: #7be0a5;
  border-color: rgba(95, 202, 142, 0.22);
  background: rgba(95, 202, 142, 0.14);
}

html[data-theme="dark"] .knowledge-status-tag.pending {
  color: #8ebeff;
  border-color: rgba(115, 169, 240, 0.22);
  background: rgba(115, 169, 240, 0.14);
}

html[data-theme="dark"] .knowledge-status-tag.failed {
  color: #ff9a8f;
  border-color: rgba(255, 123, 109, 0.24);
  background: rgba(255, 123, 109, 0.13);
}

html[data-theme="dark"] .knowledge-status-tag.disabled {
  color: #aab6c6;
  border-color: rgba(170, 182, 198, 0.18);
  background: rgba(170, 182, 198, 0.11);
}
</style>
