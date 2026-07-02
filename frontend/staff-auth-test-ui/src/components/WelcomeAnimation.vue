<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';

const props = defineProps({
  durationMs: {
    type: Number,
    default: 5000
  }
});

const emit = defineEmits(['skip', 'finished']);

const canvasRef = ref(null);
const welcomeStyle = computed(() => ({
  '--welcome-duration': `${props.durationMs}ms`
}));
const CANVAS_FREEZE_PROGRESS = 0.76;

const blobs = [
  {
    color: [255, 213, 58],
    x: 0.42,
    y: 0.38,
    radius: 0.24,
    speed: 0.78,
    phase: 0.1,
    alpha: 0.78
  },
  {
    color: [184, 88, 255],
    x: 0.43,
    y: 0.61,
    radius: 0.27,
    speed: 0.66,
    phase: 1.4,
    alpha: 0.58
  },
  {
    color: [113, 189, 255],
    x: 0.62,
    y: 0.54,
    radius: 0.3,
    speed: 0.54,
    phase: 2.2,
    alpha: 0.5
  },
  {
    color: [255, 134, 164],
    x: 0.52,
    y: 0.48,
    radius: 0.25,
    speed: 0.72,
    phase: 3,
    alpha: 0.42
  },
  {
    color: [255, 147, 86],
    x: 0.47,
    y: 0.43,
    radius: 0.2,
    speed: 0.6,
    phase: 4.1,
    alpha: 0.36
  }
];

let animationId = 0;
let context = null;
let mediaQuery = null;
let startTime = 0;
let canvasWidth = 0;
let canvasHeight = 0;
let reducedMotion = false;
let finishEmitted = false;

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function easeInOut(value) {
  return value < 0.5 ? 2 * value * value : 1 - Math.pow(-2 * value + 2, 2) / 2;
}

function rgba(color, alpha) {
  return `rgba(${color[0]}, ${color[1]}, ${color[2]}, ${alpha})`;
}

function resizeCanvas() {
  const canvas = canvasRef.value;
  if (!canvas) {
    return;
  }

  const rect = canvas.getBoundingClientRect();
  const dpr = Math.min(window.devicePixelRatio || 1, 1.25);
  canvasWidth = Math.max(1, rect.width);
  canvasHeight = Math.max(1, rect.height);
  canvas.width = Math.round(canvasWidth * dpr);
  canvas.height = Math.round(canvasHeight * dpr);

  context = canvas.getContext('2d');
  context.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function drawBlob(blob, progress, elapsedSeconds) {
  const travel = easeInOut(clamp(progress / 0.82, 0, 1));
  const drift = reducedMotion ? 0 : elapsedSeconds * blob.speed;
  const waveX = Math.sin(drift + blob.phase) * 0.035;
  const waveY = Math.cos(drift * 0.88 + blob.phase) * 0.028;
  const sweep = reducedMotion ? 0 : (travel - 0.5) * 0.2;
  const scalePulse = reducedMotion ? 1 : 1 + Math.sin(drift * 1.2 + blob.phase) * 0.04;
  const maxSide = Math.max(canvasWidth, canvasHeight);
  const radius = maxSide * blob.radius * (0.78 + travel * 0.46) * scalePulse;
  const x = canvasWidth * (blob.x + waveX + sweep);
  const y = canvasHeight * (blob.y + waveY);
  const fadeIn = clamp(progress / 0.14, 0, 1);
  const fadeOut = 1 - clamp((progress - 0.78) / 0.22, 0, 1);
  const alpha = blob.alpha * easeInOut(fadeIn) * easeInOut(fadeOut);
  const gradient = context.createRadialGradient(x, y, radius * 0.05, x, y, radius);

  gradient.addColorStop(0, rgba(blob.color, alpha));
  gradient.addColorStop(0.38, rgba(blob.color, alpha * 0.62));
  gradient.addColorStop(0.68, rgba(blob.color, alpha * 0.2));
  gradient.addColorStop(1, rgba(blob.color, 0));

  context.fillStyle = gradient;
  context.beginPath();
  context.arc(x, y, radius, 0, Math.PI * 2);
  context.fill();
}

function drawFrame(now) {
  if (!context) {
    return;
  }

  const elapsed = reducedMotion ? props.durationMs * 0.34 : now - startTime;
  const progress = clamp(elapsed / props.durationMs, 0, 1);
  const drawProgress = Math.min(progress, CANVAS_FREEZE_PROGRESS);
  const elapsedSeconds = elapsed / 1000;
  context.clearRect(0, 0, canvasWidth, canvasHeight);
  context.fillStyle = '#ffffff';
  context.fillRect(0, 0, canvasWidth, canvasHeight);
  context.globalCompositeOperation = 'source-over';
  blobs.forEach((blob) => drawBlob(blob, drawProgress, elapsedSeconds));

  const vignette = context.createRadialGradient(
    canvasWidth * 0.5,
    canvasHeight * 0.5,
    Math.min(canvasWidth, canvasHeight) * 0.12,
    canvasWidth * 0.5,
    canvasHeight * 0.5,
    Math.max(canvasWidth, canvasHeight) * 0.72
  );
  vignette.addColorStop(0, 'rgba(255, 255, 255, 0)');
  vignette.addColorStop(1, 'rgba(255, 255, 255, 0.42)');
  context.fillStyle = vignette;
  context.fillRect(0, 0, canvasWidth, canvasHeight);

  if (!reducedMotion && progress < CANVAS_FREEZE_PROGRESS) {
    animationId = window.requestAnimationFrame(drawFrame);
  }
}

function startAnimation() {
  window.cancelAnimationFrame(animationId);
  finishEmitted = false;
  startTime = performance.now();
  resizeCanvas();
  drawFrame(startTime);

  if (!reducedMotion) {
    animationId = window.requestAnimationFrame(drawFrame);
  }
}

function handleMotionPreferenceChange(event) {
  reducedMotion = event.matches;
  startAnimation();
}

function emitFinishedAfterPaint() {
  if (finishEmitted) {
    return;
  }

  finishEmitted = true;
  window.requestAnimationFrame(() => {
    window.requestAnimationFrame(() => {
      emit('finished');
    });
  });
}

function handleOverlayAnimationEnd(event) {
  if (event.target !== event.currentTarget) {
    return;
  }

  emitFinishedAfterPaint();
}

onMounted(() => {
  mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
  reducedMotion = mediaQuery.matches;
  mediaQuery.addEventListener('change', handleMotionPreferenceChange);
  window.addEventListener('resize', startAnimation);
  startAnimation();
});

onBeforeUnmount(() => {
  window.cancelAnimationFrame(animationId);
  window.removeEventListener('resize', startAnimation);
  mediaQuery?.removeEventListener('change', handleMotionPreferenceChange);
});
</script>

<template>
  <div class="welcome-overlay" :style="welcomeStyle" aria-live="polite" @animationend="handleOverlayAnimationEnd">
    <canvas ref="canvasRef" class="welcome-canvas" aria-hidden="true"></canvas>
    <button type="button" class="welcome-skip" @click="emit('skip')">跳过动画</button>
    <div class="welcome-card">
      <h2>Welcome</h2>
    </div>
  </div>
</template>

<style scoped>
.welcome-overlay {
  position: fixed;
  inset: 0;
  z-index: 20;
  display: grid;
  place-items: center;
  overflow: hidden;
  padding: 24px;
  color: #fff;
  background: #fff;
  animation: welcomeOverlayIn var(--welcome-duration) cubic-bezier(0.22, 1, 0.36, 1) both;
  backface-visibility: hidden;
  contain: layout paint;
  will-change: opacity;
}

.welcome-canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  backface-visibility: hidden;
}

.welcome-card {
  position: relative;
  z-index: 2;
  display: grid;
  place-items: center;
  text-align: center;
  text-shadow: 0 10px 24px rgba(95, 75, 134, 0.16);
  animation: welcomeTextIn var(--welcome-duration) cubic-bezier(0.22, 1, 0.36, 1) both;
  backface-visibility: hidden;
  will-change: opacity, transform;
}

.welcome-card h2 {
  margin: 0;
  max-width: min(86vw, 720px);
  overflow-wrap: anywhere;
  color: rgba(255, 255, 255, 0.96);
  font-size: clamp(38px, 5vw, 58px);
  line-height: 1;
  font-weight: 900;
  letter-spacing: 0;
}

.welcome-skip {
  position: absolute;
  top: 34px;
  right: 38px;
  z-index: 4;
  min-height: 38px;
  border: 1px solid rgba(255, 255, 255, 0.42);
  border-radius: 999px;
  padding: 0 18px;
  color: #9b73db;
  background: rgba(255, 255, 255, 0.72);
  font-size: 13px;
  font-weight: 800;
  box-shadow: 0 8px 22px rgba(154, 119, 210, 0.12);
  backdrop-filter: blur(14px);
  transition: transform 160ms ease, background 160ms ease, border-color 160ms ease;
}

.welcome-skip:hover {
  transform: translateY(-1px);
  border-color: rgba(155, 115, 219, 0.34);
  background: rgba(255, 255, 255, 0.92);
}

@keyframes welcomeOverlayIn {
  0% {
    opacity: 0;
  }

  8%,
  78% {
    opacity: 1;
  }

  88% {
    opacity: 0.46;
  }

  100% {
    opacity: 0;
  }
}

@keyframes welcomeTextIn {
  0% {
    opacity: 0;
    transform: translateY(8px) scale(0.96);
  }

  14% {
    opacity: 1;
    transform: translateY(0) scale(1);
  }

  76% {
    opacity: 1;
    transform: translateY(0) scale(1);
  }

  84% {
    opacity: 0.72;
    transform: translateY(-1px) scale(1.003);
  }

  92% {
    opacity: 0.32;
    transform: translateY(-2px) scale(1.006);
  }

  100% {
    opacity: 0;
    transform: translateY(-3px) scale(1.008);
  }
}

@media (prefers-reduced-motion: reduce) {
  .welcome-overlay,
  .welcome-card {
    animation-duration: 0.01ms;
    animation-iteration-count: 1;
  }

  .welcome-skip {
    transition-duration: 0.01ms;
  }
}

@media (max-width: 900px) {
  .welcome-skip {
    top: 22px;
    right: 22px;
  }
}

@media (max-width: 520px) {
  .welcome-skip {
    top: 16px;
    right: 16px;
    min-height: 34px;
    padding: 0 14px;
  }
}
</style>
