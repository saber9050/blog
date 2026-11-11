# 项目文档索引

FastAPI 重写版博客后端。总体方案见 [rewrite-plan.md](./rewrite-plan.md)。

## 模块划分

每个模块一个目录，内含 `design.md`（设计方案）和 `api.md`（接口文档）。
开发顺序即编号顺序，后续模块依赖前序模块。

| 编号 | 模块 | 目录 | 职责 | 接口数 | 依赖 |
|---|---|---|---|---|---|
| 00 | 基础设施 | [00-foundation](./00-foundation/) | 配置、数据库、Redis、MinIO、日志、统一响应、错误码、鉴权依赖 | 1 | — |
| 01 | 认证 | [01-auth](./01-auth/) | 注册、登录、验证码、双 Token、刷新、登出 | 10 | 00 |
| 02 | 用户 | [02-user](./02-user/) | 资料、头像、改密、改邮箱、后台用户管理 | 12 | 00、01 |
| 03 | 文章 | [03-article](./03-article/) | 文章 CRUD、列表筛选、详情、点赞、图片上传 | 12 | 00、01、02、05 |
| 04 | 评论 | [04-comment](./04-comment/) | 两级评论、删除、后台管理 | 7 | 00、01、03 |
| 05 | 分类与标签 | [05-taxonomy](./05-taxonomy/) | 分类、标签、文章关联 | 12 | 00、01 |
| 06 | 关于页 | [06-about](./06-about/) | 单例内容读写 | 2 | 00、01 |
| 07 | AI 模型 | [07-llm](./07-llm/) | 模型配置 CRUD、连接测试、文章摘要 | 7 | 00、01、03 |
| | **合计** | | | **63** | |

> 63 条与 Go 版保留的接口数一一对应（原 83 条减去删除的 20 条）。

> 上传接口 `/api/v1/admin/upload` 归在 03-article（文章封面图与正文图片），
> 用户头像上传归在 02-user，两者共用 00-foundation 里的 `MinioStorage` 类。

## 文档模板

### `design.md` 必须包含

1. **职责与边界** —— 这个模块做什么、不做什么
2. **类设计** —— 类名、职责、关键方法签名、依赖关系（面向对象，不允许散装函数）
3. **数据模型** —— 表结构、字段类型、索引
4. **核心流程** —— 至少一条主流程的分步说明
5. **错误码** —— 本模块会抛出的业务错误
6. **测试要点** —— 单测/集成测试要覆盖的场景
7. **开放问题** —— 需要用户拍板的点

### `api.md` 必须包含

1. 接口总览表（方法、路径、鉴权、一句话说明）
2. 每个接口的请求参数表、请求示例、成功响应、失败响应
3. 字段命名严格对照 Go 版本，不做改进

## 设计决策清单

各模块 `design.md` 末尾的「开放问题」汇总在这里，并写明本轮的取舍。
标 ★ 的影响建表结构，P0 建表后再改就要清数据，**动工前先确认这几条**。

| # | 模块 | 问题 | 本轮做法 | 影响 |
|---|---|---|---|---|
| 1 ★ | 03-article | `likes` 表缺唯一索引，并发双击重复计数 | **加 `UNIQUE(article_id, user_id)`** | 建表时加，后期加要先去重 |
| 2 ★ | 05-taxonomy | 分类/标签名称查重只靠代码 | **加唯一索引** | 同上 |
| 3 | 02-user | 改昵称撞唯一索引返回 500 | **先查重，冲突返回 409** | 后端 1 处，前端不用动 |
| 4 | 02-user | 简介传 `""` 无法清空 | **`None` 不修改、`""` 清空** | 后端 1 处，前端调用不变 |
| 5 | 04-comment | 删一级评论不级联，子回复变孤儿 | **级联软删** | 后端 1 处，前端不用动 |
| 6 | 03-article | 草稿文章游客也能通过 ID 访问 | **非作者非管理员返回 404** | 后端 1 处，前端路由不用动 |
| 7 | 07-llm | `api_key` 明文存库 | **Fernet 加密**（密钥放 `config.yaml`） | +0.5 天 |
| 8 | 01-auth | Go 版预留的 `blacklist:token` 从未使用 | **不实现** | 登出靠删 refresh key 已够 |
| 9 | 00-foundation | 请求日志是否记录 body | **不记**（含密码的接口无法脱敏） | — |
| 10 | 07-llm | 摘要结果不缓存，重复点击重复花钱 | **本轮不做**，后续迭代 | 不影响本轮 |
| 11 | 04-comment | 评论列表 `total` 与文章 `comment_count` 口径不一致 | **统一为含已删**（改 `comment_count` 的 SQL） | 后端 1 处，前端不用动 |
| 12 | 05-taxonomy | 分类/标签名称入参不 strip | **入参 strip()** | 后端 1 处 |

> 第 1、2 条加唯一索引后，插入逻辑要跟着改：`likes` 的「先查后插」改成
> 捕获 `IntegrityError` 当作「已点赞」处理，否则并发下会 500 而不是 400。

**这 12 条就是开发时的执行口径。** 哪条不同意，现在说；不说就按这个做。

---

## 开发规范（2026-11-09 确定）

### 路由注册顺序（FastAPI 必守）

**静态路径必须定义在 `{id}` 之前。** FastAPI 按注册顺序线性匹配，
`{article_id}` 能匹配任意字符串；匹配上之后 `int()` 转换失败会直接返回 422，
**不会回退去试下一条路由**。

Go 的 gin 用路由树，静态路径优先级自动更高，所以原有代码写反了也不出事 ——
这是重写时最容易静默踩中的坑。

```python
# ✅
@router.get("/articles/random")
@router.get("/articles/stats")
@router.get("/articles/{article_id}")

# ❌ /articles/random 会被当成 article_id="random"
@router.get("/articles/{article_id}")
@router.get("/articles/random")
```

受影响的路径：`/articles/random`、`/articles/stats`、`/admin/articles/transfer`、
`/admin/articles/generate-summary`。跨文件 `include_router` 时也要注意先后。

### 面向对象

- **不允许模块级业务函数**。业务逻辑一律放在 `Service` 类的方法里。
- 三层结构，每层都是类：
  - `api/v1/*.py` → `XxxController` 类（或用 FastAPI 的 `APIRouter` + 类实例方法）
  - `services/*.py` → `XxxService` 类
  - `repositories/*.py` → `XxxRepository` 类
- 依赖通过构造函数注入（`__init__` 接收），不在方法内部 new 依赖。
- 跨模块协作用 `Protocol` 定义契约（见 00-foundation 的 `protocols.py`），不用继承 ABC，
  避免为了抽象而抽象。

```python
# 正确
class ArticleService:
    def __init__(
        self,
        repo: ArticleRepository,
        user_repo: UserRepository,
        storage: MinioStorage,
    ) -> None:
        self._repo = repo
        ...

# 错误：模块级函数 + 全局变量
def create_article(...):
    ...
```

### 注释

- **每个类必须有 docstring**，说清职责 + 使用场景。
- **每个公开方法必须有 docstring**，至少包含：做什么、参数、返回、抛什么异常。
- 复杂逻辑（非显而易见的分支、魔法数字、兼容性处理）必须有行内注释说明**为什么**，
  不是说明"做了什么"。
- 注释用中文，`Args` / `Returns` / `Raises` 段用英文关键字（Google 风格），保持 IDE 提示正常。

```python
async def login(self, req: LoginRequest) -> LoginResponse:
    """账号密码登录。

    校验图形验证码 → 校验账号状态 → 校验密码 → 签发双 Token。
    单设备登录：新登录会覆盖 Redis 中的 refresh token，旧设备下次刷新即失效。

    Args:
        req: 登录请求，含账号、密码、图形验证码 key 与用户输入的验证码。

    Returns:
        LoginResponse: 含 access token 与用户基础信息。

    Raises:
        BizError: 验证码错误(400) / 账号不存在(404) / 账号禁用(1004) / 密码错误(400)。
    """
```

### 提交规范

沿用 Go 项目的风格：`type(scope): 中文描述`

| type | 用途 |
|---|---|
| `feat` | 新功能 |
| `fix` | 修 bug |
| `docs` | 只改文档 |
| `refactor` | 重构，不改行为 |
| `test` | 只改测试 |
| `chore` | 构建、依赖、配置 |

示例：`docs(article): 补充文章列表筛选接口说明`

## 数据约定

- **新项目数据全部新建**，不使用 Go 版本的任何数据。
- 旧 PostgreSQL 库、旧 MinIO 桶**只读隔离**，新项目不建立任何连接。
- 数据库：MySQL 8.0，库名 `blog_v2`，字符集 `utf8mb4`（collation `utf8mb4_0900_ai_ci`）。
  > 本机 `blog-project` 库里还留着旧数据（33 篇文章 / 107 条评论 / 12 个用户），
  > 按「旧数据不碰」的约定原样隔离，新库另起名 `blog_v2`。
- MinIO：新桶名 `blog-v2`，与旧桶 `blog-project` 隔离。

## 接口契约约定

所有接口保持与 Go 版本一致，前端零改动（除后台删 2 个 tab）。

- 响应包裹：`{"code": 0, "message": "成功", "data": {...}}`
- `data` 为 `None` 时**不输出该字段**
- 时间格式：`2026-11-09T21:39:04Z`（本地时间 + 字面 Z，照抄 Go 的 bug）
- 分页字段：文章列表用 `page_size`，用户列表用 `pageSize`（历史原因，不要统一）

---

## 接口实现进度

| 模块 | 接口数 | 状态 | 提交 |
|---|---|---|---|
| 00 foundation | 1 | 完成 | `3f41bb0` |
| 01 auth | 10 | 完成 | `15d5a97` |
| 02 user | 12 | 完成 | `b37f30f` |
| 03 article | 12 | 完成 | `1878c0d` |
| 04 comment | 7 | 完成 | `58a953f` |
| 05 taxonomy | 12 | 完成 | `2354c1d` |
| 06 about | 2 | 完成 | `58a953f` |
| 07 llm | 7 | 完成 | `P6` |
| **合计** | **63** | **63 已实现** | |

### 校验契约是否漂移

```bash
python scripts/check_api_contract.py
```

从各模块 `api.md` 的表格里抽接口，与 FastAPI 实际注册的路由逐条比对。
完全一致时退出码 0，有差异时返回 1（可直接挂进 CI）。

它**只校路径与方法**，字段级契约靠 `tests/` 里的用例守着 ——
那些用例断言了 `staus` / `create_at` / `pageSize` / `git_hub` 这类历史拼写。
