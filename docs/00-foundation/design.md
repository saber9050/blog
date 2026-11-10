# 00 基础设施 · 设计方案

## 1. 职责与边界

**做什么**

- 应用装配：`create_app()` 工厂、`lifespan` 启动/关闭钩子
- 配置加载：`configs/config.yaml` → 强类型 `Settings` 对象
- 数据库：async engine、session 工厂、声明式基类、时间戳与软删除 Mixin
- 连接池：Redis、MinIO 客户端的生命周期管理
- 日志：loguru 配置（控制台 + 文件轮转）
- 统一响应与错误码体系
- 鉴权依赖：`get_current_user`、`require_admin`
- 全局中间件：请求日志、异常兜底、CORS

**不做什么**

- 不写任何业务逻辑（注册、发文章都不在这里）
- 不碰表结构定义（模型在各业务模块，这里只提供基类）

---

## 2. 目录结构

```
configs/
├── config.yaml                 # 真实配置（不入库）
└── config.yaml.example         # 模板（入库）

app/
├── main.py                     # 唯一入口：create_app() + uvicorn 目标
├── core/
│   ├── config.py               # Settings + 各配置分组
│   ├── logging.py              # LoggingConfigurator
│   ├── errors.py               # ErrorCode + BizError
│   ├── response.py             # ApiResponse + ResponseBuilder
│   ├── security.py             # PasswordHasher + JWTManager + CryptoBox
│   ├── protocols.py            # 跨模块契约（Protocol）
│   ├── timefmt.py              # 三种时间格式
│   └── deps.py                 # FastAPI 依赖：db / redis / storage / current_user
├── db/
│   ├── database.py             # Database 类：engine + sessionmaker
│   └── base.py                 # Base / TimestampMixin / SoftDeleteMixin
├── integrations/
│   ├── redis_client.py         # RedisClient + InMemoryCache
│   └── minio_storage.py        # MinioStorage 封装
├── middleware/
│   ├── request_log.py
│   └── exception.py
└── api/
    └── v1/
        └── health.py           # GET /api/v1/health
```

---

## 3. 类设计

### 3.1 配置：`Settings`

配置文件是 `configs/config.yaml`，**YAML 分组结构，与 Go 版的 `config.yaml` 对齐**。
不再保留 `.env` —— 双份配置就是双份真相，Go 项目已经踩过「两边密码不一致」的坑。

```python
class MySQLSection(BaseModel):
    host: str = "127.0.0.1"
    port: int = 3306
    user: str = "root"
    password: SecretStr = SecretStr("")
    database: str = "blog-project"
    pool_size: int = 10
    max_overflow: int = 20
    echo: bool = False

class JWTSection(BaseModel):
    secret: SecretStr = SecretStr("change-me")
    access_expire_minutes: int = 15
    refresh_expire_hours: int = 72

# ... MinioSection / SmtpSection / AdminSection / LogSection / BusinessSection

class Settings(BaseSettings):
    """配置根对象。字段名与 config.yaml 的顶层键一一对应。"""

    model_config = SettingsConfigDict(
        yaml_file=str(CONFIG_FILE),          # configs/config.yaml
        env_nested_delimiter="__",           # DATABASE__MYSQL__PASSWORD
        extra="ignore",
    )

    app: AppSection = Field(default_factory=AppSection)
    database: DatabaseSection = Field(default_factory=DatabaseSection)
    jwt: JWTSection = Field(default_factory=JWTSection)
    security: SecuritySection = Field(default_factory=SecuritySection)
    minio: MinioSection = Field(default_factory=MinioSection)
    smtp: SmtpSection = Field(default_factory=SmtpSection)
    admin: AdminSection = Field(default_factory=AdminSection)
    log: LogSection = Field(default_factory=LogSection)
    business: BusinessSection = Field(default_factory=BusinessSection)

    @classmethod
    def settings_customise_sources(cls, ...):
        """优先级：显式传参 > 环境变量 > YAML > 默认值。

        ⚠️ 这个方法必须显式写：pydantic-settings 默认**不认 YAML**，
        只声明 `yaml_file` 会静默使用默认值，不报错。
        典型症状是「改了 config.yaml 但程序没反应」。
        """

    @computed_field
    @property
    def database_url(self) -> str:
        """拼 asyncmy 连接串。密码做 URL 编码，否则 @ 和 / 会截断 URL。"""
```

YAML 结构（`configs/config.yaml`）：

```yaml
app:
  name: "blog-project"
  mode: "debug"          # debug / release
  host: "127.0.0.1"
  port: 8000

database:
  mysql:
    host: "127.0.0.1"
    port: 3306
    user: "root"
    password: ""
    database: "blog-project"
    pool_size: 10
    max_overflow: 20
    echo: false
  redis:
    enabled: false       # false 时降级为进程内缓存
    host: "127.0.0.1"
    port: 6379
    password: ""
    db: 0

jwt:
  secret: ""
  access_expire_minutes: 15
  refresh_expire_hours: 72

security:
  fernet_key: ""         # 留空则模型 api_key 明文存储（仅本地调试）

minio: { endpoint: "127.0.0.1:9000", bucket: "blog-v2", public_url: "http://127.0.0.1:9000" }
smtp:  { host: "smtp.qq.com", port: 587, username: "", password: "" }
admin: { enabled: true, account: "00000000000", password: "admin123456" }
log:   { level: "INFO", dir: "logs", rotation: "50 MB", retention: "7 days" }

business:
  image_max_bytes: 10485760
  allowed_image_exts: [".jpg", ".jpeg", ".png", ".webp"]
  captcha_length: 6
  captcha_expire_seconds: 300
  captcha_send_limit_seconds: 60
  max_page_size: 100
```

| 类 | 职责 | 说明 |
|---|---|---|
| `Settings` | 配置根对象 | 单例，`get_settings()` 带 `lru_cache` |
| `*Section` | 各配置分组 | 每个分组一个 `BaseModel`，职责单一 |
| `Database` | 持有 engine 与 sessionmaker | 见 3.2 |

**覆盖规则**：容器部署时敏感项用环境变量注入，避免写进镜像层：

```bash
DATABASE__MYSQL__PASSWORD=xxx
JWT__SECRET=xxx
SECURITY__FERNET_KEY=xxx
```

`configs/config.yaml` 不入库（`.gitignore` 已排除），只提交 `config.yaml.example`。

### 3.2 数据库：`Database`

```python
class Database:
    """异步数据库句柄，负责 engine 的创建与释放。

    不继承任何框架基类：这个类唯一的职责是「给我一个 session」。
    """

    def __init__(self, settings: Settings) -> None:
        self._engine = create_async_engine(
            settings.database_url,
            pool_size=settings.mysql_pool_size,
            max_overflow=settings.mysql_max_overflow,
            # MySQL 的 wait_timeout 默认 8 小时，池里的死连接会导致
            # 偶发 "MySQL server has gone away"，必须主动回收。
            pool_recycle=3600,
            pool_pre_ping=True,
            # MySQL 默认 REPEATABLE READ，与旧 Go 版（PG 的 READ COMMITTED）行为不一致，
            # 显式降级，避免长事务里读到旧快照。
            isolation_level="READ COMMITTED",
            echo=False,
            connect_args={"init_command": "SET time_zone='+08:00'"},
        )
        self._session_factory = async_sessionmaker(
            self._engine, expire_on_commit=False, class_=AsyncSession
        )

    def session(self) -> AsyncSession:
        """返回一个新 session。调用方负责关闭（走 FastAPI 依赖自动处理）。"""

    async def dispose(self) -> None:
        """关闭连接池。在 lifespan 的 shutdown 阶段调用。"""
```

### 3.3 声明式基类与 Mixin

```python
class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""

class TimestampMixin:
    """主键与时间戳。

    created_at / updated_at 由数据库生成（server_default），不经 Python，
    避免应用与库的时区设置不一致导致时间漂移。
    """
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

class SoftDeleteMixin:
    """软删除标记。

    ⚠️ SQLAlchemy 不像 GORM 会自动给查询加 deleted_at IS NULL，
    所有查询必须显式调用 not_deleted()，否则已删数据会「复活」。
    """
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

def not_deleted(model: type[Base]) -> ColumnElement[bool]:
    """生成软删除过滤条件。

    Args:
        model: 带 SoftDeleteMixin 的模型类。

    Returns:
        SQLAlchemy 布尔表达式，可直接放进 .where()。
    """
    return model.deleted_at.is_(None)
```

### 3.4 统一响应：`ApiResponse` + `ResponseBuilder`

```python
class ApiResponse(BaseModel, Generic[T]):
    """统一响应外壳。

    契约与 Go 版本一致：data 为空时不输出该字段（对应 omitempty），
    由 ResponseBuilder 在序列化时用 exclude_none 处理。
    """
    code: int = 0
    message: str = "成功"
    data: T | None = None

class ResponseBuilder:
    """把响应对象转成 JSONResponse。

    所有 controller 必须通过它返回，禁止直接 return dict ——
    否则少一个 code 字段前端就整页报错。
    """

    @staticmethod
    def ok(data: Any = None, message: str = "成功") -> JSONResponse: ...

    @staticmethod
    def fail(error: BizError) -> JSONResponse: ...
```

### 3.5 错误体系：`ErrorCode` + `BizError`

```python
class ErrorCode(IntEnum):
    """业务错误码。数值照抄 Go 版本的 pkg/errors，前端按 code 判断逻辑，不能改。"""
    SUCCESS = 0
    BAD_REQUEST = 400
    UNAUTHORIZED = 401
    ...

class BizError(Exception):
    """业务异常。service 层抛它，全局异常处理器统一转成 HTTP 响应。

    继承 Exception 而不是返回错误元组：Python 没有 Go 的 error 返回值，
    异常是唯一能让调用链自然中断的方式。
    """

    def __init__(self, code: ErrorCode, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)

    @property
    def http_status(self) -> int:
        """业务码 → HTTP 状态码。

        4xx/5xx 直接用码值；1xxx-3xxx 的业务码统一映射 400（与 Go 版一致）。
        """
```

### 3.6 安全：`PasswordHasher` / `JWTManager` / `CryptoBox`

```python
class PasswordHasher:
    """bcrypt 密码哈希。

    直接用 bcrypt 原生库，不用 passlib：
    passlib 1.7.4 读取 bcrypt 4.x 的 __about__ 会抛 AttributeError。
    """

    def __init__(self, rounds: int = 12) -> None: ...

    def hash(self, plain: str) -> str:
        """返回 $2b$12$... 格式的哈希。"""

    def verify(self, plain: str, hashed: str) -> bool:
        """校验密码。bcrypt 只取前 72 字节，超长密码会被静默截断，这里先主动拒绝。"""

class JWTManager:
    """双 Token 签发与解析。

    设计要点（照抄 Go 版）：
      - access token 里带 tid 字段，值等于 refresh token
      - refresh token 本身不是 JWT，是随机 hex 串，存 Redis（单设备登录）
      - 刷新时比对 Redis 中的值与 token 里的 tid，一致才发新的
    """

    def __init__(self, secret: str, access_expire_minutes: int) -> None: ...

    def create_access_token(self, user_id: int, username: str, role_id: int, tid: str) -> str: ...

    def decode(self, token: str, *, verify_exp: bool = True) -> TokenClaims:
        """解析 token。刷新接口传 verify_exp=False，允许读过期 token 的 claims。"""

    @staticmethod
    def generate_refresh_token() -> str:
        """32 字节随机 hex，同时充当会话标识。"""

class CryptoBox:
    """对称加解密，用于保管第三方密钥（目前只有模型的 api_key）。

    用 cryptography 的 Fernet（AES-128-CBC + HMAC），不手搓 AES：
    Fernet 自带完整性校验，密文被改过会直接抛 InvalidToken 而不是解密出垃圾。

    密钥从 config.yaml 的 `security.fernet_key` 读，**不要复用 jwt.secret**：
    换 JWT 密钥不该导致所有模型配置作废。
    """

    def __init__(self, key: str) -> None: ...

    def encrypt(self, plain: str) -> str:
        """返回 base64 文本，可直接存 VARCHAR 列。"""

    def decrypt(self, cipher: str) -> str:
        """解密。

        Raises:
            InvalidToken: 密钥换过或密文损坏。调用方要把它转成
            「请重新填写模型密钥」，而不是 500 堆栈。
        """
```

### 3.7 协议（跨模块契约）

```python
# app/core/protocols.py
class SupportsCache(Protocol):
    """Redis 缓存能力的最小契约。

    auth 模块只依赖这几个方法，不依赖具体的 RedisClient 类 ——
    这样单测可以塞一个内存实现，不需要起 Redis。
    """
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ttl_seconds: int) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def set_if_absent(self, key: str, value: str, ttl_seconds: int) -> bool: ...

class SupportsFileStorage(Protocol):
    """对象存储能力的最小契约。"""
    async def upload(self, object_name: str, data: bytes, content_type: str) -> str: ...
    async def delete(self, object_name: str) -> None: ...
    def public_url(self, object_name: str) -> str: ...
```

### 3.8 鉴权依赖：`deps.py`

```python
async def get_db(...) -> AsyncGenerator[AsyncSession, None]:
    """每请求一个 session，请求结束自动关闭。

    不在这里 commit：事务边界由 service 层用 `async with session.begin()` 控制，
    否则「上传成功但写库失败」这种场景会留下脏数据。
    """

async def get_current_user(...) -> CurrentUser:
    """从 Authorization: Bearer 解析当前用户，失败抛 401。

    只解 token 不查库：access token 有效期 15 分钟，
    每次请求都查一次 users 表等于自找瓶颈。
    """

async def require_admin(...) -> CurrentUser:
    """要求 role_id == 1，否则 403。"""
```

### 3.9 应用工厂

```python
class ApplicationFactory:
    """装配应用：注册中间件、异常处理器、路由、生命周期钩子。"""

    def __init__(self, settings: Settings) -> None: ...

    def create(self) -> FastAPI:
        """构建 FastAPI 实例。

        lifespan 里做三件事：
          1. 校验 MySQL / Redis / MinIO 连通性（失败打 error 但仍启动，对应 Go 版「降级不阻断」）
          2. 建表（仅 debug 模式；生产走 alembic upgrade）
          3. 确保默认管理员存在
        """
```

---

## 4. 类关系图

```
ApplicationFactory
 ├── Settings
 ├── Database ──── AsyncEngine / async_sessionmaker
 ├── LoggingConfigurator
 └── FastAPI app
      ├── middleware: RequestLogMiddleware, ExceptionMiddleware, CORSMiddleware
      ├── exception_handlers: BizError → ResponseBuilder.fail
      └── routers:
            health_router
            (后续模块注入)

deps.py
 ├── get_db()        → AsyncSession
 ├── get_redis()     → SupportsCache
 ├── get_storage()   → SupportsFileStorage
 ├── get_current_user() → CurrentUser
 └── require_admin()   → CurrentUser
```

---

## 5. 核心流程

### 5.1 应用启动

```
uvicorn app.main:app
  → create_app()
      → Settings()               # config.yaml 缺失/格式错误直接抛异常，不启动
      → LoggingConfigurator.setup()
      → Database(settings)
      → RedisClient(settings)    # 连不上只 warn，不停机
      → MinioStorage(settings)   # bucket 不存在则创建
      → ApplicationFactory.create()
          → 注册中间件（顺序：CORS → RequestLog → Exception）
          → 注册异常处理器
          → 挂载路由
  → lifespan.startup
      → ping MySQL（30s 超时）
      → ensure_admin()
```

### 5.2 请求生命周期

```
请求 → CORS → RequestLog（记录 method/path/耗时/status）
     → 路由 → 依赖注入（get_db / get_current_user）
     → Controller → Service → Repository
     → ResponseBuilder.ok() → JSONResponse
异常 → ExceptionMiddleware 捕获 BizError → ResponseBuilder.fail()
     → 未预期异常 → 日志打完整堆栈，对外只返回 500「服务器内部错误」
```

### 5.3 异常处理约定

| 异常类型 | 处理方式 | 对外 |
|---|---|---|
| `BizError` | 按 code 映射状态码 | `{code, message}` |
| `RequestValidationError` | 转成 400 + 中文提示 | `{code: 400, message: "请求参数错误"}` |
| 其他 `Exception` | `logger.exception()` 打全栈 | `{code: 500, message: "服务器内部错误"}` |

**绝不把堆栈或 SQL 语句返给前端**，与 Go 版一致。

---

## 6. 错误码表

| 码 | 常量 | HTTP | 含义 |
|---|---|---|---|
| 0 | SUCCESS | 200 | 成功 |
| 400 | BAD_REQUEST | 400 | 请求参数错误 |
| 401 | UNAUTHORIZED | 401 | 未授权 |
| 403 | FORBIDDEN | 403 | 禁止访问 |
| 404 | NOT_FOUND | 404 | 资源不存在 |
| 409 | CONFLICT | 409 | 资源冲突 |
| 429 | TOO_MANY_REQUESTS | 429 | 请求过于频繁 |
| 500 | INTERNAL_ERROR | 500 | 服务器内部错误 |
| 1001 | USER_NOT_FOUND | 400 | 用户不存在 |
| 1002 | USER_ALREADY_EXISTS | 400 | 用户已存在 |
| 1003 | INVALID_CREDENTIALS | 400 | 用户名或密码错误 |
| 1004 | USER_DISABLED | 400 | 用户已被禁用 |
| 1005 | INVALID_TOKEN | 400 | 无效的令牌 |
| 1006 | TOKEN_EXPIRED | 400 | 令牌已过期 |
| 1007 | WRONG_PASSWORD | 400 | 密码错误 |
| 1008 | TOKEN_NOT_EXPIRED | 400 | 令牌尚未过期 |
| 1009 | LOGIN_LIMIT_REACHED | 400 | 登录人数已达上限 |
| 2001 | INVALID_PARAM | 400 | 参数错误 |
| 2002 | MISSING_PARAM | 400 | 缺少必要参数 |
| 2003 | PARAM_FORMAT_ERROR | 400 | 参数格式错误 |
| 3001 | RESOURCE_NOT_FOUND | 400 | 资源不存在 |
| 3002 | RESOURCE_ALREADY_EXISTS | 400 | 资源已存在 |
| 3003 | RESOURCE_LOCKED | 400 | 资源已被锁定 |

---

## 7. 测试要点

| 用例 | 断言 |
|---|---|
| `config.yaml` 的 `jwt.secret` 缺失 | `Settings()` 抛 ValidationError，应用不启动 |
| 响应序列化 | `data=None` 时 JSON 里没有 `data` 键 |
| 业务码映射 | `BizError(ErrorCode.USER_NOT_FOUND)` → HTTP 400 + `code=1001` |
| 未捕获异常 | 返回 500，**响应体里不含堆栈** |
| 软删除过滤 | 插入带 `deleted_at` 的记录，列表查询查不到 |
| MySQL 断连 | 应用仍能启动，health 返回 degraded |
| 时间格式 | `format_time()` 输出 `2026-11-09T21:39:04Z` |

---

## 8. 开放问题

1. `redis_enabled=false` 时验证码降级到进程内存 —— 多 worker 下不共享，仅用于本地调试。
   是否接受？（建议接受，生产强制开 Redis）
2. 请求日志是否要记录请求体？含密码的接口必须脱敏，建议默认不记 body。
3. `pool_size` 与 worker 数的乘积要小于 MySQL `max_connections`（默认 151）。
   2 worker × 30 = 60，安全；若将来加到 4 worker 要同步调 `max_connections`。
