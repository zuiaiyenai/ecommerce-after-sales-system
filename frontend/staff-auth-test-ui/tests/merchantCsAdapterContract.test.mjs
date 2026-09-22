import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const root = new URL('../', import.meta.url);

async function source(relativePath) {
  return readFile(new URL(relativePath, root), 'utf8');
}

function exportedNames(code) {
  return new Set([...code.matchAll(/export\s+(?:async\s+)?(?:function|const)\s+(\w+)/g)].map((match) => match[1]));
}

test('real and mock adapters expose the same explicit API surface', async () => {
  const real = await source('src/api/merchantCs.real.js');
  const mock = await source('src/api/merchantCs.mock.js');
  assert.deepEqual([...exportedNames(real)].sort(), [...exportedNames(mock)].sort());
  assert.doesNotMatch(real, /USE_REAL_API|demo-token|mock adapter/);
  assert.doesNotMatch(mock, /VITE_USE_REAL_API|fetch\(/);
});

test('production build resolves real adapter and has no implicit mock fallback', async () => {
  const facade = await source('src/api/merchantCs.js');
  const viteConfig = await source('vite.config.js');
  assert.equal(facade.trim(), "export * from '@merchantCs';");
  assert.match(viteConfig, /mode === 'mock'/);
  assert.match(viteConfig, /生产构建必须配置 VITE_API_BASE_URL/);
  assert.match(viteConfig, /merchantCs\.real\.js/);
  assert.match(viteConfig, /merchantCs\.mock\.js/);
});

test('session UI trusts backend ordering and reloads database history', async () => {
  const list = await source('src/views/SessionsView.vue');
  const detail = await source('src/views/SessionDetailView.vue');
  assert.doesNotMatch(list, /sessions\.value\.sort|visibleSessions[^]*\.sort\(/);
  assert.match(list, /item\?\.replyStatus === 'UNREPLIED'/);
  assert.match(detail, /await sendSessionMessage[^]*await loadPage\(\)/);
  assert.match(detail, /getSessionMessages\(sessionId\)/);
  assert.match(detail, /msg\.messageType === 'IMAGE' && Boolean\(imageSrc\(msg\)\)/);
  assert.match(detail, /const raw = msg\?\.fileUrl \|\| ''/);
  assert.doesNotMatch(detail, /fileUrl\s*\|\|\s*[^\n]*content/);
});

test('real admin dashboard does not render fixed mock business data', async () => {
  const dashboard = await source('src/views/AdminDashboardView.vue');
  assert.match(dashboard, /getAdminOverview\(\)/);
  assert.match(dashboard, /getAgentAccounts\(\)/);
  assert.match(dashboard, /getKnowledgeLibraries\(\)/);
  assert.doesNotMatch(dashboard, /adminDashboardMock|fallbackPendingAccounts|fallbackKnowledgeMaintenance/);
  assert.doesNotMatch(dashboard, /星选旗舰店|Knowledge Admin|Security Bot|<strong>6<\/strong>/);
});

test('real performance and account governance views expose honest empty states', async () => {
  const performance = await source('src/components/ServicePerformanceCard.vue');
  const accounts = await source('src/views/AdminAccountsView.vue');

  assert.doesNotMatch(performance, /fallbackTrendData|return 96|value: '4\.7 \/ 5'|value: '93%'|score: 88/);
  assert.match(performance, /近 7 日暂无评价或响应样本/);
  assert.match(performance, /hasPerformanceData/);

  assert.doesNotMatch(accounts, /baseOperationLogs|Platform Admin|Security Admin|登录设备数量|未发现异常/);
  assert.doesNotMatch(accounts, /售后政策 \/ FAQ \/ 服务规则|允许使用敏感规则|允许查看证据审核规则/);
  assert.match(accounts, /当前后端尚未提供账号审计日志接口/);
  assert.match(accounts, /细粒度知识权限[^]*尚未接入独立权限配置/);
});
