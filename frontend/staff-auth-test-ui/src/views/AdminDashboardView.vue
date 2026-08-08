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

const adminDashboardMock = {
  merchantPending: 3,
  todayOperations: 18,
  fallbackPendingAccounts: 6,
  fallbackKnowledgeMaintenance: 30,
  governanceProgress: [
    { label: '账号治理完成度', value: 75 },
    { label: '商家绑定完成度', value: 60 },
    { label: '知识库配置完成度', value: 45 },
    { label: '权限配置完成度', value: 80 }
  ],
  taskTabs: [
    { key: 'accounts', label: '账号审核' },
    { key: 'merchants', label: '商家绑定' },
    { key: 'security', label: '权限异常' },
    { key: 'knowledge', label: '知识库变更' }
  ],
  tasks: [
    {
      tab: 'accounts',
      title: '客服账号注册申请待审核',
      desc: '6 个注册申请需要核对资料与商家归属',
      status: '高优先级',
      action: '去审核',
      route: '/admin/accounts',
      tone: 'danger'
    },
    {
      tab: 'merchants',
      title: '商家“星选旗舰店”尚未绑定客服',
      desc: '新商家已完成入驻，需要分配负责客服与知识范围',
      status: '待配置',
      action: '去分配',
      route: '/admin/accounts',
      tone: 'warning'
    },
    {
      tab: 'knowledge',
      title: '知识库新增 30 条待审核内容',
      desc: 'FAQ 与售后政策词条等待管理员确认后启用',
      status: '待处理',
      action: '去维护',
      route: '/admin/knowledge',
      tone: 'info'
    },
    {
      tab: 'security',
      title: '管理员密码策略仍为默认配置',
      desc: '建议开启强密码规则与登录安全校验',
      status: '安全提醒',
      action: '去设置',
      route: '/admin/dashboard',
      tone: 'secure'
    }
  ],
  operations: [
    { type: '新增客服账号', operator: 'Platform Admin', time: '10:42', tag: '已记录' },
    { type: '修改商家绑定关系', operator: 'Platform Admin', time: '09:58', tag: '配置变更' },
    { type: '更新知识库分类', operator: 'Knowledge Admin', time: '09:24', tag: '待同步' },
    { type: '调整账号权限', operator: 'Platform Admin', time: '昨天 18:16', tag: '权限审计' },
    { type: '登录安全校验', operator: 'Security Bot', time: '昨天 17:48', tag: '正常' }
  ]
};

const pendingAccountCount = computed(() => {
  if (!accounts.value.length) {
    return adminDashboardMock.fallbackPendingAccounts;
  }
  return accounts.value.filter((item) => item.status === 'PENDING_APPROVAL').length;
});

const adminDisplayName = computed(() => {
  return shell?.admin?.value?.realName || overview.value?.adminName || 'Platform Admin';
});

const activeAccountCount = computed(() => accounts.value.filter((item) => item.status === 'ACTIVE').length);
const disabledAccountCount = computed(() => accounts.value.filter((item) => item.status === 'DISABLED').length);
const abnormalLoginCount = computed(() => accounts.value.filter((item) => item.onlineStatus === 'BUSY').length || 2);

const knowledgeMaintenanceCount = computed(() => {
  if (!knowledge.value.length) {
    return adminDashboardMock.fallbackKnowledgeMaintenance;
  }
  const attentionCount = knowledge.value.filter((item) => {
    return item.ingestionStatus === 'FAILED' || item.ingestionStatus === 'PROCESSING' || item.status === 'DISABLED';
  }).length;
  return attentionCount || adminDashboardMock.fallbackKnowledgeMaintenance;
});

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
    value: adminDashboardMock.merchantPending,
    desc: '需要绑定负责客服'
  },
  {
    icon: '知',
    label: '知识库待维护',
    value: knowledgeMaintenanceCount.value,
    desc: '待审核词条 / 待更新 FAQ'
  },
  {
    icon: '记',
    label: '今日治理操作',
    value: adminDashboardMock.todayOperations,
    desc: '账号、权限、配置变更记录'
  }
]);

const visibleTasks = computed(() => {
  return adminDashboardMock.tasks.filter((item) => item.tab === activeTaskTab.value);
});

const accountStatusCards = computed(() => [
  { label: '已启用客服', value: activeAccountCount.value || 12, desc: '可正常登录接待' },
  { label: '待审核客服', value: pendingAccountCount.value, desc: '注册资料待确认' },
  { label: '已停用客服', value: disabledAccountCount.value || 1, desc: '权限已冻结' },
  { label: '异常登录提醒', value: abnormalLoginCount.value, desc: '需复核登录状态' }
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
          <strong>6</strong>
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
          <span class="admin-panel-count">{{ adminDashboardMock.tasks.length }} 项</span>
        </header>

        <div class="admin-task-tabs" aria-label="待处理事项分类">
          <button
            v-for="tab in adminDashboardMock.taskTabs"
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
          <div v-for="item in adminDashboardMock.governanceProgress" :key="item.label" class="admin-progress-item">
            <div>
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}%</strong>
            </div>
            <span class="admin-progress-track">
              <i :style="{ width: `${item.value}%` }"></i>
            </span>
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
          <article v-for="item in adminDashboardMock.operations" :key="`${item.type}-${item.time}`" class="admin-log-row">
            <span class="admin-log-dot"></span>
            <div>
              <strong>{{ item.type }}</strong>
              <p>{{ item.operator }} · {{ item.time }}</p>
            </div>
            <span class="admin-status-tag info">{{ item.tag }}</span>
          </article>
        </div>
      </article>
    </section>
  </section>
</template>
