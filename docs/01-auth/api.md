# 01 认证模块 · API 文档

前置约定见 [00-foundation/api.md](../00-foundation/api.md)。本文只写接口细节。

## 接口总览

| # | 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|---|
| 1 | POST | `/api/v1/auth/register` | 无 | 注册 |
| 2 | GET | `/api/v1/auth/image_captcha` | 无 | 获取图形验证码 |
| 3 | POST | `/api/v1/auth/login` | 无 | 账号密码登录 |
| 4 | POST | `/api/v1/auth/email_login` | 无 | 邮箱验证码登录 |
| 5 | POST | `/api/v1/auth/captcha` | 无 | 发送邮箱验证码 |
| 6 | POST | `/api/v1/auth/reset_password` | 无 | 邮箱验证码重置密码 |
| 7 | POST | `/api/v1/auth/logout` | 需登录 | 登出 |
| 8 | POST | `/api/v1/auth/refresh` | 带过期 access | 刷新令牌 |
| 9 | GET | `/api/v1/auth/is_exists_name` | 无 | 昵称唯一性检测 |
| 10 | GET | `/api/v1/auth/is_exists_account` | 无 | 账号唯一性检测 |

---

## 1. 注册

### POST /api/v1/auth/register

**请求体**

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| `user_name` | string | 是 | 1-15 字符 | 昵称，全局唯一 |
| `account` | string | 是 | 11 位纯数字 | 账号，全局唯一 |
| `password` | string | 是 | 11-20 位 | 只允许字母数字，必须同时含字母和数字 |
| `ack` | string | 是 | 11-20 位 | 密码二次确认 |

```json
{
  "user_name": "叶子",
  "account": "13800000000",
  "password": "abc12345678",
  "ack": "abc12345678"
}
```

**成功响应**

```json
{
  "code": 0,
  "message": "成功",
  "data": { "message": "注册成功" }
}
```

> `data.message` 是 Go 版本的原始结构，前端可能读它来弹提示，保留不动。

**失败响应**

| 场景 | HTTP | code | message |
|---|---|---|---|
| 参数缺失/格式不合法 | 400 | 400 | 请求参数错误 |
| 账号不是 11 位数字 | 400 | 400 | 账号格式错误 |
| 密码不满足规则 | 400 | 400 | 密码格式错误 |
| 两次密码不一致 | 400 | 400 | 两次密码不一致 |
| 昵称已存在 | 409 | 409 | 该昵称已经存在 |
| 账号已存在 | 409 | 409 | 该账号已经存在 |

**注意**

- 唯一性判断受 MySQL `utf8mb4_0900_ai_ci` 影响：`Admin` 与 `admin` 视为同一昵称。
- 注册不返回 token，需再调登录接口。

---

## 2. 获取图形验证码

### GET /api/v1/auth/image_captcha

**请求参数**：无

**成功响应**

```json
{
  "code": 0,
  "message": "成功",
  "data": {
    "captcha_id": "a1b2c3d4e5f6g7h8",
    "base_64": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg..."
  }
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `captcha_id` | string | 验证码标识，登录时回传 |
| `base_64` | string | 完整 data URI，可直接塞 `<img src>` |

**注意**

- 字段名是 `base_64`（**下划线**），不是 `base64`。前端已按这个名字取值，不能改。
- 图片尺寸 240×80，6 位数字，有效期 300 秒。
- 每次调用生成新的 `captcha_id`，旧的不失效（各存各的 key，过期自动清）。

---

## 3. 账号密码登录

### POST /api/v1/auth/login

**请求体**

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| `account` | string | 是 | — | 账号 |
| `password` | string | 是 | — | 密码 |
| `captcha_key` | string | 是 | — | 即上一步的 `captcha_id` |
| `captcha_code` | string | 是 | 6 位 | 用户输入的验证码 |

```json
{
  "account": "13800000000",
  "password": "abc12345678",
  "captcha_key": "a1b2c3d4e5f6g7h8",
  "captcha_code": "123456"
}
```

**成功响应**

```json
{
  "code": 0,
  "message": "成功",
  "data": {
    "user_name": "叶子",
    "user_id": 1,
    "user_role_id": 0,
    "access_token": "eyJhbGciOiJIUzI1NiIs..."
  }
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `user_name` | string | 昵称 |
| `user_id` | int | 用户 ID |
| `user_role_id` | int | 1 管理员 / 0 普通用户 |
| `access_token` | string | JWT，有效期 15 分钟 |

**响应里没有 refresh token**：它藏在 access token 的 `tid` claim 里，不对外暴露。

**失败响应**

| 场景 | HTTP | code | message |
|---|---|---|---|
| 缺字段 | 400 | 400 | 请求参数错误 |
| 验证码过期 | 400 | 400 | 验证码已过期 |
| 验证码错误 | 400 | 400 | 验证码错误 |
| 账号不存在 | 404 | 404 | 该账号不存在 |
| 账号被禁用 | 400 | 1004 | 用户已被禁用 |
| 密码错误 | 400 | 400 | 密码错误 |

**注意**

- 验证码校验失败也会删除 key，必须重新获取。
- 同一账号在新设备登录会覆盖 Redis 里的 refresh token，旧设备下次刷新即 401（单设备登录）。

---

## 4. 邮箱验证码登录

### POST /api/v1/auth/email_login

**请求体**

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| `email` | string | 是 | 邮箱格式 | 账号绑定的邮箱 |
| `purpose` | string | 是 | `login` | 固定传 `login` |
| `captcha` | string | 是 | 6 位 | 邮件收到的验证码 |

```json
{ "email": "user@qq.com", "purpose": "login", "captcha": "654321" }
```

**成功响应**：同「账号密码登录」

**失败响应**

| 场景 | HTTP | code | message |
|---|---|---|---|
| 邮箱不存在 | 404 | 404 | 该邮箱未注册 |
| 验证码错误 | 400 | 400 | 验证码错误 |
| 验证码过期 | 400 | 400 | 验证码已过期 |
| 账号被禁用 | 400 | 1004 | 用户已被禁用 |

---

## 5. 发送邮箱验证码

### POST /api/v1/auth/captcha

**请求体**

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| `email` | string | 是 | 邮箱格式 | 接收邮箱 |
| `purpose` | string | 是 | `login` / `reset_password` / `reset_email` / `add_email` | 用途 |

```json
{ "email": "user@qq.com", "purpose": "reset_password" }
```

**成功响应**

```json
{
  "code": 0,
  "message": "成功",
  "data": { "message": "已向你的邮箱发送验证码" }
}
```

**失败响应**

| 场景 | HTTP | code | message |
|---|---|---|---|
| 60 秒内重复发送 | 400 | 400 | 请勿频繁发送验证码，请60秒后再试 |
| SMTP 发送失败 | 500 | 500 | 发送邮箱验证码失败 |

**注意**

- 不同 `purpose` 的验证码互相独立，各自一个 Redis key。
- 发送失败会回滚频率限制，可立即重试。
- 同一邮箱 60 秒内只能发一次，**跨 purpose 也受限**（limit key 只按邮箱）。

---

## 6. 重置密码

### POST /api/v1/auth/reset_password

**请求体**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `email` | string | 是 | 注册邮箱 |
| `captcha` | string | 是 | 6 位验证码（purpose 必须是 `reset_password`） |
| `new_password` | string | 是 | 新密码 |
| `ack` | string | 是 | 新密码二次确认 |

```json
{
  "email": "user@qq.com",
  "captcha": "654321",
  "new_password": "newpass12345",
  "ack": "newpass12345"
}
```

**成功响应**

```json
{ "code": 0, "message": "成功", "data": { "message": "成功修改密码" } }
```

**失败响应**

| 场景 | HTTP | code | message |
|---|---|---|---|
| 两次密码不一致 | 400 | 400 | 两次密码不一致 |
| 新密码不满足规则 | 400 | 400 | 密码格式错误 |
| 验证码错误 | 400 | 400 | 验证码错误 |
| 邮箱未注册 | 404 | 404 | 该邮箱未注册 |

**注意**

- 改密后**不会踢掉已登录设备**，旧 access token 到期（15 分钟）自然失效。
- 若需强制下线，再删 `refresh:{user_id}`，本轮不做。

---

## 7. 登出

### POST /api/v1/auth/logout

**请求头**：`Authorization: Bearer <access_token>`

**请求体**：无

**成功响应**

```json
{ "code": 0, "message": "成功" }
```

> 注意 `data` 字段整体缺省（不是 `"data": null`）。

**失败响应**：无。token 无效/缺失时也返回成功（幂等）。

**注意**

- 只有当前会话的 `tid` 与 Redis 中一致时才删 key，防止旧设备登出误踢新设备。
- 登出不清 Redis 里的图形验证码，无需清理。

---

## 8. 刷新令牌

### POST /api/v1/auth/refresh

**请求头**：`Authorization: Bearer <access_token>`（**允许已过期**）

**请求体**：无

**成功响应**

```json
{
  "code": 0,
  "message": "成功",
  "data": { "access_token": "eyJhbGciOiJIUzI1NiIs..." }
}
```

**失败响应**

| 场景 | HTTP | code | message |
|---|---|---|---|
| 未带 Authorization | 401 | 401 | 请提供 Access Token |
| 格式不是 Bearer | 401 | 401 | 令牌格式错误 |
| token 签名无效 | 401 | 401 | Access Token 无效 |
| Redis 中无 refresh | 401 | 401 | Refresh Token 已过期，请重新登录 |
| tid 不匹配 | 401 | 401 | Refresh Token 无效，请重新登录 |

**注意**

- 刷新成功后 refresh token 会轮换，旧 access token 立即失效（tid 已变）。
- 前端拦截器应在收到 401 时自动调这个接口，成功后重放原请求（Go 版本的 Vue 已实现）。

---

## 9. 昵称唯一性检测

### GET /api/v1/auth/is_exists_name

**查询参数**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `user_name` | string | 是 | 待检测的昵称 |

> 参数名是 `user_name`，不是 `name`。

**成功响应**

```json
{ "code": 0, "message": "成功", "data": { "is_exists": false } }
```

| 字段 | 说明 |
|---|---|
| `is_exists` | `false` 表示可用；`true` 表示已被占用 |

**注意**：不区分大小写（`Admin` 视为已存在 `admin`）。

---

## 10. 账号唯一性检测

### GET /api/v1/auth/is_exists_account

**查询参数**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `account` | string | 是 | 待检测的账号 |

**成功响应**

```json
{ "code": 0, "message": "成功", "data": { "is_exists": true } }
```

---

## 附：双 Token 时序

```
[客户端]                          [服务端]                        [Redis]
   │  POST /auth/login              │                                │
   │ ─────────────────────────────> │  校验验证码/密码                │
   │                                │ ──── SET refresh:{uid} ──────> │ (72h)
   │ <─── { access_token } ──────── │                                │
   │                                │                                │
   │  （15 分钟后 access 过期）      │                                │
   │  POST /auth/refresh            │                                │
   │   Bearer <过期的 access>        │                                │
   │ ─────────────────────────────> │  decode(verify_exp=False)      │
   │                                │  GET refresh:{uid} ──────────> │
   │                                │ <── 比对 tid ───────────────── │
   │                                │  轮换：SET 新 refresh          │
   │ <─── { access_token } ──────── │                                │
```
