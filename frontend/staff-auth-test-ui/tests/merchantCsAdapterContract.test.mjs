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
