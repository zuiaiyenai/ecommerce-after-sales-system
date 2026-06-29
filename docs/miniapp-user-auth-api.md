# 小程序端用户认证接口

服务基础地址：`http://localhost:8080/api`

## 1. 获取验证码

`POST /miniapp/auth/code`

请求体：

```json
{
  "phone": "13800138000",
  "scene": "REGISTER"
}
```

`scene` 可选值：

- `REGISTER`：注册
- `RESET_PASSWORD`：找回密码

开发期响应会返回验证码，便于联调：

```json
{
  "code": 200,
  "message": "验证码发送成功",
  "data": {
    "code": "123456"
  }
}
```

生产环境应接入短信服务，并删除响应中的验证码明文。

## 2. 用户注册

`POST /miniapp/auth/register`

请求体：

```json
{
  "phone": "13800138000",
  "password": "123456",
  "code": "123456",
  "openid": "微信openid，可选",
  "nickname": "用户昵称，可选",
  "avatarUrl": "头像地址，可选"
}
```

成功响应：

```json
{
  "code": 200,
  "message": "注册成功",
  "data": {
    "userId": 1,
    "phone": "13800138000",
    "nickname": "用户昵称",
    "avatarUrl": "头像地址"
  }
}
```

## 3. 用户登录

`POST /miniapp/auth/login`

请求体：

```json
{
  "phone": "13800138000",
  "password": "123456"
}
```

成功响应：

```json
{
  "code": 200,
  "message": "登录成功",
  "data": {
    "token": "jwt-token",
    "userId": 1,
    "phone": "13800138000",
    "nickname": "用户昵称",
    "avatarUrl": "头像地址"
  }
}
```

小程序端后续请求建议携带：

```text
Authorization: Bearer jwt-token
```

## 4. 找回密码

`POST /miniapp/auth/password/reset`

请求体：

```json
{
  "phone": "13800138000",
  "code": "123456",
  "newPassword": "654321",
  "confirmPassword": "654321"
}
```

成功响应：

```json
{
  "code": 200,
  "message": "密码重置成功",
  "data": null
}
```

## 小程序调用示例

```js
wx.request({
  url: 'http://localhost:8080/api/miniapp/auth/login',
  method: 'POST',
  data: {
    phone: '13800138000',
    password: '123456'
  },
  success(res) {
    const token = res.data.data.token
    wx.setStorageSync('token', token)
  }
})
```
