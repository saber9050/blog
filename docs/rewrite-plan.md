# 博客项目重写方案：Go(Gin) → Python(FastAPI)

> 源项目：`F:\goland\blogProject`（Go + Gin + GORM + PostgreSQL + Redis + MinIO）
> 目标项目：`F:\Python_0\project\blog`（FastAPI）
> 定位：这是一次**同契约重写**，不是重做产品。前端（现有 Vue 3）原则上不改代码。

---

## 1. 目标与边界

### 1.1 一句话目标

用 FastAPI 复刻现有博客后端的全部业务能力，**砍掉 AI 助手整条链路**（向量化 / 切分 / 检索 / 会话），
只保留「对话模型」用于编辑器的一键摘要。对外接口路径、响应结构、字段名保持不变，前端只删三个后台 tab。

### 1.2 保留 / 删除清单

| 能力 | 现状 | 重写后 | 说明 |
|---|---|---|---|
| 注册 / 登录 / 邮箱登录 / 验证码 / 双 Token | 有 | **保留** | 逻辑与 Redis key 规则 1:1 复刻 |
| 用户资料 / 头像 / 改密 / 改邮箱 | 有 | **保留** | 头像走 MinIO |
| 文章 CRUD / 列表筛选 / 详情 / 浏览量 | 有 | **保留** | 含软删除 |
| 点赞 / 取消点赞 | 有 | **保留** | |
| 评论（两级）/ 删除 | 有 | **保留** | |
| 分类 / 标签 / 关于页 | 有 | **保留** | |
| 图片上传 | 有 | **保留** | MinIO |
| AI 模型配置管理 | 有（对话 + 向量两类） | **保留，仅对话类** | 新库精简表结构：去掉 `dimension` / `name` 列 |
| 一键生成摘要 | 有 | **保留** | 唯一保留的模型能力 |
| AI 助手对话（SSE 流式） | 有（约 2850 行） | **删除** | 含 hybrid_search / agent / tool 调用 / prompt |
| Markdown 切分（chunker） | 有（650 行 + 545 行测试） | **删除** | |
| 向量化（embedding + 异步 worker + 僵尸任务恢复） | 有（369 行） | **删除** | |
| 向量表维护 / 维度自检 | 有（245 行） | **删除** | |
| 后台「切分管理」「助手会话」 | 有 | **删除** | |
| 数据库 | PostgreSQL 17 + pgvector | **换成 MySQL 8.0** | 不再需要向量扩展；旧 PG 库保留但不迁数据 |

净删除约 **5000+ 行** Go 等价代码、**4 张表**、**20 条路由**。

### 1.3 明确不做的事

1. **不写数据迁移工具，不读旧库**。新库从零建，旧 PostgreSQL 库只读隔离，一个字节都不碰（见 6.4 ⑦）。
2. 表名/列名照抄旧结构（含 `categorys` 的拼写），只换底层数据库，不重新设计 ER。
3. 不改接口路径与响应字段 —— 避免前端联动改动。
4. 不引入 ORM 之外的抽象（不做 repository 泛型基类花活）。
5. 不在这轮做「多模型路由 / 失败重试 / 限流」，摘要失败就报错，够用。

---

## 2. 现状盘点（重写依据）

### 2.1 代码规模

| 层 | 文件数 | 说明 |
|---|---|---|
| Go 源文件 | 180 | service 层约 9900 行（含测试） |
| 接口 | 83 条路由 | 保留 63，删除 20 |
| 数据表 | 14 张 | 新库只建 10 张，4 张不建 |
| 前端页面 | 9 个 View | 改动很小：删 2 个 tab、去掉若干字段展示 |

### 2.2 新库要建的表（10 张）

| 表名 | 说明 | 备注 |
|---|---|---|
| `users` | 用户 | `role_id` 1=管理员 |
| `categorys` | 分类 | **表名就是 `categorys`**，Python 侧必须照抄，不要"顺手修正"成 `categories` |
| `tags` | 标签 | |
| `tag_articles` | 文章-标签关联 | 无物理外键 |
| `articles` | 文章 | **删掉 4 个向量化列**（`vector_status` / `vector_chunk_count` / `vector_error` / `vectorized_at`），`content` 用 `MEDIUMTEXT` |
| `article_images` | 正文图片引用 | 用于删除文章时清理 MinIO 对象 |
| `comments` | 评论 | 两级：`parent_id` 为空/0 即一级 |
| `likes` | 点赞 | 无唯一约束，靠代码先查后插 |
| `abouts` | 关于页 | 单行数据 |
| `ai_model_configs` | 模型配置 | 保留 `type`（恒 1），**不建 `dimension` / `name`** |

### 2.3 不建的表

`chat_sessions`、`chat_messages`、`chat_tool_messages`、`article_chunks`。

新 MySQL 库是全新的，这 4 张表**从建库脚本里就不存在**，不需要 DROP。

> **旧 PostgreSQL 库的处理**：上线后保留只读 30 天做回滚保险（`blog_pg_data` 卷 66 MB 不占地），
> 确认不需要回滚后再 `docker compose down` + 删卷。别在上线当天删。

---

## 3. 技术选型

| 关注点 | 选型 | 理由 |
|---|---|---|
| Web 框架 | FastAPI 0.115+ | 异步、OpenAPI 自动生成 |
| ASGI | uvicorn（standalone） | Windows 本地开发不能跑 gunicorn |
| 校验 / DTO | Pydantic v2 | 与 Go 的 binding tag 一一对应 |
| ORM | SQLAlchemy 2.0（async）+ `asyncmy` | SQLAlchemy 是 ORM 不是数据库，底下的库换成 MySQL |
| 数据库 | **MySQL 8.0**（`mysql:8.0`） | 用户指定；utf8mb4 / 0900_ai_ci |
| 迁移 | Alembic | 替代 GORM AutoMigrate，DDL 进版本库 |
| Redis | `redis.asyncio` 5.x | 验证码 / 刷新令牌 / 黑名单 |
| 对象存储 | `minio` 7.x | 与 Go 侧同名 SDK，行为一致 |
| JWT | PyJWT 2.x | HS256，claims 结构照抄 |
| 密码 | `bcrypt` 原生库 | **不要用 passlib**（1.7.4 与 bcrypt 4.x 有兼容坑） |
| HTTP 客户端 | httpx（async） | 调 OpenAI 兼容接口 |
| 图形验证码 | Pillow 手写 6 位数字 | 复刻 base64Captcha 的 `captcha_id + base_64` 契约 |
| 邮件 | `smtplib` + `email.message`（走线程池） | QQ 邮箱 587 端口 STARTTLS |
| 日志 | loguru（rotation/retention/compression） | 对应 zap 的 max_size/max_backups/max_age |
| 测试 | pytest + pytest-asyncio + httpx.AsyncClient | 对应 `go test -race` |
| 静态检查 | ruff + mypy | 对应 `go vet` + `gofmt` |
| Python | 3.13（本机 `.venv` 已就绪） | |

---

## 4. 目标工程结构

```
blog/
├── app/
│   ├── main.py                  # create_app() + lifespan
│   ├── core/
│   │   ├── config.py            # pydantic-settings，读 configs/config.yaml
│   │   ├── logging.py           # loguru 配置
│   │   ├── errors.py            # 错误码表 + BizError
│   │   ├── response.py          # ApiResponse / PageMeta / ok() / fail()
│   │   ├── security.py          # bcrypt + JWT 签发解析 + refresh 存储
│   │   └── deps.py              # get_db / get_redis / current_user / admin_required
│   ├── db/
│   │   ├── session.py           # async engine + sessionmaker
│   │   ├── base.py              # DeclarativeBase + 命名约定 + 时间戳 mixin
│   │   └── models/              # 一表一文件，10 个
│   ├── schemas/                 # Pydantic 请求/响应，按模块拆
│   ├── repositories/            # 纯 SQL，无业务判断
│   ├── services/                # 业务逻辑
│   ├── api/v1/
│   │   ├── auth.py  users.py  articles.py  comments.py
│   │   ├── categories.py  tags.py  about.py  health.py
│   │   └── admin/
│   │       ├── users.py  articles.py  comments.py
│   │       ├── categories.py  tags.py  llm_configs.py
│   ├── integrations/
│   │   ├── llm.py               # OpenAI 兼容 /chat/completions（唯一模型入口）
│   │   ├── minio_client.py
│   │   ├── mailer.py
│   │   └── captcha.py
│   └── utils/
├── alembic/
│   ├── env.py                   # async engine
│   └── versions/
├── tests/
│   ├── conftest.py
│   ├── test_auth.py  test_articles.py  ...
│   └── integration/             # 接真 PG
├── docs/rewrite-plan.md         # 本文件
├── pyproject.toml
├── configs/config.yaml.example
├── Dockerfile
└── docker-compose.yml
```

分层规则（对应 Go 的 `api → service → repository`）：

1. `api/` 只做参数绑定、鉴权依赖、调 service、包响应，**不写 SQL、不写业务分支**。
2. `services/` 管事务边界与业务规则，抛 `BizError`。
3. `repositories/` 只接收参数返回模型/元组，**不 commit**，事务由 service 或依赖注入统一控制。

---

## 5. 接口契约

### 5.1 统一响应结构（必须 1:1）

```json
{ "code": 0, "message": "成功", "data": { } }
```

- `code=0` 成功，4xx/5xx 与 HTTP 状态码一致，1xxx-3xxx 业务码统一映射 HTTP 400。
- `data` 为空时**不输出该字段**（对应 Go 的 `omitempty`）→ FastAPI 用
  `JSONResponse(content=model.model_dump(exclude_none=True))`。
- 错误码常量表照抄 `pkg/errors`：

```python
class Code:
    SUCCESS = 0
    BAD_REQUEST, UNAUTHORIZED, FORBIDDEN, NOT_FOUND = 400, 401, 403, 404
    CONFLICT, TOO_MANY_REQUESTS = 409, 429
    INTERNAL_ERROR, SERVICE_UNAVAILABLE = 500, 503
    USER_NOT_FOUND, USER_ALREADY_EXISTS, INVALID_CREDENTIALS = 1001, 1002, 1003
    USER_DISABLED, INVALID_TOKEN, TOKEN_EXPIRED = 1004, 1005, 1006
    WRONG_PASSWORD, TOKEN_NOT_EXPIRED, LOGIN_LIMIT = 1007, 1008, 1009
    INVALID_PARAM, MISSING_PARAM, PARAM_FORMAT = 2001, 2002, 2003
    RESOURCE_NOT_FOUND, RESOURCE_EXISTS, RESOURCE_LOCKED = 3001, 3002, 3003
```

### 5.2 路由清单（保留 63 条）

**认证 `/api/v1/auth`** — 全部免登录

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/register` | 注册 |
| POST | `/login` | 账号密码 + 图形验证码 |
| POST | `/email_login` | 邮箱验证码登录 |
| GET | `/image_captcha` | 返回 `{captcha_id, base_64}` |
| POST | `/captcha` | 发邮箱验证码 |
| POST | `/reset_password` | 重设密码 |
| POST | `/logout` | |
| POST | `/refresh` | 用过期 access token 的 claims 换新 token |
| GET | `/is_exists_name` | |
| GET | `/is_exists_account` | |

**用户 `/api/v1/user`** — 需登录

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/info` | |
| POST | `/profile` | |
| POST | `/avatar` | multipart |
| POST | `/password` | |
| POST | `/email_ack` | 改邮箱申请（发确认邮件） |
| POST | `/add_email` | |
| GET | `/is_exists_email` | |
| GET | `/email` | 邮箱确认链接，token 鉴权，免登录 |

**文章 `/api/v1/articles`**

| 方法 | 路径 | 鉴权 |
|---|---|---|
| GET | `/api/v1/articles` | 可选登录（带 token 才有 `is_liked`） |
| GET | `/random` | 无 |
| GET | `/stats` | 无 |
| GET | `/{id}` | 可选登录，**每次 +1 浏览量** |
| POST | `/{id}/like` | 需登录 |
| DELETE | `/{id}/like` | 需登录 |

**评论 `/api/v1/articles`**

| 方法 | 路径 | 鉴权 |
|---|---|---|
| GET | `/{id}/comments` | 无 |
| GET | `/{id}/comments/{comment_id}/replies` | 无 |
| POST | `/{id}/comments` | 需登录 |
| DELETE | `/{id}/comments/{comment_id}` | 需登录 |

**分类 / 标签 / 关于** — `/api/v1/categories`（列表、count）、`/api/v1/tags`（列表、count）、
`GET /api/v1/about`、`PUT /api/v1/about`（管理员）。

**后台 `/api/v1/admin`** — 全部 `role_id=1`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST/PUT/DELETE | `/users`、`/users/{id}` | 用户管理 |
| GET/POST | `/articles` | 列表（**不再返回 `vector_*` 字段**）、新建 |
| POST | `/articles/generate-summary` | **唯一的 AI 能力** |
| PUT | `/articles/transfer` | 批量转分类 |
| PUT/DELETE | `/articles/{id}` | |
| POST | `/upload` | 图片上传（注意不在 `/articles` 下） |
| GET/DELETE | `/comments`、`/comments/{id}` | 删除支持批量 |
| GET/POST/PUT/DELETE | `/categories`、`/tags` | |
| GET/POST | `/llm-configs` | 列表、新建 |
| GET/PUT/DELETE | `/llm-configs/{id}` | |
| POST | `/llm-configs/test` | 测试连接，不落库 |

**健康检查** `GET /api/v1/health` → `{"status":"ok","message":"..."}`（注意这不是统一响应结构）。

> **后台文章列表的响应瘦身**：`AdminArticleItem` 去掉 `vector_status` / `vector_chunk_count` /
> `vector_error` / `vectorized_at` 四个字段。前端 AdminView 的文章表格里对应的 4 列要一起删，
> 否则 Vue 会渲染成空白列。这是 P4 唯一需要动表格结构的地方。

### 5.3 分页字段的坑

Go 侧有两套分页结构，**不要统一**：

- `response.PageResponse` → `pageSize`
- `ArticleListResponse` / `AdminArticleListResponse` → `page_size`

前端按各自接口写死了，重写时必须逐个对齐。建议在 `schemas/common.py` 里定义
`PageMeta`（`page_size`）和 `AdminPageMeta`（同 `page_size`），另注明 `PageResponse` 仅用于用户列表。

### 5.4 时间字段的坑

Go 侧 `CreatedAt: article.CreatedAt.Format("2006-01-02T15:04:05Z")` ——
这是**本地时间硬贴了一个 `Z` 后缀**，并不是 UTC 转换。前端已按此格式解析。

Python 侧 1:1 复刻：

```python
def fmt_time(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else ""
```

修不修是另一件事（真改成 UTC 要同步改前端解析），这轮不动。

---

## 6. 数据层设计

### 6.1 ORM 映射要点（MySQL 8）

```python
class Base(DeclarativeBase):
    pass

class TimestampMixin:
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, index=True, nullable=True)
```

映射关系（与 GORM 时期的差别：**没有 timezone、没有 vector**，但多了 `MEDIUMTEXT` 的需求）：

| Go / GORM | MySQL 列 | SQLAlchemy |
|---|---|---|
| `uint` 主键 | `BIGINT AUTO_INCREMENT` | `BigInteger` + `autoincrement=True` |
| `int8` | `SMALLINT` | `SmallInteger` |
| `string` 无 tag | `TEXT` | `Text` |
| `string` + `type:varchar(n)` | `VARCHAR(n)` | `String(n)` |
| `time.Time` | `DATETIME`（无时区） | `DateTime`（**不要写 `timezone=True`**） |
| `gorm.DeletedAt` | `DATETIME NULL` + 索引 | `SoftDeleteMixin` |
| `default:0` | `NOT NULL DEFAULT 0` | `server_default="0"` |

#### MySQL 特有的四个坑

**① 文章正文别用 `TEXT`**

MySQL 的 `TEXT` 上限 64 KB，按 utf8mb4 算大概 2 万汉字。技术长文很容易超，**超了不报错，直接截断**。

```python
from sqlalchemy.dialects.mysql import MEDIUMTEXT

# with_variant：以后若再换库（比如回 PG），自动退化成普通 Text，不用改代码
content: Mapped[str] = mapped_column(Text().with_variant(MEDIUMTEXT, "mysql"))
```

`MEDIUMTEXT` 上限 16 MB，够用。别用 `LONGTEXT`（4 GB），那是浪费。

**② 状态字段的 `TINYINT(1)` 会被当成布尔**

MySQL 驱动见到 `TINYINT(1)` 会往 `bool` 上映射。Go 侧的 `status int8` 存的是 0/1，
语义上是整数不是布尔，**显式写 `SmallInteger`**，别让它变成 `True/False` 进 JSON。

**③ 时区：`DATETIME` 不存时区，靠连接参数**

```python
engine = create_async_engine(
    f"mysql+asyncmy://{user}:{pwd}@{host}:{port}/{db}?charset=utf8mb4",
    connect_args={"init_command": "SET time_zone='+08:00'"},
    pool_size=10, max_overflow=20, pool_recycle=3600,
)
```

`pool_recycle=3600` 必写：MySQL 默认 `wait_timeout` 是 8 小时，连接池里的死连接会让请求偶发报
「MySQL server has gone away」。这是 MySQL 比 PG 多出来的坑。

**④ 大小写敏感度反过来了**

MySQL 的 `utf8mb4_0900_ai_ci` 排序规则**不区分大小写**，所以：

- `LIKE '%go%'` 能命中 `Go`，不用像 PG 那样写 `ILIKE`（反而回到了 2026-10-27 之前的行为）。
- 但唯一索引也变成不区分大小写：`Admin` 和 `admin` 算重名，注册时会撞 1002「该昵称已经存在」。

这是**行为变化**，不是 bug，但要在 P1 的测试用例里加一条断言，别上线后被用户投诉。

**软删除必须显式过滤**。GORM 是自动加条件的，SQLAlchemy 不会 —— 漏一处就会让已删文章/评论"复活"。
建议在 `repositories/base.py` 提供 `not_deleted(stmt)` 小工具，并写一条单测断言
「删除后列表查不到」。

### 6.2 Alembic 策略（全新库）

不再有"接管旧库"这回事，只有一条路径：

```bash
# P0 阶段：手写模型 → 自动生成首个 migration → 人工 review → 执行
alembic revision --autogenerate -m "init schema"
alembic upgrade head          # 建 10 张表 + 索引

# 之后每次改模型
alembic revision --autogenerate -m "add xxx"
alembic upgrade head

# 验收入口：模型与库结构必须零差异
alembic check
```

**MySQL 的 DDL 不支持事务回滚**。PostgreSQL 里 migration 跑一半失败可以整体回滚，
MySQL 会隐式提交，跑到第 3 句挂了，前 2 句已经生效。

对策：
1. 每个 migration 只做一件事（别一个文件里改 5 张表）。
2. 建表语句带 `IF NOT EXISTS`，加列前先判断列是否存在，让 migration 可重复执行。
3. 上线前在本地库上完整跑一遍 `upgrade head` → `downgrade base` → 再 `upgrade head`。

### 6.3 事务

- 依赖注入给每个请求一个 `AsyncSession`，`service` 层用 `async with session.begin()` 包住写操作。
- **显式把隔离级别降到 READ COMMITTED**：MySQL 默认是 REPEATABLE READ，
  和旧 PG 版（默认 RC）行为不一致，长事务下会出现"读不到刚提交的数据"的错觉。
  `create_async_engine(..., isolation_level="READ COMMITTED")`
- MinIO 上传与 DB 写入**不能同事务**：先传文件拿 key，再写库；写库失败要补偿删文件
  （对应 Go 侧 `syncArticleImages` 的清理逻辑）。
- **不要用 `INSERT ... RETURNING`**：MySQL 不支持，SQLAlchemy 在 MySQL 方言下会直接报错。
  要拿自增主键用 `result.lastrowid` 或 SQLAlchemy 自动填充的 `obj.id`。

### 6.4 数据到底存在哪

分两层看，别混：

**① 表结构定义 —— 存在代码仓库里，跟着 Git 走**

| 内容 | 位置 | 说明 |
|---|---|---|
| 表结构唯一真相 | `app/db/models/*.py` | SQLAlchemy 模型，写错这里就是写错表 |
| 变更历史 | `alembic/versions/*.py` | 每个文件一个版本，按 `down_revision` 串成链 |
| 实际建表动作 | `alembic upgrade head` | 替代 GORM AutoMigrate，DDL 可 review |

没有建表 SQL 文件 —— 结构只存在这两处，靠 `alembic check` 保证同步。

**② 实际数据 —— 存在阿里云 ECS 的 Docker 卷里**

| 数据 | 容器 | 宿主机路径 | 说明 |
|---|---|---|---|
| 新库业务表（10 张） | `blog-mysql` | `/var/lib/docker/volumes/blog_v2_mysql_data` | **新建卷名，见下方坑** |
| 上传的图片 | `blog-minio` | `/var/lib/docker/volumes/blog_minio_data` | **复用现有卷**，11 MB |
| 验证码 / refresh token | `blog-redis` | `/var/lib/docker/volumes/blog_redis_data` | 40 KB，可丢 |
| 应用日志 | — | 容器内 `/app/logs`，**未挂宿主机** | 容器重建即丢 |
| 旧 PG 库（只读保留 30 天） | `blog-postgres` | `/var/lib/docker/volumes/blog_pg_data` | 66 MB，回滚保险 |
| 更早的 MySQL 旧库 | — | `/var/lib/docker/volumes/blog_mysql_data` | 189 MB，2026-10-27 前的，可删 |

**③ 卷名撞车坑（这条比 PG 版更危险）**

服务器上已经躺着一只 `blog_mysql_data` —— 那是 **2026-10-27 迁移到 PG 之前的老 MySQL 库**，
189 MB，里面是旧表结构和旧数据（连 chat 表都可能有）。

新项目如果按直觉把卷叫 `mysql_data`，compose 会拼成 `blog_mysql_data`，
**直接挂到那只 189 MB 的旧库上**。启动时 Alembic 一看表都在（但结构对不上），
`alembic check` 报一堆差异，或者更糟：`upgrade head` 在旧表上硬改，把旧库搅烂。

规避：**卷名必须换一个全新的**。

```yaml
name: blog-v2          # 换个项目名，容器名/网络名跟旧栈彻底分开，回滚时互不干扰

services:
  mysql:
    image: mysql:8.0
    volumes:
      - mysql_data:/var/lib/mysql
    command: >
      --character-set-server=utf8mb4
      --collation-server=utf8mb4_0900_ai_ci
      --default-time-zone=+08:00
    environment:
      MYSQL_ROOT_PASSWORD: "${MYSQL_ROOT_PASSWORD:?请设置}"
      MYSQL_DATABASE: "${MYSQL_DATABASE:-blog-project}"

volumes:
  mysql_data:
    name: blog_v2_mysql_data    # ← 显式实名，绝不能沿用 blog_mysql_data
```

> **别加 `--lower-case-table-names`**：Linux 下 MySQL 8 默认就是 0（表名区分大小写），
> 表名全小写正合适。而且这个参数**只能在数据目录初始化时设定**，
> 数据目录已存在时传不同的值，MySQL 会直接拒绝启动。网上很多 compose 模板抄了这个坑。

上线前先确认：

```bash
docker volume ls | grep -i blog          # 确认没有同名卷
docker volume inspect blog_v2_mysql_data # 确认 Mountpoint 是新的空目录
```

**④ 旧 PG 库怎么处理**

不迁数据 ≠ 马上删。上线后 `blog-postgres` 容器**继续跑着，但前端不再指向它**，
保留 30 天做回滚保险（66 MB 不占地）。确认不需要回滚后再：

```bash
docker compose -f docker-compose.prod.yml stop blog-postgres
# 再观察一周，然后 rm 容器 + 删卷
```

**⑤ 本地开发**

```bash
# docker-compose.dev.yml 只起两个服务
#   mysql:8.0  → 127.0.0.1:3306
#   redis:7    → 127.0.0.1:6379

alembic upgrade head          # 建表
python -m app.scripts.seed    # 塞测试数据（3 个分类、5 篇文章、1 个管理员）
```

数据落在 Docker Desktop 虚拟磁盘，或 bind mount 到 `F:\Python_0\data\blog-mysql`（推荐，方便删库重来）。

**⑥ 备份必须补（当前是零备份）**

实测：`crontab -l` 为空，`/opt/blog/backup` 里只有一个 2026-10-27 的 MySQL dump（250 KB）。
**生产库一次没备过。**

换 MySQL 后：

```bash
# 手工全量备份
docker exec blog-mysql mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" \
  --single-transaction --routines --triggers --default-character-set=utf8mb4 \
  blog-project | gzip > /opt/blog/backup/blog-mysql-$(date +%Y%m%d-%H%M).sql.gz

# 图片也要备（MinIO 数据不在库里）
tar czf /opt/blog/backup/blog-minio-$(date +%Y%m%d).tar.gz \
  -C /var/lib/docker/volumes/blog_minio_data/_data .
```

`--single-transaction` 必写：InnoDB 下能做到一致性快照且不锁表。漏了就是锁表备份，站点卡死。

每日 3 点跑一次、保留 7 天、同步到 OSS —— 备份和源数据放同一块云盘，等于没备份。

**⑦ 旧数据：一个字节都不碰（2026-11-09 21:39 定稿）**

用户明确要求：**新项目数据全部新建，不使用任何旧数据，也不改动 Go 版本的数据**。

执行口径，写死不许变：

| 对象 | 处置 |
|---|---|
| 旧 PostgreSQL 库（`blog_pg_data`，66 MB） | **只读隔离**。新项目不建连接、不读、不写、不导出 |
| 旧 MinIO 桶（`blog_minio_data`，11 MB） | 新项目用**新桶** `blog-v2`，与旧桶完全隔离 |
| Go 项目目录 `F:\goland\blogProject` | 不修改任何文件（包括 README、配置、代码） |
| 旧 MySQL 遗留卷（189 MB） | 不动 |

所以本方案**没有数据迁移章节**，也不需要写迁移脚本。6.5 已取消。

**后果要说清楚**：上线那天博客是空的 —— 0 篇文章、0 条评论、1 个默认管理员。
19 篇旧文章留在旧库里，作为 Go 版本的存档。要重新上架得手工写。

**回滚保险**：Go 版本的服务和旧库在服务器上原样保留，新项目另起容器组（`name: blog-v2`）。
出问题就是改 Nginx 反代目标切回去，旧数据完整无缺。观察 30 天后再考虑清理。

---

## 7. AI 模块（唯一保留的模型能力）

### 7.1 能力边界

只有一条链路：**编辑器点「生成摘要」→ 后端调一次 `/chat/completions` → 返回文本**。

不做：流式、多轮、检索、工具调用、embedding。

### 7.2 数据模型简化

新库是全新的，可以顺手把只为向量服务的列去掉：

| 列 | 旧结构 | 新结构 | 原因 |
|---|---|---|---|
| `type` | `int8`，1=对话 2=向量 | `SMALLINT NOT NULL DEFAULT 1` | **保留**，前端按这个字段判断，保留就不用改前端 |
| `dimension` | `int`，向量维度 | **不建** | 只有 embedding 用，删掉向量功能后没有任何用途 |
| `name` | `varchar(64)`，历史遗留 | **不建** | Go 注释自己都写了"仅为满足历史 not null 约束" |

- 新建配置时服务端强制 `type=1`（前端不再显示类型选择）。
- `Resolve(config_id)` 校验：存在 → `status=1` → `type=1`，任一不满足抛对应错误。
- `api_key` 列加 `varchar(512)` 够用（主流厂商密钥都在 100 字符内），索引长度 3072 字节的限制碰不到。

### 7.3 客户端实现

```python
# app/integrations/llm.py
@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: str
    model: str
    timeout_sec: int = 30
    max_tokens: int = 2048
    temperature: float = 0.3

class LLMClient:
    """OpenAI 兼容协议，只实现 chat。按配置指纹复用连接。"""
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._fingerprint: str = ""

    async def chat(self, cfg: LLMConfig, messages: list[dict]) -> str:
        ...
```

错误处理照抄 Go 侧：**不透传供应商原始响应体**，只提取 `error.message` 拼进提示。

### 7.4 摘要服务

```python
PROMPT = """请为以下文章生成一段简洁的摘要，要求：
- 不超过100字
- 概括文章核心内容
- 语言简洁通顺
- 不要出现"本文"、"文章"等开头
- 不要出现任何表情符号
- 只输出一段话的文本
- 不要有任何形式的分段和分条回答
- 生成完摘要后审查是否超过了150词，如果超过重新按照要求生成

文章标题：
{title}

文章内容：
{content}

摘要："""
```

处理流程与截断规则必须一致：

1. Markdown/HTML → 纯文本（写一个 `strip_markup()`：去 `#`、`**`、`` ` ``、链接、HTML 标签，压空白）。
2. 超 8000 字符截断（按 rune/字符，不切半个汉字）。
3. 调模型 → `strip()` → 去掉首尾的 ASCII 双引号 `"`、ASCII 单引号 `'`、中文直角引号 `「」` → 再 `strip()`。
   （Go 原文是 ``strings.Trim(summary, `"'「」""''`)``，字符集照抄即可，别漏了直角引号）
4. 超 255 字符截断（`summary` 列是 `varchar(255)`，不截会直接写库报错）。

### 7.5 后台「AI 模型」页要动的两处

1. 新建/编辑表单删掉「模型类型」下拉，固定对话模型。
2. 删掉「向量维度」输入框。

前端改这一处比后端删代码还麻烦，别忘排进计划。

---

## 8. 关键实现细节（容易翻车的地方）

| # | 事项 | 说明 |
|---|---|---|
| 1 | bcrypt 用法 | 新库没有存量用户，密码全部新建。仍用 `bcrypt` 原生库（cost=12），**不要用 passlib**（1.7.4 与 bcrypt 4.x 有兼容坑）。若日后搬旧用户，`$2a$10$` 的哈希可直接 `checkpw` 校验，不用重算 |
| 2 | `categorys` 表名 | 照抄错误拼写，改了就查不到表 |
| 3 | 双 Token 语义 | refresh 是随机串存 `refresh:{user_id}`（单设备）；access token 的 `tid` claim 存该串；刷新时比对并轮换；登出仅当 `tid` 仍等于当前存储值才删 key |
| 4 | 图形验证码 | 6 位数字、240×80、`captcha:login:{id}` 存 300 秒；响应字段是 `captcha_id` / `base_64`（下划线） |
| 5 | 邮箱验证码限流 | Redis `SETNX captcha:limit:{email}` 60 秒；key 格式别改，否则发信频率失控 |
| 6 | 浏览量自增 | 详情接口每次 `UPDATE articles SET views = views + 1`，异步执行失败不影响返回 |
| 7 | 文章列表 N+1 | Go 侧每篇文章查 6 次（作者/分类/标签/点赞/点赞数/评论数）。Python 用 `selectinload` + 子查询聚合，**一次 4 条 SQL 之内**解决，这是重写唯一明确要做的性能优化 |
| 8 | liked 判断 | `likes` 表无唯一索引，靠「先查后插」，高并发会重复。保持现状（不引入新约束），但插入前查一次不可省 |
| 9 | MinIO 对象名 | 复用 `NormalizeObjectName` / `ParseFileKey` 的规则，别自己拼 URL，否则老文章的图片链接全 404 |
| 10 | CORS | Go 侧是 `allow_origins=["*"]`；FastAPI 的 `CORSMiddleware` 在 `allow_credentials=True` 时不允许 `*`。用 `allow_origins=["*"], allow_credentials=False` |
| 11 | 请求超时 | Go 设置读写 300s；uvicorn 默认无超时，但反向代理（Nginx）默认 60s，摘要接口要单独调 `proxy_read_timeout` |
| 12 | lifespan 初始化 | 默认管理员创建、配置校验放在 `lifespan`，**失败要能启动**（对应 Go 里「向量初始化失败不阻断启动」的思路） |
| 13 | 配置来源 | 只保留 `configs/config.yaml` + `pydantic-settings`，**不再保留 `.env`**。Go 项目同时维护两份配置，README 里专门警告过「两边密码必须一致」，这次直接消灭双重来源 |
| 14 | 时区 | MySQL 的 `DATETIME` 不带时区，必须靠连接参数：`init_command="SET time_zone='+08:00'"` + compose 里 `--default-time-zone=+08:00`。漏一处，时间就差 8 小时 |
| 15 | 连接回收 | `pool_recycle=3600` 必写。MySQL 默认 `wait_timeout=8h`，池里死连接会导致偶发「MySQL server has gone away」，PG 没这个问题 |
| 16 | 正文列类型 | 文章 `content` 用 `MEDIUMTEXT`（16 MB），不要用 `TEXT`（64 KB）。中文长文超限**静默截断**，不报错 |

---

## 9. 配置与部署

### 9.1 配置文件 `configs/config.yaml`

**单一配置源，YAML 分组结构**，与 Go 版 `config.yaml` 一致：

```yaml
app:
  name: "blog-project"
  mode: "debug"            # debug 开放 /docs；release 关闭
  host: "127.0.0.1"
  port: 8000

database:
  mysql:
    host: "127.0.0.1"
    port: 3306
    user: "root"
    password: ""           # 容器部署时留空，用环境变量注入
    database: "blog-project"
    pool_size: 10
    max_overflow: 20
    echo: false
  redis:
    enabled: false         # false 时降级为进程内缓存（仅单 worker）
    host: "127.0.0.1"
    port: 6379
    password: ""
    db: 0

jwt:
  secret: ""
  access_expire_minutes: 15
  refresh_expire_hours: 72

security:
  fernet_key: ""           # 模型 api_key 的加密密钥
  # 生成：python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

minio:
  endpoint: "127.0.0.1:9000"
  access_key: "admin"
  secret_key: ""
  bucket: "blog-v2"
  use_ssl: false
  public_url: "http://127.0.0.1:9000"   # 必须是纯源，不要带路径前缀

smtp:
  host: "smtp.qq.com"
  port: 587
  username: ""
  password: ""

admin:
  enabled: true
  account: "00000000000"
  password: "admin123456"

log:
  level: "INFO"
  dir: "logs"
  rotation: "50 MB"
  retention: "7 days"

business:
  image_max_bytes: 10485760
  allowed_image_exts: [".jpg", ".jpeg", ".png", ".webp"]
  captcha_length: 6
  captcha_expire_seconds: 300
  captcha_send_limit_seconds: 60
  max_page_size: 100
```

**优先级**：环境变量 > YAML > 代码默认值。

容器部署时敏感项用双下划线环境变量注入，避免写进镜像层：

```yaml
environment:
  DATABASE__MYSQL__PASSWORD: "${MYSQL_PASSWORD}"
  JWT__SECRET: "${JWT_SECRET}"
  SECURITY__FERNET_KEY: "${FERNET_KEY}"
```

`configs/config.yaml` 不入库，只提交 `configs/config.yaml.example`。

> **不再保留 `.env`**。Go 版同时维护 `config.yaml` 和 `.env`，README 里专门写过
> 「两边密码必须一致」——那不是配置系统，是两个人肉维护的副本。重写只留一份。

> 大模型仍然**不进配置文件**，登录后台维护，与现状一致。


### 9.2 Dockerfile

`asyncmy` 是 C 扩展，`pip install` 需要编译工具链，所以构建阶段要带 `gcc`：

```dockerfile
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 TZ=Asia/Shanghai
WORKDIR /app

# asyncmy 编译依赖（分两段装，最终镜像里不留编译工具）
RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

RUN apt-get purge -y gcc && apt-get autoremove -y

COPY . .
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2"]
```

> `--workers` 别超过核数。这台 ECS 是 2 核 4G，还跑着 Langfuse，`workers 2` 就够，
> 每多一个 worker 就多一份连接池（2 × 30 = 60 连接，MySQL `max_connections` 默认 151，留意别撑爆）。

### 9.3 compose 变化

| 项 | 现在 | 重写后 |
|---|---|---|
| 数据库镜像 | `pgvector/pgvector:pg17` | `mysql:8.0` |
| 数据库端口 | `127.0.0.1:5432` | `127.0.0.1:3306`（**别和现有 3306 直暴冲突**） |
| 数据卷 | `blog_pg_data` | `blog_v2_mysql_data`（新名字，见 6.4 ③） |
| backend | Go 二进制，端口 9527 | python 镜像，端口 8000 |
| 健康检查 | postgres `pg_isready` | mysql `mysqladmin ping` |
| alembic | 无 | 容器启动前执行 |

```yaml
services:
  mysql:
    image: mysql:8.0
    command: >
      --character-set-server=utf8mb4
      --collation-server=utf8mb4_0900_ai_ci
      --default-time-zone=+08:00
      --max-connections=200
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "127.0.0.1", "-p$$MYSQL_ROOT_PASSWORD"]
      interval: 10s
      timeout: 5s
      retries: 10
      start_period: 30s          # MySQL 首次初始化慢，不给 30s 会误判失败

  backend:
    depends_on:
      mysql:
        condition: service_healthy
      redis:
        condition: service_started
```

> `start_period` 必须写。MySQL 第一次启动要初始化数据目录，20-30 秒很正常，
> 没这个参数会被 Docker 判成 unhealthy 然后反复重启，表还没建完容器就死了。

前端 Nginx 的 `/api` 反代目标从 `blog-backend:9527` 改成 `blog-backend:8000`。

### 9.4 CI 调整

```yaml
- run: ruff format --check .
- run: ruff check .
- run: mypy app
- run: pytest -q
- run: python -c "from app.main import app"   # 导入冒烟，替代 go build
```

集成测试的 service 容器从 postgres 换 mysql：

```yaml
services:
  mysql:
    image: mysql:8.0
    env:
      MYSQL_ROOT_PASSWORD: test
      MYSQL_DATABASE: blog_test
    options: >-
      --health-cmd="mysqladmin ping -h 127.0.0.1 -ptest"
      --health-interval=10s --health-timeout=5s --health-retries=10
```

---

## 10. 分阶段实施计划

| 阶段 | 内容 | 产出 | 验收 | 预估 |
|---|---|---|---|---|
| **P0 骨架 + MySQL** | 目录结构、config、loguru、错误码、统一响应、health；起 mysql:8.0；10 张表模型 + 首个 Alembic migration | 能启动的空壳 + 建好的空库 | `alembic check` 零 diff；`upgrade head → downgrade base → upgrade head` 三连通过 | 2 天 |
| **P1 认证** | 注册/登录/邮箱登录/验证码/双 Token/刷新/登出 | `/auth/*` 全部 10 条 | 注册→登录→刷新→登出全流程跑通；大小写重名能被拦住 | 2.5 天 |
| **P2 内容** | 文章 CRUD/列表筛选/详情/点赞；分类/标签/评论/关于；MinIO 上传 | 前台 + 后台内容接口 | 分页字段、时间格式、软删除、长正文不截断四项验证 | 4 天 |
| **P3 AI 摘要 + 后台** | 模型配置 CRUD + 测试连接 + 摘要生成 | `/admin/llm-configs/*`、`/articles/generate-summary` | 真实模型生成摘要；超长正文/空正文/禁用配置三类异常正确 | 1.5 天 |
| **P4 前端适配** | 删 2 个 tab、AI 模型页去掉类型/维度、Nginx 反代改端口 | 前端可跑通全流程 | 后台 6 个 tab 全部可操作 | 1 天 |
| **P5 切流上线** | 部署脚本、回滚预案、备份机制、空站验收 | 上线 | 功能回归用例全绿；空库能正常跑通全流程 | 2.5 天 |

合计约 **13.5 人日**，留缓冲按 **15 人日** 排。

比 PostgreSQL 版多的 3.5 天，全花在三个地方：
① 换库带来的类型/时区/大小写调试（P0、P2）；
② 数据搬运脚本（P5，可选）；
③ MySQL 的坑比 PG 多（`pool_recycle`、`TEXT` 截断、`tinyint(1)`、DDL 无事务）。

### 10.1 P5 的验收方式变了

因为数据库整个换了、旧数据不迁，**没法再做"新旧接口逐字段 diff"**（新库是空的，数据不一样）。
改成两条：

**① 功能回归用例**（覆盖 63 条接口的主路径）

```python
# tests/integration/test_regression.py
# 用 seed 脚本造一套固定数据，跑完整业务流程
# 注册 → 登录 → 建分类 → 建文章 → 传图 → 点赞 → 评论 → 后台改 → 删
```

**② 数据量核对**（如果做了搬运）

```sql
-- 源（PG）与目标（MySQL）对比，数量必须一致
SELECT count(*) FROM articles WHERE deleted_at IS NULL;
SELECT count(*) FROM comments;
SELECT count(*) FROM tag_articles;
-- 随机抽 5 篇比对 title + char_length(content)
```

---

## 11. 风险清单

| 风险 | 影响 | 应对 |
|---|---|---|
| 新卷名撞上旧的 `blog_mysql_data`（189 MB 老库） | Alembic 在旧表上硬改，旧库被搅烂 | 卷名写死 `blog_v2_mysql_data`；启动前 `docker volume inspect` 确认 Mountpoint 是空的 |
| 中文长文超 `TEXT` 64 KB | **静默截断**，正文丢一半且不报错 | `content` 用 `MEDIUMTEXT`；P2 用 3 万字的测试文章跑一遍，比对 `char_length` |
| `TINYINT(1)` 被驱动当布尔 | `status: 0/1` 变成 `false/true`，前端判断全错 | 显式 `SmallInteger`；接口测试断言 JSON 里是数字 |
| 时区没设对 | 文章时间差 8 小时，评论排序乱 | `init_command` + compose `--default-time-zone` 两处都设；P2 断言 created_at 具体值 |
| 连接池空转被 MySQL 掐断 | 偶发 `MySQL server has gone away`，难复现 | `pool_recycle=3600`；压测跑 1 小时以上 |
| MySQL DDL 隐式提交 | migration 失败无法回滚，库处于半成品状态 | 一文件一变更；上线前本地跑 `upgrade → downgrade → upgrade` 三连 |
| 大小写重名 | `Admin` / `admin` 撞唯一索引，注册报 1002 | 不是 bug 是行为变化，写进测试用例并提前告知 |
| 软删除漏过滤 | 已删内容重新出现，属数据事故 | repository 层统一封装 `not_deleted()` + 专门单测 |
| 异步 ORM 在同步上下文误用（`asyncio.run` 嵌套） | 随机 500 | 全局禁用 `asyncio.run`，后台任务走 `BackgroundTasks` |
| MinIO 对象名规则没对齐 | 老图片链接全挂 | 复用 Go 侧 `ParseFileKey` 规则，单测覆盖 `http://host:9000/bucket/a/b.jpg` |
| 前端 Nginx 反代端口没改 | 全站 502 | P4 单独验收，写进部署 checklist |
| 摘要接口拖慢整体 | 编辑器卡死 | 单独超时 30s，`httpx` 设置 connect/read 分离超时 |
| 旧 PG 容器删早了 | 无法回滚 | 只停不删，观察 30 天 |

---

## 12. 已定 / 待定

### 12.1 已定（2026-11-09）

| 项 | 决定 | 影响 |
|---|---|---|
| 数据库 | **MySQL 8.0，空库重建** | 全文第 6 章按 MySQL 重写；排期 15 人日 |
| 旧数据 | **完全不用、不动** | 上线是空站；旧库旧桶原样封存做回滚保险 |
| ORM | SQLAlchemy 2.0 async + asyncmy | 换库只改连接串与方言细节，分层代码不动 |
| 开发范式 | **面向对象 + 详细注释** | 每个模块用 `Service` / `Repository` 类，不用模块级散函数 |
| 接口契约 | 不变 | 前端只删 2 个 tab、去 2 个表单字段 |
| 交付节奏 | 分模块出文档 → 审核 → 开发，每阶段 `git commit` | 见 `docs/README.md` 的模块索引 |

### 12.2 还差一个决定

**前端动不动**：默认「复用现有 Vue，只删 tab + 去表单字段」。
想借这次重写前端（换 React / 重构 AdminView），工作量另算。

---

## 附录 A：删除清单（对照用）

删除目录/文件（Go）：

```
internal/api/v1/chat/             internal/api/v1/admin/chat/
internal/api/v1/admin/chunk/      internal/api/v1/admin/vector/
internal/repository/chat/         internal/repository/articlechunk/
internal/service/chat/            internal/service/chunk/
internal/service/chunker/         internal/service/vectorize/
internal/service/vectorschema/
internal/model/entity/chat_*.go   internal/model/entity/article_chunk.go
internal/model/dto/*/chat.go      internal/model/dto/*/chunk.go
internal/model/dto/*/vector*.go
pkg/llmclient/embeddings.go
```

删除接口 20 条，按路由族分布：

| 路由族 | 条目数 | 明细 |
|---|---|---|
| `/api/v1/articles/{article_id}/chat/context` + `/api/v1/chat/*` | 8 | 上下文、建会话、消息列表、发消息、工具记录、改会话、删会话、文章候选 |
| `/api/v1/admin/chat-sessions/*` | 3 | 列表、详情、删除 |
| `/api/v1/admin/chunks/*` | 5 | 列表、统计、按节查、详情、批量删除 |
| `/api/v1/admin/vector/*` | 2 | schema、reset |
| `/api/v1/admin/articles/{article_id}/*` | 2 | vectorize、vector-status |

## 附录 B：本次不做但值得记下来的技术债

1. `created_at` 的假 `Z` 后缀 —— 应改真 UTC，但涉及前端解析。
2. `likes` 表缺唯一索引 —— 并发下会重复点赞，应加 `(article_id, user_id)` 唯一约束。
3. `categorys` 拼写错误 —— 改名要动 SQL 与前端枚举，收益低。
4. 浏览量用 `UPDATE` 自增，热点文章行锁竞争 —— 可改 Redis 计数异步落库。
