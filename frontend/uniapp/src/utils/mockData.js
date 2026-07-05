// 模拟数据 - 所有页面统一引用，保证数据一致

export const products = [
  { id: 1, name: 'T恤', spec: '白色 / M码', price: 29.90, icon: '/static/images/T恤.png' },
  { id: 2, name: '手机', spec: '黑色 / 128GB', price: 2999.00, icon: '/static/images/手机.png' },
  { id: 3, name: '相纸', spec: '6寸 / 40张', price: 35.90, icon: '/static/images/相纸.png' },
  { id: 4, name: '耳机', spec: '黑色 / 标准版', price: 128.00, icon: '/static/images/耳机.png' },
  { id: 5, name: '鞋子', spec: '42码 / 白色', price: 168.00, icon: '/static/images/鞋子.png' }
]

export const orders = [
  { id: 1, orderNo: 'ORD20240115001', product: products[0], quantity: 1, status: 'RECEIVED', statusText: '已收货', createTime: '2024-01-15 10:30:00' },
  { id: 2, orderNo: 'ORD20240118001', product: products[1], quantity: 2, status: 'SHIPPED', statusText: '已发货', createTime: '2024-01-18 14:20:00' },
  { id: 3, orderNo: 'ORD20240120001', product: products[2], quantity: 1, status: 'RECEIVED', statusText: '已收货', createTime: '2024-01-20 09:15:00' },
  { id: 4, orderNo: 'ORD20240122001', product: products[3], quantity: 1, status: 'AFTERSALE', statusText: '售后中', createTime: '2024-01-22 16:45:00' },
  { id: 5, orderNo: 'ORD20240125001', product: products[4], quantity: 1, status: 'SHIPPED', statusText: '已发货', createTime: '2024-01-25 11:00:00' }
]

export const afterSales = [
  { id: 1, afterSaleNo: 'AS20240120001', order: orders[2], reason: '数量不符', desc: '收到的相纸数量少于订单数量', status: 'PROCESSING', statusText: '处理中', createTime: '2024-01-20 15:30:00' },
  { id: 2, afterSaleNo: 'AS20240122001', order: orders[3], reason: '音质问题', desc: '耳机左声道有杂音', status: 'PROCESSING', statusText: '处理中', createTime: '2024-01-22 10:20:00' },
  { id: 3, afterSaleNo: 'AS20240125001', order: orders[0], reason: '尺码不合适', desc: 'M码偏小，需要换大一号', status: 'COMPLETED', statusText: '已完成', createTime: '2024-01-25 08:45:00' }
]

// 获取订单状态对应的样式类
export function getStatusClass(status) {
  const map = {
    PAID: 'paid',
    SHIPPED: 'pending',
    RECEIVED: 'done',
    AFTERSALE: 'waiting',
    PROCESSING: 'processing',
    APPROVED: 'approved',
    REJECTED: 'rejected',
    COMPLETED: 'completed'
  }
  return map[status] || ''
}

// 获取订单操作按钮
export function getOrderActions(status) {
  const actions = []
  if (status === 'RECEIVED' || status === 'SHIPPED') {
    actions.push({ label: '申请售后', type: 'primary', action: 'applyAfterSale' })
  }
  if (status === 'SHIPPED') {
    actions.push({ label: '确认收货', type: 'primary', action: 'confirmReceive' })
  }
  if (status === 'AFTERSALE') {
    actions.push({ label: '查看进度', type: '', action: 'goDetail' })
  } else {
    actions.push({ label: '查看详情', type: '', action: 'goDetail' })
  }
  return actions
}
