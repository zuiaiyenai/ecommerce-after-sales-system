<script setup>
import { computed, inject, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import KnowledgeDetailPanel from '../components/KnowledgeDetailPanel.vue';
import KnowledgeDraftReviewPanel from '../components/KnowledgeDraftReviewPanel.vue';
import KnowledgeImportModal from '../components/KnowledgeImportModal.vue';
import KnowledgeListPanel from '../components/KnowledgeListPanel.vue';
import KnowledgeSummaryCards from '../components/KnowledgeSummaryCards.vue';
import {
  createKnowledgeFileImport, deleteKnowledgeLibrary, getKnowledgeDraft, getKnowledgeIngestionStatus,
  getKnowledgeLibraries, getKnowledgeMetadataOptions, publishKnowledgeDraft, retryKnowledgeIngestion,
  syncKnowledgeLibrary, updateKnowledgeDraft, updateKnowledgeDraftChunk, updateKnowledgeLibrary
} from '../api/adminConsole.js';
import { createLatestRequestGuard, normalizeDraft } from '../api/knowledgeDraft.js';
import { mergeKnowledgeRecord } from '../api/knowledgeRecord.js';

const shell = inject('adminShell', null);
const loading = ref(true);
const libraries = ref([]);
const selectedLibraryId = ref(null);
const searchKeyword = ref('');
const activeStatus = ref('ALL');
const activeCategory = ref('ALL');
const activeSource = ref('ALL');
const activeTab = ref('detail');
const errorMessage = ref('');
const showImportModal = ref(false);
const submitting = ref(false);
const actionLoading = ref('');
const draft = ref(null);
const draftLoading = ref(false);
const draftSaving = ref(false);
const publishing = ref(false);
const metadataOptions = reactive({ merchants: [], productCategories: [], scenes: [], intents: [] });
let statusPollTimer = null;
const statusRequestGuard = createLatestRequestGuard();

const importForm = reactive({ title: '', knowledgeType: 'faq', scope: 'MERCHANT', merchantCode: 'MERCHANT_DEMO', file: null });
const policyKnowledgeTypes = new Set(['after_sales_policy', 'refund_policy', 'exchange_rule']);
const terminalReviewStatuses = new Set(['REVIEW_REQUIRED', 'PUBLISHED', 'PARSE_FAILED', 'CLASSIFY_FAILED', 'EMBEDDING_FAILED']);
const statusOptions = [
  { key: 'ALL', label: '全部' }, { key: 'PROCESSING', label: '处理中' }, { key: 'REVIEW_REQUIRED', label: '待审核' },
  { key: 'PUBLISHING', label: '发布中' }, { key: 'PUBLISHED', label: '已发布' },
  { key: 'PARSE_FAILED', label: '解析失败' }, { key: 'CLASSIFY_FAILED', label: '分类失败' },
  { key: 'EMBEDDING_FAILED', label: '向量化失败' }, { key: 'DISABLED', label: '已停用' }
];
const categoryOptions = [
  { value: 'ALL', label: '全部分类' }, { value: 'faq', label: '常见问题' }, { value: 'after_sales_policy', label: '售后规则' },
  { value: 'refund_policy', label: '退款政策' }, { value: 'exchange_rule', label: '换货规则' }, { value: 'logistics_issue', label: '物流问题' },
  { value: 'evidence_requirement', label: '证据要求' }, { value: 'product_quality', label: '商品质量' }, { value: 'other', label: '其他' }
];
const sourceOptions = [{ value: 'ALL', label: '全部来源' }, { value: 'FILE', label: '文件上传' }, { value: 'TEXT', label: '历史文本导入' }];
const detailTabs = [{ key: 'detail', label: '内容详情' }, { key: 'chunks', label: '切片结果' }, { key: 'records', label: '处理记录' }, { key: 'scope', label: '使用范围' }];

const decoratedLibraries = computed(() => libraries.value.map((item) => ({
  ...item, displayStatus: getDisplayStatus(item), displayStatusLabel: displayStatusLabel(getDisplayStatus(item)),
  typeLabel: typeLabel(item.type), sourceLabel: item.ingestionSourceType === 'FILE' ? '文件上传' : '文本导入',
  scopeLabel: item.scope === 'GLOBAL' ? '全部商户' : '指定商户', updatedAtLabel: formatDate(item.updatedAt), createdAtLabel: formatDate(item.createdAt)
})));
const selectedLibrary = computed(() => decoratedLibraries.value.find((item) => item.id === selectedLibraryId.value) || null);
const showDraftReview = computed(() => selectedLibrary.value?.displayStatus === 'REVIEW_REQUIRED' && draft.value);
const filteredLibraries = computed(() => decoratedLibraries.value.filter((item) => {
  const keyword = searchKeyword.value.trim().toLowerCase();
  return (!keyword || [item.name, item.typeLabel, item.merchantCode, item.code].filter(Boolean).some((value) => String(value).toLowerCase().includes(keyword)))
    && (activeStatus.value === 'ALL' || item.displayStatus === activeStatus.value)
    && (activeCategory.value === 'ALL' || item.type === activeCategory.value)
    && (activeSource.value === 'ALL' || item.ingestionSourceType === activeSource.value);
}));
const summaryCards = computed(() => [
  { key: 'total', icon: '知', label: '知识条目总数', value: decoratedLibraries.value.length, desc: '已导入的售后知识内容', tone: 'orange' },
  { key: 'published', icon: '启', label: '已发布', value: decoratedLibraries.value.filter((item) => item.displayStatus === 'PUBLISHED').length, desc: '当前可用于检索的版本', tone: 'green' },
  { key: 'pending', icon: '审', label: '待处理', value: decoratedLibraries.value.filter((item) => ['PROCESSING', 'REVIEW_REQUIRED', 'PUBLISHING'].includes(item.displayStatus)).length, desc: '等待解析、审核或发布', tone: 'blue' },
  { key: 'failed', icon: '!', label: '处理失败', value: decoratedLibraries.value.filter((item) => item.displayStatus.endsWith('_FAILED')).length, desc: '可重新发起处理', tone: 'red' }
]);
const canSubmitImport = computed(() => Boolean(importForm.knowledgeType && importForm.file && (importForm.scope !== 'MERCHANT' || importForm.merchantCode.trim())));

watch(filteredLibraries, (items) => {
  if (items.length && !items.some((item) => item.id === selectedLibraryId.value)) selectedLibraryId.value = items[0].id;
});
watch(selectedLibraryId, async (id) => {
  clearStatusPoll();
  draft.value = null;
  if (!id) return;
  await refreshSelectedStatus(id);
  if (selectedLibraryId.value === id) startStatusPoll();
}, { flush: 'post' });

function getDisplayStatus(item) {
  if (item.status === 'DISABLED') return 'DISABLED';
  return item.reviewStatus || 'PUBLISHED';
}
function displayStatusLabel(status) { return statusOptions.find((item) => item.key === status)?.label || status; }
function typeLabel(value) { return categoryOptions.find((item) => item.value === value)?.label || value || '其他'; }
function formatDate(value) { return value ? String(value).replace('T', ' ').slice(0, 16) : '暂无时间'; }
function clearStatusPoll() {
  if (statusPollTimer) clearTimeout(statusPollTimer);
  statusPollTimer = null;
  statusRequestGuard.invalidate();
}
function updateLocalStatus(status) {
  libraries.value = libraries.value.map((item) => item.id === status.documentId
    ? mergeKnowledgeRecord(item, {
      ...item, reviewStatus: status.reviewStatus, revision: Number(status.revision || 0),
      publishedRevision: status.publishedRevision == null ? null : Number(status.publishedRevision), errorMessage: status.errorMessage || ''
    })
    : item);
}
function startStatusPoll(id = selectedLibraryId.value) {
  if (statusPollTimer) clearTimeout(statusPollTimer);
  statusPollTimer = null;
  const item = libraries.value.find((library) => library.id === id);
  if (selectedLibraryId.value !== id || !['PROCESSING', 'PUBLISHING'].includes(getDisplayStatus(item || {}))) return;
  statusPollTimer = setTimeout(async () => {
    statusPollTimer = null;
    await refreshSelectedStatus(id);
    if (selectedLibraryId.value === id) startStatusPoll(id);
  }, 2000);
}
async function loadMetadataOptions() {
  try {
    const options = await getKnowledgeMetadataOptions(importForm.merchantCode);
    metadataOptions.merchants = options.merchants || [];
    metadataOptions.productCategories = options.productCategories || [];
    metadataOptions.scenes = options.scenes || [];
    metadataOptions.intents = options.intents || [];
  } catch { Object.assign(metadataOptions, { merchants: [], productCategories: [], scenes: [], intents: [] }); }
}
async function loadPage() {
  loading.value = true; errorMessage.value = '';
  try {
    const result = await getKnowledgeLibraries();
    const currentById = new Map(libraries.value.map((item) => [item.id, item]));
    libraries.value = (result.records || []).map((item) => mergeKnowledgeRecord(currentById.get(item.id), item));
    if (!selectedLibraryId.value || !libraries.value.some((item) => item.id === selectedLibraryId.value)) selectedLibraryId.value = libraries.value[0]?.id || null;
  } catch (error) {
    libraries.value = []; selectedLibraryId.value = null; errorMessage.value = error?.message || '知识库接口请求失败，请稍后重试';
  } finally { loading.value = false; }
}
async function loadDraft(id = selectedLibraryId.value) {
  if (!id || selectedLibraryId.value !== id) return;
  draftLoading.value = true;
  try {
    const chunks = await getKnowledgeDraft(id);
    const item = selectedLibrary.value;
    if (selectedLibraryId.value === id) draft.value = normalizeDraft({ documentId: id, revision: item?.revision, chunks, policyVersion: item?.policyVersion || '', validFrom: item?.validFrom || '', validTo: item?.validTo || '' });
  } finally { draftLoading.value = false; }
}
async function refreshSelectedStatus(id = selectedLibraryId.value) {
  if (!id) return;
  const requestToken = statusRequestGuard.issue(id);
  try {
    const status = await getKnowledgeIngestionStatus(id);
    if (selectedLibraryId.value !== id || !statusRequestGuard.isCurrent(requestToken, id)) return;
    updateLocalStatus(status);
    if (status.reviewStatus === 'REVIEW_REQUIRED') await loadDraft(id);
    if (terminalReviewStatuses.has(status.reviewStatus)) clearStatusPoll();
  } catch (error) {
    if (selectedLibraryId.value === id && statusRequestGuard.isCurrent(requestToken, id)) {
      errorMessage.value = error?.message || '处理状态加载失败';
    }
  }
}
function resetImportForm() { Object.assign(importForm, { title: '', knowledgeType: 'faq', scope: 'MERCHANT', merchantCode: 'MERCHANT_DEMO', file: null }); }
async function openImport() { resetImportForm(); showImportModal.value = true; await loadMetadataOptions(); }
function closeImportModal() { showImportModal.value = false; }
function handleFileChange(event) { importForm.file = event.target.files?.[0] || null; }
function selectLibrary(item) { selectedLibraryId.value = item.id; activeTab.value = 'detail'; }
async function submitImport() {
  if (!canSubmitImport.value || submitting.value) return;
  submitting.value = true; errorMessage.value = '';
  try {
    const formData = new FormData();
    if (importForm.title.trim()) formData.append('title', importForm.title.trim());
    formData.append('knowledgeType', importForm.knowledgeType); formData.append('scope', importForm.scope);
    if (importForm.scope === 'MERCHANT') formData.append('merchantCode', importForm.merchantCode);
    formData.append('file', importForm.file);
    const response = await createKnowledgeFileImport(formData);
    closeImportModal(); await loadPage(); selectedLibraryId.value = String(response.documentId); shell?.setAction?.('文件已上传，正在生成 Draft');
  } catch (error) { errorMessage.value = error?.message || '文件上传失败，请稍后重试'; }
  finally { submitting.value = false; }
}
async function reloadDraftAfterConflict(error, documentId) {
  if (error?.status !== 409) return false;
  if (selectedLibraryId.value !== documentId) return true;
  errorMessage.value = '内容已被其他管理员更新，已重新加载 Draft';
  await refreshSelectedStatus(documentId);
  return true;
}
async function saveDraftChunk(payload) {
  if (!selectedLibrary.value || draftSaving.value) return;
  const documentId = selectedLibrary.value.id;
  draftSaving.value = true; errorMessage.value = '';
  try { await updateKnowledgeDraftChunk(documentId, payload.chunkId, payload); await refreshSelectedStatus(documentId); }
  catch (error) { if (!await reloadDraftAfterConflict(error, documentId) && selectedLibraryId.value === documentId) errorMessage.value = error?.message || '切片保存失败'; }
  finally { draftSaving.value = false; }
}
async function saveDraftPolicy(payload) {
  if (!selectedLibrary.value || draftSaving.value) return;
  const documentId = selectedLibrary.value.id;
  draftSaving.value = true; errorMessage.value = '';
  try {
    await updateKnowledgeDraft(documentId, payload);
    libraries.value = libraries.value.map((item) => item.id === documentId ? {
      ...item,
      policyVersion: payload.policyVersion,
      validFrom: payload.validFrom,
      validTo: payload.validTo
    } : item);
    await refreshSelectedStatus(documentId);
  }
  catch (error) { if (!await reloadDraftAfterConflict(error, documentId) && selectedLibraryId.value === documentId) errorMessage.value = error?.message || '政策信息保存失败'; }
  finally { draftSaving.value = false; }
}
async function publishDraft(expectedRevision) {
  if (!selectedLibrary.value || publishing.value) return;
  const documentId = selectedLibrary.value.id;
  publishing.value = true; errorMessage.value = '';
  try { await publishKnowledgeDraft(documentId, expectedRevision); await refreshSelectedStatus(documentId); if (selectedLibraryId.value === documentId) startStatusPoll(documentId); shell?.setAction?.('发布任务已启动'); }
  catch (error) { if (!await reloadDraftAfterConflict(error, documentId) && selectedLibraryId.value === documentId) errorMessage.value = error?.message || '发布失败'; }
  finally { publishing.value = false; }
}
async function retryIngestion() {
  if (!selectedLibrary.value || actionLoading.value) return;
  const documentId = selectedLibrary.value.id;
  actionLoading.value = 'retry'; errorMessage.value = '';
  try { const status = await retryKnowledgeIngestion(documentId); updateLocalStatus(status); if (selectedLibraryId.value === documentId) { draft.value = null; startStatusPoll(documentId); } shell?.setAction?.('已重新发起文件处理'); }
  catch (error) { if (selectedLibraryId.value === documentId) errorMessage.value = error?.message || '重新处理失败'; }
  finally { actionLoading.value = ''; }
}
async function syncIngestion() {
  if (!selectedLibrary.value || actionLoading.value) return;
  const documentId = selectedLibrary.value.id;
  actionLoading.value = 'sync'; errorMessage.value = '';
  try {
    await syncKnowledgeLibrary(documentId);
    await refreshSelectedStatus(documentId);
    if (selectedLibraryId.value === documentId) startStatusPoll(documentId);
    shell?.setAction?.('已重新发起文件处理');
  } catch (error) {
    if (selectedLibraryId.value === documentId) errorMessage.value = error?.message || '重新处理失败';
  } finally { actionLoading.value = ''; }
}
async function toggleEnabled(nextStatus) {
  if (!selectedLibrary.value) return;
  actionLoading.value = `status-${nextStatus}`;
  try { await updateKnowledgeLibrary(selectedLibrary.value.id, { title: selectedLibrary.value.name, merchantCode: selectedLibrary.value.merchantCode, status: nextStatus === 'ENABLED' ? 1 : 0 }); await loadPage(); }
  catch (error) { errorMessage.value = error?.message || '知识记录状态更新失败'; }
  finally { actionLoading.value = ''; }
}
async function removeLibrary() {
  if (!selectedLibrary.value || !window.confirm(`确认删除“${selectedLibrary.value.name}”？删除后不可恢复。`)) return;
  actionLoading.value = 'delete';
  try { await deleteKnowledgeLibrary(selectedLibrary.value.id); selectedLibraryId.value = null; await loadPage(); }
  catch (error) { errorMessage.value = error?.message || '知识记录删除失败'; }
  finally { actionLoading.value = ''; }
}

onMounted(() => { loadPage(); loadMetadataOptions(); });
onBeforeUnmount(clearStatusPoll);
</script>

<template>
  <section class="knowledge-management-page" :aria-busy="loading || draftLoading">
    <header class="knowledge-page-head">
      <div><span class="knowledge-breadcrumb">当前页面 / 知识治理</span><h1>知识库管理</h1><p>文件先解析为 Draft，再由管理员确认标签和发布版本。</p></div>
      <div class="knowledge-head-actions"><button type="button" class="primary-action compact" @click="openImport">上传文件</button><button type="button" class="ghost-mini" @click="loadPage">刷新列表</button></div>
    </header>
    <KnowledgeSummaryCards :cards="summaryCards" />
    <section class="knowledge-workbench">
      <KnowledgeListPanel v-model:search="searchKeyword" v-model:status="activeStatus" v-model:category="activeCategory" v-model:source="activeSource" :items="filteredLibraries" :selected-id="selectedLibraryId" :loading="loading" :error-message="errorMessage" :status-options="statusOptions" :category-options="categoryOptions" :source-options="sourceOptions" :total="decoratedLibraries.length" @select="selectLibrary" />
      <KnowledgeDraftReviewPanel v-if="showDraftReview" :draft="draft" :status="selectedLibrary.displayStatus" :saving="draftSaving" :publishing="publishing" :policy-document="policyKnowledgeTypes.has(selectedLibrary.type)" :label-options="{ productCategories: metadataOptions.productCategories, scenes: metadataOptions.scenes, intents: metadataOptions.intents }" @save-chunk="saveDraftChunk" @save-policy="saveDraftPolicy" @publish="publishDraft" @retry="retryIngestion" />
      <KnowledgeDetailPanel v-else-if="selectedLibrary" v-model:active-tab="activeTab" :item="selectedLibrary" :tabs="detailTabs" :action-loading="actionLoading" @retry="retryIngestion" @sync="syncIngestion" @enable="toggleEnabled('ENABLED')" @disable="toggleEnabled('DISABLED')" @delete="removeLibrary" />
      <article v-else class="knowledge-no-detail"><strong>请选择一条知识</strong><p>{{ loading ? '正在加载知识库内容。' : '列表为空时，可以先上传文件。' }}</p><button type="button" class="primary-action compact" @click="openImport">上传文件</button></article>
    </section>
    <KnowledgeImportModal :show="showImportModal" :form="importForm" :category-options="categoryOptions" :merchant-options="metadataOptions.merchants" :submitting="submitting" :can-submit="canSubmitImport" @close="closeImportModal" @submit="submitImport" @file-change="handleFileChange" />
  </section>
</template>

<style scoped>
.knowledge-management-page { min-height: 0; height: 100%; display: grid; grid-template-rows: auto auto minmax(0,1fr); gap: 16px; padding: 2px; overflow: hidden; }.knowledge-page-head, .knowledge-no-detail { border: 1px solid rgba(255,255,255,.7); border-radius: 22px; background: rgba(255,255,255,.84); box-shadow: 0 16px 38px rgba(31,41,55,.07); }.knowledge-page-head { display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 14px 18px; }.knowledge-breadcrumb { color: #bd560b; font-size: 12px; font-weight: 900; }.knowledge-page-head h1 { margin: 4px 0 0; font-size: 26px; }.knowledge-page-head p, .knowledge-no-detail p { margin: 6px 0 0; color: var(--muted); }.knowledge-head-actions { display: flex; gap: 10px; }.knowledge-workbench { min-height: 0; display: grid; grid-template-columns: minmax(320px,34fr) minmax(0,66fr); gap: 16px; overflow: hidden; }.knowledge-no-detail { display: grid; place-items: center; align-content: center; gap: 10px; padding: 22px; text-align: center; }
@media (max-width: 1100px) { .knowledge-management-page { height: auto; overflow: auto; }.knowledge-page-head { align-items: flex-start; flex-direction: column; }.knowledge-workbench { grid-template-columns: 1fr; overflow: visible; } }
html[data-theme="dark"] .knowledge-page-head, html[data-theme="dark"] .knowledge-no-detail { border-color: rgba(255,255,255,.12); background: rgba(17,26,39,.78); box-shadow: 0 20px 48px rgba(0,0,0,.32); }
</style>
