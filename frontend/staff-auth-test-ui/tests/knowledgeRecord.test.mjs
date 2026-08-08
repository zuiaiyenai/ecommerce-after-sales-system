import test from 'node:test';
import assert from 'node:assert/strict';
import { mapKnowledgeRecord, mergeKnowledgeRecord } from '../src/api/knowledgeRecord.js';

test('real Java list response keeps lifecycle fields and a textual document ID', () => {
  const record = mapKnowledgeRecord({
    id: '9007199254740993',
    sourceType: 'after_sales_policy',
    sourceCode: 'POLICY-1',
    merchantCode: 'MERCHANT_DEMO',
    title: '售后政策',
    status: 1,
    reviewStatus: 'REVIEW_REQUIRED',
    revision: 8,
    publishedRevision: 6,
    validFrom: '2026-07-22T08:00:00',
    validTo: '2026-08-22T08:00:00',
    metadata: { ingestionStatus: 'PROCESSING' }
  });

  assert.equal(record.id, '9007199254740993');
  assert.equal(record.reviewStatus, 'REVIEW_REQUIRED');
  assert.equal(record.revision, 8);
  assert.equal(record.publishedRevision, 6);
  assert.equal(record.validFrom, '2026-07-22T08:00:00');
  assert.equal(record.validTo, '2026-08-22T08:00:00');
});

test('legacy ingestion metadata cannot override the authoritative review status', () => {
  const record = mapKnowledgeRecord({
    id: '42',
    status: 1,
    reviewStatus: 'PUBLISHED',
    ingestionStatus: 'PROCESSING'
  });
  assert.equal(record.reviewStatus, 'PUBLISHED');
});

test('a stale list response cannot replace a terminal status with processing', () => {
  const published = mapKnowledgeRecord({ id: '42', status: 1, reviewStatus: 'PUBLISHED', revision: 9 });
  const stale = mapKnowledgeRecord({ id: '42', status: 1, reviewStatus: 'PROCESSING', revision: 9 });
  assert.equal(mergeKnowledgeRecord(published, stale).reviewStatus, 'PUBLISHED');
});
