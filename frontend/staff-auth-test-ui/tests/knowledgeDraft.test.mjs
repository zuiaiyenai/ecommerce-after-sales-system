import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizeDraft, validateDraftForPublish } from '../src/api/knowledgeDraft.js';

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
  const draft = normalizeDraft({ documentId: '9223372036854775806', revision: 4, chunks: [] });
  assert.equal(draft.documentId, '9223372036854775806');
});
