const BASE_URL = 'http://127.0.0.1:8080/api'

export function request(options) {
  return new Promise((resolve, reject) => {
    uni.request({
      url: `${BASE_URL}${options.url}`,
      method: options.method || 'GET',
      data: options.data || {},
      header: {
        'content-type': 'application/json',
        ...(options.header || {})
      },
      success: (res) => {
        const body = res.data || {}
        if (body.code !== 200) {
          reject(new Error(body.message || '操作失败'))
          return
        }
        resolve(body.data)
      },
      fail: () => {
        reject(new Error('后端服务未连接'))
      }
    })
  })
}
