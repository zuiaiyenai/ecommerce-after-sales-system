import test from 'node:test'
import assert from 'node:assert/strict'

import { mergePersistedChatHistory } from '../src/utils/chatMessageMerge.mjs'

test('persisted image replaces optimistic local image even when URLs differ', () => {
  const remote = [{
    messageId: '101',
    role: 'user',
    type: 'IMAGE',
    fileUrl: '/uploads/2026/07/30/damage.png',
    createdAt: '2026-07-30 14:13:56'
  }]
  const local = [{
    role: 'user',
    type: 'IMAGE',
    fileUrl: 'wxfile://tmp_damage.png',
    createdAt: '2026-07-30 14:13:55'
  }]

  const merged = mergePersistedChatHistory(remote, local)

  assert.equal(merged.length, 1)
  assert.equal(merged[0].fileUrl, '/uploads/2026/07/30/damage.png')
})

test('local image remains only as fallback when history has no persisted image', () => {
  const local = [{
    role: 'user',
    type: 'IMAGE',
    fileUrl: 'wxfile://tmp_damage.png',
    createdAt: '2026-07-30 14:13:55'
  }]

  const merged = mergePersistedChatHistory([], local)

  assert.equal(merged.length, 1)
  assert.equal(merged[0].fileUrl, 'wxfile://tmp_damage.png')
})
