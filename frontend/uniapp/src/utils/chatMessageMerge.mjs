function messageTime(message) {
  const value = message?.createdAt || message?.time || ''
  if (!value) return 0
  const parsed = Date.parse(String(value).replace(/-/g, '/'))
  return Number.isNaN(parsed) ? 0 : parsed
}

function compareMessageOrder(left, right) {
  const timeDifference = messageTime(left) - messageTime(right)
  if (timeDifference !== 0) return timeDifference
  const leftId = String(left?.messageId || '')
  const rightId = String(right?.messageId || '')
  if (leftId && rightId && /^\d+$/.test(leftId) && /^\d+$/.test(rightId)) {
    if (leftId.length !== rightId.length) return leftId.length - rightId.length
    return leftId.localeCompare(rightId)
  }
  return Number(left?.sequence || 0) - Number(right?.sequence || 0)
}

function isImagePlaceholder(message) {
  return message?.type !== 'IMAGE' && String(message?.content || '') === '[图片]'
}

function insertByTime(messages, imageMessage) {
  let index = messages.findIndex(
    (message) => messageTime(message) > messageTime(imageMessage)
  )
  if (index < 0) index = messages.length
  messages.splice(index, 0, imageMessage)
}

export function mergePersistedChatHistory(remoteMessages = [], localImages = []) {
  const chronologicalRemote = [...remoteMessages].sort(compareMessageOrder)
  const persistedImages = chronologicalRemote.filter(
    (message) => message?.type === 'IMAGE' && message?.fileUrl
  )
  const pendingImages = [...localImages]
  const consumed = new Set()
  for (let index = 0; index < persistedImages.length && index < pendingImages.length; index += 1) {
    consumed.add(index)
  }
  const merged = chronologicalRemote.map((message) => {
    if (!isImagePlaceholder(message)) return message
    const localIndex = pendingImages.findIndex(
      (item, index) => item?.fileUrl && !consumed.has(index)
    )
    const localImage = localIndex >= 0 ? pendingImages[localIndex] : null
    if (!localImage) return null
    consumed.add(localIndex)
    return {
      ...message,
      key: `remote-image-${message.messageId || message.sequence || localImage.fileUrl}`,
      content: message.content || '[图片]',
      fileUrl: localImage.fileUrl,
      type: 'IMAGE',
      meta: localImage.meta || ''
    }
  }).filter(Boolean)

  for (let index = 0; index < pendingImages.length; index += 1) {
    const localImage = pendingImages[index]
    if (!localImage?.fileUrl || consumed.has(index)) continue
    if (merged.some(
      (message) => message.type === 'IMAGE' && message.fileUrl === localImage.fileUrl
    )) continue
    insertByTime(merged, localImage)
  }
  return merged.sort(compareMessageOrder)
}
