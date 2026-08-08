import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import {
  createLatestRequestGuard,
  hasUnsavedDraftChanges,
  normalizeDraft,
  validateDraftForPublish
} from '../src/api/knowledgeDraft.js';

test('unconfirmed null metadata blocks publish but confirmed empty arrays pass', () => {
  assert.deepEqual(
    validateDraftForPublish({ chunks: [{ productCategories: null, scenes: [], intents: [] }] }),
    ['第 1 个切片的商品品类尚未确认']
  );
  assert.deepEqual(
    validateDraftForPublish({ chunks: [{ productCategories: [], scenes: [], intents: [] }] }),
    []
  );
});

test('knowledge ids remain strings', () => {
  const draft = normalizeDraft({
    documentId: '9223372036854775806',
    revision: 4,
    chunks: [{ chunkId: '9223372036854775805', productCategories: 'invalid', scenes: [], intents: [] }]
  });
  assert.equal(draft.documentId, '9223372036854775806');
  assert.equal(draft.chunks[0].chunkId, '9223372036854775805');
  assert.deepEqual(draft.chunks[0].productCategories, []);
});

test('all three label groups and unsaved edits block publish until the server snapshot catches up', () => {
  const saved = normalizeDraft({
    revision: 7,
    policyVersion: 'v1',
    chunks: [{ chunkId: '1', productCategories: null, scenes: null, intents: null }]
  });
  const edited = normalizeDraft(saved);
  edited.chunks[0].productCategories = [];

  assert.deepEqual(validateDraftForPublish(saved), [
    '第 1 个切片的商品品类尚未确认',
    '第 1 个切片的售后场景尚未确认',
    '第 1 个切片的处理意图尚未确认'
  ]);
  assert.equal(hasUnsavedDraftChanges(saved, edited), true);
  assert.equal(hasUnsavedDraftChanges(edited, normalizeDraft(edited)), false);
});

test('latest request guard rejects stale responses and invalidates requests after selection changes', () => {
  const guard = createLatestRequestGuard();
  const processingRequest = guard.issue('42');
  const publishedRequest = guard.issue('42');

  assert.equal(guard.isCurrent(publishedRequest, '42'), true);
  assert.equal(guard.isCurrent(processingRequest, '42'), false);
  guard.invalidate();
  assert.equal(guard.isCurrent(publishedRequest, '42'), false);
});

test('knowledge view uses single-flight polling and binds conflict reloads to the action document', async () => {
  const view = await readFile(new URL('../src/views/AdminKnowledgeView.vue', import.meta.url), 'utf8');
  const draftPanel = await readFile(new URL('../src/components/KnowledgeDraftReviewPanel.vue', import.meta.url), 'utf8');
  const detailPanel = await readFile(new URL('../src/components/KnowledgeDetailPanel.vue', import.meta.url), 'utf8');
  assert.doesNotMatch(view, /setInterval\(/);
  assert.match(view, /createLatestRequestGuard/);
  assert.match(view, /reloadDraftAfterConflict\(error, documentId\)/);
  assert.match(view, /selectedLibraryId\.value !== documentId/);
  assert.match(view, /syncKnowledgeLibrary/);
  assert.match(draftPanel, /hasUnsavedDraftChanges\(props\.draft, editable\.value\)/);
  assert.doesNotMatch(detailPanel, /\$emit\('edit'\)/);
  assert.match(detailPanel, /actionLoading === 'retry'/);
  assert.match(detailPanel, /\$emit\('sync'\)/);
});
