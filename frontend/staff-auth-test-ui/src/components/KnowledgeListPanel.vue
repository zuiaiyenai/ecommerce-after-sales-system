<script setup>
import KnowledgeStatusTag from './KnowledgeStatusTag.vue';

defineProps({
  items: {
    type: Array,
    default: () => []
  },
  selectedId: {
    type: [String, Number],
    default: null
  },
  loading: Boolean,
  errorMessage: {
    type: String,
    default: ''
  },
  search: {
    type: String,
    default: ''
  },
  status: {
    type: String,
    default: 'ALL'
  },
  category: {
    type: String,
    default: 'ALL'
  },
  source: {
    type: String,
    default: 'ALL'
  },
  statusOptions: {
    type: Array,
    default: () => []
  },
  categoryOptions: {
    type: Array,
    default: () => []
  },
  sourceOptions: {
    type: Array,
    default: () => []
  },
  total: {
    type: Number,
    default: 0
  }
});

defineEmits([
  'select',
  'update:search',
  'update:status',
  'update:category',
  'update:source'
]);
</script>

<template>
  <aside class="knowledge-list-panel">
    <header class="list-head">
      <div>
        <span class="eyebrow">Knowledge Items</span>
        <h2>知识条目</h2>
      </div>
      <span class="list-total">{{ total }} 条</span>
    </header>

    <label class="knowledge-search">
      <span aria-hidden="true">⌕</span>
      <input
        :value="search"
        type="search"
        placeholder="搜索标题 / 分类 / 商家编码"
        @input="$emit('update:search', $event.target.value)"
      />
    </label>

    <div class="status-filters" aria-label="知识状态筛选">
      <button
        v-for="option in statusOptions"
        :key="option.key"
        type="button"
        :class="{ active: status === option.key }"
        @click="$emit('update:status', option.key)"
      >
        {{ option.label }}
      </button>
    </div>

    <div class="select-filters">
      <label>
        <span>分类</span>
        <select :value="category" @change="$emit('update:category', $event.target.value)">
          <option v-for="option in categoryOptions" :key="option.value" :value="option.value">
            {{ option.label }}
          </option>
        </select>
      </label>
      <label>
        <span>来源</span>
        <select :value="source" @change="$emit('update:source', $event.target.value)">
          <option v-for="option in sourceOptions" :key="option.value" :value="option.value">
            {{ option.label }}
          </option>
        </select>
      </label>
    </div>

    <div v-if="items.length" class="knowledge-items">
      <button
        v-for="item in items"
        :key="item.id"
        type="button"
        :class="['knowledge-item-card', { active: item.id === selectedId, failed: item.displayStatus === 'FAILED' }]"
        @click="$emit('select', item)"
      >
        <span class="item-main-row">
          <strong>{{ item.name }}</strong>
          <KnowledgeStatusTag :status="item.displayStatus" :label="item.displayStatusLabel" />
        </span>
        <span class="item-meta-row">
          {{ item.typeLabel }} · {{ item.sourceLabel }} · {{ item.scopeLabel }}
        </span>
        <span class="item-foot-row">
          <small>{{ item.chunkCount || 0 }} chunks</small>
          <small>{{ item.updatedAtLabel }} 更新</small>
        </span>
      </button>
    </div>

    <div v-else class="knowledge-empty">
      <strong>{{ loading ? '正在加载知识条目' : errorMessage ? '知识库加载失败' : '没有匹配的知识条目' }}</strong>
      <p>{{ loading ? '请稍候，正在同步知识库状态。' : errorMessage || '可以调整搜索词或筛选条件后再试。' }}</p>
    </div>

    <footer class="list-foot">共 {{ total }} 条知识</footer>
  </aside>
</template>

<style scoped>
.knowledge-list-panel {
  min-height: 0;
  display: grid;
  grid-template-rows: auto auto auto auto minmax(0, 1fr) auto;
  gap: 14px;
  padding: 18px;
  border: 1px solid rgba(255, 255, 255, 0.7);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.88);
  box-shadow: 0 18px 44px rgba(31, 41, 55, 0.08);
  overflow: hidden;
}

.list-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.list-head h2 {
  margin: 0;
  font-size: 20px;
}

.list-total,
.list-foot {
  color: var(--muted);
  font-size: 12px;
  font-weight: 800;
}

.knowledge-search {
  min-height: 42px;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  align-items: center;
  padding: 0 14px;
  border: 1px solid var(--glass-border);
  border-radius: 16px;
  color: var(--muted);
  background: rgba(255, 255, 255, 0.56);
  box-shadow: 0 10px 26px rgba(31, 41, 55, 0.08);
  -webkit-backdrop-filter: blur(16px);
  backdrop-filter: blur(16px);
  transition:
    border-color 160ms ease,
    box-shadow 160ms ease,
    background 160ms ease;
}

.knowledge-search > span {
  display: none;
}

.knowledge-search:focus-within {
  border-color: rgba(255, 138, 61, 0.54);
  background: rgba(255, 255, 255, 0.78);
  box-shadow: 0 0 0 4px rgba(255, 138, 61, 0.14);
}

.knowledge-search input {
  min-width: 0;
  height: 40px;
  border: 0;
  outline: 0;
  padding: 0;
  color: var(--text);
  font-size: 14px;
  background: transparent;
}

.status-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.status-filters button {
  min-height: 34px;
  flex: 0 0 auto;
  border: 1px solid var(--glass-border);
  border-radius: 999px;
  padding: 0 13px;
  color: var(--muted);
  background: rgba(255, 255, 255, 0.52);
  box-shadow: 0 10px 26px rgba(31, 41, 55, 0.08);
  -webkit-backdrop-filter: blur(16px);
  backdrop-filter: blur(16px);
  transition:
    transform 160ms ease,
    border-color 160ms ease,
    background 160ms ease,
    color 160ms ease,
    box-shadow 160ms ease;
}

.status-filters button:hover {
  transform: translateY(-1px);
  border-color: rgba(255, 138, 61, 0.38);
  color: #c45009;
  background: rgba(255, 255, 255, 0.74);
  box-shadow: 0 14px 34px rgba(255, 107, 26, 0.12);
}

.status-filters button.active {
  color: #fff;
  border-color: rgba(255, 138, 61, 0.72);
  background: linear-gradient(135deg, var(--brand-orange), var(--brand-orange-deep));
  box-shadow: 0 16px 34px rgba(255, 107, 26, 0.24);
  font-weight: 900;
}

.select-filters {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 10px;
}

.select-filters label {
  display: grid;
  gap: 6px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 800;
}

.select-filters select {
  width: 100%;
  min-height: 38px;
  border: 1px solid var(--glass-border);
  border-radius: 14px;
  padding: 0 10px;
  color: var(--text);
  background: rgba(255, 255, 255, 0.56);
  box-shadow: 0 10px 26px rgba(31, 41, 55, 0.08);
  -webkit-backdrop-filter: blur(16px);
  backdrop-filter: blur(16px);
  transition:
    border-color 160ms ease,
    box-shadow 160ms ease,
    background 160ms ease;
}

.select-filters select:focus {
  border-color: rgba(255, 138, 61, 0.54);
  outline: none;
  background: rgba(255, 255, 255, 0.78);
  box-shadow: 0 0 0 4px rgba(255, 138, 61, 0.14);
}

.knowledge-items {
  min-height: 0;
  display: grid;
  align-content: start;
  gap: 10px;
  overflow: auto;
  padding-right: 4px;
  scrollbar-width: thin;
  scrollbar-color: rgba(255, 138, 61, 0.42) transparent;
}

.knowledge-items::-webkit-scrollbar {
  width: 6px;
}

.knowledge-items::-webkit-scrollbar-thumb {
  border-radius: 999px;
  background: rgba(255, 138, 61, 0.34);
}

.knowledge-item-card {
  width: 100%;
  min-height: 108px;
  display: grid;
  gap: 9px;
  padding: 13px 14px;
  border: 1px solid rgba(151, 170, 196, 0.16);
  border-radius: 18px;
  color: var(--text);
  background: rgba(255, 255, 255, 0.58);
  text-align: left;
  transition:
    transform 160ms ease,
    border-color 160ms ease,
    background 160ms ease,
    box-shadow 160ms ease;
}

.knowledge-item-card:hover {
  transform: translateY(-1px);
  border-color: rgba(255, 138, 61, 0.22);
  background: rgba(255, 255, 255, 0.78);
  box-shadow: 0 14px 32px rgba(31, 41, 55, 0.07);
}

.knowledge-item-card.active {
  border-color: rgba(255, 138, 61, 0.46);
  background:
    linear-gradient(135deg, rgba(255, 138, 61, 0.12), rgba(255, 255, 255, 0.74)),
    rgba(255, 255, 255, 0.82);
  box-shadow: 0 16px 36px rgba(255, 107, 26, 0.13);
}

.knowledge-item-card.failed {
  border-left-color: rgba(201, 66, 50, 0.52);
}

.item-main-row,
.item-foot-row {
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.item-main-row strong {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 15px;
}

.item-meta-row,
.item-foot-row {
  color: var(--muted);
  font-size: 12px;
}

.knowledge-empty {
  min-height: 220px;
  display: grid;
  place-items: center;
  align-content: center;
  gap: 8px;
  padding: 22px;
  border: 1px dashed rgba(151, 170, 196, 0.32);
  border-radius: 18px;
  color: var(--muted);
  text-align: center;
  background: rgba(255, 255, 255, 0.42);
}

.knowledge-empty strong {
  color: var(--text);
}

.knowledge-empty p {
  margin: 0;
}

@media (max-width: 720px) {
  .select-filters {
    grid-template-columns: 1fr;
  }
}

html[data-theme="dark"] .knowledge-list-panel {
  border-color: rgba(255, 255, 255, 0.12);
  background: rgba(17, 26, 39, 0.76);
  box-shadow: 0 20px 48px rgba(0, 0, 0, 0.32);
}

html[data-theme="dark"] .knowledge-search,
html[data-theme="dark"] .status-filters button,
html[data-theme="dark"] .select-filters select,
html[data-theme="dark"] .knowledge-item-card,
html[data-theme="dark"] .knowledge-empty {
  border-color: rgba(255, 255, 255, 0.12);
  background: rgba(9, 14, 22, 0.34);
}

html[data-theme="dark"] .knowledge-item-card:hover {
  border-color: rgba(255, 138, 61, 0.32);
  background: rgba(24, 36, 55, 0.72);
}

html[data-theme="dark"] .knowledge-item-card.active {
  border-color: rgba(255, 138, 61, 0.52);
  background:
    linear-gradient(135deg, rgba(255, 138, 61, 0.18), rgba(24, 36, 55, 0.72)),
    rgba(17, 26, 39, 0.82);
}

:global(html[data-theme="dark"]) .list-head h2,
:global(html[data-theme="dark"]) .knowledge-item-card,
:global(html[data-theme="dark"]) .item-main-row strong,
:global(html[data-theme="dark"]) .knowledge-empty strong,
:global(html[data-theme="dark"]) .knowledge-search input,
:global(html[data-theme="dark"]) .select-filters select {
  color: #f8fafc;
}

:global(html[data-theme="dark"]) .list-total,
:global(html[data-theme="dark"]) .list-foot,
:global(html[data-theme="dark"]) .knowledge-search,
:global(html[data-theme="dark"]) .select-filters label,
:global(html[data-theme="dark"]) .item-meta-row,
:global(html[data-theme="dark"]) .item-foot-row,
:global(html[data-theme="dark"]) .knowledge-empty {
  color: #cbd5e1;
}

:global(html[data-theme="dark"]) .status-filters button {
  color: #cbd5e1;
}

:global(html[data-theme="dark"]) .status-filters button.active {
  color: #ffad73;
}

:global(html[data-theme="dark"]) .knowledge-search input::placeholder {
  color: #94a3b8;
}

:global(html[data-theme="dark"]) .knowledge-search,
:global(html[data-theme="dark"]) .status-filters button,
:global(html[data-theme="dark"]) .select-filters select {
  border-color: var(--glass-border);
  color: var(--text);
  background: rgba(17, 26, 39, 0.62);
}

:global(html[data-theme="dark"]) .knowledge-search:focus-within,
:global(html[data-theme="dark"]) .status-filters button:hover,
:global(html[data-theme="dark"]) .select-filters select:focus {
  border-color: #3e5875;
  background: rgba(24, 36, 55, 0.72);
  box-shadow: 0 10px 24px rgba(0, 0, 0, 0.24);
}

:global(html[data-theme="dark"]) .knowledge-search:focus-within,
:global(html[data-theme="dark"]) .select-filters select:focus {
  box-shadow: 0 0 0 3px rgba(115, 169, 240, 0.16);
}

:global(html[data-theme="dark"]) .status-filters button.active {
  border-color: #ffad73;
  color: #101722;
  background: #ffad73;
  box-shadow: 0 16px 34px rgba(255, 173, 115, 0.18);
}

:global(html[data-theme="dark"]) .knowledge-search input::placeholder {
  color: #aebccd;
}
</style>
