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
  const chunkCandidate = Array.isArray(draft) ? draft : draft.chunks;
  const rawChunks = Array.isArray(chunkCandidate) ? chunkCandidate : [];
  return {
    ...(Array.isArray(draft) ? {} : draft),
    documentId: Array.isArray(draft) || draft.documentId == null ? null : normalizeKnowledgeId(draft.documentId),
    revision: Number(draft.revision || 0),
    chunks: rawChunks.map(normalizeChunk)
  };
}

function comparableDraft(draft) {
  const normalized = normalizeDraft(draft);
  return {
    policyVersion: normalized.policyVersion || '',
    validFrom: normalized.validFrom || '',
    validTo: normalized.validTo || '',
    chunks: normalized.chunks.map((chunk) => ({
      chunkId: chunk.chunkId,
      productCategories: chunk.productCategories,
      scenes: chunk.scenes,
      intents: chunk.intents
    }))
  };
}

export function hasUnsavedDraftChanges(savedDraft, editableDraft) {
  return JSON.stringify(comparableDraft(savedDraft)) !== JSON.stringify(comparableDraft(editableDraft));
}

export function createLatestRequestGuard() {
  let generation = 0;
  return {
    issue(documentId) {
      generation += 1;
      return { documentId: String(documentId), generation };
    },
    invalidate() {
      generation += 1;
    },
    isCurrent(token, documentId) {
      return Boolean(token)
        && token.generation === generation
        && token.documentId === String(documentId);
    }
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
