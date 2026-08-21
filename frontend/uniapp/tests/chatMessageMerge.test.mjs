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

test('one persisted image does not swallow a second pending local image', () => {
  const remote = [{
    messageId: '101',
    role: 'user',
    type: 'IMAGE',
    fileUrl: '/uploads/first.png',
    createdAt: '2026-08-16 15:55:20'
  }]
  const local = [
    { key: 'local-1', role: 'user', type: 'IMAGE', fileUrl: 'wxfile://first.png', createdAt: '2026-08-16 15:55:19' },
    { key: 'local-2', role: 'user', type: 'IMAGE', fileUrl: 'wxfile://second.png', createdAt: '2026-08-16 15:55:21' }
  ]

  const merged = mergePersistedChatHistory(remote, local)

  assert.deepEqual(merged.map((item) => item.fileUrl), [
    '/uploads/first.png',
    'wxfile://second.png'
  ])
})

test('remote history is ordered by timestamp and exact string message id', () => {
  const remote = [
    { messageId: '9007199254740994', type: 'TEXT', createdAt: '2026-08-16 15:55:20' },
    { messageId: '9007199254740993', type: 'TEXT', createdAt: '2026-08-16 15:55:20' },
    { messageId: '9007199254740992', type: 'TEXT', createdAt: '2026-08-16 15:55:19' }
  ]

  const merged = mergePersistedChatHistory(remote, [])

  assert.deepEqual(merged.map((item) => item.messageId), [
    '9007199254740992',
    '9007199254740993',
    '9007199254740994'
  ])
})
