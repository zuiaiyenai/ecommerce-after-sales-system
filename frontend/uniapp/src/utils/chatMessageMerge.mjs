function messageTime(message) {
  const value = message?.createdAt || message?.time || ''
  if (!value) return 0
  const parsed = Date.parse(String(value).replace(/-/g, '/'))
  return Number.isNaN(parsed) ? 0 : parsed
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
  const persistedImages = remoteMessages.filter(
    (message) => message?.type === 'IMAGE' && message?.fileUrl
  )
  if (persistedImages.length > 0) {
    return remoteMessages.filter((message) => !isImagePlaceholder(message))
  }

  const pendingImages = [...localImages]
  const consumed = new Set()
  const merged = remoteMessages.map((message) => {
    if (!isImagePlaceholder(message)) return message
    const localImage = pendingImages.find(
      (item) => item?.fileUrl && !consumed.has(item.fileUrl)
    )
    if (!localImage) return null
    consumed.add(localImage.fileUrl)
    return {
      ...message,
      key: `remote-image-${message.messageId || message.sequence || localImage.fileUrl}`,
      content: message.content || '[图片]',
      fileUrl: localImage.fileUrl,
      type: 'IMAGE',
      meta: localImage.meta || ''
    }
  }).filter(Boolean)

  for (const localImage of pendingImages) {
    if (!localImage?.fileUrl || consumed.has(localImage.fileUrl)) continue
    if (merged.some(
      (message) => message.type === 'IMAGE' && message.fileUrl === localImage.fileUrl
    )) continue
    insertByTime(merged, localImage)
  }
  return merged
}
