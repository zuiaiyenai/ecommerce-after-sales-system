<script setup>
import { computed, ref, watch } from 'vue';
import KnowledgeStatusTag from './KnowledgeStatusTag.vue';

const props = defineProps({
  item: {
    type: Object,
    default: null
  },
  tabs: {
    type: Array,
    default: () => []
  },
  activeTab: {
    type: String,
    default: 'detail'
  },
  actionLoading: {
    type: String,
    default: ''
  }
});

const emit = defineEmits([
  'update:activeTab',
  'edit',
  'retry',
  'enable',
  'disable',
  'delete'
]);

const expanded = ref(false);
const moreOpen = ref(false);

watch(
  () => props.item?.id,
  () => {
    expanded.value = false;
    moreOpen.value = false;
  }
);

const rawContent = computed(() => props.item?.description || '暂无原始内容。');
const previewContent = computed(() => {
  if (expanded.value || rawContent.value.length <= 520) {
    return rawContent.value;
  }
  return `${rawContent.value.slice(0, 520)}...`;
});

const infoItems = computed(() => {
  if (!props.item) {
    return [];
  }
  return [
    { label: '标题', value: props.item.name },
    { label: '分类', value: props.item.typeLabel },
    { label: '来源类型', value: props.item.sourceLabel },
    { label: '适用范围', value: props.item.scopeLabel },
    { label: '商户代码', value: props.item.merchantCode || 'GLOBAL' },
    { label: 'Chunk 数', value: props.item.chunkCount || 0 }
  ];
});

const chunkPreview = computed(() => {
  if (!props.item) {
    return [];
  }
  const content = String(props.item.description || '').trim();
  if (!content) {
    return [];
  }
  const blocks = content
    .split(/\n{2,}|[。！？!?]\s*/)
    .map((part) => part.trim())
    .filter(Boolean);
  const targetCount = Math.max(Number(props.item.chunkCount || 0), 1);
  return Array.from({ length: Math.min(targetCount, Math.max(blocks.length, 1)) }, (_, index) => {
    const text = blocks[index] || blocks[0] || content;
    return {
      index: index + 1,
      text: text.length > 180 ? `${text.slice(0, 180)}...` : text
    };
  });
});

const processingRecords = computed(() => {
  if (!props.item) {
    return [];
  }
  const records = [
    {
      title: '知识条目创建',
      desc: `${props.item.sourceLabel} · ${props.item.createdAtLabel || '暂无时间'}`,
      tone: 'done'
    },
    {
      title: props.item.displayStatus === 'FAILED' ? '切片 / 向量化失败' : '切片 / 向量化处理',
      desc: props.item.errorMessage || `${props.item.chunkCount || 0} 个 chunks 已写入知识库`,
      tone: props.item.displayStatus === 'FAILED' ? 'failed' : props.item.displayStatus === 'PENDING' ? 'pending' : 'done'
    },
    {
      title: props.item.status === 'ENABLED' ? '发布到客服检索' : '从客服检索中停用',
      desc: `${props.item.updatedAtLabel || '暂无时间'} 更新`,
      tone: props.item.status === 'ENABLED' ? 'done' : 'muted'
    }
  ];
  return records;
});
</script>

<template>
  <article v-if="item" class="knowledge-detail-panel">
    <header class="detail-head">
      <span class="detail-mark">知</span>
      <div class="detail-title">
        <h2>{{ item.name }}</h2>
        <p>{{ item.typeLabel }} / {{ item.sourceLabel }} / {{ item.merchantCode || 'GLOBAL' }}</p>
      </div>
      <KnowledgeStatusTag :status="item.displayStatus" :label="item.displayStatusLabel" />
      <div class="more-wrap">
        <button type="button" class="more-button" aria-label="更多操作" @click="moreOpen = !moreOpen">···</button>
        <div v-if="moreOpen" class="more-menu">
          <button v-if="item.status === 'ENABLED'" type="button" @click="$emit('disable'); moreOpen = false">停用记录</button>
          <button v-else type="button" @click="$emit('enable'); moreOpen = false">启用记录</button>
          <button type="button" class="danger" @click="$emit('delete'); moreOpen = false">删除记录</button>
        </div>
      </div>
    </header>

    <nav class="detail-tabs" aria-label="知识详情标签">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        type="button"
        :class="{ active: activeTab === tab.key }"
        @click="$emit('update:activeTab', tab.key)"
      >
        {{ tab.label }}
      </button>
    </nav>

    <Transition name="tab-fade" mode="out-in">
      <section v-if="activeTab === 'detail'" key="detail" class="detail-scroll">
        <div class="info-card">
          <h3>基础信息</h3>
          <div class="info-grid">
            <div v-for="info in infoItems" :key="info.label">
              <span>{{ info.label }}</span>
              <strong>{{ info.value }}</strong>
            </div>
          </div>
        </div>

        <div class="content-card">
          <header>
            <h3>原始内容预览</h3>
            <button v-if="rawContent.length > 520" type="button" class="text-button" @click="expanded = !expanded">
              {{ expanded ? '收起' : '展开' }}
            </button>
          </header>
          <pre>{{ previewContent }}</pre>
        </div>

        <div class="detail-actions">
          <button type="button" class="primary-action compact" @click="$emit('edit')">编辑内容</button>
          <button type="button" class="ghost-mini" :disabled="actionLoading === 'sync'" @click="$emit('retry')">
            {{ actionLoading === 'sync' ? '重新处理中' : '重新处理' }}
          </button>
          <button
            v-if="item.status === 'ENABLED'"
            type="button"
            class="ghost-mini subtle"
            :disabled="actionLoading === 'status-DISABLED'"
            @click="$emit('disable')"
          >
            停用记录
          </button>
          <button
            v-else
            type="button"
            class="ghost-mini subtle"
            :disabled="actionLoading === 'status-ENABLED'"
            @click="$emit('enable')"
          >
            启用记录
          </button>
        </div>
      </section>

      <section v-else-if="activeTab === 'chunks'" key="chunks" class="detail-scroll">
        <div class="content-card">
          <header>
            <h3>切片结果</h3>
            <span>{{ item.chunkCount || 0 }} chunks</span>
          </header>
          <div v-if="chunkPreview.length" class="chunk-list">
            <article v-for="chunk in chunkPreview" :key="chunk.index" class="chunk-card">
              <span>#{{ chunk.index }}</span>
              <p>{{ chunk.text }}</p>
            </article>
          </div>
          <p v-else class="muted-line">暂无切片内容，可重新处理后再查看。</p>
        </div>
      </section>

      <section v-else-if="activeTab === 'records'" key="records" class="detail-scroll">
        <div class="content-card">
          <header>
            <h3>处理记录</h3>
            <button type="button" class="ghost-mini" :disabled="actionLoading === 'sync'" @click="$emit('retry')">
              {{ actionLoading === 'sync' ? '处理中' : '重新处理' }}
            </button>
          </header>
          <div class="record-list">
            <article v-for="record in processingRecords" :key="record.title" :class="['record-row', record.tone]">
              <span></span>
              <div>
                <strong>{{ record.title }}</strong>
                <p>{{ record.desc }}</p>
              </div>
            </article>
          </div>
        </div>
      </section>

      <section v-else key="scope" class="detail-scroll">
        <div class="content-card">
          <header>
            <h3>使用范围</h3>
            <KnowledgeStatusTag :status="item.displayStatus" :label="item.displayStatusLabel" />
          </header>
          <div class="scope-card">
            <span>{{ item.scope === 'GLOBAL' ? '全部商户可用' : '指定商户可用' }}</span>
            <strong>{{ item.merchantCode || 'GLOBAL' }}</strong>
            <p>启用后可被客服端与 Python Agent 按商户范围召回。停用只会隐藏检索，不删除历史内容。</p>
          </div>
        </div>
      </section>
    </Transition>
  </article>
</template>

<style scoped>
.knowledge-detail-panel {
  min-height: 0;
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
  border: 1px solid rgba(255, 255, 255, 0.7);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.88);
  box-shadow: 0 18px 44px rgba(31, 41, 55, 0.08);
  overflow: hidden;
}

.detail-head {
  min-height: 86px;
  display: grid;
  grid-template-columns: 48px minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 14px;
  padding: 18px 20px;
  border-bottom: 1px solid rgba(151, 170, 196, 0.14);
}

.detail-mark {
  width: 48px;
  height: 48px;
  display: grid;
  place-items: center;
  border-radius: 16px;
  color: #bd560b;
  background: rgba(255, 138, 61, 0.14);
  font-weight: 900;
}

.detail-title {
  min-width: 0;
}

.detail-title h2 {
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 22px;
}

.detail-title p {
  margin: 6px 0 0;
  color: var(--muted);
  font-size: 13px;
}

.more-wrap {
  position: relative;
}

.more-button {
  width: 38px;
  height: 38px;
  border: 1px solid rgba(151, 170, 196, 0.2);
  border-radius: 12px;
  color: var(--text);
  background: rgba(255, 255, 255, 0.62);
  font-weight: 900;
}

.more-menu {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  z-index: 10;
  width: 138px;
  display: grid;
  gap: 4px;
  padding: 8px;
  border: 1px solid rgba(151, 170, 196, 0.18);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 18px 42px rgba(31, 41, 55, 0.14);
}

.more-menu button {
  min-height: 34px;
  border: 0;
  border-radius: 10px;
  color: var(--text);
  background: transparent;
  text-align: left;
}

.more-menu button:hover {
  background: rgba(255, 138, 61, 0.1);
}

.more-menu .danger {
  color: var(--danger);
}

.detail-tabs {
  display: flex;
  gap: 8px;
  padding: 12px 20px;
  border-bottom: 1px solid rgba(151, 170, 196, 0.14);
}

.detail-tabs button {
  min-height: 36px;
  border: 1px solid rgba(151, 170, 196, 0.18);
  border-radius: 999px;
  padding: 0 14px;
  color: var(--muted);
  background: rgba(255, 255, 255, 0.56);
}

.detail-tabs button.active {
  color: #bd560b;
  border-color: rgba(255, 138, 61, 0.34);
  background: rgba(255, 138, 61, 0.12);
  font-weight: 900;
}

.detail-scroll {
  min-height: 0;
  display: grid;
  align-content: start;
  gap: 14px;
  padding: 18px 20px 20px;
  overflow: auto;
}

.info-card,
.content-card {
  border: 1px solid rgba(151, 170, 196, 0.15);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.64);
  box-shadow: 0 12px 28px rgba(31, 41, 55, 0.04);
}

.info-card {
  padding: 16px;
}

.info-card h3,
.content-card h3 {
  margin: 0;
  font-size: 16px;
}

.info-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: 14px;
}

.info-grid div {
  min-height: 66px;
  display: grid;
  align-content: center;
  gap: 6px;
  padding: 12px;
  border-radius: 14px;
  background: rgba(246, 248, 251, 0.74);
}

.info-grid span,
.content-card header span,
.muted-line,
.scope-card p,
.record-row p {
  color: var(--muted);
}

.info-grid span {
  font-size: 12px;
  font-weight: 800;
}

.info-grid strong {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.content-card {
  padding: 16px;
}

.content-card header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.text-button {
  border: 0;
  color: #bd560b;
  background: transparent;
  font-weight: 800;
}

pre {
  max-height: 360px;
  margin: 0;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  border: 1px solid rgba(151, 170, 196, 0.16);
  border-radius: 14px;
  padding: 14px;
  color: var(--text);
  background: rgba(246, 248, 251, 0.8);
  font: 13px/1.75 "Consolas", "Microsoft YaHei", monospace;
}

.detail-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.ghost-mini.subtle {
  color: var(--muted);
}

.chunk-list,
.record-list {
  display: grid;
  gap: 10px;
}

.chunk-card,
.record-row,
.scope-card {
  border: 1px solid rgba(151, 170, 196, 0.15);
  border-radius: 14px;
  padding: 13px;
  background: rgba(246, 248, 251, 0.68);
}

.chunk-card span {
  display: inline-flex;
  margin-bottom: 8px;
  color: #bd560b;
  font-size: 12px;
  font-weight: 900;
}

.chunk-card p,
.scope-card p,
.record-row p {
  margin: 0;
  line-height: 1.6;
}

.record-row {
  display: grid;
  grid-template-columns: 12px minmax(0, 1fr);
  gap: 12px;
}

.record-row > span {
  width: 10px;
  height: 10px;
  margin-top: 5px;
  border-radius: 999px;
  background: #37a667;
}

.record-row.failed > span {
  background: #c94232;
}

.record-row.pending > span {
  background: #3178c6;
}

.record-row.muted > span {
  background: #9aa4b2;
}

.scope-card {
  display: grid;
  gap: 8px;
}

.scope-card span {
  color: var(--muted);
  font-size: 12px;
  font-weight: 800;
}

.scope-card strong {
  font-size: 24px;
}

.tab-fade-enter-active,
.tab-fade-leave-active {
  transition: opacity 150ms ease, transform 150ms ease;
}

.tab-fade-enter-from,
.tab-fade-leave-to {
  opacity: 0;
  transform: translateY(4px);
}

@media (max-width: 720px) {
  .detail-head {
    grid-template-columns: 42px minmax(0, 1fr) auto;
  }

  .more-wrap {
    grid-column: 3;
  }

  .info-grid {
    grid-template-columns: 1fr;
  }

  .detail-tabs {
    overflow-x: auto;
  }
}

html[data-theme="dark"] .knowledge-detail-panel {
  border-color: rgba(255, 255, 255, 0.12);
  background: rgba(17, 26, 39, 0.76);
  box-shadow: 0 20px 48px rgba(0, 0, 0, 0.32);
}

html[data-theme="dark"] .detail-head,
html[data-theme="dark"] .detail-tabs {
  border-bottom-color: rgba(255, 255, 255, 0.1);
}

html[data-theme="dark"] .more-button,
html[data-theme="dark"] .detail-tabs button,
html[data-theme="dark"] .info-card,
html[data-theme="dark"] .content-card,
html[data-theme="dark"] .info-grid div,
html[data-theme="dark"] pre,
html[data-theme="dark"] .chunk-card,
html[data-theme="dark"] .record-row,
html[data-theme="dark"] .scope-card {
  border-color: rgba(255, 255, 255, 0.12);
  background: rgba(9, 14, 22, 0.34);
}

html[data-theme="dark"] .more-menu {
  border-color: rgba(255, 255, 255, 0.12);
  background: rgba(17, 26, 39, 0.96);
}

:global(html[data-theme="dark"]) .detail-title h2,
:global(html[data-theme="dark"]) .info-card h3,
:global(html[data-theme="dark"]) .content-card h3,
:global(html[data-theme="dark"]) .info-grid strong,
:global(html[data-theme="dark"]) pre,
:global(html[data-theme="dark"]) .chunk-card p,
:global(html[data-theme="dark"]) .record-row strong,
:global(html[data-theme="dark"]) .scope-card strong,
:global(html[data-theme="dark"]) .more-button,
:global(html[data-theme="dark"]) .more-menu button {
  color: #f8fafc;
}

:global(html[data-theme="dark"]) .detail-title p,
:global(html[data-theme="dark"]) .info-grid span,
:global(html[data-theme="dark"]) .content-card header span,
:global(html[data-theme="dark"]) .muted-line,
:global(html[data-theme="dark"]) .scope-card span,
:global(html[data-theme="dark"]) .scope-card p,
:global(html[data-theme="dark"]) .record-row p {
  color: #cbd5e1;
}

:global(html[data-theme="dark"]) .detail-tabs button {
  color: #cbd5e1;
}

:global(html[data-theme="dark"]) .detail-tabs button.active,
:global(html[data-theme="dark"]) .text-button,
:global(html[data-theme="dark"]) .chunk-card span {
  color: #ffad73;
}
</style>
