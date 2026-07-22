<script setup>
import { computed, ref, watch } from 'vue';
import { hasUnsavedDraftChanges, normalizeDraft, validateDraftForPublish } from '../api/knowledgeDraft.js';

const props = defineProps({
  draft: { type: Object, required: true },
  status: { type: String, default: 'REVIEW_REQUIRED' },
  saving: Boolean,
  publishing: Boolean,
  policyDocument: Boolean,
  labelOptions: { type: Object, default: () => ({}) }
});

const emit = defineEmits(['save-chunk', 'save-policy', 'publish', 'retry']);
const editable = ref(normalizeDraft(props.draft));

watch(() => props.draft, (draft) => {
  editable.value = normalizeDraft(draft);
}, { deep: true });

const availableLabelOptions = computed(() => {
  const options = { productCategories: new Set(), scenes: new Set(), intents: new Set() };
  Object.entries(options).forEach(([field, values]) => {
    (props.labelOptions[field] || []).forEach((option) => values.add(String(option?.value ?? option)));
  });
  editable.value.chunks.forEach((chunk) => {
    Object.keys(options).forEach((field) => (chunk[field] || []).forEach((value) => options[field].add(value)));
  });
  return Object.fromEntries(Object.entries(options).map(([field, values]) => [field, [...values].sort()]));
});

const publishErrors = computed(() => {
  const errors = validateDraftForPublish(editable.value);
  if (hasUnsavedDraftChanges(props.draft, editable.value)) {
    errors.push('请先保存所有未提交的 Draft 修改');
  }
  return errors;
});

function saveChunk(chunk) {
  emit('save-chunk', {
    chunkId: chunk.chunkId,
    expectedRevision: editable.value.revision,
    productCategories: chunk.productCategories,
    scenes: chunk.scenes,
    intents: chunk.intents
  });
}

function confirmGeneric(chunk, field) {
  chunk[field] = [];
}

function savePolicy() {
  emit('save-policy', {
    expectedRevision: editable.value.revision,
    policyVersion: editable.value.policyVersion,
    validFrom: editable.value.validFrom,
    validTo: editable.value.validTo
  });
}
</script>

<template>
  <article class="draft-review-panel">
    <header class="draft-review-head">
      <div>
        <span class="eyebrow">Draft Review</span>
        <h2>确认切片与检索标签</h2>
        <p>AI 建议仅供审核；空数组表示已确认该标签为通用知识。</p>
      </div>
      <div class="draft-review-actions">
        <button v-if="status.endsWith('_FAILED')" type="button" class="ghost-mini" :disabled="saving" @click="$emit('retry')">重新处理</button>
        <button type="button" class="primary-action compact" :disabled="saving || publishing || publishErrors.length" @click="$emit('publish', editable.revision)">
          {{ publishing ? '发布中…' : '确认并发布' }}
        </button>
      </div>
    </header>

    <p v-if="publishErrors.length" class="draft-validation" role="alert">{{ publishErrors.join('；') }}</p>

    <section v-if="policyDocument" class="policy-editor">
      <h3>政策版本与有效期</h3>
      <label><span>政策版本</span><input v-model.trim="editable.policyVersion" placeholder="例如 v2026.07" /></label>
      <label><span>生效时间</span><input v-model="editable.validFrom" type="datetime-local" /></label>
      <label><span>失效时间</span><input v-model="editable.validTo" type="datetime-local" /></label>
      <button type="button" class="ghost-mini" :disabled="saving" @click="savePolicy">保存政策信息</button>
    </section>

    <ol class="draft-chunk-list">
      <li v-for="chunk in editable.chunks" :key="chunk.chunkId" class="draft-chunk-card">
        <header>
          <div>
            <strong>切片 {{ chunk.chunkIndex + 1 }}</strong>
            <span v-if="chunk.headingPath.length">{{ chunk.headingPath.join(' / ') }}</span>
            <span v-if="chunk.pageNumber">第 {{ chunk.pageNumber }} 页</span>
          </div>
          <small>{{ chunk.classificationSource || 'MANUAL' }} · 置信度 {{ chunk.confidence == null ? '—' : chunk.confidence }}</small>
        </header>
        <p class="chunk-excerpt">{{ chunk.text }}</p>
        <p v-if="chunk.reason" class="chunk-reason">建议依据：{{ chunk.reason }}</p>
        <div class="chunk-labels">
          <label v-for="([field, label]) in [['productCategories', '商品品类'], ['scenes', '售后场景'], ['intents', '处理意图']]" :key="field">
            <span>{{ label }}</span>
            <select v-model="chunk[field]" multiple :aria-label="label">
              <option v-for="option in availableLabelOptions[field]" :key="option" :value="option">{{ option }}</option>
            </select>
            <small v-if="chunk[field] === null">待确认</small>
            <small v-else-if="!chunk[field].length">已确认为通用</small>
            <button v-if="chunk[field] === null" type="button" class="confirm-generic" @click="confirmGeneric(chunk, field)">确认通用</button>
          </label>
        </div>
        <footer><button type="button" class="ghost-mini" :disabled="saving" @click="saveChunk(chunk)">保存该切片</button></footer>
      </li>
    </ol>
  </article>
</template>

<style scoped>
.draft-review-panel { min-height: 0; padding: 18px; border: 1px solid rgba(148, 163, 184, .22); border-radius: 18px; background: rgba(255,255,255,.92); overflow: auto; }
.draft-review-head, .draft-review-actions, .draft-chunk-card header, .draft-chunk-card header > div, .chunk-labels, .policy-editor { display: flex; gap: 12px; }
.draft-review-head { justify-content: space-between; align-items: flex-start; }
.draft-review-head h2 { margin: 4px 0; font-size: 20px; }.draft-review-head p, .chunk-reason { margin: 0; color: var(--muted); font-size: 13px; }
.draft-validation { padding: 10px 12px; border-radius: 10px; color: #9a3412; background: #fff7ed; }.policy-editor { flex-wrap: wrap; align-items: end; padding: 14px 0; border-bottom: 1px solid #e2e8f0; }.policy-editor h3 { width: 100%; margin: 0; }.policy-editor label, .chunk-labels label { display: grid; gap: 5px; color: var(--muted); font-size: 12px; }.policy-editor input, .chunk-labels select { min-height: 34px; border: 1px solid #cbd5e1; border-radius: 8px; padding: 6px; color: var(--text); background: white; }
.draft-chunk-list { display: grid; gap: 12px; margin: 16px 0 0; padding: 0; list-style: none; }.draft-chunk-card { padding: 14px; border: 1px solid #e2e8f0; border-radius: 12px; }.draft-chunk-card header { justify-content: space-between; }.draft-chunk-card header > div { flex-wrap: wrap; align-items: center; }.draft-chunk-card header span, .draft-chunk-card header small { color: var(--muted); font-size: 12px; }.chunk-excerpt { max-height: 7.2em; margin: 10px 0 6px; overflow: auto; white-space: pre-wrap; line-height: 1.5; }.chunk-labels { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); margin-top: 12px; }.chunk-labels select { min-height: 82px; }.confirm-generic { width: fit-content; padding: 0; border: 0; color: #2563eb; background: transparent; cursor: pointer; }.draft-chunk-card footer { display: flex; justify-content: end; margin-top: 10px; }
@media (max-width: 720px) { .draft-review-head, .draft-review-actions { align-items: stretch; flex-direction: column; }.chunk-labels { grid-template-columns: 1fr; }.draft-chunk-card header { align-items: flex-start; flex-direction: column; } }
html[data-theme="dark"] .draft-review-panel { border-color: rgba(255,255,255,.12); background: rgba(17,26,39,.9); } html[data-theme="dark"] .policy-editor input, html[data-theme="dark"] .chunk-labels select { border-color: rgba(255,255,255,.16); color: #f8fafc; background: #182333; } html[data-theme="dark"] .draft-chunk-card { border-color: rgba(255,255,255,.12); } html[data-theme="dark"] .draft-validation { color: #fed7aa; background: rgba(154,52,18,.25); }
</style>
