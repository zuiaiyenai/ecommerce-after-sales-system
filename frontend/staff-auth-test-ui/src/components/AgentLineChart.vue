<script setup>
import { computed } from 'vue';

const props = defineProps({
  series: {
    type: Array,
    default: () => []
  },
  emptyText: {
    type: String,
    default: '所选时间范围暂无监控样本'
  }
});

const WIDTH = 820;
const HEIGHT = 252;
const PADDING = { top: 18, right: 18, bottom: 34, left: 58 };
const colors = {
  green: '#2f9d68',
  red: '#dc5b45',
  amber: '#d99624',
  blue: '#3e7ecb',
  orange: '#ec7b32',
  slate: '#77869a'
};

const chart = computed(() => {
  const usable = props.series
    .map((item) => ({
      ...item,
      points: (item.points || [])
        .map((point) => ({ time: Date.parse(point.timestamp), value: Number(point.value) }))
        .filter((point) => Number.isFinite(point.time) && Number.isFinite(point.value))
    }))
    .filter((item) => item.points.length);

  const allPoints = usable.flatMap((item) => item.points);
  if (!allPoints.length) {
    return { lines: [], yTicks: [], xTicks: [] };
  }

  const minTime = Math.min(...allPoints.map((point) => point.time));
  const rawMaxTime = Math.max(...allPoints.map((point) => point.time));
  const maxTime = rawMaxTime === minTime ? minTime + 60_000 : rawMaxTime;
  const rawMaxValue = Math.max(...allPoints.map((point) => point.value), 0);
  const maxValue = rawMaxValue > 0 ? rawMaxValue * 1.12 : 1;
  const plotWidth = WIDTH - PADDING.left - PADDING.right;
  const plotHeight = HEIGHT - PADDING.top - PADDING.bottom;
  const x = (time) => PADDING.left + ((time - minTime) / (maxTime - minTime)) * plotWidth;
  const y = (value) => PADDING.top + (1 - value / maxValue) * plotHeight;

  const lines = usable.map((item) => {
    const coordinates = item.points.map((point) => ({ ...point, x: x(point.time), y: y(point.value) }));
    return {
      ...item,
      color: colors[item.tone] || colors.slate,
      coordinates,
      path: coordinates.map((point, index) => `${index === 0 ? 'M' : 'L'} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`).join(' '),
      last: coordinates.at(-1)
    };
  });

  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => ({
    y: PADDING.top + (1 - ratio) * plotHeight,
    value: maxValue * ratio
  }));
  const xTicks = [minTime, minTime + (maxTime - minTime) / 2, maxTime].map((time) => ({
    x: x(time),
    label: new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' }).format(new Date(time))
  }));
  return { lines, yTicks, xTicks };
});

const unit = computed(() => props.series.find((item) => item.points?.length)?.unit || 'number');

function formatAxis(value) {
  if (unit.value === 'seconds') {
    return value >= 1 ? `${value.toFixed(1)}s` : `${Math.round(value * 1000)}ms`;
  }
  if (value >= 10) {
    return Math.round(value).toString();
  }
  return value.toFixed(value >= 1 ? 1 : 2);
}

function formatPoint(line) {
  const value = line.unit === 'seconds'
    ? line.last.value >= 1 ? `${line.last.value.toFixed(2)} 秒` : `${Math.round(line.last.value * 1000)} 毫秒`
    : `${line.last.value.toFixed(3)} 次/秒`;
  return `${line.label}：${value}`;
}
</script>

<template>
  <div class="agent-line-chart">
    <div v-if="chart.lines.length" class="agent-chart-legend" aria-label="图例">
      <span v-for="line in chart.lines" :key="line.key">
        <i :style="{ backgroundColor: line.color }"></i>{{ line.label }}
      </span>
    </div>

    <div v-if="!chart.lines.length" class="agent-chart-empty">
      <span>∿</span>
      <p>{{ emptyText }}</p>
    </div>

    <svg v-else :viewBox="`0 0 ${WIDTH} ${HEIGHT}`" role="img" aria-label="Agent 指标趋势图">
      <g class="agent-chart-grid">
        <template v-for="tick in chart.yTicks" :key="tick.y">
          <line :x1="PADDING.left" :x2="WIDTH - PADDING.right" :y1="tick.y" :y2="tick.y" />
          <text :x="PADDING.left - 10" :y="tick.y + 4" text-anchor="end">{{ formatAxis(tick.value) }}</text>
        </template>
      </g>
      <g class="agent-chart-x-axis">
        <text v-for="tick in chart.xTicks" :key="tick.x" :x="tick.x" :y="HEIGHT - 8" text-anchor="middle">
          {{ tick.label }}
        </text>
      </g>
      <g v-for="line in chart.lines" :key="line.key">
        <path class="agent-chart-path" :d="line.path" :stroke="line.color" />
        <circle class="agent-chart-marker" :cx="line.last.x" :cy="line.last.y" r="4.5" :fill="line.color">
          <title>{{ formatPoint(line) }}</title>
        </circle>
      </g>
    </svg>
  </div>
</template>

<style scoped>
.agent-line-chart {
  min-height: 286px;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
}

.agent-chart-legend {
  min-height: 30px;
  display: flex;
  justify-content: flex-end;
  gap: 16px;
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 700;
}

.agent-chart-legend span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.agent-chart-legend i {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

svg {
  width: 100%;
  min-height: 230px;
  overflow: visible;
}

.agent-chart-grid line {
  stroke: var(--border-color);
  stroke-width: 1;
  stroke-dasharray: 3 6;
}

.agent-chart-grid text,
.agent-chart-x-axis text {
  fill: var(--text-muted);
  font-size: 11px;
}

.agent-chart-path {
  fill: none;
  stroke-width: 3;
  stroke-linecap: round;
  stroke-linejoin: round;
  vector-effect: non-scaling-stroke;
}

.agent-chart-marker {
  stroke: var(--card-bg);
  stroke-width: 3;
}

.agent-chart-empty {
  min-height: 250px;
  display: grid;
  place-content: center;
  justify-items: center;
  gap: 8px;
  color: var(--text-muted);
}

.agent-chart-empty span {
  font-size: 36px;
  line-height: 1;
  color: #9daabd;
}

.agent-chart-empty p {
  margin: 0;
  font-size: 13px;
}
</style>
