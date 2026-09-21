import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

test('text import uses the current Java knowledge lifecycle endpoint', async () => {
  const api = await readFile(new URL('../src/api/adminConsole.js', import.meta.url), 'utf8');

  assert.match(api, /request\('\/api\/admin\/knowledge\/text-import'/);
  assert.doesNotMatch(api, /request\('\/api\/admin\/knowledge\/import\/text'/);
});
