<script setup>
import { inject, onMounted, ref } from 'vue';
import { getAdminOverview, getAgentAccounts, getKnowledgeLibraries } from '../api/adminConsole';

const shell = inject('adminShell', null);
const overview = ref(null);
const accounts = ref([]);
const knowledge = ref([]);
const loading = ref(true);

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

onMounted(loadPage);
</script>

<template>
  <section class="home-page dashboard-simple admin-dashboard-page" :aria-busy="loading">
    <article class="hero-panel admin-hero-panel">
      <div class="hero-copy">
        <span class="eyebrow">Admin Overview</span>
        <h2>{{ overview?.greeting || '管理员治理台' }}</h2>
        <p>{{ overview?.subtitle || '统一承接客服账号管理、知识库规划与治理接口设计。' }}</p>
      </div>
      <div class="hero-number">
        <span>治理面板</span>
        <strong>{{ overview?.stats?.length || 0 }}</strong>
      </div>
    </article>

    <section class="admin-stat-grid">
      <article v-for="item in overview?.stats || []" :key="item.label" :class="['module-card', item.accent]">
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
      </article>
    </section>

    <section class="admin-workbench">
      <article class="wide-panel">
        <div class="panel-head compact">
          <div>
            <span class="eyebrow">Governance Focus</span>
            <h2>当前治理重点</h2>
          </div>
        </div>
        <div class="data-list">
          <article v-for="item in overview?.focus || []" :key="item" class="data-row admin-note-row">
            <div class="avatar small">策</div>
            <div class="row-copy">
              <strong>{{ item }}</strong>
              <span>管理员端先承载规则治理与接口收口，避免后续知识建设再次分散。</span>
            </div>
          </article>
        </div>
      </article>

      <article class="side-panel admin-side-panel">
        <div class="panel-head compact">
          <div>
            <span class="eyebrow">Status</span>
            <h2>建设状态</h2>
          </div>
        </div>
        <div class="info-grid admin-summary-grid">
          <div>
            <span>在线客服</span>
            <strong>{{ accounts.filter((item) => item.onlineStatus === 'ONLINE').length }}</strong>
          </div>
          <div>
            <span>忙碌客服</span>
            <strong>{{ accounts.filter((item) => item.onlineStatus === 'BUSY').length }}</strong>
          </div>
          <div>
            <span>建设中知识库</span>
            <strong>{{ knowledge.filter((item) => item.status === 'BUILDING').length }}</strong>
          </div>
          <div>
            <span>已留接口</span>
            <strong>{{ knowledge.filter((item) => item.interfaceStatus === 'READY_FOR_API').length }}</strong>
          </div>
        </div>
      </article>
    </section>
  </section>
</template>
