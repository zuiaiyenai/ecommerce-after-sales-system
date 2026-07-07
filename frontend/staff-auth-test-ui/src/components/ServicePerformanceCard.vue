<script setup>
import { computed } from 'vue';

const props = defineProps({
  performance: {
    type: Object,
    default: () => ({ metrics: [] })
  }
});

const serviceScore = 96;
const scoreStatus = '今日服务表现优秀';

const trendData = [
  { day: '周一', score: 91 },
  { day: '周二', score: 93 },
  { day: '周三', score: 92 },
  { day: '周四', score: 95 },
  { day: '周五', score: 94 },
  { day: '周六', score: 96 },
  { day: '周日', score: 96 }
];

const metricConfigs = [
  {
    key: 'handleTime',
    label: '平均处理时长',
    aliases: ['平均处理时长'],
    value: '6分30秒',
    targetText: '目标 ≤ 08:00',
    currentPercent: 100,
    targetPercent: 100,
    sampleSize: 3,
    lowerIsBetter: true
  },
  {
    key: 'satisfaction',
    label: '用户满意度',
    aliases: ['用户满意度'],
    value: '5.0/5',
    targetText: '目标 ≥ 4.5/5',
    currentPercent: 100,
    targetPercent: 90,
    sampleSize: 3,
    lowerIsBetter: false
  },
  {
    key: 'goodRate',
    label: '好评率',
    aliases: ['好评率'],
    value: '100%',
    targetText: '目标 ≥ 90%',
    currentPercent: 100,
    targetPercent: 90,
    sampleSize: 3,
    lowerIsBetter: false
  }
];

const scorePercent = computed(() => clampPercent(serviceScore));
const gaugeDash = computed(() => `${scorePercent.value} 100`);

const trendPoints = computed(() => {
  const width = 256;
  const height = 84;
  const padX = 12;
  const padTop = 10;
  const padBottom = 18;
  const scores = trendData.map((item) => item.score);
  let min = Math.min(...scores);
  let max = Math.max(...scores);

  if (max - min < 6) {
    const mid = (max + min) / 2;
    min = Math.max(0, mid - 3);
    max = Math.min(100, mid + 3);
  }

  const usableHeight = height - padTop - padBottom;
  const step = (width - padX * 2) / (trendData.length - 1);

  return trendData.map((item, index) => {
    const ratio = max === min ? 0.5 : (max - item.score) / (max - min);
    return {
      ...item,
      x: Number((padX + step * index).toFixed(1)),
      y: Number((padTop + ratio * usableHeight).toFixed(1))
    };
  });
});

const trendLine = computed(() => trendPoints.value.map((point) => `${point.x},${point.y}`).join(' '));
const trendArea = computed(() => {
  const points = trendPoints.value;
  const baseline = 66;
  return `${points[0].x},${baseline} ${trendLine.value} ${points[points.length - 1].x},${baseline}`;
});

const displayMetrics = computed(() => metricConfigs.map((config) => normalizeMetric(config)));

function normalizeMetric(config) {
  const source = findMetric(config);
  const hasSourceValue = hasMetricValue(source);
  const currentPercent = hasSourceValue ? source.currentPercent : config.currentPercent;
  const targetPercent = hasSourceValue ? source.targetPercent : config.targetPercent;

  return {
    ...config,
    value: hasSourceValue ? normalizeMetricValue(config, source.value) : config.value,
    currentPercent: clampPercent(currentPercent),
    targetPercent: clampPercent(targetPercent),
    sampleSize: hasSourceValue ? Number(source.sampleSize ?? config.sampleSize) : config.sampleSize,
    lowerIsBetter: Boolean(source?.lowerIsBetter ?? config.lowerIsBetter)
  };
}

function findMetric(config) {
  const metrics = Array.isArray(props.performance?.metrics) ? props.performance.metrics : [];
  return metrics.find((item) => config.aliases.some((alias) => String(item?.label || '').includes(alias)));
}

function hasMetricValue(item) {
  if (!item || item.value == null || item.value === '--') {
    return false;
  }
  return Number(item.sampleSize ?? 1) > 0;
}

function normalizeMetricValue(config, value) {
  if (config.key !== 'handleTime') {
    return value;
  }
  return normalizeDurationText(value);
}

function normalizeDurationText(value) {
  const text = String(value || '').trim();
  const match = text.match(/^(\d+):([0-5]\d)$/);

  if (!match) {
    return text;
  }

  const minutes = Number(match[1]);
  const seconds = Number(match[2]);

  if (minutes < 60) {
    return text;
  }

  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return `${hours}:${padTime(remainingMinutes)}:${padTime(seconds)}`;
}

function padTime(value) {
  return String(value).padStart(2, '0');
}

function clampPercent(value) {
  const percent = Number(value);
  if (!Number.isFinite(percent)) {
    return 0;
  }
  return Math.min(Math.max(percent, 0), 100);
}
</script>

<template>
  <div class="service-performance-card">
    <section class="score-panel" aria-label="服务综合分">
      <div class="score-gauge-wrap" aria-hidden="true">
        <svg class="score-gauge" viewBox="0 0 176 104" role="img">
          <path
            class="score-gauge-track"
            d="M24 86 A64 64 0 0 1 152 86"
            pathLength="100"
          />
          <path
            class="score-gauge-value"
            d="M24 86 A64 64 0 0 1 152 86"
            pathLength="100"
            :stroke-dasharray="gaugeDash"
          />
        </svg>
        <strong>{{ serviceScore }}</strong>
      </div>
      <div class="score-copy">
        <span>服务综合分</span>
        <p>{{ scoreStatus }}</p>
      </div>
    </section>

    <section class="trend-panel" aria-label="近7日趋势">
      <div class="section-title">
        <h3>近7日趋势</h3>
        <span>{{ trendData[0].score }} → {{ trendData[trendData.length - 1].score }}</span>
      </div>
      <svg class="trend-svg" viewBox="0 0 256 84" preserveAspectRatio="none" role="img" aria-label="近7日服务表现变化">
        <line class="trend-grid" x1="12" y1="18" x2="244" y2="18" />
        <line class="trend-grid" x1="12" y1="42" x2="244" y2="42" />
        <line class="trend-grid" x1="12" y1="66" x2="244" y2="66" />
        <polygon class="trend-area" :points="trendArea" />
        <polyline class="trend-line" :points="trendLine" />
        <circle
          v-for="point in trendPoints"
          :key="point.day"
          class="trend-point"
          :cx="point.x"
          :cy="point.y"
          r="2.8"
        />
      </svg>
      <div class="trend-days" aria-hidden="true">
        <span v-for="item in trendData" :key="item.day">{{ item.day.replace('周', '') }}</span>
      </div>
    </section>

    <section class="target-panel" aria-label="目标达成">
      <div
        v-for="item in displayMetrics"
        :key="item.key"
        class="target-row"
      >
        <span class="target-label">{{ item.label }}</span>
        <div class="target-track" aria-hidden="true">
          <i class="target-fill" :style="{ width: `${item.currentPercent}%` }"></i>
          <i class="target-marker" :style="{ left: `${item.targetPercent}%` }"></i>
        </div>
        <strong class="target-value">{{ item.value }}</strong>
        <em>{{ item.targetText }} · 样本 {{ item.sampleSize }}</em>
      </div>
    </section>
  </div>
</template>

<style scoped>
.service-performance-card {
  min-height: 0;
  height: 100%;
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
  gap: 12px;
  overflow: auto;
  padding-right: 4px;
}

.score-panel,
.trend-panel,
.target-row {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fbfcfe;
}

.score-panel {
  display: grid;
  grid-template-columns: 142px minmax(0, 1fr);
  align-items: center;
  gap: 14px;
  padding: 12px 14px;
  background:
    linear-gradient(135deg, rgba(243, 106, 16, 0.1), transparent 62%),
    #fbfcfe;
}

.score-gauge-wrap {
  position: relative;
  width: 142px;
  height: 86px;
  display: grid;
  place-items: end center;
}

.score-gauge {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  overflow: visible;
}

.score-gauge-track,
.score-gauge-value {
  fill: none;
  stroke-width: 15;
  stroke-linecap: round;
}

.score-gauge-track {
  stroke: #eceff3;
}

.score-gauge-value {
  stroke: var(--accent);
  filter: drop-shadow(0 8px 12px rgba(243, 106, 16, 0.2));
}

.score-gauge-wrap strong {
  position: relative;
  z-index: 1;
  color: var(--text);
  font-size: 34px;
  line-height: 1;
}

.score-copy {
  min-width: 0;
  display: grid;
  gap: 7px;
}

.score-copy span,
.section-title span,
.target-row em {
  color: var(--muted);
}

.score-copy span {
  font-size: 13px;
}

.score-copy p {
  margin: 0;
  color: #bf540b;
  font-size: 18px;
  font-weight: 800;
  line-height: 1.35;
}

.trend-panel {
  display: grid;
  gap: 8px;
  padding: 12px;
}

.section-title {
  min-width: 0;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
}

.section-title h3 {
  margin: 0;
  font-size: 15px;
}

.section-title span {
  flex: none;
  font-size: 12px;
}

.trend-svg {
  width: 100%;
  height: 84px;
  display: block;
}

.trend-grid {
  stroke: var(--line);
  stroke-width: 1;
  stroke-dasharray: 4 6;
  opacity: 0.78;
}

.trend-area {
  fill: rgba(243, 106, 16, 0.12);
}

.trend-line {
  fill: none;
  stroke: var(--accent);
  stroke-width: 3;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.trend-point {
  fill: var(--panel);
  stroke: var(--accent);
  stroke-width: 2;
}

.trend-days {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  color: var(--muted);
  font-size: 11px;
  text-align: center;
}

.target-panel {
  min-height: 0;
  display: grid;
  align-content: start;
  gap: 8px;
}

.target-row {
  min-width: 0;
  display: grid;
  grid-template-columns: 86px minmax(0, 1fr) auto;
  grid-template-rows: auto auto;
  align-items: center;
  gap: 7px 10px;
  padding: 10px 12px;
}

.target-label {
  color: var(--muted);
  font-size: 13px;
  white-space: nowrap;
}

.target-track {
  position: relative;
  min-width: 0;
  height: 14px;
  border-radius: 999px;
  overflow: visible;
  background: #e9edf2;
}

.target-fill {
  position: absolute;
  inset: 0 auto 0 0;
  border-radius: inherit;
  background: linear-gradient(90deg, #ffb36f, var(--accent));
}

.target-marker {
  position: absolute;
  top: -4px;
  bottom: -4px;
  width: 3px;
  transform: translateX(-50%);
  border-radius: 999px;
  background: #747c87;
  box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.72);
}

.target-value {
  justify-self: end;
  color: var(--text);
  font-size: 18px;
  line-height: 1;
  white-space: nowrap;
}

.target-row em {
  grid-column: 2 / 4;
  font-size: 12px;
  font-style: normal;
}

:global(html[data-theme="dark"]) .score-panel,
:global(html[data-theme="dark"]) .trend-panel,
:global(html[data-theme="dark"]) .target-row {
  background: #111a27;
}

:global(html[data-theme="dark"]) .score-panel {
  background:
    linear-gradient(135deg, rgba(255, 138, 61, 0.13), transparent 62%),
    #111a27;
}

:global(html[data-theme="dark"]) .score-gauge-track,
:global(html[data-theme="dark"]) .target-track {
  background: #263244;
  stroke: #263244;
}

:global(html[data-theme="dark"]) .score-copy p {
  color: #ffad73;
}

:global(html[data-theme="dark"]) .target-marker {
  background: #aab4c2;
  box-shadow: 0 0 0 2px rgba(17, 26, 39, 0.82);
}

@media (max-width: 520px) {
  .score-panel {
    grid-template-columns: minmax(0, 1fr);
    justify-items: center;
    text-align: center;
  }

  .target-row {
    grid-template-columns: minmax(0, 1fr) auto;
  }

  .target-track,
  .target-row em {
    grid-column: 1 / 3;
  }
}
</style>
