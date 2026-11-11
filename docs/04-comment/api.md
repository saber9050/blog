# 04 评论模块 · API 文档

前置约定见 [00-foundation/api.md](../00-foundation/api.md)。

## 接口总览

**前台（挂在 `/articles` 下）**

| # | 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|---|
| 1 | GET | `/api/v1/articles/{article_id}/comments` | 无 | 一级评论列表 |
| 2 | GET | `/api/v1/articles/{article_id}/comments/{comment_id}/replies` | 无 | 二级回复列表 |
| 3 | POST | `/api/v1/articles/{article_id}/comments` | 需登录 | 发表评论/回复 |
| 4 | DELETE | `/api/v1/articles/{article_id}/comments/{comment_id}` | 需登录 | 删除评论 |

**后台（需管理员）**

| # | 方法 | 路径 | 说明 |
|---|---|---|---|
| 5 | GET | `/api/v1/admin/comments` | 评论列表 |
| 6 | DELETE | `/api/v1/admin/comments/{comment_id}` | 删除单条 |
| 7 | DELETE | `/api/v1/admin/comments` | 批量删除 |

---

## 通用响应对象：`CommentItem`

```json
{
  "id": 34,
  "content": "写得很清楚，学到了",
  "user_id": 2,
  "user_name": "路人甲",
  "avatar_url": "https://zouxp.xyz/blog-project/avatar/20261101/x.jpg",
  "parent_id": null,
  "reply_to_name": "",
  "is_deleted": false,
  "created_at": "2026-11-09T21:39:04.123456+08:00",
  "children_total": 3
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `parent_id` | int \| null | `null` 或 `0` 表示一级评论 |
| `reply_to_name` | string | 回复目标昵称（快照） |
| `is_deleted` | bool | 已删除的评论仍返回，`content` 为空 |
| `created_at` | string | **注意格式与文章不同**，见下 |
| `children_total` | int | 子回复数。回复列表里恒为 0 |

> ⚠️ **时间格式不一致，必须照抄**：
> - 文章 `created_at` 是 `"2026-11-09T21:39:04Z"`（Go 的 string 格式化，假 Z）
> - 评论 `created_at` 是 `"2026-11-09T21:39:04.123456+08:00"`（Go 的 `time.Time`
>   直接 JSON 序列化，带时区和微秒）
>
> 前端对这两种格式都用 `new Date()` 解析，能正常工作。重写时 Python 侧要分别输出：
> 文章用 `strftime("%Y-%m-%dT%H:%M:%SZ")`，评论用 `isoformat()`。

---

## 1. 一级评论列表

### GET /api/v1/articles/{article_id}/comments

**路径参数**：`id` — 文章 ID

**查询参数**

| 参数 | 类型 | 必填 | 默认 | 上限 |
|---|---|---|---|---|
| `page` | int | 否 | 1 | — |
| `page_size` | int | 否 | 20 | 50 |

**成功响应**

```json
{
  "code": 0,
  "message": "成功",
  "data": {
    "list": [
      {
        "id": 34,
        "content": "写得很清楚，学到了",
        "user_id": 2,
        "user_name": "路人甲",
        "avatar_url": "https://zouxp.xyz/blog-project/avatar/20261101/x.jpg",
        "parent_id": null,
        "reply_to_name": "",
        "is_deleted": false,
        "created_at": "2026-11-09T21:39:04.123456+08:00",
        "children_total": 3
      }
    ],
    "total": 8,
    "page": 1,
    "page_size": 20
  }
}
```

**注意**

- 按 `created_at DESC` 排序（新的在上）。
- **已删除的评论也会返回**，`is_deleted: true` 且 `content: ""`，前端显示「该评论已删除」。
- **`total` 与 `list` 的口径一致，都包含已删评论**。不要只算未删的，
  否则会出现「total=3 但列表渲染 5 条」的分页错位（Go 版就有这个 bug，重写要修掉）。
- 文章不存在时也返回空列表，不报 404（Go 版行为）。

---

## 2. 二级回复列表

### GET /api/v1/articles/{article_id}/comments/{comment_id}/replies

**路径参数**

| 参数 | 说明 |
|---|---|
| `id` | 文章 ID |
| `comment_id` | 一级评论 ID |

**查询参数**

| 参数 | 类型 | 必填 | 默认 | 上限 |
|---|---|---|---|---|
| `page` | int | 否 | 1 | — |
| `page_size` | int | 否 | **10** | **30** |

> 与一级列表的默认值和上限都不同，前端已按这个写死。

**成功响应**：结构同 1，但 `children_total` 恒为 `0`

**注意**

- 按 `created_at **ASC**` 排序（对话顺序，早的在上）—— 与一级评论的 DESC 相反。
- 同样包含已删回复，`total` 口径与列表一致。
- `id`（文章 ID）只用于路径一致性，**不做归属校验** —— 传了别的文章 ID 也能查到。
  这是 Go 版行为，本轮保持（无安全影响，评论本身是公开的）。

---

## 3. 发表评论 / 回复

### POST /api/v1/articles/{article_id}/comments

**鉴权**：需登录

**请求体**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `content` | string | 是 | 评论内容 |
| `parent_id` | int \| null | 否 | 回复某条一级评论时传；一级评论传 `null` 或不传 |
| `reply_to_user_name` | string | 否 | 回复目标昵称，二级评论展示用 |

一级评论：

```json
{ "content": "写得很清楚，学到了" }
```

回复：

```json
{
  "content": "同意，特别是 N+1 那段",
  "parent_id": 34,
  "reply_to_user_name": "路人甲"
}
```

**成功响应**：返回新建的 `CommentItem`

```json
{
  "code": 0,
  "message": "成功",
  "data": {
    "id": 35,
    "content": "同意，特别是 N+1 那段",
    "user_id": 1,
    "user_name": "叶子",
    "avatar_url": "",
    "parent_id": 34,
    "reply_to_name": "路人甲",
    "is_deleted": false,
    "created_at": "2026-11-09T21:40:12.654321+08:00",
    "children_total": 0
  }
}
```

**失败响应**

| 场景 | HTTP | code | message |
|---|---|---|---|
| 内容为空 | 400 | 400 | 请求参数错误 |
| 用户不存在 | 404 | 404 | 用户不存在 |
| 用户被封禁 | 403 | 403 | 该用户已被封禁 |
| 父评论不存在 | 404 | 404 | 资源不存在 |
| 父评论属于别的文章 | 400 | 400 | 父评论不属于该文章 |

---

## 4. 删除评论

### DELETE /api/v1/articles/{article_id}/comments/{comment_id}

**鉴权**：需登录。作者本人或管理员可删，其他人 403。

**成功响应**

```json
{ "code": 0, "message": "成功" }
```

**失败响应**

| 场景 | HTTP | code | message |
|---|---|---|---|
| 评论不存在 | 404 | 404 | 资源不存在 |
| 既不是作者也不是管理员 | 403 | 403 | 禁止访问 |

**注意**

- 软删除。删除后该评论在列表中仍占位，`is_deleted: true`、`content: ""`。
- **删一级评论会级联软删它下面所有回复**。Go 版只删一条、留一堆孤儿回复，
  本轮改掉（见 design 7.1）。

---

## 5. 后台评论列表

### GET /api/v1/admin/comments

**鉴权**：管理员

**查询参数**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `page` | int | 否 | 1 | |
| `page_size` | int | 否 | 10 | 上限 50 |
| `article_title` | string | 否 | — | 按文章标题模糊匹配 |
| `user_name` | string | 否 | — | 按评论者昵称模糊匹配 |
| `start_time` | string | 否 | — | `YYYY-MM-DD` |
| `end_time` | string | 否 | — | `YYYY-MM-DD` |

**成功响应**

```json
{
  "code": 0,
  "message": "成功",
  "data": {
    "list": [
      {
        "id": 34,
        "article_title": "FastAPI 重写实践",
        "user_name": "路人甲",
        "content": "写得很清楚，学到了",
        "created_at": "2026-11-09T21:39:04Z"
      }
    ],
    "total": 4,
    "page": 1,
    "page_size": 10
  }
}
```

> 后台列表的 `created_at` 又是字符串格式（`...Z`），与前台评论接口不同。
> 三处格式：文章 `...Z`、前台评论 `+08:00`、后台评论 `...Z`。照抄即可，别顺手统一。

**注意**：只返回未删除的评论（`deleted_at IS NULL`）。

---

## 6. 删除单条评论

### DELETE /api/v1/admin/comments/{comment_id}

**鉴权**：管理员

**成功响应**

```json
{ "code": 0, "message": "成功" }
```

**失败响应**

| 场景 | HTTP | code | message |
|---|---|---|---|
| 评论不存在 | 404 | 404 | 资源不存在 |

---

## 7. 批量删除评论

### DELETE /api/v1/admin/comments

**鉴权**：管理员

**请求体**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `ids` | int[] | 是 | 要删除的评论 ID 列表 |

```json
{ "ids": [34, 35, 36] }
```

**成功响应**

```json
{ "code": 0, "message": "成功", "data": { "count": 3 } }
```

**注意**

- 空数组直接返回 `count: 0`，不报错。
- 不存在的 ID 会被跳过，`count` 是实际删除条数。
