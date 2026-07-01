<script setup>
import { computed, inject, onMounted, onUnmounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import {
  closeSession,
  getSession,
  getSessionMessages,
  getSessions,
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

const terminalStatuses = ['RESOLVED', 'CLOSED'];
const filterOptions = [
  { key: 'ACTIVE', label: '活跃' },
  { key: 'PROCESSING', label: '进行中' },
  { key: 'AWAITING_EVALUATION', label: '待评价' },
  { key: 'READY_TO_CLOSE', label: '待关闭' },
  { key: 'COMPLETED', label: '已完成' }
];

const quickReplies = ['退款流程', '退款时效', '退货说明', '发货时间', '优惠券使用', '商品保修'];

const visibleSessions = computed(() => {
  return sessions.value.filter((item) => {
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
    return '问题处理完成后，可以发送评价请求。';
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
    return '该会话已由客服关闭。';
  }
  return '当前会话仍在接入或处理中。';
});

const userScore = computed(() => (`${session.value?.emotion || ''}`.includes('预警') ? '4.2' : '4.8'));
const isActionBusy = computed(() => Boolean(actionLoading.value));

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
    shell?.setAction('会话已由客服关闭');
  } catch (error) {
    shell?.setAction(error.message || '只有待客服关闭状态可以关闭');
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

function fieldValue(value, fallback = '暂无') {
  return value || fallback;
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
          <h2>{{ fieldValue(session?.user, '未知用户') }} <em>VIP</em></h2>
          <p>会员等级：V3　联系方式：138****5678</p>
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
            <p>{{ message.content }}</p>
            <time>{{ message.senderRole === 'SERVICE' ? '10:26' : '10:24' }}</time>
          </div>
        </div>

        <section class="template-product-card">
          <div class="product-thumb">耳机</div>
          <div>
            <strong>{{ fieldValue(session?.product || session?.productName, '轻音降噪耳机 Pro') }}</strong>
            <span>颜色：奶白色</span>
            <em>¥299.00　×1</em>
          </div>
          <div class="product-status">
            <strong>售后中</strong>
            <span>{{ fieldValue(session?.topic, '退款进度咨询') }}</span>
          </div>
          <button type="button" aria-label="查看商品">›</button>
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
            class="ghost-mini"
            :disabled="session?.status !== 'AWAITING_EVALUATION' || isActionBusy"
            @click="handleSubmitEvaluation"
          >
            模拟用户评价
          </button>
          <button
            type="button"
            class="ghost-mini danger"
            :disabled="session?.status !== 'READY_TO_CLOSE' || isActionBusy"
            @click="handleClose"
          >
            {{ actionLoading === 'close' ? '关闭中' : '关闭会话' }}
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
          <button type="button">更多 ›</button>
        </div>
        <div class="template-user-info">
          <span>用户等级</span>
          <strong><em>V3</em> 高级会员</strong>
          <span>近30天订单数</span>
          <strong>6</strong>
          <span>累计消费金额</span>
          <strong>¥ 2,843.00</strong>
          <span>满意度评分</span>
          <strong>{{ userScore }} ★★★★★</strong>
        </div>
      </section>
    </aside>
  </section>
</template>
