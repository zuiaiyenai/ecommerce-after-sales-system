export function normalizeProductList(data) {
  return Array.isArray(data) ? data : []
}

export function resolveShopViewState({ loading, errorMessage, products }) {
  if (loading) return 'loading'
  if (errorMessage) return 'error'
  return products.length === 0 ? 'empty' : 'content'
}
