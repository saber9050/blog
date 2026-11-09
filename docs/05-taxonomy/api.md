# 05 分类与标签 · API 文档

前置约定见 [00-foundation/api.md](../00-foundation/api.md)。

## 接口总览

**前台**

| # | 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|---|
| 1 | GET | `/api/v1/categories` | 无 | 启用的分类列表 |
| 2 | GET | `/api/v1/categories/count` | 无 | 启用分类数量 |
| 3 | GET | `/api/v1/tags` | 无 | 启用的标签列表 |
| 4 | GET | `/api/v1/tags/count` | 无 | 启用标签数量 |

**后台（需管理员）**

| # | 方法 | 路径 | 说明 |
|---|---|---|---|
| 5 | GET | `/api/v1/admin/categories` | 分类列表 |
| 6 | POST | `/api/v1/admin/categories` | 新建分类 |
| 7 | PUT | `/api/v1/admin/categories/{id}` | 更新分类 |
| 8 | DELETE | `/api/v1/admin/categories/{id}` | 删除分类 |
| 9 | GET | `/api/v1/admin/tags` | 标签列表 |
| 10 | POST | `/api/v1/admin/tags` | 新建标签 |
| 11 | PUT | `/api/v1/admin/tags/{id}` | 更新标签 |
| 12 | DELETE | `/api/v1/admin/tags/{id}` | 删除标签 |

---

## 1. 分类列表（前台）

### GET /api/v1/categories

**请求参数**：无

**成功响应**

```json
{
  "code": 0,
  "message": "成功",
  "data": [
    { "id": 3, "name": "后端" },
    { "id": 4, "name": "前端" }
  ]
}
```

> `data` 直接是数组，**不是分页对象**。

**注意**：只返回 `status=1` 的分类，按创建时间正序。空则返回 `[]`。

---

## 2. 分类数量

### GET /api/v1/categories/count

**成功响应**

```json
{ "code": 0, "message": "成功", "data": { "count": 3 } }
```

**注意**：只统计启用的。

---

## 3. 标签列表（前台）

### GET /api/v1/tags

**成功响应**

```json
{
  "code": 0,
  "message": "成功",
  "data": [
    { "id": 1, "name": "Python" },
    { "id": 2, "name": "FastAPI" }
  ]
}
```

---

## 4. 标签数量

### GET /api/v1/tags/count

**成功响应**

```json
{ "code": 0, "message": "成功", "data": { "count": 4 } }
```

---

## 5. 后台分类列表

### GET /api/v1/admin/categories

**鉴权**：管理员

**查询参数**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `page` | int | 否 | 1 | |
| `page_size` | int | 否 | 10 | |
| `status` | int | 否 | — | 0 / 1，不传则全部 |
| `keyword` | string | 否 | — | 名称模糊匹配 |
| `start_time` | string | 否 | — | `YYYY-MM-DD` |
| `end_time` | string | 否 | — | `YYYY-MM-DD` |

**成功响应**

```json
{
  "code": 0,
  "message": "成功",
  "data": {
    "list": [
      { "id": 3, "name": "后端", "status": 1, "created_at": "2026-11-01T10:00:00Z" }
    ],
    "total": 1,
    "page": 1,
    "page_size": 10
  }
}
```

---

## 6. 新建分类

### POST /api/v1/admin/categories

**请求体**

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `name` | string | 是 | ≤ 50 字符 |
| `status` | int | 是 | 0 / 1 |

```json
{ "name": "后端", "status": 1 }
```

**成功响应**

```json
{ "code": 0, "message": "成功", "data": { "id": 5 } }
```

**失败响应**

| 场景 | HTTP | code | message |
|---|---|---|---|
| 名称为空/超长 | 400 | 400 | 请求参数错误 |
| 名称已存在 | 400 | 400 | 分类名称已存在 |

**注意**：名称入库前会 `strip()`，首尾空格不参与比较与存储。

---

## 7. 更新分类

### PUT /api/v1/admin/categories/{id}

**请求体**：同新建（`name` 与 `status` 都必填）

```json
{ "name": "后端开发", "status": 1 }
```

**成功响应**

```json
{ "code": 0, "message": "成功" }
```

**失败响应**

| 场景 | HTTP | code | message |
|---|---|---|---|
| 分类不存在 | 404 | 404 | 分类不存在 |
| 名称与其他分类重复 | 400 | 400 | 分类名称已存在 |

**注意**：查重时排除自己，所以只改大小写或改回原名不会报错。

---

## 8. 删除分类

### DELETE /api/v1/admin/categories/{id}

**成功响应**

```json
{ "code": 0, "message": "成功" }
```

**失败响应**

| 场景 | HTTP | code | message |
|---|---|---|---|
| 分类不存在 | 404 | 404 | 分类不存在 |
| 分类下有文章 | 400 | 400 | 该分类下存在文章，无法删除 |

**注意**

- **物理删除**，不是软删（`categorys` 表没有 `deleted_at`）。
- 有文章时拒绝删除，必须先在后台「批量转移分类」把文章挪走。

---

## 9. 后台标签列表

### GET /api/v1/admin/tags

**查询参数**：同分类列表

**成功响应**

```json
{
  "code": 0,
  "message": "成功",
  "data": {
    "list": [
      { "id": 1, "name": "Python", "status": 1, "created_at": "2026-11-01T10:00:00Z" }
    ],
    "total": 1,
    "page": 1,
    "page_size": 10
  }
}
```

---

## 10. 新建标签

### POST /api/v1/admin/tags

**请求体**

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `name` | string | 是 | ≤ 100 字符 |
| `status` | int | 是 | 0 / 1 |

```json
{ "name": "FastAPI", "status": 1 }
```

**成功响应**

```json
{ "code": 0, "message": "成功", "data": { "id": 6 } }
```

**失败响应**：名称重复 → 400「标签名称已存在」

---

## 11. 更新标签

### PUT /api/v1/admin/tags/{id}

**请求体**：同新建

**成功响应**

```json
{ "code": 0, "message": "成功" }
```

**失败响应**：标签不存在 404 / 名称重复 400

---

## 12. 删除标签

### DELETE /api/v1/admin/tags/{id}

**成功响应**

```json
{ "code": 0, "message": "成功" }
```

**失败响应**：标签不存在 → 404「标签不存在」

**注意**

- 与分类不同：**标签下有文章也允许删除**。
- 删除时先清 `tag_articles` 里的关联，文章本身不受影响，只是少一个标签。
- 物理删除。
