<script setup>
import { computed, inject, onMounted, ref } from 'vue';
import { getReviews, resolveAssetUrl } from '../api/merchantCs';

const shell = inject('merchantCsShell', null);
const loading = ref(false);
const reviews = ref([]);
const activeScore = ref('ALL');
const keyword = ref('');
const selectedReview = ref(null);

const scoreFilters = [
  { key: 'ALL', label: '全部评价' },
  { key: 'GOOD', label: '好评' },
  { key: 'NORMAL', label: '中评' },
  { key: 'BAD', label: '差评' }
];

const stats = computed(() => {
  const total = reviews.value.length;
  const avg = total
    ? (reviews.value.reduce((sum, item) => sum + (Number(item.overallScore) || 0), 0) / total).toFixed(1)
    : '0.0';
  const good = reviews.value.filter(item => Number(item.overallScore) >= 5).length;
  const low = reviews.value.filter(item => Number(item.overallScore) > 0 && Number(item.overallScore) <= 2).length;
  return [
    { label: '平均评分', value: avg, tone: 'orange', filter: 'ALL' },
    { label: '好评数量', value: good, tone: 'green', filter: 'GOOD' },
    { label: '低分反馈', value: low, tone: 'red', filter: 'BAD' }
  ];
});

const visibleReviews = computed(() => reviews.value.filter(item => {
  const score = Number(item.overallScore) || 0;
  const matchesScore =
    activeScore.value === 'ALL' ||
    (activeScore.value === 'GOOD' && score >= 5) ||
    (activeScore.value === 'NORMAL' && (score === 3 || score === 4)) ||
    (activeScore.value === 'BAD' && score > 0 && score <= 2);
  const text = `${item.orderNo || ''} ${item.user || ''} ${item.productName || ''} ${item.ticketNo || ''} ${item.content || ''}`;
  return matchesScore && (!keyword.value.trim() || text.includes(keyword.value.trim()));
}));

async function loadPage() {
  loading.value = true;
  try {
    const page = await getReviews({ size: 100 });
    reviews.value = page.records || [];
  } catch (error) {
    shell?.setAction(error.message || '评价加载失败');
  } finally {
    loading.value = false;
  }
}

function scoreText(value) {
  const score = Number(value) || 0;
  if (score >= 5) return '非常满意';
  if (score === 4) return '满意';
  if (score === 3) return '一般';
  if (score === 2) return '不满意';
  return score > 0 ? '很不满意' : '未评分';
}

function stars(value) {
  const score = Number(value) || 0;
  return '★★★★★'.slice(0, score) + '☆☆☆☆☆'.slice(0, 5 - score);
}

function productImage(item) {
  return resolveAssetUrl(item.productImage);
}

function openReview(item) {
  selectedReview.value = item;
}

function closeReview() {
  selectedReview.value = null;
}

function detailScores(item) {
  if (!item) return [];
  return [
    { label: '综合评价', value: item.overallScore },
    { label: '响应速度', value: item.responseSpeedScore },
    { label: '服务态度', value: item.serviceAttitudeScore },
    { label: '专业程度', value: item.professionalScore },
    { label: '处理效率', value: item.efficiencyScore }
  ];
}

onMounted(loadPage);
</script>

<template>
  <section class="work-page reviews-page">
    <article class="wide-panel reviews-panel order-query-panel">
      <div class="review-head order-query-head">
        <div>
          <span class="eyebrow">用户评价</span>
          <h2>售后服务评价</h2>
          <p>查看用户对售后服务的真实评分和补充反馈。</p>
        </div>
        <button type="button" class="primary-action compact" :disabled="loading" @click="loadPage">
          {{ loading ? '同步中' : '同步评价' }}
        </button>
      </div>

      <div class="review-search-row">
        <input
          v-model.trim="keyword"
          class="review-search-input"
          placeholder="订单、商品、用户或评价内容"
        />
        <span class="review-result-count">{{ loading ? '加载中' : `匹配 ${visibleReviews.length} 条` }}</span>
      </div>

      <div class="order-stat-grid review-stat-grid">
        <button
          v-for="item in stats"
          :key="item.label"
          type="button"
          :class="['order-stat-card', item.tone, { active: activeScore === item.filter }]"
          @click="activeScore = item.filter"
        >
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
        </button>
      </div>

      <div class="review-toolbar order-filter-row">
        <button
          v-for="item in scoreFilters"
          :key="item.key"
          type="button"
          :class="['filter-chip', { active: activeScore === item.key }]"
          @click="activeScore = item.key"
        >
          {{ item.label }}
        </button>
      </div>

      <div class="review-list order-card-list">
        <button v-for="item in visibleReviews" :key="item.id" type="button" class="review-card" @click="openReview(item)">
          <span class="review-product">
            <img v-if="productImage(item)" :src="productImage(item)" alt="" />
            <span v-else>{{ (item.productName || '评').slice(0, 1) }}</span>
          </span>
          <span class="review-main">
            <strong>{{ item.productName || '售后商品' }}</strong>
            <em>{{ item.orderNo || '--' }} · {{ item.ticketNo || '无售后单号' }}</em>
            <small>{{ item.content || '用户未填写补充评价' }}</small>
          </span>
          <span class="review-score">
            <strong>{{ item.overallScore || 0 }}.0</strong>
            <em>{{ stars(item.overallScore) }}</em>
            <small>{{ scoreText(item.overallScore) }}</small>
          </span>
          <span class="review-meta">
            <strong>{{ item.user || '用户' }}</strong>
            <em>{{ item.createdAt || '--' }}</em>
            <small>点击查看评价指标</small>
          </span>
        </button>

        <div v-if="!loading && visibleReviews.length === 0" class="empty-state review-empty">
          <h2>当前没有用户评价</h2>
          <p>用户完成售后评价后会显示在这里。</p>
        </div>
      </div>
    </article>

    <div v-if="selectedReview" class="review-modal-mask" @click.self="closeReview">
      <section class="review-modal" aria-label="评价详情">
        <div class="modal-head">
          <div>
            <span class="eyebrow">评价详情</span>
            <h2>{{ selectedReview.productName || '售后商品' }}</h2>
          </div>
          <button type="button" class="modal-close" @click="closeReview">×</button>
        </div>

        <div class="modal-product">
          <span class="review-product large">
            <img v-if="productImage(selectedReview)" :src="productImage(selectedReview)" alt="" />
            <span v-else>{{ (selectedReview.productName || '评').slice(0, 1) }}</span>
          </span>
          <div>
            <strong>{{ selectedReview.orderNo || '--' }}</strong>
            <p>售后单号：{{ selectedReview.ticketNo || '无售后单号' }}</p>
            <p>评价用户：{{ selectedReview.user || '用户' }}</p>
            <p>评价时间：{{ selectedReview.createdAt || '--' }}</p>
          </div>
        </div>

        <div class="score-detail-list">
          <div v-for="score in detailScores(selectedReview)" :key="score.label" class="score-detail-row">
            <span>{{ score.label }}</span>
            <em>{{ stars(score.value) }}</em>
            <strong>{{ score.value || 0 }}.0</strong>
            <small>{{ scoreText(score.value) }}</small>
          </div>
        </div>

        <div class="review-content-box">
          <span>补充评价</span>
          <p>{{ selectedReview.content || '用户未填写补充评价' }}</p>
        </div>
      </section>
    </div>
  </section>
</template>

<style scoped>
.reviews-page {
  height: 100%;
  grid-template-rows: minmax(0, 1fr);
}

.reviews-panel {
  gap: 14px;
  min-height: 0;
  grid-template-rows: auto auto auto auto minmax(0, 1fr);
  border-color: #edf0f4;
  background: rgba(255, 255, 255, 0.9);
}

.review-head {
  margin-bottom: 0;
}

.review-head h2 {
  margin: 0;
  font-size: 26px;
}

.review-head p {
  margin: 6px 0 0;
  color: var(--muted);
  line-height: 1.6;
}

.review-search-row {
  margin-top: 0;
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.review-search-input {
  width: 220px;
  height: 36px;
  padding: 0 12px;
  border: 1px solid var(--glass-border);
  border-radius: 16px;
  color: var(--text);
  background: rgba(255, 255, 255, 0.56);
  -webkit-backdrop-filter: blur(16px);
  backdrop-filter: blur(16px);
  box-shadow: 0 10px 26px rgba(31, 41, 55, 0.08);
  font-size: 14px;
  transition: border-color 160ms ease, box-shadow 160ms ease, background 160ms ease;
}

.review-search-input::placeholder {
  color: var(--muted);
}

.review-search-input:focus {
  border-color: rgba(255, 138, 61, 0.54);
  outline: none;
  background: rgba(255, 255, 255, 0.78);
  box-shadow: 0 0 0 4px rgba(255, 138, 61, 0.14);
}

.review-result-count {
  min-height: 36px;
  display: inline-grid;
  place-items: center;
  border: 1px solid var(--glass-border);
  border-radius: 999px;
  padding: 0 14px;
  color: var(--muted);
  background: rgba(255, 255, 255, 0.52);
  -webkit-backdrop-filter: blur(16px);
  backdrop-filter: blur(16px);
  box-shadow: 0 10px 26px rgba(31, 41, 55, 0.08);
  font-size: 13px;
  font-weight: 700;
}

.review-stat-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.review-stat-grid .order-stat-card.red {
  border-color: #ffd4ca;
  background: #fff7f5;
}

.review-stat-grid .order-stat-card.red:hover,
.review-stat-grid .order-stat-card.red:focus-visible {
  border-color: #ff9f8c;
  background: #ffece6;
  color: #8f2f0c;
}

.review-stat-grid .order-stat-card.red:hover span,
.review-stat-grid .order-stat-card.red:focus-visible span {
  color: #9d5548;
}

.review-stat-grid .order-stat-card.red:active {
  border-color: #ef846f;
  background: #ffddd5;
}

.review-toolbar {
  margin: 0;
}

.review-list {
  min-height: 0;
  overflow: auto;
}

.review-card {
  min-height: 92px;
  width: 100%;
  display: grid;
  grid-template-columns: 62px minmax(260px, 1fr) 150px 190px;
  align-items: center;
  gap: 14px;
  padding: 14px;
  border: 1px solid #edf0f4;
  border-radius: 8px;
  background: #ffffff;
  color: var(--text);
  text-align: left;
  cursor: pointer;
  transition: transform 160ms ease, border-color 160ms ease, box-shadow 160ms ease, background 160ms ease;
}

.review-card:hover {
  transform: translateY(-1px);
  border-color: #dbeaff;
  background: #f7fbff;
  box-shadow: 0 10px 24px rgba(31, 38, 48, 0.08);
}

.review-card:focus-visible {
  outline: 2px solid #ff9c4a;
  outline-offset: 2px;
}

.review-product {
  display: grid;
  place-items: center;
  width: 62px;
  height: 62px;
  border-radius: 8px;
  background: #f4f6f8;
  color: #c97b5a;
  font-weight: 800;
  overflow: hidden;
}

.review-product img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.review-product.large {
  width: 84px;
  height: 84px;
}

.review-main {
  min-width: 0;
}

.review-main strong,
.review-score strong,
.review-meta strong {
  display: block;
  color: #111827;
}

.review-main strong,
.review-main em,
.review-meta strong,
.review-meta em,
.review-meta small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.review-main em,
.review-main small,
.review-score em,
.review-score small,
.review-meta em,
.review-meta small {
  display: block;
  margin-top: 6px;
  color: #6b7280;
  font-style: normal;
}

.review-main small {
  color: #374151;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.review-score {
  min-width: 0;
  color: #c97b5a;
}

.review-score strong {
  font-size: 24px;
  line-height: 1;
}

.review-score em {
  color: #c97b5a;
  letter-spacing: 1px;
}

.review-meta {
  min-width: 0;
  text-align: right;
}

.review-empty {
  min-height: 220px;
  padding: 60px 24px;
  border: 1px dashed #dce2ea;
  background: #fbfcfe;
}

.review-modal-mask {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(15, 23, 42, 0.36);
}

.review-modal {
  width: min(720px, 100%);
  max-height: calc(100vh - 64px);
  overflow: auto;
  padding: 24px;
  border-radius: 10px;
  background: #ffffff;
  box-shadow: 0 24px 70px rgba(15, 23, 42, 0.22);
}

.modal-head,
.modal-product,
.score-detail-row {
  display: flex;
  align-items: center;
}

.modal-head {
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
}

.modal-head h2 {
  margin: 6px 0 0;
  font-size: 24px;
}

.modal-close {
  width: 36px;
  height: 36px;
  border: 1px solid #e5e7eb;
  border-radius: 18px;
  background: #ffffff;
  color: #6b7280;
  font-size: 20px;
  cursor: pointer;
}

.modal-product {
  gap: 16px;
  padding: 16px;
  border: 1px solid #edf0f4;
  border-radius: 8px;
  background: #f8fafc;
}

.modal-product strong,
.modal-product p {
  margin: 0;
}

.modal-product strong {
  display: block;
  margin-bottom: 8px;
  color: #111827;
}

.modal-product p {
  margin-top: 4px;
  color: #6b7280;
}

.score-detail-list {
  margin-top: 18px;
  border: 1px solid #edf0f4;
  border-radius: 8px;
  overflow: hidden;
}

.score-detail-row {
  min-height: 58px;
  padding: 0 16px;
  border-bottom: 1px solid #edf0f4;
  background: #ffffff;
}

.score-detail-row:last-child {
  border-bottom: none;
}

.score-detail-row span {
  width: 120px;
  font-weight: 800;
  color: #111827;
}

.score-detail-row em {
  flex: 1;
  color: #c97b5a;
  font-style: normal;
  letter-spacing: 2px;
}

.score-detail-row strong {
  width: 60px;
  color: #111827;
}

.score-detail-row small {
  width: 92px;
  color: #6b7280;
  text-align: right;
}

.review-content-box {
  margin-top: 18px;
  padding: 16px;
  border: 1px solid #edf0f4;
  border-radius: 8px;
}

.review-content-box span {
  display: block;
  margin-bottom: 8px;
  font-weight: 800;
  color: #111827;
}

.review-content-box p {
  margin: 0;
  color: #374151;
  line-height: 1.7;
}

/* Liquid glass refinements */
.reviews-panel,
.review-card,
.review-modal,
.modal-product,
.score-detail-list,
.score-detail-row,
.review-content-box,
.review-empty {
  border-color: var(--glass-border);
  background: var(--glass-bg);
  -webkit-backdrop-filter: var(--glass-blur);
  backdrop-filter: var(--glass-blur);
  box-shadow: var(--glass-shadow);
}

.reviews-panel,
.review-modal {
  border-radius: var(--radius-lg);
}

.review-card,
.modal-product,
.score-detail-list,
.review-content-box,
.review-empty {
  border-radius: var(--radius-md);
}

.review-card {
  background: rgba(255, 255, 255, 0.58);
}

.review-card:hover {
  transform: translateY(-3px);
  border-color: rgba(255, 138, 61, 0.3);
  background: rgba(255, 255, 255, 0.74);
  box-shadow: var(--glass-shadow-hover);
}

.review-stat-grid .order-stat-card.red {
  --stat-accent: #c94232;
  --stat-tint: rgba(201, 66, 50, 0.11);
  --stat-ring: rgba(201, 66, 50, 0.32);
  --stat-glow: rgba(201, 66, 50, 0.16);
  border-color: rgba(201, 66, 50, 0.24);
  background:
    linear-gradient(135deg, rgba(201, 66, 50, 0.1), rgba(255, 255, 255, 0.14) 58%),
    var(--glass-bg-strong);
}

.review-stat-grid .order-stat-card.red:hover,
.review-stat-grid .order-stat-card.red:focus-visible,
.review-stat-grid .order-stat-card.red.active {
  color: var(--text);
  border-color: var(--stat-ring);
  background:
    linear-gradient(135deg, var(--stat-tint), rgba(255, 255, 255, 0.34) 62%),
    var(--glass-bg-strong);
  box-shadow:
    0 18px 44px var(--stat-glow),
    var(--glass-shadow-hover);
}

.review-stat-grid .order-stat-card.red:hover span,
.review-stat-grid .order-stat-card.red:focus-visible span,
.review-stat-grid .order-stat-card.red.active span {
  color: var(--muted);
}

.review-modal-mask {
  background: rgba(15, 23, 42, 0.32);
  -webkit-backdrop-filter: blur(10px);
  backdrop-filter: blur(10px);
}

.review-modal {
  border: 1px solid var(--glass-border-strong);
  background: var(--glass-bg-strong);
  box-shadow: 0 28px 86px rgba(31, 41, 55, 0.2);
}

.modal-product,
.score-detail-row,
.review-content-box {
  background: rgba(255, 255, 255, 0.54);
}

.score-detail-list {
  overflow: hidden;
}

.score-detail-row {
  border-bottom-color: rgba(220, 228, 236, 0.68);
  box-shadow: none;
}

.modal-close {
  border-color: var(--glass-border);
  background: rgba(255, 255, 255, 0.56);
  -webkit-backdrop-filter: blur(16px);
  backdrop-filter: blur(16px);
  transition: transform 160ms ease, border-color 160ms ease, color 160ms ease, box-shadow 160ms ease;
}

.modal-close:hover {
  transform: translateY(-2px);
  border-color: rgba(255, 138, 61, 0.4);
  color: #c45009;
  box-shadow: 0 12px 30px rgba(255, 107, 26, 0.14);
}

:global(html[data-theme="dark"]) .reviews-panel,
:global(html[data-theme="dark"]) .review-card,
:global(html[data-theme="dark"]) .review-modal,
:global(html[data-theme="dark"]) .modal-product,
:global(html[data-theme="dark"]) .score-detail-list,
:global(html[data-theme="dark"]) .score-detail-row,
:global(html[data-theme="dark"]) .review-content-box,
:global(html[data-theme="dark"]) .review-empty {
  border-color: var(--glass-border);
  background: var(--glass-bg);
  box-shadow: var(--glass-shadow);
}

:global(html[data-theme="dark"]) .review-modal-mask {
  background: rgba(4, 8, 14, 0.58);
}

:global(html[data-theme="dark"]) .review-card:hover {
  border-color: rgba(255, 138, 61, 0.34);
  background: rgba(24, 36, 55, 0.76);
}

:global(html[data-theme="dark"]) .review-search-input,
:global(html[data-theme="dark"]) .review-result-count {
  border-color: var(--glass-border);
  color: var(--text);
  background: rgba(17, 26, 39, 0.62);
}

:global(html[data-theme="dark"]) .review-search-input::placeholder {
  color: #7f8da0;
}

:global(html[data-theme="dark"]) .review-search-input:focus {
  border-color: rgba(255, 138, 61, 0.54);
  background: rgba(24, 36, 55, 0.78);
  box-shadow: 0 0 0 4px rgba(255, 138, 61, 0.16);
}

:global(html[data-theme="dark"]) .review-stat-grid .order-stat-card.red {
  color: #f7fafc;
  border-color: rgba(201, 66, 50, 0.28);
  background:
    linear-gradient(135deg, var(--stat-tint), rgba(17, 26, 39, 0.38) 62%),
    rgba(17, 26, 39, 0.66);
}

:global(html[data-theme="dark"]) .review-stat-grid .order-stat-card.red:hover,
:global(html[data-theme="dark"]) .review-stat-grid .order-stat-card.red:focus-visible,
:global(html[data-theme="dark"]) .review-stat-grid .order-stat-card.red.active {
  border-color: var(--stat-ring);
  background:
    linear-gradient(135deg, var(--stat-tint), rgba(24, 36, 55, 0.72) 62%),
    rgba(24, 36, 55, 0.78);
  box-shadow:
    0 18px 46px rgba(0, 0, 0, 0.36),
    0 18px 42px var(--stat-glow);
}

:global(html[data-theme="dark"]) .review-stat-grid .order-stat-card.red span {
  color: #c6d2e2;
}

:global(html[data-theme="dark"]) .modal-product,
:global(html[data-theme="dark"]) .score-detail-row,
:global(html[data-theme="dark"]) .review-content-box,
:global(html[data-theme="dark"]) .modal-close {
  border-color: var(--glass-border);
  background: rgba(17, 26, 39, 0.62);
}

:global(html[data-theme="dark"]) .modal-product strong,
:global(html[data-theme="dark"]) .score-detail-row span,
:global(html[data-theme="dark"]) .score-detail-row strong,
:global(html[data-theme="dark"]) .review-content-box span,
:global(html[data-theme="dark"]) .review-content-box p {
  color: var(--text);
}
</style>
