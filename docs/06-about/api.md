# 06 关于页 · API 文档

前置约定见 [00-foundation/api.md](../00-foundation/api.md)。

## 接口总览

| # | 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|---|
| 1 | GET | `/api/v1/about` | 无 | 读取关于页 |
| 2 | PUT | `/api/v1/about` | 管理员 | 更新关于页 |

---

## 1. 读取关于页

### GET /api/v1/about

**请求参数**：无

**成功响应**

```json
{
  "code": 0,
  "message": "成功",
  "data": {
    "admin_name": "叶子",
    "avatar_url": "https://zouxp.xyz/blog-project/avatar/20261101/x.jpg",
    "email": "user@qq.com",
    "introduction": "写 Go 和 Python",
    "tech_stack": "Go,Python,MySQL,Redis",
    "my_story": "从后端开发开始...",
    "why": "想有个地方沉淀技术笔记",
    "interest": "分布式,数据库",
    "git_hub": "https://github.com/saber9050",
    "csdn": "https://blog.csdn.net/xxx"
  }
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `admin_name` | string | 管理员昵称 |
| `avatar_url` | string | 完整 URL，未设置为 `""` |
| `email` | string | 管理员邮箱 |
| `introduction` | string | 管理员个人简介 |
| `tech_stack` | string | 逗号分隔的技术栈 |
| `my_story` | string | 我的故事 |
| `why` | string | 为什么建站 |
| `interest` | string | 逗号分隔的兴趣方向 |
| `git_hub` | string | **注意字段名是 `git_hub`，不是 `github`** |
| `csdn` | string | CSDN 主页 |

**失败响应**

| 场景 | HTTP | code | message |
|---|---|---|---|
| 系统里没有管理员账号 | 404 | 404 | 资源不存在 |

**注意**

- 全新空库（`abouts` 表无记录）时**不报错**，6 个文字字段返回 `""`。
  只有连管理员都没有时才 404。
- 这个接口是前台页面 `/about` 的唯一数据源，前端不需要额外调 `/user/info`。

---

## 2. 更新关于页

### PUT /api/v1/about

**鉴权**：管理员

**请求体**（**部分更新**，只传要改的字段）

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| `tech_stack` | string \| null | 否 | ≤ 255 | 传 `null` 或不传 = 不修改 |
| `my_story` | string \| null | 否 | — | |
| `why` | string \| null | 否 | — | |
| `interest` | string \| null | 否 | ≤ 255 | |
| `git_hub` | string \| null | 否 | ≤ 255 | |
| `csdn` | string \| null | 否 | ≤ 255 | |

```json
{
  "tech_stack": "Go,Python,MySQL,Redis",
  "my_story": "从后端开发开始...",
  "interest": "分布式,数据库"
}
```

**成功响应**

```json
{ "code": 0, "message": "成功" }
```

**失败响应**

| 场景 | HTTP | code | message |
|---|---|---|---|
| 字段超长 | 400 | 400 | 请求参数错误 |
| 非管理员 | 401 / 403 | 401 / 403 | 未授权 / 禁止访问 |

**注意**

- 字段语义：
  - **不传** 或 传 `null` → 保持原值
  - 传 `""` → **清空该字段**
  - 传具体值 → 覆盖
- 这个语义与 Go 版的 `*string` 指针一致，前端已按此实现。
- 全部字段都不传时直接返回成功，不发 SQL。
