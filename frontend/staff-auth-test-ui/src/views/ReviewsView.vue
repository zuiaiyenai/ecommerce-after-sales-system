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
    { label: '评价总数', value: total, tone: 'blue' },
    { label: '平均评分', value: avg, tone: 'orange' },
    { label: '好评数量', value: good, tone: 'green' },
    { label: '低分反馈', value: low, tone: 'red' }
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
    <article class="wide-panel reviews-panel">
      <div class="review-head">
        <div>
          <span class="eyebrow">用户评价</span>
          <h2>售后服务评价</h2>
          <p>查看用户对售后服务的真实评分和补充反馈。</p>
        </div>
        <button type="button" class="primary-action compact" :disabled="loading" @click="loadPage">
          {{ loading ? '同步中' : '同步评价' }}
        </button>
      </div>

      <div class="ticket-stat-grid">
        <button v-for="item in stats" :key="item.label" type="button" :class="['ticket-stat-card', item.tone]">
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
        </button>
      </div>

      <div class="review-toolbar">
        <div class="ticket-filter-row">
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
        <input v-model.trim="keyword" class="review-search" placeholder="搜索订单、商品、用户或评价内容" />
      </div>

      <div class="review-list">
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
  min-height: 100%;
}

.review-head,
.review-toolbar,
.review-card {
  display: flex;
  align-items: center;
}

.review-head {
  justify-content: space-between;
  margin-bottom: 22px;
}

.review-head h2 {
  margin: 8px 0;
  font-size: 26px;
}

.review-head p {
  margin: 0;
  color: #6b7280;
}

.review-toolbar {
  justify-content: space-between;
  gap: 16px;
  margin: 18px 0;
}

.review-search {
  width: 320px;
  height: 40px;
  padding: 0 14px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  font-size: 14px;
}

.review-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.review-card {
  gap: 16px;
  width: 100%;
  padding: 18px;
  border: 1px solid #edf0f4;
  border-radius: 8px;
  background: #ffffff;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.16s ease, box-shadow 0.16s ease;
}

.review-card:hover {
  border-color: #f2c9b8;
  box-shadow: 0 10px 24px rgba(17, 24, 39, 0.06);
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
  flex: 1;
  min-width: 0;
}

.review-main strong,
.review-score strong,
.review-meta strong {
  display: block;
  color: #111827;
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
}

.review-score {
  width: 150px;
  color: #c97b5a;
}

.review-score strong {
  font-size: 28px;
}

.review-score em {
  color: #c97b5a;
  letter-spacing: 1px;
}

.review-meta {
  width: 190px;
  text-align: right;
}

.review-empty {
  padding: 60px 24px;
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
</style>
