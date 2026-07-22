import { normalizeKnowledgeId } from './knowledgeId.js';

export function mapKnowledgeRecord(item = {}) {
  return {
    id: normalizeKnowledgeId(item.id),
    code: item.sourceCode,
    name: item.title,
    type: item.sourceType,
    status: item.status === 1 ? 'ENABLED' : 'DISABLED',
    description: item.content || '',
    merchantCode: item.merchantCode || '',
    productCategory: item.productCategory || '',
    scene: item.scene || '',
    intent: item.intent || '',
    policyVersion: item.policyVersion || '',
    validFrom: item.validFrom || '',
    validTo: item.validTo || '',
    tags: Array.isArray(item.tags) ? item.tags.join(', ') : '',
    updatedAt: item.updatedAt,
    createdAt: item.createdAt,
    chunkCount: item.chunkCount || 0,
    ingestionStatus: item.ingestionStatus || 'SUCCESS',
    reviewStatus: item.reviewStatus || 'PUBLISHED',
    revision: Number(item.revision || 0),
    publishedRevision: item.publishedRevision == null ? null : Number(item.publishedRevision),
    ingestionSourceType: item.ingestionSourceType || 'TEXT',
    fileName: item.fileName || '',
    fileUrl: item.fileUrl || '',
    errorMessage: item.errorMessage || '',
    scope: item.scope || 'MERCHANT',
    metadata: item.metadata || {}
  };
}

const terminalReviewStatuses = new Set([
  'REVIEW_REQUIRED', 'PUBLISHED', 'PARSE_FAILED', 'CLASSIFY_FAILED', 'EMBEDDING_FAILED'
]);

export function mergeKnowledgeRecord(current, incoming) {
  if (!current || current.id !== incoming.id) return incoming;
  const currentRevision = Number(current.revision || 0);
  const incomingRevision = Number(incoming.revision || 0);
  const keepCurrentLifecycle = currentRevision > incomingRevision
    || (currentRevision === incomingRevision
      && terminalReviewStatuses.has(current.reviewStatus)
      && !terminalReviewStatuses.has(incoming.reviewStatus));
  if (!keepCurrentLifecycle) return incoming;
  return {
    ...incoming,
    reviewStatus: current.reviewStatus,
    revision: current.revision,
    publishedRevision: current.publishedRevision,
    errorMessage: current.errorMessage
  };
}
