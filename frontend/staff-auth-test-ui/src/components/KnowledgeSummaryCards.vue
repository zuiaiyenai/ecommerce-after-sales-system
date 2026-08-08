<script setup>
defineProps({
  cards: {
    type: Array,
    default: () => []
  }
});
</script>

<template>
  <section class="knowledge-summary-grid" aria-label="知识库概览">
    <article v-for="card in cards" :key="card.key" :class="['knowledge-summary-card', card.tone]">
      <span class="summary-icon">{{ card.icon }}</span>
      <div class="summary-copy">
        <span>{{ card.label }}</span>
        <strong>{{ card.value }}</strong>
        <p>{{ card.desc }}</p>
      </div>
    </article>
  </section>
</template>

<style scoped>
.knowledge-summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.knowledge-summary-card {
  --summary-accent: #ff8a3d;
  --summary-tint: rgba(255, 138, 61, 0.13);
  min-height: 92px;
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr);
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  border: 1px solid rgba(255, 255, 255, 0.7);
  border-radius: 20px;
  background:
    linear-gradient(135deg, var(--summary-tint), rgba(255, 255, 255, 0.74) 68%),
    rgba(255, 255, 255, 0.88);
  box-shadow: 0 16px 38px rgba(31, 41, 55, 0.07);
  transition:
    transform 160ms ease,
    box-shadow 160ms ease,
    border-color 160ms ease;
}

.knowledge-summary-card:hover {
  transform: translateY(-3px);
  border-color: color-mix(in srgb, var(--summary-accent) 38%, transparent);
  box-shadow: 0 20px 48px rgba(31, 41, 55, 0.1);
}

.knowledge-summary-card.orange {
  --summary-accent: #ff8a3d;
  --summary-tint: rgba(255, 138, 61, 0.15);
}

.knowledge-summary-card.green {
  --summary-accent: #37a667;
  --summary-tint: rgba(55, 166, 103, 0.13);
}

.knowledge-summary-card.blue {
  --summary-accent: #3178c6;
  --summary-tint: rgba(49, 120, 198, 0.13);
}

.knowledge-summary-card.red {
  --summary-accent: #c94232;
  --summary-tint: rgba(201, 66, 50, 0.1);
}

.summary-icon {
  width: 42px;
  height: 42px;
  display: grid;
  place-items: center;
  border-radius: 14px;
  color: var(--summary-accent);
  background: rgba(255, 255, 255, 0.7);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--summary-accent) 16%, transparent);
  font-weight: 900;
}

.summary-copy {
  min-width: 0;
}

.summary-copy span,
.summary-copy p {
  margin: 0;
  color: var(--muted);
  font-size: 12px;
}

.summary-copy span {
  font-weight: 800;
}

.summary-copy strong {
  display: block;
  margin: 4px 0 3px;
  color: var(--text);
  font-size: 30px;
  line-height: 1;
}

@media (max-width: 1360px) {
  .knowledge-summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .knowledge-summary-grid {
    grid-template-columns: 1fr;
  }
}

html[data-theme="dark"] .knowledge-summary-card {
  border-color: rgba(255, 255, 255, 0.12);
  background:
    linear-gradient(135deg, var(--summary-tint), rgba(17, 26, 39, 0.72) 68%),
    rgba(17, 26, 39, 0.76);
  box-shadow: 0 18px 42px rgba(0, 0, 0, 0.28);
}

html[data-theme="dark"] .knowledge-summary-card:hover {
  box-shadow: 0 22px 52px rgba(0, 0, 0, 0.34);
}

html[data-theme="dark"] .summary-icon {
  background: rgba(255, 255, 255, 0.08);
}
</style>
