<script setup>
const props = defineProps({
  show: Boolean,
  mode: {
    type: String,
    default: 'TEXT'
  },
  form: {
    type: Object,
    required: true
  },
  categoryOptions: {
    type: Array,
    default: () => []
  },
  submitting: Boolean,
  canSubmit: Boolean
});

const emit = defineEmits(['close', 'submit', 'file-change', 'switch-mode']);
</script>

<template>
  <Teleport to="body">
    <Transition name="modal-fade">
      <div v-if="show" class="knowledge-modal-backdrop" @click.self="$emit('close')">
        <section class="knowledge-import-modal" role="dialog" aria-modal="true">
          <header class="modal-head">
            <div>
              <span class="eyebrow">Knowledge Import</span>
              <h2>{{ mode === 'EDIT' ? '编辑知识内容' : mode === 'FILE' ? '文件上传' : '文本导入' }}</h2>
              <p>维护售后规则、FAQ、证据要求和商家专属知识。</p>
            </div>
            <button type="button" class="modal-close" aria-label="关闭" @click="$emit('close')">×</button>
          </header>

          <div v-if="mode !== 'EDIT'" class="modal-mode-tabs">
            <button type="button" :class="{ active: mode === 'TEXT' }" @click="$emit('switch-mode', 'TEXT')">文本导入</button>
            <button type="button" :class="{ active: mode === 'FILE' }" @click="$emit('switch-mode', 'FILE')">文件上传</button>
          </div>

          <form class="import-form" @submit.prevent="$emit('submit')">
            <label class="admin-field">
              <span>知识标题</span>
              <input v-model.trim="form.title" placeholder="例如：售后审核多久有结果" />
            </label>

            <label class="admin-field">
              <span>分类</span>
              <select v-model="form.knowledgeType" :disabled="mode === 'EDIT'">
                <option v-for="item in categoryOptions.filter((option) => option.value !== 'ALL')" :key="item.value" :value="item.value">
                  {{ item.label }}
                </option>
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
              <input v-model.trim="form.merchantCode" placeholder="MERCHANT_DEMO" />
            </label>

            <label class="admin-check">
              <input v-model="form.enabled" type="checkbox" />
              <span>{{ mode === 'EDIT' ? '保存后保持启用' : '导入后立即启用' }}</span>
            </label>

            <label v-if="mode === 'FILE'" class="upload-zone">
              <input type="file" accept=".txt,.md" @change="$emit('file-change', $event)" />
              <strong>{{ form.file?.name || '拖拽文件到此处，或点击选择文件' }}</strong>
              <span>支持 .txt / .md，保持现有上传接口能力</span>
            </label>

            <label v-else class="admin-field admin-field-full">
              <span>原始内容</span>
              <textarea v-model="form.content" rows="9" placeholder="粘贴售后知识内容，系统会在提交后进行清洗、切片与向量化。"></textarea>
            </label>

            <label v-if="mode === 'FILE'" class="admin-check">
              <input v-model="form.autoChunk" type="checkbox" />
              <span>自动切片</span>
            </label>

            <footer class="modal-actions">
              <button type="button" class="ghost-mini" @click="$emit('close')">取消</button>
              <button type="submit" class="primary-action compact" :disabled="!canSubmit || submitting">
                {{ submitting ? '提交中' : mode === 'EDIT' ? '保存并重新处理' : '提交导入' }}
              </button>
            </footer>
          </form>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.knowledge-modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(15, 23, 35, 0.38);
  -webkit-backdrop-filter: blur(10px);
  backdrop-filter: blur(10px);
}

.knowledge-import-modal {
  width: min(760px, 100%);
  max-height: min(780px, calc(100vh - 48px));
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.72);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 24px 70px rgba(31, 41, 55, 0.22);
}

.modal-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
  padding: 22px 24px 14px;
}

.modal-head h2 {
  margin: 0;
}

.modal-head p {
  margin: 8px 0 0;
  color: var(--muted);
}

.modal-close {
  width: 38px;
  height: 38px;
  border: 1px solid rgba(151, 170, 196, 0.2);
  border-radius: 12px;
  color: var(--text);
  background: rgba(255, 255, 255, 0.64);
  font-size: 22px;
}

.modal-mode-tabs {
  display: flex;
  gap: 8px;
  padding: 0 24px 14px;
}

.modal-mode-tabs button {
  min-height: 36px;
  border: 1px solid rgba(151, 170, 196, 0.2);
  border-radius: 999px;
  padding: 0 14px;
  color: var(--muted);
  background: rgba(255, 255, 255, 0.64);
}

.modal-mode-tabs button.active {
  color: #bd560b;
  border-color: rgba(255, 138, 61, 0.34);
  background: rgba(255, 138, 61, 0.12);
  font-weight: 900;
}

.import-form {
  min-height: 0;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px 16px;
  overflow: auto;
  padding: 0 24px 24px;
}

.admin-field {
  display: grid;
  gap: 8px;
}

.admin-field span,
.admin-check span {
  color: var(--muted);
  font-size: 13px;
  font-weight: 800;
}

.admin-field input,
.admin-field select,
.admin-field textarea {
  width: 100%;
  min-height: 44px;
  border: 1px solid rgba(151, 170, 196, 0.24);
  border-radius: 14px;
  padding: 0 13px;
  color: var(--text);
  background: rgba(255, 255, 255, 0.82);
}

.admin-field textarea {
  min-height: 170px;
  padding: 12px 13px;
  resize: vertical;
}

.admin-field input:focus,
.admin-field select:focus,
.admin-field textarea:focus {
  outline: none;
  border-color: rgba(255, 138, 61, 0.42);
  box-shadow: 0 0 0 4px rgba(255, 138, 61, 0.12);
}

.admin-field-full,
.upload-zone,
.modal-actions {
  grid-column: 1 / -1;
}

.admin-check {
  min-height: 44px;
  display: inline-flex;
  align-items: center;
  gap: 9px;
  padding: 0 12px;
  border: 1px solid rgba(151, 170, 196, 0.16);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.52);
}

.upload-zone {
  min-height: 148px;
  display: grid;
  place-items: center;
  align-content: center;
  gap: 8px;
  border: 1px dashed rgba(255, 138, 61, 0.42);
  border-radius: 18px;
  color: var(--muted);
  background:
    linear-gradient(135deg, rgba(255, 138, 61, 0.1), rgba(49, 120, 198, 0.04)),
    rgba(255, 255, 255, 0.58);
  cursor: pointer;
}

.upload-zone input {
  display: none;
}

.upload-zone strong {
  color: var(--text);
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding-top: 4px;
}

.modal-fade-enter-active,
.modal-fade-leave-active {
  transition: opacity 160ms ease;
}

.modal-fade-enter-from,
.modal-fade-leave-to {
  opacity: 0;
}

@media (max-width: 720px) {
  .import-form {
    grid-template-columns: 1fr;
  }
}

html[data-theme="dark"] .knowledge-modal-backdrop {
  background: rgba(2, 6, 14, 0.58);
}

html[data-theme="dark"] .knowledge-import-modal {
  border-color: rgba(255, 255, 255, 0.12);
  background: rgba(17, 26, 39, 0.96);
  box-shadow: 0 28px 78px rgba(0, 0, 0, 0.46);
}

html[data-theme="dark"] .modal-close,
html[data-theme="dark"] .modal-mode-tabs button,
html[data-theme="dark"] .admin-field input,
html[data-theme="dark"] .admin-field select,
html[data-theme="dark"] .admin-field textarea,
html[data-theme="dark"] .admin-check,
html[data-theme="dark"] .upload-zone {
  border-color: rgba(255, 255, 255, 0.12);
  background: rgba(9, 14, 22, 0.38);
}

:global(html[data-theme="dark"]) .modal-head h2,
:global(html[data-theme="dark"]) .modal-close,
:global(html[data-theme="dark"]) .admin-field input,
:global(html[data-theme="dark"]) .admin-field select,
:global(html[data-theme="dark"]) .admin-field textarea,
:global(html[data-theme="dark"]) .upload-zone strong {
  color: #f8fafc;
}

:global(html[data-theme="dark"]) .modal-head p,
:global(html[data-theme="dark"]) .modal-mode-tabs button,
:global(html[data-theme="dark"]) .admin-field span,
:global(html[data-theme="dark"]) .admin-check span,
:global(html[data-theme="dark"]) .upload-zone {
  color: #cbd5e1;
}

:global(html[data-theme="dark"]) .modal-mode-tabs button.active {
  color: #ffad73;
}

:global(html[data-theme="dark"]) .admin-field input::placeholder,
:global(html[data-theme="dark"]) .admin-field textarea::placeholder {
  color: #94a3b8;
}
</style>
