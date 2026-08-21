<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { getAgentOperations } from '../api/adminConsole';
import AgentLineChart from '../components/AgentLineChart.vue';

const range = ref('1h');
const data = ref(null);
const loading = ref(false);
const errorMessage = ref('');
let refreshTimer = 0;

const rangeOptions = [
  { key: '1h', label: '近 1 小时' },
  { key: '6h', label: '近 6 小时' },
  { key: '24h', label: '近 24 小时' }
];

const overall = computed(() => {
  const status = data.value?.overallStatus || 'UNAVAILABLE';
  return {
    HEALTHY: { label: '运行平稳', tone: 'healthy', description: '核心链路当前未发现显著异常' },
    ATTENTION: { label: '需要关注', tone: 'warning', description: '部分指标偏离健康阈值' },
    CRITICAL: { label: '存在异常', tone: 'critical', description: '组件或消息链路需要立即排查' },
    UNAVAILABLE: { label: '监控不可用', tone: 'muted', description: '暂时无法读取 Prometheus 数据' }
  }[status];
});

const metricCards = computed(() => {
  const overview = data.value?.overview || {};
  return [
    {
      key: 'success',
      label: '网关成功率',
      value: formatPercent(overview.gatewaySuccessRate),
      detail: overview.gatewaySuccessRate == null ? '暂无网关请求' : '最近 5 分钟',
      tone: rateTone(overview.gatewaySuccessRate, 0.95, 0.9)
    },
    {
      key: 'throughput',
      label: '当前吞吐',
      value: formatRps(overview.requestsPerSecond),
      detail: 'Java → Python Agent',
      tone: 'blue'
    },
    {
      key: 'java-latency',
      label: 'Java 网关 P95',
      value: formatLatency(overview.gatewayP95Seconds),
      detail: '包含 Agent 调用等待',
      tone: latencyTone(overview.gatewayP95Seconds)
    },
    {
      key: 'agent-latency',
      label: 'Python Agent P95',
      value: formatLatency(overview.agentP95Seconds),
      detail: 'LangGraph 请求处理',
      tone: latencyTone(overview.agentP95Seconds)
    },
    {
      key: 'tool-failure',
      label: '工具失败率',
      value: formatPercent(overview.toolFailureRate),
      detail: overview.toolFailureRate == null ? '所选时段暂无调用' : '失败 / 全部工具调用',
      tone: inverseRateTone(overview.toolFailureRate, 0.1, 0.2)
    },
    {
      key: 'handoff',
      label: '人工转接率',
      value: formatPercent(overview.handoffRate),
      detail: overview.handoffRate == null ? '所选时段暂无会话' : 'Agent 会话转人工',
      tone: 'slate'
    }
  ];
});

const runtimeFacts = computed(() => [
  {
    label: '待回复会话',
    value: data.value?.overview?.unrepliedSessions == null ? '—' : formatCount(data.value.overview.unrepliedSessions),
    tone: Number(data.value?.overview?.unrepliedSessions || 0) > 0 ? 'warning' : 'healthy'
  },
  {
    label: 'DLQ 事件',
    value: data.value?.overview?.dlqEvents == null ? '—' : formatCount(data.value.overview.dlqEvents),
    tone: Number(data.value?.overview?.dlqEvents || 0) > 0 ? 'critical' : 'healthy'
  }
]);

async function loadData() {
  if (loading.value) {
    return;
  }
  loading.value = true;
  errorMessage.value = '';
  try {
    data.value = await getAgentOperations(range.value);
  } catch (error) {
    errorMessage.value = error.message || 'Agent 运行数据加载失败';
  } finally {
    loading.value = false;
  }
}

function openGrafana() {
  if (!data.value?.grafanaUrl) {
    return;
  }
  const url = new URL(data.value.grafanaUrl, window.location.href);
  url.searchParams.set('from', `now-${range.value}`);
  url.searchParams.set('to', 'now');
  url.searchParams.set('refresh', '10s');
  window.open(url.toString(), '_blank', 'noopener,noreferrer');
}

function formatPercent(value) {
  return value == null || !Number.isFinite(Number(value)) ? '—' : `${(Number(value) * 100).toFixed(1)}%`;
}

function formatLatency(value) {
  if (value == null || !Number.isFinite(Number(value))) {
    return '—';
  }
  const seconds = Number(value);
  return seconds >= 1 ? `${seconds.toFixed(2)} s` : `${Math.round(seconds * 1000)} ms`;
}

function formatRps(value) {
  if (value == null || !Number.isFinite(Number(value))) {
    return '—';
  }
  return `${Number(value).toFixed(Number(value) < 1 ? 3 : 1)} req/s`;
}

function formatCount(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return '—';
  }
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: number < 10 ? 1 : 0 }).format(number);
}

function formatTime(value) {
  if (!value) {
    return '尚未同步';
  }
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  }).format(new Date(value));
}

function rateTone(value, warning, critical) {
  if (value == null) return 'muted';
  if (value < critical) return 'critical';
  if (value < warning) return 'warning';
  return 'healthy';
}

function inverseRateTone(value, warning, critical) {
  if (value == null) return 'muted';
  if (value > critical) return 'critical';
  if (value > warning) return 'warning';
  return 'healthy';
}

function latencyTone(value) {
  if (value == null) return 'muted';
  if (value > 10) return 'critical';
  if (value > 3) return 'warning';
  return 'blue';
}

function breakdownValue(item) {
  if (item.key === 'dlq') {
    return `${formatCount(item.value)} 条`;
  }
  return `${formatCount(item.value)} 次`;
}

watch(range, loadData, { immediate: true });

onMounted(() => {
  refreshTimer = window.setInterval(() => {
    if (document.visibilityState === 'visible') {
      loadData();
    }
  }, 15_000);
});

onBeforeUnmount(() => window.clearInterval(refreshTimer));
</script>

<template>
  <section class="agent-operations-page" :aria-busy="loading">
    <header class="agent-operations-hero">
      <div class="agent-operations-heading">
        <span class="eyebrow">Agent Operations</span>
        <div class="agent-operations-title-row">
          <h1>Agent 运行中心</h1>
          <span :class="['agent-overall-pill', overall.tone]">
            <i></i>{{ overall.label }}
          </span>
        </div>
        <p>面向平台管理员的全局运行视图，统一观察 Agent 编排、RAG、工具调用与异步初审链路。</p>
      </div>

      <div class="agent-operations-actions">
        <div class="agent-range-switch" aria-label="监控时间范围">
          <button
            v-for="option in rangeOptions"
            :key="option.key"
            type="button"
            :class="{ active: range === option.key }"
            @click="range = option.key"
          >
            {{ option.label }}
          </button>
        </div>
        <button type="button" class="agent-action-button" :disabled="loading" @click="loadData">
          <span :class="{ spinning: loading }">↻</span>{{ loading ? '同步中' : '立即刷新' }}
        </button>
        <button type="button" class="agent-action-button primary" :disabled="!data?.grafanaUrl" @click="openGrafana">
          深入 Grafana ↗
        </button>
      </div>
    </header>

    <div v-if="errorMessage" class="agent-data-banner critical">
      <strong>页面数据请求失败</strong>
      <span>{{ errorMessage }}</span>
      <button type="button" @click="loadData">重试</button>
    </div>
    <div v-else-if="data?.dataStatus === 'UNAVAILABLE'" class="agent-data-banner warning">
      <strong>监控数据降级</strong>
      <span>Prometheus 暂不可用，页面未使用模拟数据；Java 业务接口是否可用需单独判断。</span>
      <button type="button" @click="loadData">重新连接</button>
    </div>

    <section class="agent-health-strip">
      <div class="agent-health-summary">
        <span :class="['agent-health-orb', overall.tone]"><i></i></span>
        <div>
          <strong>{{ overall.description }}</strong>
          <p>最近同步：{{ formatTime(data?.generatedAt) }} · 15 秒自动刷新</p>
        </div>
      </div>
      <div class="agent-target-list">
        <article v-for="target in data?.targets || []" :key="target.key" class="agent-target-item">
          <span :class="['agent-target-dot', target.status.toLowerCase()]"></span>
          <div>
            <strong>{{ target.label }}</strong>
            <p>{{ target.status === 'UP' ? 'Prometheus 采集正常' : target.status === 'DOWN' ? '采集目标离线' : '状态未知' }}</p>
          </div>
          <em>{{ target.status }}</em>
        </article>
        <article v-for="fact in runtimeFacts" :key="fact.label" class="agent-runtime-fact">
          <span>{{ fact.label }}</span>
          <strong :class="fact.tone">{{ fact.value }}</strong>
        </article>
      </div>
    </section>

    <section class="agent-metric-grid" aria-label="Agent 核心运行指标">
      <article v-for="item in metricCards" :key="item.key" :class="['agent-metric-card', item.tone]">
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
        <p>{{ item.detail }}</p>
      </article>
    </section>

    <section class="agent-chart-grid">
      <article class="agent-operations-panel">
        <header class="agent-panel-head">
          <div>
            <span class="eyebrow">Traffic</span>
            <h2>Agent 网关吞吐趋势</h2>
          </div>
          <span>按请求结果拆分</span>
        </header>
        <AgentLineChart :series="data?.throughputSeries || []" empty-text="所选时段暂无 Agent 网关请求" />
      </article>

      <article class="agent-operations-panel">
        <header class="agent-panel-head">
          <div>
            <span class="eyebrow">Latency</span>
            <h2>端到端 P95 延迟</h2>
          </div>
          <span>Java 网关 / Python Agent</span>
        </header>
        <AgentLineChart :series="data?.latencySeries || []" empty-text="所选时段暂无可计算的延迟样本" />
      </article>
    </section>

    <section class="agent-analysis-grid">
      <article class="agent-operations-panel agent-insight-panel">
        <header class="agent-panel-head">
          <div>
            <span class="eyebrow">Signal</span>
            <h2>运行诊断</h2>
          </div>
        </header>
        <div class="agent-insight-list">
          <article v-for="item in data?.insights || []" :key="item.title" :class="['agent-insight-item', item.level]">
            <i></i>
            <div>
              <strong>{{ item.title }}</strong>
              <p>{{ item.description }}</p>
            </div>
          </article>
          <div v-if="!data?.insights?.length" class="agent-breakdown-empty">等待第一批监控数据</div>
        </div>
      </article>

      <article class="agent-operations-panel">
        <header class="agent-panel-head">
          <div>
            <span class="eyebrow">RAG</span>
            <h2>检索模式分布</h2>
          </div>
        </header>
        <div class="agent-breakdown-list">
          <div v-for="item in data?.ragModes || []" :key="item.key" class="agent-breakdown-row">
            <div><strong>{{ item.label }}</strong><span>{{ breakdownValue(item) }}</span></div>
            <span class="agent-breakdown-track"><i :class="item.tone" :style="{ width: `${Math.max(3, (item.ratio || 0) * 100)}%` }"></i></span>
          </div>
          <div v-if="!data?.ragModes?.length" class="agent-breakdown-empty">所选时段暂无 RAG 检索记录</div>
        </div>
      </article>

      <article class="agent-operations-panel">
        <header class="agent-panel-head">
          <div>
            <span class="eyebrow">Tools</span>
            <h2>工具失败画像</h2>
          </div>
        </header>
        <div class="agent-breakdown-list">
          <div v-for="item in data?.toolFailures || []" :key="item.key" class="agent-breakdown-row">
            <div><strong>{{ item.label }}</strong><span>{{ breakdownValue(item) }} · {{ formatPercent(item.ratio) }}</span></div>
            <span class="agent-breakdown-track"><i class="red" :style="{ width: `${Math.max(3, (item.ratio || 0) * 100)}%` }"></i></span>
          </div>
          <div v-if="!data?.toolFailures?.length" class="agent-breakdown-empty">所选时段暂无工具失败记录</div>
        </div>
      </article>

      <article class="agent-operations-panel">
        <header class="agent-panel-head">
          <div>
            <span class="eyebrow">Review</span>
            <h2>AI 初审结论</h2>
          </div>
        </header>
        <div class="agent-breakdown-list">
          <div v-for="item in data?.reviewVerdicts || []" :key="item.key" class="agent-breakdown-row">
            <div><strong>{{ item.label }}</strong><span>{{ breakdownValue(item) }}</span></div>
            <span class="agent-breakdown-track"><i :class="item.tone" :style="{ width: `${Math.max(3, (item.ratio || 0) * 100)}%` }"></i></span>
          </div>
          <div v-if="!data?.reviewVerdicts?.length" class="agent-breakdown-empty">所选时段暂无 AI 初审记录</div>
        </div>
      </article>

      <article class="agent-operations-panel">
        <header class="agent-panel-head">
          <div>
            <span class="eyebrow">Reliability</span>
            <h2>Outbox / DLQ 可靠性</h2>
          </div>
        </header>
        <div class="agent-breakdown-list">
          <div v-for="item in data?.messageReliability || []" :key="item.key" class="agent-breakdown-row">
            <div><strong>{{ item.label }}</strong><span>{{ breakdownValue(item) }}</span></div>
            <span class="agent-breakdown-track"><i :class="item.tone" :style="{ width: `${Math.max(3, (item.ratio || 0) * 100)}%` }"></i></span>
          </div>
          <div v-if="!data?.messageReliability?.length" class="agent-breakdown-empty">所选时段暂无异步初审事件</div>
        </div>
      </article>
    </section>
  </section>
</template>

<style scoped>
.agent-operations-page {
  height: 100%;
  min-height: 0;
  display: grid;
  align-content: start;
  gap: 16px;
  padding: 2px 4px 18px 2px;
  overflow: auto;
  scrollbar-gutter: stable;
}

.agent-operations-hero,
.agent-health-strip,
.agent-metric-card,
.agent-operations-panel {
  border: 1px solid rgba(151, 170, 196, 0.2);
  background: var(--card-bg);
  box-shadow: 0 14px 34px rgba(15, 23, 42, 0.055);
}

.agent-operations-hero {
  min-height: 142px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 28px;
  padding: 24px;
  border-radius: 20px;
}

.agent-operations-heading {
  min-width: 0;
}

.agent-operations-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 3px;
}

.agent-operations-title-row h1 {
  margin: 0;
  color: var(--text-primary);
  font-size: 28px;
  line-height: 1.2;
}

.agent-operations-heading p {
  margin: 9px 0 0;
  color: var(--text-muted);
  font-size: 14px;
}

.agent-overall-pill,
.agent-target-item em {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  border-radius: 999px;
  padding: 6px 10px;
  font-size: 12px;
  font-style: normal;
  font-weight: 800;
}

.agent-overall-pill i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
}

.agent-overall-pill.healthy { color: #24784a; background: rgba(55, 166, 103, 0.12); }
.agent-overall-pill.warning { color: #9a6208; background: rgba(217, 150, 36, 0.14); }
.agent-overall-pill.critical { color: #b64230; background: rgba(220, 91, 69, 0.13); }
.agent-overall-pill.muted { color: var(--text-muted); background: var(--card-bg-soft); }

.agent-operations-actions {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  flex-wrap: wrap;
  gap: 9px;
  max-width: 590px;
}

.agent-range-switch {
  display: flex;
  gap: 3px;
  padding: 4px;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  background: var(--card-bg-soft);
}

.agent-range-switch button,
.agent-action-button {
  min-height: 36px;
  border: 0;
  border-radius: 7px;
  padding: 0 12px;
  color: var(--text-muted);
  background: transparent;
  font-size: 13px;
  font-weight: 750;
}

.agent-range-switch button.active {
  color: #bd560b;
  background: var(--card-bg);
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.08);
}

.agent-action-button {
  border: 1px solid var(--border-color);
  color: var(--text-secondary);
  background: var(--card-bg);
}

.agent-action-button.primary {
  border-color: #d96c24;
  color: #fff;
  background: #d96c24;
}

.agent-action-button span {
  display: inline-block;
  margin-right: 5px;
}

.agent-action-button span.spinning { animation: agent-spin 800ms linear infinite; }

.agent-data-banner {
  min-height: 52px;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  padding: 11px 14px;
  border-radius: 12px;
  font-size: 13px;
}

.agent-data-banner.warning { color: #81500b; background: rgba(217, 150, 36, 0.12); border: 1px solid rgba(217, 150, 36, 0.22); }
.agent-data-banner.critical { color: #9f3628; background: rgba(220, 91, 69, 0.11); border: 1px solid rgba(220, 91, 69, 0.2); }
.agent-data-banner button { border: 0; color: inherit; background: transparent; font-weight: 800; }

.agent-health-strip {
  display: grid;
  grid-template-columns: minmax(270px, 0.7fr) minmax(0, 1.6fr);
  align-items: center;
  gap: 20px;
  padding: 16px 18px;
  border-radius: 18px;
}

.agent-health-summary {
  display: flex;
  align-items: center;
  gap: 13px;
  min-width: 0;
}

.agent-health-summary strong { color: var(--text-primary); font-size: 14px; }
.agent-health-summary p { margin: 4px 0 0; color: var(--text-muted); font-size: 12px; }

.agent-health-orb {
  width: 42px;
  height: 42px;
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  border-radius: 13px;
  background: var(--card-bg-soft);
}

.agent-health-orb i { width: 12px; height: 12px; border-radius: 50%; background: currentColor; box-shadow: 0 0 0 6px color-mix(in srgb, currentColor 14%, transparent); }
.agent-health-orb.healthy { color: #2f9d68; }
.agent-health-orb.warning { color: #d99624; }
.agent-health-orb.critical { color: #dc5b45; }
.agent-health-orb.muted { color: #8d9aab; }

.agent-target-list {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.agent-target-item,
.agent-runtime-fact {
  min-height: 64px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: var(--card-bg-soft);
}

.agent-target-item {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 9px;
  padding: 10px 11px;
}

.agent-target-item strong { color: var(--text-primary); font-size: 13px; }
.agent-target-item p { margin: 3px 0 0; color: var(--text-muted); font-size: 10px; white-space: nowrap; }
.agent-target-item em { padding: 4px 6px; color: var(--text-muted); background: var(--card-bg); font-size: 9px; }

.agent-target-dot { width: 8px; height: 8px; border-radius: 50%; background: #91a0b1; }
.agent-target-dot.up { background: #2f9d68; box-shadow: 0 0 0 4px rgba(47, 157, 104, 0.12); }
.agent-target-dot.down { background: #dc5b45; box-shadow: 0 0 0 4px rgba(220, 91, 69, 0.12); }

.agent-runtime-fact {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 12px;
}

.agent-runtime-fact span { color: var(--text-muted); font-size: 12px; font-weight: 700; }
.agent-runtime-fact strong { color: var(--text-primary); font-size: 22px; }
.agent-runtime-fact strong.warning { color: #bd7a13; }
.agent-runtime-fact strong.critical { color: #c54a37; }
.agent-runtime-fact strong.healthy { color: #2d8a5c; }

.agent-metric-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 12px;
}

.agent-metric-card {
  min-height: 118px;
  position: relative;
  padding: 17px;
  border-radius: 16px;
  overflow: hidden;
}

.agent-metric-card::before {
  content: '';
  position: absolute;
  inset: 0 auto 0 0;
  width: 3px;
  background: #8b98a8;
}

.agent-metric-card.healthy::before { background: #2f9d68; }
.agent-metric-card.warning::before { background: #d99624; }
.agent-metric-card.critical::before { background: #dc5b45; }
.agent-metric-card.blue::before { background: #3e7ecb; }
.agent-metric-card.slate::before { background: #77869a; }
.agent-metric-card span { color: var(--text-muted); font-size: 12px; font-weight: 750; }
.agent-metric-card strong { display: block; margin-top: 12px; color: var(--text-primary); font-size: 25px; line-height: 1; white-space: nowrap; }
.agent-metric-card p { margin: 10px 0 0; color: var(--text-muted); font-size: 11px; }

.agent-chart-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.agent-operations-panel {
  min-width: 0;
  padding: 19px;
  border-radius: 18px;
}

.agent-panel-head {
  min-height: 44px;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.agent-panel-head h2 { margin: 1px 0 0; color: var(--text-primary); font-size: 17px; }
.agent-panel-head > span { color: var(--text-muted); font-size: 11px; }

.agent-analysis-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

.agent-insight-panel { grid-row: span 2; }

.agent-insight-list,
.agent-breakdown-list {
  display: grid;
  align-content: start;
  gap: 10px;
  margin-top: 12px;
}

.agent-insight-item {
  min-height: 70px;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 11px;
  padding: 13px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: var(--card-bg-soft);
}

.agent-insight-item > i { width: 9px; height: 9px; margin-top: 4px; border-radius: 50%; background: #8795a7; }
.agent-insight-item.healthy > i { background: #2f9d68; box-shadow: 0 0 0 4px rgba(47, 157, 104, 0.12); }
.agent-insight-item.warning > i { background: #d99624; box-shadow: 0 0 0 4px rgba(217, 150, 36, 0.12); }
.agent-insight-item.critical > i { background: #dc5b45; box-shadow: 0 0 0 4px rgba(220, 91, 69, 0.12); }
.agent-insight-item strong { color: var(--text-primary); font-size: 13px; }
.agent-insight-item p { margin: 5px 0 0; color: var(--text-muted); font-size: 11px; line-height: 1.55; }

.agent-breakdown-row { display: grid; gap: 8px; }
.agent-breakdown-row > div { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.agent-breakdown-row strong { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-primary); font-size: 12px; }
.agent-breakdown-row span { color: var(--text-muted); font-size: 11px; white-space: nowrap; }
.agent-breakdown-track { height: 7px; border-radius: 999px; background: var(--card-bg-soft); overflow: hidden; }
.agent-breakdown-track i { display: block; height: 100%; border-radius: inherit; background: #77869a; }
.agent-breakdown-track i.green { background: #2f9d68; }
.agent-breakdown-track i.amber { background: #d99624; }
.agent-breakdown-track i.red,
.agent-breakdown-track i.danger { background: #dc5b45; }
.agent-breakdown-track i.blue { background: #3e7ecb; }

.agent-breakdown-empty {
  min-height: 92px;
  display: grid;
  place-items: center;
  padding: 14px;
  border: 1px dashed var(--border-color);
  border-radius: 12px;
  color: var(--text-muted);
  background: var(--card-bg-soft);
  font-size: 12px;
}

@keyframes agent-spin { to { transform: rotate(360deg); } }

@media (max-width: 1480px) {
  .agent-metric-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .agent-target-list { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

:global(html[data-theme='dark']) .agent-operations-hero,
:global(html[data-theme='dark']) .agent-health-strip,
:global(html[data-theme='dark']) .agent-metric-card,
:global(html[data-theme='dark']) .agent-operations-panel {
  border-color: var(--border-color);
  box-shadow: 0 16px 38px rgba(2, 6, 23, 0.2);
}
</style>
