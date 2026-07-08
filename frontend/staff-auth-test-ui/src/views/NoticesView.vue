<script setup>
import { inject, onMounted, ref } from 'vue';
import { getDashboardPerformance, getDashboardTodos } from '../api/merchantCs';

const shell = inject('merchantCsShell', null);
const todos = ref([]);
const performance = ref({ metrics: [] });

async function loadPage() {
  const [todoData, performanceData] = await Promise.all([getDashboardTodos(), getDashboardPerformance()]);
  todos.value = todoData;
  performance.value = performanceData;
}

onMounted(loadPage);
</script>

<template>
  <section class="work-page two-column notice-workbench">
    <article class="wide-panel notice-list-panel">
      <div class="panel-head">
        <div>
          <span class="eyebrow">消息通知</span>
          <h2>待办与预警</h2>
        </div>
      </div>

      <div class="data-list">
        <RouterLink v-for="item in todos" :key="item.id" :to="item.target" class="data-row notice-row">
          <span class="todo-dot"></span>
          <span class="row-copy">
            <strong>{{ item.title }}</strong>
            <span>{{ item.tag }} · {{ item.amount }}</span>
          </span>
          <span class="muted">处理</span>
        </RouterLink>
      </div>
    </article>

    <aside class="side-panel notice-performance-panel">
      <span class="eyebrow">服务表现</span>
      <div v-for="item in performance.metrics" :key="item.label" class="performance-row">
        <strong>{{ item.value }}</strong>
        <span>{{ item.label }} · {{ item.desc }}</span>
      </div>
      <button type="button" class="ghost-action" @click="shell?.setAction('通知筛选和已读接口后续接入')">
        标记全部已读
      </button>
    </aside>
  </section>
</template>
