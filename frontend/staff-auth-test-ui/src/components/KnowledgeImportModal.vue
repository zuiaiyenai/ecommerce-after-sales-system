<script setup>
defineProps({
  show: Boolean,
  form: { type: Object, required: true },
  categoryOptions: { type: Array, default: () => [] },
  merchantOptions: { type: Array, default: () => [] },
  submitting: Boolean,
  canSubmit: Boolean
});

defineEmits(['close', 'submit', 'file-change']);
</script>

<template>
  <Teleport to="body">
    <Transition name="modal-fade">
      <div v-if="show" class="knowledge-modal-backdrop" @click.self="$emit('close')">
        <section class="knowledge-import-modal" role="dialog" aria-modal="true" aria-labelledby="knowledge-import-title">
          <header class="modal-head">
            <div>
              <span class="eyebrow">Knowledge Import</span>
              <h2 id="knowledge-import-title">文件上传</h2>
              <p>先上传文件，再在 Draft 审核阶段确认切片、标签和政策有效期。</p>
            </div>
            <button type="button" class="modal-close" aria-label="关闭" @click="$emit('close')">×</button>
          </header>

          <form class="import-form" @submit.prevent="$emit('submit')">
            <label class="admin-field">
              <span>知识标题</span>
              <input v-model.trim="form.title" placeholder="可选；留空时使用文件名" />
            </label>
            <label class="admin-field">
              <span>分类</span>
              <select v-model="form.knowledgeType">
                <option v-for="item in categoryOptions.filter((option) => option.value !== 'ALL')" :key="item.value" :value="item.value">{{ item.label }}</option>
              </select>
            </label>
            <label class="admin-field">
              <span>适用范围</span>
              <select v-model="form.scope">
                <option value="MERCHANT">指定商户</option>
                <option value="GLOBAL">全部商户</option>
              </select>
            </label>
            <label v-if="form.scope === 'MERCHANT'" class="admin-field">
              <span>商户代码</span>
              <select v-model="form.merchantCode">
                <option v-for="item in merchantOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
              </select>
            </label>
            <label class="upload-zone">
              <input type="file" accept=".pdf,.md,.txt,application/pdf,text/markdown,text/plain" @change="$emit('file-change', $event)" />
              <strong>{{ form.file?.name || '点击选择要上传的文件' }}</strong>
              <span>支持文本型 PDF、Markdown 和 TXT；扫描版 PDF 暂不支持 OCR</span>
            </label>
            <footer class="modal-actions">
              <button type="button" class="ghost-mini" @click="$emit('close')">取消</button>
              <button type="submit" class="primary-action compact" :disabled="!canSubmit || submitting">{{ submitting ? '提交中…' : '提交导入' }}</button>
            </footer>
          </form>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.knowledge-modal-backdrop { position: fixed; inset: 0; z-index: 80; display: grid; place-items: center; padding: 24px; background: rgba(15,23,35,.38); backdrop-filter: blur(10px); }
.knowledge-import-modal { width: min(640px,100%); padding: 22px; border: 1px solid rgba(148,163,184,.26); border-radius: 20px; background: #fff; box-shadow: 0 28px 78px rgba(15,23,42,.25); }
.modal-head, .modal-actions { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; }.modal-head h2 { margin: 4px 0; }.modal-head p { margin: 0; color: var(--muted); }.modal-close { border: 0; color: var(--muted); background: transparent; font-size: 26px; }
.import-form { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-top: 20px; }.admin-field { display: grid; gap: 6px; color: var(--muted); font-size: 13px; }.admin-field input, .admin-field select { min-height: 38px; border: 1px solid #cbd5e1; border-radius: 9px; padding: 8px 10px; color: var(--text); background: #fff; }.upload-zone { grid-column: 1 / -1; display: grid; place-items: center; gap: 7px; min-height: 130px; padding: 18px; border: 1px dashed #94a3b8; border-radius: 12px; color: var(--muted); text-align: center; }.upload-zone input { max-width: 100%; }.modal-actions { grid-column: 1 / -1; align-items: center; margin-top: 4px; }
@media (max-width: 620px) { .knowledge-modal-backdrop { padding: 12px; }.import-form { grid-template-columns: 1fr; }.knowledge-import-modal { padding: 18px; } }
html[data-theme="dark"] .knowledge-import-modal { border-color: rgba(255,255,255,.12); background: #111a27; } html[data-theme="dark"] .admin-field input, html[data-theme="dark"] .admin-field select { border-color: rgba(255,255,255,.16); color: #f8fafc; background: #182333; }
</style>
