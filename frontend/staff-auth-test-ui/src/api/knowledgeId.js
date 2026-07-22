export function normalizeKnowledgeId(libraryId) {
  if (typeof libraryId === 'number' && !Number.isSafeInteger(libraryId)) {
    throw new Error('知识库记录 ID 精度不安全，请刷新列表后重试');
  }
  const value = String(libraryId ?? '').trim();
  if (!/^\d+$/.test(value)) {
    throw new Error('知识库记录 ID 无效，请刷新列表后重试');
  }
  return value;
}

export function buildKnowledgePath(libraryId, suffix = '') {
  const id = normalizeKnowledgeId(libraryId);
  return `/api/admin/knowledge/${encodeURIComponent(id)}${suffix}`;
}
