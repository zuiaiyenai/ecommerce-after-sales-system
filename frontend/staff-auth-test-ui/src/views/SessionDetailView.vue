<script setup>
import { computed, inject, onMounted, onUnmounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import {
  closeSession,
  getSession,
  getSessionMessages,
  getSessions,
  resolveAssetUrl,
  requestSessionEvaluation,
  sendSessionMessage,
  submitSessionEvaluation
} from '../api/merchantCs';

const route = useRoute();
const router = useRouter();
const shell = inject('merchantCsShell', null);
const session = ref(null);
const sessions = ref([]);
const messages = ref([]);
const draft = ref('');
const sending = ref(false);
const actionLoading = ref('');
const activeFilter = ref('ACTIVE');
let ws = null;
let wsReconnectTimer = null;

const terminalStatuses = ['RESOLVED'];
const filterOptions = [
  { key: 'ACTIVE', label: '活跃' },
  { key: 'PROCESSING', label: '进行中' },
  { key: 'AWAITING_EVALUATION', label: '待评价' },
  { key: 'READY_TO_CLOSE', label: '待关闭' },
  { key: 'COMPLETED', label: '已完成' }
];

const quickReplies = ['退款流程', '退款时效', '退货说明', '发货时间', '优惠券使用', '商品保修'];

const visibleSessions = computed(() => {
  return sessions.value.filter((item) => item.status !== 'CLOSED').filter((item) => {
    if (activeFilter.value === 'ACTIVE') {
      return !terminalStatuses.includes(item.status);
    }
    if (activeFilter.value === 'COMPLETED') {
      return terminalStatuses.includes(item.status);
    }
    return item.status === activeFilter.value;
  });
});

const recommendedReply = computed(() => {
  const topic = `${session.value?.topic || ''}${session.value?.emotion || ''}`;
  if (topic.includes('退款')) {
    return '您好，退款将原路退回至您的支付账户。审核通过后一般 1-3 个工作日到账，具体以银行或支付平台处理时间为准。';
  }
  if (topic.includes('物流')) {
    return '您好，我已经帮您核对物流节点，会继续跟进包裹状态，并在有更新后第一时间同步给您。';
  }
  return '您好，我先帮您核对订单和售后记录，请您稍等一下。';
});

const evaluationHint = computed(() => {
  const status = session.value?.status;
  if (status === 'PROCESSING') {
    return '问题处理完成后会自动邀请用户评价，也可以在这里手动补发。';
  }
  if (status === 'AWAITING_EVALUATION') {
    return `评价请求已发送，30 分钟内未评价将转为待客服关闭。发送时间：${session.value?.evaluationRequestedAt || '暂无'}`;
  }
  if (status === 'READY_TO_CLOSE') {
    return '用户 30 分钟内未评价，客服现在可以关闭会话。';
  }
  if (status === 'RESOLVED') {
    return `用户已完成评价，会话自动进入已完成。评分：${session.value?.rating || 5} 星`;
  }
  if (status === 'CLOSED') {
    return '该会话已从列表移除，历史内容仍会保留。';
  }
  return '当前会话仍在接入或处理中。';
});

const hasRelatedOrder = computed(() => Boolean(session.value?.orderId));
const userScore = computed(() => (`${session.value?.emotion || ''}`.includes('预警') ? '4.2' : '4.8'));
const isActionBusy = computed(() => Boolean(actionLoading.value));
const userEmotionMessages = computed(() =>
  messages.value.filter((message) => message.senderRole === 'USER' && message.emotionLabel)
);
const emotionTrend = computed(() => {
  const items = userEmotionMessages.value;
  if (!items.length) {
    return [];
  }
  return items.map((message, index) => ({
    id: message.id || `${message.createdAt || 'msg'}-${index}`,
    step: index + 1,
    label: emotionLabelText(message.emotionLabel),
    rawLabel: message.emotionLabel,
    score: normalizeScore(message.emotionScore),
    confidence: normalizeConfidence(message.emotionConfidence),
    preview: message.content,
    createdAt: message.createdAt
  }));
});
const currentEmotionSnapshot = computed(() => ({
  label: emotionLabelText(session.value?.emotionLabel),
  rawLabel: session.value?.emotionLabel || '',
  score: normalizeScore(session.value?.emotionScore),
  confidence: normalizeConfidence(session.value?.emotionConfidence),
  tone: emotionTone(session.value?.emotionLabel),
  summary: emotionSummary(session.value?.emotionLabel)
}));
const emotionEscalationText = computed(() => {
  const items = emotionTrend.value;
  if (items.length < 2) {
    return '当前会话有效情绪样本还不多，先结合最新一轮判断。';
  }
  const firstRank = emotionRank(items[0].rawLabel);
  const lastRank = emotionRank(items[items.length - 1].rawLabel);
  if (lastRank > firstRank) {
    return '用户情绪有升级趋势，建议优先回应最新诉求并缩短等待感。';
  }
  if (lastRank < firstRank) {
    return '用户情绪较前面已有缓和，当前可以继续按流程推进。';
  }
  return '用户情绪整体保持同一等级，重点看最新一句的诉求变化。';
});

const latestKnowledgeMessage = computed(() => {
  const candidates = [...messages.value]
    .filter((message) => message.senderRole === 'SERVICE' && ((message.knowledgeHits && message.knowledgeHits.length) || message.knowledgeHitCount))
    .sort((left, right) => new Date(right.createdAt || 0).getTime() - new Date(left.createdAt || 0).getTime());
  return candidates[0] || null;
});
const latestKnowledgeHits = computed(() => latestKnowledgeMessage.value?.knowledgeHits || []);
const latestKnowledgeSummary = computed(() => {
  const message = latestKnowledgeMessage.value;
  if (!message) {
    return '当前还没有可展示的知识命中记录，等 AI 基于知识库生成回复后会显示在这里。';
  }
  const hitCount = message.knowledgeHitCount ?? latestKnowledgeHits.value.length;
  const sourceTypes = [...new Set(latestKnowledgeHits.value.map((item) => item.sourceType).filter(Boolean))];
  const sourceText = sourceTypes.length ? sourceTypes.map(knowledgeSourceLabel).join(' / ') : '未区分来源';
  return `最近一条 AI 回复使用了 ${hitCount || 0} 条知识，来源：${sourceText}。`;
});

async function loadPage() {
  const [page, detail, messageList] = await Promise.all([
    getSessions(),
    getSession(route.params.sessionId),
    getSessionMessages(route.params.sessionId)
  ]);
  sessions.value = page.records || [];
  session.value = detail;
  messages.value = messageList;
  connectWebSocket(route.params.sessionId);
}

function connectWebSocket(sessionId) {
  if (ws) {
    ws.close();
    ws = null;
  }
  if (wsReconnectTimer) {
    clearTimeout(wsReconnectTimer);
    wsReconnectTimer = null;
  }
  try {
    ws = new WebSocket('ws://127.0.0.1:8080/api/ws/chat');
    ws.onopen = () => {
      ws.send(JSON.stringify({ action: 'subscribe', sessionId: Number(sessionId) }));
    };
    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.action === 'message' && msg.role !== 'SERVICE') {
          messages.value = [...messages.value, {
            id: Date.now(),
            sessionId: msg.sessionId,
            senderRole: msg.role === 'USER' ? 'USER' : 'SERVICE',
            messageType: msg.messageType,
            content: msg.content,
            createdAt: msg.createdAt
          }];
        }
      } catch (e) {
        // ignore parse errors
      }
    };
    ws.onclose = () => {
      wsReconnectTimer = setTimeout(() => {
        if (route.params.sessionId) {
          connectWebSocket(route.params.sessionId);
        }
      }, 3000);
    };
  } catch (e) {
    // WebSocket connection failed, rely on HTTP polling
  }
}

async function refreshSession(updated) {
  session.value = { ...session.value, ...updated };
  const page = await getSessions();
  sessions.value = page.records || [];
  shell?.refreshShell();
}

async function handleSend() {
  if (!draft.value.trim() || sending.value) {
    return;
  }
  sending.value = true;
  try {
    const message = await sendSessionMessage(route.params.sessionId, draft.value.trim());
    messages.value = [...messages.value, message];
    draft.value = '';
    shell?.setAction('消息已发送');
    await loadPage();
  } finally {
    sending.value = false;
  }
}

async function handleRequestEvaluation() {
  actionLoading.value = 'request';
  try {
    const updated = await requestSessionEvaluation(route.params.sessionId);
    await refreshSession(updated);
    shell?.setAction('已发送评价请求');
  } catch (error) {
    shell?.setAction(error.message || '当前状态不能发送评价请求');
  } finally {
    actionLoading.value = '';
  }
}

async function handleSubmitEvaluation() {
  actionLoading.value = 'submit';
  try {
    const updated = await submitSessionEvaluation(route.params.sessionId, 5, '用户已完成服务评价');
    await refreshSession(updated);
    shell?.setAction('用户评价完成，会话已完成');
  } catch (error) {
    shell?.setAction(error.message || '当前状态不能提交评价');
  } finally {
    actionLoading.value = '';
  }
}

async function handleClose() {
  actionLoading.value = 'close';
  try {
    const updated = await closeSession(route.params.sessionId);
    await refreshSession(updated);
    shell?.setAction('会话已移除');
  } catch (error) {
    shell?.setAction(error.message || '移除失败');
  } finally {
    actionLoading.value = '';
  }
}

function handleInputKeydown(event) {
  if (event.key !== 'Enter' || event.shiftKey) {
    return;
  }
  event.preventDefault();
  handleSend();
}

function useRecommendedReply() {
  draft.value = recommendedReply.value;
}

function useQuickReply(label) {
  const replies = {
    退款流程: '您好，退款申请通过后会原路退回支付账户，我先帮您确认当前审核节点。',
    退款时效: '审核通过后通常 1-3 个工作日到账，遇到银行或支付平台处理可能略有延迟。',
    退货说明: '请保持商品及配件完整，按售后页面的退货地址寄回，并保留物流单号。',
    发货时间: '我会帮您核对仓库发货计划，有明确时间后马上同步给您。',
    优惠券使用: '优惠券是否可用取决于活动规则和订单金额，我帮您查看一下适用条件。',
    商品保修: '我先确认购买时间和故障表现，再为您匹配对应的保修政策。'
  };
  draft.value = replies[label] || recommendedReply.value;
}

function goSession(sessionId) {
  router.push(`/sessions/${sessionId}`);
}

function statusLabel(status) {
  const labels = {
    WAITING: '待接入',
    PROCESSING: '处理中',
    AWAITING_EVALUATION: '待用户评价',
    READY_TO_CLOSE: '待客服关闭',
    RESOLVED: '已完成',
    CLOSED: '已完成'
  };
  return labels[status] || '进行中';
}

function statusTone(status) {
  if (status === 'RESOLVED' || status === 'CLOSED') {
    return 'closed';
  }
  if (status === 'READY_TO_CLOSE') {
    return 'ready';
  }
  if (status === 'AWAITING_EVALUATION' || status === 'WAITING') {
    return 'waiting';
  }
  return 'processing';
}

function senderLabel(role) {
  return role === 'SERVICE' ? '客服' : '用户';
}

function showImage(msg) {
  return msg && msg.messageType === 'IMAGE';
}

function imageSrc(msg) {
  return resolveAssetUrl(msg && msg.content);
}

function fieldValue(value, fallback = '暂无') {
  return value || fallback;
}

function emotionLabelText(label) {
  const textMap = {
    SATISFIED: '满意',
    CALM: '平静',
    ANXIOUS: '着急',
    DISSATISFIED: '不满',
    ANGRY: '愤怒'
  };
  return textMap[String(label || '').toUpperCase()] || '未识别';
}

function emotionRank(label) {
  const rankMap = {
    SATISFIED: 0,
    CALM: 1,
    ANXIOUS: 2,
    DISSATISFIED: 3,
    ANGRY: 4
  };
  return rankMap[String(label || '').toUpperCase()] ?? 1;
}

function emotionTone(label) {
  const toneMap = {
    SATISFIED: 'calm',
    CALM: 'calm',
    ANXIOUS: 'anxious',
    DISSATISFIED: 'dissatisfied',
    ANGRY: 'angry'
  };
  return toneMap[String(label || '').toUpperCase()] || 'calm';
}

function normalizeScore(value) {
  const numeric = Number(value ?? 0);
  if (!Number.isFinite(numeric)) {
    return 0;
  }
  if (numeric <= 1) {
    return Math.round(numeric * 100);
  }
  return Math.max(0, Math.min(100, Math.round(numeric)));
}

function normalizeConfidence(value) {
  const numeric = Number(value ?? 0);
  if (!Number.isFinite(numeric)) {
    return 0;
  }
  if (numeric <= 1) {
    return Math.round(numeric * 100);
  }
  return Math.max(0, Math.min(100, Math.round(numeric)));
}

function emotionSummary(label) {
  const summaryMap = {
    SATISFIED: '用户情绪稳定偏正向，可以正常推进。',
    CALM: '用户表达平稳，当前没有明显升级风险。',
    ANXIOUS: '用户更关注处理速度和进展，需要及时反馈。',
    DISSATISFIED: '用户已有明显负面感受，建议加强安抚与解释。',
    ANGRY: '用户情绪风险高，建议优先处理并考虑转人工升级。'
  };
  return summaryMap[String(label || '').toUpperCase()] || '暂未获取到明确情绪判断。';
}

function knowledgeSourceLabel(sourceType) {
  const sourceMap = {
    faq: 'FAQ',
    product: '商品知识',
    policy: '售后政策',
    scene_evidence: '场景举证',
    review_interpretation: '评价解释'
  };
  return sourceMap[String(sourceType || '').toLowerCase()] || sourceType || '知识来源';
}

watch(() => route.params.sessionId, loadPage);
onMounted(loadPage);
onUnmounted(() => {
  if (ws) {
    ws.close();
    ws = null;
  }
  if (wsReconnectTimer) {
    clearTimeout(wsReconnectTimer);
    wsReconnectTimer = null;
  }
});
</script>

<template>
  <section class="session-template-page">
    <aside class="session-template-list">
      <div class="template-panel-head">
        <h2>会话列表</h2>
        <button type="button" class="template-icon-button" aria-label="筛选会话">≡</button>
      </div>

      <div class="template-filter-tabs" aria-label="会话筛选">
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

      <div class="template-conversation-list">
        <button
          v-for="item in visibleSessions"
          :key="item.id"
          type="button"
          :class="['template-conversation-card', { active: Number(route.params.sessionId) === item.id }]"
          @click="goSession(item.id)"
        >
          <span class="template-user-avatar">{{ fieldValue(item.user, '访客').slice(0, 1) }}</span>
          <span class="template-conversation-copy">
            <strong>{{ fieldValue(item.user, '未知用户') }}</strong>
            <em>{{ fieldValue(item.lastMessageContent, item.topic) }}</em>
            <small>{{ statusLabel(item.status) }} · {{ fieldValue(item.orderNo) }}</small>
          </span>
          <span class="template-conversation-side">
            <time>{{ item.id === 101 ? '10:24' : item.id === 102 ? '10:21' : '10:15' }}</time>
            <i v-if="!terminalStatuses.includes(item.status)" aria-hidden="true"></i>
          </span>
        </button>
      </div>

      <div class="template-list-foot">共 {{ sessions.length }} 条会话</div>
    </aside>

    <article class="session-template-chat">
      <header class="template-chat-head">
        <span class="template-user-avatar large">{{ fieldValue(session?.user, '访客').slice(0, 1) }}</span>
        <div>
          <h2>{{ fieldValue(session?.user, '未知用户') }}</h2>
          <p>订单号：{{ fieldValue(session?.orderNo, '--') }}</p>
        </div>
        <span :class="['session-status', statusTone(session?.status)]">{{ statusLabel(session?.status) }}</span>
        <button type="button" class="template-order-button" @click="router.push(`/orders/${session?.orderNo}`)">查看订单</button>
      </header>

      <div class="template-message-stream">
        <div
          v-for="message in messages"
          :key="message.id"
          :class="['template-message-row', message.senderRole === 'SERVICE' ? 'service' : 'user']"
        >
          <span class="template-user-avatar mini">{{ senderLabel(message.senderRole).slice(0, 1) }}</span>
          <div class="template-message-content">
            <img
              v-if="showImage(message)"
              :src="imageSrc(message)"
              alt="图片"
              style="max-width:200px;max-height:200px;border-radius:8px;display:block"
            />
            <p v-else>{{ message.content }}</p>
          </div>
        </div>

        <section class="template-product-card">
          <img
            v-if="session?.productImage"
            class="product-thumb"
            :src="imageSrc({content: session.productImage})"
            alt="商品"
          />
          <div v-else class="product-thumb">
            {{ fieldValue(session?.productName || session?.product, hasRelatedOrder ? '商' : '咨').slice(0, 1) }}
          </div>
          <div class="product-card-main">
            <strong>{{ fieldValue(session?.product || session?.productName, hasRelatedOrder ? '售后商品' : '未关联订单咨询') }}</strong>
            <span>订单号：{{ hasRelatedOrder ? fieldValue(session?.orderNo, '--') : '未关联订单' }}</span>
            <span :class="['session-status', statusTone(session?.status)]">{{ statusLabel(session?.status) }}</span>
          </div>
          <button
            type="button"
            aria-label="查看订单"
            :disabled="!hasRelatedOrder"
            @click="hasRelatedOrder && router.push(`/orders/${session?.orderId}`)"
          >
            {{ hasRelatedOrder ? '查看订单' : '无关联订单' }}
          </button>
        </section>
      </div>

      <form class="template-reply-composer" @submit.prevent="handleSend">
        <textarea
          v-model="draft"
          placeholder="请输入消息，Enter 发送，Shift + Enter 换行"
          rows="3"
          @keydown="handleInputKeydown"
        ></textarea>
        <div class="template-composer-actions">
          <span class="template-tool-row" aria-label="消息工具">
            <button type="button" aria-label="表情">☺</button>
            <button type="button" aria-label="图片">□</button>
            <button type="button" aria-label="附件">⌘</button>
            <button type="button" aria-label="文件">▱</button>
          </span>
          <button type="submit" class="template-send-button" :disabled="sending || !draft.trim()">
            {{ sending ? '发送中' : '发送' }}
          </button>
        </div>
      </form>
    </article>

    <aside class="session-template-assist">
      <section class="template-assist-card evaluation-card">
        <div class="template-card-title">
          <h2>评价与关闭</h2>
          <span :class="['session-status', statusTone(session?.status)]">{{ statusLabel(session?.status) }}</span>
        </div>
        <p>{{ evaluationHint }}</p>
        <p v-if="session?.rating" class="evaluation-real-result">
          真实评分：{{ session.rating }} 星
          <span v-if="session.evaluationContent">｜{{ session.evaluationContent }}</span>
        </p>
        <div class="evaluation-action-grid">
          <button
            type="button"
            class="template-primary-blue"
            :disabled="session?.status !== 'PROCESSING' || isActionBusy"
            @click="handleRequestEvaluation"
          >
            {{ actionLoading === 'request' ? '发送中' : '发送评价请求' }}
          </button>
          <button
            type="button"
            class="ghost-mini danger"
            :disabled="session?.status === 'CLOSED' || isActionBusy"
            @click="handleClose"
          >
            {{ actionLoading === 'close' ? '处理中' : '×' }}
          </button>
        </div>
      </section>

      <section class="template-assist-card">
        <div class="template-card-title">
          <h2>AI 智能辅助</h2>
        </div>
        <div class="template-recommend">
          <div class="template-card-title small">
            <strong>推荐回复</strong>
            <span>置信度 <em>92%</em></span>
          </div>
          <p>{{ recommendedReply }}</p>
          <div class="template-recommend-actions">
            <button type="button" class="template-primary-blue" @click="useRecommendedReply">一键采用</button>
            <button type="button" aria-label="赞同">♡</button>
            <button type="button" aria-label="反馈">☞</button>
          </div>
        </div>
        <div class="template-quick-grid">
          <div class="template-card-title small">
            <strong>快捷回复</strong>
            <span>管理</span>
          </div>
          <button v-for="reply in quickReplies" :key="reply" type="button" @click="useQuickReply(reply)">
            {{ reply }}
          </button>
        </div>
      </section>

      <section class="template-assist-card">
        <div class="template-card-title">
          <h2>用户信息</h2>
        </div>
        <div class="template-user-info">
          <span>用户名称</span>
          <strong>{{ fieldValue(session?.user, '未知用户') }}</strong>
          <span>会话编号</span>
          <strong>{{ fieldValue(session?.sessionNo, '--') }}</strong>
          <span>当前状态</span>
          <strong>{{ statusLabel(session?.status) }}</strong>
          <span>情绪标签</span>
          <strong>{{ session?.emotion || '中性' }}</strong>
        </div>
      </section>

      <section class="template-assist-card knowledge-hit-card">
        <div class="template-card-title">
          <h2>知识命中来源</h2>
          <span>{{ latestKnowledgeMessage?.knowledgeRetrievalMode || '未命中' }}</span>
        </div>

        <div class="knowledge-hit-summary">
          <strong>{{ latestKnowledgeMessage?.knowledgeQuery || '暂无检索词' }}</strong>
          <p>{{ latestKnowledgeSummary }}</p>
        </div>

        <div v-if="latestKnowledgeHits.length" class="knowledge-hit-list">
          <div v-for="(item, index) in latestKnowledgeHits" :key="`${item.sourceCode || item.title}-${index}`" class="knowledge-hit-item">
            <div class="knowledge-hit-head">
              <span class="knowledge-source-chip">{{ knowledgeSourceLabel(item.sourceType) }}</span>
              <strong>{{ item.title || item.sourceCode || '知识片段' }}</strong>
            </div>
            <p>{{ item.summary || item.snippet || '暂无摘要' }}</p>
            <small>命中分数 {{ item.score ?? '--' }}</small>
          </div>
        </div>
        <div v-else class="knowledge-hit-empty">
          当前会话还没有可展示的知识命中记录。
        </div>
      </section>

      <section class="template-assist-card emotion-monitor-card">
        <div class="template-card-title">
          <h2>情绪变化监控</h2>
          <span :class="['emotion-pill', currentEmotionSnapshot.tone]">{{ currentEmotionSnapshot.label }}</span>
        </div>

        <div class="emotion-snapshot">
          <div class="emotion-snapshot-main">
            <strong>{{ currentEmotionSnapshot.label }}</strong>
            <p>{{ currentEmotionSnapshot.summary }}</p>
          </div>
          <div class="emotion-meters">
            <div class="emotion-meter">
              <span>情绪分数</span>
              <strong>{{ currentEmotionSnapshot.score }}</strong>
            </div>
            <div class="emotion-meter">
              <span>判断置信度</span>
              <strong>{{ currentEmotionSnapshot.confidence }}%</strong>
            </div>
          </div>
        </div>

        <div class="emotion-trend-copy">
          <strong>趋势判断</strong>
          <p>{{ emotionEscalationText }}</p>
        </div>

        <div v-if="emotionTrend.length" class="emotion-trend-list">
          <div v-for="item in emotionTrend" :key="item.id" class="emotion-trend-item">
            <div class="emotion-trend-head">
              <span class="emotion-step">第 {{ item.step }} 轮</span>
              <span :class="['emotion-pill', emotionTone(item.rawLabel)]">{{ item.label }}</span>
            </div>
            <p class="emotion-preview">{{ item.preview }}</p>
            <div class="emotion-track-row">
              <span>分数 {{ item.score }}</span>
              <div class="emotion-track">
                <i :style="{ width: `${item.score}%` }"></i>
              </div>
              <span>置信 {{ item.confidence }}%</span>
            </div>
            <small>{{ item.createdAt || '--' }}</small>
          </div>
        </div>
        <div v-else class="emotion-empty">
          暂时没有可用于绘制轨迹的用户情绪样本。
        </div>
      </section>
    </aside>
  </section>
</template>

<style scoped>
.knowledge-hit-card {
  gap: 14px;
}

.knowledge-hit-summary {
  padding: 14px;
  border-radius: 16px;
  background: linear-gradient(135deg, rgba(14, 165, 233, 0.08), rgba(15, 23, 42, 0.04));
}

.knowledge-hit-summary strong {
  display: block;
  color: #0f172a;
  font-size: 15px;
}

.knowledge-hit-summary p,
.knowledge-hit-item p,
.knowledge-hit-empty {
  margin: 6px 0 0;
  color: #475569;
  line-height: 1.6;
}

.knowledge-hit-list {
  display: grid;
  gap: 12px;
}

.knowledge-hit-item {
  padding: 14px;
  border-radius: 16px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  background: #fff;
}

.knowledge-hit-head {
  display: grid;
  gap: 8px;
}

.knowledge-source-chip {
  display: inline-flex;
  width: fit-content;
  align-items: center;
  justify-content: center;
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(14, 165, 233, 0.12);
  color: #0369a1;
  font-size: 12px;
  font-weight: 600;
}

.knowledge-hit-item small {
  display: block;
  margin-top: 8px;
  color: #64748b;
}

.knowledge-hit-empty {
  padding: 14px;
  border-radius: 14px;
  background: rgba(248, 250, 252, 0.9);
}

.emotion-monitor-card {
  gap: 16px;
}

.emotion-snapshot {
  display: grid;
  gap: 14px;
  padding: 14px;
  border-radius: 18px;
  background: linear-gradient(135deg, rgba(15, 118, 110, 0.08), rgba(249, 115, 22, 0.08));
}

.emotion-snapshot-main strong {
  display: block;
  font-size: 20px;
  color: #0f172a;
}

.emotion-snapshot-main p,
.emotion-trend-copy p,
.emotion-preview,
.emotion-empty {
  margin: 6px 0 0;
  color: #475569;
  line-height: 1.6;
}

.emotion-meters {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.emotion-meter {
  padding: 12px 14px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid rgba(148, 163, 184, 0.18);
}

.emotion-meter span,
.emotion-trend-copy strong,
.emotion-step,
.emotion-track-row span,
.emotion-trend-item small {
  color: #64748b;
  font-size: 12px;
}

.emotion-meter strong {
  display: block;
  margin-top: 4px;
  font-size: 22px;
  color: #0f172a;
}

.emotion-trend-list {
  display: grid;
  gap: 12px;
}

.emotion-trend-item {
  padding: 14px;
  border-radius: 16px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  background: #fff;
}

.emotion-trend-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.emotion-track-row {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 10px;
  align-items: center;
  margin-top: 10px;
}

.emotion-track {
  height: 8px;
  border-radius: 999px;
  background: #e2e8f0;
  overflow: hidden;
}

.emotion-track i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #0ea5e9, #f97316, #ef4444);
}

.emotion-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 5px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
}

.emotion-pill.calm {
  background: rgba(14, 165, 233, 0.12);
  color: #0369a1;
}

.emotion-pill.anxious {
  background: rgba(249, 115, 22, 0.14);
  color: #c2410c;
}

.emotion-pill.dissatisfied,
.emotion-pill.angry {
  background: rgba(239, 68, 68, 0.14);
  color: #b91c1c;
}

.emotion-empty {
  padding: 14px;
  border-radius: 14px;
  background: rgba(248, 250, 252, 0.9);
}
</style>
