<script setup>
import { computed, inject, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { getAdminOverview, getAgentAccounts, getKnowledgeLibraries } from '../api/adminConsole';

const shell = inject('adminShell', null);
const router = useRouter();
const overview = ref(null);
const accounts = ref([]);
const knowledge = ref([]);
const loading = ref(true);
const activeTaskTab = ref('accounts');

const taskTabs = [
  { key: 'accounts', label: '账号审核' },
  { key: 'merchants', label: '商家绑定' },
  { key: 'knowledge', label: '知识库变更' }
];

const pendingAccountCount = computed(() => accounts.value.filter((item) => item.status === 'PENDING_APPROVAL').length);

const adminDisplayName = computed(() => {
  return shell?.admin?.value?.realName || overview.value?.greeting?.replace(/^您好，/, '') || '管理员';
});

const activeAccountCount = computed(() => accounts.value.filter((item) => item.status === 'ACTIVE').length);
const disabledAccountCount = computed(() => accounts.value.filter((item) => item.status === 'DISABLED').length);
const busyAccountCount = computed(() => accounts.value.filter((item) => item.onlineStatus === 'BUSY').length);
const unassignedMerchantCount = computed(() => accounts.value.filter((item) => !item.merchantCode).length);

const knowledgeMaintenanceCount = computed(() => {
  return knowledge.value.filter((item) => {
    return item.ingestionStatus === 'FAILED' || item.ingestionStatus === 'PROCESSING' || item.status === 'DISABLED';
  }).length;
});

const pendingTotal = computed(() => pendingAccountCount.value + unassignedMerchantCount.value + knowledgeMaintenanceCount.value);

const kpiCards = computed(() => [
  {
    icon: '审',
    label: '待审核客服',
    value: pendingAccountCount.value,
    desc: '注册申请 / 资料待确认'
  },
  {
    icon: '商',
    label: '商家待分配',
    value: unassignedMerchantCount.value,
    desc: '需要绑定负责客服'
  },
  {
    icon: '知',
    label: '知识库待维护',
    value: knowledgeMaintenanceCount.value,
    desc: '待审核词条 / 待更新 FAQ'
  },
  {
    icon: '库',
    label: '知识文档总量',
    value: knowledge.value.length,
    desc: '当前知识库记录'
  }
]);

const actionTasks = computed(() => {
  const tasks = [];
  if (pendingAccountCount.value > 0) {
    tasks.push({ tab: 'accounts', title: '客服账号注册申请待审核', desc: `${pendingAccountCount.value} 个申请需要核对资料与商家归属`, status: '待审核', action: '去审核', route: '/admin/accounts', tone: 'danger' });
  }
  if (unassignedMerchantCount.value > 0) {
    tasks.push({ tab: 'merchants', title: '客服账号尚未绑定商家', desc: `${unassignedMerchantCount.value} 个账号需要补充商家归属`, status: '待配置', action: '去分配', route: '/admin/accounts', tone: 'warning' });
  }
  if (knowledgeMaintenanceCount.value > 0) {
    tasks.push({ tab: 'knowledge', title: '知识库记录需要处理', desc: `${knowledgeMaintenanceCount.value} 条记录处于处理中、失败或停用状态`, status: '待处理', action: '去维护', route: '/admin/knowledge', tone: 'info' });
  }
  return tasks;
});

const visibleTasks = computed(() => {
  return actionTasks.value.filter((item) => item.tab === activeTaskTab.value);
});

const governanceFocus = computed(() => overview.value?.focus || []);

const accountStatusCards = computed(() => [
  { label: '已启用客服', value: activeAccountCount.value, desc: '可正常登录接待' },
  { label: '待审核客服', value: pendingAccountCount.value, desc: '注册资料待确认' },
  { label: '已停用客服', value: disabledAccountCount.value, desc: '权限已冻结' },
  { label: '忙碌客服', value: busyAccountCount.value, desc: '当前接待状态为忙碌' }
]);

async function loadPage() {
  loading.value = true;
  try {
    const [overviewData, accountPage, knowledgePage] = await Promise.all([
      getAdminOverview(),
      getAgentAccounts(),
      getKnowledgeLibraries()
    ]);
    overview.value = overviewData;
    accounts.value = accountPage.records || [];
    knowledge.value = knowledgePage.records || [];
  } finally {
    loading.value = false;
  }
}

function goTo(route) {
  router.push(route);
}

onMounted(loadPage);
</script>

<template>
  <section class="admin-dashboard-page" :aria-busy="loading">
    <article class="admin-hero-card">
      <div class="admin-hero-copy">
        <span class="eyebrow">Admin Console</span>
        <h2>你好，{{ adminDisplayName }}</h2>
        <p>统一管理客服账号、商家归属、知识库与系统配置</p>
      </div>
      <div class="admin-hero-actions">
        <button type="button" class="primary-action compact" @click="goTo('/admin/accounts')">新增客服账号</button>
        <button type="button" class="ghost-mini" @click="goTo('/admin/accounts')">商家分配</button>
        <button type="button" class="ghost-mini" @click="goTo('/admin/knowledge')">进入治理面板</button>
        <div class="admin-pending-pill">
          <span>待处理</span>
          <strong>{{ pendingTotal }}</strong>
        </div>
      </div>
    </article>

    <section class="admin-kpi-grid" aria-label="管理员核心指标">
      <article v-for="item in kpiCards" :key="item.label" class="admin-kpi-card">
        <span class="admin-kpi-icon">{{ item.icon }}</span>
        <div>
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
        </div>
        <p>{{ item.desc }}</p>
      </article>
    </section>

    <section class="admin-main-grid">
      <article class="admin-panel admin-task-panel">
        <header class="admin-panel-head">
          <div>
            <span class="eyebrow">Action Queue</span>
            <h2>待处理事项</h2>
          </div>
          <span class="admin-panel-count">{{ actionTasks.length }} 项</span>
        </header>

        <div class="admin-task-tabs" aria-label="待处理事项分类">
          <button
            v-for="tab in taskTabs"
            :key="tab.key"
            type="button"
            :class="{ active: activeTaskTab === tab.key }"
            @click="activeTaskTab = tab.key"
          >
            {{ tab.label }}
          </button>
        </div>

        <div class="admin-task-list">
          <article v-for="item in visibleTasks" :key="item.title" class="admin-task-row">
            <span :class="['admin-task-mark', item.tone]"></span>
            <div>
              <strong>{{ item.title }}</strong>
              <p>{{ item.desc }}</p>
            </div>
            <span :class="['admin-status-tag', item.tone]">{{ item.status }}</span>
            <button type="button" class="ghost-mini" @click="goTo(item.route)">{{ item.action }}</button>
          </article>
          <p v-if="!visibleTasks.length">当前分类暂无待处理事项</p>
        </div>
      </article>

      <article class="admin-panel admin-governance-panel">
        <header class="admin-panel-head">
          <div>
            <span class="eyebrow">Governance</span>
            <h2>系统治理状态</h2>
          </div>
        </header>

        <div class="admin-progress-list">
          <div v-for="item in governanceFocus" :key="item" class="admin-progress-item">
            <div>
              <span>{{ item }}</span>
            </div>
          </div>
        </div>

        <footer class="admin-governance-actions">
          <button type="button" class="primary-action compact" @click="goTo('/admin/knowledge')">查看配置详情</button>
        </footer>
      </article>
    </section>

    <section class="admin-secondary-grid">
      <article class="admin-panel">
        <header class="admin-panel-head">
          <div>
            <span class="eyebrow">Accounts</span>
            <h2>客服账号状态</h2>
          </div>
        </header>
        <div class="admin-account-status-grid">
          <div v-for="item in accountStatusCards" :key="item.label" class="admin-account-status-card">
            <span>{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
            <p>{{ item.desc }}</p>
          </div>
        </div>
      </article>

      <article class="admin-panel">
        <header class="admin-panel-head">
          <div>
            <span class="eyebrow">Audit Log</span>
            <h2>最近管理操作</h2>
          </div>
        </header>
        <div class="admin-log-list">
          <p>暂无可用的管理操作记录</p>
        </div>
      </article>
    </section>
  </section>
</template>
