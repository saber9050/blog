# 06 关于页 · 设计方案

## 1. 职责与边界

**做什么**

- 读取关于页：站点管理员的基本信息 + 关于页文字内容
- 更新关于页：部分更新，只改传了的字段

**不做什么**

- 不管管理员资料的编辑（走 02-user 的 `/user/profile`）
- 不支持多语言、多版本

---

## 2. 目录结构

```
app/
├── api/v1/about.py                   # AboutController（2 条）
├── services/about_service.py         # AboutService
├── repositories/about_repository.py
└── schemas/about.py
```

---

## 3. 类设计

### 3.1 `AboutController`

```python
class AboutController:
    """关于页接口。

    只有两个方法，但仍然单独成类：
      GET  /about       无鉴权（任何人可看）
      PUT  /about       管理员
    两条路由鉴权级别不同，放在同一个类的 router 里用不同依赖声明即可。
    """

    def __init__(self, service: AboutService) -> None: ...

    def router(self) -> APIRouter: ...

    async def get_about(self) -> JSONResponse: ...
    async def update_about(self, req: AboutUpdateRequest) -> JSONResponse: ...
```

### 3.2 `AboutService`

```python
class AboutService:
    """关于页读写。

    这个服务需要跨两个领域取数据：
      - 管理员信息（昵称、头像、邮箱、简介）来自 users 表
      - 技术栈、故事、为什么建站等来自 abouts 表
    所以同时注入 UserRepository 与 AboutRepository。
    """

    def __init__(
        self,
        repo: AboutRepository,
        user_repo: UserRepository,
        storage: SupportsFileStorage,
    ) -> None: ...

    async def get_info(self) -> AboutInfoResponse:
        """读取关于页。

        管理员取 role_id=1 的第一个用户（站点只有一个管理员）。
            └─ 一个管理员都没有 → 404「资源不存在」

        abouts 表可能一条记录都没有（新站）。
            └─ 此时返回管理员信息 + 所有文字字段为空字符串，不报错。

        这是关键：新库是空的，如果没记录就报 404，前端关于页整页打不开。
        """

    async def update(self, req: AboutUpdateRequest) -> None:
        """部分更新。只写传了的字段。

        用 `Optional[str]` 而不是 `str` 来区分「不传」与「传空」：
          - 字段缺失（None）→ 不动
          - 传 "" → 清空该字段
        Go 版用的是 `*string` 指针，语义一致。
        """

    # ---------- 内部 ----------

    async def _ensure_row(self) -> About:
        """取单行；不存在则插入一条空记录。

        abouts 是单例表，全表只会有一行。用「先查，没有再建」而不是
        固定 id=1，避免有人手工清过表后应用直接崩。
        """
```

### 3.3 `AboutRepository`

```python
class AboutRepository:
    """abouts 表访问。单行表，不需要分页。"""

    async def get_singleton(self) -> About | None:
        """取第一行。用 LIMIT 1 而不是 WHERE id = 1，容忍主键不连续的脏数据。"""

    async def insert_empty(self) -> int: ...

    async def update_fields(self, about_id: int, **fields: Any) -> None: ...
```

---

## 4. 数据模型

### `abouts`

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | `BIGINT` | PK |
| `tech_stack` | `VARCHAR(255)` | 技术栈，逗号分隔 |
| `my_story` | `TEXT` | 我的故事 |
| `why` | `TEXT` | 为什么建这个博客 |
| `interest` | `VARCHAR(255)` | 感兴趣的技术，逗号分隔 |
| `git_hub` | `VARCHAR(255)` | GitHub 地址 |
| `csdn` | `VARCHAR(255)` | CSDN 地址 |
| `created_at` / `updated_at` | `DATETIME` | |

> 列名是 `git_hub`（不是 `github`），响应 JSON 字段也是 `git_hub`。
> 前端已按这个取值，**照抄**。

**约束**：无外键、无软删、无索引（数据量恒为 1 行，不需要）。

---

## 5. 核心流程

### 5.1 读取

```
GET /about
 → SELECT * FROM users WHERE role_id = 1 AND deleted_at IS NULL LIMIT 1
     └─ 无 → 404
 → avatar_url 转完整 URL（存的是 key）
 → SELECT * FROM abouts LIMIT 1
     ├─ 有 → 填充 6 个文字字段
     └─ 无 → 6 个字段返回 ""
 → 合并返回
```

### 5.2 更新

```
PUT /about {tech_stack: "Go,Python", my_story: null, why: "..."}
 → 校验各字段长度（tech_stack ≤ 255、interest ≤ 255、git_hub ≤ 255、csdn ≤ 255）
 → 取单行（没有则插入空行）
 → 收集非 None 的字段
     └─ 空 dict → 直接返回成功（无字段可改）
 → UPDATE abouts SET ... WHERE id = ?
```

---

## 6. 错误码

| 场景 | code | message |
|---|---|---|
| 没有管理员账号 | 404 | 资源不存在 |
| 字段超长 | 400 | 请求参数错误 |

---

## 7. 测试要点

| # | 用例 | 断言 |
|---|---|---|
| 1 | 全新空库（无 abouts 记录） | GET 返回 200，文字字段为 `""`，不报 404 |
| 2 | 无管理员账号 | GET 返回 404 |
| 3 | 只传 `tech_stack` | 其他字段不变 |
| 4 | 传 `my_story: ""` | 该字段被清空（不是忽略） |
| 5 | 传 `my_story: null` | 不修改 |
| 6 | `git_hub` 字段名 | 响应里是 `git_hub`，不是 `github` |
| 7 | 管理员换头像后 | GET /about 返回新头像完整 URL |

---

## 8. 开放问题

1. **`tech_stack` / `interest` 是逗号分隔的字符串**，不是数组。前端自己 split。
   是否改成数组？改了前端要动，建议保持。
2. **多管理员时取第一个**：`role_id=1` 若有多个，只显示最早创建的那个。
   单管理员站没问题，是否需要明确约束？建议不加（约束了反而麻烦）。
3. **`abouts` 允许存在多行**：没有唯一约束。代码取 LIMIT 1，多余的行会被忽略。
   是否加约束保证单行？建议不做，靠代码控制即可。
