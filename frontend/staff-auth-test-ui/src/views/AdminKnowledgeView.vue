<script setup>
import { computed, inject, onMounted, reactive, ref, watch } from 'vue';
import KnowledgeDetailPanel from '../components/KnowledgeDetailPanel.vue';
import KnowledgeImportModal from '../components/KnowledgeImportModal.vue';
import KnowledgeListPanel from '../components/KnowledgeListPanel.vue';
import KnowledgeSummaryCards from '../components/KnowledgeSummaryCards.vue';
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
const searchKeyword = ref('');
const activeStatus = ref('ALL');
const activeCategory = ref('ALL');
const activeSource = ref('ALL');
const activeTab = ref('detail');
const importMode = ref('TEXT');
const showImportModal = ref(false);
const submitting = ref(false);
const actionLoading = ref('');
const showCreateMenu = ref(false);

const importForm = reactive({
  id: null,
  title: '',
  knowledgeType: 'faq',
  scope: 'MERCHANT',
  merchantCode: 'MERCHANT_DEMO',
  enabled: true,
  autoChunk: true,
  content: '',
  file: null
});

const statusOptions = [
  { key: 'ALL', label: '全部' },
  { key: 'ENABLED', label: '已启用' },
  { key: 'PENDING', label: '待处理' },
  { key: 'FAILED', label: '失败' },
  { key: 'DISABLED', label: '已停用' }
];

const categoryOptions = [
  { value: 'ALL', label: '全部分类' },
  { value: 'faq', label: '常见问题' },
  { value: 'after_sales_policy', label: '售后规则' },
  { value: 'refund_policy', label: '退款政策' },
  { value: 'exchange_rule', label: '换货规则' },
  { value: 'logistics_issue', label: '物流问题' },
  { value: 'evidence_requirement', label: '证据要求' },
  { value: 'product_quality', label: '商品质量' },
  { value: 'other', label: '其他' }
];

const sourceOptions = [
  { value: 'ALL', label: '全部来源' },
  { value: 'TEXT', label: '文本导入' },
  { value: 'FILE', label: '文件上传' }
];

const detailTabs = [
  { key: 'detail', label: '内容详情' },
  { key: 'chunks', label: '切片结果' },
  { key: 'records', label: '处理记录' },
  { key: 'scope', label: '使用范围' }
];

const fallbackKnowledgeRecords = [
  {
    id: 'mock-1',
    name: '售后审核多久有结果',
    type: 'faq',
    status: 'ENABLED',
    description: '用户提交售后申请后，平台会在 24 小时内完成首次审核。若凭证完整且符合规则，客服可直接通过审核；若凭证缺失，应引导用户补充商品照片、外包装照片或物流面单。',
    merchantCode: 'MERCHANT_DEMO',
    updatedAt: '2026-07-09T10:20:00',
    createdAt: '2026-07-08T16:40:00',
    chunkCount: 1,
    ingestionStatus: 'SUCCESS',
    ingestionSourceType: 'TEXT',
    scope: 'MERCHANT',
    errorMessage: ''
  },
  {
    id: 'mock-2',
    name: '破损商品证据要求',
    type: 'evidence_requirement',
    status: 'ENABLED',
    description: '商品破损类售后需至少提供商品破损特写、完整外包装照片和物流面单。客服需要确认照片清晰、损坏位置与用户描述一致，并在必要时要求补充视频说明。',
    merchantCode: 'GLOBAL',
    updatedAt: '2026-07-09T09:36:00',
    createdAt: '2026-07-07T13:22:00',
    chunkCount: 2,
    ingestionStatus: 'SUCCESS',
    ingestionSourceType: 'FILE',
    fileName: 'evidence-rules.md',
    scope: 'GLOBAL',
    errorMessage: ''
  },
  {
    id: 'mock-3',
    name: '退款到账时效说明',
    type: 'refund_policy',
    status: 'ENABLED',
    description: '退款审核通过后，原路退回通常在 1-3 个工作日到账。银行卡或第三方支付通道可能存在延迟，客服应根据订单支付方式说明预计到账时间。',
    merchantCode: 'MERCHANT_DEMO',
    updatedAt: '2026-07-08T18:12:00',
    createdAt: '2026-07-08T18:00:00',
    chunkCount: 1,
    ingestionStatus: 'PROCESSING',
    ingestionSourceType: 'TEXT',
    scope: 'MERCHANT',
    errorMessage: ''
  },
  {
    id: 'mock-4',
    name: '物流面单识别失败处理',
    type: 'logistics_issue',
    status: 'ENABLED',
    description: '当物流面单模糊或遮挡时，应要求用户重新拍摄完整面单，确保快递单号、收寄信息和条码清晰可见。',
    merchantCode: 'MERCHANT_DEMO',
    updatedAt: '2026-07-08T14:05:00',
    createdAt: '2026-07-08T13:40:00',
    chunkCount: 0,
    ingestionStatus: 'FAILED',
    ingestionSourceType: 'FILE',
    fileName: 'logistics.txt',
    scope: 'MERCHANT',
    errorMessage: '文件编码无法识别，请转换为 UTF-8 后重新上传。'
  }
];

const selectedLibrary = computed(() => {
  return decoratedLibraries.value.find((item) => item.id === selectedLibraryId.value) || null;
});

const decoratedLibraries = computed(() => {
  return libraries.value.map((item) => decorateKnowledge(item));
});

const filteredLibraries = computed(() => {
  const keyword = searchKeyword.value.trim().toLowerCase();
  return decoratedLibraries.value.filter((item) => {
    const matchesKeyword =
      !keyword ||
      [item.name, item.typeLabel, item.merchantCode, item.code]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(keyword));
    const matchesStatus = activeStatus.value === 'ALL' || item.displayStatus === activeStatus.value;
    const matchesCategory = activeCategory.value === 'ALL' || item.type === activeCategory.value;
    const matchesSource = activeSource.value === 'ALL' || item.ingestionSourceType === activeSource.value;
    return matchesKeyword && matchesStatus && matchesCategory && matchesSource;
  });
});

const summaryCards = computed(() => {
  const total = decoratedLibraries.value.length;
  const enabled = decoratedLibraries.value.filter((item) => item.displayStatus === 'ENABLED').length;
  const pending = decoratedLibraries.value.filter((item) => item.displayStatus === 'PENDING').length;
  const failed = decoratedLibraries.value.filter((item) => item.displayStatus === 'FAILED').length;
  return [
    { key: 'total', icon: '知', label: '知识条目总数', value: total, desc: '已导入的售后知识内容', tone: 'orange' },
    { key: 'enabled', icon: '启', label: '已启用', value: enabled, desc: '当前可被客服端使用', tone: 'green' },
    { key: 'pending', icon: '审', label: '待处理', value: pending, desc: '等待切片 / 审核 / 发布', tone: 'blue' },
    { key: 'failed', icon: '!', label: '处理失败', value: failed, desc: '需要重新处理或修复', tone: 'red' }
  ];
});

const canSubmitImport = computed(() => {
  if (!importForm.title.trim() || !importForm.knowledgeType) {
    return false;
  }
  if (importForm.scope === 'MERCHANT' && !importForm.merchantCode.trim()) {
    return false;
  }
  if (importMode.value === 'FILE') {
    return Boolean(importForm.file);
  }
  return Boolean(importForm.content.trim());
});

watch(filteredLibraries, (items) => {
  if (!items.length) {
    return;
  }
  if (!items.some((item) => item.id === selectedLibraryId.value)) {
    selectedLibraryId.value = items[0].id;
  }
});

async function loadPage() {
  loading.value = true;
  try {
    const data = await getKnowledgeLibraries();
    libraries.value = data.records || [];
  } catch (error) {
    libraries.value = fallbackKnowledgeRecords;
    shell?.setAction?.('知识库接口暂不可用，已展示本地演示数据');
  } finally {
    if (!selectedLibraryId.value && libraries.value.length) {
      selectedLibraryId.value = libraries.value[0].id;
    }
    if (selectedLibraryId.value && !libraries.value.some((item) => item.id === selectedLibraryId.value)) {
      selectedLibraryId.value = libraries.value[0]?.id || null;
    }
    loading.value = false;
  }
}

function decorateKnowledge(item) {
  const displayStatus = getDisplayStatus(item);
  return {
    ...item,
    displayStatus,
    displayStatusLabel: displayStatusLabel(displayStatus),
    typeLabel: typeLabel(item.type),
    sourceLabel: sourceLabel(item.ingestionSourceType),
    scopeLabel: scopeLabel(item.scope),
    updatedAtLabel: formatDate(item.updatedAt),
    createdAtLabel: formatDate(item.createdAt)
  };
}

function getDisplayStatus(item) {
  if (item.status === 'DISABLED') {
    return 'DISABLED';
  }
  if (item.ingestionStatus === 'FAILED') {
    return 'FAILED';
  }
  if (item.ingestionStatus === 'PROCESSING') {
    return 'PENDING';
  }
  return 'ENABLED';
}

function displayStatusLabel(value) {
  return statusOptions.find((item) => item.key === value)?.label || value;
}

function typeLabel(value) {
  return categoryOptions.find((item) => item.value === value)?.label || value || '其他';
}

function sourceLabel(value) {
  return value === 'FILE' ? '文件上传' : '文本导入';
}

function scopeLabel(value) {
  return value === 'GLOBAL' ? '全部商户' : '指定商户';
}

function formatDate(value) {
  if (!value) {
    return '暂无时间';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value).slice(0, 10);
  }
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function pad(value) {
  return String(value).padStart(2, '0');
}

function resetImportForm() {
  importForm.id = null;
  importForm.title = '';
  importForm.knowledgeType = 'faq';
  importForm.scope = 'MERCHANT';
  importForm.merchantCode = 'MERCHANT_DEMO';
  importForm.enabled = true;
  importForm.autoChunk = true;
  importForm.content = '';
  importForm.file = null;
}

function openImport(mode) {
  resetImportForm();
  importMode.value = mode;
  showCreateMenu.value = false;
  showImportModal.value = true;
}

function openEdit() {
  if (!selectedLibrary.value) {
    return;
  }
  importMode.value = 'EDIT';
  importForm.id = selectedLibrary.value.id;
  importForm.title = selectedLibrary.value.name || '';
  importForm.knowledgeType = selectedLibrary.value.type || 'faq';
  importForm.scope = selectedLibrary.value.scope || 'MERCHANT';
  importForm.merchantCode = selectedLibrary.value.merchantCode || 'MERCHANT_DEMO';
  importForm.enabled = selectedLibrary.value.status === 'ENABLED';
  importForm.autoChunk = true;
  importForm.content = selectedLibrary.value.description || '';
  importForm.file = null;
  showImportModal.value = true;
}

function closeImportModal() {
  showImportModal.value = false;
}

function handleFileChange(event) {
  importForm.file = event.target.files?.[0] || null;
}

function selectLibrary(item) {
  selectedLibraryId.value = item.id;
  activeTab.value = 'detail';
}

async function submitImport() {
  if (!canSubmitImport.value || submitting.value) {
    return;
  }
  submitting.value = true;
  try {
    if (importMode.value === 'EDIT') {
      await updateKnowledgeLibrary(importForm.id, {
        title: importForm.title,
        merchantCode: importForm.scope === 'MERCHANT' ? importForm.merchantCode : 'GLOBAL',
        status: importForm.enabled ? 1 : 0,
        content: importForm.content
      });
      shell?.setAction?.('知识内容已保存，并进入重新处理流程');
    } else if (importMode.value === 'TEXT') {
      await createKnowledgeTextImport({
        title: importForm.title,
        knowledgeType: importForm.knowledgeType,
        scope: importForm.scope,
        merchantCode: importForm.scope === 'MERCHANT' ? importForm.merchantCode : null,
        status: importForm.enabled ? 'ENABLED' : 'DISABLED',
        content: importForm.content
      });
      shell?.setAction?.('文本知识导入任务已提交');
    } else {
      const formData = new FormData();
      formData.append('title', importForm.title);
      formData.append('knowledgeType', importForm.knowledgeType);
      formData.append('scope', importForm.scope);
      formData.append('merchantCode', importForm.scope === 'MERCHANT' ? importForm.merchantCode : '');
      formData.append('status', importForm.enabled ? 'ENABLED' : 'DISABLED');
      formData.append('file', importForm.file);
      await createKnowledgeFileImport(formData);
      shell?.setAction?.('文件知识导入任务已提交');
    }
    closeImportModal();
    await loadPage();
    await shell?.refreshShell?.();
  } finally {
    submitting.value = false;
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

async function removeLibrary() {
  if (!selectedLibrary.value) {
    return;
  }
  const confirmed = window.confirm(`确认删除“${selectedLibrary.value.name}”？删除后不可恢复。`);
  if (!confirmed) {
    return;
  }
  actionLoading.value = 'delete';
  try {
    await deleteKnowledgeLibrary(selectedLibrary.value.id);
    shell?.setAction?.('知识记录已删除');
    selectedLibraryId.value = null;
    await loadPage();
    await shell?.refreshShell?.();
  } finally {
    actionLoading.value = '';
  }
}

onMounted(loadPage);
</script>

<template>
  <section class="knowledge-management-page" :aria-busy="loading">
    <header class="knowledge-page-head">
      <div>
        <span class="knowledge-breadcrumb">当前页面 / 知识治理</span>
        <h1>知识库管理</h1>
        <p>统一维护售后规则、常见问题、证据要求与商家专属知识</p>
      </div>

      <div class="knowledge-head-actions">
        <div class="create-menu-wrap">
          <button type="button" class="primary-action compact" @click="showCreateMenu = !showCreateMenu">新增知识</button>
          <div v-if="showCreateMenu" class="create-menu">
            <button type="button" @click="openImport('TEXT')">文本导入</button>
            <button type="button" @click="openImport('FILE')">文件上传</button>
          </div>
        </div>
        <button type="button" class="ghost-mini" @click="loadPage">刷新列表</button>
      </div>
    </header>

    <KnowledgeSummaryCards :cards="summaryCards" />

    <section class="knowledge-workbench">
      <KnowledgeListPanel
        v-model:search="searchKeyword"
        v-model:status="activeStatus"
        v-model:category="activeCategory"
        v-model:source="activeSource"
        :items="filteredLibraries"
        :selected-id="selectedLibraryId"
        :loading="loading"
        :status-options="statusOptions"
        :category-options="categoryOptions"
        :source-options="sourceOptions"
        :total="decoratedLibraries.length"
        @select="selectLibrary"
      />

      <KnowledgeDetailPanel
        v-if="selectedLibrary"
        v-model:active-tab="activeTab"
        :item="selectedLibrary"
        :tabs="detailTabs"
        :action-loading="actionLoading"
        @edit="openEdit"
        @retry="retrySync"
        @enable="toggleEnabled('ENABLED')"
        @disable="toggleEnabled('DISABLED')"
        @delete="removeLibrary"
      />

      <article v-else class="knowledge-no-detail">
        <strong>请选择一条知识</strong>
        <p>{{ loading ? '正在加载知识库内容。' : '左侧列表为空时，可以通过新增知识开始导入。' }}</p>
        <button type="button" class="primary-action compact" @click="openImport('TEXT')">文本导入</button>
      </article>
    </section>

    <KnowledgeImportModal
      :show="showImportModal"
      :mode="importMode"
      :form="importForm"
      :category-options="categoryOptions"
      :submitting="submitting"
      :can-submit="canSubmitImport"
      @close="closeImportModal"
      @submit="submitImport"
      @file-change="handleFileChange"
      @switch-mode="openImport"
    />
  </section>
</template>

<style scoped>
.knowledge-management-page {
  min-height: 0;
  height: 100%;
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
  gap: 16px;
  padding: 2px;
  overflow: hidden;
}

.knowledge-management-page::before {
  content: "";
  position: fixed;
  inset: 0;
  z-index: -1;
  background:
    radial-gradient(circle at 72% 12%, rgba(255, 138, 61, 0.13), transparent 28%),
    linear-gradient(135deg, #f3f6fa, #eef3f8 48%, #f8fafc);
  pointer-events: none;
}

.knowledge-page-head {
  min-height: 82px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 14px 18px;
  border: 1px solid rgba(255, 255, 255, 0.7);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.82);
  box-shadow: 0 16px 38px rgba(31, 41, 55, 0.07);
}

.knowledge-breadcrumb {
  color: #bd560b;
  font-size: 12px;
  font-weight: 900;
}

.knowledge-page-head h1 {
  margin: 4px 0 0;
  font-size: 26px;
  line-height: 1.12;
}

.knowledge-page-head p {
  margin: 6px 0 0;
  color: var(--muted);
}

.knowledge-head-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.create-menu-wrap {
  position: relative;
}

.create-menu {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  z-index: 20;
  width: 142px;
  display: grid;
  gap: 4px;
  padding: 8px;
  border: 1px solid rgba(151, 170, 196, 0.18);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 18px 42px rgba(31, 41, 55, 0.14);
}

.create-menu button {
  min-height: 36px;
  border: 0;
  border-radius: 10px;
  color: var(--text);
  background: transparent;
  text-align: left;
}

.create-menu button:hover {
  background: rgba(255, 138, 61, 0.1);
}

.knowledge-workbench {
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(320px, 34fr) minmax(0, 66fr);
  gap: 16px;
  overflow: hidden;
}

.knowledge-no-detail {
  min-height: 0;
  display: grid;
  place-items: center;
  align-content: center;
  gap: 10px;
  padding: 22px;
  border: 1px solid rgba(255, 255, 255, 0.7);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.88);
  box-shadow: 0 18px 44px rgba(31, 41, 55, 0.08);
  text-align: center;
}

.knowledge-no-detail p {
  margin: 0;
  color: var(--muted);
}

@media (max-width: 1100px) {
  .knowledge-management-page {
    height: auto;
    overflow: auto;
  }

  .knowledge-page-head {
    align-items: flex-start;
    flex-direction: column;
  }

  .knowledge-workbench {
    grid-template-columns: 1fr;
    overflow: visible;
  }
}

html[data-theme="dark"] .knowledge-management-page::before {
  background:
    radial-gradient(circle at 74% 10%, rgba(255, 138, 61, 0.12), transparent 28%),
    linear-gradient(135deg, #0b1018, #101722 48%, #151d29);
}

html[data-theme="dark"] .knowledge-page-head,
html[data-theme="dark"] .knowledge-no-detail {
  border-color: rgba(255, 255, 255, 0.12);
  background: rgba(17, 26, 39, 0.76);
  box-shadow: 0 20px 48px rgba(0, 0, 0, 0.32);
}

html[data-theme="dark"] .create-menu {
  border-color: rgba(255, 255, 255, 0.12);
  background: rgba(17, 26, 39, 0.96);
}

:global(html[data-theme="dark"]) .knowledge-page-head h1,
:global(html[data-theme="dark"]) .knowledge-no-detail strong,
:global(html[data-theme="dark"]) .create-menu button {
  color: #f8fafc;
}

:global(html[data-theme="dark"]) .knowledge-page-head p,
:global(html[data-theme="dark"]) .knowledge-no-detail p {
  color: #cbd5e1;
}

:global(html[data-theme="dark"]) .knowledge-breadcrumb {
  color: #ffad73;
}
</style>
