<script setup>
import { computed, ref } from 'vue';

const props = defineProps({
  performance: {
    type: Object,
    default: () => ({ metrics: [] })
  }
});

const metricConfigs = [
  {
    key: 'avgResponseTime',
    label: '平均响应时长',
    aliases: ['平均响应时长'],
    value: '--',
    targetText: '目标 ≤ 5分钟',
    goalText: '响应更快，体验更稳',
    currentPercent: 0,
    targetPercent: 100,
    sampleSize: 0,
    lowerIsBetter: true
  },
  {
    key: 'satisfaction',
    label: '用户满意度',
    aliases: ['用户满意度'],
    value: '--',
    targetText: '目标 ≥ 4.5 / 5（基于真实评价）',
    goalText: '真实评价体验保持高位',
    currentPercent: 0,
    targetPercent: 90,
    sampleSize: 0,
    lowerIsBetter: false
  },
  {
    key: 'goodRate',
    label: '好评率',
    aliases: ['好评率'],
    value: '--',
    targetText: '目标 ≥ 90%（基于真实评价）',
    goalText: '真实评价正向反馈占比',
    currentPercent: 0,
    targetPercent: 90,
    sampleSize: 0,
    lowerIsBetter: false
  }
];

const activeTrendIndex = ref(null);
const trendChartWidth = 420;
const trendChartHeight = 148;
const trendChartPadding = {
  left: 28,
  right: 28,
  top: 32,
  bottom: 28
};
const trendChartBaseline = trendChartHeight - trendChartPadding.bottom;
const trendScoreFloor = 80;
const trendScoreCeiling = 100;
const trendGridLines = computed(() => {
  const plotHeight = trendChartHeight - trendChartPadding.top - trendChartPadding.bottom;
  const lineCount = 4;
  return Array.from({ length: lineCount }, (_, index) => {
    const y = trendChartPadding.top + (plotHeight / (lineCount - 1)) * index;
    return Number(y.toFixed(1));
  });
});

const hasPerformanceData = computed(() => {
  const metrics = Array.isArray(props.performance?.metrics) ? props.performance.metrics : [];
  return metrics.some((item) => hasMetricValue(item));
});

const trendData = computed(() => {
  const source = hasPerformanceData.value && Array.isArray(props.performance?.trend)
    ? props.performance.trend
    : [];
  return source.map((item, index) => ({
    day: item?.day || `第${index + 1}天`,
    score: clampPercent(item?.score)
  }));
});

const serviceScore = computed(() => {
  if (!hasPerformanceData.value) {
    return null;
  }
  const fromApi = Number(props.performance?.serviceScore);
  if (Number.isFinite(fromApi)) {
    return clampPercent(fromApi);
  }
  const metrics = Array.isArray(props.performance?.metrics) ? props.performance.metrics : [];
  const available = metrics
    .map((item) => Number(item?.currentPercent))
    .filter((value) => Number.isFinite(value) && value > 0);
  if (!available.length) {
    return null;
  }
  return clampPercent(Math.round(available.reduce((sum, value) => sum + value, 0) / available.length));
});

const scoreStatus = computed(() => {
  if (!hasPerformanceData.value) {
    return '暂无服务表现数据';
  }
  if (props.performance?.scoreStatus) {
    return props.performance.scoreStatus;
  }
  if (serviceScore.value >= 90) {
    return '今日服务表现优秀';
  }
  if (serviceScore.value >= 75) {
    return '今日服务表现稳定';
  }
  if (serviceScore.value > 0) {
    return '今日服务表现待提升';
  }
  return '暂无服务表现数据';
});

const scoreTags = computed(() => {
  if (!hasPerformanceData.value) {
    return ['暂无数据'];
  }
  if (Array.isArray(props.performance?.tags) && props.performance.tags.length) {
    return props.performance.tags;
  }
  return [];
});

const scorePercent = computed(() => clampPercent(serviceScore.value));
const gaugeDash = computed(() => `${scorePercent.value} 100`);
const trendLift = computed(() => {
  const data = trendData.value;
  if (data.length < 2) {
    return 0;
  }
  return data[data.length - 1].score - data[0].score;
});
const trendSummary = computed(() => {
  if (!trendData.value.length) {
    return '近7日暂无数据';
  }
  if (props.performance?.trendSummary) {
    return props.performance.trendSummary;
  }
  if (trendLift.value > 0) {
    return `本周提升 +${trendLift.value}`;
  }
  if (trendLift.value < 0) {
    return `本周下降 ${trendLift.value}`;
  }
  return '本周持平';
});

const trendPoints = computed(() => {
  const data = trendData.value;
  if (!data.length) {
    return [];
  }
  const scores = data.map((item) => item.score);
  const min = Math.min(trendScoreFloor, ...scores);
  const max = Math.max(trendScoreCeiling, ...scores);
  const plotWidth = trendChartWidth - trendChartPadding.left - trendChartPadding.right;
  const plotHeight = trendChartHeight - trendChartPadding.top - trendChartPadding.bottom;
  const step = data.length > 1 ? plotWidth / (data.length - 1) : 0;

  return data.map((item, index) => {
    const ratio = max === min ? 0.5 : (max - item.score) / (max - min);
    const x = data.length > 1
      ? trendChartPadding.left + step * index
      : trendChartPadding.left + plotWidth / 2;
    return {
      ...item,
      x: Number(x.toFixed(1)),
      y: Number((trendChartPadding.top + ratio * plotHeight).toFixed(1))
    };
  });
});

const trendLine = computed(() => trendPoints.value.map((point) => `${point.x},${point.y}`).join(' '));
const trendArea = computed(() => {
  const points = trendPoints.value;
  if (!points.length) {
    return '';
  }
  const baseline = trendChartBaseline;
  return `${points[0].x},${baseline} ${trendLine.value} ${points[points.length - 1].x},${baseline}`;
});
const activeTrendPoint = computed(() => {
  if (activeTrendIndex.value == null) {
    return null;
  }
  return trendPoints.value[activeTrendIndex.value] || null;
});

const displayMetrics = computed(() => metricConfigs.map((config) => normalizeMetric(config)));

function normalizeMetric(config) {
  const source = findMetric(config);
  const hasSource = Boolean(source);
  const hasSourceValue = hasMetricValue(source);
  const currentPercent = hasSourceValue ? source.currentPercent : 0;
  const targetPercent = hasSource ? source.targetPercent : config.targetPercent;
  const sampleSize = hasSource ? Number(source.sampleSize ?? 0) : 0;
  const normalized = {
    ...config,
    value: hasSourceValue ? normalizeMetricValue(config, source.value) : (hasSource ? source.value || '--' : config.value),
    currentPercent: clampPercent(currentPercent),
    targetPercent: clampPercent(targetPercent),
    sampleSize: Number.isFinite(sampleSize) ? sampleSize : 0,
    lowerIsBetter: Boolean(source?.lowerIsBetter ?? config.lowerIsBetter),
    hasData: hasSource && hasSourceValue
  };
  const reached = normalized.hasData && isTargetReached(normalized);

  return {
    ...normalized,
    rawDesc: source?.desc || config.targetText,
    targetText: targetTextFor(config),
    statusText: statusTextFor(config, normalized, reached),
    statusTone: statusToneFor(normalized, reached),
    progressLabel: `${normalized.label}当前进度 ${normalized.currentPercent}%`
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
  // 当 sampleSize 为 0 时也视为无数据
  const sample = Number(item.sampleSize ?? 1);
  if (sample === 0) {
    return false;
  }
  return sample > 0;
}

function normalizeMetricValue(config, value) {
  if (config.key === 'avgResponseTime') {
    return normalizeDurationText(value);
  }
  if (config.key === 'satisfaction') {
    return normalizeSatisfactionText(value);
  }
  if (config.key === 'goodRate') {
    return normalizeRateText(value);
  }
  return value;
}

function normalizeDurationText(value) {
  const text = String(value || '').trim();
  const seconds = durationToSeconds(text);

  if (seconds == null) {
    return text;
  }
  return formatDuration(seconds);
}

function durationToSeconds(text) {
  const normalized = String(text || '').trim();
  if (!normalized) {
    return null;
  }

  const colonParts = normalized.split(':');
  if (colonParts.length === 2 && colonParts.every((part) => /^\d+$/.test(part))) {
    return Number(colonParts[0]) * 60 + Number(colonParts[1]);
  }
  if (colonParts.length === 3 && colonParts.every((part) => /^\d+$/.test(part))) {
    return Number(colonParts[0]) * 3600 + Number(colonParts[1]) * 60 + Number(colonParts[2]);
  }

  const hourMatch = normalized.match(/(\d+(?:\.\d+)?)\s*(?:小时|时|h)/i);
  const minuteMatch = normalized.match(/(\d+(?:\.\d+)?)\s*(?:分钟|分|m(?!s))/i);
  const secondMatch = normalized.match(/(\d+(?:\.\d+)?)\s*(?:秒|s)/i);
  if (hourMatch || minuteMatch || secondMatch) {
    return Math.round(
      Number(hourMatch?.[1] || 0) * 3600 +
      Number(minuteMatch?.[1] || 0) * 60 +
      Number(secondMatch?.[1] || 0)
    );
  }

  return null;
}

function formatDuration(seconds) {
  const safeSeconds = Math.max(Math.round(seconds), 0);
  const hours = Math.floor(safeSeconds / 3600);
  const minutes = Math.floor((safeSeconds % 3600) / 60);
  const remainingSeconds = safeSeconds % 60;

  if (hours > 0) {
    return `${hours}小时${minutes}分${remainingSeconds}秒`;
  }
  if (minutes > 0) {
    return `${minutes}分${remainingSeconds}秒`;
  }
  return `${remainingSeconds}秒`;
}

function normalizeSatisfactionText(value) {
  const text = String(value || '').trim();
  const match = text.match(/(\d+(?:\.\d+)?)/);
  if (!match) {
    return text;
  }
  return `${Number(match[1]).toFixed(1)} / 5`;
}

function normalizeRateText(value) {
  const text = String(value || '').trim();
  const match = text.match(/(\d+(?:\.\d+)?)/);
  if (!match) {
    return text;
  }
  return `${Number(match[1]).toFixed(Number(match[1]) % 1 === 0 ? 0 : 1)}%`;
}

function targetTextFor(config) {
  if (config.key === 'avgResponseTime') {
    return '目标 ≤ 5分钟';
  }
  return config.targetText;
}

function isTargetReached(metric) {
  if (metric.lowerIsBetter) {
    return metric.currentPercent >= metric.targetPercent;
  }
  return metric.currentPercent >= metric.targetPercent;
}

function statusTextFor(config, metric, reached) {
  if (!metric.hasData) {
    return '暂无样本';
  }
  if (!reached) {
    return '需关注';
  }
  return config.key === 'satisfaction' || config.key === 'goodRate' ? '优秀' : '达标';
}

function statusToneFor(metric, reached) {
  if (!metric.hasData) {
    return 'empty';
  }
  return reached ? 'success' : 'warn';
}

function clampPercent(value) {
  if (value == null) {
    return 0;
  }
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
        <svg class="score-gauge" viewBox="0 0 188 122" role="img">
          <defs>
            <linearGradient id="serviceGaugeGradient" x1="24" y1="94" x2="164" y2="24" gradientUnits="userSpaceOnUse">
              <stop offset="0%" stop-color="#ffd4a8" />
              <stop offset="48%" stop-color="#ff9b50" />
              <stop offset="100%" stop-color="#ff6b1a" />
            </linearGradient>
          </defs>
          <path
            class="score-gauge-track"
            d="M26 94 A68 68 0 0 1 162 94"
            pathLength="100"
          />
          <path
            class="score-gauge-value"
            d="M26 94 A68 68 0 0 1 162 94"
            pathLength="100"
            :stroke-dasharray="gaugeDash"
          />
        </svg>
        <span class="score-halo"></span>
        <strong>{{ serviceScore ?? '--' }}</strong>
        <small>分</small>
      </div>
      <div class="score-copy">
        <span>服务综合分</span>
        <p>{{ scoreStatus }}</p>
        <em>{{ trendSummary }}<template v-if="scoreTags[1]"> · {{ scoreTags[1] }}</template></em>
        <div class="score-tags" aria-label="服务状态">
          <b v-for="tag in scoreTags" :key="tag">{{ tag }}</b>
        </div>
      </div>
    </section>

    <section class="trend-panel" aria-label="近7日趋势">
      <div class="section-title">
        <div>
          <h3>近7日趋势</h3>
          <small>{{ trendData[0]?.score ?? '--' }} → {{ trendData[trendData.length - 1]?.score ?? '--' }}</small>
        </div>
        <span>{{ trendSummary }}</span>
      </div>
      <div v-if="trendPoints.length" class="trend-chart">
        <svg
          class="trend-svg"
          :viewBox="`0 0 ${trendChartWidth} ${trendChartHeight}`"
          preserveAspectRatio="none"
          role="img"
          aria-label="近7日服务表现变化"
        >
          <defs>
            <linearGradient
              id="serviceTrendLineGradient"
              :x1="trendChartPadding.left"
              y1="0"
              :x2="trendChartWidth - trendChartPadding.right"
              y2="0"
              gradientUnits="userSpaceOnUse"
            >
              <stop offset="0%" stop-color="#ffc07a" />
              <stop offset="100%" stop-color="#ff6b1a" />
            </linearGradient>
            <linearGradient id="serviceTrendAreaGradient" x1="0" y1="16" x2="0" y2="96" gradientUnits="userSpaceOnUse">
              <stop offset="0%" stop-color="#ff8a3d" stop-opacity="0.2" />
              <stop offset="100%" stop-color="#ff8a3d" stop-opacity="0.02" />
            </linearGradient>
          </defs>
          <line
            v-for="lineY in trendGridLines"
            :key="lineY"
            class="trend-grid"
            :x1="trendChartPadding.left"
            :y1="lineY"
            :x2="trendChartWidth - trendChartPadding.right"
            :y2="lineY"
          />
          <polygon class="trend-area" :points="trendArea" />
          <polyline class="trend-line trend-line-shadow" :points="trendLine" />
          <polyline class="trend-line" :points="trendLine" />
          <g
            v-for="(point, index) in trendPoints"
            :key="point.day"
            class="trend-point-group"
            tabindex="0"
            role="button"
            :aria-label="`${point.day} ${point.score}分`"
            @mouseenter="activeTrendIndex = index"
            @mouseleave="activeTrendIndex = null"
            @focus="activeTrendIndex = index"
            @blur="activeTrendIndex = null"
          >
            <circle class="trend-hit" :cx="point.x" :cy="point.y" r="10" />
            <circle class="trend-point" :cx="point.x" :cy="point.y" r="3.6" />
          </g>
        </svg>
        <div
          v-if="activeTrendPoint"
          class="trend-tooltip"
          :style="{
            left: `${(activeTrendPoint.x / trendChartWidth) * 100}%`,
            top: `${(activeTrendPoint.y / trendChartHeight) * 100}%`
          }"
        >
          <span>{{ activeTrendPoint.day }}</span>
          <strong>{{ activeTrendPoint.score }} 分</strong>
        </div>
      </div>
      <div v-else class="trend-empty">近 7 日暂无评价或响应样本</div>
      <div v-if="trendPoints.length" class="trend-days" aria-hidden="true">
        <span
          v-for="point in trendPoints"
          :key="point.day"
          :style="{ left: `${(point.x / trendChartWidth) * 100}%` }"
        >
          {{ point.day.replace('周', '') }}
        </span>
      </div>
    </section>

    <section class="target-panel" aria-label="目标达成">
      <article
        v-for="item in displayMetrics"
        :key="item.key"
        :class="['target-card', `target-card-${item.key}`, item.statusTone]"
      >
        <div class="target-card-head">
          <div>
            <span class="target-label">{{ item.label }}</span>
            <em>{{ item.targetText }}</em>
          </div>
          <strong class="target-value">{{ item.value }}</strong>
        </div>
        <div class="target-track" role="img" :aria-label="item.progressLabel">
          <i class="target-fill" :style="{ width: `${item.currentPercent}%` }"></i>
          <i class="target-marker" :style="{ left: `${item.targetPercent}%` }"></i>
        </div>
        <div class="target-card-foot">
          <span>{{ item.goalText }} · 样本 {{ item.sampleSize }}</span>
          <b :class="['target-status', item.statusTone]">{{ item.statusText }}</b>
        </div>
      </article>
    </section>
  </div>
</template>

<style scoped>
.service-performance-card {
  min-height: 0;
  height: 100%;
  container-type: inline-size;
  display: grid;
  grid-template-rows: auto minmax(208px, 1fr) auto;
  gap: 18px;
  overflow: auto;
  padding: 2px 4px 8px 0;
}

.score-panel,
.trend-panel,
.target-card {
  position: relative;
  min-width: 0;
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-md);
  background: rgba(255, 255, 255, 0.56);
  -webkit-backdrop-filter: blur(18px);
  backdrop-filter: blur(18px);
  box-shadow: 0 14px 34px rgba(31, 41, 55, 0.08);
  transition:
    transform 180ms ease,
    box-shadow 180ms ease,
    border-color 180ms ease,
    background 180ms ease;
}

.score-panel:hover,
.trend-panel:hover,
.target-card:hover {
  transform: translateY(-2px);
  border-color: rgba(255, 138, 61, 0.3);
  box-shadow: 0 18px 42px rgba(255, 107, 26, 0.12), var(--glass-shadow-hover);
}

.score-panel {
  isolation: isolate;
  display: grid;
  grid-template-columns: 158px minmax(0, 1fr);
  align-items: center;
  gap: 18px;
  overflow: hidden;
  padding: 16px 18px;
  background:
    radial-gradient(circle at 18% 20%, rgba(255, 176, 105, 0.28), transparent 34%),
    linear-gradient(135deg, rgba(255, 138, 61, 0.14), rgba(255, 255, 255, 0.58) 58%),
    rgba(255, 255, 255, 0.62);
}

.score-panel::after {
  content: "";
  position: absolute;
  inset: auto -44px -58px auto;
  width: 150px;
  height: 150px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(255, 138, 61, 0.18), transparent 66%);
  pointer-events: none;
  z-index: -1;
}

.score-gauge-wrap {
  position: relative;
  width: 158px;
  height: 108px;
  display: grid;
  place-items: center;
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
  stroke-width: 16;
  stroke-linecap: round;
}

.score-gauge-track {
  stroke: rgba(226, 232, 240, 0.9);
}

.score-gauge-value {
  stroke: url("#serviceGaugeGradient");
  filter: drop-shadow(0 8px 12px rgba(255, 107, 26, 0.3));
  animation: gaugeDraw 720ms cubic-bezier(0.22, 1, 0.36, 1) both;
}

.score-halo {
  position: absolute;
  bottom: 18px;
  width: 76px;
  height: 38px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(255, 138, 61, 0.18), transparent 68%);
  filter: blur(2px);
}

.score-gauge-wrap strong {
  grid-area: 1 / 1;
  position: relative;
  z-index: 1;
  color: var(--text);
  font-size: 42px;
  line-height: 0.94;
  letter-spacing: 0;
  transform: translateY(1px);
}

.score-gauge-wrap small {
  grid-area: 1 / 1;
  position: relative;
  z-index: 1;
  margin: 0;
  color: #c45009;
  font-size: 12px;
  font-weight: 800;
  transform: translateY(34px);
}

.score-copy {
  min-width: 0;
  display: grid;
  gap: 7px;
}

.score-copy span,
.score-copy em,
.section-title span,
.section-title small,
.target-card em,
.target-card-foot span,
.trend-days {
  color: var(--muted);
}

.score-copy span {
  font-size: 13px;
  font-weight: 700;
}

.score-copy p {
  margin: 0;
  color: #b94a08;
  font-size: 20px;
  font-weight: 900;
  line-height: 1.25;
}

.score-copy em {
  font-size: 12px;
  font-style: normal;
}

.score-tags {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
  margin-top: 2px;
}

.score-tags b,
.target-status {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 800;
  line-height: 1;
}

.score-tags b {
  padding: 6px 9px;
  color: #a84808;
  background: rgba(255, 233, 216, 0.88);
  box-shadow: inset 0 0 0 1px rgba(255, 138, 61, 0.16);
}

.trend-panel {
  isolation: isolate;
  min-height: 0;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  gap: 10px;
  margin-bottom: 2px;
  padding: 14px 14px 12px;
  overflow: hidden;
}

.section-title,
.trend-chart,
.trend-days {
  position: relative;
  z-index: 1;
}

.section-title {
  min-width: 0;
  display: flex;
  justify-content: space-between;
  align-items: start;
  gap: 12px;
}

.section-title div {
  min-width: 0;
  display: grid;
  gap: 3px;
}

.section-title h3 {
  margin: 0;
  color: var(--text);
  font-size: 15px;
}

.section-title span {
  flex: none;
  border-radius: 999px;
  padding: 6px 9px;
  color: #b94a08;
  font-size: 12px;
  font-weight: 800;
  background: rgba(255, 241, 230, 0.88);
}

.section-title small {
  font-size: 12px;
}

.trend-chart {
  position: relative;
  min-width: 0;
  min-height: 148px;
  height: 100%;
  display: grid;
  overflow: hidden;
}

.trend-empty {
  min-height: 148px;
  display: grid;
  place-items: center;
  color: var(--muted);
  font-size: 13px;
}

.trend-svg {
  width: 100%;
  min-height: 148px;
  height: 100%;
  display: block;
  overflow: hidden;
}

.trend-grid {
  stroke: rgba(148, 163, 184, 0.26);
  stroke-width: 1;
  stroke-dasharray: 3 7;
}

.trend-area {
  fill: url("#serviceTrendAreaGradient");
}

.trend-line {
  fill: none;
  stroke: url("#serviceTrendLineGradient");
  stroke-width: 3.2;
  stroke-linecap: round;
  stroke-linejoin: round;
  vector-effect: non-scaling-stroke;
  animation: trendDraw 820ms ease-out both;
}

.trend-line-shadow {
  stroke: rgba(255, 107, 26, 0.18);
  stroke-width: 8;
  filter: blur(4px);
}

.trend-point-group {
  outline: none;
  cursor: pointer;
}

.trend-hit {
  fill: transparent;
}

.trend-point {
  fill: rgba(255, 255, 255, 0.96);
  stroke: #ff7a24;
  stroke-width: 2.2;
  vector-effect: non-scaling-stroke;
  filter: drop-shadow(0 4px 8px rgba(255, 107, 26, 0.18));
  transition: r 160ms ease, stroke-width 160ms ease, filter 160ms ease;
}

.trend-point-group:hover .trend-point,
.trend-point-group:focus .trend-point {
  r: 4.8;
  stroke-width: 2.8;
  filter: drop-shadow(0 6px 12px rgba(255, 107, 26, 0.28));
}

.trend-tooltip {
  position: absolute;
  z-index: 3;
  min-width: 72px;
  transform: translate(-50%, calc(-100% - 12px));
  border: 1px solid rgba(255, 138, 61, 0.18);
  border-radius: 12px;
  padding: 8px 10px;
  color: var(--text);
  text-align: center;
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 14px 30px rgba(31, 41, 55, 0.14);
  pointer-events: none;
}

.trend-tooltip::after {
  content: "";
  position: absolute;
  left: 50%;
  bottom: -5px;
  width: 10px;
  height: 10px;
  transform: translateX(-50%) rotate(45deg);
  background: inherit;
  border-right: 1px solid rgba(255, 138, 61, 0.18);
  border-bottom: 1px solid rgba(255, 138, 61, 0.18);
}

.trend-tooltip span {
  display: block;
  color: var(--muted);
  font-size: 11px;
}

.trend-tooltip strong {
  display: block;
  margin-top: 2px;
  color: #b94a08;
  font-size: 14px;
}

.trend-days {
  height: 16px;
  font-size: 11px;
  line-height: 16px;
  text-align: center;
}

.trend-days span {
  position: absolute;
  top: 0;
  min-width: 16px;
  transform: translateX(-50%);
  white-space: nowrap;
}

.target-panel {
  min-height: 0;
  align-self: stretch;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  align-content: end;
  gap: 10px;
  margin-top: 2px;
}

.target-card {
  isolation: isolate;
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
  gap: 12px;
  min-height: 146px;
  padding: 14px;
  overflow: hidden;
  background:
    linear-gradient(135deg, rgba(255, 138, 61, 0.11), rgba(255, 255, 255, 0.18) 56%),
    rgba(255, 255, 255, 0.58);
}

.target-card::after {
  content: "";
  position: absolute;
  right: -28px;
  top: -32px;
  width: 92px;
  height: 92px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(255, 138, 61, 0.13), transparent 68%);
  pointer-events: none;
  z-index: -1;
}

.target-card-head,
.target-card-foot {
  min-width: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  justify-content: space-between;
  align-items: start;
  gap: 10px;
}

.target-card-head div {
  min-width: 0;
  display: grid;
  gap: 4px;
}

.target-label {
  color: var(--muted);
  font-size: 13px;
  font-weight: 800;
  white-space: nowrap;
}

.target-card em {
  font-size: 12px;
  font-style: normal;
  white-space: nowrap;
}

.target-value {
  justify-self: end;
  min-width: 0;
  color: var(--text);
  font-size: 22px;
  line-height: 1;
  white-space: nowrap;
  overflow-wrap: anywhere;
}

.target-card-avgResponseTime .target-card-head {
  grid-template-columns: minmax(0, 1fr);
  gap: 7px;
}

.target-card-avgResponseTime .target-value {
  justify-self: start;
  font-size: 21px;
}

.target-track {
  position: relative;
  min-width: 0;
  height: 12px;
  border-radius: 999px;
  overflow: visible;
  background: rgba(226, 232, 240, 0.84);
  box-shadow: inset 0 1px 2px rgba(31, 41, 55, 0.08);
}

.target-fill {
  position: absolute;
  inset: 0 auto 0 0;
  border-radius: inherit;
  background: linear-gradient(90deg, #ffd2a3, #ff9b50 48%, #ff6b1a);
  box-shadow: 0 6px 14px rgba(255, 107, 26, 0.18);
  animation: barGrow 760ms cubic-bezier(0.22, 1, 0.36, 1) both;
  transform-origin: left center;
}

.target-marker {
  position: absolute;
  top: -6px;
  bottom: -6px;
  width: 3px;
  transform: translateX(-50%);
  border-radius: 999px;
  background: #6f7b8a;
  box-shadow: 0 0 0 3px rgba(255, 255, 255, 0.78);
}

.target-card-foot {
  align-self: end;
  align-items: center;
}

.target-card-foot span {
  min-width: 0;
  font-size: 12px;
  line-height: 1.4;
}

.target-status {
  flex: none;
  padding: 6px 8px;
}

.target-status.success {
  color: #24784a;
  background: rgba(232, 247, 239, 0.9);
}

.target-status.warn {
  color: #a84808;
  background: rgba(255, 239, 224, 0.92);
}

.target-status.empty {
  color: var(--muted);
  background: rgba(226, 232, 240, 0.72);
}

.target-card.warn .target-fill {
  background: linear-gradient(90deg, #ffd08f, #ff9b50);
}

.target-card.empty .target-fill {
  background: linear-gradient(90deg, #d8e0ea, #b8c3d1);
  box-shadow: none;
}

:global(html[data-theme="dark"] .performance-panel:has(.service-performance-card)) {
  border-color: rgba(255, 255, 255, 0.12);
  background:
    radial-gradient(circle at 18% 6%, rgba(255, 138, 61, 0.12), transparent 30%),
    radial-gradient(circle at 86% 34%, rgba(255, 107, 26, 0.09), transparent 34%),
    linear-gradient(145deg, rgba(255, 255, 255, 0.055), rgba(255, 255, 255, 0.022)),
    rgba(7, 13, 22, 0.88);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.08),
    0 24px 70px rgba(0, 0, 0, 0.38);
}

:global(html[data-theme="dark"] .service-performance-card ){
  scrollbar-color: rgba(255, 138, 61, 0.42) rgba(255, 255, 255, 0.08);
}

:global(html[data-theme="dark"] .service-performance-card .score-panel),
:global(html[data-theme="dark"] .service-performance-card .trend-panel),
:global(html[data-theme="dark"] .service-performance-card .target-card ){
  border-color: rgba(255, 255, 255, 0.12);
  background:
    linear-gradient(145deg, rgba(255, 255, 255, 0.095), rgba(255, 255, 255, 0.032)),
    rgba(10, 18, 30, 0.74);
  -webkit-backdrop-filter: blur(24px) saturate(135%);
  backdrop-filter: blur(24px) saturate(135%);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.1),
    0 20px 52px rgba(0, 0, 0, 0.38),
    0 0 38px rgba(255, 107, 26, 0.055);
}

:global(html[data-theme="dark"] .service-performance-card .score-panel ){
  background:
    radial-gradient(circle at 17% 34%, rgba(255, 158, 86, 0.28), transparent 34%),
    radial-gradient(circle at 88% 72%, rgba(255, 107, 26, 0.12), transparent 32%),
    linear-gradient(135deg, rgba(255, 255, 255, 0.12), rgba(255, 255, 255, 0.035) 54%),
    linear-gradient(135deg, rgba(19, 30, 47, 0.92), rgba(8, 14, 24, 0.92));
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.13),
    0 22px 58px rgba(0, 0, 0, 0.42),
    0 0 46px rgba(255, 107, 26, 0.09);
}

:global(html[data-theme="dark"] .service-performance-card .trend-panel ){
  background:
    radial-gradient(circle at 73% 42%, rgba(255, 107, 26, 0.13), transparent 36%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.085), rgba(255, 255, 255, 0.028)),
    rgba(9, 17, 29, 0.78);
}

:global(html[data-theme="dark"] .service-performance-card .trend-panel::before ){
  content: none;
}

:global(html[data-theme="dark"] .service-performance-card .target-card ){
  background:
    radial-gradient(circle at 86% 12%, rgba(255, 138, 61, 0.16), transparent 34%),
    linear-gradient(145deg, rgba(255, 255, 255, 0.09), rgba(255, 255, 255, 0.026)),
    rgba(10, 18, 30, 0.76);
}

:global(html[data-theme="dark"] .service-performance-card .target-card::after ){
  width: 118px;
  height: 118px;
  right: -42px;
  top: -48px;
  background: radial-gradient(circle, rgba(255, 138, 61, 0.2), transparent 66%);
}

:global(html[data-theme="dark"] .service-performance-card .score-panel:hover),
:global(html[data-theme="dark"] .service-performance-card .trend-panel:hover),
:global(html[data-theme="dark"] .service-performance-card .target-card:hover ){
  border-color: rgba(255, 155, 80, 0.36);
  background:
    linear-gradient(145deg, rgba(255, 255, 255, 0.12), rgba(255, 255, 255, 0.042)),
    rgba(15, 25, 40, 0.84);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.13),
    0 24px 62px rgba(0, 0, 0, 0.44),
    0 0 44px rgba(255, 107, 26, 0.12);
}

:global(html[data-theme="dark"] .service-performance-card .score-gauge-track ){
  stroke: rgba(220, 230, 244, 0.15);
}

:global(html[data-theme="dark"] .service-performance-card .score-gauge-value ){
  filter:
    drop-shadow(0 7px 12px rgba(255, 107, 26, 0.34))
    drop-shadow(0 0 16px rgba(255, 138, 61, 0.22));
}

:global(html[data-theme="dark"] .service-performance-card .score-halo ){
  background: radial-gradient(circle, rgba(255, 138, 61, 0.28), transparent 68%);
}

:global(html[data-theme="dark"] .service-performance-card .score-gauge-wrap strong),
:global(html[data-theme="dark"] .service-performance-card .target-value ){
  color: #ffffff;
  text-shadow: 0 0 18px rgba(255, 138, 61, 0.18);
}

:global(html[data-theme="dark"] .service-performance-card .score-gauge-wrap small),
:global(html[data-theme="dark"] .service-performance-card .score-copy p),
:global(html[data-theme="dark"] .service-performance-card .section-title span),
:global(html[data-theme="dark"] .service-performance-card .trend-tooltip strong ){
  color: #ffb370;
}

:global(html[data-theme="dark"] .service-performance-card .score-copy span),
:global(html[data-theme="dark"] .service-performance-card .score-copy em),
:global(html[data-theme="dark"] .service-performance-card .section-title small),
:global(html[data-theme="dark"] .service-performance-card .target-card em),
:global(html[data-theme="dark"] .service-performance-card .target-card-foot span),
:global(html[data-theme="dark"] .service-performance-card .trend-days ){
  color: rgba(205, 218, 235, 0.82);
}

:global(html[data-theme="dark"] .service-performance-card .target-label ){
  color: rgba(226, 234, 246, 0.88);
}

:global(html[data-theme="dark"] .service-performance-card .score-tags b),
:global(html[data-theme="dark"] .service-performance-card .section-title span ){
  background: rgba(255, 138, 61, 0.16);
  box-shadow:
    inset 0 0 0 1px rgba(255, 176, 105, 0.25),
    0 8px 20px rgba(255, 107, 26, 0.08);
}

:global(html[data-theme="dark"] .service-performance-card .trend-grid ){
  display: none;
}

:global(html[data-theme="dark"] .service-performance-card .trend-area ){
  opacity: 0.9;
}

:global(html[data-theme="dark"] .service-performance-card .trend-line ){
  filter: drop-shadow(0 0 10px rgba(255, 122, 36, 0.22));
}

:global(html[data-theme="dark"] .service-performance-card .trend-line-shadow ){
  stroke: rgba(255, 107, 26, 0.28);
  stroke-width: 9;
  filter: blur(5px);
}

:global(html[data-theme="dark"] .service-performance-card .trend-point ){
  fill: #ff9b50;
  stroke: none;
  stroke-width: 0;
  filter:
    drop-shadow(0 0 8px rgba(255, 138, 61, 0.42))
    drop-shadow(0 4px 8px rgba(255, 107, 26, 0.2));
}

:global(html[data-theme="dark"] .service-performance-card .trend-point-group:hover .trend-point),
:global(html[data-theme="dark"] .service-performance-card .trend-point-group:focus .trend-point ){
  stroke: none;
  stroke-width: 0;
}

:global(html[data-theme="dark"] .service-performance-card .trend-tooltip ){
  border-color: rgba(255, 155, 80, 0.32);
  background: rgba(11, 18, 29, 0.94);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.1),
    0 16px 34px rgba(0, 0, 0, 0.38);
}

:global(html[data-theme="dark"] .service-performance-card .target-track ){
  background: rgba(204, 218, 238, 0.17);
  box-shadow:
    inset 0 1px 3px rgba(0, 0, 0, 0.26),
    inset 0 0 0 1px rgba(255, 255, 255, 0.045);
}

:global(html[data-theme="dark"] .service-performance-card .target-fill ){
  box-shadow:
    0 0 18px rgba(255, 107, 26, 0.26),
    0 8px 18px rgba(255, 107, 26, 0.12);
}

:global(html[data-theme="dark"] .service-performance-card .target-marker ){
  background: rgba(240, 246, 255, 0.92);
  box-shadow:
    0 0 0 3px rgba(8, 14, 24, 0.9),
    0 0 18px rgba(255, 138, 61, 0.24);
}

:global(html[data-theme="dark"] .service-performance-card .target-status.success),
:global(html[data-theme="dark"] .service-performance-card .target-status.warn ){
  color: #ffd5b2;
  background: rgba(255, 138, 61, 0.16);
  box-shadow: inset 0 0 0 1px rgba(255, 176, 105, 0.24);
}

:global(html[data-theme="dark"] .service-performance-card .target-status.empty ){
  color: rgba(213, 225, 241, 0.82);
  background: rgba(154, 168, 186, 0.13);
  box-shadow: inset 0 0 0 1px rgba(218, 229, 244, 0.1);
}

@keyframes gaugeDraw {
  from {
    stroke-dasharray: 0 100;
  }
}

@keyframes trendDraw {
  from {
    stroke-dasharray: 0 420;
  }

  to {
    stroke-dasharray: 420 0;
  }
}

@keyframes barGrow {
  from {
    transform: scaleX(0);
  }
}

@container (max-width: 560px) {
  .service-performance-card {
    grid-template-rows: auto auto auto;
    align-content: start;
  }

  .target-panel {
    align-self: stretch;
    align-content: start;
    grid-template-columns: minmax(0, 1fr);
  }

  .trend-panel {
    grid-template-rows: auto auto auto;
  }

  .trend-chart {
    height: auto;
  }

  .trend-svg {
    height: 148px;
  }

  .score-panel {
    grid-template-columns: 144px minmax(0, 1fr);
    gap: 14px;
    padding: 14px;
  }

  .score-gauge-wrap {
    width: 144px;
  }

  .score-copy p {
    font-size: 18px;
  }
}

@media (max-width: 520px) {
  .score-panel {
    grid-template-columns: minmax(0, 1fr);
    justify-items: center;
    text-align: center;
  }

  .score-copy {
    justify-items: center;
  }

  .target-card-head,
  .target-card-foot {
    display: grid;
  }

  .target-value {
    justify-self: start;
  }
}

@media (prefers-reduced-motion: reduce) {
  .score-panel,
  .trend-panel,
  .target-card,
  .score-gauge-value,
  .trend-line,
  .target-fill {
    animation-duration: 1ms;
    transition-duration: 1ms;
  }
}
</style>
