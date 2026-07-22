import test from 'node:test';
import assert from 'node:assert/strict';
import { buildKnowledgePath, normalizeKnowledgeId } from '../src/api/knowledgeId.js';

test('knowledge IDs stay as decimal strings without losing Long precision', () => {
  assert.equal(normalizeKnowledgeId('9007199254740993'), '9007199254740993');
  assert.equal(normalizeKnowledgeId(42), '42');
});

test('mock and unsafe numeric IDs are rejected before an HTTP request is built', () => {
  assert.throws(() => normalizeKnowledgeId('mock-4'), /ID 无效/);
  assert.throws(() => normalizeKnowledgeId(Number.MAX_SAFE_INTEGER + 1), /精度不安全/);
});

test('knowledge operation paths contain only validated IDs', () => {
  assert.equal(buildKnowledgePath('42', '/sync'), '/api/admin/knowledge/42/sync');
});
