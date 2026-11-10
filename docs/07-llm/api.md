# 07 AI 模型 · API 文档

前置约定见 [00-foundation/api.md](../00-foundation/api.md)。

## 接口总览

| # | 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|---|
| 1 | GET | `/api/v1/admin/llm-configs` | 管理员 | 配置列表 |
| 2 | GET | `/api/v1/admin/llm-configs/{id}` | 管理员 | 配置详情 |
| 3 | POST | `/api/v1/admin/llm-configs/test` | 管理员 | 测试连接（不落库） |
| 4 | POST | `/api/v1/admin/llm-configs` | 管理员 | 新建配置 |
| 5 | PUT | `/api/v1/admin/llm-configs/{id}` | 管理员 | 更新运行参数 |
| 6 | DELETE | `/api/v1/admin/llm-configs/{id}` | 管理员 | 删除配置 |
| 7 | POST | `/api/v1/admin/articles/generate-summary` | 管理员 | 生成文章摘要 |

---

## 通用响应对象：`LLMConfig`

```json
{
  "id": 1,
  "base_url": "https://api.deepseek.com/v1",
  "api_key_masked": "sk-****cdef",
  "model": "deepseek-chat",
  "type": 1,
  "timeout_sec": 30,
  "max_tokens": 2048,
  "temperature": 0.3,
  "status": 1,
  "created_at": "2026-11-09T21:39:04Z",
  "updated_at": "2026-11-09T21:39:04Z"
}
```

| 字段 | 说明 |
|---|---|
| `api_key_masked` | 脱敏后的密钥。**明文永远不会返回**（库里存的是密文） |
| `type` | 恒为 `1`（对话模型）。字段保留是因为前端列表可能有类型列 |
| `dimension` | **不再返回**（新库无此列，向量功能已删） |

> 与 Go 版的差异：响应里少了 `dimension`。前端如果读这个字段会得到 `undefined`，
> 只要不参与渲染就不会报错。后台「AI 模型」页本来就要去掉这一列。

---

## 1. 配置列表

### GET /api/v1/admin/llm-configs

**请求参数**：无（配置条数极少，不分页）

**成功响应**

```json
{
  "code": 0,
  "message": "成功",
  "data": [
    {
      "id": 1,
      "base_url": "https://api.deepseek.com/v1",
      "api_key_masked": "sk-****cdef",
      "model": "deepseek-chat",
      "type": 1,
      "timeout_sec": 30,
      "max_tokens": 2048,
      "temperature": 0.3,
      "status": 1,
      "created_at": "2026-11-09T21:39:04Z",
      "updated_at": "2026-11-09T21:39:04Z"
    }
  ]
}
```

> `data` 直接是数组，不是分页对象。

**用途**：后台「AI 模型」页表格 + 编辑器里「用哪个模型生成摘要」的下拉框。

---

## 2. 配置详情

### GET /api/v1/admin/llm-configs/{id}

**成功响应**：单个 `LLMConfig` 对象

**失败响应**

| 场景 | HTTP | code | message |
|---|---|---|---|
| 不存在 | 404 | 404 | 配置不存在 |

---

## 3. 测试连接

### POST /api/v1/admin/llm-configs/test

**请求体**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `base_url` | string | 是 | 到 `/v1` 为止 |
| `model` | string | 是 | 模型 ID |
| `api_key` | string | 否 | 为空且传了 `id` 时，复用该配置已存的密钥 |
| `id` | int | 否 | 已有配置的 ID |
| `timeout_sec` | int | 否 | 测试用超时，服务端上限 15 秒 |

```json
{
  "base_url": "https://api.deepseek.com/v1",
  "model": "deepseek-chat",
  "api_key": "sk-1234567890abcdef"
}
```

**成功响应**（**永远 200**，成败看 `ok`）

```json
{
  "code": 0,
  "message": "成功",
  "data": {
    "ok": true,
    "latency_ms": 834,
    "reply": "连接成功"
  }
}
```

失败时：

```json
{
  "code": 0,
  "message": "成功",
  "data": {
    "ok": false,
    "latency_ms": 1203,
    "error": "LLM 返回异常状态码 401: Invalid API key"
  }
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `ok` | bool | 是否连通 |
| `latency_ms` | int | 耗时毫秒 |
| `reply` | string | 模型的回复，成功时才有 |
| `error` | string | 失败原因，失败时才有 |

**注意**

- **故意不用 HTTP 500 表示失败**：连不通是预期结果，不是服务器错误。
  前端按 `data.ok` 判断即可。
- 上游的错误信息会被透传（只取 `error.message`，不返回完整响应体）。

---

## 4. 新建配置

### POST /api/v1/admin/llm-configs

**请求体**

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| `base_url` | string | 是 | — | 到 `/v1` 为止 |
| `api_key` | string | 是 | — | 密钥 |
| `model` | string | 是 | — | 模型 ID |
| `timeout_sec` | int | 否 | 默认 30 | |
| `max_tokens` | int | 否 | 默认 2048 | |
| `temperature` | float | 否 | 默认 0.3 | |
| `status` | int | 否 | 0/1，默认 1 | |

```json
{
  "base_url": "https://api.deepseek.com/v1",
  "api_key": "sk-1234567890abcdef",
  "model": "deepseek-chat",
  "timeout_sec": 30,
  "max_tokens": 2048,
  "temperature": 0.3
}
```

**成功响应**：返回脱敏后的 `LLMConfig`

**失败响应**

| 场景 | HTTP | code | message |
|---|---|---|---|
| 缺 base_url / api_key / model | 400 | 400 | 请求参数错误 |
| **测试连接失败** | 400 | 400 | 配置不可用，测试连接失败：LLM 返回异常状态码 401: Invalid API key |

**注意**

- **先测连接，通过才入库**。测试失败时数据库里不会留下记录。
- 服务端强制 `type=1`，请求体里的 `type` 字段被忽略。

---

## 5. 更新配置

### PUT /api/v1/admin/llm-configs/{id}

**请求体**（只允许改运行参数与状态）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `timeout_sec` | int | 否 | 默认 30 |
| `max_tokens` | int | 否 | 默认 2048 |
| `temperature` | float | 否 | 默认 0.3 |
| `status` | int | 否 | 不传则保持原值 |

```json
{ "timeout_sec": 60, "status": 1 }
```

**成功响应**

```json
{ "code": 0, "message": "成功" }
```

**失败响应**

| 场景 | HTTP | code | message |
|---|---|---|---|
| 配置不存在 | 404 | 404 | 配置不存在 |

**注意**

- `base_url` / `api_key` / `model` **不可修改**，传了也会被忽略。
  要换模型请删了重建，避免「改了一个字段但连接信息还是旧的」这种半吊子状态。
- 不传的字段会取默认值（30 / 2048 / 0.3），不是保持原值 —— 这是 Go 版行为，
  前端每次都提交完整表单，所以看不出来。

---

## 6. 删除配置

### DELETE /api/v1/admin/llm-configs/{id}

**成功响应**

```json
{ "code": 0, "message": "成功" }
```

**失败响应**

| 场景 | HTTP | code | message |
|---|---|---|---|
| 配置不存在 | 404 | 404 | 配置不存在 |

**注意**：物理删除。已生成的历史摘要存在 `articles.summary` 里，不受影响。

---

## 7. 生成文章摘要

### POST /api/v1/admin/articles/generate-summary

**鉴权**：管理员

> 路径挂在 `/admin/articles` 下，但实现在本模块（依赖模型配置）。
> 前端调用方式不变。

**请求体**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `config_id` | int | 是 | 用哪条模型配置 |
| `title` | string | 是 | 文章标题 |
| `content` | string | 是 | 文章正文（Markdown / HTML 均可） |

```json
{
  "config_id": 1,
  "title": "FastAPI 重写实践",
  "content": "# 背景\n这次重写把 Go 换成了 Python..."
}
```

**成功响应**

```json
{
  "code": 0,
  "message": "成功",
  "data": {
    "summary": "记录一次从 Go 到 Python 的后端重写，重点说明接口契约保持不变、数据库迁移到 MySQL 8 的取舍。"
  }
}
```

| 字段 | 说明 |
|---|---|
| `summary` | 摘要文本，≤ 255 字符，已去掉首尾引号 |

**失败响应**

| 场景 | HTTP | code | message |
|---|---|---|---|
| 缺字段 | 400 | 400 | 请求参数错误 |
| 正文为空（清洗后） | 400 | 400 | 文章内容为空 |
| 配置不存在 | 404 | 404 | 配置不存在 |
| 配置被禁用 | 400 | 400 | 该模型配置已禁用，请先在「AI 模型」页启用 |
| 模型调用失败 | 500 | 500 | LLM 返回异常状态码 401: ... |

**注意**

- **摘要不落库**。接口只负责生成，前端拿到后填进编辑器的摘要输入框，
  用户确认后随文章一起保存。
- 正文超过 8000 字符会被截断（按字符，不是字节）。
- 同一篇内容重复调用会重复消耗 token，没有缓存。
- 调用耗时通常 3-10 秒，**Nginx 的 `proxy_read_timeout` 要大于 60 秒**，
  否则会看到 504。
- **路由注册顺序**：这条路径挂在 `/admin/articles` 前缀下，与 03 模块的
  `PUT /admin/articles/{id}` 共用前缀。FastAPI 按注册顺序匹配，虽然
  本接口是 POST 不与 PUT 冲突，但仍建议把所有静态路径排在 `{id}` 之前，
  避免将来新增 `POST /admin/articles/{id}` 时踩坑。
