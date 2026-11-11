# 02 用户模块 · API 文档

前置约定见 [00-foundation/api.md](../00-foundation/api.md)。

## 接口总览

**前台（需登录，除标注外）**

| # | 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|---|
| 1 | GET | `/api/v1/user/info` | 需登录 | 我的资料 |
| 2 | POST | `/api/v1/user/profile` | 需登录 | 编辑昵称与简介 |
| 3 | POST | `/api/v1/user/avatar` | 需登录 | 上传头像 |
| 4 | POST | `/api/v1/user/password` | 需登录 | 修改密码 |
| 5 | POST | `/api/v1/user/email_ack` | 需登录 | 申请换绑邮箱 |
| 6 | POST | `/api/v1/user/add_email` | 需登录 | 首次补绑邮箱 |
| 7 | GET | `/api/v1/user/is_exists_email` | 需登录 | 邮箱唯一性检测 |
| 8 | GET | `/api/v1/user/email` | **无** | 邮件确认链接落地 |

**后台（需管理员）**

| # | 方法 | 路径 | 说明 |
|---|---|---|---|
| 9 | GET | `/api/v1/admin/users` | 用户列表 |
| 10 | POST | `/api/v1/admin/users` | 创建用户 |
| 11 | PUT | `/api/v1/admin/users/{id}` | 启用/禁用 |
| 12 | DELETE | `/api/v1/admin/users/{id}` | 删除（软删） |

---

## 1. 我的资料

### GET /api/v1/user/info

**请求头**：`Authorization: Bearer <access_token>`

**成功响应**

```json
{
  "code": 0,
  "message": "成功",
  "data": {
    "user_id": 1,
    "user_name": "叶子",
    "account": "13800000000",
    "email": "user@qq.com",
    "avatar_url": "https://zouxp.xyz/blog-project/all/20261109/ab12.jpg",
    "introduction": "写 Go 和 Python",
    "role_id": 0,
    "staus": 1,
    "create_at": "2026-11-09T21:39:04Z"
  }
}
```

> ⚠️ **两个字段名是拼错的，必须照抄**：
> - `staus`（应为 `status`）
> - `create_at`（应为 `created_at`）
>
> 前端已经按这两个名字取值。改名等于线上白屏。

| 字段 | 类型 | 说明 |
|---|---|---|
| `user_id` | int | |
| `user_name` | string | 昵称 |
| `account` | string | 账号 |
| `email` | string | 未绑定则为 `""` |
| `avatar_url` | string | 完整 URL；未设置则 `""` |
| `introduction` | string | 未设置为 `""` |
| `role_id` | int | 1 管理员 / 0 普通 |
| `staus` | int | 1 启用 / 0 禁用 |
| `create_at` | string | 注册时间 |

**失败响应**：401 未登录

---

## 2. 编辑资料

### POST /api/v1/user/profile

**请求体**

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| `nick_name` | string | 否 | 1-15 字符 | 不传 / `null` / `""` 均表示**不修改** |
| `introduction` | string | 否 | — | 不传 / `null` → 不修改；`""` → **清空** |

```json
{ "nick_name": "叶子", "introduction": "写 Go 和 Python" }
```

**成功响应**

```json
{ "code": 0, "message": "成功" }
```

**失败响应**

| 场景 | HTTP | code | message |
|---|---|---|---|
| 昵称超过 15 字符 | 400 | 400 | 请求参数错误 |
| 昵称已被占用 | 409 | 409 | 该昵称已经存在 |

**注意**

- **昵称**：不传 / `null` / `""` 都表示不修改。
  昵称是 `NOT NULL UNIQUE`，清空没有意义，传空字符串也不会写库。
- **简介**：不传 / `null` 表示不修改；传 `""` 表示**清空**。
  Go 版用 `!= ""` 判断，导致简介永远清不掉，本轮修掉。
- 昵称查重会排除自己，所以保存时把昵称原样提交不会报「已存在」。

---

## 3. 上传头像

### POST /api/v1/user/avatar

**Content-Type**：`multipart/form-data`

**表单字段**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `file` | file | 是 | 图片文件 |

**限制**

- 大小 ≤ 10 MB
- 格式 ∈ `.jpg` / `.jpeg` / `.png` / `.webp`（扩展名不区分大小写）

**成功响应**

```json
{
  "code": 0,
  "message": "成功",
  "data": { "avatar_url": "https://zouxp.xyz/blog-project/all/20261109/ab12.jpg" }
}
```

**失败响应**

| 场景 | HTTP | code | message |
|---|---|---|---|
| 超过 10 MB | 400 | 400 | 图片大小不能超过 10MB |
| 格式不支持 | 400 | 400 | 不支持的文件格式 |
| MinIO 上传失败 | 500 | 500 | 上传图片失败 |

**注意**：旧头像文件会被异步删除，删除失败不影响接口返回。

---

## 4. 修改密码

### POST /api/v1/user/password

**请求体**

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| `old_password` | string | 是 | — | 当前密码 |
| `new_password` | string | 是 | 11-20 位字母数字混合 | 新密码 |
| `ack` | string | 是 | 同上 | 二次确认 |

```json
{ "old_password": "oldpass1234", "new_password": "newpass5678", "ack": "newpass5678" }
```

**成功响应**

```json
{ "code": 0, "message": "成功" }
```

**失败响应**

| 场景 | HTTP | code | message |
|---|---|---|---|
| 旧密码错误 | 400 | 400 | 密码错误 |
| 两次密码不一致 | 400 | 400 | 两次密码不一致 |
| 新密码不满足规则 | 400 | 400 | 密码格式错误 |

**注意**：改密后不会踢下线，旧 token 15 分钟后自然失效。

---

## 5. 申请换绑邮箱

### POST /api/v1/user/email_ack

**请求体**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `password` | string | 是 | 当前密码 |
| `captcha` | string | 是 | 6 位验证码（purpose=`reset_email`，发到**当前**邮箱） |
| `new_email` | string | 是 | 新邮箱 |

```json
{ "password": "abc12345678", "captcha": "654321", "new_email": "new@qq.com" }
```

**成功响应**

```json
{
  "code": 0,
  "message": "成功",
  "data": { "message": "已发送确认邮件到新邮箱，请到邮箱确认" }
}
```

**失败响应**

| 场景 | HTTP | code | message |
|---|---|---|---|
| 验证码错误 | 400 | 400 | 验证码错误 |
| 密码错误 | 400 | 400 | 密码错误 |
| 新邮箱已被占用 | 409 | 409 | 该邮箱已经被绑定 |
| 60 秒内重复申请 | 429 | 429 | 请勿频繁发送验证码，请60秒后再试 |
| 发信失败 | 500 | 500 | 给新邮箱发送邮件失败 |

**注意**：这个接口**不改库**，只发确认邮件。邮箱在用户点链接后才真正更新。

---

## 6. 首次补绑邮箱

### POST /api/v1/user/add_email

**请求体**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `new_email` | string | 是 | 要绑定的邮箱 |
| `captcha` | string | 是 | 6 位验证码（purpose=`add_email`） |

```json
{ "new_email": "user@qq.com", "captcha": "654321" }
```

**成功响应**

```json
{
  "code": 0,
  "message": "成功",
  "data": { "message": "添加成功" }
}
```

**失败响应**

| 场景 | HTTP | code | message |
|---|---|---|---|
| 已有邮箱（非空） | 403 | 403 | 用户已存在邮箱，不可再添加 |
| 验证码错误 | 400 | 400 | 验证码错误 |
| 邮箱已被占用 | 409 | 409 | 该邮箱已经被绑定 |

> 「已有邮箱」返回的是 **403 而不是 400**，文案是「用户已存在邮箱，不可再添加」。
> 前端按 HTTP 状态码分支时要留意。

**与 `/email_ack` 的区别**：本接口**直接生效**，不发确认邮件。仅用于从没绑过邮箱的账号。

---

## 7. 邮箱唯一性检测

### GET /api/v1/user/is_exists_email

**查询参数**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `new_email` | string | 是 | 待检测邮箱 |

> 参数名是 `new_email`，不是 `email`。前端注册/换绑页面按这个名字传。

**成功响应**

```json
{ "code": 0, "message": "成功", "data": { "is_exists": true } }
```

---

## 8. 确认换绑邮箱（邮件链接）

### GET /api/v1/user/email

**鉴权**：无。这是邮件里的链接，浏览器直接打开，不带 Authorization 头。

**查询参数**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `token` | string | 是 | 邮件链接里的 JWT，5 分钟有效 |

**响应：HTML 页面，不是 JSON**

这个接口是给浏览器直接打开的，返回一张内嵌样式的提示卡片（`Content-Type: text/html`）：

| 场景 | HTTP | 页面标题 | 页面正文 |
|---|---|---|---|
| 换绑成功 | 200 | 邮箱修改成功 | 您已成功修改绑定邮箱，下次登录可以使用新邮箱 |
| 缺少 token | 200 | 邮箱修改失败 | 缺少必要的确认信息，请重新发送确认邮件 |
| token 无效/过期 | 200 | 邮箱修改失败 | 确认链接无效或已过期，请重新申请修改 |
| token 已用过（黑名单） | 200 | 邮箱修改失败 | 确认链接无效或已过期，请重新申请修改 |

> ⚠️ **四种情况全部返回 HTTP 200**，成败只体现在页面内容上。
> 前端拿不到 JSON，也不需要拿 —— 这是纯粹的浏览器落地页。

**注意**

- token 用一次即拉黑（Redis，TTL 300 秒），重复点击会显示「确认链接无效或已过期」。
- **token 的 payload 有历史包袱**：`username` 字段里存的其实是**新邮箱**，
  不是用户名。签发时是 `GenerateTokenExpire(user_id, new_email, ...)`。
  实现时照抄，不要以为字段名和语义一致。
- 页面样式在服务端内联，不依赖前端 SPA，邮件客户端/浏览器直达也能正常显示。

---

## 9. 后台用户列表

### GET /api/v1/admin/users

**鉴权**：管理员

**查询参数**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `page` | int | 否 | 1 | 页码 |
| `page_size` | int | 否 | 10 | 每页条数 |
| `keyword` | string | 否 | — | 昵称/账号模糊匹配 |
| `status` | int | 否 | — | 1 启用 / 0 禁用，不传则全部 |
| `start_time` | string | 否 | — | 注册时间起，`YYYY-MM-DD` |
| `end_time` | string | 否 | — | 注册时间止，`YYYY-MM-DD` |

**成功响应**

> 注意这里有 `pageSize`（驼峰），不是 `page_size`。这是历史遗留，前端按这个取值。

```json
{
  "code": 0,
  "message": "成功",
  "data": {
    "list": [
      {
        "id": 2,
        "user_name": "测试用户",
        "avatar_url": "",
        "status": 1,
        "created_at": "2026-11-01T10:00:00Z"
      }
    ],
    "total": 1,
    "page": 1,
    "pageSize": 10
  }
}
```

**注意**：只返回 `role_id=0` 的普通用户，管理员不在列表里。

---

## 10. 后台创建用户

### POST /api/v1/admin/users

**请求体**

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `user_name` | string | 是 | 1-15 字符 |
| `account` | string | 是 | 11 位数字 |
| `password` | string | 是 | 11-20 位 |
| `status` | int | 是 | 0 或 1 |

```json
{ "user_name": "测试用户", "account": "13900000001", "password": "test1234567", "status": 1 }
```

**成功响应**

```json
{ "code": 0, "message": "成功", "data": { "id": 5 } }
```

**失败响应**

| 场景 | HTTP | code | message |
|---|---|---|---|
| 昵称/账号已存在 | 409 | 409 | 该昵称已经存在 / 该账号已经存在 |
| 账号格式错误 | 400 | 400 | 账号格式错误 |

---

## 11. 启用 / 禁用用户

### PUT /api/v1/admin/users/{id}

**路径参数**：`id` — 用户 ID

**请求体**

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `status` | int | 是 | 0 或 1 |

```json
{ "status": 0 }
```

**成功响应**

```json
{ "code": 0, "message": "成功" }
```

**失败响应**

| 场景 | HTTP | code | message |
|---|---|---|---|
| 用户不存在 | 404 | 404 | 用户不存在 |
| 改自己的状态 | 400 | 400 | 不能修改自己的状态 |

**注意**：禁用后该用户已有 token 仍有效（15 分钟内），但登录会被 1004 拦住。

---

## 12. 删除用户

### DELETE /api/v1/admin/users/{id}

**成功响应**

```json
{ "code": 0, "message": "成功" }
```

**失败响应**

| 场景 | HTTP | code | message |
|---|---|---|---|
| 用户不存在 | 404 | 404 | 用户不存在 |
| 删自己 | 400 | 400 | 不能删除自己 |

**注意**

- 软删除：写 `deleted_at`，数据仍在库里。
- **不级联**删除该用户的文章与评论，作者名会显示为空。
- 删除后 `account` 仍占用唯一索引，同一账号无法重新注册。
