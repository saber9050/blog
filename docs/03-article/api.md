# 03 文章模块 · API 文档

前置约定见 [00-foundation/api.md](../00-foundation/api.md)。

## 接口总览

**前台**

| # | 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|---|
| 1 | GET | `/api/v1/articles` | 可选 | 文章列表 |
| 2 | GET | `/api/v1/articles/random` | 无 | 随机一篇 |
| 3 | GET | `/api/v1/articles/stats` | 无 | 站点统计 |
| 4 | GET | `/api/v1/articles/{id}` | 可选 | 文章详情 |
| 5 | POST | `/api/v1/articles/{id}/like` | 需登录 | 点赞 |
| 6 | DELETE | `/api/v1/articles/{id}/like` | 需登录 | 取消点赞 |

**后台（需管理员）**

| # | 方法 | 路径 | 说明 |
|---|---|---|---|
| 7 | GET | `/api/v1/admin/articles` | 文章列表 |
| 8 | POST | `/api/v1/admin/articles` | 新建 |
| 9 | PUT | `/api/v1/admin/articles/{id}` | 更新 |
| 10 | DELETE | `/api/v1/admin/articles/{id}` | 删除 |
| 11 | PUT | `/api/v1/admin/articles/transfer` | 批量转移分类 |
| 12 | POST | `/api/v1/admin/upload` | 上传图片 |

> 一键生成摘要 `POST /api/v1/admin/articles/generate-summary` 在
> [07-llm](../07-llm/api.md)，因为它的主体依赖是模型配置。

---

## 通用响应对象：`ArticleItem`

前台列表、详情、后台列表都复用这个结构。

```json
{
  "id": 12,
  "title": "FastAPI 重写实践",
  "summary": "记录一次从 Go 到 Python 的重写。",
  "cover_url": "https://zouxp.xyz/blog-project/all/20261109/ab12.jpg",
  "status": 1,
  "views": 128,
  "like_count": 9,
  "comment_count": 3,
  "is_liked": false,
  "author_name": "叶子",
  "category": { "id": 3, "name": "后端" },
  "tags": [{ "id": 1, "name": "Python" }],
  "created_at": "2026-11-01T10:00:00Z"
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `cover_url` | string | 完整 URL；无封面则 `""` |
| `category` | object \| null | 分类被删时为 `null` |
| `tags` | array | 无标签为 `[]` |
| `is_liked` | bool | 游客恒为 `false` |
| `comment_count` | int | 实时统计，不含已删评论 |
| `created_at` | string | `YYYY-MM-DDTHH:MM:SSZ` |

---

## 1. 文章列表

### GET /api/v1/articles

**鉴权**：可选。带 token 时 `is_liked` 才有意义。

**查询参数**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `page` | int | 否 | 1 | 页码 |
| `page_size` | int | 否 | 10 | 每页条数。Go 版无上限，本轮在 100 处截断 |
| `sort` | string | 否 | `latest` | `latest` 按发布时间倒序；`popular` 按热度 |
| `category_id` | int | 否 | — | 分类筛选 |
| `tag_ids` | string | 否 | — | 标签筛选，**逗号分隔**，如 `1,2,3`。命中任一标签即匹配 |
| `keyword` | string | 否 | — | 标题或摘要模糊匹配，不区分大小写 |

**成功响应**

```json
{
  "code": 0,
  "message": "成功",
  "data": {
    "list": [ { "id": 12, "title": "...", "...": "..." } ],
    "total": 19,
    "page": 1,
    "page_size": 10
  }
}
```

> 这里是 `page_size`（下划线）。后台用户列表才是 `pageSize`，别混。

**热度排序公式**

```
score = like_count * 3 + views * 1 + comment_count * 2
```

**注意**

- 只返回 `status=1`（已发布）且未删除的文章。
- 分类/标签被禁用不影响文章显示（只影响筛选源列表）。
- `keyword` 在 MySQL 的 ci 排序规则下天然不区分大小写，用 `LIKE` 即可。

---

## 2. 随机文章

### GET /api/v1/articles/random

**请求参数**：无

**成功响应**

```json
{
  "code": 0,
  "message": "成功",
  "data": { "id": 7 }
}
```

**失败响应**

| 场景 | HTTP | code | message |
|---|---|---|---|
| 站点还没有已发布文章 | 404 | 404 | 暂无文章 |

**用途**：首页「随便看看」按钮，前端拿到 id 后跳 `/article/{id}`。

---

## 3. 站点统计

### GET /api/v1/articles/stats

**请求参数**：无

**成功响应**

```json
{
  "code": 0,
  "message": "成功",
  "data": {
    "article_count": 19,
    "total_views": 3421,
    "total_likes": 23
  }
}
```

---

## 4. 文章详情

### GET /api/v1/articles/{id}

**鉴权**：可选

**路径参数**：`id` — 文章 ID

**成功响应**：`ArticleItem` 全部字段 + `content`

```json
{
  "code": 0,
  "message": "成功",
  "data": {
    "id": 12,
    "title": "FastAPI 重写实践",
    "content": "# 正文\nMarkdown 内容...",
    "...": "其余字段同 ArticleItem"
  }
}
```

**失败响应**

| 场景 | HTTP | code | message |
|---|---|---|---|
| 文章不存在/已删除 | 404 | 404 | 文章不存在 |

**注意**

- 每次请求**浏览量 +1**，包括作者本人和爬虫。
- 草稿（`status=0`）的访问控制：
  - Go 版：`FindByID` 不过滤 status，**游客也能通过 ID 直接打开草稿**，只靠前端路由遮挡。
  - 本轮：非作者且非管理员访问草稿返回 **404「文章不存在」**，
    不返回 403（避免暴露「这里有一篇草稿」这个事实）。

---

## 5. 点赞

### POST /api/v1/articles/{id}/like

**鉴权**：需登录

**请求体**：无

**成功响应**

```json
{ "code": 0, "message": "成功" }
```

**失败响应**

| 场景 | HTTP | code | message |
|---|---|---|---|
| 未登录 | 401 | 401 | 请提供认证令牌 |
| 文章不存在 | 404 | 404 | 文章不存在 |
| 用户被封禁 | 403 | 403 | 该用户已被封禁 |
| 重复点赞 | 400 | 400 | 您已经点赞过该文章 |

---

## 6. 取消点赞

### DELETE /api/v1/articles/{id}/like

**鉴权**：需登录

**成功响应**

```json
{ "code": 0, "message": "成功" }
```

**失败响应**

| 场景 | HTTP | code | message |
|---|---|---|---|
| 尚未点赞 | 400 | 400 | 您尚未点赞该文章 |

---

## 7. 后台文章列表

### GET /api/v1/admin/articles

**鉴权**：管理员

**查询参数**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `page` | int | 否 | 默认 1 |
| `page_size` | int | 否 | 默认 10 |
| `status` | int | 否 | 0 草稿 / 1 发布，不传则全部 |
| `category_id` | int | 否 | |
| `tag_id` | int | 否 | **单个**标签 ID，不是逗号分隔列表 |
| `keyword` | string | 否 | |

> 后台列表只支持按**单个**标签筛选（`tag_id`），与前台的 `tag_ids`（逗号分隔、
> 命中任一）不同。这是 Go 版的现状，前端后台筛选也是单选，照抄即可。

**成功响应**

```json
{
  "code": 0,
  "message": "成功",
  "data": {
    "list": [
      {
        "id": 12,
        "title": "...",
        "summary": "...",
        "cover_url": "",
        "status": 1,
        "views": 128,
        "like_count": 9,
        "comment_count": 3,
        "is_liked": false,
        "author_name": "叶子",
        "category": { "id": 3, "name": "后端" },
        "tags": [],
        "created_at": "2026-11-01T10:00:00Z",
        "updated_at": "2026-11-02T12:00:00Z"
      }
    ],
    "total": 19,
    "page": 1,
    "page_size": 10
  }
}
```

> 与 Go 版差异：**不再返回** `vector_status` / `vector_chunk_count` /
> `vector_error` / `vectorized_at` 四个字段。前端 AdminView 文章表格要同步删掉这 4 列。

---

## 8. 新建文章

### POST /api/v1/admin/articles

**鉴权**：管理员

**请求体**

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| `title` | string | 是 | ≤ 200 | 标题 |
| `type_id` | int | 是 | — | 分类 ID，必须存在 |
| `tag_ids` | int[] | 否 | — | 标签 ID 列表 |
| `cover_url` | string | 否 | — | 封面**完整 URL**（后端会转成 key 存库） |
| `summary` | string | 否 | ≤ 255 | 摘要，可用 AI 生成 |
| `content` | string | 是 | — | Markdown 正文 |
| `status` | int | 是 | 0 / 1 | 0 草稿 1 发布 |

```json
{
  "title": "FastAPI 重写实践",
  "type_id": 3,
  "tag_ids": [1, 2],
  "cover_url": "https://zouxp.xyz/blog-project/all/20261109/ab12.jpg",
  "summary": "记录一次从 Go 到 Python 的重写。",
  "content": "# 正文\n...",
  "status": 1
}
```

**成功响应**

```json
{ "code": 0, "message": "成功", "data": { "id": 12 } }
```

**失败响应**

| 场景 | HTTP | code | message |
|---|---|---|---|
| 缺 title / content | 400 | 400 | 请求参数错误 |
| 分类不存在 | 400 | 400 | 分类不存在 |
| 封面 URL 无法解析 | 500 | 500 | 解析url失败 |

**注意**

- 作者取当前登录管理员，不接受前端传 `user_id`。
- 正文里的 `<img src>` 会被解析出来写入 `article_images`，用于删文章时清理。

---

## 9. 更新文章

### PUT /api/v1/admin/articles/{id}

**鉴权**：管理员

**请求体**：字段同新建，但**全部可选**（只更新传了的字段）

```json
{ "title": "新标题", "status": 1 }
```

**成功响应**

```json
{ "code": 0, "message": "成功" }
```

**失败响应**：同新建

**注意**

- 正文变更**不会**自动重新生成摘要。
- 正文里删掉的图片会被从 MinIO 删除（差集同步）。
- 正文改成完全无图时，`article_images` 里的旧记录**不会被清空**（Go 版刻意行为）。

---

## 10. 删除文章

### DELETE /api/v1/admin/articles/{id}

**鉴权**：管理员

**成功响应**

```json
{ "code": 0, "message": "成功" }
```

**失败响应**

| 场景 | HTTP | code | message |
|---|---|---|---|
| 文章不存在 | 404 | 404 | 文章不存在 |

**副作用**

- 正文图片从 MinIO 删除，`article_images` 记录删除
- 封面图从 MinIO 删除
- 该文章下所有评论被软删除
- 文章本身软删除

**注意**：MinIO 删除失败不会导致接口报错，只记日志。

---

## 11. 批量转移分类

### PUT /api/v1/admin/articles/transfer

**鉴权**：管理员

**请求体**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `from_type_id` | int | 是 | 源分类 ID |
| `to_type_id` | int | 是 | 目标分类 ID |

```json
{ "from_type_id": 3, "to_type_id": 5 }
```

**成功响应**

```json
{ "code": 0, "message": "成功", "data": { "count": 12 } }
```

**失败响应**

| 场景 | HTTP | code | message |
|---|---|---|---|
| 分类不存在 | 400 | 400 | 分类不存在 |
| 源与目标相同 | 400 | 400 | 源分类与目标分类相同 |

**用途**：删分类前先把文章挪走。

---

## 12. 上传图片

### POST /api/v1/admin/upload

**鉴权**：管理员

**Content-Type**：`multipart/form-data`

**表单字段**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `file` | file | 是 | 图片文件 |

**限制**：≤ 10 MB；`.jpg` / `.jpeg` / `.png` / `.webp`

**成功响应**

```json
{
  "code": 0,
  "message": "成功",
  "data": { "url": "https://zouxp.xyz/blog-project/all/20261109/ab12.jpg" }
}
```

**失败响应**

| 场景 | HTTP | code | message |
|---|---|---|---|
| 超过 10 MB | 400 | 400 | 图片大小不能超过 10MB |
| 格式不支持 | 400 | 400 | 不支持的文件格式 |
| 上传失败 | 500 | 500 | 上传图片失败 |

**注意**

- 返回值是完整 URL，前端拿它塞进 Markdown；新建/更新文章时后端再转回 key。
- 同一张图重复上传会生成不同 key（没有去重），不做内容哈希。
