# 01 认证模块 · 设计方案

## 1. 职责与边界

**做什么**

- 账号注册（账号 + 密码 + 昵称）
- 账号密码登录（带图形验证码）
- 邮箱验证码登录
- 图形验证码生成
- 邮箱验证码发送（登录 / 重置密码 / 重置邮箱 / 添加邮箱四种用途）
- 双 Token 签发、刷新、登出
- 昵称 / 账号唯一性检测

**不做什么**

- 不管用户资料修改（头像、简介 → 02-user）
- 不管权限业务判断（只在 token 里带 `role_id`，具体校验由各模块的依赖完成）

---

## 2. 目录结构

```
app/
├── api/v1/auth.py                    # AuthController：路由 + 参数绑定
├── services/auth/
│   ├── auth_service.py               # AuthService：业务编排
│   ├── auth_cache.py                 # AuthCache：Redis 读写 + key 规范
│   ├── captcha.py                    # ImageCaptchaGenerator：图形验证码
│   └── mailer.py                     # EmailSender：SMTP 发送
├── repositories/auth_repository.py   # AuthRepository：users 表的认证视角查询
└── schemas/auth.py                   # 请求/响应模型
```

---

## 3. 类设计

### 3.1 `AuthController`

```python
class AuthController:
    """认证接口控制器。

    只做三件事：解析请求 → 调 service → 包响应。
    禁止在这里写任何业务判断（哪怕是「两次密码是否一致」也不行，
    那种校验属于业务规则，必须放 service，否则单测绕不开 HTTP 层）。
    """

    def __init__(self, service: AuthService) -> None:
        self._service = service

    def router(self) -> APIRouter:
        """返回挂载了全部认证路由的 APIRouter。"""

    async def register(self, req: RegisterRequest) -> JSONResponse: ...
    async def login(self, req: LoginRequest) -> JSONResponse: ...
    async def email_login(self, req: EmailLoginRequest) -> JSONResponse: ...
    async def send_image_captcha(self) -> JSONResponse: ...
    async def send_email_captcha(self, req: SendEmailCaptchaRequest) -> JSONResponse: ...
    async def reset_password(self, req: ResetPasswordRequest) -> JSONResponse: ...
    async def logout(self, authorization: str | None) -> JSONResponse: ...
    async def refresh(self, authorization: str | None) -> JSONResponse: ...
    async def is_exists_name(self, user_name: str) -> JSONResponse: ...
    async def is_exists_account(self, account: str) -> JSONResponse: ...
```

### 3.2 `AuthService`

```python
class AuthService:
    """认证业务的核心编排类。

    依赖全部通过构造函数注入，方便单测替换（塞内存版 cache、假 mailer）。
    """

    def __init__(
        self,
        repo: AuthRepository,
        cache: AuthCache,
        captcha: ImageCaptchaGenerator,
        mailer: EmailSender,
        hasher: PasswordHasher,
        jwt: JWTManager,
        settings: Settings,
    ) -> None:
        self._repo = repo
        self._cache = cache
        self._captcha = captcha
        self._mailer = mailer
        self._hasher = hasher
        self._jwt = jwt
        self._settings = settings

    async def register(self, req: RegisterRequest) -> None:
        """注册新用户。

        校验顺序（顺序不能变，否则错误提示会互相掩盖）：
          1. 账号格式：11 位纯数字
          2. 密码格式：11-20 位，只允许字母数字，且必须同时含字母和数字
          3. 两次密码一致
          4. 昵称唯一（1-15 字符）
          5. 账号唯一
        密码入库前 bcrypt(cost=12)。

        Raises:
            BizError: 格式不符(400) / 昵称已存在(409) / 账号已存在(409)。
        """

    async def login(self, req: LoginRequest) -> LoginResponse:
        """账号密码登录。

        校验图形验证码 → 查账号 → 判状态 → 验密码 → 签发双 Token。
        """

    async def email_login(self, req: EmailLoginRequest) -> LoginResponse:
        """邮箱验证码登录。验证码校验通过后直接签发 Token，不用密码。"""

    async def send_image_captcha(self) -> ImageCaptchaResponse:
        """生成图形验证码并写入 Redis（TTL 300 秒）。

        Returns:
            ImageCaptchaResponse: captcha_id（同时也是 Redis key 的一部分）
            与 base_64（带 data:image/png;base64, 前缀的完整 data URI）。
        """

    async def send_email_captcha(self, req: SendEmailCaptchaRequest) -> None:
        """发送邮箱验证码。

        顺序很关键：**先写缓存，再判频率，最后发信**。
        发信失败要回滚频率限制（删掉 limit key），否则用户要干等 60 秒才能重试。
        """

    async def reset_password(self, req: ResetPasswordRequest) -> None:
        """邮箱验证码重置密码。成功后不清理 sessions —— 旧 token 到期自然失效。"""

    async def refresh(self, access_token: str) -> RefreshTokenResponse:
        """用（可能已过期的）access token 换新 token 对。

        这里必须用 verify_exp=False 解析，否则 access token 一过期就换不了新 token，
        双 Token 机制失去意义。
        """

    async def logout(self, access_token: str) -> None:
        """登出。仅当 token 里的 tid 仍是当前活跃会话时才删 Redis key。

        否则会出现：手机端登出，把电脑端的登录也踢掉了。
        """

    async def is_exists_name(self, user_name: str) -> IsExistsResponse: ...
    async def is_exists_account(self, account: str) -> IsExistsResponse: ...
```

### 3.3 `AuthRepository`

```python
class AuthRepository:
    """users 表的认证视角查询。

    说明：02-user 模块也有一个 UserRepository，同样操作 users 表。
    两者不合并是刻意的 —— 认证只关心 account / email / password_hash / status / role_id，
    资料模块关心 avatar / introduction 等。合并会变成一个什么都装的大类。

    Go 版本也是这么分的（repository/auth 与 repository/user）。
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None: ...

    async def find_by_account(self, account: str) -> User | None:
        """按账号查用户，带 deleted_at IS NULL 过滤。"""

    async def find_by_email(self, email: str) -> User | None: ...

    async def exists_name(self, user_name: str) -> bool: ...

    async def exists_account(self, account: str) -> bool: ...

    async def create(self, user: User) -> int:
        """插入用户，返回自增主键（MySQL 不支持 RETURNING，用 flush 后的 obj.id）。"""

    async def update_password(self, user_id: int, password_hash: str) -> None: ...
```

### 3.4 `AuthCache`

```python
class AuthCache:
    """认证相关缓存。

    所有 key 在这里统一拼，禁止业务代码里手写字符串 ——
    否则改一次前缀要全库搜。
    """

    # key 前缀常量，改动会影响存量会话，慎动
    CAPTCHA_IMAGE = "captcha:login:{key}"
    CAPTCHA_EMAIL = "captcha:email:{email}:{purpose}"
    EMAIL_LIMIT = "captcha:limit:{email}"
    REFRESH_TOKEN = "refresh:{user_id}"
    TOKEN_BLACKLIST = "blacklist:token:{token}"

    async def store_image_captcha(self, key: str, answer: str, ttl: int = 300) -> None: ...
    async def get_image_captcha(self, key: str) -> str | None: ...
    async def delete_image_captcha(self, key: str) -> None: ...

    async def store_email_captcha(self, email: str, code: str, purpose: str, ttl: int = 300) -> None: ...
    async def get_email_captcha(self, email: str, purpose: str) -> str | None: ...
    async def delete_email_captcha(self, email: str, purpose: str) -> None: ...

    async def check_send_limit(self, email: str, ttl: int = 60) -> bool:
        """SETNX 原子占位。返回 False 表示 60 秒内已发过。"""

    async def clear_send_limit(self, email: str) -> None: ...

    async def store_refresh_token(self, user_id: int, token: str, ttl: int) -> None: ...
    async def get_refresh_token(self, user_id: int) -> str | None: ...
    async def delete_refresh_token(self, user_id: int) -> None: ...
```

### 3.5 `ImageCaptchaGenerator`

```python
class ImageCaptchaGenerator:
    """图形验证码生成器。

    用 Pillow 手绘，不用第三方验证码库：
    市面库的默认字体尺寸与 base64Captcha 差异太大，前端 <img> 的容器是固定 240x80，
    尺寸一变就变形。这里按原尺寸 240x80、6 位数字、5 个干扰点、干扰线重绘。

    线程池执行：Pillow 是同步 CPU 操作，直接在协程里跑会阻塞事件循环。
    """

    WIDTH = 240
    HEIGHT = 80
    LENGTH = 6

    async def generate(self) -> tuple[str, str]:
        """生成验证码。

        Returns:
            (answer, data_uri) —— answer 是 6 位数字答案，data_uri 是
            `data:image/png;base64,...` 形式的字符串，可直接塞进 <img src>。
        """
```

### 3.6 `EmailSender`

```python
class EmailSender:
    """SMTP 邮件发送。

    QQ 邮箱 587 端口 + STARTTLS。smtplib 是同步阻塞的，
    必须用 anyio.to_thread.run_sync 包一层，否则一个慢邮件能卡住整个 worker。
    """

    def __init__(self, settings: Settings) -> None: ...

    async def send_captcha(self, to_email: str, code: str, purpose: str) -> None:
        """按用途渲染不同标题与正文。

        Raises:
            BizError: SMTP 认证失败 / 连接超时 → 500「发送邮箱验证码失败」。
        """
```

---

## 4. 类关系图

```
AuthController
   └── AuthService
         ├── AuthRepository ── users 表（认证视角）
         ├── AuthCache ─────── Redis
         ├── ImageCaptchaGenerator
         ├── EmailSender ───── SMTP
         ├── PasswordHasher   （来自 00-foundation）
         └── JWTManager       （来自 00-foundation）
```

---

## 5. 数据模型

只涉及 `users` 表的认证相关列（完整表结构见 02-user）：

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | `BIGINT AUTO_INCREMENT` | 主键 |
| `user_name` | `VARCHAR(50) NOT NULL UNIQUE` | 昵称，1-15 字符（列宽留余量） |
| `account` | `VARCHAR(50) NOT NULL UNIQUE` | 账号，11 位数字 |
| `password_hash` | `VARCHAR(255) NOT NULL` | bcrypt，60 字符 |
| `email` | `VARCHAR(50)` | 可空 |
| `status` | `SMALLINT NOT NULL` | 1 启用 / 0 禁用 |
| `role_id` | `SMALLINT NOT NULL DEFAULT 0` | 1 管理员 / 0 普通 |
| `created_at` / `updated_at` / `deleted_at` | `DATETIME` | 见 00-foundation |

> ⚠️ 唯一索引在 `utf8mb4_0900_ai_ci` 下**不区分大小写**：
> `Admin` 与 `admin` 会撞 `user_name` 唯一键。这是行为变化，不是 bug，测试用例要覆盖。

---

## 6. 核心流程

### 6.1 注册

```
POST /auth/register
 → 校验账号 ^[0-9]{11}$
 → 校验密码 11-20 位、纯字母数字、同时含字母与数字
 → password != ack → 400「两次密码不一致」
 → exists_name → 409「该昵称已经存在」
 → exists_account → 409「该账号已经存在」
 → password_hash = bcrypt.hash(password)
 → INSERT users(status=1, role_id=0)
 → 200 {"message":"注册成功"}
```

### 6.2 账号密码登录

```
POST /auth/login
 → get_image_captcha(captcha_key)
     ├─ 不存在 → 400「验证码已过期」
     └─ 不相等 → 400「验证码错误」（比较时忽略大小写，纯数字无所谓）
 → 无论对错，用完即删 key（防重放）
 → find_by_account
     ├─ 不存在 → 404「该账号不存在」
     └─ status=0 → 1004「用户已被禁用」
 → verify(password, hash)
     └─ 失败 → 400「密码错误」
 → generate_auth_tokens()
     ├─ refresh = secrets.token_hex(32)
     ├─ access  = JWT{sub, user_id, username, user_role_id, tid=refresh, exp}
     ├─ Redis: SET refresh:{user_id} = refresh EX 72h   ← 覆盖，实现单设备登录
     └─ 返回 access（refresh 不下发，前端拿不到，只能靠 access 里的 tid 刷新）
```

**为什么 refresh token 不下发给前端？**

因为 access token 的 payload 里就有 `tid`，刷新接口读它即可。refresh 不出现在
响应体里，就不用担心 XSS 偷走长期凭证。这是 Go 版的原始设计，照搬。

### 6.3 刷新 Token

```
POST /auth/refresh   Authorization: Bearer <access，可能已过期>
 → jwt.decode(verify_exp=False)      ← 允许过期，否则刷新不了
 → Redis GET refresh:{user_id}
     ├─ 空 → 401「Refresh Token 已过期，请重新登录」
     └─ != claims.tid → 401「Refresh Token 无效，请重新登录」（旧设备被踢）
 → 生成新 refresh + 新 access（新 tid）
 → Redis 覆盖 refresh:{user_id}，TTL 重置 72h
 → 返回新 access
```

### 6.4 登出

```
POST /auth/logout   Authorization: Bearer <access>
 → 解析 token（失败直接当成功，幂等）
 → Redis GET refresh:{user_id}
 → 仅当 stored == claims.tid 时 DEL refresh:{user_id}
    （否则是旧设备在登出，别误删新会话）
 → 200
```

### 6.5 邮箱验证码

```
POST /auth/captcha
 → 生成 6 位数字
 → Redis SETEX captcha:email:{email}:{purpose} 300 code
 → Redis SETNX captcha:limit:{email} 60
     ├─ 失败（已存在）→ 400「请勿频繁发送验证码，请60秒后再试」
     └─ 成功 → 发邮件
         ├─ 成功 → 200
         └─ 失败 → DEL captcha:limit:{email}（回滚）+ 500
```

---

## 7. Redis Key 规范

| Key | 类型 | TTL | 说明 |
|---|---|---|---|
| `captcha:login:{captcha_key}` | string | 300s | 图形验证码答案 |
| `captcha:email:{email}:{purpose}` | string | 300s | 邮箱验证码，purpose ∈ login / reset_password / reset_email / add_email |
| `captcha:limit:{email}` | string | 60s | 发信频率限制，SETNX 占位 |
| `refresh:{user_id}` | string | 72h | 当前会话的 refresh token（单设备） |
| `blacklist:token:{token}` | string | 剩余有效期 | 预留给强制下线用，本轮不写入 |

---

## 8. 错误码

| 场景 | code | message |
|---|---|---|
| 账号格式错误 | 400 | 账号格式错误 |
| 密码格式错误 | 400 | 密码格式错误 |
| 两次密码不一致 | 400 | 两次密码不一致 |
| 昵称已存在 | 409 | 该昵称已经存在 |
| 账号已存在 | 409 | 该账号已经存在 |
| 图形验证码错误/过期 | 400 | 验证码错误 / 验证码已过期 |
| 账号不存在 | 404 | 该账号不存在 |
| 账号被禁用 | 1004 | 用户已被禁用 |
| 密码错误 | 400 | 密码错误 |
| 邮箱验证码错误 | 400 | 验证码错误 |
| 发信过于频繁 | 400 | 请勿频繁发送验证码，请60秒后再试 |
| refresh 过期/无效 | 401 | Refresh Token 已过期，请重新登录 / 无效 |

---

## 9. 测试要点

| # | 用例 | 断言 |
|---|---|---|
| 1 | 注册账号 10 位数字 | 400「账号格式错误」 |
| 2 | 注册密码纯数字 | 400「密码格式错误」 |
| 3 | 注册昵称 `Admin`，已存在 `admin` | 409（大小写不敏感，MySQL ci 排序规则） |
| 4 | 登录不传图形验证码 | 400 |
| 5 | 验证码用第二次 | 400「验证码已过期」（用完即删） |
| 6 | 禁用用户登录 | 1004 |
| 7 | 登录成功后旧 refresh 被覆盖 | 旧 token 刷新 → 401 |
| 8 | access 过期但 refresh 有效 | 刷新成功，返回新 access |
| 9 | 旧设备登出 | 新设备的会话仍在（tid 不匹配不删 key） |
| 10 | 60 秒内连发两次邮箱验证码 | 第二次 400 |
| 11 | SMTP 发送失败 | 频率限制被回滚，可立即重试 |
| 12 | bcrypt 哈希格式 | 以 `$2b$` 开头，每次哈希不同 |

---

## 10. 开放问题

1. **`blacklist:token` 未使用**：Go 版预留了但没写入。本轮是否实现「强制下线」？
   建议不做，登出靠删 refresh key 已经够。
2. **图形验证码存 Redis**：`redis_enabled=false` 时降级到进程内存，多 worker 下不共享。
   本地调试可接受，生产必须开 Redis。
3. **登录失败次数限制**：Go 版没有。是否要加（防撞库）？建议后续迭代，不进本轮。
