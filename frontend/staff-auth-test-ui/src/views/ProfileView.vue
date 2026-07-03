<script setup>
import { computed, inject, onMounted, ref } from 'vue';
import { getCurrentStaff, getDashboardPerformance, updateWorkStatus } from '../api/merchantCs';

const shell = inject('merchantCsShell', null);
const staff = ref(null);
const performance = ref({ metrics: [] });

const statusOptions = [
  { value: 'ONLINE', label: '上线', desc: '正常接待新会话' },
  { value: 'BUSY', label: '忙碌', desc: '暂停分配新会话' },
  { value: 'OFFLINE', label: '离线', desc: '结束当前值班状态' }
];

const statusTextMap = {
  ONLINE: '在线',
  BUSY: '忙碌',
  OFFLINE: '离线'
};

const roleTextMap = {
  CUSTOMER_SERVICE: '商家客服'
};

const statusTone = computed(() => (staff.value?.onlineStatus || 'OFFLINE').toLowerCase());
const statusText = computed(() => statusTextMap[staff.value?.onlineStatus] || staff.value?.onlineStatus || '--');
const roleText = computed(() => roleTextMap[staff.value?.role] || staff.value?.role || '--');
const performanceBars = computed(() => performance.value?.metrics ?? []);
const displayStaffNo = computed(() => {
  const staffNo = String(staff.value?.staffNo || '');
  if (/^CS\d{8,}$/.test(staffNo)) {
    return `CS${String(staff.value?.staffId || staffNo.slice(-4)).padStart(4, '0')}`;
  }
  return staffNo || '--';
});
const profileInitial = computed(() => {
  const name = staff.value?.realName || staff.value?.account || 'CS';
  return name.slice(0, 1).toUpperCase();
});

async function loadPage() {
  const [profile, performanceData] = await Promise.all([
    getCurrentStaff(),
    getDashboardPerformance()
  ]);
  staff.value = profile;
  performance.value = performanceData;
}

async function setStatus(status) {
  if (staff.value?.onlineStatus === status) {
    return;
  }
  staff.value = await updateWorkStatus(status);
  shell?.setAction(`客服状态已切换为 ${statusTextMap[status] || status}`);
  shell?.refreshShell();
}

onMounted(loadPage);
</script>

<template>
  <section class="work-page two-column profile-page">
    <article class="wide-panel profile-panel">
      <div class="profile-hero">
        <div class="profile-avatar" aria-hidden="true">{{ profileInitial }}</div>
        <div class="profile-identity">
          <span class="eyebrow">个人中心</span>
          <h2>{{ staff?.realName || '客服资料' }}</h2>
          <p>{{ displayStaffNo }} · {{ staff?.account || '--' }}</p>
          <span :class="['profile-status-chip', statusTone]">{{ statusText }}</span>
        </div>
        <div class="profile-capacity">
          <span>最大接待数</span>
          <strong>{{ staff?.maxSessionCount ?? '--' }}</strong>
          <em>当前账号接待容量</em>
        </div>
      </div>

      <div class="profile-status-tabs" role="group" aria-label="客服在线状态">
        <button
          v-for="option in statusOptions"
          :key="option.value"
          type="button"
          :class="{ active: staff?.onlineStatus === option.value }"
          :aria-pressed="staff?.onlineStatus === option.value"
          @click="setStatus(option.value)"
        >
          <strong>{{ option.label }}</strong>
          <span>{{ option.desc }}</span>
        </button>
      </div>

      <div class="profile-main-grid">
        <section class="profile-card">
          <div class="panel-head compact">
            <div>
              <span class="eyebrow">Account</span>
              <h2>账号资料</h2>
            </div>
          </div>
          <div class="profile-info-list">
            <div><span>客服编号</span><strong>{{ displayStaffNo }}</strong></div>
            <div><span>登录账号</span><strong>{{ staff?.account || '--' }}</strong></div>
            <div><span>商家编码</span><strong>{{ staff?.merchantCode || '--' }}</strong></div>
            <div><span>角色权限</span><strong>{{ roleText }}</strong></div>
          </div>
        </section>

        <section class="profile-card">
          <div class="panel-head compact">
            <div>
              <span class="eyebrow">Service</span>
              <h2>服务表现</h2>
            </div>
          </div>
          <div class="profile-metric-grid">
            <div v-for="item in performanceBars" :key="item.label" class="profile-metric">
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
              <div class="profile-meter" aria-hidden="true">
                <i :style="{ width: `${Math.min(item.currentPercent ?? 0, 100)}%` }"></i>
              </div>
              <em>{{ item.desc }}</em>
            </div>
          </div>
        </section>
      </div>
    </article>

    <aside class="side-panel profile-duty-panel">
      <span class="eyebrow">值班信息</span>
      <h2>当前状态说明</h2>
      <div class="profile-duty-summary">
        <div>
          <span>接待容量</span>
          <strong>{{ staff?.maxSessionCount ?? '--' }} 个会话</strong>
        </div>
        <div>
          <span>商家编码</span>
          <strong>{{ staff?.merchantCode || '--' }}</strong>
        </div>
        <div>
          <span>当前角色</span>
          <strong>{{ roleText }}</strong>
        </div>
      </div>
      <div class="profile-status-guide">
        <div v-for="option in statusOptions" :key="option.value">
          <span :class="['profile-guide-dot', option.value.toLowerCase()]" aria-hidden="true"></span>
          <p><strong>{{ option.label }}</strong>{{ option.desc }}</p>
        </div>
      </div>
    </aside>
  </section>
</template>
