<script setup>
import { computed, inject, onMounted, reactive, ref, watch } from 'vue';
import EmptyState from '../components/EmptyState.vue';
import {
  createAgentAccount,
  getAgentAccounts,
  resetAgentPassword,
  updateAgentAccount
} from '../api/adminConsole';

const shell = inject('adminShell', null);
const loading = ref(true);
const saveLoading = ref(false);
const moreOpen = ref(false);
const isCreating = ref(false);
const activeFilter = ref('ALL');
const activeTab = ref('basic');
const searchKeyword = ref('');
const accounts = ref([]);
const selectedAccountId = ref(null);
const formSnapshot = ref('');
const hasUnsavedChanges = ref(false);
const confirmBusy = ref(false);

const form = reactive({
  account: '',
  realName: '',
  merchantCode: '',
  phone: '',
  role: 'CUSTOMER_SERVICE',
  status: 'ACTIVE',
  maxSessionCount: 8,
  knowledgeScope: '',
  note: ''
});

const confirmation = reactive({
  show: false,
  title: '',
  message: '',
  confirmText: '',
  danger: false,
  run: null
});

const filterOptions = [
  { key: 'ALL', label: '全部' },
  { key: 'PENDING_APPROVAL', label: '待审批' },
  { key: 'ACTIVE', label: '启用中' },
  { key: 'DISABLED', label: '已停用' },
  { key: 'ONLINE', label: '在线' },
  { key: 'OFFLINE', label: '离线' }
];

const detailTabs = [
  { key: 'basic', label: '基础信息' },
  { key: 'service', label: '接待配置' },
  { key: 'knowledge', label: '知识权限' },
  { key: 'security', label: '安全设置' },
  { key: 'logs', label: '操作日志' }
];

const baseOperationLogs = [
  { id: 'log-1', action: '管理员修改账号信息', operator: 'Platform Admin', time: '今天 10:42', status: '已记录' },
  { id: 'log-2', action: '调整商家归属', operator: 'Platform Admin', time: '今天 09:58', status: '配置变更' },
  { id: 'log-3', action: '修改接待上限', operator: 'Service Admin', time: '昨天 18:16', status: '已生效' },
  { id: 'log-4', action: '重置密码', operator: 'Security Admin', time: '昨天 17:48', status: '安全操作' },
  { id: 'log-5', action: '停用 / 启用账号', operator: 'Platform Admin', time: '06-28 14:21', status: '权限审计' }
];

const selectedAccount = computed(() => {
  return accounts.value.find((item) => sameId(item.id, selectedAccountId.value)) || null;
});

const pageModeTitle = computed(() => {
  if (isCreating.value) return '新建客服账号';
  if (selectedAccount.value) return '账号治理详情';
  return '请选择客服账号';
});

const visibleAccounts = computed(() => {
  const keyword = searchKeyword.value.trim().toLowerCase();

  return accounts.value.filter((item) => {
    const statusMatched =
      activeFilter.value === 'ALL' ||
      item.status === activeFilter.value ||
      item.onlineStatus === activeFilter.value;

    if (!statusMatched) {
      return false;
    }

    if (!keyword) {
      return true;
    }

    return [item.realName, item.account, item.merchantCode, item.phone, item.knowledgeScope]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(keyword));
  });
});

const accountStats = computed(() => {
  const totalAccounts = accounts.value.length;
  const pendingApproval = accounts.value.filter((item) => item.status === 'PENDING_APPROVAL').length;
  const activeAccounts = accounts.value.filter((item) => item.status === 'ACTIVE').length;
  const currentSessions = accounts.value.reduce((sum, item) => sum + toNumber(item.currentSessionCount), 0);
  const maxSessions = accounts.value.reduce((sum, item) => sum + toNumber(item.maxSessionCount), 0);

  return {
    totalAccounts,
    pendingApproval,
    activeAccounts,
    sessionCapacity: `${currentSessions}/${maxSessions || 0}`
  };
});

const kpiCards = computed(() => [
  {
    key: 'total',
    icon: 'CS',
    tone: 'orange',
    label: '客服总数',
    value: accountStats.value.totalAccounts,
    desc: '当前已创建客服账号'
  },
  {
    key: 'pending',
    icon: 'AP',
    tone: 'blue',
    label: '待审批账号',
    value: accountStats.value.pendingApproval,
    desc: '等待管理员审核注册申请'
  },
  {
    key: 'active',
    icon: 'ON',
    tone: 'green',
    label: '启用账号',
    value: accountStats.value.activeAccounts,
    desc: '当前可登录并接待用户'
  },
  {
    key: 'capacity',
    icon: 'LC',
    tone: 'slate',
    label: '平均接待上限',
    value: accountStats.value.sessionCapacity,
    desc: '当前在线接待量 / 最大接待能力'
  }
]);

const enabledCount = computed(() => accounts.value.filter((item) => item.status === 'ACTIVE').length);

const currentSessionText = computed(() => {
  const source = selectedAccount.value;
  return `${toNumber(source?.currentSessionCount)}/${toNumber(source?.maxSessionCount)}`;
});

const allowNewSession = computed(() => {
  return form.status === 'ACTIVE' && toNumber(selectedAccount.value?.currentSessionCount) < toNumber(form.maxSessionCount);
});

const knowledgeItems = computed(() => [
  {
    label: '可访问知识库范围',
    value: form.knowledgeScope || form.merchantCode || 'MERCHANT_DEMO',
    enabled: true
  },
  {
    label: '所属商家知识库',
    value: form.merchantCode || '未绑定商家',
    enabled: Boolean(form.merchantCode)
  },
  {
    label: '通用知识库',
    value: '售后政策 / FAQ / 服务规则',
    enabled: true
  },
  {
    label: '允许使用敏感规则',
    value: '仅允许读取命中结果，不允许外泄规则细节',
    enabled: false
  },
  {
    label: '允许查看证据审核规则',
    value: '图片证据、退款规则与售后时效',
    enabled: true
  }
]);

const securityFacts = computed(() => [
  { label: '最近登录时间', value: displayTime(selectedAccount.value?.lastLoginTime) },
  { label: '登录设备数量', value: selectedAccount.value ? '1 台' : '--' },
  { label: '登录异常提醒', value: selectedAccount.value?.onlineStatus === 'BUSY' ? '关注忙碌状态' : '未发现异常' }
]);

const operationLogs = computed(() => {
  const prefix = selectedAccount.value?.realName || form.realName || '当前账号';
  return baseOperationLogs.map((item) => ({
    ...item,
    action: `${item.action}：${prefix}`
  }));
});

watch(
  form,
  () => {
    hasUnsavedChanges.value = Boolean(isCreating.value || selectedAccount.value) && serializeForm() !== formSnapshot.value;
  },
  { deep: true }
);

async function loadPage() {
  loading.value = true;
  try {
    const page = await getAgentAccounts();
    accounts.value = page.records || [];

    if (selectedAccountId.value && accounts.value.some((item) => sameId(item.id, selectedAccountId.value))) {
      const current = accounts.value.find((item) => sameId(item.id, selectedAccountId.value));
      selectAccount(current);
      return;
    }

    if (accounts.value.length) {
      selectAccount(accounts.value[0]);
    } else {
      clearSelection();
    }
  } catch (error) {
    shell?.setAction?.(error.message || '客服账号列表加载失败');
  } finally {
    loading.value = false;
  }
}

function selectAccount(account) {
  if (!account) return;
  selectedAccountId.value = account.id;
  isCreating.value = false;
  activeTab.value = 'basic';
  moreOpen.value = false;
  Object.assign(form, {
    account: account.account || '',
    realName: account.realName || '',
    merchantCode: account.merchantCode || '',
    phone: account.phone || '',
    role: account.role || 'CUSTOMER_SERVICE',
    status: account.status || 'ACTIVE',
    maxSessionCount: toNumber(account.maxSessionCount) || 8,
    knowledgeScope: account.knowledgeScope || account.merchantCode || '',
    note: account.note || ''
  });
  syncSnapshot();
}

function createNewAccountDraft() {
  selectedAccountId.value = null;
  isCreating.value = true;
  activeTab.value = 'basic';
  moreOpen.value = false;
  Object.assign(form, {
    account: '',
    realName: '',
    merchantCode: '',
    phone: '',
    role: 'CUSTOMER_SERVICE',
    status: 'ACTIVE',
    maxSessionCount: 8,
    knowledgeScope: '',
    note: ''
  });
  syncSnapshot();
}

function clearSelection() {
  selectedAccountId.value = null;
  isCreating.value = false;
  activeTab.value = 'basic';
  Object.assign(form, {
    account: '',
    realName: '',
    merchantCode: '',
    phone: '',
    role: 'CUSTOMER_SERVICE',
    status: 'ACTIVE',
    maxSessionCount: 8,
    knowledgeScope: '',
    note: ''
  });
  syncSnapshot();
}

async function saveAccount() {
  if (!form.account || !form.realName || !form.merchantCode) {
    shell?.setAction?.('请先填写账号、姓名和所属商家');
    return;
  }

  saveLoading.value = true;
  try {
    if (selectedAccount.value) {
      await updateAgentAccount(selectedAccount.value.id, buildPayload());
      shell?.setAction?.('客服账号已保存');
    } else {
      const created = await createAgentAccount(buildPayload());
      selectedAccountId.value = created.id;
      shell?.setAction?.(`已创建客服账号：${created.account}`);
    }

    await loadPage();
    shell?.refreshShell?.();
  } finally {
    saveLoading.value = false;
  }
}

function cancelChanges() {
  if (selectedAccount.value) {
    selectAccount(selectedAccount.value);
    shell?.setAction?.('已撤销未保存更改');
    return;
  }

  if (isCreating.value) {
    createNewAccountDraft();
    shell?.setAction?.('已重置新建账号草稿');
  }
}

async function approveSelectedAccount() {
  if (!selectedAccount.value) return;
  await updateSelectedStatus('ACTIVE', '注册申请已审核通过');
}

function requestResetPassword() {
  if (!selectedAccount.value) return;
  openConfirm({
    title: '确认重置密码',
    message: `将为 ${displayName(selectedAccount.value)} 生成临时密码。该操作会影响客服下一次登录，请确认已完成身份核验。`,
    confirmText: '确认重置',
    danger: false,
    run: async () => {
      const result = await resetAgentPassword(selectedAccount.value.id);
      shell?.setAction?.(`密码已重置，临时密码：${result.temporaryPassword}`);
    }
  });
}

function requestForceOffline() {
  if (!selectedAccount.value) return;
  openConfirm({
    title: '确认强制下线',
    message: `将强制 ${displayName(selectedAccount.value)} 退出当前登录会话。当前后端暂未开放强制下线接口，本次仅记录前端安全操作入口。`,
    confirmText: '确认下线',
    danger: false,
    run: async () => {
      shell?.setAction?.('当前后端暂未开放强制下线接口，未执行后端下线');
    }
  });
}

function requestDisableAccount() {
  if (!selectedAccount.value) return;
  openConfirm({
    title: '确认停用账号',
    message: `停用后 ${displayName(selectedAccount.value)} 将无法登录并接待用户，历史会话记录不会被删除。`,
    confirmText: '确认停用',
    danger: true,
    run: async () => {
      await updateSelectedStatus('DISABLED', '客服账号已停用');
    }
  });
}

function requestEnableAccount() {
  if (!selectedAccount.value) return;
  openConfirm({
    title: '确认启用账号',
    message: `启用后 ${displayName(selectedAccount.value)} 可重新登录并接待用户。`,
    confirmText: '确认启用',
    danger: false,
    run: async () => {
      await updateSelectedStatus('ACTIVE', '客服账号已启用');
    }
  });
}

function requestDeleteAccount() {
  if (!selectedAccount.value) return;
  openConfirm({
    title: '确认删除账号',
    message: `删除账号属于高风险操作。当前后端暂未提供删除接口，为避免误删历史服务记录，本次不会执行后端删除。`,
    confirmText: '我已知晓',
    danger: true,
    run: async () => {
      shell?.setAction?.('当前后端暂未开放删除账号接口，未执行删除');
    }
  });
}

async function updateSelectedStatus(status, message) {
  if (!selectedAccount.value) return;
  await updateAgentAccount(selectedAccount.value.id, {
    ...buildPayload(),
    status
  });
  shell?.setAction?.(message);
  await loadPage();
  shell?.refreshShell?.();
}

function openConfirm(options) {
  Object.assign(confirmation, {
    show: true,
    title: options.title,
    message: options.message,
    confirmText: options.confirmText,
    danger: options.danger,
    run: options.run
  });
  moreOpen.value = false;
}

function closeConfirm() {
  if (confirmBusy.value) return;
  Object.assign(confirmation, {
    show: false,
    title: '',
    message: '',
    confirmText: '',
    danger: false,
    run: null
  });
}

async function runConfirmedAction() {
  if (!confirmation.run) {
    closeConfirm();
    return;
  }

  confirmBusy.value = true;
  try {
    await confirmation.run();
    confirmBusy.value = false;
    closeConfirm();
  } catch (error) {
    shell?.setAction?.(error.message || '操作执行失败');
    confirmBusy.value = false;
  }
}

function buildPayload() {
  return {
    account: form.account,
    realName: form.realName,
    merchantCode: form.merchantCode,
    phone: form.phone,
    role: form.role || 'CUSTOMER_SERVICE',
    status: form.status,
    maxSessionCount: toNumber(form.maxSessionCount) || 8,
    knowledgeScope: form.knowledgeScope || form.merchantCode,
    note: form.note
  };
}

function syncSnapshot() {
  formSnapshot.value = serializeForm();
  hasUnsavedChanges.value = false;
}

function serializeForm() {
  return JSON.stringify(buildPayload());
}

function sameId(left, right) {
  return String(left ?? '') === String(right ?? '');
}

function toNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function displayName(item) {
  return item?.realName || item?.account || '未命名账号';
}

function firstChar(value) {
  return String(value || '新').trim().slice(0, 1).toUpperCase();
}

function displayValue(value, fallback = '--') {
  return value === null || value === undefined || value === '' ? fallback : value;
}

function displayTime(value) {
  return displayValue(value, '暂无登录记录');
}

function statusLabel(status) {
  const map = {
    ACTIVE: '启用中',
    PENDING_APPROVAL: '待审批',
    DISABLED: '已停用'
  };
  return map[status] || status || '未知';
}

function statusTone(status) {
  const map = {
    ACTIVE: 'success',
    PENDING_APPROVAL: 'pending',
    DISABLED: 'disabled'
  };
  return map[status] || 'neutral';
}

function onlineLabel(status) {
  const map = {
    ONLINE: '在线',
    BUSY: '忙碌',
    OFFLINE: '离线'
  };
  return map[status] || status || '离线';
}

function onlineTone(status) {
  const map = {
    ONLINE: 'success',
    BUSY: 'warning',
    OFFLINE: 'disabled'
  };
  return map[status] || 'disabled';
}

onMounted(loadPage);
</script>

<template>
  <section class="account-governance-page" :aria-busy="loading">
    <section class="account-kpi-grid" aria-label="客服账号统计">
      <article v-for="card in kpiCards" :key="card.key" :class="['account-kpi-card', card.tone]">
        <span class="kpi-icon">{{ card.icon }}</span>
        <div class="kpi-copy">
          <span>{{ card.label }}</span>
          <strong>{{ card.value }}</strong>
          <p>{{ card.desc }}</p>
        </div>
      </article>
    </section>

    <section class="account-workbench">
      <aside class="account-list-panel">
        <header class="panel-head compact">
          <div>
            <span class="eyebrow">Account Queue</span>
            <h2>账号列表</h2>
          </div>
          <div class="panel-actions">
            <button type="button" class="primary-action compact" @click="createNewAccountDraft">新建客服账号</button>
            <button type="button" class="ghost-mini" :disabled="loading" @click="loadPage">刷新列表</button>
          </div>
        </header>

        <label class="account-search">
          <span aria-hidden="true">S</span>
          <input v-model.trim="searchKeyword" type="search" placeholder="搜索姓名 / 账号 / 商家编号" />
        </label>

        <div class="status-filter-row" aria-label="账号状态筛选">
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

        <div v-if="visibleAccounts.length" class="account-list">
          <button
            v-for="item in visibleAccounts"
            :key="item.id"
            type="button"
            :class="['account-list-item', { active: sameId(item.id, selectedAccountId) }]"
            @click="selectAccount(item)"
          >
            <span class="account-row primary">
              <strong>{{ displayName(item) }}</strong>
              <span class="tag-stack">
                <i v-if="item.onlineStatus === 'ONLINE'" class="online-dot" aria-hidden="true"></i>
                <span :class="['status-tag', statusTone(item.status)]">{{ statusLabel(item.status) }}</span>
                <span :class="['status-tag', onlineTone(item.onlineStatus)]">{{ onlineLabel(item.onlineStatus) }}</span>
              </span>
            </span>
            <span class="account-row muted">
              <em>{{ displayValue(item.account) }}</em>
              <small>{{ displayValue(item.merchantCode, '未绑定商家') }}</small>
            </span>
            <span class="account-meta-grid">
              <small>接待 {{ toNumber(item.currentSessionCount) }}/{{ toNumber(item.maxSessionCount) }}</small>
              <small>知识 {{ displayValue(item.knowledgeScope || item.merchantCode, '未配置') }}</small>
              <small>最近 {{ displayTime(item.lastLoginTime) }}</small>
            </span>
          </button>
        </div>

        <div v-else class="account-list-empty">
          <strong>{{ loading ? '正在加载客服账号' : '暂无客服账号' }}</strong>
          <p>{{ loading ? '请稍候，正在同步账号治理数据。' : '可以新建账号，或调整搜索词与状态筛选后再试。' }}</p>
        </div>

        <footer class="account-list-foot">共 {{ visibleAccounts.length }} 个账号 / 已启用 {{ enabledCount }}</footer>
      </aside>

      <article class="account-detail-panel">
        <template v-if="selectedAccount || isCreating">
          <header class="account-overview-card">
            <span class="account-avatar">{{ firstChar(form.realName || form.account) }}</span>
            <div class="overview-main">
              <div class="overview-title-row">
                <div>
                  <span class="eyebrow">{{ isCreating ? 'Create Account' : 'Account Governance' }}</span>
                  <h2>{{ pageModeTitle }}</h2>
                </div>
                <span :class="['status-tag', statusTone(form.status)]">{{ statusLabel(form.status) }}</span>
              </div>
              <div class="overview-grid">
                <span><em>姓名</em><strong>{{ displayValue(form.realName, '新客服') }}</strong></span>
                <span><em>账号</em><strong>{{ displayValue(form.account, '待填写') }}</strong></span>
                <span><em>商家</em><strong>{{ displayValue(form.merchantCode, '待绑定') }}</strong></span>
                <span><em>在线状态</em><strong>{{ selectedAccount ? displayValue(selectedAccount.onlineStatus, 'OFFLINE') : 'NEW' }}</strong></span>
                <span><em>接待能力</em><strong>{{ selectedAccount ? currentSessionText : `0/${form.maxSessionCount}` }}</strong></span>
              </div>
            </div>
          </header>

          <section class="detail-tabs-shell">
            <div class="detail-tabs" role="tablist" aria-label="账号详情配置">
              <button
                v-for="tab in detailTabs"
                :key="tab.key"
                type="button"
                role="tab"
                :aria-selected="activeTab === tab.key"
                :class="{ active: activeTab === tab.key }"
                @click="activeTab = tab.key"
              >
                {{ tab.label }}
              </button>
            </div>

            <Transition name="tab-fade" mode="out-in">
              <section v-if="activeTab === 'basic'" key="basic" class="tab-panel">
                <div class="form-grid compact">
                  <label class="form-field">
                    <span>账号</span>
                    <input v-model.trim="form.account" placeholder="例如：cs_demo" />
                  </label>
                  <label class="form-field">
                    <span>姓名</span>
                    <input v-model.trim="form.realName" placeholder="请输入客服姓名" />
                  </label>
                  <label class="form-field">
                    <span>手机号</span>
                    <input v-model.trim="form.phone" placeholder="请输入手机号" />
                  </label>
                  <label class="form-field">
                    <span>所属商家</span>
                    <input v-model.trim="form.merchantCode" placeholder="例如：MERCHANT_DEMO" />
                  </label>
                  <label class="form-field">
                    <span>状态</span>
                    <select v-model="form.status">
                      <option value="PENDING_APPROVAL">待审批</option>
                      <option value="ACTIVE">启用中</option>
                      <option value="DISABLED">已停用</option>
                    </select>
                  </label>
                  <label class="form-field full">
                    <span>备注</span>
                    <textarea v-model="form.note" rows="3" placeholder="补充负责业务、班次或权限说明"></textarea>
                  </label>
                </div>
              </section>

              <section v-else-if="activeTab === 'service'" key="service" class="tab-panel service-grid">
                <label class="form-field">
                  <span>最大接待数</span>
                  <input v-model.number="form.maxSessionCount" type="number" min="1" max="50" />
                </label>
                <article class="config-card">
                  <span>当前接待数</span>
                  <strong>{{ selectedAccount ? toNumber(selectedAccount.currentSessionCount) : 0 }}</strong>
                  <p>当前正在处理或接入中的会话数量</p>
                </article>
                <article class="config-card">
                  <span>允许接待新会话</span>
                  <strong>{{ allowNewSession ? '允许' : '暂停' }}</strong>
                  <p>根据启停状态与当前接待量自动判断</p>
                </article>
                <article class="config-card">
                  <span>启用自动分配</span>
                  <strong>{{ form.status === 'ACTIVE' ? '已启用' : '未启用' }}</strong>
                  <p>启用账号进入自动派单候选队列</p>
                </article>
                <label class="form-field">
                  <span>工作状态</span>
                  <select :value="selectedAccount?.onlineStatus || 'OFFLINE'" disabled>
                    <option value="ONLINE">在线</option>
                    <option value="BUSY">忙碌</option>
                    <option value="OFFLINE">离线</option>
                  </select>
                </label>
              </section>

              <section v-else-if="activeTab === 'knowledge'" key="knowledge" class="tab-panel">
                <label class="form-field full">
                  <span>可访问知识库范围</span>
                  <input v-model.trim="form.knowledgeScope" placeholder="例如：MERCHANT_DEMO / 通用售后 / 数码保修" />
                </label>
                <div class="permission-list">
                  <article v-for="item in knowledgeItems" :key="item.label" class="permission-row">
                    <span :class="['permission-switch', { checked: item.enabled }]"></span>
                    <div>
                      <strong>{{ item.label }}</strong>
                      <p>{{ item.value }}</p>
                    </div>
                    <span :class="['status-tag', item.enabled ? 'success' : 'disabled']">
                      {{ item.enabled ? '允许' : '关闭' }}
                    </span>
                  </article>
                </div>
              </section>

              <section v-else-if="activeTab === 'security'" key="security" class="tab-panel">
                <div class="security-actions">
                  <button type="button" class="ghost-mini" :disabled="!selectedAccount" @click="requestResetPassword">重置密码</button>
                  <button type="button" class="ghost-mini" :disabled="!selectedAccount" @click="requestForceOffline">强制下线</button>
                  <button
                    v-if="selectedAccount?.status === 'DISABLED'"
                    type="button"
                    class="ghost-mini"
                    @click="requestEnableAccount"
                  >
                    启用账号
                  </button>
                  <button
                    v-else
                    type="button"
                    class="ghost-mini danger muted-danger"
                    :disabled="!selectedAccount"
                    @click="requestDisableAccount"
                  >
                    停用账号
                  </button>
                </div>
                <div class="security-grid">
                  <article v-for="item in securityFacts" :key="item.label" class="config-card">
                    <span>{{ item.label }}</span>
                    <strong>{{ item.value }}</strong>
                  </article>
                </div>
              </section>

              <section v-else key="logs" class="tab-panel">
                <div class="operation-log-list">
                  <article v-for="log in operationLogs" :key="log.id" class="operation-log-row">
                    <span class="log-dot"></span>
                    <div>
                      <strong>{{ log.action }}</strong>
                      <p>{{ log.operator }} / {{ log.time }}</p>
                    </div>
                    <span class="status-tag neutral">{{ log.status }}</span>
                  </article>
                </div>
              </section>
            </Transition>
          </section>

          <footer class="detail-action-bar">
            <div class="dirty-hint" :class="{ show: hasUnsavedChanges }">未保存更改</div>
            <div class="detail-primary-actions">
              <button type="button" class="primary-action compact" :disabled="saveLoading" @click="saveAccount">
                {{ saveLoading ? '保存中...' : '保存修改' }}
              </button>
              <button type="button" class="ghost-mini" :disabled="saveLoading || !hasUnsavedChanges" @click="cancelChanges">
                取消修改
              </button>
            </div>
            <div class="more-menu-wrap" v-if="selectedAccount">
              <button type="button" class="ghost-mini" @click="moreOpen = !moreOpen">更多操作</button>
              <div v-if="moreOpen" class="more-menu">
                <button type="button" @click="requestResetPassword">重置密码</button>
                <button type="button" @click="requestForceOffline">强制下线</button>
                <button
                  v-if="selectedAccount.status === 'PENDING_APPROVAL'"
                  type="button"
                  @click="approveSelectedAccount"
                >
                  审核通过
                </button>
                <button
                  v-if="selectedAccount.status === 'DISABLED'"
                  type="button"
                  @click="requestEnableAccount"
                >
                  启用账号
                </button>
                <button v-else type="button" class="danger" @click="requestDisableAccount">停用账号</button>
                <button type="button" class="danger" @click="requestDeleteAccount">删除账号</button>
              </div>
            </div>
          </footer>
        </template>

        <EmptyState
          v-else
          title="没有选中账号"
          desc="从左侧选择一个客服账号查看治理详情，也可以新建客服账号。"
          action="新建客服账号"
          @action="createNewAccountDraft"
        />
      </article>
    </section>

    <div v-if="confirmation.show" class="confirm-mask" role="dialog" aria-modal="true">
      <section class="confirm-dialog">
        <header>
          <h3>{{ confirmation.title }}</h3>
          <button type="button" aria-label="关闭" @click="closeConfirm">x</button>
        </header>
        <p>{{ confirmation.message }}</p>
        <footer>
          <button type="button" class="ghost-mini" :disabled="confirmBusy" @click="closeConfirm">取消</button>
          <button
            type="button"
            :class="['primary-action', 'compact', { danger: confirmation.danger }]"
            :disabled="confirmBusy"
            @click="runConfirmedAction"
          >
            {{ confirmBusy ? '处理中...' : confirmation.confirmText }}
          </button>
        </footer>
      </section>
    </div>
  </section>
</template>

<style scoped>
.account-governance-page {
  min-height: 0;
  height: 100%;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 14px;
  color: var(--text);
}

.account-kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.account-kpi-card {
  min-height: 90px;
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr);
  align-items: center;
  gap: 12px;
  padding: 14px;
  border: 1px solid rgba(255, 255, 255, 0.7);
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.88);
  box-shadow: 0 16px 38px rgba(31, 41, 55, 0.08);
  transition:
    transform 160ms ease,
    box-shadow 160ms ease,
    border-color 160ms ease;
}

.account-kpi-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 20px 48px rgba(31, 41, 55, 0.12);
}

.account-kpi-card.orange {
  background:
    linear-gradient(135deg, rgba(255, 138, 61, 0.16), rgba(255, 255, 255, 0.38)),
    rgba(255, 255, 255, 0.88);
}

.account-kpi-card.blue {
  background:
    linear-gradient(135deg, rgba(49, 120, 198, 0.14), rgba(255, 255, 255, 0.42)),
    rgba(255, 255, 255, 0.88);
}

.account-kpi-card.green {
  background:
    linear-gradient(135deg, rgba(55, 166, 103, 0.14), rgba(255, 255, 255, 0.42)),
    rgba(255, 255, 255, 0.88);
}

.account-kpi-card.slate {
  background:
    linear-gradient(135deg, rgba(100, 116, 139, 0.13), rgba(255, 255, 255, 0.42)),
    rgba(255, 255, 255, 0.88);
}

.kpi-icon {
  width: 42px;
  height: 42px;
  display: grid;
  place-items: center;
  border-radius: 14px;
  color: #bd560b;
  font-size: 12px;
  font-weight: 900;
  background: rgba(255, 138, 61, 0.16);
}

.kpi-copy {
  min-width: 0;
  display: grid;
  gap: 2px;
}

.kpi-copy span,
.kpi-copy p {
  margin: 0;
  color: var(--muted);
  font-size: 12px;
}

.kpi-copy strong {
  color: var(--text);
  font-size: 26px;
  line-height: 1.1;
}

.account-workbench {
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(320px, 32%) minmax(0, 68%);
  gap: 14px;
}

.account-list-panel,
.account-detail-panel {
  min-height: 0;
  border: 1px solid rgba(255, 255, 255, 0.7);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.88);
  box-shadow: 0 18px 44px rgba(31, 41, 55, 0.08);
  overflow: hidden;
}

.account-list-panel {
  display: grid;
  grid-template-rows: auto auto auto minmax(0, 1fr) auto;
  gap: 12px;
  padding: 16px;
}

.account-detail-panel {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  gap: 12px;
  padding: 16px;
}

.panel-head.compact,
.overview-title-row,
.detail-action-bar,
.confirm-dialog header,
.confirm-dialog footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.panel-head h2,
.account-overview-card h2,
.confirm-dialog h3 {
  margin: 0;
}

.panel-actions,
.detail-primary-actions,
.security-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.account-search {
  min-height: 42px;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  align-items: center;
  padding: 0 14px;
  border: 1px solid var(--glass-border);
  border-radius: 16px;
  color: var(--muted);
  background: rgba(255, 255, 255, 0.56);
  box-shadow: 0 10px 26px rgba(31, 41, 55, 0.08);
  -webkit-backdrop-filter: blur(16px);
  backdrop-filter: blur(16px);
  transition:
    border-color 160ms ease,
    box-shadow 160ms ease,
    background 160ms ease;
}

.account-search > span {
  display: none;
}

.account-search:focus-within {
  border-color: rgba(255, 138, 61, 0.54);
  background: rgba(255, 255, 255, 0.78);
  box-shadow: 0 0 0 4px rgba(255, 138, 61, 0.14);
}

.account-search input,
.form-field input,
.form-field select,
.form-field textarea {
  width: 100%;
  min-width: 0;
  border: 1px solid rgba(151, 170, 196, 0.22);
  outline: 0;
  border-radius: 13px;
  color: var(--text);
  background: rgba(255, 255, 255, 0.66);
}

.account-search input {
  height: 40px;
  border: 0;
  padding: 0;
  font-size: 14px;
  background: transparent;
}

.form-field input,
.form-field select {
  min-height: 40px;
  padding: 0 12px;
}

.form-field textarea {
  min-height: 84px;
  padding: 10px 12px;
  resize: vertical;
}

.status-filter-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.status-filter-row button,
.detail-tabs button {
  min-height: 32px;
  border: 1px solid rgba(151, 170, 196, 0.2);
  border-radius: 999px;
  padding: 0 12px;
  color: var(--muted);
  background: rgba(255, 255, 255, 0.64);
}

.status-filter-row button {
  min-height: 34px;
  flex: 0 0 auto;
  padding: 0 13px;
  border-color: var(--glass-border);
  color: var(--muted);
  background: rgba(255, 255, 255, 0.52);
  box-shadow: 0 10px 26px rgba(31, 41, 55, 0.08);
  -webkit-backdrop-filter: blur(16px);
  backdrop-filter: blur(16px);
  transition:
    transform 160ms ease,
    border-color 160ms ease,
    background 160ms ease,
    color 160ms ease,
    box-shadow 160ms ease;
}

.status-filter-row button:hover {
  transform: translateY(-1px);
  border-color: rgba(255, 138, 61, 0.38);
  color: #c45009;
  background: rgba(255, 255, 255, 0.74);
  box-shadow: 0 14px 34px rgba(255, 107, 26, 0.12);
}

.status-filter-row button.active,
.detail-tabs button.active {
  color: #bd560b;
  border-color: rgba(255, 138, 61, 0.38);
  background: rgba(255, 138, 61, 0.14);
  font-weight: 900;
}

.status-filter-row button.active {
  border-color: rgba(255, 138, 61, 0.72);
  color: #fff;
  background: linear-gradient(135deg, var(--brand-orange), var(--brand-orange-deep));
  box-shadow: 0 16px 34px rgba(255, 107, 26, 0.24);
}

.account-list {
  min-height: 0;
  display: grid;
  align-content: start;
  gap: 10px;
  overflow: auto;
  padding-right: 4px;
  scrollbar-width: thin;
  scrollbar-color: rgba(255, 138, 61, 0.42) transparent;
}

.account-list-item {
  width: 100%;
  min-height: 126px;
  display: grid;
  gap: 8px;
  padding: 13px;
  border: 1px solid rgba(151, 170, 196, 0.16);
  border-radius: 18px;
  color: var(--text);
  text-align: left;
  background: rgba(255, 255, 255, 0.58);
  transition:
    transform 160ms ease,
    border-color 160ms ease,
    background 160ms ease,
    box-shadow 160ms ease;
}

.account-list-item:hover {
  transform: translateY(-1px);
  border-color: rgba(255, 138, 61, 0.24);
  background: rgba(255, 255, 255, 0.78);
  box-shadow: 0 14px 32px rgba(31, 41, 55, 0.07);
}

.account-list-item.active {
  border-color: rgba(255, 138, 61, 0.52);
  background:
    linear-gradient(135deg, rgba(255, 138, 61, 0.14), rgba(255, 255, 255, 0.74)),
    rgba(255, 255, 255, 0.84);
  box-shadow: 0 16px 36px rgba(255, 107, 26, 0.13);
}

.account-row {
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.account-row strong,
.account-row em,
.account-row small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.account-row strong {
  font-size: 15px;
}

.account-row em,
.account-row small,
.account-meta-grid,
.account-list-foot,
.account-list-empty p,
.config-card p,
.permission-row p,
.operation-log-row p,
.overview-grid em {
  color: var(--muted);
  font-size: 12px;
  font-style: normal;
}

.tag-stack {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex: none;
}

.online-dot,
.log-dot {
  width: 8px;
  height: 8px;
  flex: none;
  border-radius: 999px;
  background: #37a667;
  box-shadow: 0 0 0 4px rgba(55, 166, 103, 0.12);
}

.status-tag {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  border-radius: 999px;
  padding: 0 9px;
  font-size: 12px;
  font-weight: 800;
  white-space: nowrap;
}

.status-tag.success {
  color: #24784a;
  background: rgba(55, 166, 103, 0.13);
}

.status-tag.pending,
.status-tag.warning {
  color: #1f6daf;
  background: rgba(49, 120, 198, 0.12);
}

.status-tag.disabled,
.status-tag.neutral {
  color: #697383;
  background: rgba(100, 116, 139, 0.12);
}

.account-meta-grid {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 6px 10px;
}

.account-meta-grid small:last-child {
  grid-column: 1 / -1;
}

.account-list-empty {
  min-height: 220px;
  display: grid;
  place-items: center;
  align-content: center;
  gap: 8px;
  padding: 20px;
  border: 1px dashed rgba(151, 170, 196, 0.32);
  border-radius: 18px;
  text-align: center;
  background: rgba(255, 255, 255, 0.42);
}

.account-list-empty strong {
  color: var(--text);
}

.account-list-foot {
  font-weight: 800;
}

.account-overview-card {
  display: grid;
  grid-template-columns: 58px minmax(0, 1fr);
  gap: 14px;
  padding: 14px;
  border: 1px solid rgba(151, 170, 196, 0.16);
  border-radius: 18px;
  background:
    linear-gradient(135deg, rgba(255, 138, 61, 0.12), rgba(49, 120, 198, 0.06)),
    rgba(255, 255, 255, 0.58);
}

.account-avatar {
  width: 58px;
  height: 58px;
  display: grid;
  place-items: center;
  border-radius: 18px;
  color: #fff;
  font-size: 22px;
  font-weight: 900;
  background: linear-gradient(135deg, var(--brand-orange), var(--brand-orange-deep));
  box-shadow: 0 16px 32px rgba(255, 107, 26, 0.2);
}

.overview-main {
  min-width: 0;
  display: grid;
  gap: 10px;
}

.overview-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;
}

.overview-grid span {
  min-width: 0;
  display: grid;
  gap: 3px;
  padding: 9px 10px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.52);
}

.overview-grid strong {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}

.detail-tabs-shell {
  min-height: 0;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 12px;
  overflow: hidden;
}

.detail-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.tab-panel {
  min-height: 0;
  overflow: auto;
  padding-right: 4px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.form-field {
  display: grid;
  gap: 7px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 800;
}

.form-field.full {
  grid-column: 1 / -1;
}

.service-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  align-content: start;
  gap: 12px;
}

.config-card {
  min-height: 96px;
  display: grid;
  align-content: center;
  gap: 5px;
  padding: 14px;
  border: 1px solid rgba(151, 170, 196, 0.16);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.5);
}

.config-card span {
  color: var(--muted);
  font-size: 12px;
  font-weight: 800;
}

.config-card strong {
  font-size: 20px;
}

.permission-list,
.operation-log-list,
.security-grid {
  display: grid;
  gap: 10px;
  margin-top: 12px;
}

.security-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.permission-row,
.operation-log-row {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  padding: 12px;
  border: 1px solid rgba(151, 170, 196, 0.16);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.5);
}

.permission-row p,
.operation-log-row p {
  margin: 4px 0 0;
}

.permission-switch {
  width: 34px;
  height: 20px;
  border-radius: 999px;
  background: rgba(100, 116, 139, 0.22);
  position: relative;
}

.permission-switch::before {
  content: "";
  position: absolute;
  top: 3px;
  left: 3px;
  width: 14px;
  height: 14px;
  border-radius: 999px;
  background: #fff;
  transition: transform 160ms ease;
}

.permission-switch.checked {
  background: rgba(55, 166, 103, 0.42);
}

.permission-switch.checked::before {
  transform: translateX(14px);
}

.detail-action-bar {
  position: relative;
  padding-top: 12px;
  border-top: 1px solid rgba(151, 170, 196, 0.14);
}

.dirty-hint {
  min-width: 112px;
  color: transparent;
  font-size: 12px;
  font-weight: 900;
}

.dirty-hint.show {
  color: #bd560b;
}

.more-menu-wrap {
  position: relative;
}

.more-menu {
  position: absolute;
  right: 0;
  bottom: calc(100% + 8px);
  z-index: 15;
  width: 154px;
  display: grid;
  gap: 4px;
  padding: 8px;
  border: 1px solid rgba(151, 170, 196, 0.2);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 18px 44px rgba(31, 41, 55, 0.14);
}

.more-menu button {
  min-height: 34px;
  border: 0;
  border-radius: 10px;
  color: var(--text);
  background: transparent;
  text-align: left;
  padding: 0 10px;
}

.more-menu button:hover {
  background: rgba(255, 138, 61, 0.1);
}

.more-menu button.danger,
.ghost-mini.danger,
.primary-action.danger {
  color: var(--danger);
}

.ghost-mini.muted-danger {
  border-color: rgba(201, 66, 50, 0.2);
  background: rgba(201, 66, 50, 0.06);
}

.primary-action.danger {
  color: #fff;
  background: linear-gradient(135deg, #df6a5e, #c94232);
  box-shadow: 0 16px 34px rgba(201, 66, 50, 0.2);
}

.tab-fade-enter-active,
.tab-fade-leave-active {
  transition:
    opacity 140ms ease,
    transform 140ms ease;
}

.tab-fade-enter-from,
.tab-fade-leave-to {
  opacity: 0;
  transform: translateY(4px);
}

.confirm-mask {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(15, 23, 35, 0.38);
  backdrop-filter: blur(8px);
}

.confirm-dialog {
  width: min(460px, 100%);
  display: grid;
  gap: 14px;
  padding: 18px;
  border: 1px solid rgba(255, 255, 255, 0.7);
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 28px 72px rgba(15, 23, 42, 0.18);
}

.confirm-dialog header button {
  width: 32px;
  height: 32px;
  border: 0;
  border-radius: 999px;
  color: var(--muted);
  background: rgba(100, 116, 139, 0.12);
}

.confirm-dialog p {
  margin: 0;
  color: var(--muted);
  line-height: 1.65;
}

:global(.topbar p) {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: 13px;
}

:global(body:has(.account-governance-page)) {
  min-width: 0;
}

:global(.app-shell.admin-shell:has(.account-governance-page)) {
  min-width: 0;
}

html[data-theme="dark"] .account-kpi-card,
html[data-theme="dark"] .account-list-panel,
html[data-theme="dark"] .account-detail-panel,
html[data-theme="dark"] .confirm-dialog {
  border-color: rgba(255, 255, 255, 0.12);
  background: rgba(17, 26, 39, 0.76);
  box-shadow: 0 20px 48px rgba(0, 0, 0, 0.32);
}

html[data-theme="dark"] .account-kpi-card.orange {
  background:
    linear-gradient(135deg, rgba(255, 138, 61, 0.18), rgba(24, 36, 55, 0.58)),
    rgba(17, 26, 39, 0.76);
}

html[data-theme="dark"] .account-kpi-card.blue {
  background:
    linear-gradient(135deg, rgba(49, 120, 198, 0.18), rgba(24, 36, 55, 0.58)),
    rgba(17, 26, 39, 0.76);
}

html[data-theme="dark"] .account-kpi-card.green {
  background:
    linear-gradient(135deg, rgba(55, 166, 103, 0.16), rgba(24, 36, 55, 0.58)),
    rgba(17, 26, 39, 0.76);
}

html[data-theme="dark"] .account-kpi-card.slate {
  background:
    linear-gradient(135deg, rgba(148, 163, 184, 0.14), rgba(24, 36, 55, 0.58)),
    rgba(17, 26, 39, 0.76);
}

html[data-theme="dark"] .account-search,
html[data-theme="dark"] .status-filter-row button,
html[data-theme="dark"] .detail-tabs button,
html[data-theme="dark"] .account-list-item,
html[data-theme="dark"] .account-list-empty,
html[data-theme="dark"] .account-overview-card,
html[data-theme="dark"] .overview-grid span,
html[data-theme="dark"] .form-field input,
html[data-theme="dark"] .form-field select,
html[data-theme="dark"] .form-field textarea,
html[data-theme="dark"] .config-card,
html[data-theme="dark"] .permission-row,
html[data-theme="dark"] .operation-log-row {
  border-color: rgba(255, 255, 255, 0.12);
  background: rgba(9, 14, 22, 0.34);
}

html[data-theme="dark"] .account-list-item:hover {
  border-color: rgba(255, 138, 61, 0.32);
  background: rgba(24, 36, 55, 0.72);
}

html[data-theme="dark"] .account-list-item.active {
  border-color: rgba(255, 138, 61, 0.52);
  background:
    linear-gradient(135deg, rgba(255, 138, 61, 0.2), rgba(24, 36, 55, 0.72)),
    rgba(17, 26, 39, 0.82);
}

html[data-theme="dark"] .status-filter-row button.active,
html[data-theme="dark"] .detail-tabs button.active {
  color: #ffad73;
  border-color: rgba(255, 138, 61, 0.5);
  background: rgba(255, 138, 61, 0.18);
}

html[data-theme="dark"] .account-search,
html[data-theme="dark"] .status-filter-row button {
  border-color: var(--glass-border);
  color: var(--text);
  background: rgba(17, 26, 39, 0.62);
}

html[data-theme="dark"] .account-search:focus-within,
html[data-theme="dark"] .status-filter-row button:hover {
  border-color: #3e5875;
  background: rgba(24, 36, 55, 0.72);
  box-shadow: 0 10px 24px rgba(0, 0, 0, 0.24);
}

html[data-theme="dark"] .account-search:focus-within {
  box-shadow: 0 0 0 3px rgba(115, 169, 240, 0.16);
}

html[data-theme="dark"] .status-filter-row button.active {
  border-color: #ffad73;
  color: #101722;
  background: #ffad73;
  box-shadow: 0 16px 34px rgba(255, 173, 115, 0.18);
}

html[data-theme="dark"] .account-search input::placeholder {
  color: #aebccd;
}

html[data-theme="dark"] .more-menu {
  border-color: rgba(255, 255, 255, 0.12);
  background: rgba(17, 26, 39, 0.96);
  box-shadow: 0 18px 44px rgba(0, 0, 0, 0.34);
}

html[data-theme="dark"] .more-menu button:hover {
  background: rgba(255, 138, 61, 0.14);
}

html[data-theme="dark"] .confirm-mask {
  background: rgba(2, 6, 12, 0.52);
}

@media (max-width: 1100px) {
  .account-kpi-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .account-workbench {
    grid-template-columns: 1fr;
    overflow: auto;
  }

  .account-list-panel {
    min-height: 420px;
  }
}

@media (max-width: 720px) {
  .account-kpi-grid,
  .form-grid,
  .service-grid,
  .security-grid,
  .overview-grid {
    grid-template-columns: 1fr;
  }

  .panel-head.compact,
  .detail-action-bar,
  .overview-title-row {
    align-items: flex-start;
    flex-direction: column;
  }

  .account-overview-card {
    grid-template-columns: 1fr;
  }
}
</style>
