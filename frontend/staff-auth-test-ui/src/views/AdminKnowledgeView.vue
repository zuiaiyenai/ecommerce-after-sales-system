<script setup>
import { computed, inject, onMounted, reactive, ref } from 'vue';
import EmptyState from '../components/EmptyState.vue';
import {
  createKnowledgeLibrary,
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

const form = reactive({
  code: '',
  name: '',
  type: 'faq',
  status: 'ENABLED',
  merchantCode: '',
  productCategory: '',
  scene: '',
  intent: '',
  policyVersion: 'v1.0',
  tags: '',
  description: ''
});

const filterOptions = [
  { key: 'ALL', label: '全部' },
  { key: 'ENABLED', label: '已启用' },
  { key: 'DISABLED', label: '已停用' }
];

const knowledgeTypeOptions = [
  { value: 'faq', label: '常见问题' },
  { value: 'after_sales_policy', label: '售后政策' },
  { value: 'product_knowledge', label: '商品知识' },
  { value: 'guideline', label: '操作指南' }
];

const sceneOptions = [
  { value: '', label: '未指定' },
  { value: 'damage', label: '破损问题' },
  { value: 'quality_issue', label: '质量问题' },
  { value: 'return', label: '退货场景' },
  { value: 'exchange', label: '换货场景' },
  { value: 'refund_request', label: '退款申请' },
  { value: 'shipping_issue', label: '物流问题' },
  { value: 'complaint', label: '投诉升级' }
];

const intentOptions = [
  { value: '', label: '未指定' },
  { value: 'refund', label: '退款' },
  { value: 'exchange', label: '换货' },
  { value: 'evidence_requirement', label: '补充凭证' },
  { value: 'policy_inquiry', label: '政策咨询' },
  { value: 'complaint_escalation', label: '投诉升级' },
  { value: 'return_guidance', label: '退货指引' }
];

const selectedLibrary = computed(() => {
  return libraries.value.find((item) => item.id === selectedLibraryId.value) || null;
});

const visibleLibraries = computed(() => {
  if (activeFilter.value === 'ALL') {
    return libraries.value;
  }
  return libraries.value.filter((item) => item.status === activeFilter.value);
});

const editorTitle = computed(() => {
  return selectedLibrary.value ? '编辑知识库目录' : '新建知识库目录';
});

function knowledgeTypeLabel(value) {
  return knowledgeTypeOptions.find((item) => item.value === value)?.label || value || '未分类';
}

function statusLabel(value) {
  return value === 'ENABLED' ? '已启用' : '已停用';
}

function shortText(value, limit = 22) {
  const text = String(value || '').trim();
  if (!text) {
    return '暂无说明';
  }
  return text.length > limit ? `${text.slice(0, limit)}...` : text;
}

async function loadPage() {
  loading.value = true;
  try {
    const data = await getKnowledgeLibraries();
    libraries.value = data.records || [];
    if (!selectedLibraryId.value && libraries.value.length) {
      selectLibrary(libraries.value[0]);
      return;
    }
    if (selectedLibraryId.value && !libraries.value.some((item) => item.id === selectedLibraryId.value)) {
      if (libraries.value.length) {
        selectLibrary(libraries.value[0]);
      } else {
        createLibraryDraft();
      }
    }
  } finally {
    loading.value = false;
  }
}

function selectLibrary(library) {
  selectedLibraryId.value = library.id;
  Object.assign(form, {
    code: library.code,
    name: library.name,
    type: library.type,
    status: library.status,
    merchantCode: library.merchantCode || '',
    productCategory: library.productCategory || '',
    scene: library.scene || '',
    intent: library.intent || '',
    policyVersion: library.policyVersion || 'v1.0',
    tags: library.tags || '',
    description: library.description || ''
  });
}

function createLibraryDraft() {
  selectedLibraryId.value = null;
  Object.assign(form, {
    code: '',
    name: '',
    type: 'faq',
    status: 'ENABLED',
    merchantCode: '',
    productCategory: '',
    scene: '',
    intent: '',
    policyVersion: 'v1.0',
    tags: '',
    description: ''
  });
}

async function saveLibrary() {
  if (!form.code || !form.name) {
    shell?.setAction?.('请先填写知识库编码和名称');
    return;
  }

  if (selectedLibraryId.value) {
    await updateKnowledgeLibrary(selectedLibraryId.value, { ...form });
    shell?.setAction?.('知识库目录已更新');
  } else {
    await createKnowledgeLibrary({ ...form });
    shell?.setAction?.('知识库目录已创建');
  }
  await loadPage();
}

async function deleteLibrary() {
  if (!selectedLibrary.value) {
    return;
  }
  await deleteKnowledgeLibrary(selectedLibrary.value.id);
  shell?.setAction?.('知识库目录已删除');
  selectedLibraryId.value = null;
  await loadPage();
}

async function triggerSync() {
  if (!selectedLibrary.value) {
    return;
  }
  const result = await syncKnowledgeLibrary(selectedLibrary.value.id);
  shell?.setAction?.(result.message || '知识库同步任务已触发');
}

onMounted(loadPage);
</script>

<template>
  <section class="admin-console-page">
    <aside class="admin-console-list">
      <div class="template-panel-head">
        <h2>知识库列表</h2>
        <button type="button" class="template-icon-button" aria-label="新建目录" @click="createLibraryDraft">+</button>
      </div>

      <div class="template-filter-tabs" aria-label="知识库筛选">
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
            <em>{{ item.code }}</em>
            <small>{{ shortText(knowledgeTypeLabel(item.type), 18) }}</small>
          </span>
          <span class="template-conversation-side">
            <time>{{ statusLabel(item.status) }}</time>
            <i v-if="item.status === 'ENABLED'" aria-hidden="true"></i>
          </span>
        </button>
      </div>
      <div v-else class="template-list-empty">
        {{ loading ? '正在加载知识库列表...' : '当前筛选下没有知识库目录' }}
      </div>

      <div class="template-list-foot">共 {{ visibleLibraries.length }} 个目录</div>
    </aside>

    <article class="admin-console-main">
      <header class="template-chat-head admin-console-head">
        <span class="template-user-avatar large">知</span>
        <div>
          <h2>{{ editorTitle }}</h2>
          <p>
            {{ selectedLibrary ? `当前正在编辑：${selectedLibrary.name} / ${selectedLibrary.code}` : '当前正在创建新的知识库目录' }}
          </p>
        </div>
        <span v-if="selectedLibrary" class="session-status processing">{{ statusLabel(selectedLibrary.status) }}</span>
      </header>

      <div class="admin-console-body">
        <section class="admin-console-hero">
          <div>
            <span class="eyebrow">知识文档编辑</span>
            <h3>右侧区域负责维护当前选中的知识库文档</h3>
            <p>这里直接维护向量知识库主表字段，包括编码、类型、商户、场景、意图、标签和正文内容。</p>
          </div>
          <div class="admin-editor-badges" v-if="selectedLibrary">
            <span class="tag">{{ knowledgeTypeLabel(selectedLibrary.type) }}</span>
            <span class="tag">{{ selectedLibrary.updatedAt }}</span>
          </div>
        </section>

        <section class="admin-console-form-card">
          <div class="admin-form-grid">
            <label class="admin-field">
              <span>编码</span>
              <input v-model.trim="form.code" placeholder="例如：faq_refund_rules_001" />
            </label>
            <label class="admin-field">
              <span>名称</span>
              <input v-model.trim="form.name" placeholder="请输入知识库名称" />
            </label>
            <label class="admin-field">
              <span>类型</span>
              <select v-model="form.type">
                <option v-for="item in knowledgeTypeOptions" :key="item.value" :value="item.value">
                  {{ item.label }}
                </option>
              </select>
            </label>
            <label class="admin-field">
              <span>状态</span>
              <select v-model="form.status">
                <option value="ENABLED">启用</option>
                <option value="DISABLED">停用</option>
              </select>
            </label>
            <label class="admin-field">
              <span>商户代码</span>
              <input v-model.trim="form.merchantCode" placeholder="例如：MERCHANT_DEMO" />
            </label>
            <label class="admin-field">
              <span>商品分类</span>
              <input v-model.trim="form.productCategory" placeholder="例如：数码配件、服饰箱包" />
            </label>
            <label class="admin-field">
              <span>场景</span>
              <select v-model="form.scene">
                <option v-for="item in sceneOptions" :key="item.value" :value="item.value">
                  {{ item.label }}
                </option>
              </select>
            </label>
            <label class="admin-field">
              <span>意图</span>
              <select v-model="form.intent">
                <option v-for="item in intentOptions" :key="item.value" :value="item.value">
                  {{ item.label }}
                </option>
              </select>
            </label>
            <label class="admin-field">
              <span>政策版本</span>
              <input v-model.trim="form.policyVersion" placeholder="例如：v1.0" />
            </label>
            <label class="admin-field">
              <span>标签</span>
              <input v-model.trim="form.tags" placeholder="用逗号分隔，例如：7天无理由、保修、退换货" />
            </label>
            <label class="admin-field admin-field-full">
              <span>正文内容</span>
              <textarea
                v-model="form.description"
                rows="6"
                placeholder="请输入知识库正文内容，检索切片和向量会基于这段内容生成"
              ></textarea>
            </label>
          </div>
        </section>

        <section class="admin-console-actions">
          <button type="button" class="primary-action compact" @click="saveLibrary">保存目录</button>
          <button v-if="selectedLibrary" type="button" class="ghost-mini" @click="triggerSync">触发同步接口</button>
          <button v-if="selectedLibrary" type="button" class="ghost-mini danger" @click="deleteLibrary">删除目录</button>
        </section>

        <EmptyState
          v-if="!libraries.length && !loading"
          title="知识库目录还没有建立"
          desc="先创建一个知识库目录，左侧列表就会开始承载后续的对象切换。"
          action="创建首个目录"
          @action="createLibraryDraft"
        />
      </div>
    </article>
  </section>
</template>
