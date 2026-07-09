<script setup>
import { computed, inject, onMounted, reactive, ref } from 'vue';
import EmptyState from '../components/EmptyState.vue';
import {
  createKnowledgeFileImport,
  createKnowledgeTextImport,
  deleteKnowledgeLibrary,
  getKnowledgeLibraries,
  syncKnowledgeLibrary,
  updateKnowledgeLibrary
} from '../api/adminConsole';

const shell = inject('adminShell', null);
const loading = ref(true);
const libraries = ref([]);
const selectedLibraryId = ref(null);
const activeFilter = ref('ALL');
const importMode = ref('TEXT');
const showImportPanel = ref(false);
const submitting = ref(false);
const actionLoading = ref('');
const fileInput = ref(null);

const importForm = reactive({
  title: '',
  knowledgeType: 'faq',
  scope: 'MERCHANT',
  merchantCode: 'MERCHANT_DEMO',
  status: 'ENABLED',
  content: '',
  file: null
});

const filterOptions = [
  { key: 'ALL', label: '全部' },
  { key: 'PROCESSING', label: '处理中' },
  { key: 'SUCCESS', label: '成功' },
  { key: 'FAILED', label: '失败' },
  { key: 'DISABLED', label: '已停用' }
];

const knowledgeTypeOptions = [
  { value: 'faq', label: '常见问题' },
  { value: 'after_sales_policy', label: '售后政策' },
  { value: 'product_knowledge', label: '商品知识' },
  { value: 'guideline', label: '操作指南' }
];

const selectedLibrary = computed(() => {
  return libraries.value.find((item) => item.id === selectedLibraryId.value) || null;
});

const visibleLibraries = computed(() => {
  if (activeFilter.value === 'ALL') {
    return libraries.value;
  }
  if (activeFilter.value === 'DISABLED') {
    return libraries.value.filter((item) => item.status === 'DISABLED');
  }
  return libraries.value.filter((item) => item.ingestionStatus === activeFilter.value);
});

const enabledCount = computed(() => libraries.value.filter((item) => item.status === 'ENABLED').length);
const disabledCount = computed(() => libraries.value.filter((item) => item.status === 'DISABLED').length);
const processingCount = computed(() => libraries.value.filter((item) => item.ingestionStatus === 'PROCESSING').length);
const failedCount = computed(() => libraries.value.filter((item) => item.ingestionStatus === 'FAILED').length);

const canSubmitImport = computed(() => {
  if (!importForm.title || !importForm.knowledgeType) {
    return false;
  }
  if (importForm.scope === 'MERCHANT' && !importForm.merchantCode.trim()) {
    return false;
  }
  if (importMode.value === 'TEXT') {
    return Boolean(importForm.content.trim());
  }
  return Boolean(importForm.file);
});

const detailScopeLabel = computed(() => scopeLabel(selectedLibrary.value?.scope));

async function loadPage() {
  loading.value = true;
  try {
    const data = await getKnowledgeLibraries();
    libraries.value = data.records || [];

    if (!selectedLibraryId.value && libraries.value.length) {
      selectedLibraryId.value = libraries.value[0].id;
      return;
    }

    if (selectedLibraryId.value && !libraries.value.some((item) => item.id === selectedLibraryId.value)) {
      selectedLibraryId.value = libraries.value[0]?.id || null;
    }
  } finally {
    loading.value = false;
  }
}

function openImportPanel(mode) {
  importMode.value = mode;
  showImportPanel.value = true;
  importForm.title = '';
  importForm.knowledgeType = 'faq';
  importForm.scope = 'MERCHANT';
  importForm.merchantCode = 'MERCHANT_DEMO';
  importForm.status = 'ENABLED';
  importForm.content = '';
  importForm.file = null;
  if (fileInput.value) {
    fileInput.value.value = '';
  }
}

function closeImportPanel() {
  showImportPanel.value = false;
  importForm.file = null;
  importForm.content = '';
}

function handleFileChange(event) {
  importForm.file = event.target.files?.[0] || null;
}

function selectLibrary(library) {
  selectedLibraryId.value = library.id;
}

function typeLabel(value) {
  return knowledgeTypeOptions.find((item) => item.value === value)?.label || value || '未分类';
}

function statusLabel(value) {
  return value === 'ENABLED' ? '已启用' : '已停用';
}

function ingestionStatusLabel(value) {
  switch (value) {
    case 'PROCESSING':
      return '处理中';
    case 'FAILED':
      return '失败';
    case 'SUCCESS':
    default:
      return '成功';
  }
}

function ingestionStatusTone(value) {
  switch (value) {
    case 'PROCESSING':
      return 'processing';
    case 'FAILED':
      return 'danger';
    case 'SUCCESS':
    default:
      return 'completed';
  }
}

function sourceLabel(value) {
  return value === 'FILE' ? '文件导入' : '文本导入';
}

function scopeLabel(value) {
  return value === 'GLOBAL' ? '全局知识' : '指定商户';
}

function shortText(value, limit = 26) {
  const text = String(value || '').trim();
  if (!text) {
    return '暂无说明';
  }
  return text.length > limit ? `${text.slice(0, limit)}...` : text;
}

async function submitImport() {
  if (!canSubmitImport.value || submitting.value) {
    return;
  }

  submitting.value = true;
  try {
    if (importMode.value === 'TEXT') {
      await createKnowledgeTextImport({
        title: importForm.title,
        knowledgeType: importForm.knowledgeType,
        scope: importForm.scope,
        merchantCode: importForm.scope === 'MERCHANT' ? importForm.merchantCode : null,
        status: importForm.status,
        content: importForm.content
      });
    } else {
      const formData = new FormData();
      formData.append('title', importForm.title);
      formData.append('knowledgeType', importForm.knowledgeType);
      formData.append('scope', importForm.scope);
      formData.append('merchantCode', importForm.scope === 'MERCHANT' ? importForm.merchantCode : '');
      formData.append('status', importForm.status);
      formData.append('file', importForm.file);
      await createKnowledgeFileImport(formData);
    }

    shell?.setAction?.('知识导入任务已提交，后台正在处理中');
    closeImportPanel();
    await loadPage();
  } finally {
    submitting.value = false;
  }
}

async function toggleEnabled(nextStatus) {
  if (!selectedLibrary.value) {
    return;
  }
  actionLoading.value = `status-${nextStatus}`;
  try {
    await updateKnowledgeLibrary(selectedLibrary.value.id, {
      title: selectedLibrary.value.name,
      merchantCode: selectedLibrary.value.merchantCode,
      status: nextStatus === 'ENABLED' ? 1 : 0
    });
    shell?.setAction?.(nextStatus === 'ENABLED' ? '知识记录已启用' : '知识记录已停用');
    await loadPage();
  } finally {
    actionLoading.value = '';
  }
}

async function retrySync() {
  if (!selectedLibrary.value) {
    return;
  }
  actionLoading.value = 'sync';
  try {
    await syncKnowledgeLibrary(selectedLibrary.value.id);
    shell?.setAction?.('已触发重新处理任务');
    await loadPage();
  } finally {
    actionLoading.value = '';
  }
}

async function removeLibrary() {
  if (!selectedLibrary.value) {
    return;
  }
  actionLoading.value = 'delete';
  try {
    await deleteKnowledgeLibrary(selectedLibrary.value.id);
    shell?.setAction?.('知识记录已删除');
    selectedLibraryId.value = null;
    await loadPage();
  } finally {
    actionLoading.value = '';
  }
}

onMounted(loadPage);
</script>

<template>
  <section class="admin-console-page">
    <aside class="admin-console-list">
      <div class="template-panel-head">
        <h2>知识导入记录</h2>
        <button type="button" class="template-icon-button" aria-label="新建知识导入" @click="openImportPanel('TEXT')">+</button>
      </div>

      <div class="template-filter-tabs" aria-label="知识记录筛选">
        <button
          v-for="option in filterOptions"
          :key="option.key"
          type="button"
          :class="{ active: activeFilter === option.key }"
          @click="activeFilter = option.key"
        >
          {{ option.label }}
        </button>
      </div>

      <div v-if="visibleLibraries.length" class="template-conversation-list">
        <button
          v-for="item in visibleLibraries"
          :key="item.id"
          type="button"
          :class="['template-conversation-card', { active: item.id === selectedLibraryId }]"
          @click="selectLibrary(item)"
        >
          <span class="template-user-avatar">知</span>
          <span class="template-conversation-copy">
            <strong>{{ item.name }}</strong>
            <em>{{ typeLabel(item.type) }} / {{ sourceLabel(item.ingestionSourceType) }}</em>
            <small>{{ scopeLabel(item.scope) }} · {{ item.merchantCode || 'GLOBAL' }}</small>
            <small v-if="item.errorMessage">{{ shortText(item.errorMessage, 24) }}</small>
          </span>
          <span class="template-conversation-side">
            <time>{{ ingestionStatusLabel(item.ingestionStatus) }}</time>
            <i v-if="item.ingestionStatus === 'SUCCESS'" aria-hidden="true"></i>
          </span>
        </button>
      </div>
      <div v-else class="template-list-empty">
        {{ loading ? '正在加载知识导入记录...' : '当前筛选下没有知识记录' }}
      </div>

      <div class="template-list-foot">共 {{ visibleLibraries.length }} 条记录</div>
    </aside>

    <article class="admin-console-main">
      <template v-if="showImportPanel">
        <header class="template-chat-head admin-console-head">
          <span class="template-user-avatar large">{{ importMode === 'TEXT' ? '文' : '档' }}</span>
          <div>
            <h2>{{ importMode === 'TEXT' ? '新建文本导入' : '新建文件导入' }}</h2>
            <p>管理员只需要提供原始知识，后端会自动解析、切片并生成向量。</p>
          </div>
        </header>

        <div class="admin-console-body">
          <section class="admin-console-toolbar">
            <button type="button" class="primary-action compact" @click="submitImport" :disabled="!canSubmitImport || submitting">
              {{ submitting ? '提交中' : '提交导入' }}
            </button>
            <button type="button" class="ghost-mini" @click="openImportPanel('TEXT')">文本导入</button>
            <button type="button" class="ghost-mini" @click="openImportPanel('FILE')">文件上传</button>
            <button type="button" class="ghost-mini" @click="closeImportPanel">取消</button>
          </section>

          <section class="admin-console-form-card">
            <div class="admin-form-grid">
              <label class="admin-field">
                <span>标题</span>
                <input v-model.trim="importForm.title" placeholder="请输入知识标题" />
              </label>
              <label class="admin-field">
                <span>知识分类</span>
                <select v-model="importForm.knowledgeType">
                  <option v-for="item in knowledgeTypeOptions" :key="item.value" :value="item.value">
                    {{ item.label }}
                  </option>
                </select>
              </label>
              <label class="admin-field">
                <span>适用范围</span>
                <select v-model="importForm.scope">
                  <option value="MERCHANT">指定商户</option>
                  <option value="GLOBAL">全局知识</option>
                </select>
              </label>
              <label class="admin-field">
                <span>状态</span>
                <select v-model="importForm.status">
                  <option value="ENABLED">启用</option>
                  <option value="DISABLED">停用</option>
                </select>
              </label>
              <label v-if="importForm.scope === 'MERCHANT'" class="admin-field admin-field-full">
                <span>商户代码</span>
                <input v-model.trim="importForm.merchantCode" placeholder="请输入商户代码" />
              </label>
              <label v-if="importMode === 'TEXT'" class="admin-field admin-field-full">
                <span>原始文本</span>
                <textarea
                  v-model="importForm.content"
                  rows="12"
                  placeholder="在这里直接粘贴知识文本，系统会自动清洗、切片并生成向量。"
                ></textarea>
              </label>
              <label v-else class="admin-field admin-field-full">
                <span>上传文件</span>
                <input ref="fileInput" type="file" accept=".txt,.md" @change="handleFileChange" />
                <small class="muted">第一版仅支持 .txt 和 .md 文件。</small>
                <strong v-if="importForm.file">{{ importForm.file.name }}</strong>
              </label>
            </div>
          </section>
        </div>
      </template>

      <template v-else-if="selectedLibrary">
        <header class="template-chat-head admin-console-head">
          <span class="template-user-avatar large">知</span>
          <div>
            <h2>{{ selectedLibrary.name }}</h2>
            <p>{{ typeLabel(selectedLibrary.type) }} / {{ sourceLabel(selectedLibrary.ingestionSourceType) }} / {{ detailScopeLabel }}</p>
          </div>
          <span :class="['session-status', ingestionStatusTone(selectedLibrary.ingestionStatus)]">
            {{ ingestionStatusLabel(selectedLibrary.ingestionStatus) }}
          </span>
        </header>

        <div class="admin-console-body">
          <section class="admin-console-hero">
            <div>
              <span class="eyebrow">Import Detail</span>
              <h3>查看导入结果与处理状态</h3>
              <p>这里展示原始知识内容、切片结果、错误信息和管理动作，不再要求管理员手工维护底层知识对象字段。</p>
            </div>
            <div class="admin-editor-badges">
              <span class="tag">{{ selectedLibrary.fileName || sourceLabel(selectedLibrary.ingestionSourceType) }}</span>
              <span class="tag">{{ selectedLibrary.chunkCount || 0 }} chunks</span>
              <span class="tag">{{ statusLabel(selectedLibrary.status) }}</span>
            </div>
          </section>

          <section class="admin-console-metrics">
            <article class="admin-metric-card accent-orange">
              <span>Total Libraries</span>
              <strong>{{ libraries.length }}</strong>
            </article>
            <article class="admin-metric-card accent-green">
              <span>Enabled</span>
              <strong>{{ enabledCount }}</strong>
            </article>
            <article class="admin-metric-card accent-blue">
              <span>Processing</span>
              <strong>{{ processingCount }}</strong>
            </article>
            <article class="admin-metric-card accent-slate">
              <span>Failed</span>
              <strong>{{ failedCount }}</strong>
            </article>
          </section>

          <section class="admin-console-toolbar">
            <button type="button" class="primary-action compact" @click="openImportPanel('TEXT')">文本导入</button>
            <button type="button" class="ghost-mini" @click="openImportPanel('FILE')">文件上传</button>
            <button type="button" class="ghost-mini" @click="loadPage">刷新列表</button>
            <button type="button" class="ghost-mini" @click="retrySync" :disabled="actionLoading === 'sync'">
              {{ actionLoading === 'sync' ? '处理中' : '重新处理' }}
            </button>
          </section>

          <section class="admin-console-form-card">
            <div class="admin-form-grid">
              <div class="admin-field">
                <span>标题</span>
                <input :value="selectedLibrary.name" readonly />
              </div>
              <div class="admin-field">
                <span>分类</span>
                <input :value="typeLabel(selectedLibrary.type)" readonly />
              </div>
              <div class="admin-field">
                <span>来源类型</span>
                <input :value="sourceLabel(selectedLibrary.ingestionSourceType)" readonly />
              </div>
              <div class="admin-field">
                <span>适用范围</span>
                <input :value="detailScopeLabel" readonly />
              </div>
              <div class="admin-field">
                <span>商户代码</span>
                <input :value="selectedLibrary.merchantCode" readonly />
              </div>
              <div class="admin-field">
                <span>Chunk 数</span>
                <input :value="selectedLibrary.chunkCount || 0" readonly />
              </div>
              <div class="admin-field admin-field-full">
                <span>原始内容预览</span>
                <textarea :value="selectedLibrary.description" rows="10" readonly></textarea>
              </div>
              <div v-if="selectedLibrary.errorMessage" class="admin-field admin-field-full">
                <span>失败原因</span>
                <textarea :value="selectedLibrary.errorMessage" rows="4" readonly></textarea>
              </div>
            </div>
          </section>

          <section class="admin-console-actions">
            <button
              v-if="selectedLibrary.status === 'ENABLED'"
              type="button"
              class="ghost-mini danger"
              @click="toggleEnabled('DISABLED')"
              :disabled="actionLoading === 'status-DISABLED'"
            >
              停用记录
            </button>
            <button
              v-else
              type="button"
              class="ghost-mini"
              @click="toggleEnabled('ENABLED')"
              :disabled="actionLoading === 'status-ENABLED'"
            >
              启用记录
            </button>
            <button type="button" class="ghost-mini" @click="retrySync" :disabled="actionLoading === 'sync'">重新处理</button>
            <button type="button" class="ghost-mini danger" @click="removeLibrary" :disabled="actionLoading === 'delete'">删除记录</button>
          </section>
        </div>
      </template>

      <EmptyState
        v-else
        title="还没有知识导入记录"
        desc="从文本导入或文件上传开始创建第一条知识记录，后端会自动完成解析、切片和向量化。"
        action="新建文本导入"
        @action="openImportPanel('TEXT')"
      />
    </article>
  </section>
</template>
