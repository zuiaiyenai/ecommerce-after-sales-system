const BASE_URL = 'http://127.0.0.1:8080/api'

function getToken() {
  try {
    return uni.getStorageSync('token') || ''
  } catch (e) {
    return ''
  }
}

export function request(options) {
  const token = getToken()
  return new Promise((resolve, reject) => {
    uni.request({
      url: `${BASE_URL}${options.url}`,
      method: options.method || 'GET',
      data: options.data || {},
      header: {
        'content-type': 'application/json',
        ...(token ? { 'Authorization': 'Bearer ' + token } : {}),
        ...(options.header || {})
      },
      success: (res) => {
        const body = res.data || {}
        if (body.code === 401 || res.statusCode === 401) {
          uni.removeStorageSync('token')
          uni.removeStorageSync('userInfo')
          uni.reLaunch({ url: '/pages/auth/auth' })
          reject(new Error('登录已过期，请重新登录'))
          return
        }
        if (body.code !== 200) {
          console.error('接口请求失败', options.url, body)
          reject(new Error(normalizeErrorMessage(body)))
          return
        }
        resolve(body.data)
      },
      fail: (err) => {
        console.error('后端服务未连接', options.url, err)
        reject(new Error('后端服务未连接'))
      }
    })
  })
}

function normalizeErrorMessage(body) {
  const message = body.message || ''
  if (body.code === 500 || message.includes('###') || message.length > 40) {
    return '服务器异常，请检查后端和数据库配置'
  }
  return message || '操作失败'
}

export function setToken(t) {
  uni.setStorageSync('token', t)
}

export function clearToken() {
  uni.removeStorageSync('token')
  uni.removeStorageSync('userInfo')
}
