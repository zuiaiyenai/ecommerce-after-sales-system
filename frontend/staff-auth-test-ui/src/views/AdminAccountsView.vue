<script setup>
import { computed, inject, onMounted, reactive, ref } from 'vue';
import EmptyState from '../components/EmptyState.vue';
import {
  createAgentAccount,
  getAgentAccounts,
  resetAgentPassword,
  updateAgentAccount
} from '../api/adminConsole';

const shell = inject('adminShell', null);
const loading = ref(true);
const accounts = ref([]);
const selectedAccountId = ref(null);
const activeFilter = ref('ALL');

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

const filterOptions = [
  { key: 'ALL', label: '全部' },
  { key: 'PENDING_APPROVAL', label: '待审批' },
  { key: 'ACTIVE', label: '启用中' },
  { key: 'DISABLED', label: '已停用' }
];

const selectedAccount = computed(() => {
  return accounts.value.find((item) => item.id === selectedAccountId.value) || null;
});

const visibleAccounts = computed(() => {
  if (activeFilter.value === 'ALL') {
    return accounts.value;
  }
  return accounts.value.filter((item) => item.status === activeFilter.value);
});

const activeCount = computed(() => accounts.value.filter((item) => item.status === 'ACTIVE').length);

const editorTitle = computed(() => {
  return selectedAccount.value ? '编辑客服账号' : '新建客服账号';
});

async function loadPage() {
  loading.value = true;
  try {
    const page = await getAgentAccounts();
    accounts.value = page.records || [];
    if (!selectedAccountId.value && accounts.value.length) {
      selectAccount(accounts.value[0]);
      return;
    }
    if (selectedAccountId.value && !accounts.value.some((item) => item.id === selectedAccountId.value)) {
      if (accounts.value.length) {
        selectAccount(accounts.value[0]);
      } else {
        createNewAccountDraft();
      }
    }
  } finally {
    loading.value = false;
  }
}

function selectAccount(account) {
  selectedAccountId.value = account.id;
  Object.assign(form, {
    account: account.account,
    realName: account.realName,
    merchantCode: account.merchantCode,
    phone: account.phone,
    role: account.role,
    status: account.status,
    maxSessionCount: account.maxSessionCount,
    knowledgeScope: account.knowledgeScope,
    note: account.note || ''
  });
}

function createNewAccountDraft() {
  selectedAccountId.value = null;
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
}

async function saveAccount() {
  if (!form.account || !form.realName || !form.merchantCode) {
    shell?.setAction?.('请先填写账号、姓名和商家编号');
    return;
  }

  if (selectedAccountId.value) {
    await updateAgentAccount(selectedAccountId.value, { ...form });
    shell?.setAction?.('客服账号已更新');
  } else {
    const created = await createAgentAccount({ ...form });
    shell?.setAction?.(`已新建客服账号：${created.account}`);
  }

  await loadPage();
}

async function handleResetPassword() {
  if (!selectedAccount.value) {
    return;
  }
  const result = await resetAgentPassword(selectedAccount.value.id);
  shell?.setAction?.(`密码已重置，临时密码：${result.temporaryPassword}`);
}

async function toggleStatus(targetStatus) {
  if (!selectedAccount.value) {
    return;
  }
  await updateAgentAccount(selectedAccount.value.id, { status: targetStatus });
  if (targetStatus === 'ACTIVE') {
    shell?.setAction?.('账号已审核通过并启用');
  } else if (targetStatus === 'PENDING_APPROVAL') {
    shell?.setAction?.('账号已改回待审批');
  } else {
    shell?.setAction?.('账号已停用');
  }
  await loadPage();
}

async function approveSelectedAccount() {
  if (!selectedAccount.value) {
    return;
  }
  if (!form.account || !form.realName || !form.merchantCode) {
    shell?.setAction?.('审批前请先补全账号、姓名和商家编号');
    return;
  }
  await updateAgentAccount(selectedAccount.value.id, {
    ...form,
    status: 'ACTIVE'
  });
  shell?.setAction?.('注册申请已审核通过，客服可直接账号密码登录');
  await loadPage();
}

function statusLabel(status) {
  if (status === 'PENDING_APPROVAL') {
    return '待审批';
  }
  return status === 'ACTIVE' ? '启用中' : '已停用';
}

function displayName(item) {
  return item?.realName || item?.account || '未命名账号';
}

function shortText(value, limit = 20) {
  const text = String(value || '').trim();
  if (!text) {
    return '暂无说明';
  }
  return text.length > limit ? `${text.slice(0, limit)}...` : text;
}

onMounted(loadPage);
</script>

<template>
  <section class="admin-console-page">
    <aside class="admin-console-list">
      <div class="template-panel-head">
        <h2>账号列表</h2>
        <button type="button" class="template-icon-button" aria-label="新建账号" @click="createNewAccountDraft">+</button>
      </div>

      <div class="template-filter-tabs" aria-label="账号筛选">
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

      <div v-if="visibleAccounts.length" class="template-conversation-list">
        <button
          v-for="item in visibleAccounts"
          :key="item.id"
          type="button"
          :class="['template-conversation-card', { active: item.id === selectedAccountId }]"
          @click="selectAccount(item)"
        >
          <span class="template-user-avatar">{{ displayName(item).slice(0, 1) }}</span>
          <span class="template-conversation-copy">
            <strong>{{ displayName(item) }}</strong>
            <em>{{ item.account }}</em>
            <small>{{ shortText(item.merchantCode, 18) }}</small>
          </span>
          <span class="template-conversation-side">
            <time>{{ statusLabel(item.status) }}</time>
            <i v-if="item.status === 'ACTIVE'" aria-hidden="true"></i>
          </span>
        </button>
      </div>
      <div v-else class="template-list-empty">
        {{ loading ? '正在加载账号列表...' : '当前筛选下没有账号' }}
      </div>

      <div class="template-list-foot">共 {{ visibleAccounts.length }} 个账号 / 已启用 {{ activeCount }}</div>
    </aside>

    <article class="admin-console-main">
      <header class="template-chat-head admin-console-head">
        <span class="template-user-avatar large">{{ (selectedAccount?.realName || '新').slice(0, 1) }}</span>
        <div>
          <h2>{{ editorTitle }}</h2>
          <p>
            {{ selectedAccount ? `当前正在编辑：${selectedAccount.realName} / ${selectedAccount.account}` : '当前正在创建新的客服账号' }}
          </p>
        </div>
        <span v-if="selectedAccount" class="session-status processing">{{ statusLabel(selectedAccount.status) }}</span>
      </header>

      <div class="admin-console-body">
        <section class="admin-console-hero">
          <div>
            <span class="eyebrow">Editor</span>
            <h3>右侧主区域负责编辑当前选中的账号</h3>
            <p>这里可以直接修改客服账号的基础信息、接待上限、知识范围和状态，不再额外拆出右侧栏。</p>
          </div>
          <div class="admin-editor-badges" v-if="selectedAccount">
            <span class="tag">{{ selectedAccount.onlineStatus }}</span>
            <span class="tag">{{ selectedAccount.currentSessionCount }}/{{ selectedAccount.maxSessionCount }}</span>
            <span class="tag">{{ selectedAccount.merchantCode }}</span>
          </div>
        </section>

        <section class="admin-console-form-card">
          <div class="admin-form-grid">
            <label class="admin-field">
              <span>账号</span>
              <input v-model.trim="form.account" placeholder="例如 cs_demo" />
            </label>
            <label class="admin-field">
              <span>姓名</span>
              <input v-model.trim="form.realName" placeholder="请输入客服姓名" />
            </label>
            <label class="admin-field">
              <span>商家编号</span>
              <input v-model.trim="form.merchantCode" placeholder="自动绑定商家编号" />
            </label>
            <label class="admin-field">
              <span>手机号</span>
              <input v-model.trim="form.phone" placeholder="请输入手机号" />
            </label>
            <label class="admin-field">
              <span>状态</span>
              <select v-model="form.status">
                <option value="PENDING_APPROVAL">待审批</option>
                <option value="ACTIVE">启用</option>
                <option value="DISABLED">停用</option>
              </select>
            </label>
            <label class="admin-field">
              <span>最大接待数</span>
              <input v-model.number="form.maxSessionCount" type="number" min="1" />
            </label>
            <label class="admin-field admin-field-full">
              <span>知识范围</span>
              <input v-model.trim="form.knowledgeScope" placeholder="例如 通用售后 / 数码保修" />
            </label>
            <label class="admin-field admin-field-full">
              <span>备注</span>
              <textarea
                v-model="form.note"
                rows="5"
                placeholder="补充当前账号负责的业务范围、班次说明或权限备注"
              ></textarea>
            </label>
          </div>
        </section>

        <section class="admin-console-actions">
          <button type="button" class="primary-action compact" @click="saveAccount">保存账号</button>
          <button
            v-if="selectedAccount && selectedAccount.status === 'PENDING_APPROVAL'"
            type="button"
            class="ghost-mini"
            @click="approveSelectedAccount"
          >
            审核通过
          </button>
          <button v-if="selectedAccount" type="button" class="ghost-mini" @click="handleResetPassword">重置密码</button>
          <button
            v-if="selectedAccount && selectedAccount.status !== 'DISABLED'"
            type="button"
            class="ghost-mini danger"
            @click="toggleStatus('DISABLED')"
          >
            {{ selectedAccount.status === 'PENDING_APPROVAL' ? '驳回申请' : '停用账号' }}
          </button>
          <button
            v-if="selectedAccount && selectedAccount.status === 'DISABLED'"
            type="button"
            class="ghost-mini"
            @click="toggleStatus('ACTIVE')"
          >
            重新启用
          </button>
        </section>

        <EmptyState
          v-if="!accounts.length && !loading"
          title="还没有客服账号"
          desc="先创建一个客服账号，左侧列表就会开始承载账号切换。"
          action="创建首个账号"
          @action="createNewAccountDraft"
        />
      </div>
    </article>
  </section>
</template>
