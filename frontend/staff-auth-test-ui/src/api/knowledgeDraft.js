import { normalizeKnowledgeId } from './knowledgeId.js';

const LABEL_FIELDS = [
  ['productCategories', '商品品类'],
  ['scenes', '售后场景'],
  ['intents', '处理意图']
];

function normalizeLabels(value) {
  if (value == null) {
    return null;
  }
  return Array.isArray(value) ? value.map((item) => String(item)) : [];
}

function normalizeChunk(chunk = {}, index = 0) {
  return {
    ...chunk,
    chunkId: chunk.chunkId == null ? null : normalizeKnowledgeId(chunk.chunkId),
    chunkIndex: Number.isFinite(Number(chunk.chunkIndex)) ? Number(chunk.chunkIndex) : index,
    headingPath: Array.isArray(chunk.headingPath) ? chunk.headingPath.map(String) : [],
    productCategories: normalizeLabels(chunk.productCategories),
    scenes: normalizeLabels(chunk.scenes),
    intents: normalizeLabels(chunk.intents),
    confidence: chunk.confidence == null ? null : Number(chunk.confidence)
  };
}

export function normalizeDraft(draft = {}) {
  const rawChunks = Array.isArray(draft) ? draft : draft.chunks || [];
  return {
    ...(Array.isArray(draft) ? {} : draft),
    documentId: Array.isArray(draft) || draft.documentId == null ? null : normalizeKnowledgeId(draft.documentId),
    revision: Number(draft.revision || 0),
    chunks: rawChunks.map(normalizeChunk)
  };
}

export function validateDraftForPublish(draft) {
  const normalized = normalizeDraft(draft);
  const errors = [];
  normalized.chunks.forEach((chunk, index) => {
    LABEL_FIELDS.forEach(([field, label]) => {
      if (chunk[field] == null) {
        errors.push(`第 ${index + 1} 个切片的${label}尚未确认`);
      }
    });
  });
  return errors;
}
