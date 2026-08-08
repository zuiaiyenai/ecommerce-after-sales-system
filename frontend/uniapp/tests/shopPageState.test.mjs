import test from 'node:test'
import assert from 'node:assert/strict'

import { normalizeProductList, resolveShopViewState } from '../src/utils/shopPageState.mjs'

test('商品接口返回非数组时按空列表处理', () => {
  assert.deepEqual(normalizeProductList(null), [])
  assert.deepEqual(normalizeProductList({ records: [] }), [])
})

test('商品页优先展示加载态，其次展示错误、空态和列表', () => {
  assert.equal(resolveShopViewState({ loading: true, errorMessage: '失败', products: [] }), 'loading')
  assert.equal(resolveShopViewState({ loading: false, errorMessage: '失败', products: [] }), 'error')
  assert.equal(resolveShopViewState({ loading: false, errorMessage: '', products: [] }), 'empty')
  assert.equal(resolveShopViewState({ loading: false, errorMessage: '', products: [{ id: '1' }] }), 'content')
})
